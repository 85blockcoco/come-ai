"""Audit reports for the requirement traceability registry (SPEC-011).

Every report is computed from the traces and their events; nothing is stored
a second time and nothing is estimated.  A percentage always comes with the
raw counts it was computed from, so a reader can check the arithmetic.

REPORTS
- ``coverage_by_offer()``  — coverage of the requirements of each offer.
- ``coverage_by_cv()``     — coverage of the profile evidence per CV.
- ``critical_gaps()``      — mandatory requirements that are not covered.
- ``waived_requirements()`` — waived requirements and their justification.
- ``status_timeline()``    — the status history of every requirement.
- ``coverage_evolution()`` — the coverage curve rebuilt from the events.
- ``audit_report()``       — all of the above in one payload.

A ``covered`` requirement counts as covered.  A ``partial`` one is reported
separately and never inflates the coverage rate: half-proofs are not proofs.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .models import utc_now
from .traceability import (
    COVERED_STATUSES,
    STATUSES,
    RequirementTrace,
    TraceEvent,
)


def _percentage(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part * 100.0 / total, 2)


def _status_counts(traces: Sequence[RequirementTrace]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for trace in traces:
        counts[trace.status] = counts.get(trace.status, 0) + 1
    return counts


def _coverage_block(traces: Sequence[RequirementTrace]) -> dict[str, Any]:
    counts = _status_counts(traces)
    total = len(traces)
    covered = counts.get("covered", 0)
    partial = counts.get("partial", 0)
    return {
        "total": total,
        "covered": covered,
        "partial": partial,
        "uncovered": counts.get("uncovered", 0),
        "contradicted": counts.get("contradicted", 0),
        "waived": counts.get("waived", 0),
        "by_status": counts,
        "coverage_rate": _percentage(covered, total),
        "partial_rate": _percentage(partial, total),
        "gaps": counts.get("uncovered", 0) + counts.get("contradicted", 0),
    }


def coverage_by_offer(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Coverage of the requirements, grouped by offer."""
    grouped: dict[str, list[RequirementTrace]] = {}
    for trace in traces:
        key = trace.offer_id or trace.source or "unknown"
        grouped.setdefault(key, []).append(trace)
    report = []
    for key in sorted(grouped):
        block = _coverage_block(grouped[key])
        report.append(
            {
                "offer_id": key,
                "source": grouped[key][0].source,
                **block,
            }
        )
    return report


def coverage_by_cv(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Coverage of the profile evidence, grouped by CV."""
    grouped: dict[str, list[RequirementTrace]] = {}
    for trace in traces:
        key = trace.cv_id or "unknown"
        grouped.setdefault(key, []).append(trace)
    report = []
    for key in sorted(grouped):
        block = _coverage_block(grouped[key])
        report.append({"cv_id": key, **block})
    return report


def critical_gaps(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Mandatory requirements that are not covered by a proof.

    A waived requirement is a deliberate decision, not a gap: it is reported
    by :func:`waived_requirements` instead.
    """
    gaps = []
    for trace in traces:
        if trace.deleted:
            continue
        if trace.criticality != "mandatory":
            continue
        if trace.status in COVERED_STATUSES:
            continue
        if trace.status == "waived":
            continue
        gaps.append(
            {
                "trace_id": trace.trace_id,
                "requirement_id": trace.requirement_id,
                "requirement_text": trace.requirement_text,
                "offer_id": trace.offer_id,
                "status": trace.status,
                "criticality": trace.criticality,
                "category": trace.category,
                "evidence_id": trace.evidence_id,
                "updated_at": trace.updated_at,
            }
        )
    return sorted(gaps, key=lambda item: (item["offer_id"], item["trace_id"]))


def waived_requirements(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Waived requirements with the justification that was recorded."""
    waived = []
    for trace in traces:
        if trace.status != "waived":
            continue
        waived.append(
            {
                "trace_id": trace.trace_id,
                "requirement_id": trace.requirement_id,
                "requirement_text": trace.requirement_text,
                "offer_id": trace.offer_id,
                "criticality": trace.criticality,
                "justification": trace.waiver_reason or "",
                "waived_at": trace.updated_at,
            }
        )
    return sorted(waived, key=lambda item: (item["offer_id"], item["trace_id"]))


def status_timeline(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """The status history of every requirement, oldest event first."""
    timeline = []
    for trace in traces:
        entries = []
        for event in trace.history:
            if event.event_type not in {"created", "status_changed", "waived", "reopened", "linked", "unlinked", "validated"}:
                continue
            entries.append(
                {
                    "timestamp": event.timestamp,
                    "event_type": event.event_type,
                    "actor": event.actor,
                    "status": event.new_value if event.event_type in {"created", "status_changed", "waived", "reopened"} else None,
                    "comment": event.comment,
                }
            )
        timeline.append(
            {
                "trace_id": trace.trace_id,
                "requirement_text": trace.requirement_text,
                "offer_id": trace.offer_id,
                "current_status": trace.status,
                "events": entries,
            }
        )
    return sorted(timeline, key=lambda item: item["trace_id"])


def coverage_evolution(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Rebuild the coverage curve from the audit trail.

    The curve replays the events in chronological order: every status change
    produces one point of the series.  The result is reproducible: the same
    history always yields the same curve.
    """
    events: list[tuple[str, TraceEvent]] = []
    for trace in traces:
        for event in trace.history:
            events.append((trace.trace_id, event))
    events.sort(key=lambda item: (item[1].timestamp, item[1].event_id))

    statuses: dict[str, str] = {}
    points: list[dict[str, Any]] = []
    for trace_id, event in events:
        if event.event_type == "created":
            statuses[trace_id] = event.new_value or "uncovered"
        elif event.event_type in {"status_changed", "waived", "reopened"}:
            statuses[trace_id] = event.new_value or statuses.get(trace_id, "uncovered")
        else:
            continue
        counts = _status_counts_values(statuses.values())
        total = len(statuses)
        points.append(
            {
                "timestamp": event.timestamp,
                "trace_id": trace_id,
                "total": total,
                "covered": counts.get("covered", 0),
                "partial": counts.get("partial", 0),
                "uncovered": counts.get("uncovered", 0),
                "contradicted": counts.get("contradicted", 0),
                "waived": counts.get("waived", 0),
                "coverage_rate": _percentage(counts.get("covered", 0), total),
            }
        )
    return points


def _status_counts_values(statuses: Iterable[str]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return counts


def audit_report(
    traces: Sequence[RequirementTrace],
    *,
    events: Sequence[TraceEvent] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Return every audit report of the registry in one payload."""
    active = [trace for trace in traces if not trace.deleted]
    gaps = critical_gaps(active)
    waived = waived_requirements(active)
    overall = _coverage_block(active)
    return {
        "generated_at": generated_at or utc_now(),
        "totals": {
            "traces": len(traces),
            "active": len(active),
            "deleted": len(traces) - len(active),
            "events": len(events) if events is not None else sum(len(trace.history) for trace in traces),
        },
        "overall": overall,
        "coverage_by_offer": coverage_by_offer(active),
        "coverage_by_cv": coverage_by_cv(active),
        "critical_gaps": gaps,
        "critical_gap_count": len(gaps),
        "waived": waived,
        "waived_count": len(waived),
        "waived_mandatory_count": sum(1 for item in waived if item["criticality"] == "mandatory"),
        "timeline": status_timeline(active),
        "evolution": coverage_evolution(active),
    }
