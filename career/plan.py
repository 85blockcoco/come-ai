"""Revision plan derived from observed quiz mastery, never from invented scores."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .quiz import QuizEngine

VC_CHAPTERS = [
    "TOPIC 1 — Introduction au VC et écosystème",
    "TOPIC 2 — Évaluation des startups",
    "TOPIC 3 — Valorisation, ownership, returns",
    "TOPIC 4 — Term sheets, structuring, négociation",
    "TOPIC 5 — Gouvernance, monitoring, exits",
]
PRIORITY_ORDER = [VC_CHAPTERS[2], VC_CHAPTERS[3], VC_CHAPTERS[4], VC_CHAPTERS[1], VC_CHAPTERS[0]]


def build_plan(quiz: QuizEngine, *, today: date | None = None, until: date | None = None) -> dict[str, Any]:
    start = today or date.today()
    end = until or start + timedelta(days=max(0, 4 - start.weekday()))
    if end < start:
        end = start
    mastery = {item["chapter"]: item for item in quiz.all_mastery(VC_CHAPTERS)}
    pending = [chapter for chapter in PRIORITY_ORDER if not mastery[chapter]["mastered"]]
    days = (end - start).days + 1
    sessions: list[dict[str, Any]] = []
    for index in range(days):
        day = start + timedelta(days=index)
        chapter = pending[index % len(pending)] if pending else PRIORITY_ORDER[index % len(PRIORITY_ORDER)]
        status = mastery[chapter]
        sessions.append({
            "date": day.isoformat(),
            "chapter": chapter,
            "phase": "guided_learning" if status["attempts"] == 0 else "consolidation" if not status["mastered"] else "exam_preparation",
            "mastery": status,
            "activities": ["lire la fiche sourcée", "réviser les cartes dues", "faire un quiz progressif"],
        })
    return {"start": start.isoformat(), "until": end.isoformat(), "sessions": sessions, "chapters": list(mastery.values()), "local_only": True}


__all__ = ["PRIORITY_ORDER", "VC_CHAPTERS", "build_plan"]
