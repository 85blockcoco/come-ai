from __future__ import annotations

import json

import pytest

from academics.vc.cram import (
    FORMULA_GROUPS,
    TRAPS,
    formula_payload,
    plan_blocks,
    render_html,
    render_markdown,
)
from academics.vc.drills import parse_number
from academics.vc.errors import ContentError, InputError
from academics.vc.pastpapers import (
    answer_template,
    find_paper,
    grade_paper,
    load_papers,
    paper_payload,
)


def _papers_by_year():
    return {paper.year: paper for paper in load_papers()}


def _correct_answers(paper) -> dict[str, str]:
    answers: dict[str, str] = {}
    for question in paper.questions:
        if question.kind in ("mcq", "numeric"):
            answers[question.id] = question.answer
        for part in question.parts:
            if part.kind == "numeric":
                answers[part.id] = part.answer
    return answers


def test_papers_load_sorted_with_unique_ids_and_three_years() -> None:
    papers = load_papers()
    assert [paper.year for paper in papers] == [2023, 2024, 2025]
    ids = [question.id for paper in papers for question in paper.questions]
    assert len(ids) == len(set(ids))
    assert all(paper.questions for paper in papers)
    assert all(paper.points > 0 for paper in papers)


def test_2025_paper_matches_the_real_exam_structure() -> None:
    paper = _papers_by_year()[2025]
    assert paper.duration_minutes == 90
    assert len(paper.questions) == 21
    assert sum(1 for question in paper.questions if question.section == "A") == 15
    assert sum(1 for question in paper.questions if question.section == "B") == 4
    assert sum(1 for question in paper.questions if question.section == "C") == 2
    assert {section["id"] for section in paper.sections} == {"A", "B", "C"}


def test_every_mcq_has_a_valid_answer_and_a_solution() -> None:
    for paper in load_papers():
        for question in paper.questions:
            if question.kind != "mcq":
                continue
            labels = {choice.label for choice in question.choices}
            assert question.answer in labels, question.id
            assert question.solution, question.id
            assert len(question.choices) >= 2


def test_every_numeric_answer_parses_and_has_a_solution() -> None:
    for paper in load_papers():
        for question in paper.questions:
            values = []
            if question.kind == "numeric":
                values.append((question.id, question.answer, question.solution))
            for part in question.parts:
                if part.kind == "numeric":
                    values.append((part.id, part.answer, part.solution))
            for item_id, answer, solution in values:
                parse_number(answer)
                assert solution, item_id


def test_correct_answers_score_full_marks_on_auto_graded_items() -> None:
    for paper in load_papers():
        result = grade_paper(paper, _correct_answers(paper))
        assert result["auto_points"] == result["auto_max"], paper.paper_id
        assert result["auto_percent"] == 100.0
        assert all(
            item["status"] in ("correct", "self_assess") for item in result["items"]
        )


def test_wrong_and_missing_answers_are_reported() -> None:
    paper = _papers_by_year()[2025]
    result = grade_paper(
        paper,
        {
            "2025-A01": "A",  # wrong, correct is D
            "2025-B16": "",  # missing
            "2025-B17a": "9.99",  # wrong numeric
        },
    )
    by_id = {item["question_id"]: item for item in result["items"]}
    assert by_id["2025-A01"]["status"] == "incorrect"
    assert by_id["2025-B16"]["status"] == "missing"
    assert by_id["2025-B17a"]["status"] == "incorrect"
    assert result["auto_points"] < result["auto_max"]
    assert result["auto_percent"] < 100


def test_numeric_answers_accept_units_and_rounding() -> None:
    paper = _papers_by_year()[2025]
    result = grade_paper(
        paper,
        {
            "2025-B16": "54 %",
            "2025-B17a": "1.82",
            "2025-B17b": "2.27",
            "2025-B19d": "2,000 M€",
        },
    )
    by_id = {item["question_id"]: item for item in result["items"]}
    assert by_id["2025-B16"]["status"] == "correct"
    assert by_id["2025-B17a"]["status"] == "correct"
    assert by_id["2025-B17b"]["status"] == "correct"
    assert by_id["2025-B19d"]["status"] == "correct"


def test_answer_template_only_contains_auto_graded_keys() -> None:
    paper = _papers_by_year()[2025]
    template = answer_template(paper)
    assert "2025-A01" in template
    assert "2025-B16" in template
    assert "2025-B17a" in template
    assert "2025-C20a" not in template
    assert all(value == "" for value in template.values())


def test_paper_payload_hides_solutions_unless_requested() -> None:
    paper = _papers_by_year()[2025]
    hidden = paper_payload(paper)
    shown = paper_payload(paper, solutions=True)
    assert "solution" not in hidden["questions"][0]
    assert hidden["questions"][0]["choices"][0]["label"] == "A"
    assert shown["questions"][0]["solution"]
    assert shown["questions"][0]["answer"] == "D"


def test_find_paper_rejects_unknown_year() -> None:
    with pytest.raises(InputError):
        find_paper(1999)


def test_invalid_pack_is_rejected(tmp_path) -> None:
    (tmp_path / "topics.json").write_text(
        json.dumps({"topics": [{"id": "VC01"}]}), encoding="utf-8"
    )
    (tmp_path / "paper_1999.json").write_text(
        json.dumps(
            {
                "schema_version": 99,
                "paper_id": "bad",
                "year": 1999,
                "sections": [{"id": "A", "title": "A", "points": 1}],
                "questions": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContentError):
        load_papers(tmp_path)


def test_formula_sheet_covers_the_six_exam_families() -> None:
    payload = formula_payload()
    ids = {group["id"] for group in payload["groups"]}
    assert {"valuation", "cap-table", "vc-method", "terms", "notes", "lbo"} <= ids
    assert len(TRAPS) >= 12
    for group in FORMULA_GROUPS:
        assert group.items
        for item in group.items:
            assert item.formula
            assert item.note


def test_plan_blocks_are_bounded_and_complete() -> None:
    for minutes in (15, 30, 60, 90, 120):
        blocks = plan_blocks(minutes)
        assert blocks
        assert blocks[-1]["end_minute"] == minutes
        assert all(block["minutes"] > 0 for block in blocks)
        assert all(
            block["end_minute"] > block["start_minute"] for block in blocks
        )


def test_render_markdown_contains_plan_formulas_and_papers() -> None:
    papers = load_papers()
    text = render_markdown(papers, minutes=90)
    assert "# VC Exam Cram" in text
    assert "V_POST = I / F_INV" in text
    assert "2025 — EDHEC Venture Capital" in text
    assert "Q16" in text
    assert "Worked solution" in text or "*Solution:*" in text


def test_render_html_is_self_contained_and_escapes_content() -> None:
    papers = load_papers()
    page = render_html(papers, minutes=60)
    assert page.startswith("<!DOCTYPE html>")
    assert "<style>" in page
    assert "<details" in page
    assert "2025" in page
    assert "V_POST = I / F_INV" in page
    assert "http://" not in page and "https://" not in page
    assert page.count("<details") == page.count("</details>")
