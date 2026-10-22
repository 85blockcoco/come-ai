"""Rapports d'audit du registre de traçabilité (SPEC-011).

Les rapports sont calculés à partir des traces et de leur historique.  Ils
ne décident rien : ils exposent ce qui est couvert, ce qui ne l'est pas, ce
qui a été renoncé et comment la situation a évolué.

RAPPORTS
- ``coverage_by_offer``  : % d'exigences couvertes par offre.
- ``coverage_by_cv``     : % d'exigences rattachées à un CV et couvertes.
- ``critical_gaps``      : exigences ``mandatory`` non couvertes.
- ``waived_requirements``: exigences renonciées, avec leur justification.
- ``history_timeline``   : chronologie filtrable des événements.
- ``coverage_over_time`` : courbe de couverture reconstruite depuis
  l'historique (relecture des événements, pas d'horodatage supposé).

DÉFINITIONS
- ``covered_pct``  : exigences ``covered`` / total.
- ``effective_pct`` : ``(covered + 0,5 × partial)`` / total : une exigence
  partiellement prouvée compte pour moitié, jamais pour totalité.
- Une exigence ``waived`` est comptée à part : elle ne gonfle ni la
  couverture ni le reste à faire.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .traceability import RequirementTrace, TraceabilityRegistry

#: Marker of the deletion event (extension of the contract, see traceability).
DELETED_MARKER = "deleted"

__all__ = [
    "audit_summary",
    "coverage_by_cv",
    "coverage_by_offer",
    "coverage_over_time",
    "critical_gaps",
    "history_timeline",
    "waived_requirements",
]


def _percent(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part * 100.0 / total, 1)


def _traces_of(source: Any) -> list[RequirementTrace]:
    if isinstance(source, TraceabilityRegistry):
        return source.traces()
    if isinstance(source, RequirementTrace):
        return [source]
    if isinstance(source, Iterable):
        return [item for item in source if isinstance(item, RequirementTrace)]
    return []


def _counts(traces: Sequence[RequirementTrace]) -> dict[str, Any]:
    total = len(traces)
    by_status: dict[str, int] = {}
    for trace in traces:
        by_status[trace.status] = by_status.get(trace.status, 0) + 1
    covered = by_status.get("covered", 0)
    partial = by_status.get("partial", 0)
    uncovered = by_status.get("uncovered", 0)
    contradicted = by_status.get("contradicted", 0)
    waived = by_status.get("waived", 0)
    assessed = total - waived
    return {
        "total": total,
        "assessed": assessed,
        "covered": covered,
        "partial": partial,
        "uncovered": uncovered,
        "contradicted": contradicted,
        "waived": waived,
        "by_status": dict(sorted(by_status.items())),
        "covered_pct": _percent(covered, assessed),
        "partial_pct": _percent(partial, assessed),
        "uncovered_pct": _percent(uncovered, assessed),
        "contradicted_pct": _percent(contradicted, assessed),
        "waived_pct": _percent(waived, total),
        "effective_pct": _percent(covered * 2 + partial, assessed * 2),
    }


def coverage_by_offer(source: Any) -> list[dict[str, Any]]:
    """Return the coverage of every offer present in the registry."""

    grouped: dict[str, list[RequirementTrace]] = {}
    for trace in _traces_of(source):
        grouped.setdefault(trace.offer_id or trace.source, []).append(trace)
    report = []
    for offer_id in sorted(grouped):
        traces = grouped[offer_id]
        counts = _counts(traces)
        counts.update(
            {
                "offer_id": offer_id,
                "source": traces[0].source,
                "by_category": _by(traces, "category"),
                "by_criticality": _by(traces, "criticality"),
            }
        )
        report.append(counts)
    return report


def coverage_by_cv(source: Any) -> list[dict[str, Any]]:
    """Return the coverage of every CV present in the registry.

    Only the requirements attached to a CV (``cv_<id>``) are counted here:
    an offer requirement belongs to its offer, not to a CV.
    """

    grouped: dict[str, list[RequirementTrace]] = {}
    for trace in _traces_of(source):
        cv_id = trace.cv_id
        if not cv_id:
            continue
        grouped.setdefault(cv_id, []).append(trace)
    report = []
    for cv_id in sorted(grouped):
        traces = grouped[cv_id]
        counts = _counts(traces)
        counts.update(
            {
                "cv_id": cv_id,
                "source": traces[0].source,
                "linked_evidence": sum(1 for trace in traces if trace.evidence_id),
            }
        )
        report.append(counts)
    return report


def _by(traces: Sequence[RequirementTrace], attribute: str) -> dict[str, int]:
    counter: dict[str, int] = {}
    for trace in traces:
        value = getattr(trace, attribute)
        counter[value] = counter.get(value, 0) + 1
    return dict(sorted(counter.items()))


def critical_gaps(source: Any, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Return the mandatory requirements that are not covered."""

    gaps = []
    for trace in _traces_of(source):
        if trace.criticality != "mandatory":
            continue
        if trace.status in {"covered", "waived"}:
            continue
        gaps.append(
            {
                "trace_id": trace.trace_id,
                "requirement_id": trace.requirement_id,
                "requirement_text": trace.requirement_text,
                "source": trace.source,
                "offer_id": trace.offer_id,
                "cv_id": trace.cv_id,
                "category": trace.category,
                "criticality": trace.criticality,
                "status": trace.status,
                "tags": list(trace.tags),
            }
        )
    gaps.sort(key=lambda item: (item["source"], item["requirement_id"], item["trace_id"]))
    return gaps[:limit] if limit else gaps


def waived_requirements(source: Any) -> list[dict[str, Any]]:
    """Return the waived requirements with their justification."""

    waived = []
    for trace in _traces_of(source):
        if trace.status != "waived":
            continue
        waived.append(
            {
                "trace_id": trace.trace_id,
                "requirement_id": trace.requirement_id,
                "requirement_text": trace.requirement_text,
                "source": trace.source,
                "offer_id": trace.offer_id,
                "category": trace.category,
                "criticality": trace.criticality,
                "justification": trace.justification(),
                "updated_at": trace.updated_at,
            }
        )
    waived.sort(key=lambda item: (item["source"], item["requirement_id"]))
    return waived


def history_timeline(
    source: Any,
    *,
    trace_id: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
    source_filter: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return the chronological trail of the events, filtered.

    ``source_filter`` filters on the source label of the requirement (the
    ``offer_42`` / ``cv_7`` prefix), never on a fuzzy match.
    """

    events: list[dict[str, Any]] = []
    for trace in _traces_of(source):
        if trace_id and trace.trace_id != trace_id:
            continue
        if source_filter and trace.source != source_filter:
            continue
        for index, event in enumerate(trace.history):
            if event_type and event.event_type != event_type:
                continue
            if actor and event.actor != actor:
                continue
            if since and event.timestamp < since:
                continue
            if until and event.timestamp > until:
                continue
            events.append(
                {
                    "trace_id": trace.trace_id,
                    "requirement_id": trace.requirement_id,
                    "requirement_text": trace.requirement_text,
                    "source": trace.source,
                    "offer_id": trace.offer_id,
                    "status": trace.status,
                    "sequence": index,
                    **event.to_dict(),
                }
            )
    events.sort(key=lambda item: (item["timestamp"], item["trace_id"], item["sequence"]))
    return events[:limit] if limit else events


def coverage_over_time(source: Any) -> list[dict[str, Any]]:
    """Rebuild the coverage curve from the immutable history.

    The curve is a replay: each event is applied to the status of its
    requirement, in chronological order.  No date is invented — a point of
    the curve exists only where an event exists.
    """

    traces = _traces_of(source)
    statuses: dict[str, str] = {trace.trace_id: "uncovered" for trace in traces}
    known: dict[str, RequirementTrace] = {trace.trace_id: trace for trace in traces}

    points: list[dict[str, Any]] = []
    for event in history_timeline(traces):
        trace_id = event["trace_id"]
        trace = known.get(trace_id)
        if trace is None:
            continue
        event_type = event["event_type"]
        if event_type == "created":
            statuses[trace_id] = event.get("new_value") or "uncovered"
        elif event_type == "status_changed":
            statuses[trace_id] = event.get("new_value") or statuses[trace_id]
        elif event_type == "waived":
            statuses[trace_id] = "waived"
        elif event_type == "reopened":
            statuses[trace_id] = event.get("new_value") or "uncovered"
        elif event_type == DELETED_MARKER:
            statuses.pop(trace_id, None)
        covered = sum(1 for value in statuses.values() if value == "covered")
        partial = sum(1 for value in statuses.values() if value == "partial")
        waived = sum(1 for value in statuses.values() if value == "waived")
        assessed = len(statuses) - waived
        points.append(
            {
                "timestamp": event["timestamp"],
                "trace_id": trace_id,
                "event_type": event_type,
                "covered": covered,
                "partial": partial,
                "waived": waived,
                "total": len(statuses),
                "covered_pct": _percent(covered, assessed),
                "effective_pct": _percent(covered * 2 + partial, assessed * 2),
            }
        )
    return points


def audit_summary(source: Any) -> dict[str, Any]:
    """Return a compact summary of the registry state."""

    traces = _traces_of(source)
    counts = _counts(traces)
    counts.update(
        {
            "by_category": _by(traces, "category"),
            "by_criticality": _by(traces, "criticality"),
            "by_source": _by(traces, "source"),
            "critical_gaps": len(critical_gaps(traces)),
            "waived": len(waived_requirements(traces)),
            "linked_evidence": sum(1 for trace in traces if trace.evidence_id),
        }
    )
    return counts


def report_to_dict(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy of a report (helper for the HTTP layer)."""

    return {key: value for key, value in report.items()}
