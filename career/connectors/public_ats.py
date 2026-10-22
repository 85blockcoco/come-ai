"""Bounded read-only adapters for documented public ATS job postings.

No employer identifiers are embedded here. Callers must provide a verified
source record. Adapters only construct fixed-vendor HTTPS endpoints, use
bounded pagination and return source facts without inferring missing fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
import heapq
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Protocol

from ..discovery import DiscoveryPayload, PublicSourceError, _location_parts, source_html_to_text
from ..countries import (
    canonicalize_country,
    country_from_location,
    geo_filter,
    resolve_published_country,
)
from ..exploration import EXPLORATION_MAX_RESULTS, criteria_admit, ranking_key, classify_internship
from ..offer_qualification import qualify_offer
from ..scoring import classify_job_family
from ..stage_search import default_brief, score_brief_match, validate_brief
from ..models import clean_text


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_PAGES = 4
PAGE_SIZE = 100
MAX_ROWS = 400
TIMEOUT_SECONDS = 8
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_USER_AGENT = "Come-AI-Career/3.2 (local reader of published public job postings)"
_LISTING_HOSTS = {
    "lever": frozenset({"jobs.lever.co", "jobs.eu.lever.co"}),
    "ashby": frozenset({"jobs.ashbyhq.com"}),
    "smartrecruiters": frozenset({"www.smartrecruiters.com", "careers.smartrecruiters.com", "api.smartrecruiters.com"}),
}


class JsonTransport(Protocol):
    def get_json(self, endpoint: str, timeout_seconds: int) -> Any: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        _ = (req, fp, code, msg, headers, newurl)
        return None


class UrllibPublicATSTransport:
    """HTTPS JSON GET transport with fixed host allow-list and size/time bounds."""

    HOSTS = frozenset({"api.lever.co", "api.eu.lever.co", "api.ashbyhq.com", "api.smartrecruiters.com"})

    def __init__(self) -> None:
        context = ssl.create_default_context()
        try:
            import certifi  # noqa: PLC0415
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        self._opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def get_json(self, endpoint: str, timeout_seconds: int) -> Any:
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != "https" or parsed.hostname not in self.HOSTS or parsed.username or parsed.password:
            raise PublicSourceError("URL de connecteur public invalide.", code="invalid_source")
        request = urllib.request.Request(endpoint, method="GET", headers={
            "Accept": "application/json", "User-Agent": _USER_AGENT,
        })
        try:
            with self._opener.open(request, timeout=max(1, min(TIMEOUT_SECONDS, int(timeout_seconds)))) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            code = str(error.code)
            raise PublicSourceError(f"La source ATS a renvoyé une erreur ({code}).",
                                    retryable=error.code in {429, 500, 502, 503, 504}, code=code) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise PublicSourceError("La source ATS ne répond pas dans le délai prévu.",
                                    retryable=True, code="timeout") from error
        if len(body) > MAX_RESPONSE_BYTES:
            raise PublicSourceError("La réponse ATS dépasse la taille maximale autorisée.", code="oversize")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PublicSourceError("La source ATS n’a pas renvoyé un JSON valide.", code="invalid_json") from error


class PublicATSConnector:
    provider = ""
    api_host = ""
    enabled_by_default = False
    documentation_url = ""
    doc_verified = True
    listing_hosts: frozenset[str] = frozenset()

    def __init__(self, *, transport: JsonTransport | None = None, enabled: bool = False,
                 clock: Callable[[], str] | None = None, monotonic: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep,
                 max_pages: int = MAX_PAGES, page_size: int = PAGE_SIZE,
                 max_results: int = EXPLORATION_MAX_RESULTS) -> None:
        self.transport = transport or UrllibPublicATSTransport()
        self.enabled = bool(enabled)
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.max_pages = max(1, min(MAX_PAGES, int(max_pages)))
        self.page_size = max(1, min(PAGE_SIZE, int(page_size)))
        self.max_results = max(1, min(EXPLORATION_MAX_RESULTS, int(max_results)))
        self._last_request_at = 0.0
        self._last_metrics: dict[str, Any] = {
            "raw_count": 0,
            "filtered_count": 0,
            "excluded_count": 0,
            "country_excluded_count": 0,
            "excluded_by_country": {},
        }
        self._last_error: str | None = None

    @staticmethod
    def _identifier(source: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = clean_text(source.get(key), limit=100)
            if value:
                if not _IDENTIFIER.fullmatch(value):
                    raise PublicSourceError("L’identifiant ATS de cette source est invalide.", code="invalid_source")
                return value
        raise PublicSourceError("L’identifiant ATS de cette source manque.", code="invalid_source")

    def _request(self, endpoint: str, *, deadline: float | None) -> Any:
        now = self.monotonic()
        if deadline is not None and now >= deadline:
            raise PublicSourceError("Le budget de recherche est atteint.", code="budget")
        # Stay deliberately gentle even when multiple pages are requested.
        delay = 0.25 - (now - self._last_request_at)
        if self._last_request_at and delay > 0:
            if deadline is not None and self.monotonic() + delay >= deadline:
                raise PublicSourceError("Le budget de recherche est atteint.", code="budget")
            self.sleeper(delay)
        remaining = deadline - self.monotonic() if deadline is not None else TIMEOUT_SECONDS
        if remaining <= 0:
            raise PublicSourceError("Le budget de recherche est atteint.", code="budget")
        self._last_request_at = self.monotonic()
        return self.transport.get_json(endpoint, max(1, min(TIMEOUT_SECONDS, int(remaining))))

    def build_endpoint(self, source: dict[str, Any], *, offset: int = 0) -> str:
        raise NotImplementedError

    def parse(self, source: dict[str, Any], payload: Any) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _pages(self, source: dict[str, Any], *, deadline: float | None) -> list[Any]:
        raise NotImplementedError

    def discover_internships(self, source: dict[str, Any], *, selection_brief: dict[str, Any],
                             deadline: float | None = None,
                             countries_exclude: list[str] | tuple[str, ...] | None = None,
                             countries_include: list[str] | tuple[str, ...] | None = None) -> DiscoveryPayload:
        if not self.enabled:
            raise PublicSourceError("Ce connecteur est désactivé par défaut.", code="connector_disabled")
        if not isinstance(source, dict) or source.get("provider") != self.provider:
            raise PublicSourceError("La source ne correspond pas au connecteur demandé.", code="invalid_source")
        provenance = urllib.parse.urlsplit(clean_text(source.get("provenance_url"), limit=2_000))
        if (not clean_text(source.get("id"), limit=160) or not clean_text(source.get("company"), limit=240)
                or not clean_text(source.get("verified_at"), limit=80)
                or provenance.scheme != "https" or not provenance.hostname):
            raise PublicSourceError("Une source officielle vérifiée est requise avant toute consultation.",
                                    code="unverified_source")
        brief = validate_brief(selection_brief) if selection_brief else default_brief()
        geo = geo_filter(countries_exclude, countries_include, brief)
        excluded_by_country: dict[str, int] = {}
        pages = self._pages(source, deadline=deadline)
        raw_count = evaluated = invalid = confirmed = uncertain = excluded = relevant = filtered = 0
        country_excluded = 0
        ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for page in pages:
            items = self._raw_items(page)
            raw_count += len(items)
            if raw_count > MAX_ROWS:
                raise PublicSourceError("Le flux dépasse la limite d’offres évaluées.", code="too_many_rows")
            for raw in items:
                if not isinstance(raw, dict):
                    invalid += 1
                    continue
                # The country is read on the raw row, before the offer is
                # normalized: an excluded country costs no description
                # parsing, no qualification and no local record.
                explicit_country, location = self._country_of_raw(raw)
                country_canonical, excluded_code = resolve_published_country(
                    explicit_country, location, geo
                )
                if excluded_code:
                    country_excluded += 1
                    excluded += 1
                    evaluated += 1
                    excluded_by_country[excluded_code] = (
                        excluded_by_country.get(excluded_code, 0) + 1
                    )
                    continue
                try:
                    job = self._normalise_one(source, raw)
                except (KeyError, TypeError, ValueError):
                    invalid += 1
                    continue
                evaluated += 1
                classification = classify_internship(job)
                qualification = qualify_offer(
                    job,
                    allowed_contract_types=brief.get("contract_types"),
                    allowed_start_months=brief.get("start_months"),
                    minimum_stage_duration_months=brief.get("minimum_stage_duration_months", 6),
                    excluded_countries=brief.get("excluded_countries"),
                    excluded_cities=brief.get("excluded_cities"),
                    require_known_location=brief.get("require_known_location", False),
                ).to_dict()
                job["qualification"] = qualification
                target = qualification["target_status"]
                confirmed += int(target == "conforming")
                uncertain += int(target == "to_verify")
                excluded += int(target == "non_conforming")
                if target == "non_conforming":
                    continue
                if (not job.get("official_url") or
                        (qualification["contract_type"] == "unknown" and not classification.get("evidence"))):
                    filtered += 1
                    continue
                match = score_brief_match(brief, job)
                if not criteria_admit(match, job, brief):
                    filtered += 1
                    continue
                relevant += 1
                job["internship_classification"] = classification
                ranked.append((ranking_key(job, match), {"job": job, "match": match}))
        selected = heapq.nsmallest(self.max_results, ranked, key=lambda item: item[0])
        self._last_metrics = {
            "raw_count": raw_count,
            "filtered_count": invalid + filtered,
            "excluded_count": excluded,
            "country_excluded_count": country_excluded,
            "excluded_by_country": excluded_by_country,
        }
        return DiscoveryPayload(
            jobs=tuple(item[1]["job"] for item in selected), verified_at=self.clock(),
            truncated=relevant > self.max_results, raw_count=raw_count,
            evaluated_count=evaluated, invalid_count=invalid, confirmed_count=confirmed,
            uncertain_count=uncertain, excluded_count=excluded, relevant_count=relevant,
            filtered_criteria_count=filtered,
            country_excluded_count=country_excluded,
            excluded_by_country=excluded_by_country,
        )

    def health_check(self) -> dict[str, Any]:
        """Factual counters of the last read; no offer is ever invented here."""
        metrics = self._last_metrics
        return {
            "provider": self.provider,
            "last_error": self._last_error,
            "raw_count": int(metrics.get("raw_count", 0)),
            "filtered_count": int(metrics.get("filtered_count", 0)),
            "excluded_count": int(metrics.get("excluded_count", 0)),
            "country_excluded_count": int(metrics.get("country_excluded_count", 0)),
            "excluded_by_country": dict(metrics.get("excluded_by_country", {})),
        }

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _country_of_raw(self, raw: dict[str, Any]) -> tuple[Any, Any]:
        """The country fields this vendor publishes, read on the raw row.

        The answer is the pair ``(explicit country, location)``: the explicit
        country is a published field when the vendor has one, and the
        location is the prose the source writes.  The default is an unknown
        country: an offer whose country cannot be read is never turned into
        a geography, and never dropped because of one.
        """
        return None, None

    def _raw_items(self, payload: Any) -> list[Any]:
        raise NotImplementedError


class LeverConnector(PublicATSConnector):
    """Lever public postings feed (official docs: https://github.com/lever/postings-api)."""
    provider = "lever"
    api_host = "api.lever.co"
    documentation_url = "https://github.com/lever/postings-api"
    listing_hosts = frozenset({"jobs.lever.co", "jobs.eu.lever.co"})

    def build_endpoint(self, source: dict[str, Any], *, offset: int = 0) -> str:
        board = self._identifier(source, "board_token", "site")
        query = urllib.parse.urlencode({"mode": "json", "skip": max(0, offset), "limit": self.page_size})
        return f"https://api.lever.co/v0/postings/{urllib.parse.quote(board, safe='')}?{query}"

    def _pages(self, source: dict[str, Any], *, deadline: float | None) -> list[Any]:
        pages: list[Any] = []
        offset = 0
        for _ in range(self.max_pages):
            page = self._request(self.build_endpoint(source, offset=offset), deadline=deadline)
            if not isinstance(page, list):
                raise PublicSourceError("Le flux Lever a un format inattendu.", code="invalid_payload")
            pages.append(page)
            offset += len(page)
            if len(page) < self.page_size or offset >= MAX_ROWS:
                break
        return pages

    def _raw_items(self, payload: Any) -> list[Any]:
        return payload if isinstance(payload, list) else []

    def parse(self, source: dict[str, Any], payload: Any) -> list[dict[str, Any]]:
        return [self._normalise_one(source, item) for item in self._raw_items(payload) if isinstance(item, dict)]

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        categories = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
        return _common_job(self.provider, source, raw.get("id"), raw.get("text"),
                           raw.get("hostedUrl"), raw.get("applyUrl"), raw.get("descriptionPlain"),
                           categories.get("location"), raw.get("country"), categories.get("commitment"), "")

    def _country_of_raw(self, raw: dict[str, Any]) -> tuple[Any, Any]:
        """Lever publishes the country in ``country`` and the location in
        ``categories.location``; the explicit country wins."""
        categories = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
        return raw.get("country"), categories.get("location")


class AshbyConnector(PublicATSConnector):
    """Ashby public job-board feed (official docs: https://developers.ashbyhq.com/docs/public-job-posting-api)."""
    provider = "ashby"
    api_host = "api.ashbyhq.com"
    documentation_url = "https://developers.ashbyhq.com/docs/public-job-posting-api"
    listing_hosts = frozenset({"jobs.ashbyhq.com"})

    def build_endpoint(self, source: dict[str, Any], *, offset: int = 0) -> str:
        _ = offset
        board = self._identifier(source, "board_token", "job_board_name")
        return f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(board, safe='')}"

    def _pages(self, source: dict[str, Any], *, deadline: float | None) -> list[Any]:
        return [self._request(self.build_endpoint(source), deadline=deadline)]

    def _raw_items(self, payload: Any) -> list[Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise PublicSourceError("Le flux Ashby a un format inattendu.", code="invalid_payload")
        return payload["jobs"]

    def parse(self, source: dict[str, Any], payload: Any) -> list[dict[str, Any]]:
        return [self._normalise_one(source, item) for item in self._raw_items(payload)
                if isinstance(item, dict) and item.get("isListed") is not False]

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        address = raw.get("address") if isinstance(raw.get("address"), dict) else {}
        postal = address.get("postalAddress") if isinstance(address.get("postalAddress"), dict) else {}
        location = postal.get("addressLocality") or raw.get("location")
        country = postal.get("addressCountry")
        job_url = raw.get("jobUrl")
        fallback_id = urllib.parse.urlsplit(str(job_url or "")).path.rstrip("/").rsplit("/", 1)[-1]
        return _common_job(self.provider, source, raw.get("id") or fallback_id, raw.get("title"),
                           job_url, raw.get("applyUrl"), raw.get("descriptionPlain"),
                           location, country, raw.get("employmentType"), raw.get("publishedAt"))

    def _country_of_raw(self, raw: dict[str, Any]) -> tuple[Any, Any]:
        """Ashby publishes the country in ``address.postalAddress.addressCountry``."""
        address = raw.get("address") if isinstance(raw.get("address"), dict) else {}
        postal = address.get("postalAddress") if isinstance(address.get("postalAddress"), dict) else {}
        return postal.get("addressCountry"), postal.get("addressLocality")


class SmartRecruitersConnector(PublicATSConnector):
    """Public postings only (official docs: https://developers.smartrecruiters.com/docs/posting-api)."""
    provider = "smartrecruiters"
    api_host = "api.smartrecruiters.com"
    documentation_url = "https://developers.smartrecruiters.com/docs/posting-api"
    listing_hosts = frozenset({"www.smartrecruiters.com", "careers.smartrecruiters.com", "api.smartrecruiters.com"})

    def build_endpoint(self, source: dict[str, Any], *, offset: int = 0) -> str:
        company = self._identifier(source, "company_identifier", "board_token")
        query = urllib.parse.urlencode({"limit": self.page_size, "offset": max(0, offset), "destination": "PUBLIC"})
        return f"https://api.smartrecruiters.com/v1/companies/{urllib.parse.quote(company, safe='')}/postings?{query}"

    def _pages(self, source: dict[str, Any], *, deadline: float | None) -> list[Any]:
        pages: list[Any] = []
        offset = 0
        for _ in range(self.max_pages):
            page = self._request(self.build_endpoint(source, offset=offset), deadline=deadline)
            if not isinstance(page, dict) or not isinstance(page.get("content"), list):
                raise PublicSourceError("Le flux SmartRecruiters a un format inattendu.", code="invalid_payload")
            pages.append(page)
            rows = len(page["content"])
            offset += rows
            total = page.get("totalFound")
            if rows < self.page_size or (isinstance(total, int) and offset >= total) or offset >= MAX_ROWS:
                break
        return pages

    def _raw_items(self, payload: Any) -> list[Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
            raise PublicSourceError("Le flux SmartRecruiters a un format inattendu.", code="invalid_payload")
        return payload["content"]

    def parse(self, source: dict[str, Any], payload: Any) -> list[dict[str, Any]]:
        return [self._normalise_one(source, item) for item in self._raw_items(payload) if isinstance(item, dict)]

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
        company = raw.get("company") if isinstance(raw.get("company"), dict) else {}
        contract = raw.get("typeOfEmployment") if isinstance(raw.get("typeOfEmployment"), dict) else {}
        # The documented list response's `ref` is an official API detail URL;
        # a human apply link is used when a source supplies one directly.
        official_url = raw.get("applyUrl") or raw.get("ref")
        return _common_job(self.provider, source, raw.get("id"), raw.get("name"), official_url,
                           raw.get("applyUrl"), raw.get("description"), location.get("city"),
                           location.get("country"), contract.get("label"), raw.get("releasedDate"),
                           company_name=company.get("name"))

    def _country_of_raw(self, raw: dict[str, Any]) -> tuple[Any, Any]:
        """SmartRecruiters publishes the country in ``location.country``."""
        location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
        return location.get("country"), location.get("city")


def _canonical_country(country: Any, location: Any) -> str:
    """The canonical country of a normalized posting.

    The explicit country field of the vendor wins; the location prose is
    read on country names only.  An offer whose country cannot be read
    keeps an unknown country: it is shown to the person as *to verify*.
    """
    code = canonicalize_country(country)
    if code:
        return code
    return country_from_location(location)


def _common_job(provider: str, source: dict[str, Any], job_id: Any, title: Any, official_url: Any,
                apply_url: Any, description: Any, location: Any, country: Any,
                employment_type: Any, posted_date: Any, *, company_name: Any = None) -> dict[str, Any]:
    source_id = clean_text(job_id, limit=240)
    title_text = clean_text(title, limit=300)
    url = clean_text(official_url, limit=2_000)
    if not source_id or not title_text:
        raise ValueError("missing identity")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _LISTING_HOSTS[provider] or parsed.username or parsed.password:
        raise ValueError("missing official URL")
    city, country_from_location = _location_parts(location, preserve_multi_locations=True)
    # Normalize remote markup once at the connector boundary so matching,
    # evidence and UI all use the same safe, provenance-preserving text.
    text = source_html_to_text(description)
    contract = clean_text(employment_type, limit=120)
    posted = clean_text(posted_date, limit=80)
    if posted:
        try:
            posted = datetime.fromisoformat(posted.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            # A malformed vendor timestamp is not an application date fact.
            posted = ""
    country_text = clean_text(country or country_from_location, limit=120)
    return {
        "company": clean_text(company_name or source.get("company"), limit=240),
        "title": title_text,
        "source_name": provider,
        "source_id": source_id,
        "official_url": url,
        "apply_url": clean_text(apply_url, limit=2_000),
        "city": city,
        "country": country_text,
        "country_canonical": _canonical_country(country, location),
        "posted_date": posted,
        "deadline_date": "",
        "start_date": "",
        "end_date": "",
        "duration_months": None,
        "source_status": "open",
        "source_verified": True,
        "employment_type": contract,
        "role_level": "",
        "requirements": "",
        "languages_required": "",
        "eligibility_requirement": "",
        "description_original": text,
        "job_family": classify_job_family(title_text, text),
    }
