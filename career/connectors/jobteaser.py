"""Bounded read-only connector for JobTeaser public job search.

Official career page: https://www.jobteaser.com/en/jobs
Verified: 2026-10-20 (manual inspection of search endpoint and HTML structure)
Documentation: No public API; uses search HTML with structured data.
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Iterator

from ..discovery import DiscoveryPayload, PublicSourceError, source_html_to_text
from ..models import clean_text, canonical_url
from ..exploration import classify_internship, criteria_admit, ranking_key
from ..offer_qualification import qualify_offer
from ..stage_search import default_brief, score_brief_match, validate_brief


_JT_BASE = "https://www.jobteaser.com"
_JT_SEARCH = _JT_BASE + "/en/jobs"
_JT_TIMEOUT = 15
_JT_MAX_PAGES = 5
_JT_RATE_LIMIT = 2.0
_JT_USER_AGENT = "ComeAI-StageBot/1.0"
_JT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_JT_MAX_ROWS = 400


@dataclass
class JobTeaserHealth:
    last_ok: bool = False
    last_error: str | None = None
    consecutive_failures: int = 0
    raw_offers: int = 0
    valid_offers: int = 0
    finance_offers: int = 0
    stage_offers: int = 0
    conforming_offers: int = 0
    to_verify_offers: int = 0


_HEALTH = JobTeaserHealth()
_LAST_REQUEST_TIME = 0.0


class _JTJobParser(HTMLParser):
    """Parse job cards from JobTeaser search results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jobs: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._in_job_card = False
        self._current_field = ""
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "article" and "job-card" in attrs_dict.get("class", ""):
            self._in_job_card = True
            self._current = {
                "title": "",
                "company": "",
                "location": "",
                "contract_type": "",
                "url": "",
                "description": "",
            }
            self._depth = 1
        elif self._in_job_card:
            self._depth += 1
            if tag == "a" and attrs_dict.get("href"):
                href = attrs_dict["href"]
                if "/jobs/" in href or "/offers/" in href:
                    self._current["url"] = urllib.parse.urljoin(_JT_BASE, href)
            elif tag in ("h3", "h4", "h5", "span", "p", "div"):
                classes = attrs_dict.get("class", "").lower()
                testid = attrs_dict.get("data-testid", "").lower()
                if "title" in classes or "title" in testid:
                    self._current_field = "title"
                elif "company" in classes or "company" in testid or "employer" in classes:
                    self._current_field = "company"
                elif "location" in classes or "location" in testid or "city" in classes:
                    self._current_field = "location"
                elif "contract" in classes or "contract" in testid or "type" in classes:
                    self._current_field = "contract_type"
                elif "description" in classes or "excerpt" in classes or "summary" in classes:
                    self._current_field = "description"

    def handle_endtag(self, tag: str) -> None:
        if self._in_job_card:
            self._depth -= 1
            if self._depth == 0 and tag == "article":
                if self._current and self._current.get("title") and self._current.get("url"):
                    self.jobs.append(self._current)
                self._in_job_card = False
                self._current = None
                self._current_field = ""
            elif tag in ("h3", "h4", "h5", "span", "p", "div"):
                self._current_field = ""

    def handle_data(self, data: str) -> None:
        if self._in_job_card and self._current is not None and self._current_field and data.strip():
            self._current[self._current_field] = clean_text(
                self._current.get(self._current_field, "") + " " + data.strip(), limit=500
            )


def _default_fetch(url: str) -> str | None:
    global _LAST_REQUEST_TIME
    now = time.monotonic()
    elapsed = now - _LAST_REQUEST_TIME
    if elapsed < _JT_RATE_LIMIT:
        time.sleep(_JT_RATE_LIMIT - elapsed)
    _LAST_REQUEST_TIME = time.monotonic()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _JT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9,fr;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_JT_TIMEOUT) as resp:
            body = resp.read(_JT_MAX_RESPONSE_BYTES + 1)
            if len(body) > _JT_MAX_RESPONSE_BYTES:
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


def _build_search_url(query: str, page: int) -> str:
    """Build JobTeaser search URL with filters for finance internships outside France."""
    params = {
        "query": query,
        "page": str(page),
        "contract_type": "internship",
        "countries[]": ["GB", "DE", "NL", "BE", "LU", "CH", "IE", "ES", "IT", "PT",
                        "SE", "NO", "DK", "FI", "AT", "PL", "CZ", "HU", "RO", "BG",
                        "HR", "SI", "SK", "EE", "LV", "LT", "MT", "CY"],
    }
    query_string = urllib.parse.urlencode(params, doseq=True)
    return f"{_JT_SEARCH}?{query_string}"


def _parse_location(location_text: str) -> tuple[str, str]:
    """Parse location string into city and country."""
    location_text = clean_text(location_text, limit=160)
    if not location_text:
        return "", ""
    parts = [p.strip() for p in re.split(r"[,(]", location_text) if p.strip()]
    if len(parts) >= 2:
        city = parts[0]
        country = parts[-1]
        return city, country
    return location_text, ""


def _is_france_location(city: str, country: str) -> bool:
    """Check if location is in France (to be excluded per R1)."""
    france_indicators = {"france", "fr", "paris", "lyon", "marseille", "toulouse", "nice", "nantes",
                         "strasbourg", "montpellier", "bordeaux", "lille", "rennes", "reims",
                         "le havre", "saint-etienne", "toulon", "grenoble", "dijon", "angers",
                         "villeurbanne", "nanterre", "creteil", "aubervilliers", "asnieres",
                         "colombes", "courbevoie", "levallois-perret", "neuilly-sur-seine"}
    city_norm = city.lower().strip()
    country_norm = country.lower().strip()
    if country_norm in {"france", "fr"}:
        return True
    for ind in france_indicators:
        if ind == "fr":
            continue
        if ind in city_norm.split():
            return True
        if f"-{ind}" in city_norm or f"{ind}-" in city_norm:
            return True
    return False


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
    query: str = "finance internship",
    fetch: Callable[[str], str | None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Iterate over raw internship offers from JobTeaser."""
    fetch_fn = fetch or _default_fetch
    for page in range(1, _JT_MAX_PAGES + 1):
        url = _build_search_url(query, page)
        html = fetch_fn(url)
        if html is None:
            break

        parser = _JTJobParser()
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

            title = clean_text(raw.get("title", ""), limit=300)
            company = clean_text(raw.get("company", ""), limit=240)
            url_raw = clean_text(raw.get("url", ""), limit=2000)
            location_text = clean_text(raw.get("location", ""), limit=160)
            contract_type = clean_text(raw.get("contract_type", ""), limit=120)
            description = source_html_to_text(raw.get("description", ""))

            if not title or not company or not url_raw:
                continue

            try:
                official_url = canonical_url(url_raw)
            except Exception:
                continue

            city, country = _parse_location(location_text)

            if _is_france_location(city, country):
                continue

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

            yield {
                "company": company,
                "title": title,
                "source_name": "jobteaser",
                "source_id": job_id,
                "official_url": official_url,
                "apply_url": official_url,
                "city": city,
                "country": country,
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

        if len(page_jobs) < 15:
            break

    _HEALTH.last_ok = True
    _HEALTH.last_error = None
    _HEALTH.consecutive_failures = 0


class JobTeaserConnector:
    """JobTeaser connector implementing the InternshipConnector protocol."""

    def __init__(
        self,
        *,
        clock: Callable[[], str] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        max_pages: int = _JT_MAX_PAGES,
        max_results: int = 150,
        fetch: Callable[[str], str | None] | None = None,
        enabled: bool = False,
    ) -> None:
        self.enabled = enabled
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.max_pages = max(1, min(_JT_MAX_PAGES, int(max_pages)))
        self.max_results = max(1, min(150, int(max_results)))
        self._fetch = fetch

    def discover_internships(
        self, source: dict[str, Any], *, selection_brief: dict[str, Any], deadline: float | None = None
    ) -> DiscoveryPayload:
        if not isinstance(source, dict) or source.get("provider") != "jobteaser":
            raise PublicSourceError("La source ne correspond pas au connecteur JobTeaser.", code="invalid_source")
        if not source.get("id") or not source.get("company") or not source.get("verified_at") or not source.get("provenance_url"):
            raise PublicSourceError("Une source officielle vérifiée est requise avant toute consultation.", code="unverified_source")

        brief = validate_brief(selection_brief) if selection_brief else default_brief()

        _HEALTH.raw_offers = 0
        _HEALTH.valid_offers = 0
        _HEALTH.finance_offers = 0
        _HEALTH.stage_offers = 0
        _HEALTH.conforming_offers = 0
        _HEALTH.to_verify_offers = 0

        raw_count = evaluated = invalid = confirmed = uncertain = excluded = relevant = filtered = 0
        ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        for raw in _iter_raw_offers(fetch=self._fetch):
            if deadline is not None and self.monotonic() >= deadline:
                raise PublicSourceError("Le budget de recherche est atteint.", code="budget")
            raw_count += 1
            if raw_count > _JT_MAX_ROWS:
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
        }


def register_jobteaser_connector(registry: dict[str, tuple]) -> None:
    """Register the JobTeaser connector."""
    registry["jobteaser"] = (JobTeaserConnector, "class")