"""Synthetic contract tests for the UK sources connector; sockets stay blocked.

Every page read by these tests is built in the test file or loaded from
``tests/fixtures/uk_sources_synthetic.json``.  No public board is contacted and
no socket is opened: ``fetch`` is always injected, and the transport-level
tests use a fake ``opener``.
"""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from career.connectors import CONNECTOR_REGISTRY, CONNECTOR_SPECS, UkSourcesConnector
from career.connectors import uk_sources as uk
from career.connectors.uk_sources import (
    UK_PROVIDERS,
    fetch_published_html,
    register_uk_sources_connector,
)
from career.discovery import PublicSourceError
from career.stage_search import default_brief, validate_brief


FIXTURE = Path(__file__).parent / "fixtures" / "uk_sources_synthetic.json"
PROVENANCE = {
    "prospects": "https://www.prospects.ac.uk/jobs-and-work-experience/job-sectors",
    "gradcracker": "https://www.gradcracker.com/search/all-disciplines/finance",
    "targetjobs": "https://targetjobs.co.uk/internships",
}
WRAPPERS = {
    "prospects": ("li", "search-result job-card", "data-job-id"),
    "gradcracker": ("article", "job-card", "data-offer-id"),
    "targetjobs": ("div", "job-result", "data-vacancy-id"),
}


@pytest.fixture(autouse=True)
def _clean_health():
    UkSourcesConnector.reset_health()
    yield
    UkSourcesConnector.reset_health()


@pytest.fixture
def fixtures():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FixtureFetch:
    """Replay synthetic pages; never raise if a test forgets a page."""

    def __init__(self, html_responses):
        self.responses = list(html_responses)
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("fixture fetch exhausted")
        return self.responses.pop(0)


def source(provider: str, **extra) -> dict:
    return {
        "id": f"synthetic:{provider}:board",
        "provider": provider,
        "company": "Synthetic UK Board",
        "verified_at": "2026-10-31T00:00:00Z",
        "provenance_url": PROVENANCE.get(provider, "https://www.example.test/jobs"),
    } | extra


def build_page(provider: str, jobs: list[dict], *, with_time: bool = True) -> str:
    """Build the semantic result card the connector is contracted to read."""
    tag, marker, identifier = WRAPPERS[provider]
    cards = []
    for job in jobs:
        published = job.get("published", "")
        time_tag = f'<time datetime="{published}">{published}</time>' if with_time and published else ""
        cards.append(
            f'<{tag} class="{marker}" {identifier}="{job.get("id", "")}">'
            f'<h3 class="job-title">{job.get("title", "")}</h3>'
            f'<span class="company">{job.get("company", "")}</span>'
            f'<span class="location">{job.get("location", "")}</span>'
            f'<span class="contract-type">{job.get("contract_type", "")}</span>'
            f'{time_tag}'
            f'<a href="{job.get("url", "")}">View offer</a>'
            f'<div class="description">{job.get("description", "")}</div>'
            f'</{tag}>'
        )
    return f"<html><body>{''.join(cards)}</body></html>"


def run(provider: str, jobs: list[dict], *, brief=None, **connector_kwargs):
    fetch = FixtureFetch([build_page(provider, jobs)])
    connector = UkSourcesConnector(
        clock=lambda: "2026-10-31T01:00:00Z",
        fetch=fetch,
        **connector_kwargs,
    )
    payload = connector.discover_internships(source(provider), selection_brief=brief or default_brief())
    return payload, fetch


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def http_error(url: str = "https://targetjobs.co.uk/internships/finance", code: int = 429,
               retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(url, code, "synthetic error", headers, io.BytesIO(b""))


# --- Registration ------------------------------------------------------------


@pytest.mark.parametrize("provider", UK_PROVIDERS)
def test_connector_is_registered(provider):
    assert provider in CONNECTOR_REGISTRY
    assert CONNECTOR_REGISTRY[provider][0] is UkSourcesConnector


@pytest.mark.parametrize("provider", UK_PROVIDERS)
def test_connector_spec_is_disabled_by_default_and_documented(provider):
    spec = CONNECTOR_SPECS[provider]
    assert spec.provider == provider
    assert spec.doc_verified is True
    assert spec.documentation_url.startswith("https://")
    assert spec.enabled_by_default is False


def test_registration_helper_maps_the_three_boards():
    registry: dict[str, tuple] = {}
    register_uk_sources_connector(registry)
    assert set(registry) == set(UK_PROVIDERS)
    assert all(value == (UkSourcesConnector, "class") for value in registry.values())


def test_connector_is_disabled_when_instantiated_directly():
    assert UkSourcesConnector().enabled is False


# --- Common contract ---------------------------------------------------------


@pytest.mark.parametrize("provider", UK_PROVIDERS)
def test_maps_synthetic_postings_to_the_common_contract(provider, fixtures):
    jobs = fixtures[provider]
    payload, _fetch = run(provider, jobs)

    assert len(payload.jobs) == len(jobs)
    for job in payload.jobs:
        assert job["source_name"] == provider
        assert job["source_id"]
        assert job["official_url"].startswith("https://")
        assert job["source_verified"] is True
        assert job["employment_type"] == "Internship"
        assert job["country_canonical"] == "GB"
        assert job["description_original"]


def test_published_identifier_is_transmitted_unchanged(fixtures):
    provider = "targetjobs"
    payload, _fetch = run(provider, fixtures[provider])
    assert {job["source_id"] for job in payload.jobs} == {job["id"] for job in fixtures[provider]}


def test_published_timestamp_is_transmitted_under_its_source_name(fixtures):
    provider = "prospects"
    payload, _fetch = run(provider, fixtures[provider])
    job = next(job for job in payload.jobs if job["source_id"] == fixtures[provider][0]["id"])
    assert job["source_fields"][provider]["datetime"] == fixtures[provider][0]["published"]


def test_visible_fields_keep_their_source_name(fixtures):
    provider = "gradcracker"
    payload, _fetch = run(provider, fixtures[provider])
    job = payload.jobs[0]
    published = job["source_fields"][provider]
    assert published["title"] == job["title"]
    assert published["company"] == job["company"]
    assert published["url"] == job["official_url"]


@pytest.mark.parametrize("provider", UK_PROVIDERS)
def test_empty_page_returns_no_jobs(provider):
    payload, _fetch = run(provider, [])
    assert payload.jobs == ()
    assert payload.raw_count == 0
    assert payload.evaluated_count == 0


def test_malformed_html_is_handled_gracefully():
    fetch = FixtureFetch(['<html><body><article class="job-card"><h3 class="title">Broken</h3></body></html>'])
    connector = UkSourcesConnector(fetch=fetch)
    payload = connector.discover_internships(source("gradcracker"), selection_brief=default_brief())
    assert isinstance(payload.jobs, tuple)


@pytest.mark.parametrize("provider", UK_PROVIDERS)
def test_missing_required_fields_never_create_a_job(provider, fixtures):
    job = dict(fixtures[provider][0])
    job["company"] = ""
    payload, _fetch = run(provider, [job])
    assert payload.jobs == ()
    # The card is read, then dropped before it can enter the evaluated stream.
    assert UkSourcesConnector.health_check()["raw_count"] == 1
    assert UkSourcesConnector.health_check()["filtered_count"] == 1


def test_missing_description_does_not_break_the_read(fixtures):
    provider = "prospects"
    job = dict(fixtures[provider][0], description="")
    payload, _fetch = run(provider, [job])
    assert payload.raw_count == 1
    assert isinstance(payload.jobs, tuple)


def test_a_card_without_a_title_is_not_published(fixtures):
    provider = "targetjobs"
    job = dict(fixtures[provider][0], title="")
    payload, _fetch = run(provider, [job])
    assert payload.jobs == ()
    assert payload.raw_count == 0


# --- Source-side safety ------------------------------------------------------


def test_a_link_to_another_host_is_ignored(fixtures):
    provider = "targetjobs"
    job = dict(fixtures[provider][0], url="https://attacker.invalid/internships/fake-offer")
    payload, _fetch = run(provider, [job])
    assert payload.jobs == ()


def test_a_link_with_credentials_is_dropped(fixtures):
    provider = "prospects"
    job = dict(
        fixtures[provider][0],
        url="https://user:secret@www.prospects.ac.uk/jobs/ma-internship-london",
    )
    payload, _fetch = run(provider, [job])
    assert payload.jobs == ()
    assert UkSourcesConnector.health_check()["filtered_count"] == 1


def test_category_links_are_not_mistaken_for_offers():
    html = (
        '<html><body>'
        '<div class="job-card"><h3 class="title">Finance Internship</h3>'
        '<span class="company">Synthetic</span>'
        '<a href="/internships/finance">Finance sector</a></div>'
        '</body></html>'
    )
    fetch = FixtureFetch([html])
    payload = UkSourcesConnector(fetch=fetch).discover_internships(
        source("targetjobs"), selection_brief=default_brief()
    )
    assert payload.jobs == ()


def test_a_tracking_query_is_removed_by_the_official_url_normalizer(fixtures):
    provider = "gradcracker"
    job = dict(
        fixtures[provider][0],
        url="https://www.gradcracker.com/job/2001/jpmorgan-finance-internship?utm_source=newsletter&gclid=track",
    )
    payload, _fetch = run(provider, [job])
    assert payload.jobs
    assert "gclid" not in payload.jobs[0]["official_url"]


# --- Geography ---------------------------------------------------------------


@pytest.mark.parametrize("provider", UK_PROVIDERS)
def test_france_is_excluded_at_the_source(provider, fixtures):
    job = dict(fixtures[provider][0], location="Paris, France")
    payload, _fetch = run(provider, [job])
    assert payload.jobs == ()
    assert payload.excluded_by_country == {"FR": 1}
    assert payload.country_excluded_count == 1
    assert UkSourcesConnector.health_check()["excluded_by_country"] == {"FR": 1}


@pytest.mark.parametrize("wording", ["Paris, France", "Paris, FRANCE", "Paris, fr", "Paris, FRA"])
def test_french_wording_variants_are_excluded(wording, fixtures):
    provider = "prospects"
    job = dict(fixtures[provider][0], location=wording)
    payload, _fetch = run(provider, [job])
    assert payload.jobs == ()
    assert payload.excluded_by_country == {"FR": 1}


def test_an_emptied_exclusion_list_allows_france(fixtures):
    provider = "targetjobs"
    job = dict(fixtures[provider][0], location="Paris, France")
    payload, _fetch = run(provider, [job], brief=validate_brief({"countries_exclude": []}))
    assert len(payload.jobs) == 1
    assert payload.excluded_by_country == {}


def test_a_city_only_location_defaults_to_the_united_kingdom(fixtures):
    provider = "gradcracker"
    job = dict(fixtures[provider][2])
    payload, _fetch = run(provider, [job])
    assert payload.jobs[0]["city"] == "Leeds"
    assert payload.jobs[0]["country"] == "United Kingdom"
    assert payload.jobs[0]["country_canonical"] == "GB"


def test_a_dash_separated_location_is_read(fixtures):
    provider = "prospects"
    job = dict(fixtures[provider][2])
    payload, _fetch = run(provider, [job])
    assert payload.jobs[0]["city"] == "Edinburgh"
    assert payload.jobs[0]["country_canonical"] == "GB"


# --- Bounds, budget and counters --------------------------------------------


def test_max_pages_is_clamped_to_the_hard_limit():
    assert UkSourcesConnector(max_pages=99).max_pages == uk._UK_MAX_PAGES
    assert UkSourcesConnector(max_pages=0).max_pages == 1


def test_max_results_bounds_the_returned_tuple(fixtures):
    provider = "prospects"
    payload, _fetch = run(provider, fixtures[provider], max_results=1)
    assert len(payload.jobs) == 1
    assert payload.truncated is True
    assert payload.relevant_count == len(fixtures[provider])


def test_row_cap_stops_the_read(fixtures, monkeypatch):
    provider = "prospects"
    monkeypatch.setattr(uk, "_UK_MAX_ROWS", 2)
    fetch = FixtureFetch([build_page(provider, fixtures[provider])])
    connector = UkSourcesConnector(fetch=fetch)
    with pytest.raises(PublicSourceError) as error:
        connector.discover_internships(source(provider), selection_brief=default_brief())
    assert error.value.code == "too_many_rows"


def test_deadline_stops_the_read(fixtures):
    provider = "prospects"
    fetch = FixtureFetch([build_page(provider, fixtures[provider])])
    connector = UkSourcesConnector(monotonic=lambda: 100.0, fetch=fetch)
    with pytest.raises(PublicSourceError) as error:
        connector.discover_internships(
            source(provider), selection_brief=default_brief(), deadline=50.0
        )
    assert error.value.code == "budget"


def test_counters_are_consistent(fixtures):
    provider = "gradcracker"
    payload, _fetch = run(provider, fixtures[provider])
    assert payload.raw_count == payload.evaluated_count + payload.invalid_count
    assert payload.evaluated_count == payload.confirmed_count + payload.uncertain_count + payload.excluded_count
    assert payload.relevant_count + payload.filtered_criteria_count == (
        payload.confirmed_count + payload.uncertain_count
    )


def test_health_check_exposes_bounded_metrics():
    health = UkSourcesConnector.health_check()
    assert set(health) >= {
        "last_ok", "last_error", "consecutive_failures", "raw_offers", "valid_offers",
        "finance_offers", "stage_offers", "conforming_offers", "to_verify_offers",
        "raw_count", "filtered_count", "excluded_count", "excluded_by_country",
        "throttled_requests",
    }
    assert isinstance(health["excluded_by_country"], dict)
    assert all(isinstance(value, (bool, int, str, type(None), dict)) for value in health.values())


# --- Source identity ---------------------------------------------------------


def test_refuses_a_source_that_is_not_a_uk_board():
    connector = UkSourcesConnector()
    with pytest.raises(PublicSourceError) as error:
        connector.discover_internships(source("greenhouse"), selection_brief=default_brief())
    assert error.value.code == "invalid_source"


def test_refuses_an_unknown_provider():
    connector = UkSourcesConnector()
    with pytest.raises(PublicSourceError) as error:
        connector.discover_internships(source("linkedin"), selection_brief=default_brief())
    assert error.value.code == "invalid_source"


@pytest.mark.parametrize("missing", ["id", "company", "verified_at", "provenance_url"])
def test_refuses_a_source_without_verified_provenance(missing):
    connector = UkSourcesConnector()
    incomplete = source("prospects", **{missing: ""})
    with pytest.raises(PublicSourceError) as error:
        connector.discover_internships(incomplete, selection_brief=default_brief())
    assert error.value.code == "unverified_source"


# --- Search URLs -------------------------------------------------------------


@pytest.mark.parametrize("provider", UK_PROVIDERS)
def test_search_url_stays_on_the_provider_host(provider):
    url = uk._build_search_url(provider, 2)
    parsed = urllib.parse.urlsplit(url)
    assert parsed.hostname == urllib.parse.urlsplit(uk._UK_BASES[provider]).hostname
    query = urllib.parse.parse_qs(parsed.query)
    assert query["page"] == ["2"]
    assert query["query"] == ["finance internship"]


def test_search_url_clamps_the_page_number():
    url = uk._build_search_url("targetjobs", 999)
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["page"] == [str(uk._UK_MAX_PAGES)]


def test_search_url_refuses_an_unsupported_provider():
    with pytest.raises(ValueError):
        uk._build_search_url("linkedin")


# --- HTTP transport: 429, backoff, size and honesty --------------------------


def test_429_is_retried_then_succeeds():
    calls = []

    def opener(request, timeout=None, context=None):
        calls.append(request)
        if len(calls) == 1:
            raise http_error()
        return FakeResponse(b"<html>ok</html>")

    delays: list[float] = []
    body = fetch_published_html(
        "https://targetjobs.co.uk/internships/finance", opener=opener, sleeper=delays.append
    )
    assert body == "<html>ok</html>"
    assert len(calls) == 2
    assert delays == [uk._UK_BACKOFF_SECONDS]
    assert UkSourcesConnector.health_check()["throttled_requests"] == 1


def test_429_is_given_up_after_the_bounded_number_of_retries():
    calls = []

    def opener(request, timeout=None, context=None):
        calls.append(request)
        raise http_error()

    delays: list[float] = []
    body = fetch_published_html(
        "https://targetjobs.co.uk/internships/finance", opener=opener, sleeper=delays.append
    )
    assert body is None
    assert len(calls) == 1 + uk._UK_MAX_429_RETRIES
    assert delays == [uk._UK_BACKOFF_SECONDS, 2 * uk._UK_BACKOFF_SECONDS]
    assert UkSourcesConnector.health_check()["last_error"] == "HTTP 429"
    assert UkSourcesConnector.health_check()["throttled_requests"] == uk._UK_MAX_429_RETRIES


def test_retry_after_header_is_honoured():
    delays: list[float] = []
    calls = []

    def opener(request, timeout=None, context=None):
        calls.append(request)
        if len(calls) == 1:
            raise http_error(retry_after="3")
        return FakeResponse(b"ok")

    fetch_published_html("https://targetjobs.co.uk/internships/finance", opener=opener, sleeper=delays.append)
    assert delays == [3.0]


def test_retry_after_is_bounded():
    delays: list[float] = []
    calls = []

    def opener(request, timeout=None, context=None):
        calls.append(request)
        if len(calls) == 1:
            raise http_error(retry_after="999")
        return FakeResponse(b"ok")

    fetch_published_html("https://targetjobs.co.uk/internships/finance", opener=opener, sleeper=delays.append)
    assert delays == [uk._UK_MAX_BACKOFF_SECONDS]


def test_backoff_is_exponential_without_retry_after():
    delays: list[float] = []

    def opener(request, timeout=None, context=None):
        raise http_error()

    fetch_published_html("https://targetjobs.co.uk/internships/finance", opener=opener, sleeper=delays.append)
    assert delays == [1.0, 2.0]


def test_rate_limit_waits_between_requests(monkeypatch):
    monkeypatch.setattr(uk, "_LAST_REQUEST_TIME", 10.0)
    delays: list[float] = []
    uk._wait_for_rate_limit(monotonic=lambda: 10.5, sleeper=delays.append, rate_limit=2.0)
    assert delays == [1.5]
    assert uk._LAST_REQUEST_TIME == 12.0


def test_rate_limit_does_not_wait_when_the_delay_has_elapsed(monkeypatch):
    monkeypatch.setattr(uk, "_LAST_REQUEST_TIME", 10.0)
    delays: list[float] = []
    uk._wait_for_rate_limit(monotonic=lambda: 13.0, sleeper=delays.append, rate_limit=2.0)
    assert delays == []


def test_user_agent_is_honest():
    requests = []

    def opener(request, timeout=None, context=None):
        requests.append(request)
        return FakeResponse(b"ok")

    fetch_published_html("https://www.prospects.ac.uk/jobs", opener=opener, sleeper=lambda _delay: None)
    headers = {name.lower(): value for name, value in requests[0].headers.items()}
    assert headers["user-agent"] == uk._UK_USER_AGENT
    assert headers["user-agent"].startswith("ComeAI-StageBot/1.0")
    assert "read-only" in headers["user-agent"]


def test_oversized_response_is_refused():
    body = fetch_published_html(
        "https://www.prospects.ac.uk/jobs",
        opener=lambda request, timeout=None, context=None: FakeResponse(b"0123456789"),
        sleeper=lambda _delay: None,
        max_bytes=4,
    )
    assert body is None
    assert UkSourcesConnector.health_check()["last_error"] == "Response too large"


def test_http_error_other_than_429_is_reported():
    body = fetch_published_html(
        "https://www.prospects.ac.uk/jobs",
        opener=lambda request, timeout=None, context=None: (_ for _ in ()).throw(http_error(code=500)),
        sleeper=lambda _delay: None,
    )
    assert body is None
    assert UkSourcesConnector.health_check()["last_error"] == "HTTP 500"


def test_network_error_is_reported():
    def opener(request, timeout=None, context=None):
        raise urllib.error.URLError("offline")

    body = fetch_published_html("https://www.prospects.ac.uk/jobs", opener=opener, sleeper=lambda _delay: None)
    assert body is None
    assert UkSourcesConnector.health_check()["last_error"].startswith("Network error:")


# --- HTML normalization ------------------------------------------------------


def test_scripts_and_styles_never_reach_the_description(fixtures):
    provider = "prospects"
    job = dict(
        fixtures[provider][0],
        description=(
            "<p>Six-month internship starting January 2027.</p>"
            "<script>alert('secret_marker')</script><style>.secret{}</style>"
        ),
    )
    payload, _fetch = run(provider, [job])
    description = payload.jobs[0]["description_original"]
    assert "Six-month internship" in description
    assert "secret_marker" not in description
    assert "alert" not in description


def test_html_entities_are_decoded(fixtures):
    provider = "gradcracker"
    job = dict(
        fixtures[provider][0],
        description="<p>Six-month internship &amp; financial analysis starting January 2027.</p>",
    )
    payload, _fetch = run(provider, [job])
    assert "&amp;" not in payload.jobs[0]["description_original"]
    assert "&" in payload.jobs[0]["description_original"]
