"""Follow-up engine (N100-H05)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Iterable


@dataclass
class FollowUp:
    application_id: str
    due_date: str
    reason: str
    priority: str = "normal"


def due_followups(applications: Iterable[dict[str, Any]], *, today: str | None = None) -> list[FollowUp]:
    if today is None:
        today = date.today().isoformat()
    today_d = datetime.strptime(today[:10], "%Y-%m-%d").date()
    out: list[FollowUp] = []
    for app in applications:
        if not isinstance(app, dict):
            continue
        status = str(app.get("status", "")).lower()
        if status in ("rejected", "accepted", "withdrawn"):
            continue
        last = app.get("last_contact") or app.get("sent_at") or app.get("date")
        if not last:
            continue
        try:
            last_d = datetime.strptime(str(last)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        # Follow-up due after 7 days without response.
        if (today_d - last_d).days >= 7:
            out.append(FollowUp(
                application_id=str(app.get("id") or app.get("application_id") or ""),
                due_date=today,
                reason="no_response_7d",
                priority="high" if (today_d - last_d).days >= 14 else "normal",
            ))
    return out


def to_dict(f: FollowUp) -> dict[str, Any]:
    return asdict(f)