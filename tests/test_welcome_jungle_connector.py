"""Synthetic contract tests for Welcome to the Jungle connector; sockets stay blocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.connectors.welcome_jungle import WelcomeJungleConnector
from career.discovery import PublicSourceError
from career.stage_search import default_brief


FIXTURE = Path(__file__).parent / "fixtures" / "career_new_sources_synthetic.json"


class FixtureFetch:
    def __init__(self, html_responses):
        self.responses = list(html_responses)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("fixture fetch exhausted")
        return self.responses.pop(0)


@pytest.fixture
def fixtures():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def source(provider_val, **extra):
    return {
        "id": f"synthetic:{provider_val}:board",
        "provider": provider_val,
        "company": "Synthetic Finance",
        "board_token": "synthetic-board",
        "verified_at": "2026-10-20T00:00:00Z",
        "provenance_url": "https://www.welcometothejungle.com/fr/jobs",
    } | extra


def build_welcome_jungle_html(jobs):
    """Build synthetic HTML for Welcome to the Jungle job cards."""
    cards = []
    for job in jobs:
        card = f'''
        <article data-testid="job-card">
            <h3 data-testid="job-title">{job["title"]}</h3>
            <span data-testid="company">{job["company"]}</span>
            <span data-testid="location">{job["location"]}</span>
            <span data-testid="contract">{job["contract_type"]}</span>
            <a href="{job["url"].replace("https://www.welcometothejungle.com", "")}"></a>
            <div data-testid="description">{job["description"]}</div>
        </article>
        '''
        cards.append(card)
    return f"<html><body>{''.join(cards)}</body></html>"


def test_welcome_jungle_connector_registered():
    from career.connectors import CONNECTOR_SPECS, CONNECTOR_REGISTRY
    assert "welcome_jungle" in CONNECTOR_SPECS
    assert "welcome_jungle" in CONNECTOR_REGISTRY
    spec = CONNECTOR_SPECS["welcome_jungle"]
    assert spec.provider == "welcome_jungle"
    assert spec.doc_verified is True
    assert spec.documentation_url == "https://www.welcometothejungle.com/fr/jobs"
    assert spec.enabled_by_default is False


def test_welcome_jungle_maps_synthetic_postings_to_common_contract(fixtures):
    raw = fixtures["welcome_jungle"]
    html = build_welcome_jungle_html(raw)
    fetch = FixtureFetch([html])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)

    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())

    assert hasattr(result, 'jobs')
    assert isinstance(result.jobs, tuple)
    assert len(result.jobs) == 3
    for job in result.jobs:
        assert job["company"] in {"Goldman Sachs", "DWS Group", "ING Bank"}
        assert job["source_name"] == "welcome_jungle"
        assert job["source_id"]
        assert job["official_url"].startswith("https://")
        assert job["source_verified"] is True
        assert job["employment_type"] in {"Internship", "Stage"}


def test_welcome_jungle_html_normalized_before_education_evidence(fixtures):
    raw = [dict(fixtures["welcome_jungle"][0])]
    raw[0]["description"] = (
        "<ul><li>Bachelor's degree in Finance required.</li></ul>"
        "<script>secret_marker()</script>"
    )
    html = build_welcome_jungle_html(raw)
    fetch = FixtureFetch([html])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)

    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    assert len(result.jobs) >= 1
    job = result.jobs[0]
    assert "<" not in job["description_original"]
    assert "secret_marker" not in job["description_original"]
    assert "Bachelor" in job["description_original"]


def test_welcome_jungle_refuses_until_valid_source(fixtures):
    connector = WelcomeJungleConnector()
    unverified = {"provider": "welcome_jungle", "company": "Synthetic Finance", "board_token": "synthetic-board"}
    with pytest.raises(PublicSourceError, match="vérifiée|identity|provenance|source"):
        connector.discover_internships(unverified, selection_brief=default_brief())


def test_welcome_jungle_refuses_wrong_provider(fixtures):
    connector = WelcomeJungleConnector()
    wrong = source("greenhouse")
    with pytest.raises(PublicSourceError, match="ne correspond pas"):
        connector.discover_internships(wrong, selection_brief=default_brief())


def test_welcome_jungle_bounded_pages_and_rows(fixtures):
    html = build_welcome_jungle_html(fixtures["welcome_jungle"])
    fetch = FixtureFetch([html])
    connector = WelcomeJungleConnector(max_pages=1, max_results=10, fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    assert len(result.jobs) <= 10


def test_welcome_jungle_health_check_returns_metrics():
    health = WelcomeJungleConnector.health_check()
    assert set(health.keys()) == {
        "last_ok", "last_error", "consecutive_failures",
        "raw_offers", "valid_offers", "finance_offers",
        "stage_offers", "conforming_offers", "to_verify_offers",
        "raw_count", "kept_count", "filtered_count", "excluded_count",
        "mixed_count", "unknown_count", "excluded_by_country", "mixed_by_country"
    }
    assert isinstance(health["excluded_by_country"], dict)


def test_welcome_jungle_france_exclusion(fixtures):
    """Verify that France locations are excluded per R1."""
    # Add a France job to test exclusion
    raw = fixtures["welcome_jungle"] + [{
        "title": "M&A Internship - Paris",
        "company": "BNP Paribas",
        "location": "Paris, France",
        "contract_type": "Internship",
        "url": "https://www.welcometothejungle.com/fr/companies/bnpparibas/jobs/ma-internship-paris",
        "description": "<p>Stage M&A à Paris.</p>"
    }]
    html = build_welcome_jungle_html(raw)
    fetch = FixtureFetch([html])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    for job in result.jobs:
        assert job["country"].lower() not in {"france", "fr"}
        assert "paris" not in job["city"].lower()


def test_welcome_jungle_consistent_counts(fixtures):
    html = build_welcome_jungle_html(fixtures["welcome_jungle"])
    fetch = FixtureFetch([html])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    assert result.raw_count == result.evaluated_count + result.invalid_count
    assert result.evaluated_count == result.confirmed_count + result.uncertain_count + result.excluded_count
    assert result.relevant_count + result.filtered_criteria_count == result.confirmed_count + result.uncertain_count


def test_welcome_jungle_official_url_validation(fixtures):
    """Foreign posting URLs should not be admitted."""
    raw = [dict(fixtures["welcome_jungle"][0])]
    raw[0]["url"] = "https://attacker.invalid/fake"
    html = build_welcome_jungle_html(raw)
    fetch = FixtureFetch([html])
    connector = WelcomeJungleConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    for job in result.jobs:
        assert "attacker.invalid" not in job["official_url"]


def test_welcome_jungle_empty_html_returns_no_jobs():
    fetch = FixtureFetch(["<html><body></body></html>"])
    connector = WelcomeJungleConnector(fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    assert len(result.jobs) == 0
    assert result.raw_count == 0


def test_welcome_jungle_malformed_html_handled_gracefully():
    fetch = FixtureFetch(["<html><body><article data-testid=\"job-card\"><h3>Title</h3></body></html>"])
    connector = WelcomeJungleConnector(fetch=fetch)
    result = connector.discover_internships(source("welcome_jungle"), selection_brief=default_brief())
    # Should not crash, but may have 0 jobs due to missing required fields
    assert isinstance(result.jobs, tuple)