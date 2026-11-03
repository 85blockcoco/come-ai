"""Final mock-exam gate: no exam before chapter mastery reaches 80%."""

from __future__ import annotations

import json
from functools import wraps
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .plan import VC_CHAPTERS
from .quiz import QuizEngine


def _quiz_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.quiz._lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class ExamGate:
    allowed: bool
    missing: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "missing": self.missing, "threshold": 0.8, "local_only": True}


class ExamEngine:
    def __init__(self, quiz: QuizEngine):
        self.quiz = quiz
        self._conn = quiz._conn
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS exam_sessions (
                exam_id TEXT PRIMARY KEY, question_ids_json TEXT NOT NULL, answers_json TEXT NOT NULL,
                started_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT ''
            )"""
        )
        self._conn.commit()

    @_quiz_locked
    def stats(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT result_json FROM exam_sessions WHERE status IN ('submitted','expired_submitted') ORDER BY rowid DESC"
        ).fetchall()
        scores: list[float] = []
        for row in rows:
            try:
                scores.append(float(json.loads(row["result_json"])["score"]))
            except (KeyError, TypeError, ValueError):
                continue
        return {
            "completed": len(scores),
            "last_score": scores[0] if scores else None,
            "best_score": max(scores) if scores else None,
            "local_only": True,
        }

    @_quiz_locked
    def gate(self, chapters: list[str] | None = None) -> ExamGate:
        selected = chapters or VC_CHAPTERS
        missing = [item for item in self.quiz.all_mastery(selected) if not item["mastered"]]
        return ExamGate(not missing, missing)

    @_quiz_locked
    def start(self, *, size: int = 5, chapters: list[str] | None = None, duration_minutes: int = 90) -> dict[str, Any]:
        if not 1 <= size <= 20:
            raise ValueError("La taille de l’examen doit être comprise entre 1 et 20.")
        if not 5 <= duration_minutes <= 180:
            raise ValueError("La durée de l’examen doit être comprise entre 5 et 180 minutes.")
        gate = self.gate(chapters)
        if not gate.allowed:
            return {"status": "blocked", "reason": "Maîtrise insuffisante : réponds aux questions d’entraînement de chaque chapitre et atteins au moins 80 % avant l’examen blanc.", "gate": gate.to_dict()}
        selected = chapters or VC_CHAPTERS
        questions: list[dict[str, Any]] = []
        # With the full five-chapter set, give valuation and returns a second
        # slot: calculation practice is central to this exam objective.
        schedule = list(selected)
        if len(selected) == 5 and size >= 6:
            schedule.insert(3, selected[2])
        for sequence in range(size):
            chapter = schedule[sequence % len(schedule)]
            question = self.quiz.next_question(chapter, difficulty="challenge", sequence=sequence)
            if question is not None:
                questions.append(question.public())
        if not questions:
            return {"status": "unavailable", "reason": "Aucune question sourcée n’est disponible pour les chapitres choisis.", "gate": gate.to_dict(), "local_only": True}
        started = datetime.now(timezone.utc)
        expires = started + timedelta(minutes=duration_minutes)
        exam_id = uuid4().hex
        self._conn.execute(
            "INSERT INTO exam_sessions(exam_id,question_ids_json,answers_json,started_at,expires_at,status) VALUES(?,?,?,?,?,?)",
            (exam_id, json.dumps([item["question_id"] for item in questions]), "{}", started.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds"), "active"),
        )
        self._conn.commit()
        return {
            "status": "ready",
            "exam_id": exam_id,
            "questions": questions,
            "gate": gate.to_dict(),
            "timer": {"duration_minutes": duration_minutes, "started_at": started.isoformat(timespec="seconds"), "expires_at": expires.isoformat(timespec="seconds")},
            "correction": "Chaque réponse est corrigée à partir de la citation locale du corpus.",
            "local_only": True,
        }

    @_quiz_locked
    def answer(self, exam_id: str, question_id: str, option_index: int) -> dict[str, Any]:
        if not isinstance(option_index, int) or option_index < 0:
            raise ValueError("Réponse d’examen invalide.")
        session = self._conn.execute("SELECT * FROM exam_sessions WHERE exam_id = ?", (exam_id,)).fetchone()
        if session is None:
            raise KeyError("Session d’examen introuvable.")
        if session["status"] != "active":
            raise ValueError("Cette session d’examen est déjà terminée.")
        if datetime.now(timezone.utc) >= datetime.fromisoformat(session["expires_at"]):
            self._conn.execute("UPDATE exam_sessions SET status='expired' WHERE exam_id=?", (exam_id,))
            self._conn.commit()
            raise ValueError("Le temps imparti est écoulé.")
        question_ids = json.loads(session["question_ids_json"])
        if question_id not in question_ids:
            raise ValueError("Cette question n’appartient pas à cette session.")
        question = self._conn.execute("SELECT options_json FROM quiz_questions WHERE question_id=?", (question_id,)).fetchone()
        if question is None or option_index >= len(json.loads(question["options_json"])):
            raise ValueError("Réponse d’examen invalide.")
        answers = json.loads(session["answers_json"])
        answers[question_id] = option_index
        self._conn.execute("UPDATE exam_sessions SET answers_json=? WHERE exam_id=?", (json.dumps(answers), exam_id))
        self._conn.commit()
        return {"exam_id": exam_id, "question_id": question_id, "saved": True, "answered": len(answers), "total": len(question_ids), "local_only": True}

    @_quiz_locked
    def submit(self, exam_id: str) -> dict[str, Any]:
        session = self._conn.execute("SELECT * FROM exam_sessions WHERE exam_id = ?", (exam_id,)).fetchone()
        if session is None:
            raise KeyError("Session d’examen introuvable.")
        if session["status"] in {"submitted", "expired_submitted"}:
            return json.loads(session["result_json"])
        if session["status"] not in {"active", "expired"}:
            raise ValueError("Cette session d’examen ne peut pas être corrigée.")
        now = datetime.now(timezone.utc)
        timed_out = session["status"] == "expired" or now >= datetime.fromisoformat(session["expires_at"])
        question_ids = json.loads(session["question_ids_json"])
        answers = json.loads(session["answers_json"])
        corrections: list[dict[str, Any]] = []
        correct_count = 0
        db = self._conn
        try:
            db.execute("BEGIN IMMEDIATE")
            for question_id in question_ids:
                row = db.execute("SELECT * FROM quiz_questions WHERE question_id=?", (question_id,)).fetchone()
                if row is None:
                    raise KeyError("Question de l’examen absente de la base locale.")
                options = json.loads(row["options_json"])
                correct_index = int(row["correct_index"])
                selected_index = answers.get(question_id)
                is_correct = selected_index == correct_index
                correct_count += int(is_correct)
                if selected_index is not None:
                    db.execute("INSERT INTO quiz_attempts(question_id,chapter,correct,difficulty) VALUES(?,?,?,?)", (question_id, row["chapter"], int(is_correct), row["difficulty"]))
                corrections.append({
                    "question_id": question_id,
                    "chapter": row["chapter"],
                    "prompt": row["prompt"],
                    "selected_answer": options[selected_index] if selected_index is not None else None,
                    "correct_answer": options[correct_index],
                    "correct": is_correct,
                    "explanation": row["explanation"],
                    "citation": json.loads(row["citation_json"]),
                })
            total = len(question_ids)
            result = {
                "exam_id": exam_id,
                "status": "timed_out" if timed_out else "submitted",
                "score": round(correct_count / total, 4) if total else 0.0,
                "correct": correct_count,
                "total": total,
                "answered": len(answers),
                "remediation": sorted({item["chapter"] for item in corrections if not item["correct"]}),
                "corrections": corrections,
                "local_only": True,
            }
            status = "expired_submitted" if timed_out else "submitted"
            db.execute("UPDATE exam_sessions SET status=?,result_json=? WHERE exam_id=?", (status, json.dumps(result, ensure_ascii=False), exam_id))
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise


__all__ = ["ExamEngine", "ExamGate"]
