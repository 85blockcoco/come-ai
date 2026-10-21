"""Contract tests for the deterministic official-source trust module (SK-01).

Every case is synthetic: no network, no real employer, no real URL.  The
fixtures live in ``tests/fixtures/source_trust/`` and drive the same code
path as the product.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.source_registry import CURATED_SOURCES
from career.source_trust import (
    PROVIDERS,
    STATUS_LABELS,
    TrustResult,
    check_offer_trust,
    check_trust,
)


FIXTURES = Path(__file__).parent / "fixtures" / "source_trust"
CHECKED_AT = "2026-10-21T09:00:00+00:00"


def _clock() -> str:
    return CHECKED_AT


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _synthetic_registry() -> list[dict]:
    return list(_load("registry.json")["sources"])


def _cases() -> list[dict]:
    return list(_load("cases.json")["cases"])


CASES = _cases()
CASE_IDS = [case["name"] for case in CASES]


def _run(case: dict) -> TrustResult:
    return check_trust(
        case.get("url", ""),
        employer_hint=case.get("employer_hint"),
        registry=_synthetic_registry(),
        redirects=case.get("redirects"),
        claimed_official=bool(case.get("claimed_official")),
        clock=_clock,
    )


def test_the_fixture_covers_every_mandatory_case() -> None:
    assert len(CASES) >= 12
    covered = {case["mission_case"] for case in CASES}
    mandatory = {
        "Greenhouse officiel",
        "Lever officiel",
        "Ashby officiel",
        "SmartRecruiters officiel",
        "Page carrière employeur",
        "Domaine ressemblant officiel",
        "Sous-domaine trompeur",
        "URL raccourcie",
        "URL manquante",
        "Fournisseur connu, entreprise incohérente",
        "Redirection (fixture) — selon cible finale",
        "Métadonnée « officielle » sans preuve",
    }
    assert mandatory <= covered


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_each_synthetic_case_reaches_its_expected_verdict(case: dict) -> None:
    result = _run(case)
    expected = case["expected"]
    assert result.status == expected["status"]
    assert result.provider == expected["provider"]
    assert result.canonical_host == expected["canonical_host"]
    assert result.employer_match == expected["employer_match"]
    assert result.registry_evidence == expected["registry_evidence"]
    assert result.checked_at == CHECKED_AT


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_decision_carries_readable_reasons(case: dict) -> None:
    result = _run(case)
    assert result.reasons, "une décision sans raison n’est pas explicable"
    for reason in result.reasons:
        assert isinstance(reason, str) and reason.strip()
    for expected in case.get("expected_reason_contains", []):
        assert any(expected in reason for reason in result.reasons), (
            f"raison attendue « {expected} » absente de {result.reasons}"
        )


def test_the_json_contract_exposes_the_seven_mission_fields() -> None:
    payload = check_trust(
        "https://job-boards.greenhouse.io/acmecorp/jobs/12345",
        employer_hint="Acme Corp",
        registry=_synthetic_registry(),
        clock=_clock,
    ).to_dict()
    assert set(payload) == {
        "status",
        "provider",
        "canonical_host",
        "employer_match",
        "registry_evidence",
        "reasons",
        "checked_at",
    }
    assert payload["status"] == "verified"
    assert payload["registry_evidence"] == "registry:greenhouse:acmecorp"


def test_the_same_input_always_produces_the_same_verdict() -> None:
    first = check_trust(
        "https://jobs.ashbyhq.com/initech/8f2c-job",
        employer_hint="Initech",
        registry=_synthetic_registry(),
        clock=_clock,
    )
    second = check_trust(
        "https://jobs.ashbyhq.com/initech/8f2c-job",
        employer_hint="Initech",
        registry=_synthetic_registry(),
        clock=_clock,
    )
    assert first == second
    assert first.to_dict() == second.to_dict()


def test_a_source_boolean_never_acts_as_a_single_proof() -> None:
    without_claim = check_trust(
        "https://greenhouse-jobs.example.net/acmecorp",
        employer_hint="Acme Corp",
        registry=_synthetic_registry(),
        clock=_clock,
    )
    with_claim = check_trust(
        "https://greenhouse-jobs.example.net/acmecorp",
        employer_hint="Acme Corp",
        registry=_synthetic_registry(),
        claimed_official=True,
        clock=_clock,
    )
    assert with_claim.status == without_claim.status == "unverified"
    assert any("pas une preuve" in reason for reason in with_claim.reasons)


def test_a_legitimate_domain_is_not_rejected_only_because_it_is_not_a_known_ats() -> None:
    result = check_trust(
        "https://jobs.contoso.example/careers/12",
        employer_hint="Contoso",
        registry=_synthetic_registry(),
        clock=_clock,
    )
    assert result.status == "verified"
    assert result.provider == "employer"
    assert result.registry_evidence is None


def test_the_curated_registry_proves_a_real_board_without_any_hint() -> None:
    result = check_trust(
        "https://job-boards.greenhouse.io/monzo/jobs/1",
        clock=_clock,
    )
    assert result.status == "verified"
    assert result.provider == "greenhouse"
    assert result.registry_evidence == "registry:greenhouse:monzo"
    assert result.employer_match == "confirmed"


def test_the_curated_registry_covers_the_four_known_providers() -> None:
    providers = {entry["provider"] for entry in CURATED_SOURCES}
    known = {spec.name for spec in PROVIDERS}
    assert {"greenhouse", "lever", "ashby"} <= providers
    assert known == {"greenhouse", "lever", "ashby", "smartrecruiters"}


def test_a_missing_url_is_reported_as_missing_and_never_as_unverified() -> None:
    for url in ("", "   ", None):
        result = check_trust(url or "", employer_hint="Acme Corp", clock=_clock)
        assert result.status == "missing"
        assert result.provider is None
        assert result.canonical_host is None
        assert result.employer_match == "unknown"
        assert result.registry_evidence is None


def test_the_interface_can_differentiate_the_three_usable_states() -> None:
    assert set(STATUS_LABELS) == {"verified", "unverified", "contradictory", "missing"}
    verified = check_trust(
        "https://job-boards.greenhouse.io/acmecorp/jobs/1",
        employer_hint="Acme Corp",
        registry=_synthetic_registry(),
        clock=_clock,
    )
    unverified = check_trust(
        "https://bit.ly/3xYzAbc", employer_hint="Acme Corp", clock=_clock
    )
    contradictory = check_trust(
        "https://greenhouse.acmecorp.example/jobs/42",
        employer_hint="Acme Corp",
        clock=_clock,
    )
    labels = {verified.label, unverified.label, contradictory.label}
    assert len(labels) == 3
    assert verified.is_official is True
    assert unverified.is_official is False
    assert contradictory.is_official is False


def test_a_deceptive_host_is_never_treated_as_a_provider_board() -> None:
    for url in (
        "https://greenhouse.acmecorp.example/jobs/42",
        "https://job-boards.greenhouse.io.acmecorp.example/jobs/42",
        "https://jobs.lever.co.acmecorp.example/x",
        "https://ashby.acmecorp.example/x",
        "https://smartrecruiters.acmecorp.example/x",
    ):
        result = check_trust(url, employer_hint="Acme Corp", clock=_clock)
        assert result.status == "contradictory", url
        assert result.provider != "greenhouse"


def test_a_short_link_stays_unverified_until_the_target_is_known() -> None:
    unresolved = check_trust("https://bit.ly/3xYzAbc", employer_hint="Acme Corp", clock=_clock)
    assert unresolved.status == "unverified"
    resolved = check_trust(
        "https://bit.ly/3xYzAbc",
        employer_hint="Acme Corp",
        registry=_synthetic_registry(),
        redirects={"https://bit.ly/3xYzAbc": "https://job-boards.greenhouse.io/acmecorp/jobs/1"},
        clock=_clock,
    )
    assert resolved.status == "verified"
    assert resolved.canonical_host == "job-boards.greenhouse.io"


def test_a_redirect_loop_cannot_hang_or_grant_confidence() -> None:
    result = check_trust(
        "https://bit.ly/loop",
        redirects={
            "https://bit.ly/loop": "https://bit.ly/loop2",
            "https://bit.ly/loop2": "https://bit.ly/loop",
        },
        clock=_clock,
    )
    assert result.status == "unverified"


def test_an_offer_mapping_is_graded_without_being_modified() -> None:
    offer = {
        "official_url": "https://job-boards.greenhouse.io/acmecorp/jobs/12345",
        "company": "Acme Corp",
        "source_verified": True,
    }
    snapshot = dict(offer)
    result = check_offer_trust(offer, registry=_synthetic_registry(), clock=_clock)
    assert offer == snapshot
    assert result.status == "verified"
    assert result.employer_match == "confirmed"


def test_an_offer_without_link_is_missing() -> None:
    result = check_offer_trust({"company": "Acme Corp"}, registry=_synthetic_registry(), clock=_clock)
    assert result.status == "missing"
