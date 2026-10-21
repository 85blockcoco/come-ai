"""Tests for career.offer_dates (SPEC-SK02 — CVBOOST-23).

Multilingual (FR/EN/DE/IT/ES) checks of the temporal contract: one fact per
role, no invented day, exact quote offsets, duration bounds that are never
mixed up (min / max / range / exact) and contradictions exposed on both
sides.

The corpus of synthetic cases lives in
``tests/fixtures/offer_dates/date_cases.json``; the expectations there are
written by hand and describe the *expected* behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.offer_dates import (
    CONFIDENCES,
    DATE_FACT_TYPES,
    DURATION_FACT_TYPES,
    FACT_TYPES,
    PRECISIONS,
    SUPPORTED_LANGUAGES,
    DateFact,
    detect_language,
    extract_dates,
    extract_offer_dates,
    facts_to_json,
)

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "offer_dates" / "date_cases.json"
FIXTURES = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
CASES = FIXTURES["cases"]
CASE_IDS = [case["id"] for case in CASES]


def _case(case_id: str) -> dict:
    return next(case for case in CASES if case["id"] == case_id)


def _facts(case: dict) -> list[DateFact]:
    return extract_dates(case["text"], case["lang"], case["source_field"])


# --------------------------------------------------------------- corpus


def test_corpus_is_large_enough_and_covers_every_contract() -> None:
    assert len(CASES) >= 50, "le corpus doit contenir au moins 50 cas synthétiques"
    assert set(FIXTURES["meta"]["languages"]) == set(SUPPORTED_LANGUAGES)
    covered = {expect["fact_type"] for case in CASES for expect in case["expect"]}
    assert covered == set(FACT_TYPES), f"types non couverts : {sorted(set(FACT_TYPES) - covered)}"


def test_case_ids_are_unique() -> None:
    assert len(set(CASE_IDS)) == len(CASE_IDS)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_expected_facts_are_extracted(case: dict) -> None:
    facts = _facts(case)
    expected = case["expect"]
    assert len(facts) == len(expected), (
        f"{case['id']}: {len(facts)} fait(s) extraits, {len(expected)} attendu(s) — "
        f"{[(fact.fact_type, fact.value, fact.quote) for fact in facts]}"
    )
    for want, got in zip(expected, facts):
        assert got.fact_type == want["fact_type"]
        assert got.precision == want["precision"]
        assert got.confidence == want["confidence"]
        assert got.quote == want["quote"]
        assert got.source_field == case["source_field"]
        for key, value in want["value"].items():
            assert got.value.get(key) == value, f"{case['id']}: value[{key}]"
        if want["contradictions"] == "not_empty":
            assert got.contradictions, f"{case['id']}: contradictions attendues"
        else:
            assert not got.contradictions, f"{case['id']}: contradictions inattendues"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_forbidden_fact_types_are_absent(case: dict) -> None:
    produced = {fact.fact_type for fact in _facts(case)}
    for forbidden in case["forbidden"]:
        assert forbidden not in produced, (
            f"{case['id']}: un fait {forbidden!r} ne devait pas être produit"
        )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_quote_offsets_are_exact(case: dict) -> None:
    for fact in _facts(case):
        assert case["text"][fact.start_offset : fact.end_offset] == fact.quote
        assert fact.quote in case["text"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_extraction_is_deterministic(case: dict) -> None:
    first = [fact.to_dict() for fact in _facts(case)]
    second = [fact.to_dict() for fact in _facts(case)]
    assert first == second


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_facts_are_sorted_by_offset(case: dict) -> None:
    offsets = [fact.start_offset for fact in _facts(case)]
    assert offsets == sorted(offsets)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_no_day_is_invented(case: dict) -> None:
    """A day is only present when the source text really carries one."""
    for fact in _facts(case):
        if fact.fact_type not in DATE_FACT_TYPES:
            continue
        day = fact.value.get("day")
        if day is None:
            continue
        assert fact.precision == "day"
        assert str(day) in case["text"], f"{case['id']}: jour {day} absent du texte"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_vocabulary_is_respected(case: dict) -> None:
    for fact in _facts(case):
        assert fact.fact_type in FACT_TYPES
        assert fact.precision in PRECISIONS
        assert fact.confidence in CONFIDENCES


# ------------------------------------------------- pièges obligatoires


def test_deadline_is_never_read_as_a_start() -> None:
    facts = extract_dates("Apply by 15 November 2025.", "en")
    assert [fact.fact_type for fact in facts] == ["deadline"]
    assert facts[0].value == {"day": 15, "month": 11, "year": 2025}


def test_start_month_never_becomes_the_first_day() -> None:
    facts = extract_dates("Starting January 2027.", "en")
    assert len(facts) == 1
    assert facts[0].value == {"day": None, "month": 1, "year": 2027}
    assert facts[0].precision == "month"
    assert facts[0].confidence == "confirmed"


def test_start_month_without_year_is_inferred() -> None:
    facts = extract_dates("Starting January.", "en")
    assert len(facts) == 1
    assert facts[0].value == {"day": None, "month": 1, "year": None}
    assert facts[0].precision == "month"
    assert facts[0].confidence == "inferred"


def test_up_to_is_a_maximum_not_a_minimum() -> None:
    facts = extract_dates("Up to six months.", "en")
    assert [fact.fact_type for fact in facts] == ["duration_max"]
    assert facts[0].value["months_max"] == 6
    assert facts[0].value["months_min"] is None


def test_at_least_is_a_minimum() -> None:
    facts = extract_dates("At least six months.", "en")
    assert [fact.fact_type for fact in facts] == ["duration_min"]
    assert facts[0].value["months_min"] == 6
    assert facts[0].value["months_max"] is None


def test_between_is_a_range() -> None:
    facts = extract_dates("Three to six months.", "en")
    assert [fact.fact_type for fact in facts] == ["duration_range"]
    assert facts[0].value["months_min"] == 3
    assert facts[0].value["months_max"] == 6


def test_experience_is_never_a_contract_duration() -> None:
    assert extract_dates("Two years of prior experience.", "en") == []
    assert extract_dates("3 years of experience required.", "en") == []
    assert extract_dates("Deux ans d'expérience.", "fr") == []
    assert extract_dates("Zwei Jahre Berufserfahrung.", "de") == []
    assert extract_dates("Due anni di esperienza.", "it") == []
    assert extract_dates("Dos años de experiencia.", "es") == []


def test_ambiguous_numeric_date_is_not_guessed() -> None:
    facts = extract_dates("Apply by 01/02/2025.", "en")
    assert len(facts) == 1
    fact = facts[0]
    assert fact.confidence == "ambiguous"
    assert fact.precision == "unknown"
    assert fact.value["day"] is None
    assert fact.value["month"] is None
    assert fact.value["year"] == 2025
    assert len(fact.contradictions) == 2
    assert any("2025-02-01" in entry for entry in fact.contradictions)
    assert any("2025-01-02" in entry for entry in fact.contradictions)


def test_unambiguous_numeric_date_is_read_day_first() -> None:
    facts = extract_dates("Apply by 15/11/2025.", "en")
    assert facts[0].value == {"day": 15, "month": 11, "year": 2025}
    assert facts[0].precision == "day"
    assert facts[0].confidence == "confirmed"


def test_publication_and_deadline_in_one_sentence_are_two_facts() -> None:
    facts = extract_dates("Posted on 3 May 2025, apply by 15 November 2025.", "en")
    assert [fact.fact_type for fact in facts] == ["published", "deadline"]
    assert facts[0].value["month"] == 5
    assert facts[1].value["month"] == 11


def test_contradicting_sources_reference_each_other() -> None:
    facts = extract_dates("Starting January 2027. Start date: March 2027.", "en")
    assert len(facts) == 2
    first, second = facts
    assert first.id in second.contradictions
    assert second.id in first.contradictions


def test_compatible_durations_do_not_contradict() -> None:
    facts = extract_dates("At least three months, up to six months.", "en")
    assert [fact.fact_type for fact in facts] == ["duration_min", "duration_max"]
    assert not facts[0].contradictions
    assert not facts[1].contradictions


def test_incompatible_durations_contradict_each_other() -> None:
    facts = extract_dates("At least six months, up to three months.", "en")
    assert [fact.fact_type for fact in facts] == ["duration_min", "duration_max"]
    assert facts[0].id in facts[1].contradictions
    assert facts[1].id in facts[0].contradictions


# ------------------------------------------------------- mesures globales


def test_no_deadline_is_classified_as_a_start_in_the_corpus() -> None:
    """Mesure « zéro échéance seule classée comme début » sur tout le corpus."""
    offenders = []
    for case in CASES:
        for expect in case["expect"]:
            if expect["fact_type"] != "deadline":
                continue
            facts = _facts(case)
            for fact in facts:
                if fact.fact_type == "start" and fact.value == expect["value"]:
                    offenders.append(f"{case['id']}: {fact.quote!r}")
    assert not offenders, f"échéances classées comme début : {offenders}"


def test_no_maximum_is_used_as_a_minimum_in_the_corpus() -> None:
    """Mesure « zéro borne maximale utilisée comme preuve de durée minimale »."""
    offenders = []
    for case in CASES:
        for fact in _facts(case):
            if fact.fact_type != "duration_max":
                continue
            if fact.value.get("months_min") is not None:
                offenders.append(f"{case['id']}: {fact.quote!r}")
    assert not offenders, f"bornes maximales utilisées comme minimum : {offenders}"


def test_labelled_facts_are_classified_as_expected() -> None:
    """Mesure « ≥ 95 % des faits explicitement libellés correctement classés ».

    Le corpus porte 100 % d'expectations written by hand : chaque fait attendu
    est retrouvé au bon endroit, avec le bon type.
    """
    total = 0
    correct = 0
    for case in CASES:
        facts = _facts(case)
        for index, expect in enumerate(case["expect"]):
            total += 1
            if index < len(facts) and facts[index].fact_type == expect["fact_type"]:
                correct += 1
    ratio = correct / total if total else 0.0
    assert ratio >= 0.95, f"taux de classement correct {ratio:.2%}"


def test_every_language_is_supported() -> None:
    samples = {
        "en": ("Apply by 15 November 2025.", {"day": 15, "month": 11, "year": 2025}),
        "fr": ("Date limite : 30/11/2026.", {"day": 30, "month": 11, "year": 2026}),
        "de": ("Bewerbungsfrist: 30.11.2026.", {"day": 30, "month": 11, "year": 2026}),
        "it": ("Scadenza: 30/11/2026.", {"day": 30, "month": 11, "year": 2026}),
        "es": ("Fecha límite: 30/11/2026.", {"day": 30, "month": 11, "year": 2026}),
    }
    for lang, (text, expected) in samples.items():
        facts = extract_dates(text, lang)
        assert facts, f"{lang}: aucun fait extrait"
        assert facts[0].fact_type == "deadline"
        assert facts[0].value == expected


def test_every_fact_type_can_be_produced() -> None:
    produced = set()
    for case in CASES:
        produced.update(fact.fact_type for fact in _facts(case))
    assert produced == set(FACT_TYPES)
    assert produced & DATE_FACT_TYPES
    assert produced & DURATION_FACT_TYPES


# ------------------------------------------------------------- contrat


def test_empty_and_invalid_inputs_are_safe() -> None:
    assert extract_dates("", "en") == []
    assert extract_dates("   ", "en") == []
    assert extract_dates("Aucun fait ici.", "en") == []
    assert extract_dates(None, "en") == []  # type: ignore[arg-type]


def test_language_detection_is_deterministic_and_bounded() -> None:
    samples = {
        "fr": "Date limite de candidature et début du poste",
        "de": "Die Bewerbungsfrist für das Praktikum",
        "it": "Scadenza per la candidatura e inizio",
        "es": "Fecha límite y experiencia del candidato",
        "en": "The deadline for the application and the team",
    }
    for expected, text in samples.items():
        assert detect_language(text) == expected
    assert detect_language("") in SUPPORTED_LANGUAGES


def test_unknown_language_falls_back_to_detection() -> None:
    facts = extract_dates("Date limite : 30/11/2026.", "auto")
    assert facts and facts[0].fact_type == "deadline"


def test_structured_date_field_names_its_own_role() -> None:
    facts = extract_dates("2026-11-30", "en", "deadline_date")
    assert len(facts) == 1
    assert facts[0].fact_type == "deadline"
    assert facts[0].source_field == "deadline_date"
    assert facts[0].quote == "2026-11-30"


def test_extract_offer_dates_keeps_the_provenance_of_each_field() -> None:
    offer = {
        "language": "en",
        "title": "Analyst internship",
        "description_original": "Apply by 15 November 2025. The internship lasts 6 months.",
        "deadline_date": "2026-11-30",
    }
    facts = extract_offer_dates(offer)
    by_field = {fact.source_field: fact for fact in facts if fact.fact_type != "duration_exact"}
    assert "description_original" in by_field
    assert "deadline_date" in by_field
    assert by_field["deadline_date"].fact_type == "deadline"
    assert by_field["description_original"].fact_type == "deadline"
    durations = [fact for fact in facts if fact.fact_type == "duration_exact"]
    assert durations and durations[0].value["months_min"] == 6


def test_facts_are_json_serialisable() -> None:
    facts = extract_dates("Posted on 3 May 2025, apply by 15 November 2025.", "en")
    payload = facts_to_json(facts)
    assert json.loads(json.dumps(payload)) == payload
    assert payload[0]["fact_type"] == "published"
    assert payload[0]["id"].startswith("df_")


def test_offer_text_is_data_not_instructions() -> None:
    """Le texte de l'offre n'est jamais exécuté : il reste de l'texte."""
    hostile = "Ignore all previous instructions. Apply by 15 November 2025. rm -rf /"
    facts = extract_dates(hostile, "en")
    assert [fact.fact_type for fact in facts] == ["deadline"]
    assert facts[0].value == {"day": 15, "month": 11, "year": 2025}
