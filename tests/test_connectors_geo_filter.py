"""Source-side country exclusion: no connector may return an excluded offer.

Every corpus here is synthetic and offline: no socket is opened, no live
board is read.  The invariant under test is the product one — the person
never wants French offers, so a French posting is refused *by the
connector*, before it becomes an offer and before it reaches the database.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from career.connectors.apec import ApecConnector
from career.connectors.jobteaser import JobTeaserConnector
from career.connectors.public_ats import AshbyConnector, LeverConnector, SmartRecruitersConnector
from career.connectors.talent_com import TalentComConnector
from career.connectors.welcome_jungle import WelcomeJungleConnector
from career.discovery import (
    GREENHOUSE_MAX_JOBS,
    GreenhouseBoard,
    GreenhouseJobBoardConnector,
    split_location,
)
from career.stage_search import (
    canonical_country_codes,
    canonicalize_country,
    default_brief,
    resolve_countries,
    validate_brief,
)
from career.stage_search import vocabulary as stage_search_vocabulary


BOARD = GreenhouseBoard(id="synthetic-board", company="Synthetic Bank", board_token="synthetic-bank")


# ---------------------------------------------------------------------------
# Offline doubles
# ---------------------------------------------------------------------------


class FixtureTransport:
    """Greenhouse/ATS transport double; it records the endpoints it is asked for."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_json(self, endpoint: str, timeout_seconds: int) -> Any:
        self.calls.append(endpoint)
        return self.payload


class FixtureFetch:
    """HTML fetch double for the public job boards."""

    def __init__(self, html_responses: list[str]) -> None:
        self.responses = list(html_responses)
        self.calls: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("fixture fetch exhausted")
        return self.responses.pop(0)


def source(provider: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"synthetic:{provider}:board",
        "provider": provider,
        "company": "Synthetic Finance",
        "board_token": "synthetic-board",
        "verified_at": "2026-10-20T00:00:00Z",
        "provenance_url": "https://careers.example.test/",
    } | extra


def greenhouse_job(identifier: str, location: str, *, title: str = "Corporate Finance Intern") -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "absolute_url": f"https://careers.example.test/jobs/{identifier}",
        "location": {"name": location},
        "content": "<p>Six-month finance internship with financial analysis and valuation.</p>",
    }


def build_html(provider: str, cards: list[dict[str, Any]]) -> str:
    """Build one synthetic card per posting, in the markup each board uses."""
    if provider == "welcome_jungle":
        body = "".join(
            f'<article data-testid="job-card"><h3 data-testid="job-title">{card["title"]}</h3>'
            f'<span data-testid="company">{card["company"]}</span>'
            f'<span data-testid="location">{card["location"]}</span>'
            f'<span data-testid="contract">{card["contract_type"]}</span>'
            f'<a href="{card["url"].replace("https://www.welcometothejungle.com", "")}"></a>'
            f'<div data-testid="description">{card["description"]}</div></article>'
            for card in cards
        )
    elif provider == "jobteaser":
        body = "".join(
            f'<article class="job-card"><h3 class="title">{card["title"]}</h3>'
            f'<span class="company">{card["company"]}</span>'
            f'<span class="location">{card["location"]}</span>'
            f'<span class="contract">{card["contract_type"]}</span>'
            f'<a href="{card["url"].replace("https://www.jobteaser.com", "")}"></a>'
            f'<div class="description">{card["description"]}</div></article>'
            for card in cards
        )
    elif provider == "talent_com":
        body = "".join(
            f'<div class="job-card" data-job-id="{card.get("source_id", "")}"><h2 class="title">{card["title"]}</h2>'
            f'<span class="company">{card["company"]}</span>'
            f'<span class="location">{card["location"]}</span>'
            f'<span class="contract">{card["contract_type"]}</span>'
            f'<a href="{card["url"].replace("https://www.talent.com", "")}"></a>'
            f'<div class="description">{card["description"]}</div></div>'
            for card in cards
        )
    else:
        body = "".join(
            f'<div class="job-result" data-offer-id="{card.get("source_id", "")}"><h2 class="title">{card["title"]}</h2>'
            f'<span class="entreprise">{card["company"]}</span>'
            f'<span class="lieu">{card["location"]}</span>'
            f'<span class="contrat">{card["contract_type"]}</span>'
            f'<a href="{card["url"].replace("https://www.apec.fr", "")}"></a>'
            f'<div class="description">{card["description"]}</div></div>'
            for card in cards
        )
    return f"<html><body>{body}</body></html>"


def card(identifier: str, location: str, *, provider: str = "welcome_jungle") -> dict[str, Any]:
    """One synthetic posting, in the URL shape its own board publishes."""
    urls = {
        "welcome_jungle": f"https://www.welcometothejungle.com/fr/companies/synthetic-finance/jobs/{identifier}",
        "jobteaser": f"https://www.jobteaser.com/en/jobs/{identifier}",
        "talent_com": f"https://www.talent.com/job/{identifier}",
        "apec": f"https://www.apec.fr/emploi/{identifier}",
    }
    return {
        "title": f"Corporate Finance Intern {identifier}",
        "company": "Synthetic Finance",
        "location": location,
        "contract_type": "Internship",
        "url": urls[provider],
        "description": "<p>Six-month finance internship with financial analysis and valuation.</p>",
    }


def html_connector(provider: str, fetch: FixtureFetch):
    if provider == "welcome_jungle":
        return WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    if provider == "jobteaser":
        return JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    if provider == "talent_com":
        return TalentComConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    return ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)


# ---------------------------------------------------------------------------
# The country vocabulary
# ---------------------------------------------------------------------------


def test_canonicalize_country_fr_variants() -> None:
    """Every spelling a source may use for France reads as the same country."""
    for spelling in ("FR", "fr", "Fr", "FRA", "fra", "France", "france", "FRANCE",
                      "French Republic", "République française"):
        assert canonicalize_country(spelling) == "FR", spelling


def test_case_insensitive() -> None:
    """The person's own list is read whatever case it is written in."""
    assert canonical_country_codes(["fr"]) == ["FR"]
    assert canonical_country_codes(["Fr"]) == ["FR"]
    assert canonical_country_codes(["FR"]) == ["FR"]
    assert canonical_country_codes(["france"]) == ["FR"]


def test_frankfurt_not_excluded() -> None:
    """"Frankfurt" is a German city: it must never be read as France."""
    assert canonicalize_country("Frankfurt") == ""
    assert resolve_countries("Frankfurt") == ()
    assert resolve_countries("Frankfurt, Germany") == ("DE",)
    assert canonicalize_country("Frankfurt am Main") == ""


def test_unknown_country_is_never_invented() -> None:
    """A city is not a country: an unnamed country stays unknown."""
    assert resolve_countries("Paris") == ()
    assert canonicalize_country("Paris") == ""


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------


def test_greenhouse_excludes_france() -> None:
    transport = FixtureTransport({"jobs": [
        greenhouse_job("paris-role", "Paris, France"),
        greenhouse_job("london-role", "London, United Kingdom"),
    ]})
    connector = GreenhouseJobBoardConnector(transport)
    result = connector.discover_ranked(BOARD, selection_brief=default_brief())
    assert [job["source_id"] for job in result.jobs] == ["london-role"]
    assert all(job["country"] != "France" for job in result.jobs)


def test_greenhouse_office_country_code() -> None:
    """A board that only names the city is read through its office country."""
    payload = {"jobs": [{
        "id": "paris-office",
        "title": "Corporate Finance Intern",
        "absolute_url": "https://careers.example.test/jobs/paris-office",
        "location": {"name": "Paris"},
        "offices": [{"name": "Paris", "location": "Paris, France"}],
        "content": "<p>Six-month finance internship.</p>",
    }]}
    connector = GreenhouseJobBoardConnector(FixtureTransport(payload))
    result = connector.discover_ranked(BOARD, selection_brief=default_brief())
    assert result.jobs == ()
    assert connector.health_check()["excluded_by_country"] == {"FR": 1}


def test_greenhouse_publishes_the_canonical_country() -> None:
    transport = FixtureTransport({"jobs": [greenhouse_job("london-role", "London, United Kingdom")]})
    connector = GreenhouseJobBoardConnector(transport)
    result = connector.discover_ranked(BOARD, selection_brief=default_brief())
    assert result.jobs[0]["country_canonical"] == "GB"
    assert result.jobs[0]["country"] == "United Kingdom"


# ---------------------------------------------------------------------------
# The four public job boards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["welcome_jungle", "jobteaser", "talent_com", "apec"])
def test_boards_exclude_france(provider: str) -> None:
    fetch = FixtureFetch([build_html(provider, [
        card("paris", "Paris, France", provider=provider),
        card("london", "London, United Kingdom", provider=provider),
    ])])
    connector = html_connector(provider, fetch)
    result = connector.discover_internships(source(provider), selection_brief=default_brief())
    assert [job["source_id"] for job in result.jobs] == ["london"]
    for job in result.jobs:
        assert job["country_canonical"] == "GB"
        assert job["country"].lower() not in {"france", "fr"}


def test_welcome_jungle_excludes_france() -> None:
    """WJ reads the board country code and double-checks the card itself."""
    fetch = FixtureFetch([build_html("welcome_jungle", [
        card("paris", "Paris, France"),
        card("london", "London, United Kingdom"),
    ])])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    assert [job["source_id"] for job in result.jobs] == ["london"]
    health = WelcomeJungleConnector.health_check()
    assert health["excluded_by_country"] == {"FR": 1}
    assert health["excluded_count"] == 1


def test_jobteaser_excludes_france() -> None:
    fetch = FixtureFetch([build_html("jobteaser", [
        card("paris", "Paris, France", provider="jobteaser"),
        card("london", "London, UK", provider="jobteaser"),
    ])])
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    assert [job["source_id"] for job in result.jobs] == ["london"]
    assert JobTeaserConnector.health_check()["excluded_by_country"] == {"FR": 1}


def test_talent_com_excludes_france() -> None:
    fetch = FixtureFetch([build_html("talent_com", [
        card("paris", "Paris, France", provider="talent_com"),
        card("zurich", "Zurich, Switzerland", provider="talent_com"),
    ])])
    connector = TalentComConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    assert [job["source_id"] for job in result.jobs] == ["zurich"]
    assert TalentComConnector.health_check()["excluded_by_country"] == {"FR": 1}


def test_apec_excludes_france() -> None:
    fetch = FixtureFetch([build_html("apec", [
        card("paris", "Paris, France", provider="apec"),
        card("geneve", "Genève, Suisse", provider="apec"),
    ])])
    connector = ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("apec"), selection_brief=default_brief())
    assert [job["source_id"] for job in result.jobs] == ["geneve"]
    assert ApecConnector.health_check()["excluded_by_country"] == {"FR": 1}


# ---------------------------------------------------------------------------
# The public ATS connectors
# ---------------------------------------------------------------------------


def test_public_ats_excludes_france() -> None:
    """Lever, Ashby and SmartRecruiters all refuse a French posting."""
    lever = FixtureTransport([{
        "id": "synthetic-lever-paris",
        "text": "Finance Intern",
        "categories": {"location": "Paris, France", "commitment": "Intern"},
        "country": "FR",
        "descriptionPlain": "Synthetic internship description.",
        "hostedUrl": "https://jobs.lever.co/synthetic-board/synthetic-lever-paris",
    }])
    connector = LeverConnector(transport=lever, enabled=True)
    result = connector.discover_internships(source("lever"), selection_brief=default_brief())
    assert result.jobs == ()
    assert connector.health_check()["excluded_by_country"] == {"FR": 1}

    ashby = FixtureTransport({"jobs": [{
        "title": "Finance Intern",
        "location": "Paris, France",
        "address": {"postalAddress": {"addressCountry": "France"}},
        "jobUrl": "https://jobs.ashbyhq.com/synthetic-board/synthetic-ashby-paris",
        "isListed": True,
    }]})
    connector = AshbyConnector(transport=ashby, enabled=True)
    result = connector.discover_internships(source("ashby"), selection_brief=default_brief())
    assert result.jobs == ()
    assert connector.health_check()["excluded_by_country"] == {"FR": 1}

    smartrecruiters = FixtureTransport({"content": [{
        "id": "synthetic-sr-paris",
        "name": "Finance Intern",
        "location": {"city": "Paris", "country": "FR"},
        "applyUrl": "https://jobs.smartrecruiters.com/synthetic-board/synthetic-sr-paris",
    }]})
    connector = SmartRecruitersConnector(transport=smartrecruiters, enabled=True)
    result = connector.discover_internships(source("smartrecruiters"), selection_brief=default_brief())
    assert result.jobs == ()
    assert connector.health_check()["excluded_by_country"] == {"FR": 1}


def test_welcome_jungle_drops_the_excluded_country_from_the_request() -> None:
    """The board itself is asked for other countries: no French download."""
    fetch = FixtureFetch([build_html("welcome_jungle", [card("london", "London, United Kingdom")])])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    codes = parse_qs(urlsplit(fetch.calls[0]).query)["refinementList[office.country_code][]"]
    assert "FR" not in codes
    assert "GB" in codes


def test_jobteaser_drops_the_excluded_country_from_the_request() -> None:
    """JobTeaser is asked for other countries only."""
    fetch = FixtureFetch([build_html("jobteaser", [card("london", "London, UK", provider="jobteaser")])])
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    codes = parse_qs(urlsplit(fetch.calls[0]).query)["countries[]"]
    assert "FR" not in codes
    assert "GB" in codes


def test_reopening_france_asks_the_board_for_france_again() -> None:
    """An explicit empty list reopens France, request included."""
    fetch = FixtureFetch([build_html("welcome_jungle", [card("paris", "Paris, France")])])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief={"countries_exclude": []})
    codes = parse_qs(urlsplit(fetch.calls[0]).query)["refinementList[office.country_code][]"]
    assert "FR" in codes
    assert [job["source_id"] for job in result.jobs] == ["paris"]


def test_vocabulary_exposes_the_country_exclusion() -> None:
    """The interface can render the source-side country exclusion."""
    vocabulary = stage_search_vocabulary()
    assert vocabulary["countries_exclude"]["default"] == ["FR"]
    assert "FR" in vocabulary["countries_exclude"]["available"]
    assert "GB" in vocabulary["countries_exclude"]["available"]


@pytest.mark.parametrize("location,expected", [
    ("Paris, France", ["Paris", "France"]),
    ("Paris - France", ["Paris", "France"]),
    ("Paris (France)", ["Paris", "France"]),
    ("Paris/France", ["Paris", "France"]),
    ("Saint-Étienne, France", ["Saint-Étienne", "France"]),
    ("Paris", ["Paris"]),
])
def test_locations_are_split_on_the_shared_separators(location: str, expected: list[str]) -> None:
    """Every board reads a location the same way, dash included."""
    assert split_location(location) == expected


def test_dashed_location_is_excluded_like_a_comma_one() -> None:
    """A source that writes "Paris - France" is filtered like "Paris, France"."""
    fetch = FixtureFetch([build_html("welcome_jungle", [card("paris", "Paris - France")])])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    assert result.jobs == ()
    assert WelcomeJungleConnector.health_check()["excluded_by_country"] == {"FR": 1}


# ---------------------------------------------------------------------------
# The default and the override
# ---------------------------------------------------------------------------


def test_default_is_fr_excluded() -> None:
    """Without a brief, France is excluded: the person never wants it."""
    assert default_brief()["countries_exclude"] == ["FR"]
    assert validate_brief({})["countries_exclude"] == ["FR"]
    transport = FixtureTransport({"jobs": [greenhouse_job("paris-role", "Paris, France")]})
    connector = GreenhouseJobBoardConnector(transport)
    assert connector.discover_ranked(BOARD).jobs == ()
    assert connector.discover_internships(BOARD, selection_brief={}).jobs == ()


def test_countries_exclude_empty() -> None:
    """An explicitly empty list excludes nothing at all."""
    assert validate_brief({"countries_exclude": []})["countries_exclude"] == []
    transport = FixtureTransport({"jobs": [greenhouse_job("paris-role", "Paris, France")]})
    connector = GreenhouseJobBoardConnector(transport)
    result = connector.discover_ranked(BOARD, selection_brief={"countries_exclude": []})
    assert [job["source_id"] for job in result.jobs] == ["paris-role"]
    assert connector.health_check()["excluded_count"] == 0


def test_override_via_brief() -> None:
    """The person can reopen France from the search brief."""
    transport = FixtureTransport({"jobs": [greenhouse_job("paris-role", "Paris, France")]})
    connector = GreenhouseJobBoardConnector(transport)
    result = connector.discover_ranked(BOARD, selection_brief={"countries_exclude": []})
    assert [job["source_id"] for job in result.jobs] == ["paris-role"]
    assert result.jobs[0]["country_canonical"] == "FR"


def test_brief_rejects_an_unknown_country() -> None:
    from workspace_core import UserFacingError
    with pytest.raises(UserFacingError, match="n’est pas reconnu"):
        validate_brief({"countries_exclude": ["Klingon"]})


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_excluded_count() -> None:
    """health_check() says which country caused each refusal."""
    jobs = [greenhouse_job(f"paris-{index:04}", "Paris, France") for index in range(42)]
    jobs.append(greenhouse_job("london-role", "London, United Kingdom"))
    connector = GreenhouseJobBoardConnector(FixtureTransport({"jobs": jobs}))
    connector.discover_ranked(BOARD, selection_brief=default_brief())
    health = connector.health_check()
    assert health["excluded_by_country"] == {"FR": 42}
    assert health["excluded_count"] == 42
    assert health["raw_count"] == 43
    assert health["filtered_count"] == 1


def test_boards_health_check_exposes_the_geo_metrics() -> None:
    fetch = FixtureFetch([build_html("welcome_jungle", [
        card("paris", "Paris, France"),
        card("london", "London, United Kingdom"),
    ])])
    WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch).discover_internships(
        source("welcome_jungle"), selection_brief=default_brief()
    )
    health = WelcomeJungleConnector.health_check()
    assert health["excluded_by_country"] == {"FR": 1}
    assert health["raw_count"] == 2
    assert health["kept_count"] == 1
    assert health["filtered_count"] == 1


# ---------------------------------------------------------------------------
# Mixed batches and volume
# ---------------------------------------------------------------------------


def test_mixed_countries() -> None:
    """In a mixed batch, only the excluded country is removed."""
    transport = FixtureTransport({"jobs": [
        greenhouse_job("fr-role", "Paris, France"),
        greenhouse_job("de-role", "Frankfurt, Germany"),
        greenhouse_job("uk-role", "London, United Kingdom"),
    ]})
    connector = GreenhouseJobBoardConnector(transport)
    result = connector.discover_ranked(BOARD, selection_brief=default_brief())
    assert {job["source_id"] for job in result.jobs} == {"de-role", "uk-role"}
    assert connector.health_check()["excluded_by_country"] == {"FR": 1}


def test_mixed_posting_is_kept_and_counted_apart() -> None:
    """A posting placed in France *and* in another country stays, and is counted apart."""
    transport = FixtureTransport({"jobs": [
        greenhouse_job("mixed-role", "London, United Kingdom / Paris, France"),
    ]})
    connector = GreenhouseJobBoardConnector(transport)
    result = connector.discover_internships(BOARD, selection_brief=default_brief())
    assert [job["source_id"] for job in result.jobs] == ["mixed-role"]
    health = connector.health_check()
    assert health["excluded_count"] == 0
    assert health["excluded_by_country"] == {}
    assert health["mixed_count"] == 1
    assert health["mixed_by_country"] == {"FR": 1}


def test_no_french_offer_over_500_synthetic_offers() -> None:
    """Over five hundred synthetic postings, not one French offer comes back."""
    jobs = [greenhouse_job(f"fr-{index:04}", "Paris, France") for index in range(300)]
    jobs += [greenhouse_job(f"intl-{index:04}", "London, United Kingdom") for index in range(300)]
    connector = GreenhouseJobBoardConnector(FixtureTransport({"jobs": jobs}))
    result = connector.discover_ranked(BOARD, selection_brief=default_brief())
    assert len(jobs) == 600
    assert result.relevant_count == 300
    assert result.excluded_count == 300
    # The board keeps at most its own per-source cap; what matters is that
    # not one of the retained postings is French.
    assert len(result.jobs) == GREENHOUSE_MAX_JOBS
    assert all(job["country_canonical"] == "GB" for job in result.jobs)
    assert connector.health_check()["excluded_by_country"] == {"FR": 300}
