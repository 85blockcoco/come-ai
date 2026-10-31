"""Tests for J-1 briefing generator (SPEC-037)."""

from __future__ import annotations


from career.j1_briefing import BriefingDoc, build_j1_briefing, to_dict


def test_build_basic() -> None:
    doc = build_j1_briefing(
        "app_1",
        company_facts=["Acme is a fintech"],
        top_questions=["Why us?"],
        cv_sections=["Experience", "Skills"],
    )
    assert isinstance(doc, BriefingDoc)
    assert doc.application_id == "app_1"
    assert doc.company_facts == ["Acme is a fintech"]
    assert doc.top_questions == ["Why us?"]
    assert doc.cv_section_reread == ["Experience", "Skills"]


def test_star_ready_filter() -> None:
    ws = [
        {"name": "ws1", "completeness": 0.9},
        {"name": "ws2", "completeness": 0.5},
    ]
    doc = build_j1_briefing("app_2", star_worksheets=ws)
    assert "ws1" in doc.star_ready
    assert "ws2" in doc.incomplete_sections


def test_empty_star_marks_incomplete() -> None:
    doc = build_j1_briefing("app_3")
    assert "STAR worksheets" in doc.incomplete_sections


def test_admin_blockers() -> None:
    doc = build_j1_briefing("app_4", admin_blockers=["visa", "housing"])
    assert doc.admin_blockers == ["visa", "housing"]


def test_to_dict() -> None:
    doc = build_j1_briefing("app_5", company_facts=["f"])
    d = to_dict(doc)
    assert d["application_id"] == "app_5"
    assert "incomplete_sections" in d


def test_empty_inputs() -> None:
    doc = build_j1_briefing("app_6")
    assert doc.company_facts == []
    assert doc.top_questions == []
    assert doc.star_ready == []
    assert doc.admin_blockers == []
    assert doc.cv_section_reread == []


def test_star_threshold_custom() -> None:
    ws = [{"name": "ws1", "completeness": 0.7}]
    doc = build_j1_briefing("app_7", star_worksheets=ws, star_completeness_threshold=0.6)
    assert "ws1" in doc.star_ready


def test_adversarial_none_values() -> None:
    doc = build_j1_briefing("app_8", company_facts=None, top_questions=None)
    assert doc.company_facts == []
    assert doc.top_questions == []