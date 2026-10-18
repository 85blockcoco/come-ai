"""Synthetic advertised requirements; no candidate facts or network access."""

import socket

import pytest

from career.education_access import assess_education_access


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network is forbidden in education preference tests")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.mark.parametrize("text", [
    "Bachelor's degree in finance required.",
    "Diplôme Bac+3 requis.",
    "Niveau licence en finance requis.",
    "Vous êtes étudiant en Master 1.",
    "Formation Bac + 4 requise.",
    "Student in M1 finance.",
])
def test_explicit_bachelor_or_m1_is_preferred(text):
    result = assess_education_access({"description": text})
    assert result["status"] == "preferred"
    assert result["priority_rank"] == 0
    assert result["evidence"] == [{"field": "description", "passage": text}]


@pytest.mark.parametrize("text", ["Master 2", "M2", "Bac+5"])
def test_m2_is_considered_without_rejection(text):
    result = assess_education_access({"role_level": text})
    assert result["status"] == "consider"
    assert result["priority_rank"] == 1


def test_alternative_accepts_bachelor():
    result = assess_education_access({"requirements": "Bachelor or Master 2 degree required."})
    assert result["status"] == "preferred"
    assert result["labels"] == ["Bachelor / Bac+3", "Master 2 / Bac+5"]


@pytest.mark.parametrize("text", [
    "Bachelor and Master 2 degrees required.",
    "Both Bachelor and Master 2 degrees are required.",
    "Diplômes Bachelor et Master 2 requis.",
    "Degree: Bachelor, Master 2.",
])
def test_conjunction_or_ambiguous_list_does_not_imply_bachelor_access(text):
    assert assess_education_access({"requirements": text})["status"] == "to_verify"


@pytest.mark.parametrize("job", [
    {},
    {"description": "A rewarding financial internship."},
    {"description": "You must master Python and financial models."},
    {"requirements": "You must master Python."},
    {"description": "A third year student is required."},
    {"description": "Driving licence required."},
    {"role_level": "Master"},
    {"requirements": "Master's degree in finance required."},
])
def test_unknown_or_generic_level_remains_unconfirmed(job):
    result = assess_education_access(job)
    assert result["status"] == "to_verify"
    assert "Master 2 / Bac+5" not in result["labels"]


def test_false_friend_has_no_degree_evidence():
    result = assess_education_access({"description": "You must master Python and Excel."})
    assert result["labels"] == []
    assert result["evidence"] == []


def test_unknown_candidate_and_grades_are_not_inferred():
    result = assess_education_access({"requirements": "Bachelor's degree required. Minimum GPA 3.5."})
    assert set(result) == {"status", "labels", "evidence", "reason", "priority_rank"}
    assert result["status"] == "preferred"
    assert all("GPA" not in item["passage"] for item in result["evidence"])


def test_evidence_is_original_substring_and_retains_field():
    text = "Synthetic offer.\nEducation: Bachelor’s degree in Finance required.\nRemote work."
    result = assess_education_access({"eligibility_requirement": text})
    assert result["evidence"] == [{"field": "eligibility_requirement", "passage": "Education: Bachelor’s degree in Finance required."}]
    assert all(item["passage"] in text for item in result["evidence"])


def test_neutral_preference_does_not_filter_degree():
    result = assess_education_access({"requirements": "Doctorat requis."}, preference="any")
    assert result["status"] == "consider"
    assert result["labels"] == ["Doctorat"]
    assert result["priority_rank"] == 1


def test_doctoral_requirement_is_outside_soft_preference_only():
    result = assess_education_access({"requirements": "PhD required."})
    assert result["status"] == "outside_preference"
    assert "eligible" not in result
    assert "exclude" not in result


def test_description_without_requirement_context_is_not_used():
    assert assess_education_access({"description": "Our Bachelor programme is famous."})["labels"] == []


def test_conflicting_passages_are_not_overconfident():
    result = assess_education_access({"requirements": "Bachelor degree required. Master 2 required."})
    assert result["status"] == "to_verify"


def test_html_slash_does_not_change_joint_requirement_to_alternative():
    result = assess_education_access({"requirements": "<p>Bachelor and Master 2 degrees required.</p>"})
    assert result["status"] == "to_verify"


def test_explicitly_excluded_bachelor_is_not_preferred():
    result = assess_education_access({"requirements": "Bachelor is not accepted. Master 2 required."})
    assert result["status"] == "to_verify"


def test_normalized_offer_description_original_preserves_field_evidence():
    text = "Synthetic offer. Bachelor's degree in finance required. You must master Python."
    result = assess_education_access({"description_original": text})
    assert result["status"] == "preferred"
    assert result["evidence"] == [{
        "field": "description_original", "passage": "Bachelor's degree in finance required."
    }]


def test_normalized_offer_master_python_is_not_academic_evidence():
    result = assess_education_access({"description_original": "You must master Python and Excel."})
    assert result["status"] == "to_verify"
    assert result["labels"] == []
    assert result["evidence"] == []


def test_normalized_description_requires_education_or_requirement_context():
    result = assess_education_access({"description_original": "Our Bachelor programme is famous."})
    assert result["evidence"] == []


def test_bachelor_required_and_m2_preferred_is_conservative():
    result = assess_education_access({"requirements": "Bachelor required, Master 2 preferred."})
    assert result["status"] == "to_verify"


def test_and_or_degree_requirement_is_an_explicit_alternative():
    result = assess_education_access({"requirements": "Bachelor and/or Master 2 degree required."})
    assert result["status"] == "preferred"


def test_unknown_preference_is_rejected():
    with pytest.raises(ValueError):
        assess_education_access({}, preference="assume_my_degree")
