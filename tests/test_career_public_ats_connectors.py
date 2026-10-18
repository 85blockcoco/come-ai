"""Synthetic contract tests for public ATS connectors; sockets stay blocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.connectors import CONNECTOR_SPECS, AshbyConnector, LeverConnector, SmartRecruitersConnector
from career.discovery import PublicSourceError
from career.education_access import assess_education_access
from career.stage_search import default_brief
from career.service import CareerService


FIXTURE = Path(__file__).parent / "fixtures" / "career_connectors_synthetic.json"


class FixtureTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get_json(self, endpoint, timeout_seconds):
        self.calls.append((endpoint, timeout_seconds))
        if not self.responses:
            raise AssertionError("fixture transport exhausted")
        return self.responses.pop(0)


@pytest.fixture
def fixtures():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def source(provider, **extra):
    return {"id": f"synthetic:{provider}:board", "provider": provider,
            "company": "Synthetic Finance", "board_token": "synthetic-board",
            "verified_at": "2026-10-18T00:00:00Z", "provenance_url": "https://careers.example.test/"} | extra


def test_public_connectors_are_registered_but_disabled_by_default():
    assert set(CONNECTOR_SPECS) >= {"lever", "ashby", "smartrecruiters"}
    assert all(spec.enabled_by_default is False for spec in CONNECTOR_SPECS.values())
    assert all(spec.doc_verified is True and spec.documentation_url.startswith("https://")
               for spec in CONNECTOR_SPECS.values())


def test_career_service_enables_public_ats_only_for_explicit_curated_exploration(tmp_path):
    service = CareerService(tmp_path)
    assert set(service._exploration_connectors) == {"greenhouse", "lever", "ashby", "smartrecruiters"}
    assert service._exploration_connectors["lever"].enabled is True
    assert service._exploration_connectors["ashby"].enabled is True
    assert service._exploration_connectors["smartrecruiters"].enabled is True
    # Direct construction remains opt-in: no source or import activates I/O.
    assert LeverConnector().enabled is False
    assert AshbyConnector().enabled is False
    assert SmartRecruitersConnector().enabled is False


@pytest.mark.parametrize("connector_type,provider,fixture_key", [
    (LeverConnector, "lever", "lever"),
    (AshbyConnector, "ashby", "ashby"),
    (SmartRecruitersConnector, "smartrecruiters", "smartrecruiters"),
])
def test_connector_maps_synthetic_public_postings_to_common_contract(
    connector_type, provider, fixture_key, fixtures,
):
    raw = fixtures[fixture_key]
    transport = FixtureTransport([raw])
    connector = connector_type(transport=transport, enabled=True, clock=lambda: "2026-10-18T01:00:00Z")

    jobs = connector.parse(source(provider), raw)

    assert len(jobs) == 1
    job = jobs[0]
    assert job["company"] == "Synthetic Finance"
    assert "Finance Intern" in job["title"]
    assert job["source_name"] == provider
    assert job["source_id"].startswith("synthetic-")
    assert job["official_url"].startswith("https://")
    assert job["source_verified"] is True
    assert job["posted_date"] in {"", "2026-10-01T09:00:00Z"}
    assert "start_date" not in job or job["start_date"] == ""


def test_public_ats_html_is_normalized_before_education_evidence(fixtures):
    raw = [dict(fixtures["lever"][0])]
    raw[0]["descriptionPlain"] = (
        "<ul><li>Bachelor’s degree in Finance required.</li></ul>"
        "<script>secret_marker()</script>"
    )
    job = LeverConnector(enabled=True).parse(source("lever"), raw)[0]
    assert job["description_original"] == "Bachelor’s degree in Finance required."
    assert "<" not in job["description_original"]
    assert "secret_marker" not in job["description_original"]
    education = assess_education_access(job)
    assert education["status"] == "preferred"
    assert education["evidence"] == [{
        "field": "description_original", "passage": "Bachelor’s degree in Finance required."
    }]


@pytest.mark.parametrize("connector_type,provider,fixture_key", [
    (LeverConnector, "lever", "lever"),
    (AshbyConnector, "ashby", "ashby"),
    (SmartRecruitersConnector, "smartrecruiters", "smartrecruiters"),
])
def test_connectors_refuse_until_explicitly_enabled(connector_type, provider, fixture_key, fixtures):
    transport = FixtureTransport([fixtures[fixture_key]])
    connector = connector_type(transport=transport)
    with pytest.raises(Exception, match="désactivé|disabled"):
        connector.discover_internships(source(provider), selection_brief={"domains": ["Finance"]})
    assert transport.calls == []


def test_connectors_bound_page_count_and_validate_employer_identifier(fixtures):
    transport = FixtureTransport([fixtures["lever"]])
    connector = LeverConnector(transport=transport, enabled=True, max_pages=1)
    bad = source("lever", board_token="https://attacker.invalid/path")
    with pytest.raises(Exception):
        connector.discover_internships(bad, selection_brief={"domains": ["Finance"]})
    assert transport.calls == []


def test_enabled_connector_requires_a_verified_source_record_before_network():
    transport = FixtureTransport([])
    connector = LeverConnector(transport=transport, enabled=True)
    unverified = {"provider": "lever", "company": "Synthetic Finance", "board_token": "synthetic-board"}
    with pytest.raises(PublicSourceError, match="vérifiée"):
        connector.discover_internships(unverified, selection_brief=default_brief())
    assert transport.calls == []


@pytest.mark.parametrize("connector_type,provider,fixture_key", [
    (LeverConnector, "lever", "lever"),
    (AshbyConnector, "ashby", "ashby"),
    (SmartRecruitersConnector, "smartrecruiters", "smartrecruiters"),
])
def test_enabled_fixture_discovery_returns_consistent_counts_without_sockets(
    connector_type, provider, fixture_key, fixtures,
):
    transport = FixtureTransport([fixtures[fixture_key]])
    connector = connector_type(transport=transport, enabled=True, clock=lambda: "2026-10-18T01:00:00Z")

    result = connector.discover_internships(source(provider), selection_brief=default_brief())

    assert result.raw_count == result.evaluated_count + result.invalid_count
    assert result.evaluated_count == result.confirmed_count + result.uncertain_count + result.excluded_count
    assert result.confirmed_count + result.uncertain_count == result.relevant_count + result.filtered_criteria_count
    assert result.verified_at == "2026-10-18T01:00:00Z"
    assert len(result.jobs) <= result.relevant_count
    assert len(transport.calls) == 1


def test_smartrecruiters_always_requests_public_destination(fixtures):
    transport = FixtureTransport([fixtures["smartrecruiters"]])
    connector = SmartRecruitersConnector(transport=transport, enabled=True)
    endpoint = connector.build_endpoint(source("smartrecruiters"))
    assert "destination=PUBLIC" in endpoint
    assert transport.calls == []


@pytest.mark.parametrize("connector_type,provider,fixture_key,malicious_url", [
    (LeverConnector, "lever", "lever", "https://attacker.invalid/fake"),
    (AshbyConnector, "ashby", "ashby", "https://jobs.attacker.invalid/fake"),
    (SmartRecruitersConnector, "smartrecruiters", "smartrecruiters", "https://attacker.invalid/fake"),
])
def test_foreign_posting_url_is_not_admitted(connector_type, provider, fixture_key, malicious_url, fixtures):
    raw = fixtures[fixture_key]
    if isinstance(raw, list):
        raw = [dict(raw[0], hostedUrl=malicious_url)]
    elif provider == "ashby":
        raw = {**raw, "jobs": [dict(raw["jobs"][0], jobUrl=malicious_url)]}
    else:
        raw = {**raw, "content": [dict(raw["content"][0], applyUrl=malicious_url, ref=malicious_url)]}
    with pytest.raises(ValueError):
        connector_type(transport=FixtureTransport([]), enabled=True).parse(source(provider), raw)
