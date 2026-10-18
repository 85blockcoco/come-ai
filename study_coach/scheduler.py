"""Simple spaced repetition driven by the answer history.

The mechanism is deliberately a ladder of intervals, not a model of the
learner's ability:

* a correct answer moves the item one rung up (1, 3, 7, 14, 30, 60 days);
* a partial answer keeps the item where it is;
* an incorrect answer sends it back to the first rung and counts a lapse;
* a non-evaluable answer changes nothing -- no data, no schedule change.

Pure functions only: the same history always produces the same plan, which keeps
the behaviour auditable and testable offline.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from .models import SCHEDULE_VERSION, ScheduleEntry, clean_text, utc_now

INTERVALS_DAYS = (0, 1, 3, 7, 14, 30, 60)
MIN_EASE = 1.3
MAX_EASE = 2.8
EASE_STEP_UP = 0.1
EASE_STEP_DOWN = 0.2


def _clamp_ease(value: float) -> float:
    return round(max(MIN_EASE, min(MAX_EASE, value)), 3)


def _clamp_rung(value: int) -> int:
    return max(0, min(int(value), len(INTERVALS_DAYS) - 1))


def interval_days(rung: int) -> int:
    return INTERVALS_DAYS[_clamp_rung(rung)]


def update_entry(entry: ScheduleEntry, status: str, *, today: date | None = None) -> ScheduleEntry:
    """Return the new schedule entry after one graded answer."""

    reference = today or date.today()
    updated = ScheduleEntry.from_dict(entry.to_dict())
    updated.updated_at = utc_now()
    updated.last_status = clean_text(status, limit=32)

    if status == "correct":
        updated.rung = _clamp_rung(entry.rung + 1)
        updated.ease = _clamp_ease(entry.ease + EASE_STEP_UP)
        updated.streak = entry.streak + 1
    elif status == "partiel":
        updated.rung = _clamp_rung(entry.rung)
        updated.streak = 0
    elif status == "incorrect":
        updated.rung = 0
        updated.ease = _clamp_ease(entry.ease - EASE_STEP_DOWN)
        updated.streak = 0
        updated.lapses = entry.lapses + 1
    else:
        # "non_evaluable" (or anything unknown): no evidence, no schedule move.
        updated.rung = entry.rung
        updated.due_at = entry.due_at
        return updated

    updated.due_at = (reference + timedelta(days=interval_days(updated.rung))).isoformat()
    return updated


def new_entry(item_key: str, *, kind: str = "notion", today: date | None = None) -> ScheduleEntry:
    """A brand-new item is due today."""

    reference = today or date.today()
    return ScheduleEntry(
        item_key=item_key,
        kind=kind,
        rung=0,
        ease=2.5,
        due_at=reference.isoformat(),
        streak=0,
        lapses=0,
        last_status="",
        updated_at=utc_now(),
    )


def days_overdue(entry: ScheduleEntry, *, today: date | None = None) -> int:
    reference = today or date.today()
    try:
        due = date.fromisoformat(str(entry.due_at)[:10])
    except ValueError:
        return 0
    return max(0, (reference - due).days)


def is_due(entry: ScheduleEntry, *, today: date | None = None) -> bool:
    return days_overdue(entry, today=today) >= 0


def plan_due(
    entries: Iterable[ScheduleEntry],
    *,
    today: date | None = None,
    limit: int = 20,
    priorities: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Rank the items to revise today: most overdue first, then most important."""

    reference = today or date.today()
    weights = dict(priorities or {})
    due: list[dict[str, Any]] = []
    for entry in entries:
        overdue = days_overdue(entry, today=reference)
        if overdue < 0:
            continue
        due.append(
            {
                "item_key": entry.item_key,
                "kind": entry.kind,
                "due_at": entry.due_at,
                "days_overdue": overdue,
                "interval_days": interval_days(entry.rung),
                "streak": entry.streak,
                "lapses": entry.lapses,
                "last_status": entry.last_status,
                "priority": int(weights.get(entry.item_key, 2)),
                "schedule_version": SCHEDULE_VERSION,
            }
        )
    due.sort(key=lambda item: (-item["days_overdue"], -item["priority"], item["item_key"]))
    return due[: max(1, int(limit or 20))]


def recommend_from_answers(answers: Iterable[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    """Notions to rework, ranked by mistakes and by the last time they failed."""

    aggregated: dict[str, dict[str, Any]] = {}
    for answer in answers:
        notion_id = str(answer.get("notion_id") or "")
        if not notion_id:
            continue
        bucket = aggregated.setdefault(
            notion_id,
            {
                "notion_id": notion_id,
                "syllabus_id": str(answer.get("syllabus_id") or ""),
                "seen": 0,
                "correct": 0,
                "incorrect": 0,
                "last_failure_at": "",
            },
        )
        bucket["seen"] += 1
        status = str(answer.get("status") or "")
        if status == "correct":
            bucket["correct"] += 1
        elif status in {"incorrect", "partiel"}:
            bucket["incorrect"] += 1
            bucket["last_failure_at"] = max(bucket["last_failure_at"], str(answer.get("answered_at") or ""))

    ranking = []
    for bucket in aggregated.values():
        if bucket["incorrect"] == 0:
            continue
        accuracy = round(bucket["correct"] / bucket["seen"], 3) if bucket["seen"] else 0.0
        ranking.append(
            {
                **bucket,
                "accuracy": accuracy,
                "score": round(bucket["incorrect"] * 2 - accuracy, 3),
            }
        )
    ranking.sort(key=lambda item: (-item["score"], -item["incorrect"], item["notion_id"]))
    return ranking[: max(1, int(limit or 5))]
