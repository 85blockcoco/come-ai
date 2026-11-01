"""Evidence freshness (N100-D06).

Approved evidence ages: older evidence must be re-confirmed by the human
before reuse in letters/CVs.  Thresholds configurable.
"""

from __future__ import annotations

import datetime
from typing import Any, Iterable

FRESH_DAYS = 90
AGING_DAYS = 180

STATUSES = ("fresh", "aging", "stale", "unknown")


def _parse(value: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def classify_evidence_freshness(evidence_date: str, *, today: str | None = None) -> dict[str, Any]:
    d = _parse(evidence_date)
    if d is None:
        return {"status": "unknown", "age_days": None, "needs_review": True}
    today_d = _parse(today) if today else datetime.date.today()
    if today_d is None:
        return {"status": "unknown", "age_days": None, "needs_review": True}
    age = (today_d - d).days
    if age <= FRESH_DAYS:
        status, review = "fresh", False
    elif age <= AGING_DAYS:
        status, review = "aging", False
    else:
        status, review = "stale", True
    return {"status": status, "age_days": age, "needs_review": review}


def review_queue(evidences: Iterable[dict[str, Any]], *, date_key: str = "date", today: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in evidences:
        if not isinstance(ev, dict):
            continue
        cls = classify_evidence_freshness(str(ev.get(date_key) or ""), today=today)
        if cls["needs_review"]:
            out.append({"evidence_id": str(ev.get("id") or ""), "status": cls["status"], "age_days": cls["age_days"]})
    return out


def to_dict(result: dict[str, Any]) -> dict[str, Any]:
    return result
