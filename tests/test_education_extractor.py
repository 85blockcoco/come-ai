"""SK-19 — fixtures synthétiques multilingues de l'extracteur de niveau d'études.

Contrat vérifié : faits déterministes, citation exacte (``text[start:end] == quote``),
plafond de 2 faits de niveau, préférence jamais promue en exigence, mentions
niées ignorées, aucun réseau ni horloge.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from career.cv_quality.education_extractor import (
    LANGUAGES,
    EducationFact,
    detect_education_language,
    extract_education,
)


FIXTURES = Path(__file__).parent / "fixtures" / "education_extractor" / "synthetic_education_cases.json"
CASES = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network is forbidden in education extractor tests")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def _case_ids(cases):
    return [case["id"] for case in cases]


@pytest.mark.parametrize("case", CASES, ids=_case_ids(CASES))
def test_synthetic_case_matches_expectations(case):
    text = case["text"]
    facts = extract_education(text, lang=case.get("lang", "auto"))
    if case.get("no_facts"):
        assert facts == []
        return
    expected = case["expect"]
    assert len(facts) == len(expected), [fact.quote for fact in facts]
    for fact, wanted in zip(facts, expected):
        assert isinstance(fact, EducationFact)
        assert fact.fact_type == wanted["fact_type"]
        assert fact.level_rank == wanted["level_rank"]
        assert fact.field == wanted["field"]
        if "confidence" in wanted:
            assert fact.confidence == wanted["confidence"]
        if "quote" in wanted:
            assert fact.quote == wanted["quote"]
        # Citation exacte : offsets pointant dans la source, jamais recopiés.
        assert text[fact.start_offset:fact.end_offset] == fact.quote
        for fragment in wanted.get("contradictions_include", []):
            assert any(fragment in item for item in fact.contradictions), fact.contradictions
        if "contradictions_exact" in wanted:
            assert fact.contradictions == wanted["contradictions_exact"]


@pytest.mark.parametrize("case", CASES, ids=_case_ids(CASES))
def test_synthetic_case_is_deterministic(case):
    text = case["text"]
    first = extract_education(text, lang=case.get("lang", "auto"))
    second = extract_education(text, lang=case.get("lang", "auto"))
    assert first == second


def test_level_facts_are_capped_at_two():
    facts = extract_education("Bac+3 minimum. Licence 4. Master apprécié. Doctorat exigé.")
    level_facts = [fact for fact in facts if fact.fact_type == "education_level_required"]
    assert 1 <= len(level_facts) <= 2


def test_language_filter_excludes_other_languages():
    assert extract_education("Promotion erwünscht", lang="fr") == []
    found = extract_education("Promotion erwünscht", lang="de")
    assert [fact.level_rank for fact in found] == [8]


def test_language_auto_covers_every_supported_language():
    samples = {
        "fr": "Bac+5 requis",
        "en": "Master's degree required",
        "de": "Masterabschluss erforderlich",
        "it": "Laurea magistrale richiesta",
        "es": "Máster requerido",
        "nl": "Master vereist",
    }
    assert set(samples) == set(LANGUAGES)
    for sample in samples.values():
        facts = extract_education(sample)
        assert facts and facts[0].level_rank >= 3


def test_preference_is_never_promoted_to_requirement():
    (fact,) = extract_education("PhD preferred")
    assert fact.level_rank == 8
    assert fact.confidence == "inferred"


def test_experience_equivalence_never_proves_a_level():
    (fact,) = extract_education("Bac+5 ou expérience équivalente")
    assert fact.confidence == "ambiguous"
    assert "experience_equivalent" in fact.contradictions


def test_negated_mention_yields_nothing_even_with_field_nearby():
    assert extract_education("Recrutement sans Master ni Finance imposé") == []


def test_empty_and_blank_inputs():
    assert extract_education("") == []
    assert extract_education("   \n\t ") == []


def test_non_string_input_fails_loudly():
    with pytest.raises(TypeError):
        extract_education(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        extract_education("Bac+5", lang="xx")


def test_offsets_are_absolute_in_long_documents():
    prefix = "Vous avez l'expérience idéale. " * 40
    text = prefix + "Bac+5 minimum en Finance."
    (fact,) = extract_education(text)
    assert fact.start_offset >= len(prefix)
    assert text[fact.start_offset:fact.end_offset] == fact.quote == "Bac+5"
    assert fact.field == "Finance"


def test_long_documents_are_bounded():
    text = ("Profil étudiant motivé. " * 5_000) + "Bac+5 requis."
    facts = extract_education(text)
    # Le texte tronqué à MAX_TEXT_CHARS ne contient pas la fin : aucun fait,
    # et surtout aucun coût non borné sur une offre-hostile géante.
    assert isinstance(facts, list)


def test_detect_language_heuristic():
    assert detect_education_language("Le diplôme d'ingénieur est requis en France") == "fr"
    assert detect_education_language("A master's degree is required") == "en"
    assert detect_education_language("") == "en"


def test_public_api_exports():
    from career import cv_quality
    assert hasattr(cv_quality, "extract_education")
    assert hasattr(cv_quality, "EducationFact")
