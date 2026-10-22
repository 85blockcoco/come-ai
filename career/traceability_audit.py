"""Rapports d'audit du registre de traçabilité — SPEC-011 (CVBOOST-46).

Ce module ne fait **aucun accès au disque** : il transforme des exigences
et des événements (dataclasses) en rapports lisibles et recalculables.  Les
mêmes entrées produisent toujours le même rapport.

LES SIX RAPPORTS
----------------
============================= ==========================================
Rapport                       Fonction
============================= ==========================================
Couverture par offre          :func:`coverage_by_offer`
Couverture par CV             :func:`coverage_by_cv`
Gaps critiques                :func:`critical_gaps`
Historique des changements    :func:`change_timeline`
Exigences dérogées            :func:`waived_requirements`
Évolution dans le temps       :func:`evolution`
============================= ==========================================

DÉFINITIONS (explicites, pour que les chiffres se discutent)
------------------------------------------------------------
* **applicable** : les exigences qui ne sont pas dérogées.  Une exigence
  dérogée (``waived``) est retirée du dénominateur : elle a été excusée,
  elle n'attend pas de preuve.
* **couverture** : part des exigences *applicables* dont le statut est
  ``covered``.  Le taux est ``None`` quand il n'y a aucune exigence
  applicable — jamais ``0`` (zéro exigerait de l'appliquer) ni ``1`` (le
  laisser à ``None`` évite de faire croire à une couverture parfaite).
* **gap critique** : une exigence ``mandatory`` dont le statut n'est pas
  ``covered``.  ``partial`` et ``contradicted`` en font donc partie : une
  couverture partielle n'est pas une couverture.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .traceability import RequirementTrace, TraceEvent, event_to_dict, trace_to_dict


#: Statuts considérés comme « couvert » pour le taux de couverture.
COVERED_STATUSES = frozenset({"covered"})

#: Statuts qui comptent comme un gap sur une exigence obligatoire.
GAP_STATUSES = frozenset({"uncovered", "partial", "contradicted"})


def _counts(traces: Sequence[RequirementTrace]) -> dict[str, Any]:
    """Compteurs bruts d'un lot d'exigences."""
    counters = {
        "total": len(traces),
        "covered": 0,
        "partial": 0,
        "uncovered": 0,
        "contradicted": 0,
        "waived": 0,
    }
    for trace in traces:
        if trace.status in counters:
            counters[trace.status] += 1
    applicable = counters["total"] - counters["waived"]
    counters["applicable"] = applicable
    counters["coverage_rate"] = (
        round(counters["covered"] / applicable, 4) if applicable > 0 else None
    )
    return counters


def _grouped(traces: Iterable[RequirementTrace], key: str) -> dict[str, list[RequirementTrace]]:
    grouped: dict[str, list[RequirementTrace]] = {}
    for trace in traces:
        value = getattr(trace, key, "") or "unknown"
        grouped.setdefault(str(value), []).append(trace)
    return grouped


def coverage_by_offer(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Couverture par offre : part des exigences couverte, gaps et dérogées."""
    report: list[dict[str, Any]] = []
    for offer_id, group in sorted(_grouped(traces, "offer_id").items()):
        counters = _counts(group)
        mandatory = [trace for trace in group if trace.criticality == "mandatory"]
        report.append(
            {
                "offer_id": offer_id,
                **counters,
                "mandatory_total": len(mandatory),
                "mandatory_uncovered": sum(
                    1 for trace in mandatory if trace.status in GAP_STATUSES
                ),
                "waived_requirements": [
                    {
                        "trace_id": trace.trace_id,
                        "requirement_text": trace.requirement_text,
                        "justification": trace.waiver_reason,
                    }
                    for trace in group
                    if trace.status == "waived"
                ],
            }
        )
    return report


def coverage_by_cv(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Couverture par CV : part des exigences du profil prouvées par une preuve."""
    report: list[dict[str, Any]] = []
    for cv_id, group in sorted(_grouped(traces, "cv_id").items()):
        counters = _counts(group)
        report.append(
            {
                "cv_id": cv_id,
                **counters,
                "with_evidence": sum(1 for trace in group if trace.evidence_id),
                "pending_validation": sum(
                    1 for trace in group if trace.evidence_id and not trace.confirmed
                ),
            }
        )
    return report


def critical_gaps(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Exigences obligatoires non couvertes (les plus actionnables d'abord)."""
    gaps: list[dict[str, Any]] = []
    for trace in traces:
        if trace.criticality != "mandatory":
            continue
        if trace.status not in GAP_STATUSES:
            continue
        gaps.append(
            {
                "trace_id": trace.trace_id,
                "requirement_id": trace.requirement_id,
                "requirement_text": trace.requirement_text,
                "offer_id": trace.offer_id,
                "source": trace.source,
                "category": trace.category,
                "criticality": trace.criticality,
                "status": trace.status,
                "locator": trace.locator,
                "source_field": trace.source_field,
                "waiver_reason": trace.waiver_reason,
            }
        )
    gaps.sort(key=lambda gap: (gap["offer_id"], gap["requirement_id"], gap["trace_id"]))
    return gaps


def waived_requirements(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Exigences dérogées, avec leur justification."""
    waived = [
        {
            "trace_id": trace.trace_id,
            "requirement_id": trace.requirement_id,
            "requirement_text": trace.requirement_text,
            "offer_id": trace.offer_id,
            "source": trace.source,
            "criticality": trace.criticality,
            "justification": trace.waiver_reason,
            "updated_at": trace.updated_at,
        }
        for trace in traces
        if trace.status == "waived"
    ]
    waived.sort(key=lambda item: (item["offer_id"], item["requirement_id"], item["trace_id"]))
    return waived


def change_timeline(
    traces: Sequence[RequirementTrace], events: Sequence[TraceEvent] = ()
) -> list[dict[str, Any]]:
    """Chronologie des changements (créations, liaisons, statuts, dérogations).

    Quand le journal global est fourni, il fait seul foi : il contient aussi
    les événements d'exigences supprimées, que les traces vivantes ne
    portent plus.
    """
    if events:
        timeline = [event_to_dict(event) for event in events]
    else:
        seen: set[str] = set()
        timeline = []
        for trace in traces:
            for event in trace.history:
                if event.event_id in seen:
                    continue
                seen.add(event.event_id)
                timeline.append(event_to_dict(event))
    timeline.sort(key=lambda item: (item["timestamp"], item["event_id"]))
    return timeline


def _status_points(trace: RequirementTrace) -> list[tuple[str, str]]:
    """Points (jour, statut) reconstruits depuis l'historique d'une exigence."""
    points: list[tuple[str, str]] = []
    for event in trace.history:
        if event.event_type in {"created", "status_changed", "waived", "reopened"}:
            points.append((event.timestamp[:10], event.new_value or "uncovered"))
    return points


def evolution(traces: Sequence[RequirementTrace]) -> list[dict[str, Any]]:
    """Courbe de couverture dans le temps (un point par jour)."""
    points = {trace.trace_id: _status_points(trace) for trace in traces}
    days: set[str] = set()
    for trace in traces:
        if trace.created_at:
            days.add(trace.created_at[:10])
        for day, _status in points[trace.trace_id]:
            days.add(day)
    series: list[dict[str, Any]] = []
    for day in sorted(days):
        covered = 0
        applicable = 0
        for trace in traces:
            if not trace.created_at or trace.created_at[:10] > day:
                continue
            status = "uncovered"
            for point_day, point_status in points[trace.trace_id]:
                if point_day <= day:
                    status = point_status
            if status == "waived":
                continue
            applicable += 1
            if status in COVERED_STATUSES:
                covered += 1
        series.append(
            {
                "date": day,
                "applicable": applicable,
                "covered": covered,
                "coverage_rate": round(covered / applicable, 4) if applicable > 0 else None,
            }
        )
    return series


def global_summary(traces: Sequence[RequirementTrace]) -> dict[str, Any]:
    """Synthèse globale du registre."""
    counters = _counts(traces)
    by_category = {
        category: len(group) for category, group in sorted(_grouped(traces, "category").items())
    }
    by_criticality = {
        criticality: len(group)
        for criticality, group in sorted(_grouped(traces, "criticality").items())
    }
    by_status = {status: len(group) for status, group in sorted(_grouped(traces, "status").items())}
    return {
        **counters,
        "by_category": by_category,
        "by_criticality": by_criticality,
        "by_status": by_status,
        "offers": len(_grouped(traces, "offer_id")),
        "pending_validation": sum(
            1 for trace in traces if trace.evidence_id and not trace.confirmed
        ),
        "auto_origin_without_proof": sum(
            1 for trace in traces if trace.link_origin == "auto" and not trace.evidence_id
        ),
    }


def build_audit_report(
    traces: Sequence[RequirementTrace], events: Sequence[TraceEvent] = ()
) -> dict[str, Any]:
    """Rapport d'audit complet (une seule passe, tout est recalculé)."""
    return {
        "summary": global_summary(traces),
        "coverage_by_offer": coverage_by_offer(traces),
        "coverage_by_cv": coverage_by_cv(traces),
        "critical_gaps": critical_gaps(traces),
        "waived_requirements": waived_requirements(traces),
        "timeline": change_timeline(traces, events),
        "evolution": evolution(traces),
        "traces": [trace_to_dict(trace) for trace in traces],
    }


__all__ = [
    "COVERED_STATUSES",
    "GAP_STATUSES",
    "build_audit_report",
    "change_timeline",
    "coverage_by_cv",
    "coverage_by_offer",
    "critical_gaps",
    "evolution",
    "global_summary",
    "waived_requirements",
]
