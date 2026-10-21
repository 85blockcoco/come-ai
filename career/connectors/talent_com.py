"""Bounded read-only connector for Talent.com public job search.

Official career page: https://www.talent.com
Verified: 2026-10-20 (manual inspection of search endpoint and HTML structure)
Documentation: No public API; uses search HTML with structured data.
"""

from __future__ import annotations

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
from ..exploration import admit_offer, ranking_key
from ..source_fields import attach_source_material
from ..stage_search import default_brief, validate_brief

from .cards import card_attributes, published_fields, time_attribute


_TALENT_BASE = "https://www.talent.com"
_TALENT_SEARCH = _TALENT_BASE + "/jobs"
_TALENT_TIMEOUT = 15
_TALENT_MAX_PAGES = 5
_TALENT_RATE_LIMIT = 2.0
_TALENT_USER_AGENT = "ComeAI-StageBot/1.0"
_TALENT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TALENT_MAX_ROWS = 400


@dataclass
class TalentComHealth:
    last_ok: bool = False
    last_error: str | None = None
    consecutive_failures: int = 0
    raw_offers: int = 0
    valid_offers: int = 0
    finance_offers: int = 0
    stage_offers: int = 0
    conforming_offers: int = 0
    to_verify_offers: int = 0


_HEALTH = TalentComHealth()
_LAST_REQUEST_TIME = 0.0


class _TalentJobParser(HTMLParser):
    """Parse job cards from Talent.com search results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jobs: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._in_job_card = False
        self._current_field = ""
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in ("div", "article") and (
            "job-card" in attrs_dict.get("class", "") or
            attrs_dict.get("data-job-id") or
            attrs_dict.get("data-testid") == "job-card"
        ):
            self._in_job_card = True
            self._current = {
                "title": "",
                "company": "",
                "location": "",
                "contract_type": "",
                "url": "",
                "description": "",
                "attributes": card_attributes(attrs),
            }
            self._depth = 1
            if attrs_dict.get("data-job-id"):
                self._current["source_id"] = attrs_dict["data-job-id"]
        elif self._in_job_card:
            self._depth += 1
            if tag == "time":
                published = time_attribute(attrs)
                if published:
                    self._current.setdefault("attributes", {})["datetime"] = published
            elif tag == "a" and attrs_dict.get("href"):
                href = attrs_dict["href"]
                if "/job/" in href or "/view/" in href:
                    self._current["url"] = urllib.parse.urljoin(_TALENT_BASE, href)
            elif tag in ("h2", "h3", "h4", "span", "p", "div"):
                classes = attrs_dict.get("class", "").lower()
                testid = attrs_dict.get("data-testid", "").lower()
                itemprop = attrs_dict.get("itemprop", "").lower()
                if "title" in classes or "title" in testid or itemprop == "title":
                    self._current_field = "title"
                elif "company" in classes or "company" in testid or itemprop == "hiringOrganization":
                    self._current_field = "company"
                elif "location" in classes or "location" in testid or itemprop == "jobLocation":
                    self._current_field = "location"
                elif "contract" in classes or "type" in classes or "employment" in classes:
                    self._current_field = "contract_type"
                elif "description" in classes or "excerpt" in classes or "summary" in classes or itemprop == "description":
                    self._current_field = "description"

    def handle_endtag(self, tag: str) -> None:
        if self._in_job_card:
            self._depth -= 1
            if self._depth == 0 and tag in ("div", "article"):
                if self._current and self._current.get("title") and self._current.get("url"):
                    self.jobs.append(self._current)
                self._in_job_card = False
                self._current = None
                self._current_field = ""
            elif tag in ("h2", "h3", "h4", "span", "p", "div"):
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
    if elapsed < _TALENT_RATE_LIMIT:
        time.sleep(_TALENT_RATE_LIMIT - elapsed)
    _LAST_REQUEST_TIME = time.monotonic()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _TALENT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9,fr;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TALENT_TIMEOUT) as resp:
            body = resp.read(_TALENT_MAX_RESPONSE_BYTES + 1)
            if len(body) > _TALENT_MAX_RESPONSE_BYTES:
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


def _build_search_url(query: str, location: str, page: int) -> str:
    """Build Talent.com search URL with filters for finance internships outside France."""
    params = {
        "k": query,
        "l": location,
        "p": str(page),
        "contract": "internship",
    }
    query_string = urllib.parse.urlencode(params)
    return f"{_TALENT_SEARCH}?{query_string}"


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
    location: str = "Europe",
    fetch: Callable[[str], str | None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Iterate over raw internship offers from Talent.com."""
    fetch_fn = fetch or _default_fetch
    for page in range(1, _TALENT_MAX_PAGES + 1):
        url = _build_search_url(query, location, page)
        html = fetch_fn(url)
        if html is None:
            break

        parser = _TalentJobParser()
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

            job_id = raw.get("source_id") or urllib.parse.urlsplit(official_url).path.rstrip("/").rsplit("/", 1)[-1]
            if not job_id:
                job_id = str(hash(official_url))[-12:]

            yield attach_source_material({
                "company": company,
                "title": title,
                "source_name": "talent_com",
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
            }, "talent_com", published_fields(raw, raw.get("attributes")))

        if len(page_jobs) < 15:
            break

    _HEALTH.last_ok = True
    _HEALTH.last_error = None
    _HEALTH.consecutive_failures = 0


class TalentComConnector:
    """Talent.com connector implementing the InternshipConnector protocol."""

    def __init__(
        self,
        *,
        clock: Callable[[], str] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        max_pages: int = _TALENT_MAX_PAGES,
        max_results: int = 150,
        fetch: Callable[[str], str | None] | None = None,
        enabled: bool = False,
    ) -> None:
        self.enabled = enabled
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.max_pages = max(1, min(_TALENT_MAX_PAGES, int(max_pages)))
        self.max_results = max(1, min(150, int(max_results)))
        self._fetch = fetch

    def discover_internships(
        self, source: dict[str, Any], *, selection_brief: dict[str, Any], deadline: float | None = None
    ) -> DiscoveryPayload:
        if not isinstance(source, dict) or source.get("provider") != "talent_com":
            raise PublicSourceError("La source ne correspond pas au connecteur Talent.com.", code="invalid_source")
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
            if raw_count > _TALENT_MAX_ROWS:
                raise PublicSourceError("Le flux dépasse la limite d'offres évaluées.", code="too_many_rows")

            try:
                job = self._normalise_one(source, raw)
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


def register_talent_com_connector(registry: dict[str, tuple]) -> None:
    """Register the Talent.com connector."""
    registry["talent_com"] = (TalentComConnector, "class")