"""Local flashcards with a small SM-2 scheduler."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ingest import CorpusIndex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass(frozen=True)
class Flashcard:
    card_id: str
    chapter: str
    question: str
    answer: str
    source: dict[str, Any]
    due_at: str
    repetitions: int
    interval_days: int
    ease_factor: float
    last_quality: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SRSStore:
    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS flashcards (
                card_id TEXT PRIMARY KEY, chapter TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
                source_json TEXT NOT NULL, due_at TEXT NOT NULL, repetitions INTEGER NOT NULL DEFAULT 0,
                interval_days INTEGER NOT NULL DEFAULT 0, ease_factor REAL NOT NULL DEFAULT 2.5, last_quality INTEGER
            )"""
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> Flashcard:
        import json

        return Flashcard(row["card_id"], row["chapter"], row["question"], row["answer"], json.loads(row["source_json"]), row["due_at"], int(row["repetitions"]), int(row["interval_days"]), float(row["ease_factor"]), row["last_quality"])

    def generate(self, index: CorpusIndex, *, chapter: str | None = None, limit: int = 40) -> list[Flashcard]:
        import json

        chunks = index.search(chapter or "venture capital startup valuation term sheet governance", limit=min(limit, 20), section=chapter)
        created: list[Flashcard] = []
        for chunk in chunks:
            sentence = re.split(r"(?<=[.!?])\s+|\n+", chunk.text.strip())[0].strip()
            if len(sentence) < 25:
                sentence = chunk.text[:500].strip()
            card_id = hashlib.sha256(f"{chunk.chunk_id}:card".encode()).hexdigest()[:24]
            question = f"Que faut-il retenir de la section « {chunk.section} » (p.{chunk.page_start}) ?"
            self._conn.execute(
                "INSERT OR IGNORE INTO flashcards(card_id,chapter,question,answer,source_json,due_at) VALUES(?,?,?,?,?,?)",
                (card_id, chunk.section, question, sentence, json.dumps(chunk.citation(), ensure_ascii=False), _iso(_now())),
            )
            row = self._conn.execute("SELECT * FROM flashcards WHERE card_id = ?", (card_id,)).fetchone()
            if row is not None:
                created.append(self._row(row))
        self._conn.commit()
        return created

    def due(self, *, now: datetime | None = None, limit: int = 20, chapter: str | None = None) -> list[Flashcard]:
        current = _iso(now or _now())
        sql = "SELECT * FROM flashcards WHERE due_at <= ?"
        params: list[Any] = [current]
        if chapter:
            sql += " AND chapter = ?"
            params.append(chapter)
        sql += " ORDER BY due_at, card_id LIMIT ?"
        params.append(max(1, min(limit, 100)))
        return [self._row(row) for row in self._conn.execute(sql, params).fetchall()]

    def get(self, card_id: str) -> Flashcard | None:
        row = self._conn.execute("SELECT * FROM flashcards WHERE card_id = ?", (card_id,)).fetchone()
        return self._row(row) if row else None

    def review(self, card_id: str, quality: int) -> Flashcard:
        if not 0 <= quality <= 5:
            raise ValueError("La qualité SRS doit être comprise entre 0 et 5.")
        card = self.get(card_id)
        if card is None:
            raise KeyError("Carte SRS introuvable dans le corpus local.")
        repetitions = card.repetitions
        if quality < 3:
            repetitions = 0
            interval = 1
        else:
            repetitions += 1
            interval = 1 if repetitions == 1 else 6 if repetitions == 2 else max(1, round(card.interval_days * card.ease_factor))
        ease = max(1.3, card.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
        due_at = _iso(_now() + timedelta(days=interval))
        self._conn.execute("UPDATE flashcards SET due_at=?, repetitions=?, interval_days=?, ease_factor=?, last_quality=? WHERE card_id=?", (due_at, repetitions, interval, round(ease, 4), quality, card_id))
        self._conn.commit()
        return self.get(card_id)  # type: ignore[return-value]

    def stats(self) -> dict[str, int]:
        row = self._conn.execute("SELECT COUNT(*) total, SUM(CASE WHEN due_at <= ? THEN 1 ELSE 0 END) due FROM flashcards", (_iso(_now()),)).fetchone()
        return {"total": int(row["total"] or 0), "due": int(row["due"] or 0)}


__all__ = ["Flashcard", "SRSStore"]
