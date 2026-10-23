"""Bounded read-only connector for Welcome to the Jungle public job search.

Official career page: https://www.welcometothejungle.com/fr/jobs
Verified: 2026-10-20 (manual inspection of search endpoint and HTML structure)
Documentation: No public API; uses search HTML with structured data attributes.
"""

from __future__ import annotations

import functools
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Iterator

from ..discovery import DiscoveryPayload, PublicSourceError, source_html_to_text
from ..countries import (
    GeoFilter,
    geo_filter,
    resolve_hinted_country,
    resolve_published_country,
    split_location,
)
from ..models import clean_text, canonical_url
from ..exploration import classify_internship, criteria_admit, ranking_key
from ..offer_qualification import qualify_offer
from ..stage_search import default_brief, score_brief_match, validate_brief


_WTJ_BASE = "https://www.welcometothejungle.com"
_WTJ_SEARCH = _WTJ_BASE + "/fr/jobs"
_WTJ_TIMEOUT = 15
_WTJ_MAX_PAGES = 5
_WTJ_RATE_LIMIT = 2.0  # seconds between requests
_WTJ_USER_AGENT = "ComeAI-StageBot/1.0"
_WTJ_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_WTJ_MAX_ROWS = 400


@functools.lru_cache(maxsize=1)
def _trusted_ssl_context() -> ssl.SSLContext:
    """SSL context that trusts the certifi root bundle when it is installed.

    macOS Python installers often leave the system keychain without the
    Mozilla root bundle, which makes a plain default context reject every
    public site with CERTIFICATE_VERIFY_FAILED.  ``certifi`` solves this
    without weakening certificate verification; the stdlib context stays the
    fallback when certifi is absent.  The same fallback already backs the
    Greenhouse transport (``career/discovery.py``) and the public ATS
    connectors (``career/connectors/public_ats.py``).
    """
    context = ssl.create_default_context()
    try:
        import certifi  # noqa: PLC0415 - optional, keep stdlib-only fallback

        context = ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    return context


@dataclass
class WelcomeJungleHealth:
    last_ok: bool = False
    last_error: str | None = None
    consecutive_failures: int = 0
    raw_offers: int = 0
    valid_offers: int = 0
    finance_offers: int = 0
    stage_offers: int = 0
    conforming_offers: int = 0
    to_verify_offers: int = 0
    # Source-side geographic filtering: raw rows read, rows dropped and the
    # country that caused each drop.
    raw_count: int = 0
    filtered_count: int = 0
    excluded_count: int = 0
    excluded_by_country: dict[str, int] = field(default_factory=dict)


_HEALTH = WelcomeJungleHealth()
_LAST_REQUEST_TIME = 0.0


class _WTJJobParser(HTMLParser):
    """Parse job cards from Welcome to the Jungle search results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jobs: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._in_job_card = False
        self._current_field = ""
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "article" and attrs_dict.get("data-testid") == "job-card":
            self._in_job_card = True
            self._current = {
                "title": "",
                "company": "",
                "location": "",
                "contract_type": "",
                "url": "",
                "description": "",
            }
        elif self._in_job_card and self._current is not None:
            if tag == "a" and attrs_dict.get("href"):
                href = attrs_dict["href"]
                if href.startswith("/fr/companies/") and "/jobs/" in href:
                    self._current["url"] = urllib.parse.urljoin(_WTJ_BASE, href)
            elif tag in ("h3", "h4", "span", "p", "div"):
                testid = attrs_dict.get("data-testid", "")
                if "job-title" in testid or "title" in testid:
                    self._current_field = "title"
                elif "company" in testid:
                    self._current_field = "company"
                elif "location" in testid or "office" in testid:
                    self._current_field = "location"
                elif "contract" in testid or "type" in testid:
                    self._current_field = "contract_type"
                elif "description" in testid or "excerpt" in testid:
                    self._current_field = "description"
            elif tag in ("script", "style", "noscript"):
                self._drop_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._in_job_card and tag == "article":
            if self._current and self._current.get("title") and self._current.get("url"):
                self.jobs.append(self._current)
            self._in_job_card = False
            self._current = None
            self._current_field = ""
        elif self._in_job_card and tag in ("h3", "h4", "span", "p", "div"):
            self._current_field = ""
        elif self._in_job_card and tag in ("script", "style", "noscript") and self._drop_depth > 0:
            self._drop_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._drop_depth > 0:
            return
        if self._in_job_card and self._current is not None and self._current_field and data.strip():
            self._current[self._current_field] = clean_text(
                self._current.get(self._current_field, "") + " " + data.strip(), limit=500
            )


def _default_fetch(url: str) -> str | None:
    global _LAST_REQUEST_TIME
    now = time.monotonic()
    elapsed = now - _LAST_REQUEST_TIME
    if elapsed < _WTJ_RATE_LIMIT:
        time.sleep(_WTJ_RATE_LIMIT - elapsed)
    _LAST_REQUEST_TIME = time.monotonic()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _WTJ_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_WTJ_TIMEOUT, context=_trusted_ssl_context()) as resp:
            body = resp.read(_WTJ_MAX_RESPONSE_BYTES + 1)
            if len(body) > _WTJ_MAX_RESPONSE_BYTES:
                _HEALTH.last_error = "Response too large"
                _HEALTH.consecutive_failures += 1
                return None
            return body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        _HEALTH.last_error = f"HTTP {e.code}"
        _HEALTH.consecutive_failures += 1
        return None
    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        _HEALTH.last_error = f"Network error: {type(e).__name__}"
        _HEALTH.consecutive_failures += 1
        return None
    except Exception as e:
        _HEALTH.last_error = f"Unexpected error: {type(e).__name__}: {e}"
        _HEALTH.consecutive_failures += 1
        return None


def _build_search_url(query: str, location: str, page: int,
                      geo: GeoFilter | None = None) -> str:
    """Build Welcome to the Jungle search URL with filters.

    The country refinement is asked of the source itself: an excluded country
    never enters the feed, so the connector spends no quota on it.  When the
    source is targeted (an inclusion list), the request asks for exactly
    those countries.
    """
    country_codes = [
        "GB", "DE", "NL", "BE", "LU", "CH", "IE", "ES", "IT", "PT",
        "SE", "NO", "DK", "FI", "AT", "PL",
    ]
    if geo is not None:
        country_codes = [code for code in country_codes if code not in geo.exclude]
        if geo.include:
            country_codes = [code for code in country_codes if code in geo.include]
    params = {
        "query": query,
        "page": str(page),
        "aroundQuery": location,
        "refinementList[contract_type][]": "internship",
        "refinementList[office.country_code][]": country_codes,
    }
    query_string = urllib.parse.urlencode(params, doseq=True)
    return f"{_WTJ_SEARCH}?{query_string}"


def _parse_location(location_text: str) -> tuple[str, str]:
    """Parse location string into city and country."""
    location_text = clean_text(location_text, limit=160)
    if not location_text:
        return "", ""
    parts = split_location(location_text)
    if len(parts) >= 2:
        city = parts[0]
        country = parts[-1]
        return city, country
    return location_text, ""


def _is_excluded_location(city: str, country: str, geo: GeoFilter, location_text: str = "") -> str:
    """Canonical country of a location when it is rejected, else an empty string.

    The country is normalized before the comparison, so ``"France"``,
    ``"FR"``, ``"FRA"`` and ``"fr"`` are all the same country while
    ``"Frankfurt"`` (Germany) is never mistaken for ``"FR"``.  A city alone
    never designates a country: an unknown country is not a French offer.

    A source that publishes the country alone (``"France"``, ``"Germany"``)
    publishes a country: it is read on the country name, never guessed.  A
    posting that names several countries is kept as soon as one of them is
    allowed.

    A scraped card that names a single city and no country may only be
    **excluded** by the city hint: the hint never proves where the offer is,
    it only refuses an offer whose location suggests an excluded country.
    """
    _ = city
    _canonical, excluded = resolve_published_country(None, location_text or country, geo)
    if excluded:
        return excluded
    return resolve_hinted_country(location_text or country, geo)


def _is_finance_role(title: str, description: str) -> bool:
    """Check if job is finance-related."""
    finance_keywords = {
        "m&a", "mergers", "acquisitions", "fusion", "acquisition", "investment banking",
        "banque d'affaires", "corporate finance", "finance d'entreprise", "private equity",
        "capital investissement", "asset management", "gestion d'actifs", "portfolio management",
        "equity research", "fixed income", "sales & trading", "global markets", "trading",
        "transaction services", "due diligence", "financial due diligence", "audit",
        "audit financier", "fp&a", "financial planning", "controle de gestion", "treasury",
        "valuation", "strategic finance", "quantitative research", "quant", "risk management",
        "gestion de portefeuille", "analyse financiere", "banque", "finance", "comptabilite",
        "expertise comptable", "consolidation", "reporting", "controler", "business partner"
    }
    text = (title + " " + description).lower()
    return any(kw in text for kw in finance_keywords)


def _is_stage_role(title: str, description: str, contract_type: str) -> bool:
    """Check if job is an internship/stage."""
    stage_keywords = {"stage", "stagiaire", "intern", "internship", "tirocinio", "praktikum",
                      "werkstudent", "working student", "apprenti", "apprentissage", "alternance"}
    contract = contract_type.lower()
    text = (title + " " + description).lower()
    return any(kw in contract for kw in stage_keywords) or any(kw in text for kw in stage_keywords)


def _iter_raw_offers(
    query: str = "stage finance",
    location: str = "europe",
    fetch: Callable[[str], str | None] | None = None,
    geo: GeoFilter | None = None,
) -> Iterator[dict[str, Any]]:
    """Iterate over raw internship offers from Welcome to the Jungle."""
    fetch_fn = fetch or _default_fetch
    geo_filter_object = geo or GeoFilter()
    for page in range(1, _WTJ_MAX_PAGES + 1):
        url = _build_search_url(query, location, page, geo_filter_object)
        html = fetch_fn(url)
        if html is None:
            break

        parser = _WTJJobParser()
        try:
            parser.feed(html)
            parser.close()
        except Exception as e:
            _HEALTH.last_error = f"Parse error: {type(e).__name__}: {e}"
            _HEALTH.consecutive_failures += 1
            break

        page_jobs = parser.jobs
        if not page_jobs:
            break

        for raw in page_jobs:
            _HEALTH.raw_offers += 1
            _HEALTH.raw_count += 1

            title = clean_text(raw.get("title", ""), limit=300)
            company = clean_text(raw.get("company", ""), limit=240)
            url_raw = clean_text(raw.get("url", ""), limit=2000)
            location_text = clean_text(raw.get("location", ""), limit=160)
            contract_type = clean_text(raw.get("contract_type", ""), limit=120)

            if not title or not company or not url_raw:
                _HEALTH.filtered_count += 1
                continue

            try:
                official_url = canonical_url(url_raw)
            except Exception:
                _HEALTH.filtered_count += 1
                continue

            city, country = _parse_location(location_text)

            # The excluded countries are dropped here, on the source side: the
            # offer never becomes a local record and never consumes a slot.
            # The check runs before the description is even parsed.
            excluded_code = _is_excluded_location(city, country, geo_filter_object, location_text)
            if excluded_code:
                _HEALTH.excluded_by_country[excluded_code] = (
                    _HEALTH.excluded_by_country.get(excluded_code, 0) + 1
                )
                _HEALTH.excluded_count += 1
                _HEALTH.filtered_count += 1
                continue

            description = source_html_to_text(raw.get("description", ""))

            _HEALTH.valid_offers += 1

            is_finance = _is_finance_role(title, description)
            is_stage = _is_stage_role(title, description, contract_type)

            if is_finance:
                _HEALTH.finance_offers += 1
            if is_stage:
                _HEALTH.stage_offers += 1

            conforming = is_finance and is_stage and bool(official_url)
            if conforming:
                _HEALTH.conforming_offers += 1
            else:
                _HEALTH.to_verify_offers += 1

            job_id = urllib.parse.urlsplit(official_url).path.rstrip("/").rsplit("/", 1)[-1]
            if not job_id:
                job_id = str(hash(official_url))[-12:]

            canonical_country, _excluded = resolve_published_country(
                None, location_text, geo_filter_object
            )

            yield {
                "company": company,
                "title": title,
                "source_name": "welcome_jungle",
                "source_id": job_id,
                "official_url": official_url,
                "apply_url": official_url,
                "city": city,
                "country": country,
                "country_canonical": canonical_country,
                "posted_date": "",
                "deadline_date": "",
                "start_date": "",
                "end_date": "",
                "duration_months": None,
                "source_status": "open",
                "source_verified": True,
                "employment_type": contract_type,
                "role_level": "",
                "requirements": "",
                "languages_required": "",
                "eligibility_requirement": "",
                "description_original": description,
            }

        if len(page_jobs) < 20:
            break

    _HEALTH.last_ok = True
    _HEALTH.last_error = None
    _HEALTH.consecutive_failures = 0


class WelcomeJungleConnector:
    """Welcome to the Jungle connector implementing the InternshipConnector protocol."""

    def __init__(
        self,
        *,
        clock: Callable[[], str] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        max_pages: int = _WTJ_MAX_PAGES,
        max_results: int = 150,
        fetch: Callable[[str], str | None] | None = None,
        enabled: bool = False,
    ) -> None:
        self.enabled = enabled
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.max_pages = max(1, min(_WTJ_MAX_PAGES, int(max_pages)))
        self.max_results = max(1, min(150, int(max_results)))
        self._fetch = fetch

    def discover_internships(
        self, source: dict[str, Any], *, selection_brief: dict[str, Any], deadline: float | None = None,
        countries_exclude: list[str] | tuple[str, ...] | None = None,
        countries_include: list[str] | tuple[str, ...] | None = None,
    ) -> DiscoveryPayload:
        if not isinstance(source, dict) or source.get("provider") != "welcome_jungle":
            raise PublicSourceError("La source ne correspond pas au connecteur Welcome to the Jungle.", code="invalid_source")
        # Verify source identity and provenance
        if not source.get("id") or not source.get("company") or not source.get("verified_at") or not source.get("provenance_url"):
            raise PublicSourceError("Une source officielle vérifiée est requise avant toute consultation.", code="unverified_source")

        brief = validate_brief(selection_brief) if selection_brief else default_brief()
        geo = geo_filter(countries_exclude, countries_include, brief)

        # Reset health counters for this run
        _HEALTH.raw_offers = 0
        _HEALTH.valid_offers = 0
        _HEALTH.finance_offers = 0
        _HEALTH.stage_offers = 0
        _HEALTH.conforming_offers = 0
        _HEALTH.to_verify_offers = 0
        _HEALTH.raw_count = 0
        _HEALTH.filtered_count = 0
        _HEALTH.excluded_count = 0
        _HEALTH.excluded_by_country = {}

        raw_count = evaluated = invalid = confirmed = uncertain = excluded = relevant = filtered = 0
        ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        for raw in _iter_raw_offers(fetch=self._fetch, geo=geo):
            if deadline is not None and self.monotonic() >= deadline:
                raise PublicSourceError("Le budget de recherche est atteint.", code="budget")
            raw_count += 1
            if raw_count > _WTJ_MAX_ROWS:
                raise PublicSourceError("Le flux dépasse la limite d'offres évaluées.", code="too_many_rows")

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

        import heapq
        selected = heapq.nsmallest(self.max_results, ranked, key=lambda item: item[0])

        return DiscoveryPayload(
            jobs=tuple(item[1]["job"] for item in selected),
            verified_at=self.clock(),
            truncated=relevant > self.max_results,
            raw_count=raw_count,
            evaluated_count=evaluated,
            invalid_count=invalid,
            confirmed_count=confirmed,
            uncertain_count=uncertain,
            excluded_count=excluded,
            relevant_count=relevant,
            filtered_criteria_count=filtered,
            country_excluded_count=_HEALTH.excluded_count,
            excluded_by_country=dict(_HEALTH.excluded_by_country),
        )

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        return raw

    @staticmethod
    def health_check() -> dict[str, Any]:
        return {
            "last_ok": _HEALTH.last_ok,
            "last_error": _HEALTH.last_error,
            "consecutive_failures": _HEALTH.consecutive_failures,
            "raw_offers": _HEALTH.raw_offers,
            "valid_offers": _HEALTH.valid_offers,
            "finance_offers": _HEALTH.finance_offers,
            "stage_offers": _HEALTH.stage_offers,
            "conforming_offers": _HEALTH.conforming_offers,
            "to_verify_offers": _HEALTH.to_verify_offers,
            "raw_count": _HEALTH.raw_count,
            "filtered_count": _HEALTH.filtered_count,
            "excluded_count": _HEALTH.excluded_count,
            "excluded_by_country": dict(_HEALTH.excluded_by_country),
        }


def register_welcome_jungle_connector(registry: dict[str, tuple]) -> None:
    """Register the Welcome to the Jungle connector."""
    registry["welcome_jungle"] = (WelcomeJungleConnector, "class")