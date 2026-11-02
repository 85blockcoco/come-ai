"""Examens blancs VC déterministes, reprenables et sans corrigé prématuré."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExamQuestion:
    id: str
    topic: str
    prompt: str
    answer: str
    points: int


@dataclass(frozen=True)
class MockExam:
    id: str
    duration_minutes: int
    questions: tuple[ExamQuestion, ...]


@dataclass(frozen=True)
class ExamResult:
    exam_id: str
    score: int
    max_score: int
    answered: int
    timed_out: bool
    weak_topics: tuple[str, ...]
    details: tuple[dict[str, Any], ...]


def build_mock_exam(*, exam_id: str = "vc-mock-001", limit: int = 20) -> MockExam:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("Un examen doit contenir entre 1 et 100 questions.")
    bank = (
        ExamQuestion("q-pm", "valuation", "Pre-money 8 et investissement 2 : post-money ?", "10", 2),
        ExamQuestion("q-moic", "returns", "Distributions 30 sur paid-in 10 : MOIC ?", "3", 2),
        ExamQuestion("q-dilution", "cap-table", "Une part 80 % subit une nouvelle émission de 20 % : part ?", "64", 2),
        ExamQuestion("q-term", "term-sheet", "Que signifie 1x non participating ?", "preference", 2),
        ExamQuestion("q-unknown", "method", "Que faire si une convention du cours manque ?", "inconnu", 2),
    )
    questions = tuple(
        ExamQuestion(
            id=bank[index % len(bank)].id if index < len(bank) else f"{bank[index % len(bank)].id}-{index + 1}",
            topic=bank[index % len(bank)].topic,
            prompt=bank[index % len(bank)].prompt,
            answer=bank[index % len(bank)].answer,
            points=bank[index % len(bank)].points,
        )
        for index in range(limit)
    )
    return MockExam(exam_id, 30, questions)


def grade_mock_exam(exam: MockExam, answers: dict[str, str], *, elapsed_minutes: int = 0) -> ExamResult:
    if elapsed_minutes < 0:
        raise ValueError("Le temps écoulé ne peut pas être négatif.")
    timed_out = elapsed_minutes >= exam.duration_minutes
    details: list[dict[str, Any]] = []
    scores_by_topic: dict[str, list[int]] = {}
    score = 0
    for question in exam.questions:
        answer = str(answers.get(question.id, "")).strip().casefold()
        expected = question.answer.casefold()
        correct = bool(answer) and (expected in answer or (expected == "64" and answer in {"0.64", "64%"}))
        points = question.points if correct else 0
        score += points
        scores_by_topic.setdefault(question.topic, []).append(points)
        details.append({"question_id": question.id, "topic": question.topic, "points": points,
                        "max_points": question.points, "answered": bool(answer), "revealed": False})
    weak_topics = tuple(sorted(topic for topic, values in scores_by_topic.items() if sum(values) < len(values) * 2))
    return ExamResult(exam.id, score, sum(question.points for question in exam.questions),
                      sum(1 for question in exam.questions if str(answers.get(question.id, "")).strip()),
                      timed_out, weak_topics, tuple(details))
