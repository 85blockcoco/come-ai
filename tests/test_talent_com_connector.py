"""Synthetic contract tests for Talent.com connector; sockets stay blocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.connectors.talent_com import TalentComConnector
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
        "provenance_url": "https://www.talent.com",
    } | extra


def build_talent_com_html(jobs):
    """Build synthetic HTML for Talent.com job cards."""
    cards = []
    for job in jobs:
        card = f'''
        <div class="job-card" data-job-id="{job.get("source_id", "")}">
            <h2 class="title">{job["title"]}</h2>
            <span class="company">{job["company"]}</span>
            <span class="location">{job["location"]}</span>
            <span class="contract">{job["contract_type"]}</span>
            <a href="{job["url"].replace("https://www.talent.com", "")}"></a>
            <div class="description">{job["description"]}</div>
        </div>
        '''
        cards.append(card)
    return f"<html><body>{''.join(cards)}</body></html>"


def test_talent_com_connector_registered():
    from career.connectors import CONNECTOR_SPECS, CONNECTOR_REGISTRY
    assert "talent_com" in CONNECTOR_SPECS
    assert "talent_com" in CONNECTOR_REGISTRY
    spec = CONNECTOR_SPECS["talent_com"]
    assert spec.provider == "talent_com"
    assert spec.doc_verified is True
    assert spec.documentation_url == "https://www.talent.com"
    assert spec.enabled_by_default is False


def test_talent_com_maps_synthetic_postings_to_common_contract(fixtures):
    raw = fixtures["talent_com"]
    html = build_talent_com_html(raw)
    fetch = FixtureFetch([html])
    connector = TalentComConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)

    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())

    assert hasattr(result, 'jobs')
    assert isinstance(result.jobs, tuple)
    assert len(result.jobs) == 3
    for job in result.jobs:
        assert job["company"] in {"KBC Group", "Bank of Ireland", "UBS"}
        assert job["source_name"] == "talent_com"
        assert job["source_id"]
        assert job["official_url"].startswith("https://")
        assert job["source_verified"] is True
        assert job["employment_type"] in {"Internship", "Stage"}


def test_talent_com_preserves_published_fields(fixtures):
    connector = TalentComConnector(
        fetch=FixtureFetch([build_talent_com_html(fixtures["talent_com"])]),
        clock=lambda: "2026-10-20T01:00:00Z",
    )
    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    job = result.jobs[0]
    fields = job["source_fields"]["talent_com"]
    assert fields["contract_type"] == "Internship"
    assert fields["location"] == "Brussels, Belgium"
    assert fields["url"] == "https://www.talent.com/job/financial-analyst-intern-brussels"


def test_talent_com_refuses_until_valid_source(fixtures):
    connector = TalentComConnector()
    unverified = {"provider": "talent_com", "company": "Synthetic Finance", "board_token": "synthetic-board"}
    with pytest.raises(PublicSourceError, match="vérifiée|identity|provenance|source"):
        connector.discover_internships(unverified, selection_brief=default_brief())


def test_talent_com_refuses_wrong_provider(fixtures):
    connector = TalentComConnector()
    wrong = source("greenhouse")
    with pytest.raises(PublicSourceError, match="ne correspond pas"):
        connector.discover_internships(wrong, selection_brief=default_brief())


def test_talent_com_bounded_pages_and_rows(fixtures):
    html = build_talent_com_html(fixtures["talent_com"])
    fetch = FixtureFetch([html])
    connector = TalentComConnector(max_pages=1, max_results=10, fetch=fetch)
    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    assert len(result.jobs) <= 10


def test_talent_com_health_check_returns_metrics():
    health = TalentComConnector.health_check()
    assert set(health.keys()) == {
        "last_ok", "last_error", "consecutive_failures",
        "raw_offers", "valid_offers", "finance_offers",
        "stage_offers", "conforming_offers", "to_verify_offers",
        "raw_count", "filtered_count", "excluded_count", "excluded_by_country"
    }
    assert all(isinstance(v, (bool, int, str, type(None), dict)) for v in health.values())
    assert isinstance(health["excluded_by_country"], dict)


def test_talent_com_france_exclusion(fixtures):
    """Verify that France locations are excluded per R1."""
    raw = fixtures["talent_com"] + [{
        "title": "Financial Analyst Intern - Paris",
        "company": "Société Générale",
        "location": "Paris, France",
        "contract_type": "Internship",
        "url": "https://www.talent.com/job/financial-analyst-intern-paris",
        "description": "<p>Stage analyste financier à Paris.</p>"
    }]
    html = build_talent_com_html(raw)
    fetch = FixtureFetch([html])
    connector = TalentComConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    for job in result.jobs:
        assert job["country"].lower() not in {"france", "fr"}
        assert "paris" not in job["city"].lower()


def test_talent_com_consistent_counts(fixtures):
    html = build_talent_com_html(fixtures["talent_com"])
    fetch = FixtureFetch([html])
    connector = TalentComConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    assert result.raw_count == result.evaluated_count + result.invalid_count
    assert result.evaluated_count == result.confirmed_count + result.uncertain_count + result.excluded_count
    assert result.relevant_count + result.filtered_criteria_count == result.confirmed_count + result.uncertain_count


def test_talent_com_official_url_validation(fixtures):
    """Foreign posting URLs should not be admitted."""
    raw = [dict(fixtures["talent_com"][0])]
    raw[0]["url"] = "https://attacker.invalid/fake"
    html = build_talent_com_html(raw)
    fetch = FixtureFetch([html])
    connector = TalentComConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    for job in result.jobs:
        assert "attacker.invalid" not in job["official_url"]


def test_talent_com_empty_html_returns_no_jobs():
    fetch = FixtureFetch(["<html><body></body></html>"])
    connector = TalentComConnector(fetch=fetch)
    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    assert len(result.jobs) == 0
    assert result.raw_count == 0


def test_talent_com_malformed_html_handled_gracefully():
    fetch = FixtureFetch(["<html><body><div class=\"job-card\"><h2>Title</h2></body></html>"])
    connector = TalentComConnector(fetch=fetch)
    result = connector.discover_internships(source("talent_com"), selection_brief=default_brief())
    assert isinstance(result.jobs, tuple)
