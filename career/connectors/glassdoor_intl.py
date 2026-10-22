"""Bounded read-only connector for the international pages of Glassdoor.

Official page: https://www.glassdoor.com/Job/jobs.htm
Documentation: no public API; the search returns HTML result cards.
Endpoint: https://www.glassdoor.com/Job/jobs.htm

The country filter is **native**: the search is asked for one country at a
time through its ``locId`` parameter, so an excluded country is never
requested.  The country is read again on the facts the source publishes, so
an offer that names an excluded country is dropped before it becomes a
local record.

The ``locId`` values are the country identifiers Glassdoor publishes in its
job-search URLs.  They are **best effort**: a portal may reorganise them.
That is why the canonical country read on the published location is the
guarantee, and the identifier is only the request parameter.  A source may
publish its own identifiers through ``location_ids``.

Rate limit: one request every five seconds, at most three pages, because
the portal publishes anti-automation rules and a slow reader is a welcome
one.  The reader identifies itself honestly and never rotates its identity
to look like somebody else.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Iterator

from ..models import clean_text
from .intl_common import (
    SOURCE_TIER_AGGREGATOR,
    CardSpec,
    IntlConnector,
    IntlHealth,
    JobCardParser,
    allowed_countries,
    build_job,
)

_GLASSDOOR_BASE = "https://www.glassdoor.com"
_GLASSDOOR_SEARCH = _GLASSDOOR_BASE + "/Job/jobs.htm"
_GLASSDOOR_TIMEOUT = 20
_GLASSDOOR_MAX_PAGES = 3
_GLASSDOOR_PAGE_SIZE = 30
_GLASSDOOR_RATE_LIMIT = 5.0
_GLASSDOOR_USER_AGENT = "ComeAI-Career/1.0 (read-only public job source)"

#: The country identifiers Glassdoor publishes in its job-search URLs.  They
#: are best effort and may be replaced by a source that publishes its own.
_GLASSDOOR_LOCATION_IDS: dict[str, int] = {
    "US": 1, "CA": 2, "GB": 3, "DE": 4, "FR": 5, "AU": 6, "IN": 7, "NL": 8,
    "CH": 9, "ES": 10, "IT": 11, "MX": 12, "NZ": 13, "BE": 14, "AT": 15,
    "PT": 16, "IE": 17, "DK": 18, "NO": 19, "SE": 20, "FI": 21, "PL": 22,
    "LU": 23, "SG": 24, "ZA": 25, "KR": 26, "JP": 27, "CN": 28, "HK": 29,
    "IL": 30, "TR": 31, "GR": 32, "CZ": 33,
}

#: The countries this source is read for.  France is absent on purpose: the
#: person never wants a French offer, and the connector must not spend a
#: request on it.
_GLASSDOOR_COUNTRIES: tuple[str, ...] = (
    "US", "CA", "GB", "DE", "NL", "CH", "BE", "AT", "IE", "SE", "NO", "DK",
    "FI", "ES", "IT", "PT", "PL", "LU", "AU", "NZ", "SG",
)

#: The result cards of the search page.
_GLASSDOOR_CARD = CardSpec(
    container_tag="li",
    container_class="react-job-listing",
    title_hints=("job-search-card__title", "jobtitle"),
    company_hints=("job-search-card__name", "companyname"),
    location_hints=("job-search-card__location", "location"),
    contract_hints=("job-search-card__type",),
    description_hints=("job-search-card__description",),
    link_class="job-search-card__link",
    link_hints=("/Job/", "-Job-ID-"),
)

_DEFAULT_KEYWORDS = "finance internship"


def _build_search_url(keywords: str, location_id: int, page: int) -> str:
    """Build one Glassdoor search URL for one country."""
    params = {
        "sc.keyword": keywords,
        # ``locT=C`` means "the location is a country".
        "locT": "C",
        "locId": str(location_id),
        "p": str(page),
    }
    return f"{_GLASSDOOR_SEARCH}?{urllib.parse.urlencode(params)}"


def _parse_cards(html: str) -> list[dict[str, Any]]:
    """Read the result cards of one Glassdoor search page."""
    parser = JobCardParser(_GLASSDOOR_CARD)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed remote HTML is untrusted data, not a reason to fail the
        # whole run: the cards read so far are kept.
        pass
    return parser.cards


def _job_id(url: str) -> str:
    """The identifier Glassdoor publishes in the job URL."""
    tail = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    marker = "-Job-ID-"
    if marker in tail:
        return tail.rsplit(marker, 1)[-1]
    return tail


class GlassdoorIntlConnector(IntlConnector):
    """Glassdoor search, read country by country outside France."""

    provider = "glassdoor_intl"
    documentation_url = "https://www.glassdoor.com/Job/jobs.htm"
    source_tier = SOURCE_TIER_AGGREGATOR
    hosts = frozenset({"www.glassdoor.com"})
    user_agent = _GLASSDOOR_USER_AGENT
    min_interval = _GLASSDOOR_RATE_LIMIT
    timeout = _GLASSDOOR_TIMEOUT
    #: The portal asks for a slow reader; the request bound keeps the run
    #: inside the network budget of the exploration, and the round-robin
    #: spreads the requests over the countries.
    max_requests = 4
    _HEALTH = IntlHealth()

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_pages", _GLASSDOOR_MAX_PAGES)
        super().__init__(**kwargs)

    def target_countries(self) -> tuple[str, ...]:
        """The country codes this source is read for."""
        return _GLASSDOOR_COUNTRIES

    def _location_ids(self, source: dict[str, Any]) -> dict[str, int]:
        """The country identifiers used for the requests."""
        identifiers = dict(_GLASSDOOR_LOCATION_IDS)
        published = source.get("location_ids")
        if isinstance(published, dict):
            for code, value in published.items():
                try:
                    identifiers[str(code).upper()] = int(value)
                except (TypeError, ValueError):
                    continue
        return identifiers

    def _keywords(self, source: dict[str, Any]) -> str:
        return clean_text(source.get("keywords"), limit=120) or _DEFAULT_KEYWORDS

    def _iter_offers(
        self, source: dict[str, Any], *, deadline: float | None, excluded: frozenset[str]
    ) -> Iterator[dict[str, Any]]:
        countries = allowed_countries(
            self.target_countries(), excluded, source.get("preferred_countries")
        )
        identifiers = self._location_ids(source)
        countries = [code for code in countries if code in identifiers]
        if not countries:
            return
        keywords = self._keywords(source)

        def build(code: str, start: int) -> str:
            page = start // _GLASSDOOR_PAGE_SIZE + 1
            return _build_search_url(keywords, identifiers[code], page)

        yield from self._iter_by_country(
            countries,
            deadline=deadline,
            build_url=build,
            parse_page=_parse_cards,
            page_size=_GLASSDOOR_PAGE_SIZE,
        )

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        location = raw.get("location", "")
        url = raw.get("url", "")
        if url.startswith("/"):
            url = f"{_GLASSDOOR_BASE}{url}"
        return build_job(
            provider=self.provider,
            source_tier=self.source_tier,
            title=raw.get("title"),
            company=raw.get("company"),
            url=url,
            location_text=location,
            country_structural=raw.get("country"),
            country_hint=raw.get("country_hint", ""),
            contract_type=raw.get("contract_type") or "Internship",
            description=raw.get("description"),
            posted_date=raw.get("posted_date"),
            source_id=_job_id(url),
            employment_type=raw.get("contract_type") or "Internship",
        )


def register_glassdoor_intl_connector(registry: dict[str, tuple]) -> None:
    """Register the Glassdoor International connector."""
    registry["glassdoor_intl"] = (GlassdoorIntlConnector, "class")


__all__ = [
    "GlassdoorIntlConnector",
    "register_glassdoor_intl_connector",
]
