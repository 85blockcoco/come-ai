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
from ..exploration import EXPLORATION_MAX_RESULTS, admit_offer, ranking_key
from ..scoring import classify_job_family
from ..source_fields import attach_source_material
from ..stage_search import default_brief, validate_brief
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
    # ``jobs.smartrecruiters.com`` is the public career host the Posting API
    # itself publishes as ``postingUrl``/``applyUrl``.
    "smartrecruiters": frozenset({"www.smartrecruiters.com", "careers.smartrecruiters.com",
                                   "jobs.smartrecruiters.com", "api.smartrecruiters.com"}),
}

#: A posting detail read is one request per posting: the number of reads is
#: bounded explicitly instead of following the size of the feed.
MAX_DETAIL_READS = 20


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
                             deadline: float | None = None) -> DiscoveryPayload:
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
        pages = self._pages(source, deadline=deadline)
        raw_count = evaluated = invalid = confirmed = uncertain = excluded = relevant = filtered = 0
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
                try:
                    job = self._normalise_one(source, raw, deadline=deadline)
                except (KeyError, TypeError, ValueError):
                    invalid += 1
                    continue
                evaluated += 1
                # The admission layer decides; the connector only transmits.
                verdict = admit_offer(job, brief)
                target = verdict["target_status"]
                confirmed += int(target == "conforming")
                uncertain += int(target == "to_verify")
                excluded += int(target == "non_conforming")
                if verdict["status"] == "excluded":
                    continue
                if verdict["status"] != "admitted":
                    filtered += 1
                    continue
                relevant += 1
                job = verdict["job"]
                ranked.append((ranking_key(job, verdict["match"]), {"job": job, "match": verdict["match"]}))
        selected = heapq.nsmallest(self.max_results, ranked, key=lambda item: item[0])
        return DiscoveryPayload(
            jobs=tuple(item[1]["job"] for item in selected), verified_at=self.clock(),
            truncated=relevant > self.max_results, raw_count=raw_count,
            evaluated_count=evaluated, invalid_count=invalid, confirmed_count=confirmed,
            uncertain_count=uncertain, excluded_count=excluded, relevant_count=relevant,
            filtered_criteria_count=filtered,
        )

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any], *,
                        deadline: float | None = None) -> dict[str, Any]:
        raise NotImplementedError

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
        return [self._normalise_one(source, item, deadline=None) for item in self._raw_items(payload)
                if isinstance(item, dict)]

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any], *,
                        deadline: float | None = None) -> dict[str, Any]:
        categories = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
        job = _common_job(self.provider, source, raw.get("id"), raw.get("text"),
                           raw.get("hostedUrl"), raw.get("applyUrl"), raw.get("descriptionPlain"),
                           categories.get("location"), raw.get("country"), categories.get("commitment"), "")
        # Every published field is transmitted under its own name; the
        # description itself is transmitted as ``description_original``.
        return attach_source_material(job, self.provider, {
            "id": raw.get("id"),
            "text": raw.get("text"),
            "createdAt": raw.get("createdAt"),
            "updatedAt": raw.get("updatedAt"),
            "hostedUrl": raw.get("hostedUrl"),
            "applyUrl": raw.get("applyUrl"),
            "country": raw.get("country"),
            "workplaceType": raw.get("workplaceType"),
            "categories": categories,
            "openingPlain": raw.get("openingPlain"),
            "additionalPlain": raw.get("additionalPlain"),
            "lists": raw.get("lists"),
        })


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
        return [self._normalise_one(source, item, deadline=None) for item in self._raw_items(payload)
                if isinstance(item, dict) and item.get("isListed") is not False]

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any], *,
                        deadline: float | None = None) -> dict[str, Any]:
        address = raw.get("address") if isinstance(raw.get("address"), dict) else {}
        postal = address.get("postalAddress") if isinstance(address.get("postalAddress"), dict) else {}
        location = postal.get("addressLocality") or raw.get("location")
        country = postal.get("addressCountry")
        job_url = raw.get("jobUrl")
        fallback_id = urllib.parse.urlsplit(str(job_url or "")).path.rstrip("/").rsplit("/", 1)[-1]
        job = _common_job(self.provider, source, raw.get("id") or fallback_id, raw.get("title"),
                           job_url, raw.get("applyUrl"), raw.get("descriptionPlain"),
                           location, country, raw.get("employmentType"), raw.get("publishedAt"))
        return attach_source_material(job, self.provider, {
            "id": raw.get("id"),
            "title": raw.get("title"),
            "publishedAt": raw.get("publishedAt"),
            "employmentType": raw.get("employmentType"),
            "workplaceType": raw.get("workplaceType"),
            "isRemote": raw.get("isRemote"),
            "isListed": raw.get("isListed"),
            "department": raw.get("department"),
            "team": raw.get("team"),
            "secondaryLocations": raw.get("secondaryLocations"),
            "location": raw.get("location"),
            "address": address,
            "jobUrl": raw.get("jobUrl"),
            "applyUrl": raw.get("applyUrl"),
        })


class SmartRecruitersConnector(PublicATSConnector):
    """Public postings only (official docs: https://developers.smartrecruiters.com/docs/posting-api)."""
    provider = "smartrecruiters"
    api_host = "api.smartrecruiters.com"
    documentation_url = "https://developers.smartrecruiters.com/docs/posting-api"
    listing_hosts = frozenset({"www.smartrecruiters.com", "careers.smartrecruiters.com",
                                "jobs.smartrecruiters.com", "api.smartrecruiters.com"})

    def __init__(self, *, transport: JsonTransport | None = None, enabled: bool = False,
                 clock: Callable[[], str] | None = None, monotonic: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep,
                 max_pages: int = MAX_PAGES, page_size: int = PAGE_SIZE,
                 max_results: int = EXPLORATION_MAX_RESULTS,
                 enrich_details: bool = False, max_detail_reads: int = MAX_DETAIL_READS) -> None:
        super().__init__(transport=transport, enabled=enabled, clock=clock, monotonic=monotonic,
                         sleeper=sleeper, max_pages=max_pages, page_size=page_size, max_results=max_results)
        # The list response publishes no job description: the advertisement
        # only exists in the posting detail.  That read is one request per
        # posting, so it stays opt-in and bounded instead of silently
        # multiplying the number of requests made to a public board.
        self.enrich_details = bool(enrich_details)
        self.max_detail_reads = max(0, min(MAX_DETAIL_READS, int(max_detail_reads)))
        self._detail_reads = 0

    def build_endpoint(self, source: dict[str, Any], *, offset: int = 0) -> str:
        company = self._identifier(source, "company_identifier", "board_token")
        query = urllib.parse.urlencode({"limit": self.page_size, "offset": max(0, offset), "destination": "PUBLIC"})
        return f"https://api.smartrecruiters.com/v1/companies/{urllib.parse.quote(company, safe='')}/postings?{query}"

    def build_detail_endpoint(self, source: dict[str, Any], posting_id: str) -> str:
        """Official detail endpoint of one posting of the same company."""
        company = self._identifier(source, "company_identifier", "board_token")
        return (f"https://api.smartrecruiters.com/v1/companies/{urllib.parse.quote(company, safe='')}"
                f"/postings/{urllib.parse.quote(posting_id, safe='')}")

    def _pages(self, source: dict[str, Any], *, deadline: float | None) -> list[Any]:
        self._detail_reads = 0
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
        return [self._normalise_one(source, item, deadline=None) for item in self._raw_items(payload)
                if isinstance(item, dict)]

    def _detail_for(self, source: dict[str, Any], raw: dict[str, Any], *,
                     deadline: float | None) -> dict[str, Any] | None:
        """Read one posting detail, best effort and within the read budget."""
        if not self.enrich_details or self._detail_reads >= self.max_detail_reads:
            return None
        posting_id = clean_text(raw.get("id"), limit=240)
        if not posting_id:
            return None
        self._detail_reads += 1
        try:
            detail = self._request(self.build_detail_endpoint(source, posting_id), deadline=deadline)
        except (PublicSourceError, OSError, ValueError, TypeError, KeyError):
            # A detail read is an enrichment, never a condition: a board that
            # refuses one posting keeps the facts the list already published.
            return None
        return detail if isinstance(detail, dict) else None

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any], *,
                        deadline: float | None = None) -> dict[str, Any]:
        location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
        company = raw.get("company") if isinstance(raw.get("company"), dict) else {}
        contract = raw.get("typeOfEmployment") if isinstance(raw.get("typeOfEmployment"), dict) else {}
        # The documented list response's `ref` is an official API detail URL;
        # a human apply link is used when a source supplies one directly.
        official_url = raw.get("applyUrl") or raw.get("ref")
        apply_url = raw.get("applyUrl")
        sections = _smartrecruiters_sections(raw)
        detail = self._detail_for(source, raw, deadline=deadline)
        published: dict[str, Any] = {}
        if detail is not None:
            published = _smartrecruiters_published(detail)
            detail_sections = _smartrecruiters_sections(detail)
            if detail_sections:
                sections = detail_sections
            posting_url = clean_text(detail.get("postingUrl"), limit=2_000)
            detail_apply = clean_text(detail.get("applyUrl"), limit=2_000)
            if _is_listing_url(self.provider, posting_url):
                official_url = posting_url
            if _is_listing_url(self.provider, detail_apply):
                apply_url = detail_apply
        description = _smartrecruiters_description(sections) or raw.get("description")
        job = _common_job(self.provider, source, raw.get("id"), raw.get("name"), official_url,
                           apply_url, description, location.get("city"),
                           location.get("country"), contract.get("label"), raw.get("releasedDate"),
                           company_name=company.get("name"))
        return attach_source_material(job, self.provider, {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "requisitionId": raw.get("requisitionId"),
            "postedDate": raw.get("postedDate"),
            "releasedDate": raw.get("releasedDate"),
            "location": location,
            "typeOfEmployment": contract,
            "department": raw.get("department"),
            "company": company,
            "applyUrl": raw.get("applyUrl"),
            "ref": raw.get("ref"),
            "jobAd.sections": sections,
            **published,
        })


def _smartrecruiters_sections(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the published sections of a SmartRecruiters advertisement."""
    job_ad = raw.get("jobAd")
    if not isinstance(job_ad, dict):
        return {}
    sections = job_ad.get("sections")
    return sections if isinstance(sections, dict) else {}


def _smartrecruiters_published(detail: dict[str, Any]) -> dict[str, Any]:
    """Return the fields a posting detail publishes under their own name."""
    published: dict[str, Any] = {
        "jobId": detail.get("jobId"),
        "jobAdId": detail.get("jobAdId"),
        "postingUrl": detail.get("postingUrl"),
        "applyUrl": detail.get("applyUrl"),
        "referralUrl": detail.get("referralUrl"),
        "active": detail.get("active"),
        "visibility": detail.get("visibility"),
        "refNumber": detail.get("refNumber"),
        "releasedDate": detail.get("releasedDate"),
        "typeOfEmployment": detail.get("typeOfEmployment"),
        "department": detail.get("department"),
        "company": detail.get("company"),
        "location": detail.get("location"),
        "customField": detail.get("customField"),
        "language": detail.get("language"),
        "industry": detail.get("industry"),
        "function": detail.get("function"),
        "experienceLevel": detail.get("experienceLevel"),
    }
    return published


def _is_listing_url(provider: str, url: Any) -> bool:
    """Tell whether a URL points to a public posting page of the provider."""
    text = clean_text(url, limit=2_000)
    if not text:
        return False
    parsed = urllib.parse.urlsplit(text)
    return (parsed.scheme == "https" and parsed.hostname in _LISTING_HOSTS[provider]
            and not parsed.username and not parsed.password)


def _smartrecruiters_description(sections: dict[str, Any]) -> str:
    """Compose the description from the published sections, in published order.

    The sections are the prerequisites of the advertisement; they are read as
    published, never summarised or rewritten.  Each section keeps the name the
    source publishes it under: the heading is what lets the requirements layer
    tell a prerequisite section from a description of the company, without the
    connector deciding anything about the offer.
    """
    parts: list[str] = []
    for name, value in sections.items():
        title, text = _smartrecruiters_section(name, value)
        if text:
            parts.append(f"{title}\n{text}")
    return "\n\n".join(parts)


def _smartrecruiters_section(name: str, value: Any) -> tuple[str, str]:
    """Return the published title and the published text of one section.

    The documented shape of a section is an object carrying a ``title`` and a
    ``text``; a source that publishes the text directly is read as well.  The
    title is the one the source publishes when it publishes one, so the
    heading of the section is never invented by the connector.
    """
    if isinstance(value, dict):
        title = clean_text(value.get("title"), limit=120) or _published_section_title(name)
        text = value.get("text")
        return title, (source_html_to_text(text) if isinstance(text, str) else "")
    if isinstance(value, str):
        return _published_section_title(name), source_html_to_text(value)
    return _published_section_title(name), ""


def _published_section_title(name: str) -> str:
    """Return the name a section is published under, as a title.

    The name is not renamed: ``companyDescription`` becomes ``Company
    description`` and ``qualifications`` becomes ``Qualifications``.  A name
    the source publishes in another language keeps its own words.
    """
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-zÀ-ÖØ-öø-ÿ]*|[a-zÀ-ÖØ-öø-ÿ]+", name)
    if not words:
        return name
    title = " ".join(word if index == 0 else word.lower() for index, word in enumerate(words))
    return title[:1].upper() + title[1:]


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
    return {
        "company": clean_text(company_name or source.get("company"), limit=240),
        "title": title_text,
        "source_name": provider,
        "source_id": source_id,
        "official_url": url,
        "apply_url": clean_text(apply_url, limit=2_000),
        "city": city,
        "country": clean_text(country or country_from_location, limit=120),
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
