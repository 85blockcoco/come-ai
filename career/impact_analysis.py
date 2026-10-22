"""Moteur d'analyse d'impact et de scénarios ``what-if`` (SPEC-013).

Ce module ajoute à :mod:`career.dependencies` trois couches :

* l'**application pure** d'un changement à une copie du graphe (jamais au
  graphe d'origine) ;
* la **simulation multi-changements** : chaque changement est analysé puis
  appliqué, ce qui permet de comparer « supprimer cette preuve » et « ajouter
  cette preuve » avant toute écriture ;
* un **façade** :class:`ImpactEngine` pour les routes et l'UI.

Aucun scénario n'est appliqué automatiquement.  Aucun résultat n'est un
verdict : ce sont des risques et des charges de travail à relire.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Iterable

from .dependencies import (
    CHANGE_TYPES,
    DEFAULT_MAX_DEPTH,
    DEFAULT_THRESHOLD,
    EFFORT_LEVELS,
    IMPACT_LEVELS,
    DependencyGraph,
    DependencyNode,
    ExecutionPlan,
    ImpactAnalysis,
    ImpactLevel,
    ImpactNode,
    _EFFORT_RANK,
    _LEVEL_RANK,
    _clean,
    _coerce_node_type,
    _coerce_weight,
    analyze_impact,
    build_execution_plan,
    critical_nodes,
    cycle_resolutions,
    detect_cycles,
    effort_for_impact,
    fragility_report,
    graph_validation,
    node_id_for,
    validate_graph,
)


@dataclass
class ScenarioSimulation:
    """Résultat agrégé de plusieurs changements simulés sur une copie du graphe."""

    graph_version: int = 0
    changes: list[dict[str, Any]] = field(default_factory=list)
    analyses: list[ImpactAnalysis] = field(default_factory=list)
    impacted_nodes: list[ImpactNode] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    propagation_depth: int = 0
    estimated_total_effort: str = "trivial"
    breaking_changes: list[str] = field(default_factory=list)
    recommended_order: list[str] = field(default_factory=list)
    rollback_plan: list[str] = field(default_factory=list)
    net_effect: str = ""
    applied_graph: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = (
        "Simulation uniquement : aucun changement n'est appliqué au graphe persistant. "
        "Les niveaux d'impact sont des risques à vérifier, pas des certitudes."
    )

    def to_dict(self, *, include_graph: bool = False) -> dict[str, Any]:
        payload = {
            "graph_version": int(self.graph_version),
            "changes": copy.deepcopy(self.changes),
            "analyses": [analysis.to_dict() for analysis in self.analyses],
            "impacted_nodes": [node.to_dict() for node in self.impacted_nodes],
            "critical_path": list(self.critical_path),
            "propagation_depth": int(self.propagation_depth),
            "estimated_total_effort": self.estimated_total_effort,
            "breaking_changes": list(self.breaking_changes),
            "recommended_order": list(self.recommended_order),
            "rollback_plan": list(self.rollback_plan),
            "net_effect": self.net_effect,
            "disclaimer": self.disclaimer,
        }
        if include_graph:
            payload["applied_graph"] = copy.deepcopy(self.applied_graph)
        return payload


def _normalized_change(change: Any) -> dict[str, Any]:
    if not isinstance(change, dict):
        raise ValueError("Un changement doit être un objet {change_type, node_id, details}.")
    normalized = copy.deepcopy(change)
    change_type = _clean(normalized.get("change_type") or normalized.get("type"), 40).lower()
    if change_type not in CHANGE_TYPES:
        raise ValueError(
            f"Type de changement inconnu : {change_type!r}. Valeurs acceptées : {', '.join(CHANGE_TYPES)}."
        )
    normalized["change_type"] = change_type
    node_id = _clean(
        normalized.get("node_id") or normalized.get("source_node_id") or normalized.get("source"),
        180,
    )
    if node_id:
        normalized["node_id"] = node_id
    details = normalized.get("details")
    normalized["details"] = copy.deepcopy(details) if isinstance(details, dict) else {}
    return normalized


def apply_change(graph: DependencyGraph, change: Any) -> DependencyGraph:
    """Applique un changement à une **copie** et retourne le nouveau graphe.

    Le graphe reçu n'est jamais muté.  Les identifiants sont canonicalisés avec
    le préfixe du type lorsqu'il est fourni.  Un changement impossible lève
    ``ValueError``/``KeyError`` : mieux vaut un refus explicite qu'un scénario
    silencieusement faux.
    """
    normalized = _normalized_change(change)
    updated = graph.copy()
    change_type = normalized["change_type"]
    details = normalized.get("details") or {}
    node_id = normalized.get("node_id") or _clean(details.get("node_id"), 180)
    node_type = _coerce_node_type(details.get("node_type") or normalized.get("node_type"))

    if change_type == "create":
        if not node_id:
            raise ValueError("Une création exige un node_id (ou details.node_id).")
        node_id = node_id_for(node_type, node_id)
        existing = updated.nodes.get(node_id)
        if existing is None:
            updated.add_node(
                DependencyNode(
                    node_id=node_id,
                    node_type=node_type,  # type: ignore[arg-type]
                    label=_clean(details.get("label") or normalized.get("label"), 240) or node_id,
                    metadata=copy.deepcopy(details.get("metadata") or {}),
                )
            )
        else:
            if details.get("label"):
                existing.label = _clean(details.get("label"), 240)
            if isinstance(details.get("metadata"), dict):
                existing.metadata.update(copy.deepcopy(details["metadata"]))
        return updated

    if not node_id:
        raise ValueError(f"Un changement « {change_type} » exige un node_id.")
    if node_id not in updated.nodes:
        raise KeyError(f"Nœud inconnu dans le graphe : {node_id!r}.")

    node = updated.nodes[node_id]
    if change_type == "delete":
        updated.remove_node(node_id)
    elif change_type == "update":
        if details.get("label"):
            node.label = _clean(details.get("label"), 240)
        if isinstance(details.get("metadata"), dict):
            node.metadata.update(copy.deepcopy(details["metadata"]))
    elif change_type == "status_change":
        node.metadata["previous_status"] = node.metadata.get("status") or node.metadata.get("stage", "")
        node.metadata["status"] = _clean(details.get("status") or details.get("new_status"), 80) or "unknown"
    elif change_type == "link":
        source_id = _clean(details.get("source_id") or normalized.get("source_id") or node_id, 180)
        target_id = _clean(details.get("target_id") or normalized.get("target_id"), 180)
        if not target_id:
            raise ValueError("Un lien exige une cible (details.target_id).")
        if source_id not in updated.nodes:
            raise KeyError(f"Nœud source inconnu : {source_id!r}.")
        if target_id not in updated.nodes:
            raise KeyError(f"Nœud cible inconnu : {target_id!r}.")
        updated.add_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=details.get("edge_type") or "requires",
            weight=_coerce_weight(details.get("weight"), 0.5),
            metadata=copy.deepcopy(details.get("metadata") or {"simulated": True}),
        )
    elif change_type == "unlink":
        edge_id = _clean(details.get("edge_id") or normalized.get("edge_id"), 180)
        removed = False
        if edge_id:
            removed = updated.remove_edge(edge_id)
        else:
            source_id = _clean(details.get("source_id") or node_id, 180)
            target_id = _clean(details.get("target_id"), 180)
            edge_type = _clean(details.get("edge_type"), 40)
            before = len(updated.edges)
            updated.edges = [
                edge
                for edge in updated.edges
                if not (
                    edge.source_id == source_id
                    and (not target_id or edge.target_id == target_id)
                    and (not edge_type or edge.edge_type == edge_type)
                )
            ]
            removed = len(updated.edges) != before
        if not removed:
            raise KeyError("Aucune arête ne correspond au déliage demandé.")
    return updated


def apply_changes(graph: DependencyGraph, changes: Iterable[Any]) -> DependencyGraph:
    """Applique une séquence de changements à une copie, dans l'ordre fourni."""
    working = graph.copy()
    for change in changes:
        working = apply_change(working, change)
    return working


def _merge_impact_nodes(nodes: Iterable[ImpactNode]) -> list[ImpactNode]:
    merged: dict[str, ImpactNode] = {}
    for node in nodes:
        previous = merged.get(node.node_id)
        if previous is None:
            merged[node.node_id] = ImpactNode(
                node_id=node.node_id,
                impact_level=node.impact_level,
                impact_reasons=list(node.impact_reasons),
                affected_paths=[list(path) for path in node.affected_paths],
                estimated_effort=node.estimated_effort,
            )
            continue
        if _LEVEL_RANK[node.impact_level] > _LEVEL_RANK[previous.impact_level]:
            previous.impact_level = node.impact_level
            previous.estimated_effort = node.estimated_effort
        for reason in node.impact_reasons:
            if reason not in previous.impact_reasons:
                previous.impact_reasons.append(reason)
        for path in node.affected_paths:
            if path not in previous.affected_paths:
                previous.affected_paths.append(path)
        previous.affected_paths.sort(key=lambda item: (len(item), item))
        del previous.affected_paths[3:]
    return sorted(merged.values(), key=lambda item: (-_LEVEL_RANK[item.impact_level], item.node_id))


def simulate_scenarios(
    graph: DependencyGraph,
    changes: Iterable[Any],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
    include_applied_graph: bool = False,
) -> ScenarioSimulation:
    """Simule plusieurs changements sans modifier le graphe d'origine.

    Une création est appliquée avant son analyse (le nœud doit exister) ; une
    suppression ou un déliage est analysé avant d'être appliqué (sinon le
    nœud/arête n'existe plus).  Les autres changements suivent le même ordre :
    analyse de l'état courant, puis application pour le changement suivant.
    """
    normalized = [_normalized_change(change) for change in changes]
    if not normalized:
        raise ValueError("Aucun changement fourni : le scénario serait vide.")
    if len(normalized) > 50:
        raise ValueError("Un scénario est limité à 50 changements pour rester lisible.")

    working = graph.copy()
    analyses: list[ImpactAnalysis] = []
    for change in normalized:
        change_type = change["change_type"]
        node_id = change.get("node_id") or _clean((change.get("details") or {}).get("node_id"), 180)
        if change_type == "create":
            working = apply_change(working, change)
            source_id = node_id_for(
                _coerce_node_type((change.get("details") or {}).get("node_type")),
                node_id,
            )
            analyses.append(
                analyze_impact(
                    working,
                    source_id,
                    "create",
                    change.get("details") or {},
                    threshold=threshold,
                    max_depth=max_depth,
                )
            )
            continue
        if not node_id or node_id not in working.nodes:
            raise KeyError(f"Nœud inconnu dans le scénario : {node_id!r}.")
        analyses.append(
            analyze_impact(
                working,
                node_id,
                change_type,
                change.get("details") or {},
                threshold=threshold,
                max_depth=max_depth,
            )
        )
        working = apply_change(working, change)

    impacted = _merge_impact_nodes(node for analysis in analyses for node in analysis.impacted_nodes)
    depth = max((analysis.propagation_depth for analysis in analyses), default=0)
    total_effort = "trivial"
    for node in impacted:
        if _EFFORT_RANK[node.estimated_effort] > _EFFORT_RANK[total_effort]:
            total_effort = node.estimated_effort

    recommended_order: list[str] = []
    for analysis in analyses:
        for node_id in analysis.recommended_order:
            if node_id not in recommended_order:
                recommended_order.append(node_id)

    breaking: list[str] = []
    for analysis in analyses:
        for message in analysis.breaking_changes:
            if message not in breaking:
                breaking.append(message)

    rollback: list[str] = []
    for analysis in analyses:
        for step in analysis.rollback_plan:
            if step not in rollback:
                rollback.append(step)

    critical_path: list[str] = []
    for analysis in analyses:
        if len(analysis.critical_path) > len(critical_path):
            critical_path = list(analysis.critical_path)

    net_effect = (
        f"{len(normalized)} changement(s) simulé(s) · {len(impacted)} nœud(s) impacté(s) · "
        f"profondeur maximale {depth} · charge relative {total_effort}."
    )
    if any(change["change_type"] == "create" for change in normalized):
        net_effect += " Une création peut réduire une dépendance, sans l'effacer automatiquement."
    if breaking:
        net_effect += f" {len(breaking)} rupture(s) potentielle(s) à relire."

    return ScenarioSimulation(
        graph_version=graph.version,
        changes=normalized,
        analyses=analyses,
        impacted_nodes=impacted,
        critical_path=critical_path,
        propagation_depth=depth,
        estimated_total_effort=total_effort,
        breaking_changes=breaking,
        recommended_order=recommended_order,
        rollback_plan=rollback,
        net_effect=net_effect,
        applied_graph=working.to_dict() if include_applied_graph else {},
    )


class ImpactEngine:
    """Façade légère autour d'un graphe, sans état persistant propre."""

    def __init__(
        self,
        graph: DependencyGraph,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ):
        self.graph = graph
        self.threshold = threshold
        self.max_depth = max_depth

    def analyze(
        self,
        source_node_id: str,
        change_type: str,
        change_details: dict[str, Any] | None = None,
    ) -> ImpactAnalysis:
        return analyze_impact(
            self.graph,
            source_node_id,
            change_type,
            change_details,
            threshold=self.threshold,
            max_depth=self.max_depth,
        )

    def simulate(self, changes: Iterable[Any], *, include_applied_graph: bool = False) -> ScenarioSimulation:
        return simulate_scenarios(
            self.graph,
            changes,
            threshold=self.threshold,
            max_depth=self.max_depth,
            include_applied_graph=include_applied_graph,
        )

    def plan(self, node_ids: Iterable[str], *, action: str = "apply") -> ExecutionPlan:
        return build_execution_plan(self.graph, node_ids, action=action)

    def critical(self, *, top_n: int = 10) -> list[dict[str, Any]]:
        return critical_nodes(self.graph, top_n=top_n)

    def fragility(self, *, top_n: int = 10) -> dict[str, Any]:
        report = fragility_report(self.graph, top_n=top_n)
        report["cycle_resolutions"] = cycle_resolutions(self.graph, report.get("cycles"))
        return report

    def cycles(self) -> dict[str, Any]:
        cycles = detect_cycles(self.graph)
        return {"cycles": cycles, "count": len(cycles), "resolutions": cycle_resolutions(self.graph, cycles)}

    def validate(self) -> dict[str, Any]:
        return graph_validation(self.graph)


__all__ = [
    "EFFORT_LEVELS",
    "IMPACT_LEVELS",
    "ExecutionPlan",
    "ImpactEngine",
    "ImpactLevel",
    "ScenarioSimulation",
    "apply_change",
    "apply_changes",
    "build_execution_plan",
    "detect_cycles",
    "effort_for_impact",
    "simulate_scenarios",
    "validate_graph",
]
