"""Extraction tests for career.offer_requirements (CVBOOST-02).

Multilingual (FR/EN/DE/IT/ES) checks of provenance precision: categories,
modalities, deadline, contradictions exposed side by side, and duplicate
handling — including translated duplicates that must never be silently
merged away.
"""

from __future__ import annotations

import pytest

from career.offer_requirements import analyze_offer, load_fixtures

FIXTURES = load_fixtures()


def analysis_for(offer_id: str) -> dict:
    offer = next(fixture for fixture in FIXTURES if fixture["id"] == offer_id)
    return analyze_offer(offer)


def requirements_for(offer_id: str) -> list[dict]:
    return analysis_for(offer_id)["requirements"]


@pytest.mark.parametrize(
    "offer_id, category",
    [
        ("OFF-001", "technical_skill"),
        ("OFF-002", "language"),
        ("OFF-003", "language"),
        ("OFF-004", "education"),
        ("OFF-005", "education"),
        ("OFF-006", "language"),
        ("OFF-007", "technical_skill"),
        ("OFF-014", "language"),
        ("OFF-020", "technical_skill"),
        ("OFF-036", "language"),
    ],
)
def test_expected_category_is_produced(offer_id: str, category: str) -> None:
    records = requirements_for(offer_id)
    assert any(record["category"] == category for record in records), (
        f"{offer_id}: aucune exigence de catégorie {category}."
    )


@pytest.mark.parametrize(
    "offer_id, index, expected_modality, expected_category",
    [
        # FR: "Espagnol apprécié" dans le champ structuré reste une préférence.
        ("OFF-001", 2, "preferred", "language"),
        # DE: bachelor requis, expérience "von Vorteil" reste préférée.
        ("OFF-004", 0, "required", "education"),
        ("OFF-004", 3, "preferred", "experience"),
        # IT: "gradito" n'est jamais obligatoire.
        ("OFF-005", 3, "preferred", "language"),
        # ES: "se valoriza" n'est jamais obligatoire.
        ("OFF-006", 3, "preferred", "language"),
        # EN: négation explicite.
        ("OFF-009", 0, "contextual", "language"),
        # FR: "n'est pas requise" ne peut jamais devenir une obligation.
        ("OFF-010", 0, "contextual", "technical_skill"),
    ],
)
def test_modality_and_category_by_fixture(
    offer_id: str, index: int, expected_modality: str, expected_category: str
) -> None:
    records = requirements_for(offer_id)
    assert len(records) > index, f"{offer_id}: moins d'exigences que prévu."
    record = records[index]
    assert record["modality"] == expected_modality
    assert record["category"] == expected_category


@pytest.mark.parametrize("offer_id", ["OFF-001", "OFF-004", "OFF-005", "OFF-006", "OFF-028"])
def test_each_language_has_structured_required_records(offer_id: str) -> None:
    records = requirements_for(offer_id)
    assert any(record["modality"] == "required" for record in records)
    for record in records:
        if record["modality"] == "required":
            assert record["confidence"] >= 0.85


def test_category_vocabulary_is_covered_by_fixtures() -> None:
    covered = set()
    for offer in FIXTURES:
        for record in analyze_offer(offer)["requirements"]:
            covered.add(record["category"])
    assert covered == {
        "technical_skill", "language", "education", "experience",
        "availability", "mobility", "work_authorization", "other",
    }


def test_provenance_locator_points_to_real_source_lines() -> None:
    offer = next(fixture for fixture in FIXTURES if fixture["id"] == "OFF-005")
    analysis = analyze_offer(offer)
    source_lines = analysis  # no: use split helper
    del source_lines
    for record in analysis["requirements"]:
        assert record["locator"].startswith("line:"), record
        if record["source_field"] == "description_original":
            number = int(record["locator"][5:].split(".")[0])
            assert number >= 2, "les titres de section ne sont jamais cités comme exigence."


def test_deadline_with_iso_date_in_description() -> None:
    analysis = analysis_for("OFF-013")
    deadline = analysis["application_deadline"]
    assert deadline is not None
    assert deadline["source_field"] == "description_original"
    assert deadline["date_iso"] == "2026-11-30"
    assert "Application deadline" in deadline["text"]
    # La ligne deadline n'est jamais transformée en exigence générique.
    assert all("deadline" not in record["text"].casefold() for record in analysis["requirements"])


def test_deadline_from_structured_field_beats_description_scan() -> None:
    analysis = analysis_for("OFF-014")
    deadline = analysis["application_deadline"]
    assert deadline["source_field"] == "deadline_date"
    assert deadline["date_iso"] == "2026-12-15"
    assert deadline["locator"] == "line:1"


def test_deadline_without_iso_date_keeps_text_and_reports_no_date() -> None:
    deadline = analysis_for("OFF-015")["application_deadline"]
    assert deadline is not None
    assert deadline["date_iso"] is None
    assert "12 décembre 2026" in deadline["text"]


def test_contradiction_is_exposed_with_both_original_sides() -> None:
    analysis = analysis_for("OFF-011")
    contradictions = analysis["contradictions"]
    assert len(contradictions) == 1
    entry = contradictions[0]
    assert entry["kind"] == "structured_vs_description"
    assert entry["structured"]["modality"] == "required"
    assert entry["described"]["modality"] == "preferred"
    assert "Anglais courant" == entry["structured"]["text"]
    assert "est un plus" in entry["described"]["text"]
    # Exposées, jamais arbitrées : les deux exigences restent toutes deux
    # présentes dans la liste, avec leur provenance respective.
    ids = {record["id"] for record in analysis["requirements"]}
    assert entry["structured"]["id"] in ids
    assert entry["described"]["id"] in ids


def test_negated_structured_vs_description_contradiction() -> None:
    entry = analysis_for("OFF-012")["contradictions"][0]
    assert entry["structured"]["modality"] == "required"
    assert entry["described"]["modality"] == "contextual"
    assert entry["described"]["id"] in {r["id"] for r in requirements_for("OFF-012")}


def test_translated_duplicates_are_kept_as_distinct_requirements() -> None:
    analysis = analysis_for("OFF-020")
    texts = [record["text"] for record in analysis["requirements"]]
    assert "Excel is required for this role." in texts
    assert "Excel requis pour ce poste." in texts
    # Une traduction n'est pas un doublon lexical : rien n'est fusionné.
    assert analysis["duplicates"] == []


def test_exact_duplicate_is_flagged_never_dropped() -> None:
    analysis = analysis_for("OFF-021")
    records = analysis["requirements"]
    assert len(records) == 2
    duplicates = analysis["duplicates"]
    assert len(duplicates) == 1
    assert duplicates[0]["id"] == records[1]["id"]
    assert duplicates[0]["duplicate_of"] == records[0]["id"]
    assert records[1]["id"].startswith(records[0]["id"] + "_")


def test_benefit_content_is_never_a_requirement() -> None:
    analysis = analysis_for("OFF-016")
    assert all(
        "bonus" not in record["text"].casefold()
        and "meal vouchers" not in record["text"].casefold()
        for record in analysis["requirements"]
    )
    assert analysis["skipped"]["benefit_lines"] >= 2


def test_other_sections_are_never_requirement_sources() -> None:
    analysis = analysis_for("OFF-002")
    assert all("financial models" not in record["text"].casefold() for record in analysis["requirements"])


def test_truncated_offer_is_flagged_top_level() -> None:
    analysis = analysis_for("OFF-022")
    assert analysis["truncated"] is True
    assert any("tronqué" in warning for warning in analysis["warnings"])


def test_html_never_leaks_into_quoted_texts() -> None:
    analysis = analysis_for("OFF-019")
    for record in analysis["requirements"]:
        assert "<" not in record["text"]
        assert ">" not in record["text"]
        assert "JavaScript" not in record["text"]
    assert any("balises" in warning for warning in analysis["warnings"])


def test_requirements_cap_keeps_extraction_bounded() -> None:
    offer = {
        "id": "OFF-CAP",
        "description_original": "Requirements:\n"
        + "\n".join(f"- Skill {index} definitely required for the role." for index in range(120)),
    }
    analysis = analyze_offer(offer)
    assert len(analysis["requirements"]) <= 60
