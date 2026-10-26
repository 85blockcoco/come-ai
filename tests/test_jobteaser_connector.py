"""Synthetic contract tests for JobTeaser connector; sockets stay blocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.connectors.jobteaser import JobTeaserConnector
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
        "provenance_url": "https://www.jobteaser.com/en/jobs",
    } | extra


def build_jobteaser_html(jobs):
    """Build synthetic HTML for JobTeaser job cards."""
    cards = []
    for job in jobs:
        card = f'''
        <article class="job-card">
            <h3 class="title">{job["title"]}</h3>
            <span class="company">{job["company"]}</span>
            <span class="location">{job["location"]}</span>
            <span class="contract">{job["contract_type"]}</span>
            <a href="{job["url"].replace("https://www.jobteaser.com", "")}"></a>
            <div class="description">{job["description"]}</div>
        </article>
        '''
        cards.append(card)
    return f"<html><body>{''.join(cards)}</body></html>"


def test_jobteaser_connector_registered():
    from career.connectors import CONNECTOR_SPECS, CONNECTOR_REGISTRY
    assert "jobteaser" in CONNECTOR_SPECS
    assert "jobteaser" in CONNECTOR_REGISTRY
    spec = CONNECTOR_SPECS["jobteaser"]
    assert spec.provider == "jobteaser"
    assert spec.doc_verified is True
    assert spec.documentation_url == "https://www.jobteaser.com/en/jobs"
    assert spec.enabled_by_default is False


def test_jobteaser_maps_synthetic_postings_to_common_contract(fixtures):
    raw = fixtures["jobteaser"]
    html = build_jobteaser_html(raw)
    fetch = FixtureFetch([html])
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)

    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())

    assert hasattr(result, 'jobs')
    assert isinstance(result.jobs, tuple)
    assert len(result.jobs) == 3
    for job in result.jobs:
        assert job["company"] in {"Morgan Stanley", "Partners Group", "Banco Santander"}
        assert job["source_name"] == "jobteaser"
        assert job["source_id"]
        assert job["official_url"].startswith("https://")
        assert job["source_verified"] is True
        assert job["employment_type"] in {"Internship", "Stage"}


def test_jobteaser_preserves_published_fields_and_contract_conflict(fixtures):
    posting = dict(fixtures["jobteaser"][0])
    posting["description"] = "<p>Permanent contract opportunity for a finance internship.</p>"
    connector = JobTeaserConnector(
        fetch=FixtureFetch([build_jobteaser_html([posting])]),
        clock=lambda: "2026-10-20T01:00:00Z",
    )
    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    job = result.jobs[0]
    fields = job["source_fields"]["jobteaser"]
    assert fields["contract_type"] == "Internship"
    assert fields["location"] == "London, UK"
    assert fields["url"] == posting["url"]
    assert any(item["kind"] == "contract" for item in job["source_conflicts"])


def test_jobteaser_refuses_until_valid_source(fixtures):
    connector = JobTeaserConnector()
    unverified = {"provider": "jobteaser", "company": "Synthetic Finance", "board_token": "synthetic-board"}
    with pytest.raises(PublicSourceError, match="vérifiée|identity|provenance|source"):
        connector.discover_internships(unverified, selection_brief=default_brief())


def test_jobteaser_refuses_wrong_provider(fixtures):
    connector = JobTeaserConnector()
    wrong = source("greenhouse")
    with pytest.raises(PublicSourceError, match="ne correspond pas"):
        connector.discover_internships(wrong, selection_brief=default_brief())


def test_jobteaser_bounded_pages_and_rows(fixtures):
    html = build_jobteaser_html(fixtures["jobteaser"])
    fetch = FixtureFetch([html])
    connector = JobTeaserConnector(max_pages=1, max_results=10, fetch=fetch)
    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    assert len(result.jobs) <= 10


def test_jobteaser_health_check_returns_metrics():
    health = JobTeaserConnector.health_check()
    assert set(health.keys()) == {
        "last_ok", "last_error", "consecutive_failures",
        "raw_offers", "valid_offers", "finance_offers",
        "stage_offers", "conforming_offers", "to_verify_offers",
        "raw_count", "filtered_count", "excluded_count", "excluded_by_country"
    }
    assert all(isinstance(v, (bool, int, str, type(None), dict)) for v in health.values())
    assert isinstance(health["excluded_by_country"], dict)


def test_jobteaser_france_exclusion(fixtures):
    """Verify that France locations are excluded per R1."""
    raw = fixtures["jobteaser"] + [{
        "title": "M&A Internship - Paris",
        "company": "BNP Paribas",
        "location": "Paris, France",
        "contract_type": "Internship",
        "url": "https://www.jobteaser.com/en/jobs/ma-internship-paris",
        "description": "<p>Stage M&A à Paris.</p>"
    }]
    html = build_jobteaser_html(raw)
    fetch = FixtureFetch([html])
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    for job in result.jobs:
        assert job["country"].lower() not in {"france", "fr"}
        assert "paris" not in job["city"].lower()


def test_jobteaser_consistent_counts(fixtures):
    html = build_jobteaser_html(fixtures["jobteaser"])
    fetch = FixtureFetch([html])
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    assert result.raw_count == result.evaluated_count + result.invalid_count
    assert result.evaluated_count == result.confirmed_count + result.uncertain_count + result.excluded_count
    assert result.relevant_count + result.filtered_criteria_count == result.confirmed_count + result.uncertain_count


def test_jobteaser_official_url_validation(fixtures):
    """Foreign posting URLs should not be admitted."""
    raw = [dict(fixtures["jobteaser"][0])]
    raw[0]["url"] = "https://attacker.invalid/fake"
    html = build_jobteaser_html(raw)
    fetch = FixtureFetch([html])
    connector = JobTeaserConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    for job in result.jobs:
        assert "attacker.invalid" not in job["official_url"]


def test_jobteaser_empty_html_returns_no_jobs():
    fetch = FixtureFetch(["<html><body></body></html>"])
    connector = JobTeaserConnector(fetch=fetch)
    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    assert len(result.jobs) == 0
    assert result.raw_count == 0


def test_jobteaser_malformed_html_handled_gracefully():
    fetch = FixtureFetch(["<html><body><article class=\"job-card\"><h3>Title</h3></body></html>"])
    connector = JobTeaserConnector(fetch=fetch)
    result = connector.discover_internships(source("jobteaser"), selection_brief=default_brief())
    assert isinstance(result.jobs, tuple)
