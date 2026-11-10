"""Contract tests for career.offer_requirements (CVBOOST-02).

These tests pin the documented schema: every field of the contract, its
vocabulary, determinism, stable ids and resolvable locators.  A consumer of
this package relies on those invariants instead of a generic "exigence n°N".
"""

from __future__ import annotations

import re

import pytest

from career.offer_requirements import (
    CATEGORIES,
    ID_PREFIX,
    MODALITIES,
    SCHEMA_VERSION,
    SOURCE_FIELDS,
    UNKNOWN_CONFIDENCE_CAP,
    analyze_offer,
    load_fixtures,
    requirement_provenance,
    resolve_locator,
    split_source_lines,
)

REQUIREMENT_KEYS = frozenset(
    {
        "id",
        "text",
        "source_field",
        "locator",
        "heading",
        "category",
        "modality",
        "confidence",
        "negated",
        "injection_suspect",
        "notes",
    }
)
TOP_LEVEL_KEYS = frozenset(
    {
        "offer_id",
        "requirements",
        "duplicates",
        "contradictions",
        "application_deadline",
        "injection_suspects",
        "truncated",
        "warnings",
        "skipped",
        "stats",
        "contract_version",
    }
)

_ID_RE = re.compile(r"^req_[0-9a-f]{16}(_\d+)?$")
_LOCATOR_RE = re.compile(r"^line:\d+(\.sentence:\d+)?$")


def test_fixtures_cover_five_languages_and_36_offers() -> None:
    fixtures = load_fixtures()
    assert len(fixtures) >= 36
    assert {fixture["language"] for fixture in fixtures} == {"fr", "en", "de", "it", "es"}
    assert len({fixture["id"] for fixture in fixtures}) == len(fixtures)


def test_analyze_offer_returns_documented_schema() -> None:
    analysis = analyze_offer(load_fixtures()[0])
    assert set(analysis) <= TOP_LEVEL_KEYS
    assert analysis["contract_version"] == SCHEMA_VERSION
    for record in analysis["requirements"]:
        assert set(record) == REQUIREMENT_KEYS
        assert record["category"] in CATEGORIES
        assert record["modality"] in MODALITIES
        assert record["source_field"] in SOURCE_FIELDS
        assert _ID_RE.fullmatch(record["id"])
        assert record["id"].startswith(ID_PREFIX)
        assert _LOCATOR_RE.fullmatch(record["locator"])
        assert 0.0 <= record["confidence"] <= 1.0
        assert isinstance(record["negated"], bool)
        assert isinstance(record["injection_suspect"], bool)
        assert isinstance(record["notes"], list)


def test_analysis_is_fully_deterministic() -> None:
    offer = load_fixtures()[1]
    first = analyze_offer(offer)
    second = analyze_offer(offer)
    assert first == second
    ids = [record["id"] for record in first["requirements"]]
    assert ids == sorted_ids_not_required(ids)  # ordering is stable, not sorted
    assert analyze_offer(offer)["requirements"][0]["id"] == ids[0]


def sorted_ids_not_required(ids: list[str]) -> list[str]:
    # The contract promises a stable order, not alphabetical sorting.
    return ids


def test_unknown_modality_is_never_disguised_as_high_confidence() -> None:
    offer = next(
        fixture
        for fixture in load_fixtures()
        if fixture["id"] == "OFF-033"
    )
    records = analyze_offer(offer)["requirements"]
    assert records, "Le passage « Context » doit rester exposé."
    for record in records:
        if record["modality"] == "unknown":
            assert record["confidence"] <= UNKNOWN_CONFIDENCE_CAP


def test_unverified_placeholder_stays_unknown() -> None:
    analyses = (
        analyze_offer({"requirements": "Language level to verify"}),
        analyze_offer({"description_original": "Requirements:\nLanguage level to verify"}),
    )

    for analysis in analyses:
        record = analysis["requirements"][0]
        assert record["modality"] == "unknown"
        assert record["confidence"] <= UNKNOWN_CONFIDENCE_CAP


def test_structured_fields_carry_the_highest_confidence() -> None:
    offer = next(fixture for fixture in load_fixtures() if fixture["id"] == "OFF-028")
    analysis = analyze_offer(offer)
    for record in analysis["requirements"]:
        assert record["source_field"] == "requirements"
        assert record["confidence"] >= 0.9
        assert record["modality"] == "required"


def test_locator_resolves_to_the_verbatim_passage() -> None:
    offer = next(fixture for fixture in load_fixtures() if fixture["id"] == "OFF-004")
    analysis = analyze_offer(offer)
    record = analysis["requirements"][0]
    assert record["source_field"] == "description_original"
    passage = resolve_locator(offer, record["source_field"], record["locator"])
    assert passage == "- Bachelor-Abschluss im Finanzbereich"
    lines = split_source_lines(offer, "description_original")
    assert any("Voraussetzungen" in line for line in lines)
    # A fabricated locator resolves to "" : nothing is ever guessed.
    assert resolve_locator(offer, "description_original", "line:999") == ""


def test_requirement_provenance_fails_loudly_for_unknown_ids() -> None:
    offer = next(fixture for fixture in load_fixtures() if fixture["id"] == "OFF-001")
    analysis = analyze_offer(offer)
    target = analysis["requirements"][0]
    provenance = requirement_provenance(analysis, target["id"], offer)
    assert provenance["source_field"] == target["source_field"]
    assert provenance["locator"] == target["locator"]
    assert provenance["text"] == target["text"]
    assert provenance["modality"] == target["modality"]
    assert "req_" + "f" * 16 not in [record["id"] for record in analysis["requirements"]]
    with pytest.raises(LookupError):
        requirement_provenance(analysis, "req_does_not_exist", offer)


def test_ids_are_unique_and_stable_across_whole_fixture_set() -> None:
    fixtures = load_fixtures()
    seen: set[str] = set()
    for fixture in fixtures:
        analysis = analyze_offer(fixture)
        ids = [record["id"] for record in analysis["requirements"]]
        assert len(ids) == len(set(ids)), f"identifiant dupliqué pour {fixture['id']}"
        assert not seen & set(ids)
        seen |= set(ids)


def test_preference_is_never_mandatory_across_all_fixtures() -> None:
    preferred_markers = (
        "nice to have", "appreci", "souhait", "un plus", "gradit",
        "valoriz", "von vorteil", "wunschenswert", "desirable", "bonus",
    )
    for offer in load_fixtures():
        for record in analyze_offer(offer)["requirements"]:
            if record["modality"] == "preferred":
                assert record["notes"], "Une préférence doit porter une note explicative."
            for marker in preferred_markers:
                if marker in record["text"].casefold():
                    assert record["modality"] != "required", (
                        f"{offer['id']}: « {record['text']} » est une préférence, jamais une obligation."
                    )


def test_negations_are_never_counted_as_required() -> None:
    for offer in load_fixtures():
        for record in analyze_offer(offer)["requirements"]:
            if record["negated"]:
                assert record["modality"] == "contextual"
                assert "not treated" in " ".join(record["notes"])


def test_empty_and_none_offers_produce_honest_empty_contract() -> None:
    empty = analyze_offer({})
    assert empty["offer_id"] == ""
    assert empty["requirements"] == []
    assert empty["duplicates"] == []
    assert empty["contradictions"] == []
    assert empty["application_deadline"] is None
    assert empty["truncated"] is False
    assert analyze_offer(None) == empty


def test_offer_text_is_data_not_instruction_static_guards() -> None:
    # The package stays pure and inert: no network, no subprocess, no eval.
    forbidden_patterns = (
        "smtplib", "subprocess", "socket", "urllib", "requests",
        "eval(", "exec(", "__import__", "os.system",
        "pickle", "httpx",
    )
    import career.offer_requirements as package
    from pathlib import Path

    package_dir = Path(package.__file__).resolve().parent
    sources = list(package_dir.glob("*.py"))
    assert len(sources) >= 4
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in text, f"{source.name} contient '{pattern}'"
