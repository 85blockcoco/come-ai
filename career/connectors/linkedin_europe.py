"""Bounded read-only connector for the public LinkedIn guest job search.

Official page: https://www.linkedin.com/jobs/search
Guest endpoint: https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
Documentation: no public API; the guest search returns an HTML fragment of
result cards.  The endpoint and the card structure were observed on the
public search page (2026-10-22) and are re-read defensively: an unknown
class name yields fewer facts, never wrong ones.

The country filter is **native**: the search is asked for one country at a
time through its ``location`` parameter, so an excluded country is never
requested and never costs a request.  The country is read again on the facts
the source publishes, so an offer that names an excluded country is dropped
before it becomes a local record.

Rate limit: one request every three seconds, at most ten pages per country
and a bounded number of requests per run.
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

_LINKEDIN_BASE = "https://www.linkedin.com"
_LINKEDIN_JOBS_SEARCH = _LINKEDIN_BASE + "/jobs-guest/jobs/api/seeMoreJobPostings/search"
_LINKEDIN_TIMEOUT = 15
_LINKEDIN_MAX_PAGES = 10
_LINKEDIN_PAGE_SIZE = 25
_LINKEDIN_RATE_LIMIT = 3.0
_LINKEDIN_USER_AGENT = "ComeAI-Career/1.0 (read-only public job source)"

#: The countries this source is read for, and the wording LinkedIn publishes
#: for them in its ``location`` parameter.  A country that is not in this
#: list is never requested: the source is asked, country by country, for the
#: places where the offers are wanted.
_LINKEDIN_LOCATIONS: dict[str, str] = {
    "DE": "Germany",
    "GB": "United Kingdom",
    "NL": "Netherlands",
    "CH": "Switzerland",
    "BE": "Belgium",
    "LU": "Luxembourg",
    "IE": "Ireland",
    "AT": "Austria",
    "SE": "Sweden",
    "NO": "Norway",
    "DK": "Denmark",
    "FI": "Finland",
    "ES": "Spain",
    "IT": "Italy",
    "PT": "Portugal",
    "PL": "Poland",
}

#: The guest search cards.
_LINKEDIN_CARD = CardSpec(
    container_tag="div",
    container_class="base-search-card",
    title_hints=("base-search-card__title", "job-search-card__title"),
    company_hints=("base-search-card__subtitle", "job-search-card__name"),
    location_hints=("job-search-card__location",),
    contract_hints=("job-search-card__type",),
    description_hints=("job-search-card__description",),
    link_class="base-card__full-link",
    time_attr="datetime",
)

#: The keyword the search starts from; a source may publish its own.
_DEFAULT_KEYWORDS = "finance internship"

#: The contract the search asks for: an internship.
_CONTRACT_TYPE = "Internship"


def _build_search_url(keywords: str, location: str, start: int) -> str:
    """Build one guest search URL for one country."""
    params = {
        "keywords": keywords,
        "location": location,
        # ``f_TPR``: the postings published in the last seven days.
        "f_TPR": "r604800",
        # ``f_WT``: the internship work type.
        "f_WT": "4",
        # ``f_E``: the internship experience level.
        "f_E": "1",
        "start": str(start),
    }
    return f"{_LINKEDIN_JOBS_SEARCH}?{urllib.parse.urlencode(params)}"


def _parse_cards(html: str) -> list[dict[str, Any]]:
    """Read the result cards of one guest search page."""
    parser = JobCardParser(_LINKEDIN_CARD)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed remote HTML is untrusted data, not a reason to fail the
        # whole run: the cards read so far are kept.
        pass
    return parser.cards


def _job_id(url: str) -> str:
    """The identifier LinkedIn publishes in the job URL."""
    path = url.split("?", 1)[0].rstrip("/")
    tail = path.rsplit("/", 1)[-1]
    digits = "".join(character for character in tail if character.isdigit())
    return digits or tail


class LinkedInEuropeConnector(IntlConnector):
    """LinkedIn guest search, read country by country outside France."""

    provider = "linkedin_europe"
    documentation_url = "https://www.linkedin.com/jobs/search"
    source_tier = SOURCE_TIER_AGGREGATOR
    hosts = frozenset({"www.linkedin.com"})
    user_agent = _LINKEDIN_USER_AGENT
    min_interval = _LINKEDIN_RATE_LIMIT
    timeout = _LINKEDIN_TIMEOUT
    #: Sixteen countries are read for; the request bound keeps the run inside
    #: the network budget of the exploration, and the round-robin spreads the
    #: requests over the countries instead of giving them all to the first.
    max_requests = 8
    _HEALTH = IntlHealth()

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_pages", _LINKEDIN_MAX_PAGES)
        super().__init__(**kwargs)

    def target_countries(self) -> dict[str, str]:
        """The country codes this source is read for."""
        return dict(_LINKEDIN_LOCATIONS)

    def _keywords(self, source: dict[str, Any]) -> str:
        return clean_text(source.get("keywords"), limit=120) or _DEFAULT_KEYWORDS

    def _iter_offers(
        self, source: dict[str, Any], *, deadline: float | None, excluded: frozenset[str]
    ) -> Iterator[dict[str, Any]]:
        countries = allowed_countries(
            self.target_countries(), excluded, source.get("preferred_countries")
        )
        if not countries:
            return
        keywords = self._keywords(source)
        locations = self.target_countries()

        def build(code: str, start: int) -> str:
            return _build_search_url(keywords, locations[code], start)

        yield from self._iter_by_country(
            countries,
            deadline=deadline,
            build_url=build,
            parse_page=_parse_cards,
            page_size=_LINKEDIN_PAGE_SIZE,
        )

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        hint = raw.get("country_hint", "")
        location = raw.get("location", "")
        url = raw.get("url", "")
        if url.startswith("/"):
            url = f"{_LINKEDIN_BASE}{url}"
        return build_job(
            provider=self.provider,
            source_tier=self.source_tier,
            title=raw.get("title"),
            company=raw.get("company"),
            url=url,
            location_text=location,
            country_structural=raw.get("country"),
            country_hint=hint,
            contract_type=raw.get("contract_type") or _CONTRACT_TYPE,
            description=raw.get("description"),
            posted_date=raw.get("posted_date"),
            source_id=_job_id(url),
            employment_type=raw.get("contract_type") or _CONTRACT_TYPE,
        )


def register_linkedin_europe_connector(registry: dict[str, tuple]) -> None:
    """Register the LinkedIn Europe connector."""
    registry["linkedin_europe"] = (LinkedInEuropeConnector, "class")


__all__ = [
    "LinkedInEuropeConnector",
    "register_linkedin_europe_connector",
]
