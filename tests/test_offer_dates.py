"""Synthetic contracts for the multilingual temporal analyzer (SPEC SK-02).

Everything here is offline: no real offer, no real company, no network, no
clock.  The same text always produces the same facts, in the same order.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from career.offer_dates import (
    DateFact,
    detect_language,
    extract_dates,
    extract_offer_dates,
    facts_by_type,
)

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


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network is forbidden in the temporal analyzer tests")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, blocked)


def _signature(fact: DateFact) -> tuple:
    return (
        fact.fact_type,
        tuple(sorted(fact.value.items())),
        fact.precision,
        fact.confidence,
        fact.quote,
    )


def test_fixture_corpus_is_large_enough():
    assert len(CASES) >= 50
    languages = {case["lang"] for case in CASES}
    assert languages == {"fr", "en", "de", "it", "es"}
    assert len(CASE_IDS) == len(set(CASE_IDS))


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_synthetic_case_matches_its_expected_contract(case):
    facts = extract_dates(
        case["text"],
        case["lang"],
        case.get("source_field", "description_original"),
    )
    expected = sorted(_signature_from_dict(item) for item in case["expected"])
    assert sorted(_signature(fact) for fact in facts) == expected
    for fact_type in case.get("absent", []):
        assert fact_type not in {fact.fact_type for fact in facts}, (
            f"{case['id']}: {fact_type} must not be extracted"
        )


def _signature_from_dict(item: dict) -> tuple:
    return (
        item["fact_type"],
        tuple(sorted(item["value"].items())),
        item["precision"],
        item["confidence"],
        item["quote"],
    )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_quotes_are_the_exact_source_span(case):
    text = case["text"]
    facts = extract_dates(text, case["lang"], case.get("source_field", "description_original"))
    for fact in facts:
        assert text[fact.start_offset:fact.end_offset] == fact.quote
        assert fact.start_offset >= 0
        assert fact.end_offset <= len(text)
        assert fact.source_field == case.get("source_field", "description_original")


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_extraction_is_deterministic(case):
    first = extract_dates(case["text"], case["lang"], case.get("source_field", "description_original"))
    second = extract_dates(case["text"], case["lang"], case.get("source_field", "description_original"))
    assert [fact.to_dict() for fact in first] == [fact.to_dict() for fact in second]


OFFER_EN = """We are looking for a finance intern.

The internship lasts six months, starting January 2027.
Applications must be received by 15 November 2025.
You will be based in Paris. Salary: 2,000 euros per month.
The offer was posted on 3 January 2025.
Requirements: two years of prior experience in Excel, a master degree.
The position ends on 30 June 2027.
"""

OFFER_FR = """Poste d'alternance en finance.

Stage de 6 mois à partir du 1er janvier 2027, à Paris.
Date limite de candidature : 15 novembre 2025.
Deux ans d'expérience en Excel exigés.
Annonce publiée le 3 janvier 2025.
"""


def test_long_offer_keeps_exact_offsets_and_quotes():
    facts = extract_dates(OFFER_EN, "en")
    quotes = {fact.fact_type: fact.quote for fact in facts}
    assert quotes == {
        "duration_exact": "lasts six months",
        "start": "starting January 2027",
        "deadline": "Applications must be received by 15 November 2025",
        "published": "posted on 3 January 2025",
        "end": "ends on 30 June 2027",
    }
    for fact in facts:
        assert OFFER_EN[fact.start_offset:fact.end_offset] == fact.quote


def test_long_offer_never_reads_a_salary_or_an_experience_as_a_duration():
    facts = extract_dates(OFFER_EN, "en")
    durations = [fact for fact in facts if fact.fact_type.startswith("duration")]
    assert [fact.value for fact in durations] == [{"months_min": 6, "months_max": 6}]


def test_long_french_offer_is_read_the_same_way():
    facts = extract_dates(OFFER_FR, "fr")
    by_type = facts_by_type(facts)
    assert by_type["start"][0].value == {"day": 1, "month": 1, "year": 2027}
    assert by_type["deadline"][0].value == {"day": 15, "month": 11, "year": 2025}
    assert by_type["published"][0].value == {"day": 3, "month": 1, "year": 2025}
    assert [fact.fact_type for fact in facts].count("duration_exact") == 1
    for fact in facts:
        assert OFFER_FR[fact.start_offset:fact.end_offset] == fact.quote


def test_the_corpus_is_classified_at_least_95_percent():
    total = 0
    correct = 0
    for case in CASES:
        facts = extract_dates(
            case["text"], case["lang"], case.get("source_field", "description_original")
        )
        found = {_signature(fact) for fact in facts}
        for item in case["expected"]:
            total += 1
            if _signature_from_dict(item) in found:
                correct += 1
    assert total >= 50
    assert correct / total >= 0.95


def test_a_deadline_is_never_reported_as_a_start():
    facts = extract_dates("Apply by 15 November 2025", "en")
    assert [fact.fact_type for fact in facts] == ["deadline"]
    assert facts[0].value == {"day": 15, "month": 11, "year": 2025}


def test_a_month_without_a_year_never_invents_a_day():
    facts = extract_dates("Starting January", "en")
    assert len(facts) == 1
    fact = facts[0]
    assert fact.fact_type == "start"
    assert fact.value == {"day": None, "month": 1, "year": None}
    assert fact.precision == "month"
    assert fact.confidence == "inferred"


def test_a_maximum_bound_is_never_used_as_a_minimum():
    facts = extract_dates("Up to six months", "en")
    assert [fact.fact_type for fact in facts] == ["duration_max"]
    assert facts[0].value == {"months_min": None, "months_max": 6}
    assert not extract_dates("Up to six months", "en")[0].contradictions


def test_a_minimum_bound_is_never_used_as_a_maximum():
    facts = extract_dates("At least six months", "en")
    assert [fact.fact_type for fact in facts] == ["duration_min"]
    assert facts[0].value == {"months_min": 6, "months_max": None}


def test_an_interval_is_reported_as_a_range():
    facts = extract_dates("Three to six months", "en")
    assert [fact.fact_type for fact in facts] == ["duration_range"]
    assert facts[0].value == {"months_min": 3, "months_max": 6}


def test_prior_experience_is_never_a_contract_duration():
    assert extract_dates("Two years of prior experience", "en") == []
    assert extract_dates("Deux ans d'expérience exigés", "fr") == []
    assert extract_dates("Zwei Jahre Berufserfahrung", "de") == []


def test_ambiguous_numeric_date_keeps_both_readings():
    facts = extract_dates("Posted on 01/02/2025", "en")
    assert len(facts) == 1
    fact = facts[0]
    assert fact.confidence == "ambiguous"
    assert fact.precision == "unknown"
    # The day and the month are not guessed: only the year is certain.
    assert fact.value == {"day": None, "month": None, "year": 2025}
    assert fact.contradictions == [
        "ambiguous_reading:2025-01-02",
        "ambiguous_reading:2025-02-01",
    ]


def test_two_conflicting_dates_name_each_other():
    facts = extract_dates(
        "Starting January 2027. The position also starts on 5 March 2027.",
        "en",
    )
    starts = facts_by_type(facts)["start"]
    assert len(starts) == 2
    ids = {fact.fact_id for fact in starts}
    for fact in starts:
        assert fact.contradictions
        for other in fact.contradictions:
            assert other in ids


def test_published_after_deadline_is_a_mutual_contradiction():
    facts = extract_dates(
        "Posted 20 November 2025. Apply by 15 November 2025.",
        "en",
    )
    by_type = facts_by_type(facts)
    published = by_type["published"][0]
    deadline = by_type["deadline"][0]
    assert published.contradictions == [deadline.fact_id]
    assert deadline.contradictions == [published.fact_id]


def test_start_after_end_is_a_mutual_contradiction():
    facts = extract_dates(
        "The contract starts on 1 July 2027 and ends on 30 June 2027.",
        "en",
    )
    by_type = facts_by_type(facts)
    start = by_type["start"][0]
    end = by_type["end"][0]
    assert start.contradictions == [end.fact_id]
    assert end.contradictions == [start.fact_id]


def test_no_day_is_invented_anywhere_in_the_corpus():
    for case in CASES:
        facts = extract_dates(case["text"], case["lang"], case.get("source_field", "description_original"))
        for fact in facts:
            if fact.fact_type not in {"published", "deadline", "start", "end"}:
                continue
            if fact.precision == "day":
                # A day is only asserted when the text writes one.
                assert fact.value["day"] is not None
            if fact.precision == "month":
                # A month precision never carries a day when a year is known.
                assert fact.value["day"] is None or fact.value["year"] is None
            if fact.precision == "unknown":
                # An unknown date commits to nothing but the year.
                assert fact.value["day"] is None and fact.value["month"] is None
            if fact.fact_type in {"duration_exact", "duration_min", "duration_max"}:
                assert fact.value["months_min"] is not None or fact.value["months_max"] is not None


def test_language_detection_is_stable_and_readable():
    assert detect_language("Apply by 15 November 2025 for your internship position") == "en"
    assert detect_language("Candidatures jusqu'au 15 novembre 2025 pour votre stage") == "fr"
    assert detect_language("Bewerbungsfrist: 15. November 2025 für das Praktikum") == "de"
    assert detect_language("Scadenza: 15 novembre 2025 per il tirocinio") == "it"
    assert detect_language("Fecha límite: 15 de noviembre de 2025 para la práctica") == "es"
    assert detect_language("") == "en"


def test_auto_language_finds_the_same_facts_as_an_explicit_language():
    text = "Candidatures jusqu'au 15 novembre 2025"
    assert extract_dates(text, "auto") == extract_dates(text, "fr")
    assert extract_dates("Apply by 15 November 2025", "auto") == extract_dates(
        "Apply by 15 November 2025", "en"
    )


def test_unknown_language_is_refused_instead_of_guessed():
    with pytest.raises(ValueError):
        extract_dates("Apply by 15 November 2025", "klingon")


def test_non_string_input_is_refused():
    with pytest.raises(TypeError):
        extract_dates(None, "en")
    with pytest.raises(TypeError):
        extract_dates(42, "en")


def test_empty_text_yields_no_fact():
    assert extract_dates("", "en") == []
    assert extract_dates("   \n  ", "fr") == []


def test_offer_level_extraction_reads_text_and_structured_fields():
    offer = {
        "title": "Finance Internship (Jan-June 2027)",
        "description_original": "Apply by 15 November 2025. Duration: 6 months.",
        "posted_date": "2025-01-03",
        "deadline_date": "2025-11-15",
        "start_date": "2027-01-01",
        "end_date": "2027-06-30",
        "duration_months": 6,
    }
    facts = extract_offer_dates(offer, lang="en")
    by_type = facts_by_type(facts)
    assert "published" in by_type
    assert "deadline" in by_type
    assert "start" in by_type
    assert "end" in by_type
    assert "duration_exact" in by_type
    for fact in facts:
        assert fact.source_field
        assert fact.quote


def test_offer_level_extraction_exposes_conflicting_sources():
    offer = {
        "title": "Finance Internship",
        "description_original": "Starting January 2027.",
        "start_date": "2027-05-01",
    }
    facts = extract_offer_dates(offer, lang="en")
    starts = facts_by_type(facts)["start"]
    assert len(starts) == 2
    ids = {fact.fact_id for fact in starts}
    for fact in starts:
        assert fact.contradictions
        for other in fact.contradictions:
            assert other in ids


def test_offer_level_extraction_rejects_non_objects():
    with pytest.raises(TypeError):
        extract_offer_dates("not an offer")
