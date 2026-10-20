"""Synthetic contract tests for public ATS connectors; sockets stay blocked."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from career.connectors import (
    CONNECTOR_SPECS,
    AshbyConnector,
    LeverConnector,
    RecruiteeConnector,
    SmartRecruitersConnector,
)
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
    defaults = {"id": f"synthetic:{provider}:board", "provider": provider,
                "company": "Synthetic Finance", "board_token": "synthetic-board",
                "verified_at": "2026-10-18T00:00:00Z", "provenance_url": "https://careers.example.test/"}
    if provider == "recruitee":
        # The verified public_url host anchors the recruit-tenant listing
        # allowance for the connector under test.
        defaults["public_url"] = "https://careers.example.test/"
    return defaults | extra


def test_public_connectors_are_registered_but_disabled_by_default():
    assert set(CONNECTOR_SPECS) >= {"lever", "ashby", "smartrecruiters", "recruitee"}
    assert all(spec.enabled_by_default is False for spec in CONNECTOR_SPECS.values())
    assert all(spec.doc_verified is True and spec.documentation_url.startswith("https://")
               for spec in CONNECTOR_SPECS.values())
    # Sources internationales : chaque connecteur documente ses conditions connues.
    assert all(spec.known_conditions.strip() for spec in CONNECTOR_SPECS.values())


def test_career_service_enables_public_ats_only_for_explicit_curated_exploration(tmp_path):
    service = CareerService(tmp_path)
    assert set(service._exploration_connectors) == {"greenhouse", "lever", "ashby", "smartrecruiters", "recruitee"}
    assert service._exploration_connectors["lever"].enabled is True
    assert service._exploration_connectors["ashby"].enabled is True
    assert service._exploration_connectors["smartrecruiters"].enabled is True
    assert service._exploration_connectors["recruitee"].enabled is True
    # Direct construction remains opt-in: no source or import activates I/O.
    assert LeverConnector().enabled is False
    assert AshbyConnector().enabled is False
    assert SmartRecruitersConnector().enabled is False
    assert RecruiteeConnector().enabled is False


@pytest.mark.parametrize("connector_type,provider,fixture_key", [
    (LeverConnector, "lever", "lever"),
    (AshbyConnector, "ashby", "ashby"),
    (SmartRecruitersConnector, "smartrecruiters", "smartrecruiters"),
    (RecruiteeConnector, "recruitee", "recruitee"),
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

    # Recruitee: an archived offer is never imported, whatever its content.
    if provider == "recruitee":
        assert all("Product Lead" not in job["title"] for job in jobs)
        assert job["posted_date"] == "2026-10-01"
        assert job["employment_type"] == "Internship"
    assert job["company"] == "Synthetic Finance"
    assert "Finance Intern" in job["title"]
    assert job["source_name"] == provider
    if provider != "recruitee":
        assert job["source_id"].startswith("synthetic")
    else:
        # Vendor identity keywords stay honest: the vendor id is kept verbatim.
        assert job["source_id"] == "2783543"
        assert job["description_original"].splitlines()[0] == "Synthetic internship description for finance."
        assert "Bachelor in Finance" in job["description_original"]
    assert job["official_url"].startswith("https://")
    assert job["source_verified"] is True
    assert job["posted_date"] in {"", "2026-10-01"}
    assert "start_date" not in job or job["start_date"] == ""


def test_recruitee_listing_url_stays_on_verified_or_tenant_host():
    record = source("recruitee")

    # A vendor-side careers URL pointing to an unrelated host is never
    # propagated: the connector falls back to the tenant URL built from the
    # registered board token.
    connector = RecruiteeConnector(transport=FixtureTransport([]), enabled=True)
    foreign = {"offers": [{
        "id": 1, "title": "Finance Intern", "status": "published", "slug": "finance-intern",
        "careers_url": "https://attacker.invalid/o/finance-intern",
        "description": "<p>finance</p>",
    }]}
    [job] = connector.parse(record, foreign)
    assert job["official_url"] == "https://synthetic-board.recruitee.com/o/finance-intern"
    assert "attacker" not in job["official_url"]

    # No admitted listing candidate at all: the offer is refused entirely.
    empty_candidate = {"offers": [{"id": 2, "title": "Finance Intern", "status": "published",
                                   "careers_url": "https://attacker.invalid/x"}]}
    with pytest.raises(ValueError):
        connector.parse(record, empty_candidate)


def test_recruitee_transport_only_reaches_recruitee_subdomains():
    from career.connectors.public_ats import UrllibRecruiteeTransport

    transport = UrllibRecruiteeTransport()
    assert transport._host_allowed("bunq.recruitee.com")
    assert transport._host_allowed("recruitee.com")
    for hostile in ("bunq.recruitee.com.attacker.invalid", "evil-recruitee.com", "api.lever.co", ""):
        assert not transport._host_allowed(hostile)


def test_gzip_response_is_decoded_under_the_transport_size_bound():
    from career.connectors.public_ats import MAX_RESPONSE_BYTES, PublicSourceError, _gunzip_bounded

    payload = json.dumps({"offers": [{"id": 1}]}).encode("utf-8")
    gzipped = gzip.compress(payload)

    # Happy path: a gzip body yields the same JSON payload.
    assert json.loads(_gunzip_bounded(gzipped)) == {"offers": [{"id": 1}]}

    # The expanded body cannot exceed the parsed budget, whatever the wire size.
    with pytest.raises(PublicSourceError, match="dépasse"):
        _gunzip_bounded(gzip.compress(b"x" * (MAX_RESPONSE_BYTES + 2048)))

    # A truncated stream is judged invalid, never silently restored.
    with pytest.raises(PublicSourceError, match="compressé|JSON valide"):
        _gunzip_bounded(gzipped[:-3])



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
    (RecruiteeConnector, "recruitee", "recruitee"),
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


def test_public_ats_timestamp_is_normalized_before_career_import(tmp_path, fixtures):
    connector = SmartRecruitersConnector(enabled=True)
    job = connector.parse(source("smartrecruiters"), fixtures["smartrecruiters"])[0]
    assert job["posted_date"] == "2026-10-01"
    stored = CareerService(tmp_path).import_job(job)
    assert stored["posted_date"] == "2026-10-01"


@pytest.mark.parametrize("connector_type,provider,fixture_key", [
    (LeverConnector, "lever", "lever"),
    (AshbyConnector, "ashby", "ashby"),
    (SmartRecruitersConnector, "smartrecruiters", "smartrecruiters"),
    (RecruiteeConnector, "recruitee", "recruitee"),
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


def test_recruitee_foreign_listing_url_is_substituted_not_propagated():
    # Recruitee never propagates a vendor URL whose host is not verified: the
    # link is replaced by the tenant URL derived from the registered board
    # token, so the attacker host can only disappear from the emitted offer.
    synthetics = json.loads(FIXTURE.read_text(encoding="utf-8"))["recruitee"]
    raw = {**synthetics, "offers": [dict(synthetics["offers"][0], careers_url="https://attacker.invalid/o/fake")]}
    [job] = RecruiteeConnector(transport=FixtureTransport([]), enabled=True).parse(source("recruitee"), raw)
    assert "attacker" not in job["official_url"]
    assert job["official_url"] == "https://synthetic-board.recruitee.com/o/synthetic-finance-intern"
