"""Source-side geographic filtering: no connector ever returns a French offer.

Synthetic feeds only.  No public board is contacted and no socket is opened:
every connector reads a synthetic payload built here.

The rule under test is simple and non-negotiable: the person never wants
French postings, so every connector normalizes the country it publishes and
drops the excluded countries **before** the offer becomes a local record.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from career.connectors import AshbyConnector, LeverConnector, SmartRecruitersConnector
from career.connectors.apec import ApecConnector
from career.connectors.jobteaser import JobTeaserConnector
from career.connectors.talent_com import TalentComConnector
from career.connectors.welcome_jungle import WelcomeJungleConnector
from career.countries import (
    DEFAULT_COUNTRIES_EXCLUDE,
    canonical_country_codes,
    canonicalize_country,
    country_from_source,
)
from career.discovery import (
    GREENHOUSE_MAX_JOBS,
    GreenhouseBoard,
    GreenhouseJobBoardConnector,
    discover_stage_offers,
)
from career.stage_search import default_brief, validate_brief


FRANCE = "Paris, France"
GERMANY = "Frankfurt, Germany"
UNITED_KINGDOM = "London, United Kingdom"


# --- Synthetic sources ------------------------------------------------------


def greenhouse_job(identifier: str, *, location: str = UNITED_KINGDOM, country_code: str | None = None,
                   title: str = "Corporate Finance Intern") -> dict[str, Any]:
    job = {
        "id": identifier,
        "title": title,
        "absolute_url": f"https://careers.example.test/jobs/{identifier}",
        "location": {"name": location},
        "content": "<p>Financial analysis and valuation. This synthetic internship lasts six months.</p>",
    }
    if country_code is not None:
        job["location"]["office"] = {"country_code": country_code}
    return job


class FeedTransport:
    """Greenhouse transport that replays one synthetic payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def get_json(self, endpoint: str, timeout_seconds: int) -> dict[str, Any]:
        assert endpoint.startswith("https://boards-api.greenhouse.io/v1/boards/")
        self.calls += 1
        return self.payload


def html_cards(jobs: list[dict[str, Any]], href: str) -> str:
    """One synthetic result page understood by the four HTML connectors."""
    cards = []
    for job in jobs:
        cards.append(f'''
        <article class="job-card job-result" data-testid="job-card" data-offer-id="{job["identifier"]}">
            <h3 class="title" data-testid="job-title">{job["title"]}</h3>
            <span class="company" data-testid="company">Synthetic Finance</span>
            <span class="location" data-testid="location">{job["location"]}</span>
            <span class="contract" data-testid="contract">Internship</span>
            <a href="{href.format(identifier=job["identifier"])}"></a>
            <p class="description" data-testid="description">Financial analysis internship.</p>
        </article>
        ''')
    return f"<html><body>{''.join(cards)}</body></html>"


class FixtureFetch:
    def __init__(self, html: str) -> None:
        self.html = html
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        return self.html


def source(provider: str) -> dict[str, Any]:
    return {
        "id": f"synthetic:{provider}:board",
        "provider": provider,
        "company": "Synthetic Finance",
        "board_token": "synthetic-board",
        "verified_at": "2026-10-20T00:00:00Z",
        "provenance_url": "https://www.example.test/jobs",
    }


def mixed_jobs(count: int, *, location: str) -> list[dict[str, Any]]:
    return [
        {"identifier": f"{location[:2]}-{index}", "title": "Corporate Finance Intern", "location": location}
        for index in range(count)
    ]


# --- Canonical country vocabulary -------------------------------------------


def test_canonicalize_country_fr_variants():
    """Every French wording resolves to the same canonical country."""
    for wording in ("FR", "fr", "Fr", "FRA", "France", "france", "FRANCE", "République Française"):
        assert canonicalize_country(wording) == "FR"


def test_canonicalize_country_does_not_read_a_city_as_a_country():
    """A city name is never a country wording: nothing is invented."""
    assert canonicalize_country("Frankfurt") == ""
    assert canonicalize_country("Paris") == ""
    assert canonicalize_country("") == ""
    assert canonicalize_country(None) == ""


def test_canonicalize_country_reads_explicit_wording_only():
    assert canonicalize_country("United Kingdom") == "GB"
    assert canonicalize_country("UK") == "GB"
    assert canonicalize_country("GBR") == "GB"
    assert canonicalize_country("Germany") == "DE"
    assert canonicalize_country("DEU") == "DE"
    assert canonicalize_country("Atlantis") == ""


def test_canonical_country_codes_keeps_order_and_drops_unknown_wordings():
    assert canonical_country_codes(["FR", "France", "fr", "DE"]) == ("FR", "DE")
    assert canonical_country_codes([]) == ()
    assert canonical_country_codes(None) == ()
    assert canonical_country_codes(["Atlantis"]) == ()


def test_country_from_source_resolves_a_location_published_in_the_country_field():
    assert country_from_source("United Kingdom") == "GB"
    assert country_from_source("London, United Kingdom") == "GB"
    assert country_from_source("") == ""


def test_default_exclusion_is_france():
    assert DEFAULT_COUNTRIES_EXCLUDE == ("FR",)
    assert default_brief()["countries_exclude"] == ["FR"]
    assert validate_brief({})["countries_exclude"] == ["FR"]
    assert validate_brief({"countries_exclude": []})["countries_exclude"] == []


# --- Greenhouse --------------------------------------------------------------


def test_greenhouse_excludes_france():
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("fr-1", location=FRANCE),
        greenhouse_job("fr-2", location="Lyon, France"),
        greenhouse_job("de-1", location=GERMANY),
        greenhouse_job("uk-1", location=UNITED_KINGDOM),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=validate_brief({"domains": ["Corporate Finance"]}),
    )
    assert [job["source_id"] for job in payload.jobs] == ["de-1", "uk-1"]
    assert payload.excluded_by_country == {"FR": 2}
    assert payload.country_excluded_count == 2
    assert all(job["country_canonical"] != "FR" for job in payload.jobs)


def test_greenhouse_office_country_code_is_used_to_deduce_the_country():
    """A structural country code wins over the prose of the location."""
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("structural-fr", location=UNITED_KINGDOM, country_code="FR"),
        greenhouse_job("structural-de", location=UNITED_KINGDOM, country_code="DE"),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=validate_brief({"domains": ["Corporate Finance"]}),
    )
    assert [job["source_id"] for job in payload.jobs] == ["structural-de"]
    assert payload.excluded_by_country == {"FR": 1}


def test_greenhouse_frankfurt_is_not_excluded_by_the_fr_code():
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("de-1", location=GERMANY),
        greenhouse_job("de-2", location="Frankfurt"),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=validate_brief({"domains": ["Corporate Finance"]}),
    )
    assert {job["source_id"] for job in payload.jobs} == {"de-1", "de-2"}
    assert payload.excluded_by_country == {}


def test_greenhouse_default_is_fr_excluded():
    """Without any brief, France is still excluded by the connector itself."""
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("fr-1", location=FRANCE),
        greenhouse_job("uk-1", location=UNITED_KINGDOM),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
    )
    assert [job["source_id"] for job in payload.jobs] == ["uk-1"]


def test_greenhouse_brief_can_bring_france_back():
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("fr-1", location=FRANCE),
        greenhouse_job("uk-1", location=UNITED_KINGDOM),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=validate_brief({"domains": ["Corporate Finance"], "countries_exclude": []}),
    )
    assert "fr-1" in {job["source_id"] for job in payload.jobs}
    assert payload.excluded_by_country == {}


# --- HTML connectors ---------------------------------------------------------


def test_welcome_jungle_excludes_france():
    fetch = FixtureFetch(html_cards(mixed_jobs(3, location=FRANCE), "/fr/companies/synthetic/jobs/{identifier}"))
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    payload = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    assert payload.jobs == ()
    health = WelcomeJungleConnector.health_check()
    assert health["excluded_by_country"] == {"FR": 3}
    assert health["excluded_count"] == 3
    assert health["raw_count"] == 3


def test_html_connectors_exclude_a_location_written_with_a_dash():
    """A source may write "Paris - France": the country is still read."""
    for connector_class, provider, path in (
        (WelcomeJungleConnector, "welcome_jungle", "/fr/companies/synthetic/jobs/{identifier}"),
        (JobTeaserConnector, "jobteaser", "/jobs/{identifier}"),
        (TalentComConnector, "talent_com", "/job/{identifier}"),
        (ApecConnector, "apec", "/emploi/{identifier}"),
    ):
        fetch = FixtureFetch(html_cards(mixed_jobs(2, location="Paris - France"), path))
        connector = connector_class(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
        payload = connector.discover_internships(source(provider), selection_brief=default_brief())
        assert payload.jobs == (), connector_class.__name__
        assert connector_class.health_check()["excluded_by_country"] == {"FR": 2}, connector_class.__name__


def test_country_from_source_reads_a_location_written_with_a_dash():
    """The dash separates the city from the country, exactly like a comma."""
    assert country_from_source("Paris - France") == "FR"
    assert country_from_source("Frankfurt - Germany") == "DE"
    # A dash without spaces belongs to the word itself, never a separator.
    assert country_from_source("Le-Mans") == ""


def test_jobteaser_excludes_france():
    fetch = FixtureFetch(html_cards(mixed_jobs(2, location=FRANCE), "/jobs/{identifier}"))
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    payload = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    assert payload.jobs == ()
    assert JobTeaserConnector.health_check()["excluded_by_country"] == {"FR": 2}


def test_talent_com_excludes_france():
    fetch = FixtureFetch(html_cards(mixed_jobs(2, location=FRANCE), "/job/{identifier}"))
    connector = TalentComConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    payload = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    assert payload.jobs == ()
    assert TalentComConnector.health_check()["excluded_by_country"] == {"FR": 2}


def test_apec_excludes_france():
    fetch = FixtureFetch(html_cards(mixed_jobs(2, location=FRANCE), "/emploi/{identifier}"))
    connector = ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    payload = connector.discover_internships(source("apec"), selection_brief=default_brief())
    assert payload.jobs == ()
    assert ApecConnector.health_check()["excluded_by_country"] == {"FR": 2}


def test_html_connectors_keep_the_offers_of_other_countries():
    fetch = FixtureFetch(html_cards(mixed_jobs(3, location=GERMANY), "/jobs/{identifier}"))
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    payload = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    assert len(payload.jobs) == 3
    assert JobTeaserConnector.health_check()["excluded_by_country"] == {}


def test_html_connector_case_insensitive_country_variants_are_excluded():
    for wording in ("Paris, France", "Paris, FRANCE", "Paris, fr", "Paris, FRA"):
        fetch = FixtureFetch(html_cards(mixed_jobs(1, location=wording), "/jobs/{identifier}"))
        connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
        payload = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
        assert payload.jobs == (), wording
        assert JobTeaserConnector.health_check()["excluded_by_country"] == {"FR": 1}, wording


def test_html_connector_can_be_told_to_allow_france():
    fetch = FixtureFetch(html_cards(mixed_jobs(1, location=FRANCE), "/jobs/{identifier}"))
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    payload = connector.discover_internships(
        source("jobteaser"), selection_brief=validate_brief({"countries_exclude": []})
    )
    assert len(payload.jobs) == 1
    assert JobTeaserConnector.health_check()["excluded_by_country"] == {}


# --- Public ATS connectors ---------------------------------------------------


def test_public_ats_connectors_exclude_france():
    # Each vendor publishes its own documented payload shape.
    feeds = {
        "lever": [{"id": "fr-1", "text": "Corporate Finance Intern", "descriptionPlain": "Internship.",
                   "hostedUrl": "https://jobs.lever.co/synthetic/fr-1", "country": "France",
                   "categories": {"location": "Paris, France"}}],
        "ashby": {"jobs": [{"id": "fr-2", "title": "Corporate Finance Intern", "descriptionPlain": "Internship.",
                            "jobUrl": "https://jobs.ashbyhq.com/synthetic/fr-2",
                            "address": {"postalAddress": {"addressLocality": "Paris",
                                                          "addressCountry": "FR"}}}]},
        "smartrecruiters": {"content": [{"id": "fr-3", "name": "Corporate Finance Intern",
                                         "description": "Internship.",
                                         "applyUrl": "https://www.smartrecruiters.com/synthetic/fr-3",
                                         "location": {"city": "Paris", "country": "France"}}]},
    }

    class Feed:
        def __init__(self, rows):
            self.rows = rows

        def get_json(self, *_args, **_kwargs):
            return self.rows

    for provider, connector in (
        ("lever", LeverConnector(transport=Feed(feeds["lever"]), enabled=True)),
        ("ashby", AshbyConnector(transport=Feed(feeds["ashby"]), enabled=True)),
        ("smartrecruiters", SmartRecruitersConnector(transport=Feed(feeds["smartrecruiters"]), enabled=True)),
    ):
        payload = connector.discover_internships(source(provider), selection_brief=default_brief())
        assert payload.jobs == (), provider
        assert payload.excluded_by_country == {"FR": 1}, provider
        assert connector.health_check()["excluded_by_country"] == {"FR": 1}, provider


# --- Metrics and entry point ------------------------------------------------


def test_metrics_excluded_count():
    """The connector reports exactly how many offers each country cost."""
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        *([greenhouse_job(f"fr-{index}", location=FRANCE) for index in range(42)]),
        greenhouse_job("uk-1", location=UNITED_KINGDOM),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
    )
    assert payload.excluded_by_country == {"FR": 42}
    health = connector.health_check()
    assert health["excluded_by_country"] == {"FR": 42}
    assert health["country_excluded_count"] == 42
    assert health["raw_count"] == 43


def test_every_connector_exposes_the_geographic_metrics():
    for connector in (
        GreenhouseJobBoardConnector(FeedTransport({"jobs": []})),
        LeverConnector(transport=SimpleNamespace(get_json=lambda *a, **k: []), enabled=True),
        AshbyConnector(transport=SimpleNamespace(get_json=lambda *a, **k: []), enabled=True),
        SmartRecruitersConnector(transport=SimpleNamespace(get_json=lambda *a, **k: []), enabled=True),
    ):
        health = connector.health_check()
        assert set(health) >= {"raw_count", "filtered_count", "excluded_count", "excluded_by_country"}
        assert isinstance(health["excluded_by_country"], dict)
    for connector in (WelcomeJungleConnector, JobTeaserConnector, TalentComConnector, ApecConnector):
        health = connector.health_check()
        assert set(health) >= {"raw_count", "filtered_count", "excluded_count", "excluded_by_country"}
        assert isinstance(health["excluded_by_country"], dict)


def test_countries_exclude_empty():
    """An emptied exclusion list excludes nothing: France comes back."""
    assert canonical_country_codes([]) == ()
    assert canonical_country_codes(None) == ()
    assert validate_brief({"countries_exclude": []})["countries_exclude"] == []

    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("fr-1", location=FRANCE),
        greenhouse_job("de-1", location=GERMANY),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=validate_brief({"countries_exclude": []}),
        countries_exclude=[],
    )
    assert {job["source_id"] for job in payload.jobs} == {"fr-1", "de-1"}
    assert payload.excluded_by_country == {}
    assert connector.health_check()["excluded_by_country"] == {}


def test_mixed_countries_only_excludes_the_excluded_one():
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("fr-1", location=FRANCE),
        greenhouse_job("de-1", location=GERMANY),
        greenhouse_job("uk-1", location=UNITED_KINGDOM),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
    )
    assert {job["source_id"] for job in payload.jobs} == {"de-1", "uk-1"}
    assert payload.excluded_by_country == {"FR": 1}


def test_no_french_offer_survives_six_hundred_synthetic_offers():
    """The reviewer criterion: zero French offers over 500+ synthetic offers."""
    jobs = []
    for index in range(300):
        jobs.append(greenhouse_job(f"fr-{index}", location=FRANCE))
        jobs.append(greenhouse_job(f"uk-{index}", location=UNITED_KINGDOM))
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": jobs}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
    )
    assert payload.raw_count == 600
    assert payload.excluded_by_country == {"FR": 300}
    assert payload.country_excluded_count == 300
    assert all(job["country_canonical"] != "FR" for job in payload.jobs)
    # The foreign half is kept, up to the bounded per-source cap.
    assert payload.relevant_count == 300
    assert len(payload.jobs) == min(300, GREENHOUSE_MAX_JOBS)


def test_discover_stage_offers_excludes_france_by_default():
    fetch = FixtureFetch(html_cards(mixed_jobs(2, location=FRANCE), "/emploi/{identifier}"))
    connector = ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    offers = discover_stage_offers({"apec": connector}, [source("apec")])
    assert offers == []
    assert ApecConnector.health_check()["excluded_by_country"] == {"FR": 2}


def test_discover_stage_offers_forwards_the_default_exclusion_list():
    class RecordingConnector:
        def __init__(self):
            self.received = None

        def discover_internships(self, source, *, selection_brief, deadline=None, countries_exclude=None):
            self.received = countries_exclude
            return SimpleNamespace(jobs=())

    connector = RecordingConnector()
    discover_stage_offers({"apec": connector}, [source("apec")])
    assert connector.received == ["FR"]

    connector = RecordingConnector()
    discover_stage_offers({"apec": connector}, [source("apec")], countries_exclude=[])
    assert connector.received == []


def test_discover_stage_offers_can_bring_france_back():
    fetch = FixtureFetch(html_cards(mixed_jobs(1, location=FRANCE), "/emploi/{identifier}"))
    connector = ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    offers = discover_stage_offers({"apec": connector}, [source("apec")], countries_exclude=[])
    assert len(offers) == 1


def test_unknown_country_wording_excludes_nothing():
    """An unknown country is never turned into an exclusion."""
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("unknown-1", location="Atlantis"),
        greenhouse_job("fr-1", location=FRANCE),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
    )
    assert "unknown-1" in {job["source_id"] for job in payload.jobs}
    assert payload.excluded_by_country == {"FR": 1}


@pytest.mark.parametrize("wording", ["fr", "Fr", "FR"])
def test_case_insensitive_exclusion_list(wording):
    connector = GreenhouseJobBoardConnector(FeedTransport({"jobs": [
        greenhouse_job("fr-1", location=FRANCE),
        greenhouse_job("de-1", location=GERMANY),
    ]}))
    payload = connector.discover_internships(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"),
        selection_brief=default_brief(),
        countries_exclude=[wording],
    )
    assert [job["source_id"] for job in payload.jobs] == ["de-1"]
    assert payload.excluded_by_country == {"FR": 1}
