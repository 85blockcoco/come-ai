"""Synthetic contract tests for APEC connector; sockets stay blocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.connectors.apec import ApecConnector
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
        "provenance_url": "https://www.apec.fr",
    } | extra


def build_apec_html(jobs):
    """Build synthetic HTML for APEC job cards."""
    cards = []
    for job in jobs:
        card = f'''
        <div class="job-result" data-offer-id="{job.get("source_id", "")}">
            <h2 class="title">{job["title"]}</h2>
            <span class="entreprise">{job["company"]}</span>
            <span class="lieu">{job["location"]}</span>
            <span class="contrat">{job["contract_type"]}</span>
            <a href="{job["url"].replace("https://www.apec.fr", "")}"></a>
            <div class="description">{job["description"]}</div>
        </div>
        '''
        cards.append(card)
    return f"<html><body>{''.join(cards)}</body></html>"


def test_apec_connector_registered():
    from career.connectors import CONNECTOR_SPECS, CONNECTOR_REGISTRY
    assert "apec" in CONNECTOR_SPECS
    assert "apec" in CONNECTOR_REGISTRY
    spec = CONNECTOR_SPECS["apec"]
    assert spec.provider == "apec"
    assert spec.doc_verified is True
    assert spec.documentation_url == "https://www.apec.fr"
    assert spec.enabled_by_default is False


def test_apec_maps_synthetic_postings_to_common_contract(fixtures):
    raw = fixtures["apec"]
    html = build_apec_html(raw)
    fetch = FixtureFetch([html])
    connector = ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)

    result = connector.discover_internships(source("apec"), selection_brief=default_brief())

    assert hasattr(result, 'jobs')
    assert isinstance(result.jobs, tuple)
    assert len(result.jobs) == 3
    for job in result.jobs:
        assert job["company"] in {"Pictet Group", "UniCredit", "Erste Group"}
        assert job["source_name"] == "apec"
        assert job["source_id"]
        assert job["official_url"].startswith("https://")
        assert job["source_verified"] is True
        assert job["employment_type"] == "STAGE"


def test_apec_refuses_until_valid_source(fixtures):
    connector = ApecConnector()
    unverified = {"provider": "apec", "company": "Synthetic Finance", "board_token": "synthetic-board"}
    with pytest.raises(PublicSourceError, match="vérifiée|identity|provenance|source"):
        connector.discover_internships(unverified, selection_brief=default_brief())


def test_apec_refuses_wrong_provider(fixtures):
    connector = ApecConnector()
    wrong = source("greenhouse")
    with pytest.raises(PublicSourceError, match="ne correspond pas"):
        connector.discover_internships(wrong, selection_brief=default_brief())


def test_apec_bounded_pages_and_rows(fixtures):
    html = build_apec_html(fixtures["apec"])
    fetch = FixtureFetch([html])
    connector = ApecConnector(max_pages=1, max_results=10, fetch=fetch)
    result = connector.discover_internships(source("apec"), selection_brief=default_brief())
    assert len(result.jobs) <= 10


def test_apec_health_check_returns_metrics():
    health = ApecConnector.health_check()
    assert set(health.keys()) == {
        "last_ok", "last_error", "consecutive_failures",
        "raw_offers", "valid_offers", "finance_offers",
        "stage_offers", "conforming_offers", "to_verify_offers"
    }
    assert all(isinstance(v, (bool, int, str, type(None))) for v in health.values())


def test_apec_france_exclusion(fixtures):
    """Verify that France locations are excluded per R1."""
    raw = fixtures["apec"] + [{
        "title": "Stage Analyste Financier - Paris",
        "company": "BNP Paribas",
        "location": "Paris, France",
        "contract_type": "STAGE",
        "url": "https://www.apec.fr/candidat/recherche-emploi.html?offre=stage-paris",
        "description": "<p>Stage analyste financier à Paris.</p>"
    }]
    html = build_apec_html(raw)
    fetch = FixtureFetch([html])
    connector = ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("apec"), selection_brief=default_brief())
    for job in result.jobs:
        assert job["country"].lower() not in {"france", "fr"}
        assert "paris" not in job["city"].lower()


def test_apec_consistent_counts(fixtures):
    html = build_apec_html(fixtures["apec"])
    fetch = FixtureFetch([html])
    connector = ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("apec"), selection_brief=default_brief())
    assert result.raw_count == result.evaluated_count + result.invalid_count
    assert result.evaluated_count == result.confirmed_count + result.uncertain_count + result.excluded_count
    assert result.relevant_count + result.filtered_criteria_count == result.confirmed_count + result.uncertain_count


def test_apec_official_url_validation(fixtures):
    """Foreign posting URLs should not be admitted."""
    raw = [dict(fixtures["apec"][0])]
    raw[0]["url"] = "https://attacker.invalid/fake"
    html = build_apec_html(raw)
    fetch = FixtureFetch([html])
    connector = ApecConnector(clock=lambda: "2026-10-20T01:00:00Z", fetch=fetch)
    result = connector.discover_internships(source("apec"), selection_brief=default_brief())
    for job in result.jobs:
        assert "attacker.invalid" not in job["official_url"]


def test_apec_empty_html_returns_no_jobs():
    fetch = FixtureFetch(["<html><body></body></html>"])
    connector = ApecConnector(fetch=fetch)
    result = connector.discover_internships(source("apec"), selection_brief=default_brief())
    assert len(result.jobs) == 0
    assert result.raw_count == 0


def test_apec_malformed_html_handled_gracefully():
    fetch = FixtureFetch(["<html><body><div class=\"job-result\"><h2>Title</h2></body></html>"])
    connector = ApecConnector(fetch=fetch)
    result = connector.discover_internships(source("apec"), selection_brief=default_brief())
    assert isinstance(result.jobs, tuple)