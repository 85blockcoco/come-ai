"""SK-11 — Filtre pays côté connecteurs : la matrice d'acceptation de la mission.

Chaque cas est une fixture synthétique lue dans ``tests/fixtures/geo_filter/`` :
aucun board public n'est contacté, aucune socket n'est ouverte, aucune donnée
personnelle n'est utilisée.

La règle testée est la règle du mission : le filtre s'applique **au niveau du
connecteur**, avant la qualification et avant l'écriture locale.  Une offre
publiée dans un pays exclu n'arrive jamais à la personne, et le connecteur
compte ce qu'il a refusé.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from career.connectors import AshbyConnector, LeverConnector, SmartRecruitersConnector
from career.connectors.apec import ApecConnector
from career.connectors.jobteaser import JobTeaserConnector
from career.connectors.talent_com import TalentComConnector
from career.connectors.welcome_jungle import WelcomeJungleConnector
from career.countries import (
    GeoFilter,
    canonicalize_country,
    country_from_location,
    geo_filter,
    hinted_country_codes,
)
from career.discovery import (
    DiscoveryPayload,
    GreenhouseBoard,
    GreenhouseJobBoardConnector,
    connector_geo_kwargs,
    discover_stage_offers,
)
from career.stage_search import default_brief, validate_brief

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "geo_filter"
FIXTURE_FILES = sorted(FIXTURE_DIR.glob("*.json"))


def _load_cases() -> list[tuple[str, dict[str, Any]]]:
    """Every synthetic case of the mission, with the file it comes from."""
    cases: list[tuple[str, dict[str, Any]]] = []
    for path in FIXTURE_FILES:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for case in payload.get("cases", []):
            cases.append((path.name, case))
    return cases


CASES = _load_cases()
CASE_IDS = [case["case_id"] for _name, case in CASES]


def _source(provider: str) -> dict[str, Any]:
    return {
        "id": f"synthetic:{provider}:board",
        "provider": provider,
        "company": "Synthetic Finance",
        "board_token": "synthetic-board",
        "verified_at": "2026-10-20T00:00:00Z",
        "provenance_url": "https://www.example.test/jobs",
    }


class FeedTransport:
    """Greenhouse transport that replays one synthetic payload."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def get_json(self, endpoint: str, timeout_seconds: int) -> Any:
        assert endpoint.startswith("https://boards-api.greenhouse.io/v1/boards/")
        return self.payload


class Feed:
    """Public ATS transport that replays one synthetic payload."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def get_json(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.payload


class FixtureFetch:
    """HTML connector transport that replays one synthetic result page."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        return self.html


def html_cards(cards: list[dict[str, Any]], href: str) -> str:
    """One synthetic result page understood by the four HTML connectors."""
    articles = []
    for card in cards:
        articles.append(f'''
        <article class="job-card job-result" data-testid="job-card" data-offer-id="{card["identifier"]}">
            <h3 class="title" data-testid="job-title">{card["title"]}</h3>
            <span class="company" data-testid="company">{card["company"]}</span>
            <span class="location" data-testid="location">{card["location"]}</span>
            <span class="contract" data-testid="contract">Internship</span>
            <a href="{href.format(identifier=card["identifier"])}"></a>
            <p class="description" data-testid="description">Financial analysis internship.</p>
        </article>
        ''')
    return f"<html><body>{''.join(articles)}</body></html>"


def _run_case(file_name: str, case: dict[str, Any]) -> DiscoveryPayload:
    """Run one synthetic case through the connector it belongs to."""
    payload = json.loads((FIXTURE_DIR / file_name).read_text(encoding="utf-8"))
    provider = payload["provider"]
    exclude = case.get("countries_exclude", ["FR"])
    include = case.get("countries_include", [])
    brief = validate_brief(case.get("brief", {}))
    if provider == "greenhouse":
        connector = GreenhouseJobBoardConnector(FeedTransport(case["feed"]))
        return connector.discover_internships(
            GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
            selection_brief=brief,
            countries_exclude=exclude,
            countries_include=include,
        )
    if provider == "lever":
        connector = LeverConnector(transport=Feed(case["feed"]), enabled=True)
    elif provider == "ashby":
        connector = AshbyConnector(transport=Feed(case["feed"]), enabled=True)
    elif provider == "smartrecruiters":
        connector = SmartRecruitersConnector(transport=Feed(case["feed"]), enabled=True)
    else:
        html = html_cards(case["cards"], payload["href"])
        connector_class = {
            "welcome_jungle": WelcomeJungleConnector,
            "jobteaser": JobTeaserConnector,
            "talent_com": TalentComConnector,
            "apec": ApecConnector,
        }[provider]
        connector = connector_class(clock=lambda: "2026-10-20T01:00:00Z", fetch=FixtureFetch(html))
    return connector.discover_internships(
        _source(provider),
        selection_brief=brief,
        countries_exclude=exclude,
        countries_include=include,
    )


@pytest.mark.parametrize("file_name,case", CASES, ids=CASE_IDS)
def test_mission_case(file_name: str, case: dict[str, Any]):
    """Each mission case ends exactly as the mission table states."""
    payload = _run_case(file_name, case)
    expected = case["expect"]
    kept = sorted(str(job.get("source_id") or "") for job in payload.jobs)
    assert kept == sorted(expected["kept_source_ids"]), case["case_id"]
    assert payload.excluded_by_country == expected["excluded_by_country"], case["case_id"]
    assert payload.offers_filtered_geo == sum(expected["excluded_by_country"].values()), case["case_id"]


def test_the_fixture_corpus_covers_the_mission_acceptance_table():
    """Twelve cases at least, and every connector of the mission."""
    assert len(CASES) >= 12
    providers = {json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))["provider"]
                 for name, _case in CASES}
    assert providers == {
        "greenhouse", "lever", "ashby", "smartrecruiters",
        "welcome_jungle", "jobteaser", "talent_com", "apec",
    }


def test_every_connector_accepts_the_geographic_parameters():
    """The parameter is declared by all eight connectors of the mission."""
    connectors = (
        GreenhouseJobBoardConnector, LeverConnector, AshbyConnector, SmartRecruitersConnector,
        WelcomeJungleConnector, JobTeaserConnector, TalentComConnector, ApecConnector,
    )
    for connector_class in connectors:
        parameters = inspect.signature(connector_class.discover_internships).parameters
        assert "countries_exclude" in parameters, connector_class.__name__
        assert "countries_include" in parameters, connector_class.__name__


def test_the_payload_exposes_the_audit_metric():
    """``offers_filtered_geo`` is the audit metric of the geographic filter."""
    payload = DiscoveryPayload(jobs=(), verified_at="2026-10-20T00:00:00Z", truncated=False,
                               country_excluded_count=7, excluded_by_country={"FR": 7})
    assert payload.offers_filtered_geo == 7
    assert payload.offers_filtered_geo == payload.country_excluded_count


def test_the_service_pushes_the_filter_to_the_connectors(tmp_path):
    """The service hands the country list to the connector, explicitly."""
    from career.service import CareerService

    received: list[Any] = []

    class RecordingConnector:
        def discover_ranked(self, board, *, selection_brief=None, countries_exclude=None,
                            countries_include=None):
            received.append(("ranked", countries_exclude, countries_include))
            return DiscoveryPayload(jobs=(), verified_at="2026-10-20T00:00:00Z", truncated=False)

        def discover_internships(self, source, *, selection_brief=None, deadline=None,
                                countries_exclude=None, countries_include=None):
            received.append(("internships", countries_exclude, countries_include))
            return DiscoveryPayload(jobs=(), verified_at="2026-10-20T00:00:00Z", truncated=False)

    service = CareerService(tmp_path, discovery_connector=RecordingConnector())
    service.create_discovery_source({"company": "Synthetic Finance", "board_reference": "synthetic-board"})
    service.discover_opportunities(force=True)
    assert received, "the connector was never called"
    for _flow, excluded, included in received:
        assert excluded == ["FR"]
        assert included == []

    received.clear()
    service.update_stage_search({"domains": ["Corporate Finance"], "excluded_countries": []})
    service.discover_opportunities(force=True)
    for _flow, excluded, _included in received:
        assert excluded == [], "an emptied exclusion list must reach the connector"


def test_the_explorer_flow_pushes_the_filter_to_the_connectors(tmp_path):
    """The curated-board explorer hands the country list to the connector too."""
    from career.service import CareerService

    received: list[Any] = []

    class RecordingConnector:
        def discover_internships(self, source, *, selection_brief=None, deadline=None,
                                countries_exclude=None, countries_include=None):
            received.append((countries_exclude, countries_include))
            return DiscoveryPayload(jobs=(), verified_at="2026-10-20T00:00:00Z", truncated=False)

    service = CareerService(
        tmp_path,
        exploration_connectors={"greenhouse": RecordingConnector()},
        curated_sources=({
            "id": "synthetic:greenhouse:board",
            "provider": "greenhouse",
            "company": "Synthetic Finance",
            "board_token": "synthetic-board",
            "verified_at": "2026-10-20T00:00:00Z",
            "provenance_url": "https://www.example.test/jobs",
        },),
    )
    service.explore_internships(force=True)
    assert received, "the connector was never called"
    for excluded, included in received:
        assert excluded == ["FR"]
        assert included == []


def test_an_inclusion_list_keeps_only_the_targeted_countries():
    """``countries_include`` drops a known country outside of the target list."""
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        {"id": "de-1", "title": "Corporate Finance Intern",
         "absolute_url": "https://careers.example.test/jobs/de-1",
         "location": {"name": "Berlin, Germany"},
         "content": "<p>Financial analysis and valuation. This synthetic internship lasts six months.</p>"},
        {"id": "fr-1", "title": "Corporate Finance Intern",
         "absolute_url": "https://careers.example.test/jobs/fr-1",
         "location": {"name": "Paris, France"},
         "content": "<p>Financial analysis and valuation. This synthetic internship lasts six months.</p>"},
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
        countries_exclude=[],
        countries_include=["DE"],
    )
    assert {job["source_id"] for job in payload.jobs} == {"de-1"}
    assert payload.excluded_by_country == {"FR": 1}


def test_an_unknown_country_survives_an_inclusion_list():
    """An unknown country is never dropped by an inclusion list."""
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        {"id": "unknown-1", "title": "Corporate Finance Intern",
         "absolute_url": "https://careers.example.test/jobs/unknown-1",
         "location": {"name": "Zurich"},
         "content": "<p>Financial analysis and valuation. This synthetic internship lasts six months.</p>"},
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
        countries_include=["DE"],
    )
    assert {job["source_id"] for job in payload.jobs} == {"unknown-1"}
    assert payload.excluded_by_country == {}


def test_the_filter_is_applied_before_the_description_is_parsed(monkeypatch):
    """The excluded country costs no description parsing."""
    import career.discovery as discovery

    parsed: list[Any] = []
    original = discovery.source_html_to_text

    def spy(value: Any) -> str:
        parsed.append(value)
        return original(value)

    monkeypatch.setattr(discovery, "source_html_to_text", spy)
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        {"id": "fr-1", "title": "Corporate Finance Intern",
         "absolute_url": "https://careers.example.test/jobs/fr-1",
         "location": {"name": "Paris, France"},
         "content": "<p>Financial analysis and valuation. This synthetic internship lasts six months.</p>"},
        {"id": "uk-1", "title": "Corporate Finance Intern",
         "absolute_url": "https://careers.example.test/jobs/uk-1",
         "location": {"name": "London, United Kingdom"},
         "content": "<p>Financial analysis and valuation. This synthetic internship lasts six months.</p>"},
    ]}))
    connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
    )
    assert len(parsed) == 1, "the French offer was parsed before it was dropped"


def test_the_canonical_vocabulary_never_reads_a_city_as_a_country():
    """Frankfurt is a city in Germany, never a French posting."""
    assert canonicalize_country("Frankfurt") == ""
    assert canonicalize_country("Paris") == ""
    assert canonicalize_country("France") == "FR"
    assert canonicalize_country("FRA") == "FR"


def test_a_city_hint_may_only_exclude_an_offer():
    """A hint refuses an offer; it never proves where the offer is."""
    assert hinted_country_codes("Paris") == ("FR",)
    assert hinted_country_codes("Berlin") == ("DE",)
    # Several unnamed places prove nothing.
    assert hinted_country_codes("Paris, London") == ()
    assert hinted_country_codes("Atlantis") == ()
    # A hint is never a country of its own: the offer keeps an unknown one.
    connector = GreenhouseJobBoardConnector(FeedTransport(_greenhouse_payload(
        "Paris", "job-hint")))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
        countries_exclude=["FR"],
    )
    assert [job["source_id"] for job in payload.jobs] == ["job-hint"]
    assert payload.jobs[0]["country_canonical"] == ""
    assert payload.excluded_by_country == {}


def test_a_scraped_card_that_names_a_single_french_city_is_filtered():
    """The scraped connectors keep their historical behaviour: Paris is out."""
    from career.connectors.welcome_jungle import WelcomeJungleConnector

    html = html_cards([{"identifier": "wtj-1", "title": "Corporate Finance Intern",
                         "company": "Synthetic Finance", "location": "Paris"}],
                      "/fr/companies/synthetic/jobs/{identifier}")
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=FixtureFetch(html))
    payload = connector.discover_internships(
        _source("welcome_jungle"),
        selection_brief=default_brief(),
        countries_exclude=["FR"],
    )
    assert payload.jobs == ()
    assert payload.excluded_by_country == {"FR": 1}


def test_a_scraped_card_that_names_several_cities_is_kept():
    """Several unnamed places prove nothing: the offer stays visible."""
    from career.connectors.welcome_jungle import WelcomeJungleConnector

    html = html_cards([{"identifier": "wtj-2", "title": "Corporate Finance Intern",
                         "company": "Synthetic Finance", "location": "Paris, London"}],
                      "/fr/companies/synthetic/jobs/{identifier}")
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=FixtureFetch(html))
    payload = connector.discover_internships(
        _source("welcome_jungle"),
        selection_brief=default_brief(),
        countries_exclude=["FR"],
    )
    assert [job["source_id"] for job in payload.jobs] == ["wtj-2"]
    assert payload.excluded_by_country == {}
    """A board that publishes the country alone publishes a country."""
    assert country_from_location("France") == "FR"
    assert country_from_location("Germany") == "DE"
    assert country_from_location("United States") == "US"
    assert country_from_location("Hong Kong") == "HK"
    assert country_from_location("Madrid, Spain") == "ES"
    # A city is never a country, and a two-letter state code is not a country.
    assert country_from_location("Paris") == ""
    assert country_from_location("Zurich") == ""
    assert country_from_location("Chicago, IL") == ""
    assert country_from_location("Dubai") == ""
    assert country_from_location("") == ""
    assert country_from_location(None) == ""


def _greenhouse_payload(location: str, identifier: str = "job-1") -> dict[str, Any]:
    return {"jobs": [{
        "id": identifier,
        "title": "Corporate Finance Intern",
        "absolute_url": f"https://careers.example.test/jobs/{identifier}",
        "location": {"name": location},
        "content": "<p>Financial analysis and valuation. This synthetic internship lasts six months.</p>",
    }]}


def test_a_posting_that_names_several_countries_is_kept_when_one_is_allowed():
    """A London role published next to Paris is still a London role."""
    connector = GreenhouseJobBoardConnector(FeedTransport(_greenhouse_payload(
        "London, Greater London, England, United Kingdom, Paris, France")))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
        countries_exclude=["FR"],
    )
    assert [job["source_id"] for job in payload.jobs] == ["job-1"]
    assert payload.excluded_by_country == {}
    assert payload.jobs[0]["country_canonical"] == "GB"


def test_a_posting_that_names_only_an_excluded_country_is_dropped():
    """The same rule with a single country: the offer is filtered."""
    connector = GreenhouseJobBoardConnector(FeedTransport(_greenhouse_payload(
        "Paris, Paris, France", "job-fr")))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
        countries_exclude=["FR"],
    )
    assert payload.jobs == ()
    assert payload.excluded_by_country == {"FR": 1}


def test_a_state_abbreviation_is_never_read_as_a_country():
    """``Chicago, IL`` publishes Illinois, not Israel."""
    connector = GreenhouseJobBoardConnector(FeedTransport(_greenhouse_payload(
        "Chicago, IL", "job-us")))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
        countries_exclude=["FR"],
    )
    assert [job["source_id"] for job in payload.jobs] == ["job-us"]
    assert payload.jobs[0]["country_canonical"] == ""
    assert payload.excluded_by_country == {}


def test_a_bare_country_code_in_the_country_slot_is_read():
    """``Paris, FR`` publishes a country code: the offer is filtered."""
    connector = GreenhouseJobBoardConnector(FeedTransport(_greenhouse_payload(
        "Paris, FR", "job-code")))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
        countries_exclude=["FR"],
    )
    assert payload.jobs == ()
    assert payload.excluded_by_country == {"FR": 1}


def test_the_geo_filter_object_never_invents_a_geography():
    """An unknown country is never rejected, whatever the lists are."""
    strict = GeoFilter(exclude=frozenset({"FR"}), include=frozenset({"DE"}))
    assert strict.rejects("FR") is True
    assert strict.rejects("DE") is False
    assert strict.rejects("ES") is True
    assert strict.rejects("") is False


def test_the_brief_resolves_the_country_lists_once():
    """The brief carries the canonical lists every connector reads."""
    brief = validate_brief({"countries_exclude": ["France"], "countries_include": ["Germany", "de"]})
    assert brief["countries_exclude"] == ["FR"]
    assert brief["countries_include"] == ["DE"]
    assert validate_brief({})["countries_exclude"] == ["FR"]
    assert validate_brief({})["countries_include"] == []
    # The mission reads the exclusion list under this name too.
    assert validate_brief({"geo_excluded_countries": ["FR"]})["countries_exclude"] == ["FR"]


def test_the_geo_filter_helper_reads_the_explicit_list_first():
    assert geo_filter(["FR"], None, {"countries_exclude": []}).exclude == frozenset({"FR"})
    assert geo_filter([], None, {"countries_exclude": ["FR"]}).exclude == frozenset()
    assert geo_filter(None, None, {"countries_exclude": ["FR"]}).exclude == frozenset({"FR"})


def test_a_connector_without_the_parameter_still_works():
    """A third-party connector that ignores the filter is never broken by it."""
    class LegacyConnector:
        def discover_internships(self, source, *, selection_brief, deadline=None):
            return SimpleNamespace(jobs=())

    offers = discover_stage_offers({"apec": LegacyConnector()}, [_source("apec")])
    assert offers == []
    assert connector_geo_kwargs(LegacyConnector()) == {}
