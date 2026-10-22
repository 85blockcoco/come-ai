"""SK-11 — the country filter is applied at the connector boundary.

Every fixture below is synthetic: no board, employer, feed or URL is real.
The suite proves three things for the eight connectors of this workspace:

* a posting published in an excluded country never reaches the results and
  never costs a qualification;
* a posting whose country could not be read stays visible, because an
  unknown country is not an excluded country;
* a connector called without the parameter keeps its historical behaviour.
"""

from __future__ import annotations

import inspect
import json
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from career.connectors.apec import ApecConnector
from career.connectors.jobteaser import JobTeaserConnector
from career.connectors.public_ats import AshbyConnector, LeverConnector, SmartRecruitersConnector
from career.connectors.talent_com import TalentComConnector
from career.connectors.welcome_jungle import WelcomeJungleConnector
from career.discovery import DiscoveryPayload, GreenhouseBoard, GreenhouseJobBoardConnector
from career.geo import (
    canonical_country_code,
    excluded_country_codes,
    geo_filter_decision,
    resolve_country_filter,
)
from career.stage_search import default_brief


FIXTURE = Path(__file__).parent / "fixtures" / "geo_filter" / "geo_filter_cases.json"
CASES: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]

BOARD = GreenhouseBoard(id="synthetic-board", company="Synthetic Bank", board_token="synthetic-bank")


def source(provider: str) -> dict[str, Any]:
    return {
        "id": f"synthetic:{provider}:board",
        "provider": provider,
        "company": "Synthetic Bank",
        "board_token": "synthetic-board",
        "company_identifier": "synthetic-bank",
        "job_board_name": "synthetic-bank",
        "verified_at": "2026-10-20T00:00:00Z",
        "provenance_url": "https://careers.example.test/synthetic-bank",
    }


class FeedTransport:
    """Returns one synthetic feed instead of contacting any ATS."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_json(self, endpoint: str, timeout_seconds: int) -> Any:
        self.calls.append(endpoint)
        return self.payload


class FixtureFetch:
    """Returns one synthetic HTML page instead of contacting any job board."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        return self.html


# --------------------------------------------------------------------------
# Synthetic HTML, one shape per scraped source
# --------------------------------------------------------------------------


def _href(url: str) -> str:
    return urllib.parse.urlsplit(url).path or "/"


def welcome_jungle_html(cards: list[dict[str, Any]]) -> str:
    body = "".join(
        f'<article data-testid="job-card">'
        f'<h3 data-testid="job-title">{card["title"]}</h3>'
        f'<span data-testid="company">{card["company"]}</span>'
        f'<span data-testid="location">{card["location"]}</span>'
        f'<span data-testid="contract">{card["contract_type"]}</span>'
        f'<a href="{_href(card["url"])}"></a>'
        f'<div data-testid="description">{card["description"]}</div>'
        f"</article>"
        for card in cards
    )
    return f"<html><body>{body}</body></html>"


def jobteaser_html(cards: list[dict[str, Any]]) -> str:
    body = "".join(
        f'<article class="job-card">'
        f'<h3 class="job-title">{card["title"]}</h3>'
        f'<span class="company-name">{card["company"]}</span>'
        f'<span class="location-city">{card["location"]}</span>'
        f'<span class="contract-type">{card["contract_type"]}</span>'
        f'<a href="{_href(card["url"])}"></a>'
        f'<div class="job-description">{card["description"]}</div>'
        f"</article>"
        for card in cards
    )
    return f"<html><body>{body}</body></html>"


def talent_com_html(cards: list[dict[str, Any]]) -> str:
    body = "".join(
        f'<div class="job-card" data-job-id="{index}">'
        f'<h2 class="job-title">{card["title"]}</h2>'
        f'<span class="company-name">{card["company"]}</span>'
        f'<span class="location-city">{card["location"]}</span>'
        f'<span class="contract-type">{card["contract_type"]}</span>'
        f'<a href="{_href(card["url"])}"></a>'
        f'<div class="job-description">{card["description"]}</div>'
        f"</div>"
        for index, card in enumerate(cards, start=1)
    )
    return f"<html><body>{body}</body></html>"


def apec_html(cards: list[dict[str, Any]]) -> str:
    body = "".join(
        f'<div class="job-result" data-offer-id="{index}">'
        f'<h2 class="offer-title">{card["title"]}</h2>'
        f'<span class="company-name">{card["company"]}</span>'
        f'<span class="location-city">{card["location"]}</span>'
        f'<span class="contract-type">{card["contract_type"]}</span>'
        f'<a href="{_href(card["url"])}"></a>'
        f'<div class="offer-description">{card["description"]}</div>'
        f"</div>"
        for index, card in enumerate(cards, start=1)
    )
    return f"<html><body>{body}</body></html>"


# --------------------------------------------------------------------------
# Running one synthetic case
# --------------------------------------------------------------------------


def run_case(case: dict[str, Any]) -> DiscoveryPayload:
    """Read one synthetic feed through its connector with the given filter."""
    excluded = case.get("excluded")
    included = case.get("included")
    connector_name = case["connector"]

    if connector_name == "greenhouse":
        connector = GreenhouseJobBoardConnector(FeedTransport(case["feed"]))
        return connector.discover_internships(
            BOARD, selection_brief=default_brief(),
            countries_exclude=excluded, countries_include=included,
        )
    if connector_name in {"lever", "ashby", "smartrecruiters"}:
        connector_class = {"lever": LeverConnector, "ashby": AshbyConnector,
                           "smartrecruiters": SmartRecruitersConnector}[connector_name]
        connector = connector_class(transport=FeedTransport(case["feed"]), enabled=True)
        return connector.discover_internships(
            source(connector_name), selection_brief=default_brief(),
            countries_exclude=excluded, countries_include=included,
        )
    builder = {"welcome_jungle": welcome_jungle_html, "jobteaser": jobteaser_html,
               "talent_com": talent_com_html, "apec": apec_html}[connector_name]
    connector_class = {"welcome_jungle": WelcomeJungleConnector, "jobteaser": JobTeaserConnector,
                       "talent_com": TalentComConnector, "apec": ApecConnector}[connector_name]
    connector = connector_class(fetch=FixtureFetch(builder(case["cards"])))
    return connector.discover_internships(
        source(connector_name), selection_brief=default_brief(),
        countries_exclude=excluded, countries_include=included,
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_country_filter_keeps_and_drops_exactly_the_expected_postings(case: dict[str, Any]) -> None:
    payload = run_case(case)
    assert sorted(job["title"] for job in payload.jobs) == sorted(case["expected_titles"])
    assert payload.filtered_geo_count == case["expected_filtered_geo"]
    assert payload.offers_filtered_geo == case["expected_filtered_geo"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_counters_stay_coherent_after_the_country_filter(case: dict[str, Any]) -> None:
    payload = run_case(case)
    assert payload.raw_count == payload.evaluated_count + payload.invalid_count
    assert payload.evaluated_count == payload.confirmed_count + payload.uncertain_count + payload.excluded_count
    assert payload.relevant_count + payload.filtered_criteria_count == payload.confirmed_count + payload.uncertain_count
    assert 0 <= payload.filtered_geo_count <= payload.excluded_count


def test_the_corpus_covers_every_connector_and_the_required_cases() -> None:
    connectors = {case["connector"] for case in CASES}
    assert connectors == {"greenhouse", "lever", "ashby", "smartrecruiters",
                          "welcome_jungle", "jobteaser", "talent_com", "apec"}
    assert len(CASES) >= 12


# --------------------------------------------------------------------------
# The contract itself
# --------------------------------------------------------------------------


def test_every_connector_accepts_the_country_filter() -> None:
    connectors = [
        GreenhouseJobBoardConnector,
        LeverConnector,
        AshbyConnector,
        SmartRecruitersConnector,
        WelcomeJungleConnector,
        JobTeaserConnector,
        TalentComConnector,
        ApecConnector,
    ]
    for connector_class in connectors:
        parameters = inspect.signature(connector_class.discover_internships).parameters
        assert "countries_exclude" in parameters, connector_class.__name__
        assert "countries_include" in parameters, connector_class.__name__
    ranked = inspect.signature(GreenhouseJobBoardConnector.discover_ranked).parameters
    assert "countries_exclude" in ranked and "countries_include" in ranked


def test_a_connector_without_the_parameter_keeps_its_historical_behaviour() -> None:
    """The ATS connectors never filtered a country before this filter."""
    connector = GreenhouseJobBoardConnector(FeedTransport(
        {"jobs": [{"id": "1", "title": "Corporate Finance Intern",
                   "absolute_url": "https://careers.example.test/jobs/1",
                   "location": {"name": "Paris, France"},
                   "content": "<p>This internship lasts six months.</p>"}]}
    ))
    payload = connector.discover_internships(BOARD, selection_brief=default_brief())
    assert [job["country"] for job in payload.jobs] == ["France"]
    assert payload.filtered_geo_count == 0


def test_the_scraped_connectors_keep_their_historical_france_exclusion() -> None:
    """The scraped connectors already excluded France before this filter."""
    connector = WelcomeJungleConnector(fetch=FixtureFetch(welcome_jungle_html([
        {"title": "Corporate Finance Intern", "company": "Synthetic Bank",
         "location": "Paris, France", "contract_type": "Internship",
         "url": "https://www.welcometothejungle.com/fr/companies/synthetic-bank/jobs/one",
         "description": "<p>This internship lasts six months.</p>"},
    ])))
    payload = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    assert payload.jobs == ()
    assert payload.filtered_geo_count == 1


def test_an_excluded_posting_is_never_qualified() -> None:
    """The filter runs before the qualification, not after it."""
    connector = LeverConnector(transport=FeedTransport([
        {"id": "lv-paris", "text": "Corporate Finance Intern",
         "hostedUrl": "https://jobs.lever.co/synthetic-bank/lv-paris",
         "applyUrl": "https://jobs.lever.co/synthetic-bank/lv-paris",
         "descriptionPlain": "This internship lasts six months.",
         "categories": {"location": "Paris, France", "commitment": "Internship"},
         "country": "France"},
    ]), enabled=True)
    payload = connector.discover_internships(
        source("lever"), selection_brief=default_brief(), countries_exclude=["FR"]
    )
    assert payload.jobs == ()
    assert payload.confirmed_count == 0 and payload.uncertain_count == 0
    assert payload.excluded_count == 1
    assert payload.filtered_geo_count == 1
    assert payload.filtered_criteria_count == 0


def test_the_service_pushes_the_saved_country_criteria_to_the_connectors(tmp_path: Path) -> None:
    from career.service import CareerService

    seen: dict[str, Any] = {}

    class RecordingConnector:
        def discover_internships(self, source, *, selection_brief, deadline=None,
                                 countries_exclude=None, countries_include=None):
            seen["excluded"] = countries_exclude
            seen["included"] = countries_include
            return DiscoveryPayload(jobs=(), verified_at="2026-10-20T00:00:00Z", truncated=False,
                                    raw_count=0, evaluated_count=0, confirmed_count=0, relevant_count=0)

    service = CareerService(tmp_path, curated_sources=(source("greenhouse"),),
                            exploration_connectors={"greenhouse": RecordingConnector()})
    service.explore_internships()
    assert seen["excluded"] == ["FR"]
    assert seen["included"] == []


def test_the_service_reads_the_saved_country_names_as_iso_codes(tmp_path: Path) -> None:
    from career.service import CareerService

    service = CareerService(tmp_path)
    brief = service.get_stage_search()["brief"]
    assert brief["excluded_countries"] == ["France"]
    assert service._geo_filter_for_brief(brief) == (("FR",), ())
    assert service._geo_filter_for_brief({"excluded_countries": ["Germany", "Espagne"]}) == (("DE", "ES"), ())


# --------------------------------------------------------------------------
# The shared country reader
# --------------------------------------------------------------------------


@pytest.mark.parametrize("wording,expected", [
    ("France", "FR"), ("fr", "FR"), ("FRA", "FR"), ("French Republic", "FR"),
    ("United Kingdom", "GB"), ("UK", "GB"), ("Great Britain", "GB"),
    ("Germany", "DE"), ("Deutschland", "DE"), ("Netherlands", "NL"),
    ("Espagne", "ES"), ("Italia", "IT"), ("Suisse", "CH"), ("Suède", "SE"),
    ("Paris", ""), ("London", ""), ("", ""), ("Remote", ""), ("unknown", ""),
])
def test_canonical_country_code_reads_only_published_countries(wording: str, expected: str) -> None:
    assert canonical_country_code(wording) == expected


def test_an_unknown_country_is_never_excluded() -> None:
    decision = geo_filter_decision(location_text="Paris", country="", excluded_codes=["FR"])
    # A city wording may only exclude an offer when the connector declares
    # the city hints; without them the country stays unknown.
    assert decision.excluded is False
    assert decision.kept is True


def test_a_posting_in_several_countries_is_only_excluded_when_all_are_excluded() -> None:
    mixed = geo_filter_decision(location_text="Paris, France, United Kingdom", excluded_codes=["FR"])
    assert mixed.excluded is False
    only_france = geo_filter_decision(location_text="Paris, France", excluded_codes=["FR"])
    assert only_france.excluded is True


def test_excluded_country_codes_reads_the_person_s_own_words() -> None:
    assert excluded_country_codes(["France"]) == ("FR",)
    assert excluded_country_codes(["Allemagne", "Spain"]) == ("DE", "ES")
    assert excluded_country_codes([]) == ()
    assert excluded_country_codes(["not a country"]) == ()


def test_an_explicit_empty_list_disables_the_filter_but_none_keeps_the_default() -> None:
    assert resolve_country_filter(None, None, default_exclude=("FR",)) == (("FR",), ())
    assert resolve_country_filter([], None, default_exclude=("FR",)) == ((), ())
    assert resolve_country_filter(["de"], ["GB"]) == (("DE",), ("GB",))
