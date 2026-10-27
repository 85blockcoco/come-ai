"""Bounded read-only connector for the international pages of JobTeaser.

Official page: https://www.jobteaser.com/en/jobs
Documentation: no public API; the search returns HTML result cards.
Endpoint: https://www.jobteaser.com/en/jobs

This connector is the international face of the JobTeaser portal: the same
search page, read for the countries where the person wants an internship
instead of France.  The French connector (``career/connectors/jobteaser.py``)
keeps its own endpoint; both read the same portal, with different country
filters.

The country filter is **native**: the allowed countries travel in the
``countries`` parameter, so an excluded country is never part of a request.
The country is read again on the facts the source publishes, so an offer
that names an excluded country is dropped before it becomes a local record.

Rate limit: one request every two seconds, at most five pages.
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

_JOBTEASER_BASE = "https://www.jobteaser.com"
_JOBTEASER_SEARCH = _JOBTEASER_BASE + "/en/jobs"
_JOBTEASER_TIMEOUT = 15
_JOBTEASER_MAX_PAGES = 5
_JOBTEASER_PAGE_SIZE = 15
_JOBTEASER_RATE_LIMIT = 2.0
_JOBTEASER_USER_AGENT = "ComeAI-Career/1.0 (read-only public job source)"

#: The countries this source is read for, France excluded.
_JOBTEASER_COUNTRIES: tuple[str, ...] = ("DE", "GB", "NL", "BE", "CH", "ES", "IT", "PT")

#: The result cards of the search page.
_JOBTEASER_CARD = CardSpec(
    container_tag="article",
    container_class="job-card",
    title_hints=("title",),
    company_hints=("company", "employer"),
    location_hints=("location", "city"),
    contract_hints=("contract", "type"),
    description_hints=("description", "excerpt", "summary"),
    link_hints=("/jobs/", "/offers/"),
)

_DEFAULT_KEYWORDS = "finance internship"


def _build_search_url(keywords: str, countries: list[str], page: int) -> str:
    """Build one JobTeaser search URL for the allowed countries."""
    params = {
        "query": keywords,
        "page": str(page),
        "contract_type": "internship",
        "countries": ",".join(countries),
    }
    return f"{_JOBTEASER_SEARCH}?{urllib.parse.urlencode(params)}"


def _parse_cards(html: str) -> list[dict[str, Any]]:
    """Read the result cards of one JobTeaser search page."""
    parser = JobCardParser(_JOBTEASER_CARD)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed remote HTML is untrusted data, not a reason to fail the
        # whole run: the cards read so far are kept.
        pass
    return parser.cards


class JobTeaserIntlConnector(IntlConnector):
    """JobTeaser international search, read for the allowed countries only."""

    provider = "jobteaser_intl"
    documentation_url = "https://www.jobteaser.com/en/jobs"
    source_tier = SOURCE_TIER_AGGREGATOR
    hosts = frozenset({"www.jobteaser.com"})
    user_agent = _JOBTEASER_USER_AGENT
    min_interval = _JOBTEASER_RATE_LIMIT
    timeout = _JOBTEASER_TIMEOUT
    _HEALTH = IntlHealth()

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_pages", _JOBTEASER_MAX_PAGES)
        super().__init__(**kwargs)

    def target_countries(self) -> tuple[str, ...]:
        """The country codes this source is read for."""
        return _JOBTEASER_COUNTRIES

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
        for page in range(1, self.max_pages + 1):
            if self._requests >= self.max_requests:
                return
            if not self._budget_left(deadline):
                self._HEALTH.budget_exhausted = True
                return
            body = self._read(_build_search_url(keywords, countries, page))
            if body is None:
                return
            cards = _parse_cards(body)
            if not cards:
                return
            for card in cards:
                yield card
            if len(cards) < _JOBTEASER_PAGE_SIZE:
                return

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        location = raw.get("location", "")
        url = raw.get("url", "")
        if url.startswith("/"):
            url = f"{_JOBTEASER_BASE}{url}"
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
            source_id=url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1],
            employment_type=raw.get("contract_type") or "Internship",
        )


def register_jobteaser_intl_connector(registry: dict[str, tuple]) -> None:
    """Register the JobTeaser International connector."""
    registry["jobteaser_intl"] = (JobTeaserIntlConnector, "class")


__all__ = [
    "JobTeaserIntlConnector",
    "register_jobteaser_intl_connector",
]
