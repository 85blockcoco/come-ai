"""Regression checks for the official VC past-paper corpus.

These checks deliberately count the nested case parts as well as the top-level
questions.  A paper being present in JSON is not enough: every record must be
validated by the loader and reachable by the grader.
"""

from __future__ import annotations

from academics.vc.pastpapers import grade_paper, load_papers


def test_all_official_papers_and_assessed_units_are_loaded() -> None:
    papers = load_papers()

    assert {paper.year for paper in papers} == {2023, 2024, 2025}
    assert {paper.year: len(paper.questions) for paper in papers} == {
        2023: 22,
        2024: 24,
        2025: 21,
    }

    top_level = sum(len(paper.questions) for paper in papers)
    nested_parts = sum(len(question.parts) for paper in papers for question in paper.questions)
    # 67 source questions plus 33 case parts = the complete in-app assessment
    # inventory for the three supplied official packs.
    assert top_level == 67
    assert nested_parts == 33
    assert top_level + nested_parts == 100


def test_every_official_assessment_unit_has_a_grade_or_self_review_path() -> None:
    for paper in load_papers():
        answers = {}
        for question in paper.questions:
            if question.kind in {"mcq", "numeric"}:
                answers[question.id] = question.answer
            for part in question.parts:
                if part.kind == "numeric":
                    answers[part.id] = part.answer

        result = grade_paper(paper, answers)
        assessed_ids = {
            item["question_id"]
            for item in result["items"]
            if item["status"] in {"correct", "self_assess"}
        }
        expected_ids = {
            question.id
            for question in paper.questions
            if question.kind != "case"
        }
        expected_ids |= {
            part.id
            for question in paper.questions
            for part in question.parts
        }
        assert assessed_ids == expected_ids

