"""Progressive, corpus-derived quiz questions and chapter mastery."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .ingest import CorpusIndex


@dataclass(frozen=True)
class QuizQuestion:
    question_id: str
    chapter: str
    prompt: str
    options: list[str]
    correct_index: int
    difficulty: str
    citation: dict[str, Any]

    def public(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("correct_index")
        return payload


class QuizEngine:
    def __init__(self, index: CorpusIndex, db_path: str | Path):
        self.index = index
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, question_id TEXT NOT NULL, chapter TEXT NOT NULL,
                correct INTEGER NOT NULL, difficulty TEXT NOT NULL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS quiz_questions (
                question_id TEXT PRIMARY KEY, chapter TEXT NOT NULL, prompt TEXT NOT NULL, options_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL, difficulty TEXT NOT NULL, citation_json TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _mastery_row(self, chapter: str) -> tuple[int, int]:
        chapter = self._canonical_chapter(chapter)
        row = self._conn.execute("SELECT COUNT(*) total, SUM(correct) correct FROM quiz_attempts WHERE chapter = ?", (chapter,)).fetchone()
        return int(row["total"] or 0), int(row["correct"] or 0)

    def mastery(self, chapter: str) -> dict[str, Any]:
        chapter = self._canonical_chapter(chapter)
        total, correct = self._mastery_row(chapter)
        return {"chapter": chapter, "attempts": total, "correct": correct, "score": round(correct / total, 4) if total else 0.0, "mastered": bool(total and correct / total >= 0.8)}

    def difficulty(self, chapter: str) -> str:
        score = self.mastery(chapter)["score"]
        return "foundation" if score < 0.5 else "consolidation" if score < 0.8 else "challenge"

    @staticmethod
    def _answer_sentence(text: str) -> str:
        value = re.split(r"(?<=[.!?])\s+|\n+", text.strip())[0].strip()
        return value[:600]

    @staticmethod
    def _canonical_chapter(chapter: str) -> str:
        match = re.match(r"^\s*topic\s*(\d+)\b", str(chapter), re.IGNORECASE)
        return f"TOPIC {match.group(1)}" if match else str(chapter).strip()

    def next_question(self, chapter: str, *, difficulty: str | None = None) -> QuizQuestion | None:
        chapter = self._canonical_chapter(str(chapter or "").strip())
        if not chapter:
            return None
        chosen_difficulty = difficulty or self.difficulty(chapter)
        section_hits = self.index.search(chapter, limit=8, section=chapter)
        if chapter.lower().startswith(("topic ", "chapter ", "section ")) and not section_hits:
            return None
        chunks = self.index.search(chapter, limit=8)
        if not chunks:
            return None
        attempts = self._conn.execute("SELECT COUNT(*) FROM quiz_attempts WHERE chapter = ?", (chapter,)).fetchone()[0]
        chunk = chunks[int(attempts) % len(chunks)]
        answer = self._answer_sentence(chunk.text)
        distractors = [self._answer_sentence(item.text) for item in chunks if item.chunk_id != chunk.chunk_id]
        options = [answer] + [item for item in distractors if item and item != answer][:2]
        while len(options) < 3:
            options.append("Cet élément n’est pas explicitement établi par l’extrait consulté.")
        digest = hashlib.sha256(f"{chapter}:{chunk.chunk_id}:{attempts}:{chosen_difficulty}".encode()).hexdigest()[:24]
        # Deterministic rotation keeps tests and offline sessions reproducible while
        # preventing the correct answer from always being displayed first.
        offset = int(digest[:2], 16) % len(options)
        rotated = options[offset:] + options[:offset]
        question = QuizQuestion(digest, chapter, f"Quel énoncé est directement soutenu par le cours pour « {chapter} » ?", rotated, rotated.index(answer), chosen_difficulty, chunk.citation())
        self._conn.execute("INSERT OR REPLACE INTO quiz_questions(question_id,chapter,prompt,options_json,correct_index,difficulty,citation_json) VALUES(?,?,?,?,?,?,?)", (question.question_id, question.chapter, question.prompt, json.dumps(question.options, ensure_ascii=False), question.correct_index, question.difficulty, json.dumps(question.citation, ensure_ascii=False)))
        self._conn.commit()
        return question

    def answer(self, question_id: str, option_index: int) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM quiz_questions WHERE question_id = ?", (question_id,)).fetchone()
        if row is None:
            raise KeyError("Question de quiz introuvable dans la session locale.")
        options = json.loads(row["options_json"])
        if not isinstance(option_index, int) or not 0 <= option_index < len(options):
            raise ValueError("Réponse de quiz invalide.")
        correct = option_index == int(row["correct_index"])
        self._conn.execute("INSERT INTO quiz_attempts(question_id,chapter,correct,difficulty) VALUES(?,?,?,?)", (question_id, row["chapter"], int(correct), row["difficulty"]))
        self._conn.commit()
        return {"question_id": question_id, "correct": correct, "feedback": "Bonne réponse : elle est soutenue par l’extrait cité." if correct else "Réponse non soutenue par l’extrait cité ; relis la citation avant de réessayer.", "citation": json.loads(row["citation_json"]), "mastery": self.mastery(row["chapter"]), "local_only": True}

    def all_mastery(self, chapters: list[str]) -> list[dict[str, Any]]:
        return [self.mastery(chapter) for chapter in chapters]

    def dashboard(self, chapters: list[str]) -> dict[str, Any]:
        notions = self.all_mastery(chapters)
        weak_points = sorted(
            (item for item in notions if not item["mastered"]),
            key=lambda item: (item["score"], item["attempts"], item["chapter"]),
        )
        return {
            "notions": notions,
            "weak_points": weak_points,
            "mastered_count": sum(1 for item in notions if item["mastered"]),
            "total_count": len(notions),
            "overall_score": round(sum(item["score"] for item in notions) / len(notions), 4) if notions else 0.0,
            "local_only": True,
        }


__all__ = ["QuizEngine", "QuizQuestion"]
