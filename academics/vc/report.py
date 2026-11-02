"""Rapport de progression VC recalculable depuis les résultats locaux."""

from __future__ import annotations

from typing import Any


def progress_report(*, radar: list[dict[str, Any]], sessions: list[dict[str, Any]], exams: list[dict[str, Any]]) -> dict[str, Any]:
    tested = [item for item in radar if item.get("status") != "non testé"]
    mastered = [item for item in radar if item.get("status") == "solide"]
    return {
        "topics": {"total": len(radar), "tested": len(tested), "mastered": len(mastered),
                   "untested": len(radar) - len(tested)},
        "sessions": {"count": len(sessions), "answered": sum(int(item.get("answered", 0)) for item in sessions)},
        "exams": {"count": len(exams), "scores": [item.get("score", 0) for item in exams]},
        "weak_topics": [item["topic"] for item in radar if item.get("status") == "fragile"],
        "honesty": "non testé reste non testé",
    }
