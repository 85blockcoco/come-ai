from __future__ import annotations

import json

import pytest

from academics.vc.content import load_content
from academics.vc.errors import ContentError, InputError
from academics.vc.exams import (
    build_exam,
    exam_payload,
    grade_exam,
    history_entry,
    is_expired,
    oral_questions,
    remaining_seconds,
)


def _correct_answers(exam, content) -> dict[str, str]:
    return {
        ref["ref_id"]: content.exam_question(ref["ref_id"]).answer
        for ref in exam.questions
    }


def _keys(payload) -> set[str]:
    if isinstance(payload, dict):
        result = set(payload)
        for value in payload.values():
            result |= _keys(value)
        return result
    if isinstance(payload, list):
        result: set[str] = set()
        for value in payload:
            result |= _keys(value)
        return result
    return set()


def test_expanded_bank_still_produces_twenty_questions_and_one_hundred_points() -> None:
    content = load_content()
    assert len(content.exams) == 26
    assert sum(question.points for question in content.exams) == 130
    exam = build_exam(content, questions=20, seed=0)
    assert len(exam.questions) == 20
    assert sum(item["points"] for item in exam.questions) == 100
    assert {question.topic_id for question in content.exams} == {
        "VC04",
        "VC05",
        "VC06",
        "VC07",
        "VC09",
    }
    assert {question.format for question in content.exams} == {"mcq", "numeric", "open"}


def test_exam_composition_is_deterministic_for_the_same_seed_and_topic_filter() -> None:
    content = load_content()
    first = build_exam(content, questions=5, minutes=30, seed=7, topic_ids=["VC04", "VC07"])
    second = build_exam(content, questions=5, minutes=30, seed=7, topic_ids=["VC07", "VC04"])
    assert [ref["ref_id"] for ref in first.questions] == [
        ref["ref_id"] for ref in second.questions
    ]
    assert [ref["points"] for ref in first.questions] == [
        ref["points"] for ref in second.questions
    ]
    assert first.exam_id != second.exam_id


def test_points_sum_to_one_hundred_and_questions_never_repeat() -> None:
    content = load_content()
    for count in (1, 2, 3, 7, 20):
        exam = build_exam(content, questions=count, seed=11)
        refs = [ref["ref_id"] for ref in exam.questions]
        assert len(refs) == count
        assert len(set(refs)) == count
        assert sum(ref["points"] for ref in exam.questions) == 100
        assert all(ref["points"] >= 1 for ref in exam.questions)


def test_timer_expiry_preserves_answers_and_marks_the_exam_expired() -> None:
    content = load_content()
    exam = build_exam(
        content,
        questions=4,
        minutes=30,
        seed=3,
        started_at="2026-11-02T10:00:00",
    )
    exam.answers = {
        exam.questions[0]["ref_id"]: "première réponse",
        exam.questions[1]["ref_id"]: "deuxième réponse",
    }
    before = dict(exam.answers)
    result = grade_exam(exam, content, now="2026-11-02T10:30:00")
    assert result["expired"] is True
    assert result["status"] == "expired"
    assert exam.answers == before
    assert result["answered"] == 2
    assert is_expired(exam, now="2026-11-02T10:30:00") is True
    assert remaining_seconds(exam, now="2026-11-02T10:29:59") == 1


def test_score_is_recomputable_from_stored_answers() -> None:
    content = load_content()
    exam = build_exam(content, questions=10, seed=5)
    exam.answers = _correct_answers(exam, content)
    result = grade_exam(exam, content)
    assert result["score"] == pytest.approx(1.0)
    assert result["points_earned"] == result["points_total"] == 100
    assert result["score"] == pytest.approx(
        round(result["points_earned"] / result["points_total"], 4)
    )
    assert sum(detail["earned"] for detail in result["details"]) == result["points_earned"]

    missing = exam.questions[0]["ref_id"]
    del exam.answers[missing]
    regraded = grade_exam(exam, content)
    assert regraded["score"] < 1.0
    assert regraded["score"] == pytest.approx(
        round(regraded["points_earned"] / regraded["points_total"], 4)
    )


def test_per_topic_scores_and_weak_topics() -> None:
    content = load_content()
    exam = build_exam(content, questions=20, seed=9)
    answers: dict[str, str] = {}
    for ref in exam.questions:
        question = content.exam_question(ref["ref_id"])
        if question.topic_id == "VC04":
            answers[question.id] = question.answer
    exam.answers = answers
    result = grade_exam(exam, content)
    assert result["per_topic"]["VC04"]["score"] == pytest.approx(1.0)
    assert "VC04" not in result["weak_topics"]
    unanswered_topics = {content.exam_question(ref["ref_id"]).topic_id for ref in exam.questions} - {"VC04"}
    assert set(result["weak_topics"]) == unanswered_topics
    assert {item["topic_id"] for item in result["remediation"]} == unanswered_topics
    assert all(item["reason"] for item in result["remediation"])


def test_mcq_accepts_letters_and_exact_text() -> None:
    content = load_content()
    exam = build_exam(content, questions=5, seed=2, topic_ids=["VC04"])
    answers: dict[str, str] = {}
    for ref in exam.questions:
        question = content.exam_question(ref["ref_id"])
        if question.format == "mcq":
            answers[question.id] = "ABCD"[question.choices.index(question.answer)]
        else:
            answers[question.id] = question.answer
    exam.answers = answers
    result = grade_exam(exam, content)
    assert result["score"] == pytest.approx(1.0)


def test_numeric_answers_accept_explicit_units() -> None:
    content = load_content()
    exam = build_exam(content, questions=5, seed=4, topic_ids=["VC04"])
    answers: dict[str, str] = {}
    for ref in exam.questions:
        question = content.exam_question(ref["ref_id"])
        if question.format == "numeric":
            suffix = {"m_eur": " M€", "percent": " %", "ratio": "x"}.get(question.unit, "")
            answers[question.id] = f"{question.answer}{suffix}"
        else:
            answers[question.id] = question.answer
    exam.answers = answers
    result = grade_exam(exam, content)
    assert result["score"] == pytest.approx(1.0)
    numeric = [
        detail for detail in result["details"] if detail["format"] == "numeric"
    ]
    assert numeric
    assert all(detail["correct"] for detail in numeric)


def test_open_question_uses_keywords_without_revealing_them_before_submit() -> None:
    content = load_content()
    exam = build_exam(content, questions=5, seed=6, topic_ids=["VC07"])
    open_question = next(
        content.exam_question(ref["ref_id"])
        for ref in exam.questions
        if content.exam_question(ref["ref_id"]).format == "open"
    )
    exam.answers = {open_question.id: " ".join(open_question.keywords[:2])}
    result = grade_exam(exam, content)
    detail = next(
        item for item in result["details"] if item["question_id"] == open_question.id
    )
    assert detail["correct"] is False
    assert detail["matched_keywords"] == list(open_question.keywords[:2])


def test_oral_follow_ups_never_reveal_the_model_answer() -> None:
    content = load_content()
    questions = oral_questions(content, "VC07", count=5)
    assert len(questions) == 5
    assert all(question["follow_ups"] for question in questions)
    serialized = json.dumps(questions, ensure_ascii=False)
    for item in questions:
        card = content.card(item["question_id"])
        assert card.answer not in serialized
        assert card.explanation not in serialized
    assert not {"answer", "explanation", "model_answer", "expected_answer"} & _keys(questions)


def test_insufficient_questions_is_a_readable_error() -> None:
    content = load_content()
    with pytest.raises(InputError, match="Not enough"):
        build_exam(content, questions=len(content.exams) + 1)
    with pytest.raises(InputError, match="Not enough"):
        build_exam(content, questions=sum(q.topic_id == "VC04" for q in content.exams) + 1, topic_ids=["VC04"])


def test_suspended_card_question_is_excluded() -> None:
    content = load_content()
    exam = build_exam(
        content,
        questions=4,
        seed=1,
        topic_ids=["VC04"],
        suspended_card_ids={"VC04-C005"},
    )
    refs = {ref["ref_id"] for ref in exam.questions}
    assert "VC04-E005" not in refs
    assert len(refs) == 4


def test_exam_payload_hides_answers_and_corrections_before_submit() -> None:
    content = load_content()
    exam = build_exam(content, questions=5, seed=8)
    payload = exam_payload(exam, content, now="2026-11-02T10:00:00")
    assert "questions" in payload
    assert payload["total_points"] == 100
    assert not {"answer", "expected_answer", "model_answer", "explanation"} & _keys(payload)
    assert all("choices" not in item for item in payload["questions"] if item["format"] != "mcq")


def test_history_entry_keeps_mastery_inputs_only() -> None:
    content = load_content()
    exam = build_exam(content, questions=4, seed=10)
    exam.answers = _correct_answers(exam, content)
    result = grade_exam(exam, content)
    entry = history_entry(result)
    assert entry["per_topic"] == result["per_topic"]
    assert entry["weak_topics"] == result["weak_topics"]
    assert "details" not in entry
    assert "remediation" not in entry


def test_exam_rejects_unknown_topic_filter() -> None:
    content = load_content()
    with pytest.raises(InputError, match="Unknown topic"):
        build_exam(content, questions=1, topic_ids=["VC99"])


def test_invalid_exam_content_is_rejected_at_load_time(tmp_path) -> None:
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
    (tmp_path / "exams_bad.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_id": "exams-bad",
                "topic_id": "VC01",
                "language": "fr",
                "source_type": "original",
                "license": "Test",
                "items": [
                    {
                        "kind": "exam_question",
                        "id": "VC01-E001",
                        "topic_id": "VC01",
                        "question": "Quel est le post-money ?",
                        "answer": "pas un nombre",
                        "points": 5,
                        "format": "numeric",
                        "unit": "m_eur",
                        "tolerance": 0.1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContentError):
        load_content(tmp_path)
