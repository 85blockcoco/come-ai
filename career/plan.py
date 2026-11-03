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
    # QuizEngine canonicalizes ``TOPIC N`` and the long display labels used by
    # the mastery brief to the same persisted notion key.
    mastery = {chapter: quiz.mastery(chapter) for chapter in VC_CHAPTERS}
    pending = [chapter for chapter in PRIORITY_ORDER if not mastery[chapter]["mastered"]]
    mastered = [chapter for chapter in PRIORITY_ORDER if mastery[chapter]["mastered"]]
    planned_chapters = pending + mastered
    days = (end - start).days + 1
    sessions: list[dict[str, Any]] = []
    schedule: list[list[str]] = [[] for _ in range(days)]
    span = max(1, days - 1)
    last_index = max(0, len(planned_chapters) - 1)
    for position, chapter in enumerate(planned_chapters):
        day_index = round(position * span / last_index) if last_index else 0
        schedule[min(days - 1, day_index)].append(chapter)
    exam_ready = all(mastery[chapter]["mastered"] for chapter in VC_CHAPTERS)
    for index, chapters_for_day in enumerate(schedule):
        day = start + timedelta(days=index)
        for chapter in chapters_for_day:
            status = mastery[chapter]
            activities = ["lire la fiche sourcée", "réviser les cartes dues", "faire un quiz progressif et corriger ses erreurs"]
            if index == days - 1:
                activities.append(
                    "examen blanc chronométré (6 questions, 30 min)"
                    if exam_ready
                    else "révision ciblée des chapitres faibles; examen blanc uniquement quand tous les chapitres atteignent les critères"
                )
            sessions.append({
                "date": day.isoformat(),
                "chapter": chapter,
                "phase": "guided_learning" if status["attempts"] == 0 else "consolidation" if not status["mastered"] else "exam_preparation",
                "mastery": status,
                "activities": activities,
            })
    return {"start": start.isoformat(), "until": end.isoformat(), "sessions": sessions, "chapters": list(mastery.values()), "local_only": True}


__all__ = ["PRIORITY_ORDER", "VC_CHAPTERS", "build_plan"]
