"""Bounded read-only connector for the EURES public job search API.

Official page: https://ec.europa.eu/eures/eures-job-search
API documentation: https://ec.europa.eu/eures/eures-api/swagger-ui.html
Endpoint: https://ec.europa.eu/eures/eures-api/search
Source tier: ``official`` — EURES is a public service of the European
Commission, not a commercial portal.

The country filter is **native**: the ``countryCodes`` parameter carries the
allowed countries only, so an excluded country is never part of a request.
The country is read again on the facts the source publishes — EURES states
it structurally in ``location.countryCode`` — so an offer that names an
excluded country is dropped before it becomes a local record.

The service is public and generous: the interval between two requests is
one second, and the answers are small, structured documents.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date, datetime, timezone
from typing import Any, Iterator

from ..models import clean_text
from .intl_common import (
    SOURCE_TIER_OFFICIAL,
    IntlConnector,
    IntlHealth,
    allowed_countries,
    build_job,
    parse_location,
)

_EURES_API = "https://ec.europa.eu/eures/eures-api/search"
_EURES_TIMEOUT = 15
_EURES_MAX_PAGES = 5
_EURES_PAGE_SIZE = 100
_EURES_MAX_ROWS = 400
_EURES_RATE_LIMIT = 1.0
_EURES_USER_AGENT = "ComeAI-Career/1.0 (EURES public API)"

#: The countries EURES publishes for, France excluded.  France is read from
#: the same list when the person explicitly asks for it again.
_EURES_DEFAULT_COUNTRIES: tuple[str, ...] = (
    "DE", "GB", "NL", "BE", "LU", "CH", "IE", "AT", "SE", "NO", "DK", "FI",
    "ES", "IT", "PT", "PL", "CZ", "HU", "RO", "BG", "HR", "SI", "SK", "EE",
    "LV", "LT", "MT", "CY", "IS", "LI",
)

#: The contract types EURES publishes, read as the source writes them.
_CONTRACT_TYPES = {
    "INTERNSHIP": "Internship",
    "INTERNSHIP_WITHOUT_TRAINING": "Internship",
    "TRAINEE": "Traineeship",
    "TRAINING": "Traineeship",
}


def _build_search_url(country_codes: list[str], page: int, page_size: int) -> str:
    """Build one EURES search URL for the allowed countries."""
    params = {
        "language": "en",
        "countryCodes": ",".join(country_codes),
        "pageSize": str(page_size),
        "pageNumber": str(page),
    }
    return f"{_EURES_API}?{urllib.parse.urlencode(params)}"


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    """Read the offers of one EURES answer.

    The public API has published more than one envelope over time; every
    shape that carries a list of offers is read, and an unknown shape yields
    no offer rather than a wrong one.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "offers", "jobs"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for envelope in ("result", "results", "data"):
        value = payload.get(envelope)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for key in ("items", "results", "offers", "jobs"):
                nested = value.get(key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return []


def _iso_date(value: Any) -> str:
    """Read a date EURES publishes, as an ISO day.

    EURES publishes both ISO days and epoch milliseconds.  A date that
    cannot be read stays empty: a missing date is an unknown fact.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000.0 if float(value) > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = clean_text(value, limit=40)
    if not text:
        return ""
    if text.isdigit():
        return _iso_date(int(text))
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return ""


def _duration_months(value: Any) -> int | None:
    """Read the duration EURES publishes, in months."""
    if value is None or value == "":
        return None
    try:
        months = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return months if 1 <= months <= 24 else None


def _employer_name(item: dict[str, Any]) -> str:
    """Read the employer EURES publishes, whichever field carries it."""
    for key in ("employerName", "companyName", "employer", "company"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            nested = value.get("name") or value.get("companyName")
            if isinstance(nested, str) and nested.strip():
                return nested
    return ""


def _location_parts(item: dict[str, Any]) -> tuple[str, str, str]:
    """Read the city, the country wording and the structural country code."""
    location = item.get("location")
    country_code = ""
    city = ""
    country = ""
    if isinstance(location, dict):
        city = clean_text(location.get("city") or location.get("name"), limit=160)
        country = clean_text(location.get("countryName") or location.get("country"), limit=120)
        country_code = clean_text(location.get("countryCode"), limit=8)
    elif isinstance(location, str):
        city, country = parse_location(location)
    if not city and isinstance(item.get("city"), str):
        city = clean_text(item.get("city"), limit=160)
    if not country and isinstance(item.get("countryName"), str):
        country = clean_text(item.get("countryName"), limit=120)
    if not country_code and isinstance(item.get("countryCode"), str):
        country_code = clean_text(item.get("countryCode"), limit=8)
    return city, country, country_code


class EuresConnector(IntlConnector):
    """EURES public job search, read for the allowed countries only."""

    provider = "eures"
    documentation_url = "https://ec.europa.eu/eures/eures-api/swagger-ui.html"
    source_tier = SOURCE_TIER_OFFICIAL
    hosts = frozenset({"ec.europa.eu"})
    user_agent = _EURES_USER_AGENT
    accept = "application/json,text/html;q=0.9,*/*;q=0.8"
    min_interval = _EURES_RATE_LIMIT
    timeout = _EURES_TIMEOUT
    _HEALTH = IntlHealth()

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_pages", _EURES_MAX_PAGES)
        super().__init__(**kwargs)

    def target_countries(self) -> tuple[str, ...]:
        """The country codes this source is read for."""
        return _EURES_DEFAULT_COUNTRIES

    def _iter_offers(
        self, source: dict[str, Any], *, deadline: float | None, excluded: frozenset[str]
    ) -> Iterator[dict[str, Any]]:
        countries = allowed_countries(
            self.target_countries(), excluded, source.get("preferred_countries")
        )
        if not countries:
            return
        page = 1
        while page <= self.max_pages and self._requests < self.max_requests:
            if not self._budget_left(deadline):
                self._HEALTH.budget_exhausted = True
                return
            body = self._read(_build_search_url(countries, page, _EURES_PAGE_SIZE))
            if body is None:
                return
            try:
                payload = json.loads(body)
            except (TypeError, ValueError):
                self._HEALTH.last_error = "Réponse EURES illisible"
                self._HEALTH.last_ok = False
                return
            items = _extract_items(payload)
            if not items:
                return
            for item in items:
                yield item
            if len(items) < _EURES_PAGE_SIZE:
                return
            page += 1

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("An EURES offer is not an object.")
        title = raw.get("title") or raw.get("positionTitle")
        employer = _employer_name(raw)
        url = (
            raw.get("applicationUrl")
            or raw.get("externalApplicationUrl")
            or raw.get("url")
            or raw.get("jobUrl")
        )
        if not url:
            raise ValueError("An EURES offer without an application URL is not usable.")
        city, country, country_code = _location_parts(raw)
        location_text = ", ".join(part for part in (city, country) if part)
        contract = clean_text(raw.get("contractType") or raw.get("typeOfContract"), limit=120)
        contract_label = _CONTRACT_TYPES.get(contract.upper(), contract)
        return build_job(
            provider=self.provider,
            source_tier=self.source_tier,
            title=title,
            company=employer,
            url=url,
            location_text=location_text,
            country_structural=country_code,
            country_hint=raw.get("country_hint", ""),
            contract_type=contract_label,
            description=raw.get("description"),
            posted_date=_iso_date(raw.get("publicationDate") or raw.get("publishedDate")),
            start_date=_iso_date(raw.get("startDate")),
            end_date=_iso_date(raw.get("endDate")),
            duration_months=_duration_months(raw.get("duration")),
            source_id=raw.get("id") or raw.get("referenceNumber"),
            employment_type=contract_label,
        )


def register_eures_connector(registry: dict[str, tuple]) -> None:
    """Register the EURES connector."""
    registry["eures"] = (EuresConnector, "class")


__all__ = [
    "EuresConnector",
    "register_eures_connector",
]
