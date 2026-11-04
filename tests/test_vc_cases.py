from __future__ import annotations

import json
from pathlib import Path

import pytest

from academics.vc.cases import (
    case_payload,
    evaluate_case,
    extract_numbers,
    normalize_text,
    unsupported_numbers,
)
from academics.vc.content import load_content
from academics.vc.drills import liquidation_waterfall
from academics.vc.errors import ContentError
from academics.vc.models import CaseCriterion, CaseQuestion, CaseStudy


def test_case_weights_and_allowed_numbers_are_valid() -> None:
    content = load_content()
    assert len(content.cases) >= 4
    for case in content.cases:
        total = sum(
            criterion.weight
            for question in case.questions
            for criterion in question.criteria
        )
        assert total == pytest.approx(1.0, abs=0.001)
        for question in case.questions:
            assert question.criteria
            for criterion in question.criteria:
                for expected in criterion.expected_numbers:
                    value = float(expected["value"])
                    assert any(abs(value - allowed) <= 1e-6 for allowed in case.allowed_numbers)


def test_each_criterion_is_evaluated_separately() -> None:
    case = load_content().case("VC03-CASE01")
    attempt = evaluate_case(
        case,
        {
            "q1": "Post-money 10 M€, investor 20%.",
            "q2": "2 million new shares.",
            "q3": "The runway shortens and a bridge may dilute further.",
        },
    )
    assert attempt.score == pytest.approx(1.0)
    assert len(attempt.criteria_results) == 4
    assert all(item["matched"] for item in attempt.criteria_results)
    assert attempt.model_answer.startswith("Post-money 10 M€")


def test_partial_answer_uses_weighted_sum() -> None:
    case = load_content().case("VC03-CASE01")
    attempt = evaluate_case(case, {"q1": "Post-money 10 M€, investor 20%."})
    assert attempt.score == pytest.approx(0.5)
    assert sum(item["earned"] for item in attempt.criteria_results) == pytest.approx(0.5)
    assert attempt.score == pytest.approx(
        round(sum(item["earned"] for item in attempt.criteria_results), 4)
    )


def test_empty_and_partial_answers_are_honest() -> None:
    case = load_content().case("VC04-CASE02")
    empty = evaluate_case(case, {})
    assert empty.score == 0.0
    assert all(not item["matched"] for item in empty.criteria_results)

    partial = evaluate_case(case, {"q1": "Post-money 30 M€, investor 20%."})
    assert partial.score == pytest.approx(0.4)


def test_unsupported_number_is_flagged_and_penalizes_the_score() -> None:
    case = load_content().case("VC03-CASE01")
    answers = {
        "q1": "Post-money 10 M€, investor 20%.",
        "q2": "2 million new shares.",
        "q3": "The runway shortens and a bridge may dilute further.",
    }
    clean = evaluate_case(case, answers)
    polluted = evaluate_case(case, {**answers, "q2": "2 million shares, i.e. 42 M€."})
    assert clean.score == pytest.approx(1.0)
    assert polluted.score == pytest.approx(0.875)
    assert polluted.score < clean.score
    assert 42.0 in polluted.unsupported_numbers
    assert 42.0 not in clean.unsupported_numbers


def test_model_answer_hidden_before_submission() -> None:
    case = load_content().case("VC07-CASE04")
    payload = case_payload(case)
    assert "model_answer" not in payload
    assert "model_answer" not in json.dumps(payload)
    with_model = case_payload(case, include_model=True)
    assert with_model["model_answer"] == case.model_answer


def test_down_round_waterfall_priority() -> None:
    rows = liquidation_waterfall(
        4,
        [
            {"name": "junior", "shares": 30, "invested": 3, "seniority": 2},
            {"name": "senior", "shares": 20, "invested": 2, "seniority": 1},
        ],
    )
    by_name = {row["name"]: row for row in rows}
    assert by_name["senior"]["total"] == 2
    assert by_name["junior"]["total"] == 2


def test_accent_insensitive_keyword_matching() -> None:
    criterion = CaseCriterion(
        id="c1",
        label="Préférence",
        weight=1.0,
        required_keywords=("preference",),
    )
    question = CaseQuestion(id="q1", prompt="Expliquez.", criteria=(criterion,))
    case = CaseStudy(
        id="VC07-CASE99",
        topic_id="VC07",
        title="Test",
        context="Un cas synthétique avec une préférence de liquidation.",
        facts=(),
        questions=(question,),
        model_answer="La préférence est remboursée avant les actions ordinaires.",
        allowed_numbers=(),
    )
    attempt = evaluate_case(case, {"q1": "La préférence de liquidation passe d'abord."})
    assert attempt.score == 1.0


def test_numeric_tolerance_for_expected_numbers() -> None:
    criterion = CaseCriterion(
        id="c1",
        label="Post-money",
        weight=1.0,
        expected_numbers=({"value": 10, "tolerance": 0.01},),
    )
    question = CaseQuestion(id="q1", prompt="Post-money ?", criteria=(criterion,))
    case = CaseStudy(
        id="VC04-CASE99",
        topic_id="VC04",
        title="Test",
        context="Un cas synthétique avec un post-money de 10 M€.",
        facts=(),
        questions=(question,),
        model_answer="Le post-money est de 10 M€.",
        allowed_numbers=(10,),
    )
    assert evaluate_case(case, {"q1": "10.005 M€"}).score == 1.0
    assert evaluate_case(case, {"q1": "10.02 M€"}).score == 0.0


def test_case_with_unknown_expected_number_is_rejected_at_load_time(tmp_path: Path) -> None:
    (tmp_path / "topics.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "topics": [
                    {
                        "id": "VC01",
                        "code": "VC01",
                        "title_fr": "Test",
                        "title_en": "Test",
                        "order": 1,
                        "exam_weight": 0.1,
                        "description": "Topic de test.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "cases_bad.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_id": "cases-bad",
                "topic_id": "VC01",
                "language": "fr",
                "source_type": "original",
                "license": "Test",
                "items": [
                    {
                        "kind": "case",
                        "id": "VC01-CASE01",
                        "topic_id": "VC01",
                        "title": "Cas invalide",
                        "context": "Un contexte suffisamment long pour être valide.",
                        "facts": [],
                        "questions": [
                            {
                                "id": "q1",
                                "prompt": "Question ?",
                                "criteria": [
                                    {
                                        "id": "c1",
                                        "label": "Critère",
                                        "weight": 1.0,
                                        "expected_numbers": [{"value": 99, "tolerance": 0.1}],
                                    }
                                ],
                            }
                        ],
                        "model_answer": "Une réponse modèle suffisamment longue.",
                        "allowed_numbers": [1, 2],
                        "difficulty": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContentError):
        load_content(tmp_path)


def test_text_helpers() -> None:
    assert normalize_text("Préférence  de LIQUIDATION") == "preference de liquidation"
    assert extract_numbers("10 M€ et 2,5 %") == [10.0, 2.5]
    case = load_content().case("VC07-CASE04")
    assert unsupported_numbers(case, "A receives 5.5 M€ and B receives 2.9 M€") == []
