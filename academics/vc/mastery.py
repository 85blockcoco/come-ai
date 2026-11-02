"""Radar de maîtrise VC et plan de révision borné."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import Card


def build_radar(cards: list[Card], reviews: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    topics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        if card.approved:
            topics[card.topic].append(reviews.get(card.id, {}))
    result = []
    for topic in sorted(topics):
        entries = [entry for entry in topics[topic] if entry]
        if not entries:
            result.append({"topic": topic, "status": "non testé", "mastery": None, "reviews": 0})
            continue
        average = sum(int(entry.get("quality", 0)) for entry in entries) / (len(entries) * 5)
        status = "fragile" if average < 0.6 else "en cours" if average < 0.8 else "solide"
        result.append({"topic": topic, "status": status, "mastery": round(average, 3), "reviews": len(entries)})
    return result


def build_study_plan(radar: list[dict[str, Any]], *, capacity_minutes: int = 60) -> dict[str, Any]:
    if isinstance(capacity_minutes, bool) or not isinstance(capacity_minutes, int) or not 1 <= capacity_minutes <= 480:
        raise ValueError("La capacité de révision doit être comprise entre 1 et 480 minutes.")
    ranked = sorted(radar, key=lambda item: (item.get("mastery") is not None, item.get("mastery") or 0, item.get("topic", "")))
    selected = []
    remaining = capacity_minutes
    for item in ranked:
        if remaining < 15:
            break
        minutes = 20 if item.get("status") == "fragile" else 15
        if minutes <= remaining:
            selected.append({"topic": item["topic"], "status": item["status"], "minutes": minutes})
            remaining -= minutes
    return {"capacity_minutes": capacity_minutes, "planned_minutes": capacity_minutes - remaining,
            "remaining_minutes": remaining, "items": selected}
