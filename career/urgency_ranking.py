"""Deadline-based offer ordering / urgency ranking (N100-C08).

Offers are ordered by deadline proximity.  An offer without a deadline is
rendered as "unknown" urgency and sorted last — never first.  Ties are
broken by job id for determinism.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass
class UrgencyRow:
    job_id: str
    deadline: str | None
    days_left: int | None
    urgency: str  # urgent_72h | soon_14d | normal | unknown

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_date(value: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _days_left(deadline: str, *, today: str | None = None) -> int | None:
    d = _parse_date(deadline)
    today_d = _parse_date(today) if today else datetime.date.today()
    if d is None or today_d is None:
        return None
    return (d - today_d).days


def classify_urgency(deadline: str, *, today: str | None = None) -> str:
    d = _parse_date(deadline)
    if d is None:
        return "unknown"
    today_d = _parse_date(today) if today else datetime.date.today()
    if today_d is None:
        return "unknown"
    days = (d - today_d).days
    if days < 0:
        return "expired"
    if days <= 3:
        return "urgent_72h"
    if days <= 14:
        return "soon_14d"
    return "normal"


def rank_by_urgency(offers: Iterable[dict[str, Any]], *, deadline_key: str = "deadline", today: str | None = None) -> tuple[list[UrgencyRow], list[dict[str, Any]]]:
    """Return (urgency rows, ordered offers) — ordered offers sort unknown last."""
    rows: list[UrgencyRow] = []
    for offer in offers:
        oid = str(offer.get("id") or offer.get("job_id") or "")
        deadline = offer.get(deadline_key)
        rows.append(UrgencyRow(
            job_id=oid,
            deadline=deadline,
            days_left=_days_left(str(deadline or ""), today=today),
            urgency=classify_urgency(str(deadline or ""), today=today),
        ))

    order = {"urgent_72h": 0, "soon_14d": 1, "normal": 2, "expired": 3, "unknown": 4}
    ordered = sorted(
        offers,
        key=lambda o: (
            order[classify_urgency(str(o.get(deadline_key) or ""), today=today)],
            str(o.get("id") or o.get("job_id") or ""),
        ),
    )
    return rows, list(ordered)
