"""Rapports d'audit du registre de traçabilité (SPEC-011).

Toutes les fonctions de ce module sont **pures** : elles prennent une liste
de :class:`~career.traceability.RequirementTrace` et renvoient des
dictionnaires sérialisables.  Aucun accès disque, aucun réseau, aucun
modèle : les mêmes données produisent toujours le même rapport.

LES RAPPORTS
------------
* :func:`coverage_summary` — vue d'ensemble (totaux, taux de couverture).
* :func:`coverage_by_offer` — couverture exigence par exigence, par offre.
* :func:`coverage_by_cv` — couverture des exigences d'un profil (CV).
* :func:`critical_gaps` — exigences **obligatoires** non couvertes.
* :func:`waived_requirements` — dérogations et leur justification.
* :func:`history_timeline` — chronologie globale des événements.
* :func:`coverage_over_time` — courbe de couverture reconstruite depuis
  l'historique.
* :func:`audit_report` — rapport d'audit complet.

DÉFINITIONS (explicites, pour que les chiffres soient discutables)
------------------------------------------------------------------
* Une exigence ``waived`` est **exclue** du dénominateur de couverture :
  une dérogation motivée n'est ni un succès ni un échec.
* Une exigence **superseded** (elle n'est plus demandée par son offre) est
  exclue du dénominateur pour la même raison : elle n'est plus évaluable.
* Le taux de couverture est ``covered / (total - waived - superseded)``,
  arrondi à quatre décimales ; il vaut ``0.0`` quand il n'y a rien à
  évaluer.
* Le taux « mandatory » ne considère que les exigences obligatoires.
* Les incohérences (exigence ``partial`` sans preuve, exigence ``covered``
  sans citation) sont **signalées**, jamais corrigées silencieusement.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .models import normalized_text
from .traceability import RequirementTrace


__all__ = [
    "audit_report",
    "coverage_by_cv",
    "coverage_by_offer",
    "coverage_over_time",
    "coverage_summary",
    "critical_gaps",
    "history_timeline",
    "superseded_requirements",
    "waived_requirements",
]


_STATUS_ORDER: tuple[str, ...] = ("covered", "partial", "contradicted", "uncovered", "waived")


def _rate(covered: int, total: int) -> float:
    """Return a rounded coverage rate (``0.0`` when there is nothing to rate)."""
    if total <= 0:
        return 0.0
    return round(covered / total, 4)


def _status_counts(traces: Sequence[RequirementTrace]) -> dict[str, int]:
    counts = {status: 0 for status in _STATUS_ORDER}
    for trace in traces:
        counts[trace.status] = counts.get(trace.status, 0) + 1
    return counts


def _trace_view(trace: RequirementTrace) -> dict[str, Any]:
    """Return the public view of one trace (without its history)."""
    payload = trace.to_dict()
    payload.pop("history", None)
    return payload


def coverage_summary(traces: Iterable[RequirementTrace]) -> dict[str, Any]:
    """Return the global coverage of the registry."""
    items = list(traces)
    counts = _status_counts(items)
    waived = counts.get("waived", 0)
    superseded = sum(1 for trace in items if trace.is_superseded)
    evaluated = len(items) - waived - superseded
    mandatory = [trace for trace in items if trace.criticality == "mandatory"]
    mandatory_evaluated = len(mandatory) - sum(1 for trace in mandatory if trace.status == "waived") - sum(
        1 for trace in mandatory if trace.is_superseded
    )
    mandatory_covered = sum(1 for trace in mandatory if trace.status == "covered")
    by_category: dict[str, dict[str, Any]] = {}
    for trace in items:
        bucket = by_category.setdefault(
            trace.category,
            {"total": 0, "covered": 0, "partial": 0, "uncovered": 0, "contradicted": 0, "waived": 0},
        )
        bucket["total"] += 1
        bucket[trace.status] = bucket.get(trace.status, 0) + 1
    by_criticality: dict[str, dict[str, Any]] = {}
    for trace in items:
        bucket = by_criticality.setdefault(
            trace.criticality,
            {"total": 0, "covered": 0, "partial": 0, "uncovered": 0, "contradicted": 0, "waived": 0},
        )
        bucket["total"] += 1
        bucket[trace.status] = bucket.get(trace.status, 0) + 1
    return {
        "total": len(items),
        "evaluated": evaluated,
        "by_status": counts,
        "coverage_rate": _rate(counts.get("covered", 0), evaluated),
        "partial_rate": _rate(counts.get("partial", 0), evaluated),
        "mandatory": {
            "total": len(mandatory),
            "evaluated": mandatory_evaluated,
            "covered": mandatory_covered,
            "coverage_rate": _rate(mandatory_covered, mandatory_evaluated),
        },
        "by_category": by_category,
        "by_criticality": by_criticality,
        "pending_reviews": sum(1 for trace in items if trace.review_state == "pending"),
        "waived_count": waived,
        "superseded_count": superseded,
    }


def _group_coverage(traces: Sequence[RequirementTrace], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[RequirementTrace]] = {}
    for trace in traces:
        identifier = getattr(trace, key, "")
        if not identifier:
            continue
        groups.setdefault(identifier, []).append(trace)
    report: list[dict[str, Any]] = []
    for identifier in sorted(groups):
        items = groups[identifier]
        counts = _status_counts(items)
        waived = counts.get("waived", 0)
        superseded = sum(1 for trace in items if trace.is_superseded)
        evaluated = len(items) - waived - superseded
        mandatory = [trace for trace in items if trace.criticality == "mandatory"]
        mandatory_evaluated = len(mandatory) - sum(1 for trace in mandatory if trace.status == "waived") - sum(
            1 for trace in mandatory if trace.is_superseded
        )
        mandatory_covered = sum(1 for trace in mandatory if trace.status == "covered")
        report.append(
            {
                key: identifier,
                "total": len(items),
                "evaluated": evaluated,
                "covered": counts.get("covered", 0),
                "partial": counts.get("partial", 0),
                "uncovered": counts.get("uncovered", 0),
                "contradicted": counts.get("contradicted", 0),
                "waived": waived,
                "superseded": superseded,
                "coverage_rate": _rate(counts.get("covered", 0), evaluated),
                "mandatory_total": len(mandatory),
                "mandatory_covered": mandatory_covered,
                "mandatory_coverage_rate": _rate(mandatory_covered, mandatory_evaluated),
            }
        )
    return report


def coverage_by_offer(traces: Iterable[RequirementTrace]) -> list[dict[str, Any]]:
    """Return the coverage of every offer (one row per ``offer_id``)."""
    return _group_coverage(list(traces), "offer_id")


def coverage_by_cv(traces: Iterable[RequirementTrace]) -> list[dict[str, Any]]:
    """Return the coverage of every candidate profile (one row per ``cv_id``)."""
    return _group_coverage(list(traces), "cv_id")


def critical_gaps(traces: Iterable[RequirementTrace]) -> list[dict[str, Any]]:
    """Return the mandatory requirements that are not covered.

    ``partial`` and ``contradicted`` requirements are gaps too: a partial
    coverage of a mandatory requirement is not a coverage.  A *superseded*
    requirement is not a gap: the offer does not ask for it anymore.
    """
    gaps: list[dict[str, Any]] = []
    for trace in traces:
        if trace.criticality != "mandatory":
            continue
        if trace.status in {"covered", "waived"}:
            continue
        if trace.is_superseded:
            continue
        payload = _trace_view(trace)
        payload["gap_reason"] = trace.status
        gaps.append(payload)
    gaps.sort(key=lambda item: (item.get("offer_id") or "", item.get("requirement_id") or ""))
    return gaps


def superseded_requirements(traces: Iterable[RequirementTrace]) -> list[dict[str, Any]]:
    """Return the requirements their source no longer states.

    A superseded requirement is neither a success nor a failure: it left the
    offer.  It stays in the registry with the event that superseded it.
    """
    superseded: list[dict[str, Any]] = []
    for trace in traces:
        if not trace.is_superseded:
            continue
        payload = _trace_view(trace)
        payload["superseded_at"] = trace.superseded_at
        superseded.append(payload)
    superseded.sort(key=lambda item: (item.get("offer_id") or "", item.get("requirement_id") or ""))
    return superseded


def waived_requirements(traces: Iterable[RequirementTrace]) -> list[dict[str, Any]]:
    """Return the waived requirements with their justification."""
    waived: list[dict[str, Any]] = []
    for trace in traces:
        if trace.status != "waived":
            continue
        justification = ""
        for event in reversed(trace.history):
            if event.event_type == "waived":
                justification = event.comment or ""
                break
        payload = _trace_view(trace)
        payload["justification"] = justification
        payload["waived_at"] = next(
            (event.timestamp for event in reversed(trace.history) if event.event_type == "waived"),
            trace.updated_at,
        )
        waived.append(payload)
    waived.sort(key=lambda item: (item.get("offer_id") or "", item.get("requirement_id") or ""))
    return waived


def history_timeline(
    traces: Iterable[RequirementTrace],
    *,
    trace_id: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return the global event timeline (chronological, then stable)."""
    events: list[dict[str, Any]] = []
    for trace in traces:
        if trace_id and trace.trace_id != trace_id:
            continue
        for event in trace.history:
            if event_type and event.event_type != event_type:
                continue
            if actor and event.actor != actor:
                continue
            if since and event.timestamp < since:
                continue
            if until and event.timestamp > until:
                continue
            payload = event.to_dict()
            payload.update(
                {
                    "trace_id": trace.trace_id,
                    "requirement_id": trace.requirement_id,
                    "requirement_text": trace.requirement_text,
                    "source": trace.source,
                    "offer_id": trace.offer_id,
                    "cv_id": trace.cv_id,
                    "category": trace.category,
                    "criticality": trace.criticality,
                }
            )
            events.append(payload)
    events.sort(key=lambda item: (item["timestamp"], item["trace_id"], item["event_id"]))
    bounded = max(0, int(limit or 0))
    return events[:bounded] if bounded else events


def coverage_over_time(traces: Iterable[RequirementTrace]) -> list[dict[str, Any]]:
    """Rebuild the coverage curve from the immutable event history.

    The statuses are replayed in chronological order: only the events that
    change a status (``created``, ``status_changed``, ``waived``,
    ``reopened``, ``superseded``) are applied.  The result is therefore the
    history of the registry, not a snapshot of the present.

    A point counts **only the requirements that existed at that moment**: a
    requirement created later never inflates the denominator of an earlier
    point (otherwise the curve would start below zero coverage for a
    registry that did not yet hold those requirements).
    """
    items = list(traces)
    points: list[tuple[str, str, int, str, str]] = []
    for trace in items:
        status_events = [
            event
            for event in trace.history
            if event.event_type in {"created", "status_changed", "waived", "reopened", "superseded"}
        ]
        if not status_events:
            points.append((trace.created_at or trace.updated_at, trace.trace_id, 0, "created", trace.status))
            continue
        for index, event in enumerate(status_events):
            if event.event_type == "waived":
                new_status = "waived"
            elif event.event_type == "reopened":
                new_status = event.new_value or "uncovered"
            else:
                new_status = event.new_value or "uncovered"
            points.append((event.timestamp, trace.trace_id, index, event.event_type, new_status))
    # The index inside the history is the tiebreaker: two events sharing the
    # same timestamp keep their causal order (the history is append-only).
    points.sort(key=lambda item: (item[0], item[1], item[2]))
    states: dict[str, str] = {}
    superseded: set[str] = set()
    timeline: list[dict[str, Any]] = []
    for timestamp, trace_id, _index, event_type, new_status in points:
        states[trace_id] = new_status
        if event_type == "superseded":
            superseded.add(trace_id)
        covered = sum(1 for status in states.values() if status == "covered")
        waived = sum(1 for status in states.values() if status == "waived")
        evaluated = len(states) - waived - len(superseded)
        timeline.append(
            {
                "timestamp": timestamp,
                "trace_id": trace_id,
                "event_type": event_type,
                "status": new_status,
                "covered": covered,
                "waived": waived,
                "superseded": len(superseded),
                "evaluated": evaluated,
                "coverage_rate": _rate(covered, evaluated),
            }
        )
    return timeline


def _inconsistencies(traces: Iterable[RequirementTrace]) -> list[dict[str, Any]]:
    """Return the coherence problems (never repaired silently)."""
    problems: list[dict[str, Any]] = []
    for trace in traces:
        if trace.status == "covered" and not (trace.evidence_id and trace.evidence_quote):
            problems.append(
                {
                    "trace_id": trace.trace_id,
                    "requirement_id": trace.requirement_id,
                    "code": "covered_without_proof",
                    "detail": "Une exigence « covered » sans preuve ni citation.",
                }
            )
        if trace.status == "partial" and not trace.evidence_id:
            problems.append(
                {
                    "trace_id": trace.trace_id,
                    "requirement_id": trace.requirement_id,
                    "code": "partial_without_proof",
                    "detail": "Une exigence « partial » sans preuve liée.",
                }
            )
        if trace.review_state == "pending" and trace.status == "covered":
            problems.append(
                {
                    "trace_id": trace.trace_id,
                    "requirement_id": trace.requirement_id,
                    "code": "covered_without_review",
                    "detail": "Une liaison automatique « pending » ne peut pas être « covered ».",
                }
            )
    problems.sort(key=lambda item: (item["trace_id"], item["code"]))
    return problems


def audit_report(traces: Iterable[RequirementTrace]) -> dict[str, Any]:
    """Return the complete audit report of the registry."""
    items = list(traces)
    return {
        "summary": coverage_summary(items),
        "by_offer": coverage_by_offer(items),
        "by_cv": coverage_by_cv(items),
        "gaps": critical_gaps(items),
        "waived": waived_requirements(items),
        "superseded": superseded_requirements(items),
        "timeline": history_timeline(items, limit=1000),
        "evolution": coverage_over_time(items),
        "inconsistencies": _inconsistencies(items),
    }


def search_traces(
    traces: Iterable[RequirementTrace],
    query: str,
    *,
    limit: int = 50,
) -> list[RequirementTrace]:
    """Return the traces whose text matches a free-text query."""
    needle = normalized_text(query)
    if not needle:
        return []
    matches = [
        trace
        for trace in traces
        if needle in normalized_text(trace.requirement_text)
        or needle in normalized_text(trace.requirement_id)
        or needle in normalized_text(trace.evidence_quote or "")
        or any(needle in normalized_text(tag) for tag in trace.tags)
    ]
    bounded = max(0, int(limit or 0))
    return matches[:bounded] if bounded else matches
