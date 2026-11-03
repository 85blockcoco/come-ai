"""Tracking report: weekly/monthly application funnel (N100-H10).

Summaries from applications: counts by status, response rate, average
response delay.  Deterministic; ``today`` injectable.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass
class TrackingReport:
    total: int
    by_status: dict[str, int]
    response_rate: float
    avg_response_days: float | None
    sent_last_week: int
    open_threads: int
    warnings: list[str] = field(default_factory=list)


def _parse(value: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def build_tracking_report(applications: Iterable[dict[str, Any]], *, today: str | None = None) -> TrackingReport:
    apps = [a for a in applications if isinstance(a, dict)]
    by_status: dict[str, int] = {}
    response_days: list[int] = []
    last_week = 0
    open_threads = 0
    today_d = _parse(today) if today else datetime.date.today()

    for a in apps:
        st = str(a.get("status") or "unknown").lower()
        by_status[st] = by_status.get(st, 0) + 1
        sent = _parse(str(a.get("sent_at") or ""))
        responded_at = _parse(str(a.get("responded_at") or ""))
        if sent and responded_at:
            response_days.append((responded_at - sent).days)
        if sent and today_d and st in ("sent", "read"):
            if (today_d - sent).days <= 7:
                last_week += 1
        if st not in ("rejected", "accepted", "withdrawn"):
            open_threads += 1

    sent_total = sum(1 for a in apps if str(a.get("status", "")).lower() in ("sent", "read", "interview", "offer", "rejected", "accepted"))
    reply_total = sum(v for k, v in by_status.items() if k in ("interview", "offer", "rejected", "accepted"))
    rate = round(100.0 * reply_total / sent_total, 1) if sent_total else 0.0
    avg = round(sum(response_days) / len(response_days), 1) if response_days else None
    return TrackingReport(
        total=len(apps),
        by_status=by_status,
        response_rate=rate,
        avg_response_days=avg,
        sent_last_week=last_week,
        open_threads=open_threads,
    )


def to_dict(r: TrackingReport) -> dict[str, Any]:
    return asdict(r)
