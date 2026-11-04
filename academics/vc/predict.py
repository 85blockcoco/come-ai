"""Deterministic prediction of likely exam questions.

The predictor does not invent questions: it ranks the existing course content
(exam bank, drills, cases) by topic exam weight and current weakness, then
returns the most representative items.  Fully offline, no AI.
"""

from __future__ import annotations

from typing import Any, Sequence

from .mastery import MasteryRecord


def predict_questions(content, radar: Sequence[MasteryRecord], *, count: int = 10) -> list[dict[str, Any]]:
    if count < 1:
        return []
    records = {r.topic_id: r for r in radar}
    weakness_factor = {"fragile": 3.0, "untested": 2.0, "developing": 1.5, "solid": 0.5}
    topics_sorted = sorted(
        content.topics,
        key=lambda t: (-(t.exam_weight * weakness_factor.get(records.get(t.id, None) and records[t.id].status, "untested")), t.order),
    )
    top_topics = {t.id for t in topics_sorted[:6]}

    candidates: list[dict[str, Any]] = []
    for question in content.exams:
        if question.topic_id in top_topics:
            candidates.append({
                "source": "exam",
                "id": question.id,
                "topic_id": question.topic_id,
                "prompt": question.question,
                "points": question.points,
                "kind": question.format,
            })
    for drill in content.drills:
        if drill.topic_id in top_topics:
            candidates.append({
                "source": "drill",
                "id": drill.id,
                "topic_id": drill.topic_id,
                "prompt": drill.prompt,
                "points": 5,
                "kind": "numeric",
            })
    for case in content.cases:
        if case.topic_id in top_topics:
            for q in case.questions:
                candidates.append({
                    "source": "case",
                    "id": f"{case.id}/{q.id}",
                    "topic_id": case.topic_id,
                    "prompt": q.prompt,
                    "points": 5,
                    "kind": "open",
                })

    # Prioritise weak topics, then by topic exam weight.
    def sort_key(item):
        rec = records.get(item["topic_id"])
        status = rec.status if rec else "untested"
        wf = weakness_factor.get(status, 1.0)
        topic = next((t for t in content.topics if t.id == item["topic_id"]), None)
        weight = topic.exam_weight if topic else 0.5
        return (-(wf * weight), item["topic_id"], item["id"])

    candidates.sort(key=sort_key)
    return candidates[:count]