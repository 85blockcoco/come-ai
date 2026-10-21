"""Corpus-wide invariants for career.offer_dates (SPEC SK-02).

The per-case expectations live in ``tests/fixtures/offer_dates/*.json``.  This
module states the rules that must hold for **every** case at once, whatever
the language and whatever the wording:

1. a deadline is never typed as a start;
2. a maximum bound is never used as a minimum (and the other way round);
3. no day is ever invented: a day that is not written down stays ``None``;
4. a duration never carries a calendar day or month;
5. the extraction never mutates the text it reads;
6. the facts come back sorted by offset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from career.offer_dates import extract_dates

FIXTURES = Path(__file__).parent / "fixtures" / "offer_dates"


def _load_cases() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(FIXTURES.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for case in payload["cases"]:
            item = dict(case)
            item["lang"] = payload["lang"]
            cases.append(item)
    return cases


CASES = _load_cases()
CASE_IDS = [case["id"] for case in CASES]

DEADLINE_MARKERS = (
    "apply by",
    "apply before",
    "deadline",
    "postuler avant",
    "date limite",
    "bewerbungsfrist",
    "bewerbungen bis",
    "scadenza",
    "candidare entro",
    "fecha limite",
    "plazo de solicitud",
    "solicitar antes",
)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_deadline_is_never_typed_as_a_start(case: dict) -> None:
    facts = extract_dates(case["text"], case["lang"], case.get("source_field", "description_original"))
    for fact in facts:
        if fact.fact_type != "start":
            continue
        quote = fact.quote.lower()
        for marker in DEADLINE_MARKERS:
            assert marker not in quote, (
                f"{case['id']}: l'echeance {marker!r} a ete classee comme debut."
            )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_bound_is_never_used_as_its_opposite(case: dict) -> None:
    facts = extract_dates(case["text"], case["lang"], case.get("source_field", "description_original"))
    for fact in facts:
        if fact.fact_type == "duration_max":
            assert fact.value["months_max"] is not None
            assert fact.value["months_min"] is None
        if fact.fact_type == "duration_min":
            assert fact.value["months_min"] is not None
            assert fact.value["months_max"] is None
        if fact.fact_type == "duration_exact":
            assert fact.value["months_min"] == fact.value["months_max"]
        if fact.fact_type == "duration_range":
            assert fact.value["months_min"] <= fact.value["months_max"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_no_day_is_invented(case: dict) -> None:
    text = case["text"]
    facts = extract_dates(text, case["lang"], case.get("source_field", "description_original"))
    for fact in facts:
        if fact.fact_type.startswith("duration_"):
            continue
        day = fact.value.get("day")
        if day is None:
            continue
        numbers = {int(number) for number in re.findall(r"\d+", fact.quote)}
        assert day in numbers, (
            f"{case['id']}: le jour {day} n'apparait pas dans la citation {fact.quote!r}."
        )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_duration_never_carries_a_calendar_component(case: dict) -> None:
    facts = extract_dates(case["text"], case["lang"], case.get("source_field", "description_original"))
    for fact in facts:
        if not fact.fact_type.startswith("duration_"):
            continue
        assert "day" not in fact.value
        assert "month" not in fact.value or fact.fact_type == "duration_range"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_extraction_does_not_mutate_its_input(case: dict) -> None:
    text = case["text"]
    snapshot = text
    extract_dates(text, case["lang"], case.get("source_field", "description_original"))
    assert text == snapshot


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_facts_are_sorted_by_offset(case: dict) -> None:
    facts = extract_dates(case["text"], case["lang"], case.get("source_field", "description_original"))
    offsets = [fact.start_offset for fact in facts]
    assert offsets == sorted(offsets)


def test_the_corpus_covers_the_five_languages() -> None:
    assert len(CASES) >= 150, "Le corpus doit couvrir au moins 150 cas."
    assert {case["lang"] for case in CASES} == {"fr", "en", "de", "it", "es"}
    assert len(CASE_IDS) == len(set(CASE_IDS)), "Les identifiants de cas doivent etre uniques."
