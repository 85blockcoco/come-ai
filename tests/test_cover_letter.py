"""Tests for targeted cover letter generation (N100-F01)."""

from __future__ import annotations


from career.cover_letter import CoverLetter, build_cover_letter, to_dict


def test_build_with_evidence() -> None:
    letter = build_cover_letter(
        candidate_name="Alice",
        target_role="Stage M&A",
        company="Acme",
        evidence=["Managed a team of 5", "Built a dashboard"],
    )
    assert isinstance(letter, CoverLetter)
    assert "Alice" in letter.body
    assert "Stage M&A" in letter.body
    assert "Acme" in letter.body
    assert "Managed a team of 5" in letter.body
    assert letter.evidence_used == ["Managed a team of 5", "Built a dashboard"]
    assert letter.missing_evidence == []


def test_build_no_evidence() -> None:
    letter = build_cover_letter(
        candidate_name="Bob",
        target_role="Stage Data",
        company="Beta",
        evidence=[],
    )
    assert "À COMPLÉTER" in letter.body
    assert letter.missing_evidence == ["aucune preuve fournie"]
    assert letter.evidence_used == []


def test_subject_and_recipient() -> None:
    letter = build_cover_letter(
        candidate_name="C",
        target_role="R",
        company="Comp",
        evidence=["fact"],
    )
    assert letter.subject == "Candidature — R"
    assert letter.recipient == "Comp"


def test_language_default() -> None:
    letter = build_cover_letter(candidate_name="X", target_role="R", company="C", evidence=["f"])
    assert letter.language == "fr"


def test_to_dict() -> None:
    letter = build_cover_letter(candidate_name="X", target_role="R", company="C", evidence=["f"])
    d = to_dict(letter)
    assert "body" in d
    assert "evidence_used" in d


def test_no_invented_facts() -> None:
    # evidence empty -> body contains placeholder, no fabricated claims
    letter = build_cover_letter(candidate_name="X", target_role="R", company="C", evidence=[])
    assert "À COMPLÉTER" in letter.body


def test_evidence_in_body() -> None:
    ev = ["Led project X", "Reduced costs by 10%"]
    letter = build_cover_letter(candidate_name="X", target_role="R", company="C", evidence=ev)
    for e in ev:
        assert e in letter.body