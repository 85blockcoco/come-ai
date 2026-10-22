"""Synthetic tests for the education-requirement extractor (Mission SK-19).

Every fixture is invented: no real offer, no personal data, no network.
The contract under test is ``extract_education(text, lang="auto")`` and its
``EducationFact`` provenance guarantees.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from career.cv_quality.education_extractor import (
    CONFIDENCE_LEVELS,
    SUPPORTED_LANGUAGES,
    EducationFact,
    detect_language,
    extract_education,
)
from career.offer_qualification import qualify_offer

FIXTURES = Path(__file__).parent / "fixtures" / "education_extractor" / "cases.json"
CASES = json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("the education extractor must stay offline")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def _facts_for(case: dict) -> list[EducationFact]:
    return extract_education(case["text"], lang=case.get("lang", "auto"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_synthetic_cases(case):
    facts = _facts_for(case)
    expected = case["expected"]
    assert len(facts) == len(expected), [fact.to_dict() for fact in facts]
    for fact, wanted in zip(facts, expected):
        assert fact.fact_type == wanted.get("fact_type", "education_level_required")
        assert fact.level_rank == wanted["rank"]
        if "label" in wanted:
            assert fact.level_label == wanted["label"]
        if "field" in wanted:
            assert fact.field == wanted["field"]
        assert fact.confidence == wanted["confidence"]
        assert fact.confidence in CONFIDENCE_LEVELS
        for token in wanted["contradictions"]:
            assert token in fact.contradictions


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_every_quote_is_an_exact_substring_with_matching_offsets(case):
    text = case["text"]
    for fact in _facts_for(case):
        assert 0 <= fact.start_offset < fact.end_offset <= len(text)
        assert text[fact.start_offset:fact.end_offset] == fact.quote
        assert fact.quote.strip()
        assert fact.source_field == "text"


def test_offsets_stay_exact_when_text_is_prefixed():
    prefix = "Annonce synthétique —\n"
    text = prefix + "Bac+5 minimum (Finance, Économie)"
    (fact,) = extract_education(text)
    assert fact.start_offset >= len(prefix)
    assert text[fact.start_offset:fact.end_offset] == fact.quote
    assert "Bac+5" in fact.quote


def test_source_field_is_propagated():
    (fact,) = extract_education("Master's degree in Finance required", source_field="requirements")
    assert fact.source_field == "requirements"


def test_empty_and_whitespace_text_yield_no_fact():
    assert extract_education("") == []
    assert extract_education("   \n\t ") == []


def test_non_string_text_is_rejected():
    with pytest.raises(TypeError):
        extract_education(None)  # type: ignore[arg-type]


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError):
        extract_education("Bac+5", lang="xx")


@pytest.mark.parametrize(("text", "language"), [
    ("Diplôme d'ingénieur requis", "fr"),
    ("Master's degree required", "en"),
    ("Masterabschluss erforderlich", "de"),
    ("Laurea magistrale richiesta", "it"),
    ("Máster requerido", "es"),
    ("Master diploma gevraagd", "nl"),
])
def test_language_detection_for_the_six_supported_languages(text, language):
    assert detect_language(text) == language


def test_supported_language_list_is_stable():
    assert SUPPORTED_LANGUAGES == ("fr", "en", "de", "it", "es", "nl")


def test_explicit_language_prevents_a_foreign_false_positive():
    # "Promotion" is a French cohort word; it is only a doctorate in German.
    assert extract_education("Promotion 2027", lang="fr") == []
    assert extract_education("Promotion erwünscht", lang="de")[0].level_rank == 8


def test_required_and_preferred_levels_are_both_reported_and_mutually_flagged():
    facts = extract_education("Bac+3 minimum, Master apprécié")
    assert [fact.level_rank for fact in facts] == [3, 5]
    assert facts[0].is_preferred is False
    assert facts[1].is_preferred is True
    assert "conflict_with_rank_5" in facts[0].contradictions
    assert "conflict_with_rank_3" in facts[1].contradictions


def test_accepted_alternative_is_not_promoted_to_required():
    facts = extract_education("Master required\nBachelor accepted")
    assert [fact.level_rank for fact in facts] == [5, 3]
    assert "accepted_alternative" in facts[1].contradictions
    assert facts[0].confidence == "explicit"


def test_equivalent_experience_makes_the_level_ambiguous_not_required():
    (fact,) = extract_education("PhD or equivalent experience")
    assert fact.level_rank == 8
    assert fact.confidence == "ambiguous"
    assert fact.is_experience_equivalent is True


def test_vague_equivalence_is_inferred_without_inventing_a_contradiction():
    (fact,) = extract_education("Master ou équivalent")
    assert fact.level_rank == 5
    assert fact.confidence == "inferred"
    assert fact.contradictions == []


def test_alternative_degrees_take_the_lowest_sufficient_branch():
    (fact,) = extract_education("Diplôme d'ingénieur ou Master 2 requis")
    assert fact.level_rank == 5
    assert fact.field == "Engineering"


def test_conjunction_keeps_the_highest_required_level():
    (fact,) = extract_education("Bac+3 et Master requis")
    assert fact.level_rank == 5


def test_at_most_two_facts_are_returned():
    facts = extract_education("Bac+3 requis. Master apprécié. Doctorat un plus.")
    assert len(facts) <= 2
    assert all(fact.level_rank in {3, 5, 8} for fact in facts)


def test_field_only_never_invents_a_level():
    (fact,) = extract_education("Diplôme en Finance requis")
    assert fact.fact_type == "education_field_required"
    assert fact.level_rank == 0
    assert fact.level_label == ""
    assert fact.field == "Finance"
    assert "Finance" in fact.quote


def test_driving_licence_is_not_an_academic_licence():
    assert extract_education("Permis de conduire (licence B) exigé") == []


def test_the_verb_to_master_is_not_a_degree():
    assert extract_education("You will master Python and SQL") == []
    assert extract_education("Master Python and SQL required") == []


def test_bachelor_duration_promotes_rank_only_when_stated():
    assert extract_education("Bachelor's degree")[0].level_rank == 3
    assert extract_education("Bachelor's degree (4 years)")[0].level_rank == 4


def test_long_text_quote_stays_bounded_and_exact():
    text = ("Contexte de l'entreprise. " * 40) + "Bac+5 en Finance requis."
    (fact,) = extract_education(text)
    assert text[fact.start_offset:fact.end_offset] == fact.quote
    assert len(fact.quote) <= 360
    assert "Bac+5" in fact.quote


def test_facts_are_serializable():
    (fact,) = extract_education("Master's degree in Finance required")
    payload = fact.to_dict()
    assert payload["level_rank"] == 5
    assert payload["field"] == "Finance"
    assert payload["contradictions"] == []


# ---------------------------------------------------------------------------
# Integration with qualify_offer
# ---------------------------------------------------------------------------


def _offer(**extra):
    offer = {
        "title": "Data analyst",
        "start_date": "2027-01-01",
        "duration_months": 6,
        "country": "France",
        "city": "Paris",
        "language": "French",
        "official_url": "https://careers.example.test/job",
        "source_name": "greenhouse",
        "source_id": "synthetic-education",
        "source_verified": True,
    }
    offer.update(extra)
    return offer


def test_qualify_offer_exposes_education_evidence():
    result = qualify_offer(_offer(description_original="Master's degree in Data Science required."))
    evidence = result.provenance["education_required"]
    assert evidence.source == "education_extractor"
    assert evidence.value[0]["level_rank"] == 5
    assert evidence.value[0]["field"] == "Data Science"
    assert evidence.value[0]["source_field"] == "description_original"
    assert evidence.quote in "Master's degree in Data Science required."


def test_qualify_offer_reads_the_requirements_field():
    result = qualify_offer(_offer(requirements="Bac+5 minimum (Finance, Économie)"))
    evidence = result.provenance["education_required"]
    assert evidence.value[0]["level_rank"] == 5
    assert evidence.value[0]["field"] == "Finance"
    assert evidence.value[0]["source_field"] == "requirements"


def test_qualify_offer_omits_the_key_when_no_education_is_advertised():
    result = qualify_offer(_offer(description_original="Great team, nice office."))
    assert "education_required" not in result.provenance


def test_education_evidence_never_changes_the_target_status():
    with_education = qualify_offer(_offer(description_original="Master's degree in Finance required."))
    without_education = qualify_offer(_offer(description_original="Great team."))
    assert with_education.target_status == without_education.target_status
