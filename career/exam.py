"""Final mock-exam gate: no exam before chapter mastery reaches 80%."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any

from .plan import VC_CHAPTERS
from .quiz import QuizEngine


@dataclass(frozen=True)
class ExamGate:
    allowed: bool
    missing: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "missing": self.missing, "threshold": 0.8, "local_only": True}


class ExamEngine:
    def __init__(self, quiz: QuizEngine):
        self.quiz = quiz

    def gate(self, chapters: list[str] | None = None) -> ExamGate:
        selected = chapters or VC_CHAPTERS
        missing = [item for item in self.quiz.all_mastery(selected) if not item["mastered"]]
        return ExamGate(not missing, missing)

    def start(self, *, size: int = 5, chapters: list[str] | None = None, duration_minutes: int = 90) -> dict[str, Any]:
        if not 1 <= size <= 20:
            raise ValueError("La taille de l’examen doit être comprise entre 1 et 20.")
        if not 5 <= duration_minutes <= 180:
            raise ValueError("La durée de l’examen doit être comprise entre 5 et 180 minutes.")
        gate = self.gate(chapters)
        if not gate.allowed:
            return {"status": "blocked", "reason": "Maîtrise insuffisante : consolide chaque chapitre à au moins 80% avant l’examen blanc.", "gate": gate.to_dict()}
        selected = chapters or VC_CHAPTERS
        questions: list[dict[str, Any]] = []
        for chapter in selected:
            question = self.quiz.next_question(chapter, difficulty="challenge")
            if question is not None:
                questions.append(question.public())
            if len(questions) >= size:
                break
        started = datetime.now(timezone.utc)
        return {
            "status": "ready",
            "exam_id": hashlib.sha256("|".join(item["question_id"] for item in questions).encode()).hexdigest()[:24],
            "questions": questions,
            "gate": gate.to_dict(),
            "timer": {"duration_minutes": duration_minutes, "started_at": started.isoformat(timespec="seconds"), "expires_at": (started + timedelta(minutes=duration_minutes)).isoformat(timespec="seconds")},
            "correction": "Chaque réponse est corrigée à partir de la citation locale du corpus.",
            "local_only": True,
        }

    def answer(self, question_id: str, option_index: int) -> dict[str, Any]:
        result = self.quiz.answer(question_id, option_index)
        result["detailed_correction"] = result.get("feedback", "") + " Consulte la citation fournie pour vérifier le raisonnement."
        return result


__all__ = ["ExamEngine", "ExamGate"]
