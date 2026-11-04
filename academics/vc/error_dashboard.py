"""Deterministic error dashboard for the VC revision coach."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence


def error_dashboard(
    content,
    *,
    reviews: Sequence[Any] = (),
    case_attempts: Sequence[Any] = (),
    drill_attempts: Sequence[Any] = (),
    exam_results: Sequence[Any] = (),
    paper_attempts: Sequence[Any] = (),
) -> dict[str, Any]:
    categories: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for event in reviews:
        if getattr(event, "correct", True):
            continue
        topic_id = getattr(event, "topic_id", "") or ""
        if topic_id:
            categories["recall"][topic_id] += 1

    for attempt in case_attempts:
        try:
            case = content.case(attempt.case_id)
        except Exception:
            continue
        for criterion in getattr(attempt, "criteria_results", []) or []:
            if criterion.get("matched"):
                continue
            categories["case"][case.topic_id] += 1
        for _ in getattr(attempt, "unsupported_numbers", []) or []:
            categories["unsupported_number"][case.topic_id] += 1

    for attempt in drill_attempts:
        try:
            drill = content.drill(attempt.drill_id)
        except Exception:
            continue
        if getattr(attempt, "accepted", True):
            continue
        category = getattr(attempt, "diagnostic", None) or "formula"
        categories[category][drill.topic_id] += 1

    for result in exam_results:
        per_topic = result.get("per_topic") if isinstance(result, dict) else None
        if not isinstance(per_topic, dict):
            continue
        for topic_id, value in per_topic.items():
            if not isinstance(value, dict):
                continue
            maximum = float(value.get("max", 0) or 0)
            earned = float(value.get("earned", 0) or 0)
            if maximum and earned / maximum < 0.6:
                categories["exam"][topic_id] += 1

    for attempt in paper_attempts:
        per_topic = getattr(attempt, "per_topic", None)
        if not isinstance(per_topic, dict):
            continue
        for topic_id, value in per_topic.items():
            if not isinstance(value, dict):
                continue
            attempts = int(value.get("attempts", 0) or 0)
            correct = int(value.get("correct", 0) or 0)
            if attempts and correct / attempts < 0.6:
                categories["paper"][topic_id] += 1

    category_totals = {cat: sum(topics.values()) for cat, topics in categories.items()}
    sorted_categories = sorted(category_totals.items(), key=lambda item: (-item[1], item[0]))

    topic_totals: dict[str, int] = defaultdict(int)
    for topics in categories.values():
        for topic_id, count in topics.items():
            topic_totals[topic_id] += count

    sorted_topics = sorted(topic_totals.items(), key=lambda item: (-item[1], item[0]))

    return {
        "total_errors": sum(category_totals.values()),
        "categories": [
            {"category": cat, "count": count, "topics": dict(categories[cat])}
            for cat, count in sorted_categories
        ],
        "topics": [{"topic_id": tid, "errors": count} for tid, count in sorted_topics],
    }