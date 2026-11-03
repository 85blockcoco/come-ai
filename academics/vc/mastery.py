"""Weakness radar and minute-bounded study plan."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Mapping, Sequence

from .dates import parse_date
from .errors import ContentError
from .models import CardProgress, CaseAttempt, MasteryRecord, ReviewEvent, StudyPlan


def _status(attempts: int, accuracy: float | None) -> str:
    if attempts == 0 or accuracy is None:
        return "untested"
    if attempts >= 3 and accuracy < 0.6:
        return "fragile"
    if accuracy < 0.8:
        return "developing"
    return "solid"


def mastery_radar(
    content,
    reviews: Sequence[ReviewEvent],
    *,
    today: str,
    case_attempts: Sequence[CaseAttempt] = (),
    exam_results: Sequence[dict[str, Any]] = (),
    progress: Mapping[str, CardProgress] | None = None,
) -> list[MasteryRecord]:
    parse_date(today)
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"attempts": 0, "correct": 0, "last": "", "errors": defaultdict(int)}
    )
    for event in reviews:
        if not event.topic_id:
            continue
        bucket = stats[event.topic_id]
        bucket["attempts"] += 1
        bucket["correct"] += 1 if event.correct else 0
        bucket["last"] = max(bucket["last"], event.reviewed_at[:10])
        if not event.correct:
            bucket["errors"]["rappel"] += 1
    for attempt in case_attempts:
        try:
            case = content.case(attempt.case_id)
        except ContentError:
            continue
        bucket = stats[case.topic_id]
        bucket["attempts"] += 1
        bucket["correct"] += 1 if attempt.score >= 0.6 else 0
        bucket["last"] = max(bucket["last"], attempt.submitted_at[:10])
        if attempt.score < 0.6:
            bucket["errors"]["cas"] += 1
    for result in exam_results:
        per_topic = result.get("per_topic") if isinstance(result, dict) else None
        if not isinstance(per_topic, dict):
            continue
        for topic_id, value in per_topic.items():
            bucket = stats[topic_id]
            if isinstance(value, dict):
                attempts = int(value.get("attempts", 0))
                correct = int(value.get("correct", 0))
            else:
                attempts = 1
                correct = 1 if float(value) >= 0.6 else 0
            bucket["attempts"] += attempts
            bucket["correct"] += correct
            bucket["last"] = max(bucket["last"], str(result.get("submitted_at", ""))[:10])
            if attempts and correct / attempts < 0.6:
                bucket["errors"]["examen"] += 1

    card_topic = {card.id: card.topic_id for card in content.cards}
    due_by_topic: dict[str, int] = defaultdict(int)
    if progress:
        for card_id, item in progress.items():
            if item.suspended or not item.due_date or item.due_date > today:
                continue
            topic_id = card_topic.get(card_id)
            if topic_id:
                due_by_topic[topic_id] += 1

    records: list[MasteryRecord] = []
    for topic in content.topics:
        bucket = stats.get(topic.id)
        attempts = int(bucket["attempts"]) if bucket else 0
        correct = int(bucket["correct"]) if bucket else 0
        accuracy = round(correct / attempts, 4) if attempts else None
        errors = (
            [name for name, _ in sorted(bucket["errors"].items(), key=lambda item: (-item[1], item[0]))]
            if bucket
            else []
        )
        records.append(
            MasteryRecord(
                topic_id=topic.id,
                title=topic.title_fr,
                attempts=attempts,
                correct=correct,
                accuracy=accuracy,
                last_activity=bucket["last"] if bucket else "",
                status=_status(attempts, accuracy),
                due_cards=due_by_topic.get(topic.id, 0),
                top_errors=errors,
            )
        )
    return records


def build_study_plan(
    content,
    radar: Sequence[MasteryRecord],
    *,
    minutes: int,
    today: str,
    exam_date: str | None = None,
) -> StudyPlan:
    if minutes <= 0:
        return StudyPlan(date=today, capacity_minutes=0, activities=[], total_minutes=0, exam_date=exam_date)
    parse_date(today)
    urgency = 1.0
    if exam_date:
        parse_date(exam_date)
        days_left = max(0, (date.fromisoformat(exam_date) - date.fromisoformat(today)).days)
        urgency = 1.0 + max(0, 30 - days_left) / 30.0

    order = {topic.id: topic.order for topic in content.topics}
    weights = {topic.id: topic.exam_weight for topic in content.topics}
    candidates: list[dict[str, Any]] = []
    for record in radar:
        if record.topic_id not in order:
            continue
        weakness = {"fragile": 3.0, "untested": 2.0, "developing": 1.5, "solid": 0.0}.get(
            record.status, 0.0
        )
        due_score = min(2.0, record.due_cards * 0.25)
        base = urgency * weights.get(record.topic_id, 0.5) + weakness + due_score
        if record.due_cards:
            candidates.append(
                {
                    "kind": "review",
                    "ref_id": record.topic_id,
                    "topic_id": record.topic_id,
                    "minutes": min(20, max(5, record.due_cards * 2)),
                    "reason": f"{record.due_cards} carte(s) due(s)",
                    "priority": base,
                }
            )
        elif record.status == "untested":
            candidates.append(
                {
                    "kind": "review",
                    "ref_id": record.topic_id,
                    "topic_id": record.topic_id,
                    "minutes": 10,
                    "reason": "topic non testé",
                    "priority": base,
                }
            )
        if record.status == "fragile":
            candidates.append(
                {
                    "kind": "drill",
                    "ref_id": record.topic_id,
                    "topic_id": record.topic_id,
                    "minutes": 10,
                    "reason": f"taux de réussite {record.accuracy:.0%}",
                    "priority": base + 0.5,
                }
            )
            candidates.append(
                {
                    "kind": "case",
                    "ref_id": record.topic_id,
                    "topic_id": record.topic_id,
                    "minutes": 15,
                    "reason": "cas recommandé après un topic fragile",
                    "priority": base + 0.25,
                }
            )
        elif record.status == "developing":
            candidates.append(
                {
                    "kind": "drill",
                    "ref_id": record.topic_id,
                    "topic_id": record.topic_id,
                    "minutes": 10,
                    "reason": f"taux de réussite {record.accuracy:.0%}",
                    "priority": base,
                }
            )
    candidates.sort(
        key=lambda item: (-item["priority"], order.get(item["topic_id"], 999), item["kind"])
    )
    activities: list[dict[str, Any]] = []
    total = 0
    for candidate in candidates:
        remaining = minutes - total
        if remaining <= 0:
            break
        if candidate["minutes"] > remaining:
            if remaining >= 5:
                candidate = {**candidate, "minutes": remaining}
            else:
                continue
        activities.append(
            {
                "kind": candidate["kind"],
                "ref_id": candidate["ref_id"],
                "topic_id": candidate["topic_id"],
                "minutes": candidate["minutes"],
                "reason": candidate["reason"],
            }
        )
        total += candidate["minutes"]
    return StudyPlan(
        date=today,
        capacity_minutes=minutes,
        activities=activities,
        total_minutes=total,
        exam_date=exam_date,
    )


def coverage_summary(records: Sequence[MasteryRecord]) -> dict[str, Any]:
    """Summarize seen vs untested topics from mastery records."""
    total = len(records)
    covered = [record.topic_id for record in records if record.attempts > 0]
    untested = [record.topic_id for record in records if record.attempts == 0]
    return {
        "total_topics": total,
        "covered_topics": len(covered),
        "ratio": round(len(covered) / total, 4) if total else 0.0,
        "covered": covered,
        "untested": untested,
    }


def radar_payload(records: Sequence[MasteryRecord], *, generated_at: str) -> dict[str, Any]:
    return {
        "topics": [record.to_dict() for record in records],
        "untested": [record.topic_id for record in records if record.status == "untested"],
        "generated_at": generated_at,
    }
