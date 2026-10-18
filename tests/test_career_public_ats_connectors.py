"""Synthetic contract tests for public ATS connectors; sockets stay blocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.connectors import CONNECTOR_SPECS, AshbyConnector, LeverConnector, SmartRecruitersConnector


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


def test_smartrecruiters_always_requests_public_destination(fixtures):
    transport = FixtureTransport([fixtures["smartrecruiters"]])
    connector = SmartRecruitersConnector(transport=transport, enabled=True)
    endpoint = connector.build_endpoint(source("smartrecruiters"))
    assert "destination=PUBLIC" in endpoint
    assert transport.calls == []
