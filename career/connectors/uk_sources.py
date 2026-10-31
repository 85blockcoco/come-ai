"""Bounded read-only connector for UK internship boards.

Public sources read by this module:

* Prospects — https://www.prospects.ac.uk
* Gradcracker — https://www.gradcracker.com
* TargetJobs — https://targetjobs.co.uk

The three boards publish static result cards around links to their own offer
pages.  No account, no API key and no authentication is used: the connector
reads the same public pages a visitor can read and never submits anything.

The connector is deliberately defensive about the published shape:

* only links on the source host are accepted, so a card can never redirect the
  person to a third-party host;
* the read is bounded (pages, rows, response size and search budget);
* HTTP 429 is honoured with an exponential backoff and an honest rate limit;
* the fields are transmitted as published (``source_fields``) and the admission
  layer, not the connector, decides whether an offer matches the criteria.

Gradcracker answered ``403`` to an automated read while this module was
written; its parser therefore keeps the same semantic card contract rather
than assuming a live DOM that could not be observed.  Tests are synthetic and
never open a socket.
"""

from __future__ import annotations

import heapq
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Iterator

from ..countries import canonical_country_codes, country_from_source, split_location
from ..discovery import DiscoveryPayload, PublicSourceError, source_html_to_text
from ..exploration import admit_offer, ranking_key
from ..models import canonical_url, clean_text
from ..source_fields import attach_source_material
from ..stage_search import default_brief, validate_brief

from .cards import card_attributes, published_fields, time_attribute
from .http import ssl_context


#: Canonical provider names handled by the connector.
UK_PROVIDERS: tuple[str, ...] = ("prospects", "gradcracker", "targetjobs")

_UK_BASES = {
    "prospects": "https://www.prospects.ac.uk",
    "gradcracker": "https://www.gradcracker.com",
    "targetjobs": "https://targetjobs.co.uk",
}

#: Public search pages used for the finance-internship query.
_UK_SEARCH_PATHS = {
    "prospects": "/jobs-and-work-experience/job-sectors/accountancy-banking-and-finance/",
    "gradcracker": "/search/all-disciplines/finance",
    "targetjobs": "/internships/finance",
}

#: Link prefixes that identify an offer page on each board.
_UK_OFFER_PREFIXES = {
    "prospects": ("/jobs/", "/job/", "/vacancy/", "/vacancies/"),
    "gradcracker": ("/job/", "/jobs/", "/vacancy/", "/vacancies/", "/internship/"),
    "targetjobs": ("/internships/", "/graduate-jobs/", "/jobs/", "/vacancies/"),
}

_UK_TIMEOUT = 15
_UK_MAX_PAGES = 3
_UK_RATE_LIMIT = 2.0  # seconds between requests
_UK_USER_AGENT = "ComeAI-StageBot/1.0 (read-only internship search)"
_UK_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_UK_MAX_ROWS = 300
_UK_MAX_RESULTS = 150
_UK_MAX_429_RETRIES = 2
_UK_BACKOFF_SECONDS = 1.0
_UK_MAX_BACKOFF_SECONDS = 8.0
#: A result page shorter than this is considered the last page.
_UK_MIN_CARDS_PER_PAGE = 10


@dataclass
class UkSourcesHealth:
    last_ok: bool = False
    last_error: str | None = None
    consecutive_failures: int = 0
    raw_offers: int = 0
    valid_offers: int = 0
    finance_offers: int = 0
    stage_offers: int = 0
    conforming_offers: int = 0
    to_verify_offers: int = 0
    raw_count: int = 0
    filtered_count: int = 0
    excluded_count: int = 0
    excluded_by_country: dict[str, int] = field(default_factory=dict)
    #: Number of HTTP 429 responses that triggered a bounded retry.
    throttled_requests: int = 0


_HEALTH = UkSourcesHealth()
_LAST_REQUEST_TIME = 0.0


def _provider(provider: Any) -> str:
    """Return a supported provider name or an empty string."""
    name = clean_text(provider, limit=40).lower()
    return name if name in _UK_BASES else ""


def _host(url: str) -> str:
    """Comparable host name: ``www.`` is not a different site."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_provider_host(provider: str, url: str) -> bool:
    expected = _host(_UK_BASES[provider])
    return bool(expected) and _host(url) == expected


def _is_offer_link(provider: str, href: str) -> bool:
    """Whether a published link points to an offer of the same source.

    A relative link is resolved later against the board base.  An absolute link
    is accepted only when it stays on the board host: the connector never
    follows a card to a third-party site.  TargetJobs publishes category pages
    under ``/internships/<sector>``; a single segment without a digit is a
    category, not an offer, and is skipped.
    """
    if not href:
        return False
    parsed = urllib.parse.urlsplit(href)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc and not _is_provider_host(provider, href):
        return False
    path = parsed.path or ""
    for prefix in _UK_OFFER_PREFIXES[provider]:
        if not path.startswith(prefix) or len(path) <= len(prefix):
            continue
        remainder = path[len(prefix):].rstrip("/")
        if provider == "targetjobs" and "/" not in remainder and not any(character.isdigit() for character in remainder):
            continue
        return True
    return False


_CARD_MARKERS = (
    "job-card", "job-result", "job-item", "vacancy", "search-result",
    "result-card", "opportunity", "offer-card",
)
_CARD_TAGS = frozenset({"article", "li", "div"})
_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})
_FIELD_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "span", "p", "div", "strong", "li"})


def _looks_like_card(tag: str, attrs: dict[str, str | None]) -> bool:
    """Whether a start tag opens a result card.

    The boards use different wrappers (``article``, ``li``, ``div``) but all of
    them expose a stable marker in the class, a data attribute or a
    ``data-testid``.  Nested cards are ignored by the parser, which only tests
    this predicate outside a card.
    """
    if tag not in _CARD_TAGS:
        return False
    classes = (attrs.get("class") or "").lower()
    testid = (attrs.get("data-testid") or "").lower()
    if any(marker in classes for marker in _CARD_MARKERS):
        return True
    if any(marker in testid for marker in _CARD_MARKERS):
        return True
    return any(attrs.get(name) for name in ("data-job-id", "data-jobid", "data-vacancy-id", "data-offer-id"))


def _card_identifier(attrs: dict[str, str | None]) -> str:
    for name in ("data-job-id", "data-jobid", "data-vacancy-id", "data-offer-id", "data-id"):
        value = clean_text(attrs.get(name), limit=160)
        if value:
            return value
    return ""


class _UkJobParser(HTMLParser):
    """Parse the result cards published by the three UK boards."""

    def __init__(self, provider: str) -> None:
        super().__init__(convert_charrefs=True)
        self.provider = provider
        self.jobs: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._stack: list[str] = []
        self._current_field = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._current is None:
            if not _looks_like_card(tag, attributes):
                return
            self._current = {
                "title": "",
                "company": "",
                "location": "",
                "contract_type": "",
                "url": "",
                "description": "",
                "attributes": card_attributes(attrs),
                "source_id": _card_identifier(attributes),
            }
            if tag not in _VOID_TAGS:
                self._stack = [tag]
            return

        if tag in _SKIP_TAGS:
            self._stack.append(tag)
            return
        if tag not in _VOID_TAGS:
            self._stack.append(tag)

        if tag == "time":
            published = time_attribute(attrs)
            if published:
                self._current.setdefault("attributes", {})["datetime"] = published
        elif tag == "a" and attributes.get("href"):
            if _is_offer_link(self.provider, attributes["href"]):
                self._current["url"] = urllib.parse.urljoin(_UK_BASES[self.provider], attributes["href"])
        elif tag in _FIELD_TAGS:
            hint = " ".join(
                (attributes.get("class") or "", attributes.get("data-testid") or "",
                 attributes.get("itemprop") or "")
            ).lower()
            if "title" in hint or "position" in hint or hint == "name":
                self._current_field = "title"
            elif any(word in hint for word in ("company", "employer", "organisation", "organization", "hiring")):
                self._current_field = "company"
            elif any(word in hint for word in ("location", "city", "region", "place")):
                self._current_field = "location"
            elif any(word in hint for word in ("contract", "employment", "job-type", "jobtype", "type")):
                self._current_field = "contract_type"
            elif any(word in hint for word in ("description", "summary", "excerpt", "snippet")):
                self._current_field = "description"

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if self._current_field and tag in _FIELD_TAGS:
            self._current_field = ""
        if tag not in self._stack:
            return
        while self._stack:
            opened = self._stack.pop()
            if opened == tag:
                break
        if self._stack:
            return
        if self._current.get("title") and self._current.get("url"):
            self.jobs.append(self._current)
        self._current = None
        self._current_field = ""

    def handle_data(self, data: str) -> None:
        if self._current is None or not self._current_field:
            return
        if any(tag in _SKIP_TAGS for tag in self._stack):
            return
        text = data.strip()
        if not text:
            return
        current = self._current.get(self._current_field, "")
        limit = 2_000 if self._current_field == "description" else 500
        self._current[self._current_field] = clean_text(f"{current} {text}", limit=limit)


def _retry_after_seconds(error: urllib.error.HTTPError) -> float | None:
    """Delay published by the source, bounded, or ``None`` when absent."""
    headers = getattr(error, "headers", None)
    value = headers.get("Retry-After") if headers is not None else None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, _UK_MAX_BACKOFF_SECONDS)


def fetch_published_html(
    url: str,
    *,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
    max_bytes: int = _UK_MAX_RESPONSE_BYTES,
) -> str | None:
    """Read one public page, retrying a bounded number of times on HTTP 429.

    The retry is the only write-free effect: the delay comes from the source's
    ``Retry-After`` header when it is a number, otherwise from exponential
    backoff.  Every other status returns ``None`` and records the error; a
    failed page never interrupts the rest of the refresh.
    """
    opener = opener or urllib.request.urlopen
    sleeper = sleeper or time.sleep
    attempt = 0
    while True:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": _UK_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9,fr;q=0.8",
            },
        )
        try:
            with opener(request, timeout=_UK_TIMEOUT, context=ssl_context()) as response:
                body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                _HEALTH.last_error = "Response too large"
                _HEALTH.consecutive_failures += 1
                return None
            _HEALTH.last_error = None
            return body.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < _UK_MAX_429_RETRIES:
                delay = _retry_after_seconds(error)
                if delay is None:
                    delay = _UK_BACKOFF_SECONDS * (2 ** attempt)
                attempt += 1
                _HEALTH.throttled_requests += 1
                sleeper(delay)
                continue
            _HEALTH.last_error = f"HTTP {error.code}"
            _HEALTH.consecutive_failures += 1
            return None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            _HEALTH.last_error = f"Network error: {type(error).__name__}"
            _HEALTH.consecutive_failures += 1
            return None
        except Exception as error:  # noqa: BLE001 - untrusted transport must not break a refresh
            _HEALTH.last_error = f"Unexpected error: {type(error).__name__}: {error}"
            _HEALTH.consecutive_failures += 1
            return None


def _wait_for_rate_limit(
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    rate_limit: float = _UK_RATE_LIMIT,
) -> None:
    """Honest client-side rate limit shared by the three boards."""
    global _LAST_REQUEST_TIME
    now = monotonic()
    wait = rate_limit - (now - _LAST_REQUEST_TIME)
    if wait > 0:
        sleeper(wait)
    else:
        wait = 0.0
    _LAST_REQUEST_TIME = now + wait


def _default_fetch(url: str) -> str | None:
    _wait_for_rate_limit()
    return fetch_published_html(url)


def _build_search_url(provider: str, page: int = 1, query: str = "finance internship") -> str:
    """Search URL of one supported board, with a bounded page number."""
    safe_provider = _provider(provider)
    if not safe_provider:
        raise ValueError("unsupported UK source")
    base = _UK_BASES[safe_provider]
    path = _UK_SEARCH_PATHS[safe_provider]
    page_number = max(1, min(_UK_MAX_PAGES, int(page)))
    params = {"query": clean_text(query, limit=120), "page": str(page_number)}
    return f"{base}{path}?{urllib.parse.urlencode(params)}"


def _parse_location(provider: str, location_text: str) -> tuple[str, str]:
    """Split a published location; these boards are UK-first.

    A card that writes only a city is completed with ``United Kingdom`` because
    the board itself only publishes UK opportunities.  The country wording is
    still normalized by ``country_from_source`` before any exclusion.
    """
    text = clean_text(location_text, limit=160)
    if not text:
        return "", ""
    parts = split_location(text)
    if not parts:
        return text, ""
    city = parts[0]
    country = parts[-1] if len(parts) >= 2 else ""
    if not country and provider in _UK_BASES:
        country = "United Kingdom"
    return city, country


def _is_excluded_location(country: str, excluded_codes: frozenset[str]) -> str:
    code = country_from_source(country)
    return code if code and code in excluded_codes else ""


_FINANCE_KEYWORDS = frozenset({
    "m&a", "mergers", "acquisitions", "investment banking", "corporate finance",
    "private equity", "capital markets", "asset management", "portfolio management",
    "equity research", "fixed income", "sales & trading", "global markets", "trading",
    "transaction services", "due diligence", "audit", "fp&a", "financial planning",
    "treasury", "valuation", "strategic finance", "quantitative research", "quant",
    "risk management", "wealth management", "finance", "financial", "banking",
    "accounting", "fintech", "insurance", "actuarial",
})

_STAGE_KEYWORDS = frozenset({
    "stage", "stagiaire", "intern", "internship", "placement", "summer analyst",
    "off-cycle", "industrial placement", "work experience", "graduate scheme",
})


def _is_finance_role(title: str, description: str) -> bool:
    text = f"{title} {description}".lower()
    return any(keyword in text for keyword in _FINANCE_KEYWORDS)


def _is_stage_role(title: str, description: str, contract_type: str) -> bool:
    text = f"{contract_type} {title} {description}".lower()
    return any(keyword in text for keyword in _STAGE_KEYWORDS)


def _iter_raw_offers(
    provider: str,
    *,
    fetch: Callable[[str], str | None] | None = None,
    countries_exclude: frozenset[str] = frozenset(),
    max_pages: int = _UK_MAX_PAGES,
    query: str = "finance internship",
) -> Iterator[dict[str, Any]]:
    """Iterate over the bounded raw offers of one UK board."""
    safe_provider = _provider(provider)
    if not safe_provider:
        return
    fetch_fn = fetch or _default_fetch
    for page in range(1, max(1, min(_UK_MAX_PAGES, int(max_pages))) + 1):
        html = fetch_fn(_build_search_url(safe_provider, page, query))
        if html is None:
            break

        parser = _UkJobParser(safe_provider)
        try:
            parser.feed(html)
            parser.close()
        except Exception as error:  # noqa: BLE001 - malformed remote HTML is not fatal
            _HEALTH.last_error = f"Parse error: {type(error).__name__}: {error}"
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
            url_raw = clean_text(raw.get("url", ""), limit=2_000)
            location_text = clean_text(raw.get("location", ""), limit=160)
            contract_type = clean_text(raw.get("contract_type", ""), limit=120)
            description = source_html_to_text(raw.get("description", ""))

            if not title or not company or not url_raw:
                _HEALTH.filtered_count += 1
                continue

            try:
                official_url = canonical_url(url_raw)
            except Exception:  # noqa: BLE001 - an invalid link is dropped, never repaired
                _HEALTH.filtered_count += 1
                continue
            if not _is_provider_host(safe_provider, official_url):
                _HEALTH.filtered_count += 1
                continue

            city, country = _parse_location(safe_provider, location_text)
            excluded_code = _is_excluded_location(country, countries_exclude)
            if excluded_code:
                _HEALTH.excluded_by_country[excluded_code] = _HEALTH.excluded_by_country.get(excluded_code, 0) + 1
                _HEALTH.excluded_count += 1
                _HEALTH.filtered_count += 1
                continue

            _HEALTH.valid_offers += 1
            is_finance = _is_finance_role(title, description)
            is_stage = _is_stage_role(title, description, contract_type)
            _HEALTH.finance_offers += int(is_finance)
            _HEALTH.stage_offers += int(is_stage)
            if is_finance and is_stage:
                _HEALTH.conforming_offers += 1
            else:
                _HEALTH.to_verify_offers += 1

            job_id = clean_text(raw.get("source_id"), limit=160)
            if not job_id:
                job_id = urllib.parse.urlsplit(official_url).path.rstrip("/").rsplit("/", 1)[-1]
            if not job_id:
                job_id = str(hash(official_url))[-12:]

            yield attach_source_material({
                "company": company,
                "title": title,
                "source_name": safe_provider,
                "source_id": job_id,
                "official_url": official_url,
                "apply_url": official_url,
                "city": city,
                "country": country,
                "country_canonical": country_from_source(country),
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
            }, safe_provider, published_fields(raw, raw.get("attributes")))

        if len(page_jobs) < _UK_MIN_CARDS_PER_PAGE:
            break

    _HEALTH.last_ok = True
    _HEALTH.last_error = None
    _HEALTH.consecutive_failures = 0


def _reset_health() -> None:
    _HEALTH.last_ok = False
    _HEALTH.last_error = None
    _HEALTH.consecutive_failures = 0
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
    _HEALTH.throttled_requests = 0


class UkSourcesConnector:
    """Read Prospects, Gradcracker and TargetJobs through one bounded contract."""

    providers = UK_PROVIDERS

    def __init__(
        self,
        *,
        clock: Callable[[], str] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        max_pages: int = _UK_MAX_PAGES,
        max_results: int = _UK_MAX_RESULTS,
        fetch: Callable[[str], str | None] | None = None,
        enabled: bool = False,
    ) -> None:
        self.enabled = enabled
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.max_pages = max(1, min(_UK_MAX_PAGES, int(max_pages)))
        self.max_results = max(1, min(_UK_MAX_RESULTS, int(max_results)))
        self._fetch = fetch

    def discover_internships(
        self,
        source: dict[str, Any],
        *,
        selection_brief: dict[str, Any],
        deadline: float | None = None,
        countries_exclude: list[str] | tuple[str, ...] | None = None,
    ) -> DiscoveryPayload:
        provider = _provider(source.get("provider")) if isinstance(source, dict) else ""
        if not provider:
            raise PublicSourceError(
                "La source ne correspond pas au connecteur UK sources.", code="invalid_source"
            )
        if not source.get("id") or not source.get("company") or not source.get("verified_at") \
                or not source.get("provenance_url"):
            raise PublicSourceError(
                "Une source officielle vérifiée est requise avant toute consultation.",
                code="unverified_source",
            )

        brief = validate_brief(selection_brief) if selection_brief else default_brief()
        excluded_codes = frozenset(canonical_country_codes(
            countries_exclude if countries_exclude is not None else brief.get("countries_exclude")
        ))

        _reset_health()
        raw_count = evaluated = invalid = confirmed = uncertain = excluded = relevant = filtered = 0
        ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        for raw in _iter_raw_offers(
            provider,
            fetch=self._fetch,
            countries_exclude=excluded_codes,
            max_pages=self.max_pages,
        ):
            if deadline is not None and self.monotonic() >= deadline:
                raise PublicSourceError("Le budget de recherche est atteint.", code="budget")
            raw_count += 1
            if raw_count > _UK_MAX_ROWS:
                raise PublicSourceError("Le flux dépasse la limite d'offres évaluées.", code="too_many_rows")

            try:
                job = self._normalise_one(source, raw)
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue

            evaluated += 1
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
        # The parser already produced the common contract; the admission layer
        # decides.  Keeping this method makes the connector symmetrical with
        # the other HTML boards.
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
            "throttled_requests": _HEALTH.throttled_requests,
        }

    @staticmethod
    def reset_health() -> None:
        """Reset the module health counters (used by a refresh and by tests)."""
        _reset_health()


def register_uk_sources_connector(registry: dict[str, tuple]) -> None:
    """Register the three UK providers on the shared connector class."""
    for provider in UK_PROVIDERS:
        registry[provider] = (UkSourcesConnector, "class")


__all__ = [
    "UK_PROVIDERS",
    "UkSourcesConnector",
    "fetch_published_html",
    "register_uk_sources_connector",
]
