"""Freshness reports, timelines and trends (SPEC-012).

Pure reporting helpers: they read the proofs, the alerts and the event
history and turn them into the payloads served by the dashboard.  No file
system, no network, no implicit clock — ``now`` is always explicit.

WHAT IS REPORTED
----------------
``build_freshness_report``
    The global picture: how many proofs are fresh / warning / expired /
    archived, the breakdown per evidence type, the upcoming expiries
    (7, 30 and 90 days), the alert counters and the automatic actions that
    were triggered.
``build_trends``
    The freshness ratios over 30, 90 and 365 days, rebuilt from the daily
    snapshots kept in the store history.
``build_audit_report``
    Both of the above plus the verification history of every proof.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from .evidence_freshness import (
    COVERAGE_ARCHIVED,
    COVERAGE_COVERED,
    COVERAGE_UNKNOWN,
    COVERAGE_WARNING,
    FRESHNESS_STATUSES,
    EvidenceFreshness,
    FreshnessAlert,
    blocks_export,
    days_until,
    format_timestamp,
    parse_timestamp,
    status_for,
)

REPORT_WINDOWS: tuple[int, ...] = (30, 90, 365)
TIMELINE_HORIZONS: tuple[int, ...] = (7, 30, 90)
ALERT_ORDER = {"critical": 0, "warning": 1, "info": 2}


def effective_status(evidence: EvidenceFreshness, now: datetime) -> str:
    """The freshness status of a proof, recomputed from its dates.

    The status stored on the record may be stale: a proof that passed its
    ``expires_at`` is ``expired`` whatever the record said before.  The
    report therefore never trusts the stored value.
    """
    return status_for(
        expires_at=parse_timestamp(evidence.expires_at),
        warning_at=parse_timestamp(evidence.warning_at),
        now=now,
        archived=evidence.archived,
    )


def summarize_evidence(evidence: EvidenceFreshness, now: datetime) -> dict[str, Any]:
    """One proof, seen from the dashboard."""
    expires_at = parse_timestamp(evidence.expires_at)
    remaining = days_until(expires_at, now)
    last_check = None
    if evidence.source_checks:
        last_check = evidence.source_checks[-1].checked_at
    status = effective_status(evidence, now)
    return {
        "evidence_id": evidence.evidence_id,
        "evidence_type": evidence.evidence_type,
        "title": evidence.title,
        "mandatory": evidence.mandatory,
        "status": status,
        "coverage_status": evidence.coverage_status,
        "created_at": evidence.created_at,
        "last_verified_at": evidence.last_verified_at,
        "last_checked_at": last_check,
        "expires_at": evidence.expires_at,
        "warning_at": evidence.warning_at,
        "days_until_expiry": remaining,
        "needs_reverification": evidence.needs_reverification,
        "archived": evidence.archived,
        "dates_pinned": evidence.dates_pinned,
        "source_url": evidence.source_url,
        "notes": evidence.notes,
        "auto_actions": list(evidence.auto_actions),
        "checks_count": len(evidence.source_checks),
        "blocks_export": blocks_export(evidence) if status == "expired" else False,
    }


def build_freshness_report(
    evidences: Sequence[EvidenceFreshness],
    alerts: Sequence[FreshnessAlert] = (),
    *,
    now: datetime,
) -> dict[str, Any]:
    """The global freshness report."""
    totals = {status: 0 for status in sorted(FRESHNESS_STATUSES)}
    by_type: dict[str, dict[str, Any]] = {}
    coverage = {
        COVERAGE_UNKNOWN: 0,
        COVERAGE_COVERED: 0,
        COVERAGE_WARNING: 0,
        COVERAGE_ARCHIVED: 0,
    }
    timeline: dict[str, list[dict[str, Any]]] = {str(horizon): [] for horizon in TIMELINE_HORIZONS}
    needs_reverification: list[str] = []
    blocking_export: list[str] = []
    expired_by_date: list[str] = []
    action_counter: dict[str, int] = {}

    for evidence in evidences:
        status = effective_status(evidence, now)
        totals[status] = totals.get(status, 0) + 1
        coverage[evidence.coverage_status] = coverage.get(evidence.coverage_status, 0) + 1
        bucket = by_type.setdefault(
            evidence.evidence_type,
            {
                "total": 0,
                "fresh": 0,
                "warning": 0,
                "expired": 0,
                "archived": 0,
                "next_expiry": None,
                "next_expiry_id": None,
            },
        )
        bucket["total"] += 1
        bucket[status] = bucket.get(status, 0) + 1
        expires_at = parse_timestamp(evidence.expires_at)
        if expires_at is not None and expires_at <= now:
            # Archivée automatiquement ou non, la date d'expiration est passée.
            expired_by_date.append(evidence.evidence_id)
        if expires_at is not None and status != "archived":
            if bucket["next_expiry"] is None or expires_at.isoformat() < bucket["next_expiry"]:
                bucket["next_expiry"] = expires_at.isoformat()
                bucket["next_expiry_id"] = evidence.evidence_id
        if evidence.needs_reverification:
            needs_reverification.append(evidence.evidence_id)
        if status == "expired" and blocks_export(evidence):
            blocking_export.append(evidence.evidence_id)
        for action in evidence.auto_actions:
            action_counter[action] = action_counter.get(action, 0) + 1
        remaining = days_until(expires_at, now)
        if remaining is None or remaining < 0 or status == "archived":
            continue
        entry = {
            "evidence_id": evidence.evidence_id,
            "evidence_type": evidence.evidence_type,
            "title": evidence.title,
            "expires_at": evidence.expires_at,
            "days_left": remaining,
            "mandatory": evidence.mandatory,
        }
        for horizon in TIMELINE_HORIZONS:
            if remaining <= horizon:
                timeline[str(horizon)].append(entry)

    total = len(evidences)
    ratios = {
        status: (round(totals.get(status, 0) / total, 4) if total else 0.0)
        for status in sorted(FRESHNESS_STATUSES)
    }
    for horizon in TIMELINE_HORIZONS:
        timeline[str(horizon)].sort(key=lambda item: (item["days_left"], item["evidence_id"]))

    alert_counts = {"info": 0, "warning": 0, "critical": 0}
    acknowledged = 0
    for alert in alerts:
        if alert.acknowledged:
            acknowledged += 1
            continue
        alert_counts[alert.level] = alert_counts.get(alert.level, 0) + 1

    return {
        "generated_at": format_timestamp(now),
        "totals": {
            "total": total,
            **totals,
            "expired_by_date": len(expired_by_date),
        },
        "ratios": ratios,
        "by_type": {key: by_type[key] for key in sorted(by_type)},
        "coverage": coverage,
        "timeline": timeline,
        "alerts": {
            "active": sum(alert_counts.values()),
            "acknowledged": acknowledged,
            **alert_counts,
        },
        "auto_actions": dict(sorted(action_counter.items())),
        "needs_reverification": sorted(needs_reverification),
        "blocking_export": sorted(blocking_export),
    }


def build_trends(
    history: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    windows: Sequence[int] = REPORT_WINDOWS,
) -> dict[str, Any]:
    """Freshness ratios rebuilt from the daily snapshots of the history."""
    snapshots: list[dict[str, Any]] = []
    for entry in history:
        if not isinstance(entry, Mapping) or entry.get("event") != "snapshot":
            continue
        counts = entry.get("counts") if isinstance(entry.get("counts"), Mapping) else {}
        total = int(entry.get("total", 0) or 0)
        day = str(entry.get("date", ""))
        snapshots.append(
            {
                "date": day,
                "total": total,
                "fresh": int(counts.get("fresh", 0) or 0),
                "warning": int(counts.get("warning", 0) or 0),
                "expired": int(counts.get("expired", 0) or 0),
                "archived": int(counts.get("archived", 0) or 0),
            }
        )
    snapshots.sort(key=lambda item: item["date"])

    trends: dict[str, Any] = {}
    for window in windows:
        start = (now - timedelta(days=window)).date().isoformat()
        series = [
            {
                "date": snapshot["date"],
                "total": snapshot["total"],
                "fresh_ratio": round(snapshot["fresh"] / snapshot["total"], 4) if snapshot["total"] else 0.0,
                "warning_ratio": round(snapshot["warning"] / snapshot["total"], 4) if snapshot["total"] else 0.0,
                "expired_ratio": round(snapshot["expired"] / snapshot["total"], 4) if snapshot["total"] else 0.0,
            }
            for snapshot in snapshots
            if snapshot["date"] >= start and snapshot["date"] <= now.date().isoformat()
        ]
        latest = series[-1] if series else None
        first = series[0] if series else None
        drift = None
        if latest is not None and first is not None:
            drift = round(latest["fresh_ratio"] - first["fresh_ratio"], 4)
        trends[str(window)] = {
            "from": start,
            "to": now.date().isoformat(),
            "points": len(series),
            "series": series,
            "latest": latest,
            "fresh_drift": drift,
        }
    return trends


def build_verification_history(evidences: Sequence[EvidenceFreshness]) -> list[dict[str, Any]]:
    """The verification history of every proof."""
    history: list[dict[str, Any]] = []
    for evidence in evidences:
        checks = [
            {
                "check_id": check.check_id,
                "checked_at": check.checked_at,
                "method": check.method,
                "result": check.result,
                "source_url": check.source_url,
                "details": dict(check.details),
            }
            for check in evidence.source_checks
        ]
        history.append(
            {
                "evidence_id": evidence.evidence_id,
                "evidence_type": evidence.evidence_type,
                "title": evidence.title,
                "last_verified_at": evidence.last_verified_at,
                "checks": checks,
                "auto_actions": list(evidence.auto_actions),
            }
        )
    history.sort(key=lambda item: item["evidence_id"])
    return history


def build_audit_report(
    evidences: Sequence[EvidenceFreshness],
    alerts: Sequence[FreshnessAlert],
    history: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    """The complete audit payload: report, trends and verification history."""
    report = build_freshness_report(evidences, alerts, now=now)
    return {
        **report,
        "trends": build_trends(history, now=now),
        "verification_history": build_verification_history(evidences),
    }


def render_report_markdown(report: Mapping[str, Any]) -> str:
    """A readable, deterministic Markdown view of the audit report."""
    totals = report.get("totals", {}) or {}
    ratios = report.get("ratios", {}) or {}
    lines = [
        "# Fraîcheur des preuves",
        "",
        f"Généré le {report.get('generated_at', '')}",
        "",
        "| Statut | Nombre | Part |",
        "| --- | --- | --- |",
    ]
    for status in sorted(totals):
        if status == "total":
            continue
        ratio = ratios.get(status, 0.0)
        lines.append(f"| {status} | {totals.get(status, 0)} | {round(float(ratio) * 100, 1)}% |")
    lines.append(f"| **total** | **{totals.get('total', 0)}** | 100% |")
    lines.append("")
    by_type = report.get("by_type", {}) or {}
    if by_type:
        lines.append("## Par type de preuve")
        lines.append("")
        lines.append("| Type | Total | Fresh | Warning | Expired | Archived |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for evidence_type in sorted(by_type):
            entry = by_type[evidence_type]
            lines.append(
                f"| {evidence_type} | {entry.get('total', 0)} | {entry.get('fresh', 0)} | "
                f"{entry.get('warning', 0)} | {entry.get('expired', 0)} | {entry.get('archived', 0)} |"
            )
        lines.append("")
    alerts = report.get("alerts", {}) or {}
    lines.append(
        f"Alertes actives : {alerts.get('active', 0)} "
        f"(critiques {alerts.get('critical', 0)}, warnings {alerts.get('warning', 0)}, "
        f"infos {alerts.get('info', 0)})."
    )
    return "\n".join(lines) + "\n"
