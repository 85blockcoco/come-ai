"""Synthetic trust contracts for career/source_trust.py.

No live URL is contacted and no real offer is copied: every employer, board
token and path comes from tests/fixtures/source_trust/.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

import pytest

from career.source_trust import (
    EMPLOYER_MATCHES,
    PROVIDERS,
    TRUST_STATUSES,
    TrustResult,
    check_trust,
    status_label,
)


FIXTURES = Path(__file__).parent / "fixtures" / "source_trust"
CASES = json.loads((FIXTURES / "trust_cases.json").read_text(encoding="utf-8"))["cases"]
REDIRECTS = json.loads((FIXTURES / "redirects.json").read_text(encoding="utf-8"))["redirects"]
FIXED_CLOCK = "2026-10-21T12:00:00+00:00"
CONTRACT_KEYS = {
    "status", "provider", "canonical_host", "employer_match",
    "registry_evidence", "reasons", "checked_at",
}


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network is forbidden in synthetic trust tests")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, blocked)


def _run(case: dict) -> TrustResult:
    final_url = REDIRECTS.get(case["redirect_key"]) if case.get("redirect_key") else None
    return check_trust(
        case["url"],
        employer_hint=case.get("employer_hint"),
        declared_provider=case.get("declared_provider"),
        final_url=final_url,
        clock=lambda: FIXED_CLOCK,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case['id']}-{case['case']}")
def test_synthetic_case_follows_the_expected_trust_decision(case):
    result = _run(case)
    assert result.status == case["expected_status"]
    assert result.provider == case["expected_provider"]
    assert result.canonical_host == case["expected_canonical_host"]
    assert result.employer_match == case["expected_employer_match"]
    assert result.registry_evidence == case["expected_registry_evidence"]
    assert result.reasons, "every decision carries at least one explanation"


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case['id']}-{case['case']}")
def test_synthetic_case_exposes_the_json_contract(case):
    payload = _run(case).to_dict()
    assert set(payload) == CONTRACT_KEYS
    assert payload["status"] in TRUST_STATUSES
    assert payload["employer_match"] in EMPLOYER_MATCHES
    assert payload["provider"] in PROVIDERS or payload["provider"] is None
    assert payload["checked_at"] == FIXED_CLOCK
    assert datetime.fromisoformat(payload["checked_at"])
    assert payload["reasons"], "an unexplained decision is a bug"
    if payload["status"] == "verified":
        assert payload["registry_evidence"], "a verified source always cites its supporting record"
    else:
        assert payload["registry_evidence"] is None, "an unproven source cites no record"


def test_every_mandatory_case_of_the_mission_is_covered():
    mandatory = {
        "greenhouse_official", "lever_official", "ashby_official", "smartrecruiters_official",
        "employer_careers_page", "lookalike_domain", "deceptive_subdomain", "shortened_url",
        "missing_url", "known_provider_wrong_employer", "redirect_resolved",
        "metadata_official_without_proof",
    }
    covered = {case["case"] for case in CASES}
    assert mandatory <= covered
    assert len(CASES) >= 12


def test_decision_is_deterministic_and_replayable():
    first = check_trust("https://job-boards.greenhouse.io/acme-corp/jobs/4217",
                        employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    second = check_trust("https://job-boards.greenhouse.io/acme-corp/jobs/4217",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert first.to_dict() == second.to_dict()
    assert first.checked_at == FIXED_CLOCK


def test_an_unregistered_employer_lookalike_domain_is_never_proven_by_its_name():
    result = check_trust("https://www.acme-corp.com/careers/stage-finance",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "unverified"
    assert result.provider == "employer"
    assert result.canonical_host == "acme-corp.com"
    assert result.registry_evidence is None
    assert any("ne prouve pas" in reason for reason in result.reasons)


def test_a_lookalike_domain_is_never_verified():
    result = check_trust("https://greenhouse-jobs.acme.test/acme-corp/jobs/1",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "unverified"
    assert result.provider == "unknown"
    assert result.registry_evidence is None
    assert any("Greenhouse" in reason for reason in result.reasons)


def test_a_known_ats_host_without_any_employer_proof_is_never_verified():
    result = check_trust("https://boards.greenhouse.io/acme-corp/jobs/1", clock=lambda: FIXED_CLOCK)
    assert result.status == "unverified"
    assert result.employer_match == "unknown"
    assert result.registry_evidence is None


def test_a_source_flag_alone_never_proves_an_official_source():
    result = check_trust("https://careers.acme-corp.example/jobs/1",
                         declared_provider="greenhouse", clock=lambda: FIXED_CLOCK)
    assert result.status == "unverified"
    assert result.registry_evidence is None
    assert any("ne constitue jamais une preuve" in reason for reason in result.reasons)


def test_a_declared_provider_conflicting_with_the_link_is_contradictory():
    result = check_trust("https://jobs.lever.co/acme-corp/2f3a-4b1c",
                         employer_hint="Acme Corp", declared_provider="greenhouse",
                         clock=lambda: FIXED_CLOCK)
    assert result.status == "contradictory"
    assert result.provider == "lever"
    assert any("incohérence" in reason.lower() for reason in result.reasons)


def test_a_shortened_link_without_its_target_stays_unverified():
    result = check_trust("https://bit.ly/3xY2zAcme", employer_hint="Acme Corp",
                         clock=lambda: FIXED_CLOCK)
    assert result.status == "unverified"
    assert result.provider == "unknown"
    assert result.registry_evidence is None


def test_a_resolved_redirect_follows_its_final_target():
    result = check_trust("https://bit.ly/3xY2zAcme", employer_hint="Acme Corp",
                         final_url=REDIRECTS["https://bit.ly/3xY2zAcme"], clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.provider == "greenhouse"
    assert result.canonical_host == "job-boards.greenhouse.io"
    assert any("résolue" in reason for reason in result.reasons)


def test_the_curated_registry_of_the_repository_is_used_as_evidence():
    # The repository already ships curated public records (public companies,
    # no personal data): a board listed there is proven without any hint.
    result = check_trust("https://boards.greenhouse.io/monzo", clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.provider == "greenhouse"
    assert result.employer_match == "confirmed"
    assert result.registry_evidence == "registry:greenhouse:monzo"


def test_a_curated_record_rejects_another_employer():
    result = check_trust("https://boards.greenhouse.io/monzo", employer_hint="Other Corp",
                         clock=lambda: FIXED_CLOCK)
    assert result.status == "contradictory"
    assert result.employer_match == "mismatch"
    assert result.registry_evidence is None


def test_an_employer_domain_proven_by_the_registry_is_verified():
    result = check_trust("https://careers.point72.com/jobs/12345", clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.provider == "employer"
    assert result.registry_evidence == "registry:greenhouse:point72"


def test_no_url_is_never_a_missing_source_with_an_explanation():
    result = check_trust("", employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "missing"
    assert result.provider is None
    assert result.canonical_host is None
    assert result.employer_match == "unknown"
    assert result.reasons


def test_unusable_urls_are_never_used_as_a_source():
    for url in ("javascript:alert(1)", "https://user:pass@careers.acme-corp.com/jobs/1", "not-a-url"):
        result = check_trust(url, employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
        assert result.status == "missing"
        assert result.registry_evidence is None


def test_an_invalid_port_is_never_used_as_a_source():
    result = check_trust("https://careers.acme-corp.com:99999/jobs/1", employer_hint="Acme Corp",
                         clock=lambda: FIXED_CLOCK)
    assert result.status == "missing"
    assert result.registry_evidence is None


def test_a_non_standard_port_is_never_verified():
    result = check_trust("https://careers.acme-corp.com:8443/jobs/1", employer_hint="Acme Corp",
                         clock=lambda: FIXED_CLOCK)
    assert result.status == "unverified"
    assert result.registry_evidence is None
    assert any("Port non standard" in reason for reason in result.reasons)


def test_a_tracking_query_or_a_trailing_slash_does_not_change_the_decision():
    result = check_trust("https://job-boards.greenhouse.io/acme-corp/jobs/4217/?gh_src=abc&utm_source=news",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.canonical_host == "job-boards.greenhouse.io"
    assert result.registry_evidence == "registry:greenhouse:acme-corp"


def test_an_uppercase_host_is_read_the_same_way():
    result = check_trust("https://JOB-BOARDS.GREENHOUSE.IO/acme-corp/jobs/4217",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.canonical_host == "job-boards.greenhouse.io"


def test_a_lookalike_inside_a_vendor_domain_is_never_an_impostor():
    # "custom.greenhouse.io" belongs to the vendor: it is not an imitation.
    result = check_trust("https://custom.greenhouse.io/acme-corp/jobs/1", employer_hint="Acme Corp",
                         clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.provider == "greenhouse"
    assert any("n'est pas un domaine officiel documenté" in reason for reason in result.reasons)


def test_an_impostor_of_a_vendor_domain_is_contradictory():
    result = check_trust("https://greenhouse.io.acme.test/acme-corp/jobs/1", employer_hint="Acme Corp",
                         clock=lambda: FIXED_CLOCK)
    assert result.status == "contradictory"
    assert result.provider == "greenhouse"
    assert result.employer_match == "unknown"


def test_the_documented_smartrecruiters_layout_is_read():
    result = check_trust("https://www.smartrecruiters.com/jobs/AcmeCorp/743999",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.provider == "smartrecruiters"
    assert result.canonical_host == "smartrecruiters.com"
    assert result.registry_evidence == "registry:smartrecruiters:AcmeCorp"


def test_the_documented_greenhouse_api_layout_is_read():
    result = check_trust("https://boards-api.greenhouse.io/v1/boards/acme-corp/jobs",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.provider == "greenhouse"
    assert result.registry_evidence == "registry:greenhouse:acme-corp"


def test_the_documented_ashby_api_layout_is_read():
    result = check_trust("https://api.ashbyhq.com/posting-api/job-board/acme-corp",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.provider == "ashby"
    assert result.registry_evidence == "registry:ashby:acme-corp"


def test_the_documented_smartrecruiters_api_layout_is_read():
    result = check_trust("https://api.smartrecruiters.com/v1/companies/AcmeCorp/postings",
                         employer_hint="Acme Corp", clock=lambda: FIXED_CLOCK)
    assert result.status == "verified"
    assert result.provider == "smartrecruiters"
    assert result.registry_evidence == "registry:smartrecruiters:AcmeCorp"


def test_the_interface_can_differentiate_the_three_states():
    assert status_label("verified") != status_label("unverified")
    assert status_label("unverified") != status_label("contradictory")
    assert status_label("missing")
    assert status_label("unknown-status") == ""


def test_check_trust_accepts_the_documented_signature():
    result = check_trust("https://job-boards.greenhouse.io/acme-corp/jobs/4217", employer_hint="Acme Corp")
    assert isinstance(result, TrustResult)
    assert result.status == "verified"
