"""Synthetic contract tests for the four international connectors (SK-14).

No socket is opened and no public source is contacted: every connector reads
a synthetic payload built from the fixtures in
``tests/fixtures/intl_sources/``.  The ``socket`` module itself is blocked
during the whole module, so a connector that tried to reach the network
would fail the test instead of silently passing.

The rules under test are the ones the mission states:

* the four connectors exist, are registered and answer the common contract;
* the excluded country is never **requested** (the filter is native);
* the excluded country is never **returned**, even when the source answers
  with it (the filter is also applied on the published facts);
* the corpus never contains a French offer, and ``france_ratio`` is 0;
* the requests are slow enough, and the ``robots.txt`` of the source is
  honoured;
* the connectors only use the standard library.
"""

from __future__ import annotations

import ast
import json
import re
import socket
import sys
import urllib.parse
from pathlib import Path

import pytest

from career.connectors import (
    CONNECTOR_REGISTRY,
    CONNECTOR_SPECS,
    default_exploration_connectors,
)
from career.connectors.eures import EuresConnector
from career.connectors.glassdoor_intl import GlassdoorIntlConnector
from career.connectors.intl_common import (
    SOURCE_TIER_AGGREGATOR,
    SOURCE_TIER_EMPLOYER,
    SOURCE_TIER_OFFICIAL,
    PoliteFetcher,
    RobotsPolicy,
)
from career.connectors.jobteaser_intl import JobTeaserIntlConnector
from career.connectors.linkedin_europe import LinkedInEuropeConnector
from career.discovery import DiscoveryPayload, PublicSourceError
from career.stage_search import default_brief


FIXTURES = Path(__file__).parent / "fixtures" / "intl_sources"
PROVIDERS = ("linkedin_europe", "eures", "jobteaser_intl", "glassdoor_intl")
CONNECTORS = {
    "linkedin_europe": LinkedInEuropeConnector,
    "eures": EuresConnector,
    "jobteaser_intl": JobTeaserIntlConnector,
    "glassdoor_intl": GlassdoorIntlConnector,
}


@pytest.fixture(autouse=True)
def no_socket(monkeypatch):
    """No connector may open a socket while the synthetic tests run."""

    def refuse(*args, **kwargs):
        raise AssertionError("un connecteur international a ouvert un socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def source(provider: str, **extra) -> dict:
    return {
        "id": f"synthetic:{provider}:source",
        "provider": provider,
        "company": "Synthetic Finance",
        "verified_at": "2026-10-20T00:00:00Z",
        "provenance_url": f"https://www.example.test/{provider}",
    } | extra


def brief(**extra) -> dict:
    return default_brief() | extra


# --- synthetic readers -------------------------------------------------------

class RecordedFetch:
    """A reader that answers with one synthetic body and records the URLs."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        return self.body


class CountryFetch:
    """Answer a country search with the cards of that country.

    A real country search answers with the offers of that country.  The
    French card of the fixture is always included: it is the probe that
    proves the connector drops an offer published in an excluded country,
    even when the source itself publishes it.
    """

    def __init__(self, html: str, resolver) -> None:
        self.blocks = re.findall(r"<li[^>]*>.*?</li>", html, re.DOTALL)
        self.resolver = resolver
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        wanted = self.resolver(url)
        kept = []
        for block in self.blocks:
            location = _location_of(block)
            if "France" in location or (wanted and wanted.lower() in location.lower()):
                kept.append(block)
        return f"<html><body><ul>{''.join(kept)}</ul></body></html>"


def _location_of(block: str) -> str:
    match = re.search(r'class="job-search-card__location">([^<]*)<', block)
    return match.group(1) if match else ""


def _query(url: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)


def linkedin_fetch() -> CountryFetch:
    html = (FIXTURES / "linkedin_europe_search.html").read_text(encoding="utf-8")
    return CountryFetch(html, lambda url: _query(url).get("location", [""])[0])


def glassdoor_fetch() -> CountryFetch:
    html = (FIXTURES / "glassdoor_intl_search.html").read_text(encoding="utf-8")
    names = {1: "United States", 2: "Canada", 3: "United Kingdom", 4: "Germany", 5: "France"}
    return CountryFetch(
        html, lambda url: names.get(int(_query(url).get("locId", ["0"])[0]), "")
    )


def jobteaser_fetch() -> RecordedFetch:
    html = (FIXTURES / "jobteaser_intl_search.html").read_text(encoding="utf-8")
    return RecordedFetch(html)


def eures_fetch() -> RecordedFetch:
    body = (FIXTURES / "eures_search.json").read_text(encoding="utf-8")
    return RecordedFetch(body)


def eures_probe_fetch() -> RecordedFetch:
    """The EURES answer, with a French offer added to it.

    The published fixture holds ten offers outside France, as the mission
    describes it.  The French offer is added here so the country filter can
    be observed on a source that publishes an excluded country.
    """
    payload = json.loads((FIXTURES / "eures_search.json").read_text(encoding="utf-8"))
    payload["result"]["items"].append({
        "id": "eures-fr-1",
        "title": "Finance Intern",
        "employerName": "Example Paris SA",
        "location": {"name": "Paris", "countryCode": "FR", "countryName": "France"},
        "contractType": "INTERNSHIP",
        "description": "<p>Finance internship in Paris.</p>",
        "applicationUrl": "https://careers.example.test/jobs/eures-fr-1",
        "publicationDate": 1760000000000,
        "startDate": "2027-02-01",
        "duration": 6,
    })
    return RecordedFetch(json.dumps(payload))


def probe_fetch(provider: str):
    """A reader whose answer holds an offer published in France."""
    return {
        "linkedin_europe": linkedin_fetch,
        "eures": eures_probe_fetch,
        "jobteaser_intl": jobteaser_fetch,
        "glassdoor_intl": glassdoor_fetch,
    }[provider]()


def build(provider: str, fetch, **kwargs):
    connector = CONNECTORS[provider](clock=lambda: "2026-10-22T00:00:00Z", fetch=fetch, enabled=True, **kwargs)
    return connector


# --- registration -------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_connector_is_registered(provider):
    assert provider in CONNECTOR_SPECS
    assert provider in CONNECTOR_REGISTRY
    spec = CONNECTOR_SPECS[provider]
    assert spec.provider == provider
    assert spec.doc_verified is True
    assert spec.documentation_url.startswith("https://")
    assert CONNECTOR_REGISTRY[provider][0] is CONNECTORS[provider]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_connector_is_in_the_exploration_map(provider):
    connectors = default_exploration_connectors(object())
    assert provider in connectors
    assert connectors[provider].enabled is True


# --- the common contract -----------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_connector_returns_the_common_payload(provider):
    fetch = {
        "linkedin_europe": linkedin_fetch,
        "eures": eures_fetch,
        "jobteaser_intl": jobteaser_fetch,
        "glassdoor_intl": glassdoor_fetch,
    }[provider]()
    connector = build(provider, fetch)

    result = connector.discover_internships(source(provider), selection_brief=brief())

    assert isinstance(result, DiscoveryPayload)
    assert isinstance(result.jobs, tuple)
    assert result.jobs, "le connecteur doit rendre au moins une offre"
    assert result.verified_at == "2026-10-22T00:00:00Z"
    for job in result.jobs:
        assert job["source_name"] == provider
        assert job["source_verified"] is True
        assert job["official_url"].startswith("https://")
        assert job["source_id"]
        assert job["country_canonical"] in {"DE", "GB", "NL", "CH", "BE", "ES", "US", "CA", "AT", "IT", "PT", "PL", "FI"}
        assert job["country_canonical"] != "FR"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_counters_stay_coherent(provider):
    """The exploration service refuses a payload whose counters disagree."""
    fetch = {
        "linkedin_europe": linkedin_fetch,
        "eures": eures_fetch,
        "jobteaser_intl": jobteaser_fetch,
        "glassdoor_intl": glassdoor_fetch,
    }[provider]()
    connector = build(provider, fetch)

    result = connector.discover_internships(source(provider), selection_brief=brief())

    assert result.raw_count == result.evaluated_count + result.invalid_count
    assert result.evaluated_count == (
        result.confirmed_count + result.uncertain_count + result.excluded_count
    )
    assert result.relevant_count + result.filtered_criteria_count == (
        result.confirmed_count + result.uncertain_count
    )
    assert len(result.jobs) <= result.relevant_count


@pytest.mark.parametrize("provider", PROVIDERS)
def test_health_check_reports_the_factual_state(provider):
    fetch = {
        "linkedin_europe": linkedin_fetch,
        "eures": eures_fetch,
        "jobteaser_intl": jobteaser_fetch,
        "glassdoor_intl": glassdoor_fetch,
    }[provider]()
    connector = build(provider, fetch)

    connector.discover_internships(source(provider), selection_brief=brief())
    health = connector.health_check()

    for key in (
        "last_ok", "last_error", "consecutive_failures", "raw_offers", "valid_offers",
        "finance_offers", "stage_offers", "conforming_offers", "to_verify_offers",
        "countries_seen", "france_ratio",
    ):
        assert key in health, f"la santé de la source ne publie pas « {key} »"
    assert health["last_ok"] is True
    assert health["france_ratio"] == 0.0
    assert health["countries_seen"]
    assert "FR" not in health["countries_seen"]
    assert health["valid_offers"] == sum(health["countries_seen"].values())


# --- the country filter ------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_excluded_country_is_never_returned(provider):
    fetch = probe_fetch(provider)
    connector = build(provider, fetch)

    result = connector.discover_internships(
        source(provider), selection_brief=brief(), countries_exclude=["FR"]
    )

    assert result.country_excluded_count >= 1
    assert result.excluded_by_country == {"FR": result.country_excluded_count}
    assert all(job["country_canonical"] != "FR" for job in result.jobs)
    assert connector.health_check()["filtered_geo_count"] == result.country_excluded_count
    assert connector.health_check()["excluded_by_country"] == {"FR": result.country_excluded_count}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_filter_is_the_only_reason_the_french_offer_is_dropped(provider):
    """With the exclusion emptied, the French offer comes back.

    This is the counter-test: it proves the French offer was read and
    understood, and that the country filter is what removed it.
    """
    fetch = probe_fetch(provider)
    connector = build(provider, fetch)

    result = connector.discover_internships(
        source(provider), selection_brief=brief(), countries_exclude=[]
    )

    assert result.country_excluded_count == 0
    assert connector.health_check()["countries_seen"].get("FR", 0) >= 1
    assert any(job["country_canonical"] == "FR" for job in result.jobs)


def test_linkedin_never_asks_for_an_excluded_country():
    fetch = linkedin_fetch()
    connector = build("linkedin_europe", fetch)

    connector.discover_internships(
        source("linkedin_europe"), selection_brief=brief(), countries_exclude=["FR", "DE"]
    )

    assert fetch.calls
    locations = {_query(url).get("location", [""])[0] for url in fetch.calls}
    assert "France" not in locations
    assert "Germany" not in locations
    assert "United Kingdom" in locations
    for url in fetch.calls:
        assert "France" not in url


def test_eures_never_asks_for_an_excluded_country():
    fetch = eures_fetch()
    connector = build("eures", fetch)

    connector.discover_internships(
        source("eures"), selection_brief=brief(), countries_exclude=["FR"]
    )

    assert fetch.calls
    codes = _query(fetch.calls[0])["countryCodes"][0].split(",")
    assert "FR" not in codes
    assert "DE" in codes and "GB" in codes
    assert len(codes) > 20


def test_jobteaser_never_asks_for_an_excluded_country():
    fetch = jobteaser_fetch()
    connector = build("jobteaser_intl", fetch)

    connector.discover_internships(
        source("jobteaser_intl"), selection_brief=brief(), countries_exclude=["FR"]
    )

    assert fetch.calls
    codes = _query(fetch.calls[0])["countries"][0].split(",")
    assert "FR" not in codes
    assert codes == ["DE", "GB", "NL", "BE", "CH", "ES", "IT", "PT"]


def test_glassdoor_never_asks_for_an_excluded_country():
    fetch = glassdoor_fetch()
    connector = build("glassdoor_intl", fetch)

    connector.discover_internships(
        source("glassdoor_intl"), selection_brief=brief(), countries_exclude=["FR"]
    )

    assert fetch.calls
    identifiers = {_query(url).get("locId", [""])[0] for url in fetch.calls}
    assert "5" not in identifiers  # 5 is the Glassdoor identifier of France
    assert "4" in identifiers  # 4 is the Glassdoor identifier of Germany


def test_eures_drops_a_french_answer_even_though_france_was_never_asked_for():
    """A source that answers with an excluded country is still filtered."""
    body = json.dumps({
        "result": {
            "items": [
                {
                    "id": "eures-fr-1",
                    "title": "Finance Intern",
                    "employerName": "Example Paris SA",
                    "location": {"name": "Paris", "countryCode": "FR", "countryName": "France"},
                    "contractType": "INTERNSHIP",
                    "description": "<p>Finance internship in Paris.</p>",
                    "applicationUrl": "https://careers.example.test/jobs/eures-fr-1",
                    "publicationDate": 1760000000000,
                    "startDate": "2027-02-01",
                    "duration": 6,
                }
            ]
        }
    })
    connector = build("eures", RecordedFetch(body))

    result = connector.discover_internships(
        source("eures"), selection_brief=brief(), countries_exclude=["FR"]
    )

    assert result.jobs == ()
    assert result.country_excluded_count == 1
    assert result.excluded_by_country == {"FR": 1}


def test_the_country_of_the_request_is_the_fallback():
    """A card without a country keeps the country the search was made for."""
    body = json.dumps({
        "result": {
            "items": [
                {
                    "id": "eures-1",
                    "title": "Finance Intern",
                    "employerName": "Example Bank GmbH",
                    "location": {"name": "Berlin", "countryCode": "DE"},
                    "contractType": "INTERNSHIP",
                    "description": "<p>Financial analysis internship.</p>",
                    "applicationUrl": "https://careers.example.test/jobs/eures-1",
                    "startDate": "2027-02-01",
                    "duration": 6,
                }
            ]
        }
    })
    connector = build("eures", RecordedFetch(body))

    result = connector.discover_internships(source("eures"), selection_brief=brief())

    assert result.jobs[0]["country_canonical"] == "DE"


def test_a_missing_country_is_never_guessed():
    """A card that names no country keeps an unknown country."""
    body = json.dumps({
        "result": {
            "items": [
                {
                    "id": "eures-1",
                    "title": "Finance Intern",
                    "employerName": "Example Bank GmbH",
                    "location": {"name": "Berlin"},
                    "contractType": "INTERNSHIP",
                    "description": "<p>Financial analysis internship.</p>",
                    "applicationUrl": "https://careers.example.test/jobs/eures-1",
                    "startDate": "2027-02-01",
                    "duration": 6,
                }
            ]
        }
    })
    connector = build("eures", RecordedFetch(body))

    result = connector.discover_internships(source("eures"), selection_brief=brief())

    assert result.jobs[0]["country_canonical"] == ""


# --- the published facts -----------------------------------------------------

def test_eures_reads_the_structured_facts():
    fetch = eures_fetch()
    connector = build("eures", fetch)

    result = connector.discover_internships(source("eures"), selection_brief=brief())
    job = next(item for item in result.jobs if item["source_id"] == "eures-0001")

    assert job["title"] == "Finance Intern"
    assert job["company"] == "Example Bank GmbH"
    assert job["city"] == "Berlin"
    assert job["country"] == "Germany"
    assert job["country_canonical"] == "DE"
    assert job["employment_type"] == "Internship"
    assert job["official_url"] == "https://careers.example.test/jobs/eures-0001"
    assert job["start_date"] == "2027-02-01"
    assert job["duration_months"] == 6
    assert job["posted_date"] == "2025-10-09"
    assert "Financial analysis" in job["description_original"]
    assert "<p>" not in job["description_original"]


def test_linkedin_reads_the_published_card():
    fetch = linkedin_fetch()
    connector = build("linkedin_europe", fetch)

    result = connector.discover_internships(source("linkedin_europe"), selection_brief=brief())
    job = next(item for item in result.jobs if "4123456789" in item["official_url"])

    assert job["title"] == "Finance Intern (m/f/d)"
    assert job["company"] == "Example Bank GmbH"
    assert job["city"] == "Berlin"
    assert job["country"] == "Germany"
    assert job["country_canonical"] == "DE"
    assert job["posted_date"] == "2026-10-19"
    assert job["employment_type"] == "Internship"
    assert job["source_id"] == "4123456789"


def test_jobteaser_reads_the_published_card():
    fetch = jobteaser_fetch()
    connector = build("jobteaser_intl", fetch)

    result = connector.discover_internships(source("jobteaser_intl"), selection_brief=brief())
    job = next(item for item in result.jobs if "0001" in item["source_id"])

    assert job["title"] == "Finance Intern"
    assert job["company"] == "Example Bank GmbH"
    assert job["country_canonical"] == "DE"
    assert job["employment_type"] == "Internship"


def test_glassdoor_reads_the_published_card():
    fetch = glassdoor_fetch()
    connector = build("glassdoor_intl", fetch)

    result = connector.discover_internships(source("glassdoor_intl"), selection_brief=brief())
    job = next(item for item in result.jobs if "5001" in item["source_id"])

    assert job["title"] == "Finance Intern"
    assert job["company"] == "Example Financial Inc"
    assert job["country_canonical"] == "US"
    assert job["employment_type"] == "Internship"


# --- the source boundary -----------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_an_unverified_source_is_refused(provider):
    connector = build(provider, RecordedFetch("<html></html>"))
    unverified = source(provider)
    unverified["verified_at"] = ""

    with pytest.raises(PublicSourceError) as raised:
        connector.discover_internships(unverified, selection_brief=brief())

    assert raised.value.code == "unverified_source"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_source_of_another_provider_is_refused(provider):
    connector = build(provider, RecordedFetch("<html></html>"))

    with pytest.raises(PublicSourceError) as raised:
        connector.discover_internships(source("welcome_jungle"), selection_brief=brief())

    assert raised.value.code == "invalid_source"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_disabled_connector_reads_nothing(provider):
    fetch = {
        "linkedin_europe": linkedin_fetch,
        "eures": eures_fetch,
        "jobteaser_intl": jobteaser_fetch,
        "glassdoor_intl": glassdoor_fetch,
    }[provider]()
    connector = CONNECTORS[provider](fetch=fetch, enabled=False)

    with pytest.raises(PublicSourceError) as raised:
        connector.discover_internships(source(provider), selection_brief=brief())

    assert raised.value.code == "connector_disabled"
    assert not fetch.calls


def test_a_run_sends_a_bounded_number_of_requests():
    """A source never spends more than its share of the network budget."""
    fetch = linkedin_fetch()
    connector = build("linkedin_europe", fetch)

    connector.discover_internships(source("linkedin_europe"), selection_brief=brief())

    assert fetch.calls
    assert len(fetch.calls) <= LinkedInEuropeConnector.max_requests


def test_the_countries_are_read_round_robin():
    """The request budget is spread over the countries, not spent on the first."""
    fetch = linkedin_fetch()
    connector = build("linkedin_europe", fetch)

    connector.discover_internships(source("linkedin_europe"), selection_brief=brief())

    locations = [_query(url)["location"][0] for url in fetch.calls]
    assert len(set(locations)) == len(locations)


def test_the_read_stops_when_the_network_budget_is_spent():
    """A cut-off keeps the offers already read and says the read is partial."""
    fetch = linkedin_fetch()
    connector = CONNECTORS["linkedin_europe"](
        fetch=fetch, enabled=True, monotonic=lambda: 0.0
    )

    result = connector.discover_internships(
        source("linkedin_europe"), selection_brief=brief(), deadline=0.0
    )

    assert result.jobs == ()
    assert result.truncated is True
    assert connector.health_check()["budget_exhausted"] is True


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_source_that_does_not_answer_leaves_the_existing_offers_alone(provider):
    fetch = RecordedFetch("")
    connector = build(provider, fetch)

    result = connector.discover_internships(source(provider), selection_brief=brief())

    assert result.jobs == ()
    assert result.raw_count == 0


def test_the_shared_entry_point_forwards_the_exclusion():
    """The shared entry point of the exploration reaches the international sources."""
    from career.discovery import discover_stage_offers

    fetch = probe_fetch("eures")
    connector = build("eures", fetch)

    offers = discover_stage_offers({"eures": connector}, [source("eures")])

    assert offers
    assert all(offer["country_canonical"] != "FR" for offer in offers)
    assert EuresConnector.health_check()["excluded_by_country"] == {"FR": 1}


def test_the_exploration_service_never_imports_a_french_offer(tmp_path):
    """The end-to-end path: a French offer never reaches the local database."""
    from career.service import CareerService

    curated = ({
        "id": "registry:eures:synthetic",
        "provider": "eures",
        "company": "EURES",
        "public_url": "https://ec.europa.eu/eures/eures-job-search",
        "provenance_url": "https://ec.europa.eu/eures/eures-job-search",
        "verified_at": "2026-10-20T00:00:00Z",
    },)
    connector = EuresConnector(
        fetch=eures_probe_fetch(), enabled=True, clock=lambda: "2026-10-22T00:00:00Z"
    )
    service = CareerService(
        tmp_path, curated_sources=curated, exploration_connectors={"eures": connector}
    )

    result = service.explore_internships()

    jobs = service.list_jobs()
    assert jobs, "le parcours doit importer les offres publiées hors France"
    assert all(job.get("country") != "France" for job in jobs)
    assert all(job.get("city") != "Paris" for job in jobs)
    assert result["summary"]["sources_succeeded"] == 1
    assert result["summary"]["retained_count"] == len(jobs)


# --- the source tier ---------------------------------------------------------

def test_the_source_tier_never_claims_an_employer_without_proof():
    """A portal that republishes postings is an aggregator, not an employer."""
    assert EuresConnector.source_tier == SOURCE_TIER_OFFICIAL
    assert LinkedInEuropeConnector.source_tier == SOURCE_TIER_AGGREGATOR
    assert JobTeaserIntlConnector.source_tier == SOURCE_TIER_AGGREGATOR
    assert GlassdoorIntlConnector.source_tier == SOURCE_TIER_AGGREGATOR
    for connector_class in CONNECTORS.values():
        assert connector_class.source_tier != SOURCE_TIER_EMPLOYER

    fetch = linkedin_fetch()
    connector = build("linkedin_europe", fetch)
    result = connector.discover_internships(source("linkedin_europe"), selection_brief=brief())
    for job in result.jobs:
        assert job["source_tier"] == SOURCE_TIER_AGGREGATOR
        assert "linkedin.com" in job["official_url"]


# --- politeness --------------------------------------------------------------

def test_two_requests_are_never_closer_than_the_interval():
    """The reader waits between two requests, and the wait is observable."""
    slept: list[float] = []
    clock = {"now": 0.0}

    def monotonic() -> float:
        return clock["now"]

    def sleeper(delay: float) -> None:
        slept.append(delay)
        clock["now"] += delay

    def transport(url, headers, timeout):
        return "<html></html>"

    fetcher = PoliteFetcher(
        hosts={"www.example.test"},
        user_agent="test",
        min_interval=2.0,
        transport=transport,
        sleeper=sleeper,
        monotonic=monotonic,
        respect_robots=False,
    )

    assert fetcher.fetch("https://www.example.test/a") == "<html></html>"
    assert fetcher.fetch("https://www.example.test/b") == "<html></html>"

    assert slept == [2.0]


def test_a_host_outside_the_allow_list_is_never_contacted():
    def transport(url, headers, timeout):
        raise AssertionError("un hôte non autorisé a été contacté")

    fetcher = PoliteFetcher(
        hosts={"www.example.test"},
        user_agent="test",
        transport=transport,
        respect_robots=False,
    )

    assert fetcher.fetch("https://elsewhere.test/a") is None


def test_the_robots_txt_of_the_source_is_honoured():
    def transport(url, headers, timeout):
        if url.endswith("/robots.txt"):
            return "User-agent: *\nDisallow: /jobs/\n"
        return "<html></html>"

    fetcher = PoliteFetcher(
        hosts={"www.example.test"},
        user_agent="test",
        transport=transport,
        respect_robots=True,
    )

    assert fetcher.fetch("https://www.example.test/jobs/1") is None
    assert fetcher.fetch("https://www.example.test/news/1") == "<html></html>"


def test_the_crawl_delay_of_the_source_is_applied():
    slept: list[float] = []
    clock = {"now": 0.0}

    def sleeper(delay: float) -> None:
        slept.append(delay)
        clock["now"] += delay

    def transport(url, headers, timeout):
        if url.endswith("/robots.txt"):
            return "User-agent: *\nCrawl-delay: 7\n"
        return "<html></html>"

    fetcher = PoliteFetcher(
        hosts={"www.example.test"},
        user_agent="test",
        min_interval=1.0,
        transport=transport,
        sleeper=sleeper,
        monotonic=lambda: clock["now"],
        respect_robots=True,
    )

    fetcher.fetch("https://www.example.test/a")
    fetcher.fetch("https://www.example.test/b")

    # The published delay of seven seconds is longer than the connector's
    # own interval, and it is the one that applies.
    assert slept == [7.0, 7.0]


def test_the_robots_rules_are_read_as_published():
    policy = RobotsPolicy("User-agent: *\nDisallow: /private/\nAllow: /private/public\n")

    assert policy.allows("https://www.example.test/jobs/1") is True
    assert policy.allows("https://www.example.test/private/x") is False
    assert policy.allows("https://www.example.test/private/public") is True


# --- dependencies ------------------------------------------------------------

def test_the_connectors_only_use_the_standard_library():
    """No third-party dependency is imported by the international sources.

    The only tolerated import is ``certifi``, and only inside a ``try``:
    it provides the Mozilla root bundle when it is installed, and the
    standard library context is used when it is not.
    """
    package = Path(__file__).parent.parent / "career" / "connectors"
    allowed_roots = {"career", "workspace_core"}
    standard_library = set(sys.stdlib_module_names)
    optional = {"certifi"}
    for name in ("intl_common.py", "linkedin_europe.py", "eures.py", "jobteaser_intl.py", "glassdoor_intl.py"):
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        guarded: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            branches = list(node.body) + [item for handler in node.handlers for item in handler.body]
            for branch in branches:
                for inner in ast.walk(branch):
                    if isinstance(inner, ast.Import):
                        guarded.update(alias.name.split(".")[0] for alias in inner.names)
                    elif isinstance(inner, ast.ImportFrom) and inner.module:
                        guarded.add(inner.module.split(".")[0])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue  # a relative import stays inside the package
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                root = module.split(".")[0]
                if root in guarded:
                    assert root in optional, (
                        f"{name} importe « {module} » sous condition : seule une dépendance optionnelle est tolérée"
                    )
                    continue
                assert root in standard_library or root in allowed_roots, (
                    f"{name} importe « {module} », qui n'appartient pas à la bibliothèque standard"
                )
