"""Reporting for the evidence freshness layer — dashboard, timeline, trends.

This module turns the raw freshness of the proofs into the figures the
person actually reads: how many proofs are fresh, what expires next, which
alerts are open, and how the situation evolved.  It stays pure and
deterministic: every figure is derived from the data it is given, and a
missing date is reported as unknown rather than as zero.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from .evidence_freshness import (
    ALERT_CRITICAL,
    ALERT_LEVEL_ORDER,
    STATUS_ARCHIVED,
    STATUS_EXPIRED,
    STATUS_FRESH,
    STATUS_WARNING,
    EvidenceFreshness,
    days_to_expiry,
    instant_to_text,
    parse_instant,
    utc_now,
)


#: Buckets of the freshness timeline, in days.
TIMELINE_BUCKETS = (7, 30, 90)

#: Windows of the freshness trends, in days.
TREND_WINDOWS = (30, 90, 365)

STATUSES = (STATUS_FRESH, STATUS_WARNING, STATUS_EXPIRED, STATUS_ARCHIVED)


def serialize_freshness(freshness: EvidenceFreshness) -> dict[str, Any]:
    """Serialize a freshness for the local API."""
    from .evidence_freshness import freshness_to_dict

    return freshness_to_dict(freshness)


def status_counts(freshnesses: Iterable[EvidenceFreshness]) -> dict[str, int]:
    """Return the number of proofs per freshness status."""
    counts = {status: 0 for status in STATUSES}
    for freshness in freshnesses:
        counts[freshness.status] = counts.get(freshness.status, 0) + 1
    counts["total"] = sum(counts[status] for status in STATUSES)
    return counts


def status_ratios(counts: dict[str, int]) -> dict[str, float]:
    """Return the share of each status, as a percentage of the total."""
    total = int(counts.get("total") or 0)
    if not total:
        return {status: 0.0 for status in STATUSES}
    return {
        status: round(100.0 * int(counts.get(status) or 0) / total, 1)
        for status in STATUSES
    }


def counts_by_type(freshnesses: Iterable[EvidenceFreshness]) -> dict[str, dict[str, int]]:
    """Return the breakdown of the proofs per evidence type."""
    breakdown: dict[str, dict[str, int]] = {}
    for freshness in freshnesses:
        bucket = breakdown.setdefault(
            freshness.evidence_type or "unknown",
            {status: 0 for status in STATUSES} | {"total": 0},
        )
        bucket[freshness.status] = bucket.get(freshness.status, 0) + 1
        bucket["total"] += 1
    return dict(sorted(breakdown.items()))


def timeline(freshnesses: Iterable[EvidenceFreshness], *, now: datetime | None = None) -> dict[str, Any]:
    """Return the number of proofs expiring in the coming 7, 30 and 90 days."""
    reference = now or utc_now()
    buckets = {f"{days}d": 0 for days in TIMELINE_BUCKETS}
    upcoming: list[dict[str, Any]] = []
    for freshness in freshnesses:
        remaining = days_to_expiry(freshness, now=reference)
        if remaining is None or remaining < 0:
            continue
        for days in TIMELINE_BUCKETS:
            if remaining <= days:
                buckets[f"{days}d"] += 1
        upcoming.append(
            {
                "evidence_id": freshness.evidence_id,
                "evidence_type": freshness.evidence_type,
                "expires_at": freshness.expires_at,
                "days_remaining": remaining,
                "status": freshness.status,
            }
        )
    upcoming.sort(key=lambda item: (item["days_remaining"], item["evidence_id"]))
    return {"buckets": buckets, "upcoming": upcoming[:50]}


def sort_alerts(alerts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the alerts sorted by severity, then by recency."""
    materialized = [dict(alert) for alert in alerts]
    materialized.sort(
        key=lambda alert: (
            ALERT_LEVEL_ORDER.get(str(alert.get("level")), 9),
            str(alert.get("created_at") or ""),
        )
    )
    return materialized


def export_gate(alerts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return the export blockers raised by the critical alerts.

    A proof that expired cannot silently stay in a generated document: the
    person is told why the export is held back instead of receiving a CV
    that claims an outdated certification.
    """
    blockers = [
        {
            "evidence_id": alert.get("evidence_id"),
            "label": alert.get("label"),
            "code": alert.get("code"),
            "message": alert.get("message"),
        }
        for alert in alerts
        if str(alert.get("level")) == ALERT_CRITICAL and not alert.get("acknowledged")
    ]
    return {
        "blocked": bool(blockers),
        "blockers": blockers,
        "message": (
            "Des preuves expiring bloquent la génération d’un document tant qu’elles ne sont pas mises à jour."
            if blockers
            else ""
        ),
    }


def trend_series(snapshots: Iterable[dict[str, Any]], window_days: int) -> list[dict[str, Any]]:
    """Return the freshness history restricted to a window, oldest first.

    A window of 30 days shows the recent evolution; 90 and 365 days show
    the longer movement.  A gap in the history is a gap: the series does
    not invent an intermediate point.
    """
    limit = (utc_now() - timedelta(days=max(0, int(window_days)))).isoformat()
    series: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        at = str(snapshot.get("at") or "")
        if at and at < limit:
            continue
        counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
        series.append(
            {
                "at": at,
                "total": int(snapshot.get("total") or 0),
                "fresh_ratio": float(snapshot.get("fresh_ratio") or 0.0),
                "fresh": int(counts.get(STATUS_FRESH) or 0),
                "warning": int(counts.get(STATUS_WARNING) or 0),
                "expired": int(counts.get(STATUS_EXPIRED) or 0),
                "archived": int(counts.get(STATUS_ARCHIVED) or 0),
            }
        )
    series.sort(key=lambda item: str(item.get("at") or ""))
    return series


def dashboard(
    freshnesses: Iterable[EvidenceFreshness],
    *,
    alerts: Iterable[dict[str, Any]] = (),
    records: Iterable[dict[str, Any]] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the global freshness dashboard."""
    reference = now or utc_now()
    materialized = list(freshnesses)
    counts = status_counts(materialized)
    active_alerts = sort_alerts(alerts)
    return {
        "generated_at": instant_to_text(reference),
        "counts": counts,
        "ratios": status_ratios(counts),
        "by_type": counts_by_type(materialized),
        "timeline": timeline(materialized, now=reference),
        "alerts": active_alerts,
        "alert_counts": {
            level: sum(1 for alert in active_alerts if alert.get("level") == level)
            for level in (ALERT_CRITICAL, "warning", "info")
        },
        "export_gate": export_gate(active_alerts),
        "coverage": coverage_breakdown(records),
    }


def coverage_breakdown(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Return the number of proofs per coverage status."""
    breakdown: dict[str, int] = {}
    for record in records:
        coverage = str(record.get("coverage_status") or "covered")
        breakdown[coverage] = breakdown.get(coverage, 0) + 1
    return dict(sorted(breakdown.items()))


def report(
    freshnesses: Iterable[EvidenceFreshness],
    *,
    alerts: Iterable[dict[str, Any]] = (),
    records: Iterable[dict[str, Any]] = (),
    policies: dict[str, Any] | None = None,
    snapshots: Iterable[dict[str, Any]] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the full freshness report, including the trends."""
    reference = now or utc_now()
    materialized = list(freshnesses)
    history = [snapshot for snapshot in snapshots if isinstance(snapshot, dict)]
    return {
        "generated_at": instant_to_text(reference),
        "summary": dashboard(materialized, alerts=alerts, records=records, now=reference),
        "policies": dict(sorted((policies or {}).items())),
        "trends": {f"{window}d": trend_series(history, window) for window in TREND_WINDOWS},
        "history_size": len(history),
        "last_snapshot_at": str(history[-1].get("at")) if history else "",
    }


def upcoming_expirations(freshnesses: Iterable[EvidenceFreshness], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Return the proofs that expire, soonest first, with their remaining days."""
    reference = now or utc_now()
    items = []
    for freshness in freshnesses:
        remaining = days_to_expiry(freshness, now=reference)
        if remaining is None:
            continue
        items.append(
            {
                "evidence_id": freshness.evidence_id,
                "evidence_type": freshness.evidence_type,
                "expires_at": freshness.expires_at,
                "days_remaining": remaining,
                "status": freshness.status,
            }
        )
    items.sort(key=lambda item: (item["days_remaining"], item["evidence_id"]))
    return items


def latest_snapshot_at(snapshots: Iterable[dict[str, Any]]) -> str:
    """Return the instant of the most recent recorded snapshot."""
    instants = [
        parse_instant(snapshot.get("at"))
        for snapshot in snapshots
        if isinstance(snapshot, dict)
    ]
    instants = [instant for instant in instants if instant is not None]
    if not instants:
        return ""
    return instant_to_text(max(instants))
