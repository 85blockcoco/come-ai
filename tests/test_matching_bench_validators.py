"""Tests of the bench validators themselves (CVBOOST-08).

A validator that never fails is worthless.  Each test here breaks one thing
on purpose and checks that the matching validator catches it — and that the
same validator stays silent on a clean observation.
"""

from __future__ import annotations

import copy

import pytest

from career.matching_bench import validators
from career.matching_bench.fixtures import load_cases
from career.matching_bench.runner import build_observation

CASES = {case.id: case for case in load_cases()}


def _observation(case_id: str) -> tuple:
    case = CASES[case_id]
    return case, build_observation(case)


def test_evidence_validator_catches_a_rewritten_proof() -> None:
    case, observation = _observation("CVB08-FP-011")
    assert validators.check_evidence_verbatim(case, observation)["ok"]
    observation["prep"]["matched_elements"][0]["evidence"] = "Maîtrise d'Excel et de VBA"
    result = validators.check_evidence_verbatim(case, observation)
    assert not result["ok"]
    assert result["failures"]


def test_evidence_validator_catches_an_invented_action_proof() -> None:
    case, observation = _observation("CVB08-FP-011")
    action = next(a for a in observation["prep"]["cv_action_plan"] if a["status"] == "supported")
    action["profile_evidence"] = "Competence citee par le conseiller"
    result = validators.check_evidence_verbatim(case, observation)
    assert not result["ok"]


def test_requirement_traceability_catches_a_rewritten_requirement() -> None:
    case, observation = _observation("CVB08-FP-011")
    assert validators.check_requirement_traceable(case, observation)["ok"]
    observation["prep"]["requirements"][0]["text"] = "Maîtrise d'Excel et de la finance de marché"
    result = validators.check_requirement_traceable(case, observation)
    assert not result["ok"]


def test_locator_validator_catches_an_unresolvable_locator() -> None:
    case, observation = _observation("CVB08-FP-011")
    assert validators.check_locator_resolves(case, observation)["ok"]
    observation["requirements"]["requirements"][0]["locator"] = "line:999"
    result = validators.check_locator_resolves(case, observation)
    assert not result["ok"]


def test_negation_validator_catches_a_mandatory_negated_statement() -> None:
    case, observation = _observation("CVB08-NG-001")
    assert validators.check_negation_handled(case, observation)["ok"]
    negated = next(
        (item for item in observation["requirements"]["requirements"] if item.get("negated")),
        None,
    )
    assert negated is not None, "le cas doit contenir une exigence niée"
    negated["modality"] = "required"
    result = validators.check_negation_handled(case, observation)
    assert not result["ok"]


def test_contact_validator_catches_a_leaked_email() -> None:
    case, observation = _observation("CVB08-FP-011")
    assert validators.check_no_contact_leak(case, observation)["ok"]
    observation["prep"]["cv_improvements"].append(
        {"suggestion": "Écris à candidat.exemple@exemple-fake.test", "basis": "profile"}
    )
    result = validators.check_no_contact_leak(case, observation)
    assert not result["ok"]
    assert any("e-mail" in failure for failure in result["failures"])


def test_contact_validator_catches_a_leaked_phone_number() -> None:
    case, observation = _observation("CVB08-FP-011")
    observation["prep"]["letter_points"].append({"point": "Rappelle le 06 11 22 33 44"})
    result = validators.check_no_contact_leak(case, observation)
    assert not result["ok"]
    assert any("téléphone" in failure for failure in result["failures"])


def test_absent_not_added_catches_a_supported_action_without_proof() -> None:
    case, observation = _observation("CVB08-CO-001")
    assert validators.check_absent_not_added(case, observation)["ok"]
    action = next(a for a in observation["prep"]["cv_action_plan"] if a["status"] == "supported")
    action["profile_evidence"] = ""
    result = validators.check_absent_not_added(case, observation)
    assert not result["ok"]


def test_absent_not_added_catches_an_inflated_coverage() -> None:
    case, observation = _observation("CVB08-CO-001")
    observation["prep"]["cv_coverage"]["coverage_percent"] = 100
    result = validators.check_absent_not_added(case, observation)
    assert not result["ok"]


def test_unknown_stays_unknown_catches_a_resolved_duration() -> None:
    case, observation = _observation("CVB08-CT-006")
    assert validators.check_unknown_stays_unknown(case, observation)["ok"]
    observation["eligibility"]["duration_min_months"] = 6
    result = validators.check_unknown_stays_unknown(case, observation)
    assert not result["ok"]


def test_unknown_stays_unknown_catches_a_resolved_education_level() -> None:
    case, observation = _observation("CVB08-DIP-005")
    assert validators.check_unknown_stays_unknown(case, observation)["ok"]
    observation["education"]["status"] = "preferred"
    result = validators.check_unknown_stays_unknown(case, observation)
    assert not result["ok"]


def test_axis_separation_catches_an_eligibility_claim() -> None:
    case, observation = _observation("CVB08-FP-011")
    assert validators.check_axis_separation(case, observation)["ok"]
    observation["prep"]["cv_improvements"].append(
        {"suggestion": "Tu es admissible pour cette offre.", "basis": "profile"}
    )
    result = validators.check_axis_separation(case, observation)
    assert not result["ok"]


def test_axis_separation_catches_a_score_in_the_plan() -> None:
    case, observation = _observation("CVB08-FP-011")
    observation["prep"]["match_score"] = 87
    result = validators.check_axis_separation(case, observation)
    assert not result["ok"]


def test_determinism_check_detects_a_divergent_replay() -> None:
    from career.matching_bench.runner import observation_hash

    case, observation = _observation("CVB08-FP-011")
    assert validators.check_determinism(case, observation, observation_hash(observation))["ok"]
    result = validators.check_determinism(case, observation, "0" * 64)
    assert not result["ok"]


def test_detection_check_catches_a_missing_requirement() -> None:
    case, observation = _observation("CVB08-CO-001")
    assert validators.check_requirement_detection(case, observation)["ok"]
    observation["prep"]["requirements"] = []
    result = validators.check_requirement_detection(case, observation)
    assert not result["ok"]
    assert any("non détectée" in failure for failure in result["failures"])


def test_detection_check_catches_a_requirement_that_should_not_exist() -> None:
    case, observation = _observation("CVB08-AV-002")
    observation["prep"]["requirements"].append(
        {"text": "- Ticket restaurant Swile à 9,50 EUR par jour.", "source": "description_original"}
    )
    result = validators.check_requirement_detection(case, observation)
    assert not result["ok"]


def test_support_decision_check_confirms_the_fixed_lexical_false_positive() -> None:
    case, observation = _observation("CVB08-FP-005")
    result = validators.check_support_decision(case, observation)
    assert result["ok"]
    detail = result["details"][0]
    assert detail["expected_supported"] is False
    assert detail["actual_supported"] is False
    assert detail["verdict"] == "conforme"


def test_eligibility_check_catches_a_wrong_verdict() -> None:
    case, observation = _observation("CVB08-CT-005")
    assert validators.check_eligibility_verdict(case, observation)["ok"]
    observation["eligibility"]["target_status"] = "non_conforming"
    result = validators.check_eligibility_verdict(case, observation)
    assert not result["ok"]


def test_education_check_catches_a_wrong_level() -> None:
    case, observation = _observation("CVB08-DIP-001")
    assert validators.check_education_verdict(case, observation)["ok"]
    observation["education"]["status"] = "consider"
    result = validators.check_education_verdict(case, observation)
    assert not result["ok"]


def test_relevance_check_catches_a_wrong_component() -> None:
    case, observation = _observation("CVB08-FP-001")
    assert validators.check_relevance_components(case, observation)["ok"]
    observation["match"]["components"][0]["status"] = "no_match"
    result = validators.check_relevance_components(case, observation)
    assert not result["ok"]


def test_quoted_material_check_catches_an_invented_quote() -> None:
    case, observation = _observation("CVB08-FP-011")
    assert validators.check_quoted_material_verbatim(case, observation)["ok"]
    observation["prep"]["cv_improvements"].append(
        {"suggestion": "Mets en avant « Certification CFO »", "basis": "profile"}
    )
    result = validators.check_quoted_material_verbatim(case, observation)
    assert not result["ok"]


def test_quoted_material_check_accepts_interface_labels() -> None:
    case, observation = _observation("CVB08-FP-011")
    observation["prep"]["cv_improvements"].append(
        {"suggestion": "Mets en avant « Compétences »", "basis": "profile"}
    )
    assert validators.check_quoted_material_verbatim(case, observation)["ok"]


def test_validators_do_not_mutate_the_observation() -> None:
    case, observation = _observation("CVB08-FP-001")
    snapshot = copy.deepcopy(observation)
    for validator in validators.HARD_VALIDATORS:
        validator(case, observation)
    for validator in validators.SEMANTIC_VALIDATORS:
        validator(case, observation)
    assert observation == snapshot


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_every_case_runs_through_the_validators(case_id: str) -> None:
    case, observation = _observation(case_id)
    for validator in validators.HARD_VALIDATORS:
        result = validator(case, observation)
        assert "ok" in result and "detail" in result
    for validator in validators.SEMANTIC_VALIDATORS:
        result = validator(case, observation)
        assert "ok" in result and "detail" in result
