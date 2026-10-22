"""Graphe de dépendances déterministe et analyse d'impact locale (SPEC-013).

Le module est volontairement **pur** : aucun réseau, aucune horloge implicite,
aucun modèle.  Un même graphe et un même changement produisent toujours le
même résultat, ce qui rend les scénarios ``what-if`` reproductibles.

Sémantique des arêtes
---------------------
Une arête ``source_id -> target_id`` porte une relation nommée par
``edge_type``.  La propagation d'un changement suit la relation :

* ``requires`` et ``derives_from`` : ``source`` dépend de ``target`` ; un
  changement de ``target`` remonte donc vers ``source`` (ex. une exigence
  ``requires`` une offre : supprimer l'offre impacte l'exigence).
* ``provides``, ``validates`` et ``enables`` : ``source`` alimente ``target`` ;
  un changement de ``source`` descend vers ``target`` (ex. une preuve
  ``validates`` une exigence).
* ``contradicts`` et ``blocks`` : relation bidirectionnelle, propagée dans les
  deux sens avec le poids de l'arête.

Les niveaux d'impact sont **prudentiels** : ``critical``, ``high``, ``medium``,
``low`` puis ``none``.  Aucun résultat ne prétend qu'une entité est « cassée de
façon certaine » : il s'agit d'un risque à vérifier.
"""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import math
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

NODE_TYPES: tuple[str, ...] = (
    "requirement",
    "evidence",
    "offer",
    "profile",
    "application",
    "matching",
    "skill",
    "certification",
)
NodeType = Literal[
    "requirement",
    "evidence",
    "offer",
    "profile",
    "application",
    "matching",
    "skill",
    "certification",
]

EDGE_TYPES: tuple[str, ...] = (
    "requires",
    "provides",
    "validates",
    "contradicts",
    "derives_from",
    "blocks",
    "enables",
)
EdgeType = Literal[
    "requires",
    "provides",
    "validates",
    "contradicts",
    "derives_from",
    "blocks",
    "enables",
]

CHANGE_TYPES: tuple[str, ...] = (
    "create",
    "update",
    "delete",
    "status_change",
    "link",
    "unlink",
)
ChangeType = Literal["create", "update", "delete", "status_change", "link", "unlink"]

IMPACT_LEVELS: tuple[str, ...] = ("none", "low", "medium", "high", "critical")
ImpactLevel = Literal["none", "low", "medium", "high", "critical"]
EFFORT_LEVELS: tuple[str, ...] = ("trivial", "low", "medium", "high", "blocking")
EffortLevel = Literal["trivial", "low", "medium", "high", "blocking"]

# Seuils de propagation : un score cumulé inférieur au seuil devient ``none``.
DEFAULT_THRESHOLD = 0.15
DEFAULT_MAX_DEPTH = 6
DEFAULT_PROPAGATION_SCORE = 0.0

_CHANGE_SEVERITY: dict[str, float] = {
    "delete": 1.0,
    "unlink": 0.9,
    "status_change": 0.8,
    "update": 0.7,
    "link": 0.55,
    "create": 0.45,
}

_FORWARD_EDGE_TYPES = frozenset({"provides", "validates", "enables"})
_REVERSE_EDGE_TYPES = frozenset({"requires", "derives_from"})
_BIDIRECTIONAL_EDGE_TYPES = frozenset({"contradicts", "blocks"})

_LEVEL_RANK = {level: index for index, level in enumerate(IMPACT_LEVELS)}
_EFFORT_RANK = {level: index for index, level in enumerate(EFFORT_LEVELS)}

_NODE_LABELS: dict[str, str] = {
    "requirement": "Exigence",
    "evidence": "Preuve",
    "offer": "Offre",
    "profile": "Profil",
    "application": "Candidature",
    "matching": "Matching",
    "skill": "Compétence",
    "certification": "Certification",
}

_EDGE_LABELS: dict[str, str] = {
    "requires": "requiert",
    "provides": "fournit",
    "validates": "valide",
    "contradicts": "contredit",
    "derives_from": "dérive de",
    "blocks": "bloque",
    "enables": "permet",
}

# Estimation d'effort par niveau et par type d'entité.  Ce n'est pas une durée
# prometteuse : c'est une charge relative, affichée comme telle dans l'UI.
_EFFORT_BY_LEVEL: dict[str, str] = {
    "critical": "blocking",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "none": "trivial",
}


def utc_now() -> str:
    """Horodatage explicite, réservé à la persistance (jamais utilisé par les calculs)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _clean(value: Any, limit: int = 400) -> str:
    text = str(value if value is not None else "").replace("\x00", "").strip()
    return text[:limit]


def _slug(value: Any, limit: int = 80) -> str:
    text = _clean(value, limit)
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-._").lower()
    return text[:limit]


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _coerce_weight(value: Any, default: float = 1.0) -> float:
    try:
        weight = float(value)
    except (TypeError, ValueError):
        weight = default
    if math.isnan(weight) or math.isinf(weight):
        return default
    return round(min(max(weight, 0.0), 1.0), 4)


def _coerce_node_type(value: Any) -> str:
    text = _clean(value, 40).lower()
    return text if text in NODE_TYPES else "requirement"


def _coerce_edge_type(value: Any) -> str:
    text = _clean(value, 40).lower()
    return text if text in EDGE_TYPES else "requires"


def node_id_for(node_type: str, raw: Any, *, label: Any = "", fallback_seed: str = "") -> str:
    """Canonicalise un identifiant ``type:clé`` sans inventer de contenu.

    Un identifiant déjà préfixé et valide est conservé tel quel.  Sinon le
    préfixe du type est ajouté.  Si aucune clé n'est fournie, la clé est un
    hachage stable du libellé (ou de ``fallback_seed``), jamais un compteur
    implicite qui rendrait deux constructions différentes non comparables.
    """
    kind = _coerce_node_type(node_type)
    text = _clean(raw, 160)
    if ":" in text:
        prefix, remainder = text.split(":", 1)
        if prefix in NODE_TYPES and _clean(remainder):
            return f"{prefix}:{_clean(remainder, 140)}"
    if text:
        return f"{kind}:{text}"
    seed = _clean(label, 200) or _clean(fallback_seed, 200) or kind
    return f"{kind}:{_stable_key(seed)}"


def edge_id_for(source_id: str, edge_type: str, target_id: str) -> str:
    """Identifiant stable d'une arête, indépendant de l'ordre d'insertion."""
    return f"edge:{_stable_key(f'{source_id}|{edge_type}|{target_id}')}"


def impact_level_for_score(score: float, *, threshold: float = DEFAULT_THRESHOLD) -> str:
    """Traduit un score cumulé en niveau prudentiel, sans binaire pass/fail."""
    if score < threshold:
        return "none"
    if score >= 0.80:
        return "critical"
    if score >= 0.55:
        return "high"
    if score >= 0.30:
        return "medium"
    return "low"


def effort_for_impact(level: str, node_type: str = "") -> str:
    """Charge relative d'un nœud impacté (approximation explicitement affichée)."""
    effort = _EFFORT_BY_LEVEL.get(level, "trivial")
    if node_type in {"application", "offer"} and effort in {"medium", "high"}:
        # Une candidature ou une offre touchée demande une vérification
        # humaine supplémentaire (dates, documents, suivi).
        return "blocking" if effort == "high" else effort
    return effort


@dataclass
class DependencyNode:
    node_id: str
    node_type: NodeType
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "label": self.label,
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DependencyNode":
        return cls(
            node_id=_clean(payload.get("node_id"), 180),
            node_type=_coerce_node_type(payload.get("node_type")),  # type: ignore[arg-type]
            label=_clean(payload.get("label"), 240),
            metadata=copy.deepcopy(payload.get("metadata") or {}),
        )


@dataclass
class DependencyEdge:
    edge_id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "weight": self.weight,
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DependencyEdge":
        edge_type = _coerce_edge_type(payload.get("edge_type"))
        source_id = _clean(payload.get("source_id"), 180)
        target_id = _clean(payload.get("target_id"), 180)
        return cls(
            edge_id=_clean(payload.get("edge_id"), 180) or edge_id_for(source_id, edge_type, target_id),
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,  # type: ignore[arg-type]
            weight=_coerce_weight(payload.get("weight")),
            metadata=copy.deepcopy(payload.get("metadata") or {}),
        )


@dataclass
class DependencyGraph:
    nodes: dict[str, DependencyNode] = field(default_factory=dict)
    edges: list[DependencyEdge] = field(default_factory=list)
    version: int = 0
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {key: self.nodes[key].to_dict() for key in sorted(self.nodes)},
            "edges": [edge.to_dict() for edge in _sorted_edges(self.edges)],
            "version": int(self.version),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "DependencyGraph":
        payload = payload or {}
        nodes: dict[str, DependencyNode] = {}
        for raw in (payload.get("nodes") or {}).values() if isinstance(payload.get("nodes"), dict) else payload.get("nodes") or []:
            node = DependencyNode.from_dict(raw)
            if node.node_id:
                nodes[node.node_id] = node
        edges = [DependencyEdge.from_dict(raw) for raw in payload.get("edges") or [] if isinstance(raw, dict)]
        try:
            version = int(payload.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        return cls(nodes=nodes, edges=edges, version=max(version, 0), updated_at=_clean(payload.get("updated_at"), 64))

    def copy(self) -> "DependencyGraph":
        return DependencyGraph.from_dict(self.to_dict())

    def add_node(self, node: DependencyNode) -> DependencyNode:
        self.nodes[node.node_id] = node
        return node

    def add_edge(
        self,
        *,
        source_id: str,
        target_id: str,
        edge_type: str,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> DependencyEdge:
        """Ajoute (ou renforce) une arête sans doublonner un même triplet."""
        source_id = _clean(source_id, 180)
        target_id = _clean(target_id, 180)
        edge_type = _coerce_edge_type(edge_type)
        normalized_weight = _coerce_weight(weight)
        for existing in self.edges:
            if (
                existing.source_id == source_id
                and existing.target_id == target_id
                and existing.edge_type == edge_type
            ):
                existing.weight = max(existing.weight, normalized_weight)
                if metadata:
                    existing.metadata.update(copy.deepcopy(metadata))
                return existing
        edge = DependencyEdge(
            edge_id=edge_id_for(source_id, edge_type, target_id),
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,  # type: ignore[arg-type]
            weight=normalized_weight,
            metadata=copy.deepcopy(metadata or {}),
        )
        self.edges.append(edge)
        return edge

    def remove_edge(self, edge_id: str) -> bool:
        before = len(self.edges)
        self.edges = [edge for edge in self.edges if edge.edge_id != edge_id]
        return len(self.edges) != before

    def remove_node(self, node_id: str) -> bool:
        if node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        self.edges = [
            edge for edge in self.edges if edge.source_id != node_id and edge.target_id != node_id
        ]
        return True

    def neighbors(self, node_id: str) -> dict[str, list[str]]:
        incoming = sorted(edge.source_id for edge in self.edges if edge.target_id == node_id)
        outgoing = sorted(edge.target_id for edge in self.edges if edge.source_id == node_id)
        return {"incoming": incoming, "outgoing": outgoing}

    def edge_for(self, edge_id: str) -> DependencyEdge | None:
        for edge in self.edges:
            if edge.edge_id == edge_id:
                return edge
        return None


@dataclass
class ImpactNode:
    node_id: str
    impact_level: ImpactLevel
    impact_reasons: list[str] = field(default_factory=list)
    affected_paths: list[list[str]] = field(default_factory=list)
    estimated_effort: EffortLevel = "trivial"

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "impact_level": self.impact_level,
            "impact_reasons": list(self.impact_reasons),
            "affected_paths": [list(path) for path in self.affected_paths],
            "estimated_effort": self.estimated_effort,
        }


@dataclass
class ImpactAnalysis:
    source_node_id: str
    change_type: ChangeType
    change_details: dict[str, Any] = field(default_factory=dict)
    impacted_nodes: list[ImpactNode] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    propagation_depth: int = 0
    estimated_total_effort: EffortLevel = "trivial"
    breaking_changes: list[str] = field(default_factory=list)
    recommended_order: list[str] = field(default_factory=list)
    rollback_plan: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_node_id": self.source_node_id,
            "change_type": self.change_type,
            "change_details": copy.deepcopy(self.change_details),
            "impacted_nodes": [node.to_dict() for node in self.impacted_nodes],
            "critical_path": list(self.critical_path),
            "propagation_depth": int(self.propagation_depth),
            "estimated_total_effort": self.estimated_total_effort,
            "breaking_changes": list(self.breaking_changes),
            "recommended_order": list(self.recommended_order),
            "rollback_plan": list(self.rollback_plan),
        }


@dataclass
class ExecutionStep:
    step_id: str
    node_id: str
    label: str
    action: str
    depends_on: list[str] = field(default_factory=list)
    estimated_effort: EffortLevel = "low"
    parallel_group: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "node_id": self.node_id,
            "label": self.label,
            "action": self.action,
            "depends_on": list(self.depends_on),
            "estimated_effort": self.estimated_effort,
            "parallel_group": int(self.parallel_group),
            "reason": self.reason,
        }


@dataclass
class ExecutionPlan:
    steps: list[ExecutionStep] = field(default_factory=list)
    parallel_groups: list[list[str]] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    estimated_duration: str = ""
    rollback_triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "parallel_groups": [list(group) for group in self.parallel_groups],
            "critical_path": list(self.critical_path),
            "estimated_duration": self.estimated_duration,
            "rollback_triggers": list(self.rollback_triggers),
        }


def _sorted_edges(edges: Iterable[DependencyEdge]) -> list[DependencyEdge]:
    return sorted(edges, key=lambda edge: (edge.source_id, edge.edge_type, edge.target_id, edge.edge_id))


def _node_label(node_type: str, raw_label: Any, node_id: str) -> str:
    label = _clean(raw_label, 240)
    if label:
        return label
    key = node_id.split(":", 1)[1] if ":" in node_id else node_id
    return f"{_NODE_LABELS.get(node_type, 'Entité')} {key}"


def _iter_records(value: Any, kind_field: str = "id") -> list[dict[str, Any]]:
    """Accepte une liste de dicts ou un mapping ``id -> dict`` (comme l'API)."""
    if not value:
        return []
    if isinstance(value, dict):
        records: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                record = dict(item)
                record.setdefault(kind_field, key)
                records.append(record)
        return records
    return [dict(item) for item in value if isinstance(item, dict)]


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;\n]", value) if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [_clean(item, 160) for item in value if _clean(item, 160)]
    return []


def build_graph(
    *,
    offers: Any = None,
    requirements: Any = None,
    evidences: Any = None,
    matchings: Any = None,
    applications: Any = None,
    profile: dict[str, Any] | None = None,
    merges: Any = None,
    splits: Any = None,
    manual_edges: Any = None,
    updated_at: str = "",
) -> DependencyGraph:
    """Construit un graphe à partir des entités locales connues.

    Les entrées sont des dictionnaires déjà locaux, sans E/S.  Les règles
    reproduisent les ponts demandés par SPEC-013 : exigences (SK-02), preuves
    (SK-10), matchings (SK-21), candidatures (SK-11), fusions/scissions de
    preuves (SK-08), puis liens manuels.  Une donnée incomplète crée un nœud
    explicite dont le libellé dit qu'elle est à compléter ; aucune valeur n'est
    inventée.
    """
    graph = DependencyGraph(updated_at=_clean(updated_at, 64))

    # --- Profil ---------------------------------------------------------
    if profile:
        profile_id = node_id_for("profile", profile.get("id") or profile.get("profile_id") or "primary", label="profil")
        graph.add_node(
            DependencyNode(
                node_id=profile_id,
                node_type="profile",
                label=_node_label("profile", profile.get("display_name") or profile.get("label"), profile_id),
                metadata={
                    "updated_at": _clean(profile.get("updated_at"), 64),
                    "fields_present": sorted(
                        key for key in ("education", "experience", "skills", "languages") if _clean(profile.get(key), 2_000)
                    ),
                },
            )
        )
    else:
        profile_id = ""

    # --- Offres ---------------------------------------------------------
    offer_ids: dict[str, str] = {}
    for index, offer in enumerate(_iter_records(offers)):
        raw_id = offer.get("id") or offer.get("offer_id") or offer.get("source_id")
        offer_id = node_id_for("offer", raw_id, label=offer.get("title"), fallback_seed=f"offer-{index}")
        offer_ids[_clean(raw_id, 160)] = offer_id
        offer_ids[_clean(offer.get("id"), 160)] = offer_id
        graph.add_node(
            DependencyNode(
                node_id=offer_id,
                node_type="offer",
                label=_node_label(
                    "offer",
                    " · ".join(part for part in (_clean(offer.get("company"), 160), _clean(offer.get("title"), 160)) if part),
                    offer_id,
                ),
                metadata={
                    "company": _clean(offer.get("company"), 160),
                    "title": _clean(offer.get("title"), 160),
                    "source_status": _clean(offer.get("source_status"), 40),
                    "deadline_date": _clean(offer.get("deadline_date"), 32),
                },
            )
        )

    # --- Compétences et exigences --------------------------------------
    requirement_ids: dict[str, str] = {}
    for index, requirement in enumerate(_iter_records(requirements)):
        raw_id = requirement.get("id") or requirement.get("requirement_id")
        requirement_id = node_id_for("requirement", raw_id, label=requirement.get("text"), fallback_seed=f"req-{index}")
        requirement_ids[_clean(raw_id, 160)] = requirement_id
        requirement_ids[_clean(requirement.get("id"), 160)] = requirement_id
        graph.add_node(
            DependencyNode(
                node_id=requirement_id,
                node_type="requirement",
                label=_node_label("requirement", requirement.get("text") or requirement.get("label"), requirement_id),
                metadata={
                    "category": _clean(requirement.get("category"), 80),
                    "modality": _clean(requirement.get("modality"), 40),
                    "criticality": _clean(requirement.get("criticality"), 40) or "unknown",
                    "confidence": _clean(requirement.get("confidence"), 40),
                    "offer_id": _clean(requirement.get("offer_id"), 160),
                },
            )
        )
        offer_key = _clean(requirement.get("offer_id"), 160)
        if offer_key:
            offer_id = offer_ids.get(offer_key) or node_id_for("offer", offer_key)
            if offer_id not in graph.nodes:
                graph.add_node(
                    DependencyNode(
                        node_id=offer_id,
                        node_type="offer",
                        label=f"Offre {offer_key}",
                        metadata={"incomplete": True, "reason": "référencée par une exigence"},
                    )
                )
            # L'exigence dépend de l'offre : supprimer l'offre remonte vers elle.
            graph.add_edge(source_id=requirement_id, target_id=offer_id, edge_type="requires", weight=0.9)
        for skill in _str_list(requirement.get("skills") or requirement.get("skill")):
            skill_id = node_id_for("skill", _slug(skill), label=skill)
            if skill_id not in graph.nodes:
                graph.add_node(
                    DependencyNode(
                        node_id=skill_id,
                        node_type="skill",
                        label=skill,
                        metadata={"incomplete": identity_is_missing(requirement.get("skills"))},
                    )
                )
            graph.add_edge(source_id=requirement_id, target_id=skill_id, edge_type="provides", weight=0.7)

    # --- Preuves --------------------------------------------------------
    evidence_ids: dict[str, str] = {}
    for index, evidence in enumerate(_iter_records(evidences)):
        raw_id = evidence.get("id") or evidence.get("evidence_id")
        evidence_id = node_id_for("evidence", raw_id, label=evidence.get("title") or evidence.get("text"), fallback_seed=f"evidence-{index}")
        evidence_ids[_clean(raw_id, 160)] = evidence_id
        evidence_ids[_clean(evidence.get("id"), 160)] = evidence_id
        graph.add_node(
            DependencyNode(
                node_id=evidence_id,
                node_type="evidence",
                label=_node_label("evidence", evidence.get("title") or evidence.get("label") or evidence.get("text"), evidence_id),
                metadata={
                    "quality": _clean(evidence.get("quality") or evidence.get("evidence_quality"), 40),
                    "expires_at": _clean(evidence.get("expires_at"), 32),
                    "source": _clean(evidence.get("source"), 120),
                },
            )
        )
        for target in _str_list(evidence.get("validates") or evidence.get("requirement_ids")):
            target_id = requirement_ids.get(target) or node_id_for("requirement", target)
            if target_id not in graph.nodes:
                graph.add_node(
                    DependencyNode(
                        node_id=target_id,
                        node_type="requirement",
                        label=f"Exigence {target}",
                        metadata={"incomplete": True, "reason": "référencée par une preuve"},
                    )
                )
            graph.add_edge(
                source_id=evidence_id,
                target_id=target_id,
                edge_type="validates",
                weight=_coerce_weight(evidence.get("weight"), 0.8),
            )
        if profile_id and evidence.get("profile_field"):
            graph.add_edge(
                source_id=profile_id,
                target_id=evidence_id,
                edge_type="validates",
                weight=0.6,
                metadata={"profile_field": _clean(evidence.get("profile_field"), 80)},
            )

    # --- Matchings ------------------------------------------------------
    for index, matching in enumerate(_iter_records(matchings)):
        raw_id = matching.get("id") or matching.get("matching_id")
        matching_id = node_id_for("matching", raw_id, label=matching.get("label"), fallback_seed=f"matching-{index}")
        graph.add_node(
            DependencyNode(
                node_id=matching_id,
                node_type="matching",
                label=_node_label("matching", matching.get("label"), matching_id),
                metadata={
                    "score": _coerce_weight(matching.get("score")),
                    "source": _clean(matching.get("source"), 80),
                },
            )
        )
        requirement_key = _clean(matching.get("requirement_id"), 160)
        evidence_key = _clean(matching.get("evidence_id"), 160)
        if requirement_key:
            requirement_id = requirement_ids.get(requirement_key) or node_id_for("requirement", requirement_key)
            if requirement_id not in graph.nodes:
                graph.add_node(
                    DependencyNode(
                        node_id=requirement_id,
                        node_type="requirement",
                        label=f"Exigence {requirement_key}",
                        metadata={"incomplete": True, "reason": "référencée par un matching"},
                    )
                )
            graph.add_edge(
                source_id=matching_id,
                target_id=requirement_id,
                edge_type="derives_from",
                weight=max(_coerce_weight(matching.get("score")), 0.1),
            )
        if evidence_key:
            evidence_id = evidence_ids.get(evidence_key) or node_id_for("evidence", evidence_key)
            if evidence_id not in graph.nodes:
                graph.add_node(
                    DependencyNode(
                        node_id=evidence_id,
                        node_type="evidence",
                        label=f"Preuve {evidence_key}",
                        metadata={"incomplete": True, "reason": "référencée par un matching"},
                    )
                )
            graph.add_edge(
                source_id=matching_id,
                target_id=evidence_id,
                edge_type="derives_from",
                weight=max(_coerce_weight(matching.get("score")), 0.1),
            )

    # --- Candidatures ---------------------------------------------------
    for index, application in enumerate(_iter_records(applications)):
        raw_id = application.get("id") or application.get("application_id")
        application_id = node_id_for("application", raw_id, label=application.get("label"), fallback_seed=f"application-{index}")
        graph.add_node(
            DependencyNode(
                node_id=application_id,
                node_type="application",
                label=_node_label(
                    "application",
                    application.get("label")
                    or " · ".join(
                        part
                        for part in (
                            _clean(application.get("company"), 160),
                            _clean(application.get("title"), 160),
                        )
                        if part
                    ),
                    application_id,
                ),
                metadata={
                    "stage": _clean(application.get("stage"), 80),
                    "job_id": _clean(application.get("job_id"), 160),
                },
            )
        )
        if profile_id:
            graph.add_edge(source_id=application_id, target_id=profile_id, edge_type="requires", weight=0.6)
        job_key = _clean(application.get("job_id"), 160)
        if job_key:
            offer_id = offer_ids.get(job_key) or node_id_for("offer", job_key)
            if offer_id not in graph.nodes:
                graph.add_node(
                    DependencyNode(
                        node_id=offer_id,
                        node_type="offer",
                        label=f"Offre {job_key}",
                        metadata={"incomplete": True, "reason": "référencée par une candidature"},
                    )
                )
            graph.add_edge(source_id=application_id, target_id=offer_id, edge_type="requires", weight=0.9)
        for evidence_key in _str_list(application.get("evidence_ids") or application.get("evidence_id")):
            evidence_id = evidence_ids.get(evidence_key) or node_id_for("evidence", evidence_key)
            if evidence_id not in graph.nodes:
                graph.add_node(
                    DependencyNode(
                        node_id=evidence_id,
                        node_type="evidence",
                        label=f"Preuve {evidence_key}",
                        metadata={"incomplete": True, "reason": "référencée par une candidature"},
                    )
                )
            graph.add_edge(source_id=application_id, target_id=evidence_id, edge_type="requires", weight=0.7)

    # --- Fusions / scissions de preuves (SK-08) -------------------------
    for raw in _iter_records(merges):
        merged_key = _clean(raw.get("merged_id") or raw.get("target_id") or raw.get("id"), 160)
        source_keys = _str_list(raw.get("source_ids") or raw.get("sources"))
        if not merged_key:
            continue
        merged_id = evidence_ids.get(merged_key) or node_id_for("evidence", merged_key)
        for source_key in source_keys:
            source_id = evidence_ids.get(source_key) or node_id_for("evidence", source_key)
            # La preuve fusionnée dépend de ses sources.
            graph.add_edge(source_id=merged_id, target_id=source_id, edge_type="derives_from", weight=0.8)
    for raw in _iter_records(splits):
        original_key = _clean(raw.get("original_id") or raw.get("source_id") or raw.get("id"), 160)
        new_keys = _str_list(raw.get("new_ids") or raw.get("targets"))
        if not original_key:
            continue
        original_id = evidence_ids.get(original_key) or node_id_for("evidence", original_key)
        for new_key in new_keys:
            new_id = evidence_ids.get(new_key) or node_id_for("evidence", new_key)
            # La nouvelle preuve dérive de l'originale.
            graph.add_edge(source_id=new_id, target_id=original_id, edge_type="derives_from", weight=0.8)

    # --- Liens manuels --------------------------------------------------
    for raw in _iter_records(manual_edges):
        source_id = _clean(raw.get("source_id") or raw.get("source"), 180)
        target_id = _clean(raw.get("target_id") or raw.get("target"), 180)
        if not source_id or not target_id:
            continue
        if raw.get("source_type"):
            source_id = node_id_for(raw.get("source_type"), source_id)
        if raw.get("target_type"):
            target_id = node_id_for(raw.get("target_type"), target_id)
        graph.add_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=raw.get("edge_type") or raw.get("type") or "requires",
            weight=_coerce_weight(raw.get("weight"), 0.5),
            metadata={"manual": True, **_clean_metadata(raw.get("metadata"))},
        )

    # Les arêtes qui pointent vers un nœud inconnu restent visibles pour que
    # la validation puisse les signaler ; aucun nœud fantôme n'est fabriqué.
    graph.updated_at = _clean(updated_at, 64)
    return graph


def identity_is_missing(value: Any) -> bool:
    """Petit utilitaire lisible : la donnée est-elle absente (et non « zéro ») ?"""
    return value is None or (isinstance(value, (str, list, tuple, set, dict)) and len(value) == 0)


def _clean_metadata(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _propagation_targets(graph: DependencyGraph, node_id: str) -> list[tuple[str, DependencyEdge]]:
    """Retourne (voisin, arête) dans le sens de propagation du changement."""
    targets: list[tuple[str, DependencyEdge]] = []
    for edge in _sorted_edges(graph.edges):
        if edge.edge_type in _FORWARD_EDGE_TYPES and edge.source_id == node_id:
            targets.append((edge.target_id, edge))
        elif edge.edge_type in _REVERSE_EDGE_TYPES and edge.target_id == node_id:
            targets.append((edge.source_id, edge))
        elif edge.edge_type in _BIDIRECTIONAL_EDGE_TYPES:
            if edge.source_id == node_id:
                targets.append((edge.target_id, edge))
            elif edge.target_id == node_id:
                targets.append((edge.source_id, edge))
    return targets


def _edge_reason(parent_id: str, child_id: str, edge: DependencyEdge, score: float) -> str:
    relation = _EDGE_LABELS.get(edge.edge_type, edge.edge_type)
    if edge.edge_type in {"validates", "provides", "enables"}:
        direction = f"« {parent_id} » {relation} « {child_id} »"
    elif edge.edge_type in {"requires", "derives_from"}:
        direction = f"« {child_id} » {relation} « {parent_id} »"
    else:
        direction = f"relation « {relation} » entre « {parent_id} » et « {child_id} »"
    return f"Atteint via {direction} (poids {edge.weight:.2f}, score cumulé {score:.2f})."


def analyze_impact(
    graph: DependencyGraph,
    source_node_id: str,
    change_type: str,
    change_details: dict[str, Any] | None = None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_paths: int = 3,
) -> ImpactAnalysis:
    """Propage un changement et produit une analyse d'impact pondérée.

    L'algorithme est un parcours en largeur avec relaxation du meilleur score
    (``score = score_parent × poids``).  La profondeur et le seuil sont bornés,
    et un nœud déjà visité ne l'est jamais deux fois : un cycle ne boucle donc
    pas.  Le résultat est trié pour être identique quel que soit l'ordre
    d'insertion des arêtes.
    """
    change_type = _clean(change_type, 40).lower()
    if change_type not in CHANGE_TYPES:
        raise ValueError(
            f"Type de changement inconnu : {change_type!r}. Valeurs acceptées : {', '.join(CHANGE_TYPES)}."
        )
    if source_node_id not in graph.nodes:
        raise KeyError(f"Nœud source inconnu dans le graphe : {source_node_id!r}.")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    threshold = min(max(threshold, 0.0), 1.0)
    try:
        max_depth = int(max_depth)
    except (TypeError, ValueError):
        max_depth = DEFAULT_MAX_DEPTH
    max_depth = max(0, min(max_depth, 32))

    severity = _CHANGE_SEVERITY[change_type]
    best_score: dict[str, float] = {source_node_id: severity}
    best_depth: dict[str, int] = {source_node_id: 0}
    best_paths: dict[str, list[list[str]]] = {source_node_id: [[source_node_id]]}
    parent_edge: dict[str, DependencyEdge] = {}
    parent_node: dict[str, str] = {}

    queue: list[tuple[float, int, str]] = [(-severity, 0, source_node_id)]
    while queue:
        negative_score, depth, current = heapq.heappop(queue)
        score = -negative_score
        if score < best_score.get(current, -1.0) - 1e-12:
            continue
        if depth >= max_depth:
            continue
        for neighbor, edge in _propagation_targets(graph, current):
            if neighbor not in graph.nodes:
                continue
            candidate = round(score * edge.weight, 6)
            if candidate < threshold:
                continue
            candidate_depth = depth + 1
            previous = best_score.get(neighbor)
            if previous is not None and candidate < previous - 1e-12:
                continue
            improved = previous is None or candidate > previous + 1e-12
            if improved:
                best_score[neighbor] = candidate
                best_depth[neighbor] = candidate_depth
                parent_edge[neighbor] = edge
                parent_node[neighbor] = current
            paths = best_paths.setdefault(neighbor, [])
            for path in best_paths.get(current, [[current]]):
                if len(path) > max_depth:
                    continue
                candidate_path = [*path, neighbor]
                if candidate_path not in paths:
                    paths.append(candidate_path)
            paths.sort(key=lambda item: (len(item), item))
            del paths[max_paths:]
            if improved:
                heapq.heappush(queue, (-candidate, candidate_depth, neighbor))

    impacted: list[ImpactNode] = []
    for node_id in sorted(best_score):
        if node_id == source_node_id:
            continue
        score = best_score[node_id]
        level = impact_level_for_score(score, threshold=threshold)
        if level == "none":
            continue
        paths = [path for path in best_paths.get(node_id, []) if path]
        reasons = []
        edge = parent_edge.get(node_id)
        parent = parent_node.get(node_id)
        if edge is not None and parent is not None:
            reasons.append(_edge_reason(parent, node_id, edge, score))
        if len(paths) > 1:
            reasons.append(f"{len(paths)} chemins d'impact connus ; le plus court est affiché.")
        node = graph.nodes.get(node_id)
        impacted.append(
            ImpactNode(
                node_id=node_id,
                impact_level=level,  # type: ignore[arg-type]
                impact_reasons=reasons or ["Impact déduit d'une dépendance directe."],
                affected_paths=paths,
                estimated_effort=effort_for_impact(level, node.node_type if node else ""),  # type: ignore[arg-type]
            )
        )

    impacted.sort(key=lambda item: (best_depth.get(item.node_id, 0), item.node_id))
    propagation_depth = max((best_depth.get(item.node_id, 0) for item in impacted), default=0)

    critical_path: list[str] = [source_node_id]
    critical_candidates = [item for item in impacted if item.affected_paths]
    if critical_candidates:
        best = min(
            critical_candidates,
            key=lambda item: (
                -best_score.get(item.node_id, 0.0),
                -best_depth.get(item.node_id, 0),
                item.affected_paths[0],
            ),
        )
        critical_path = list(best.affected_paths[0])

    recommended_order = [source_node_id]
    ordered = sorted(
        impacted,
        key=lambda item: (best_depth.get(item.node_id, 0), -best_score.get(item.node_id, 0.0), item.node_id),
    )
    recommended_order.extend(item.node_id for item in ordered)

    breaking_changes: list[str] = []
    if change_type in {"delete", "unlink"}:
        for item in ordered:
            if item.impact_level in {"critical", "high"}:
                node = graph.nodes.get(item.node_id)
                label = node.label if node else item.node_id
                breaking_changes.append(
                    f"Le changement « {change_type} » sur « {source_node_id} » fragilise « {label} » ({item.impact_level})."
                )

    total_effort = "trivial"
    for item in impacted:
        if _EFFORT_RANK[item.estimated_effort] > _EFFORT_RANK[total_effort]:
            total_effort = item.estimated_effort

    rollback_plan = [
        "1. Créer un snapshot du graphe avant toute application (POST /dependencies/snapshot).",
    ]
    for index, node_id in enumerate(reversed(recommended_order), start=2):
        node = graph.nodes.get(node_id)
        label = node.label if node else node_id
        rollback_plan.append(f"{index}. Restaurer « {label} » ({node_id}) depuis le snapshot précédent si l'étape échoue.")
    rollback_plan.append(
        f"{len(rollback_plan) + 1}. Revalider le graphe (POST /dependencies/validate) et rejouer l'impact avant de poursuivre."
    )

    return ImpactAnalysis(
        source_node_id=source_node_id,
        change_type=change_type,  # type: ignore[arg-type]
        change_details=copy.deepcopy(change_details or {}),
        impacted_nodes=impacted,
        critical_path=critical_path,
        propagation_depth=propagation_depth,
        estimated_total_effort=total_effort,  # type: ignore[arg-type]
        breaking_changes=breaking_changes,
        recommended_order=recommended_order,
        rollback_plan=rollback_plan,
    )


def _adjacency(graph: DependencyGraph, *, directed: bool = False) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in sorted(graph.nodes)}
    for edge in graph.edges:
        if edge.source_id not in adjacency or edge.target_id not in adjacency:
            continue
        adjacency[edge.source_id].add(edge.target_id)
        if not directed:
            adjacency[edge.target_id].add(edge.source_id)
    return adjacency


def detect_cycles(graph: DependencyGraph) -> list[list[str]]:
    """Détecte les cycles orientés avec Tarjan (composantes fortement connexes).

    Chaque cycle retourné est une liste de nœuds sans répétition du premier.
    Les auto-boucles sont retournées sous la forme ``["x"]``.  L'ordre est
    stable : cycles triés par taille décroissante puis par contenu.
    """
    adjacency = _adjacency(graph, directed=True)
    index_counter = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index_counter
        indexes[node] = index_counter
        lowlinks[node] = index_counter
        index_counter += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in sorted(adjacency.get(node, ())):
            if neighbor not in indexes:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[neighbor])
        if lowlinks[node] == indexes[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))
            elif component and component[0] in adjacency.get(component[0], ()):  # auto-boucle
                components.append([component[0]])

    for node in sorted(adjacency):
        if node not in indexes:
            strongconnect(node)

    return sorted(components, key=lambda cycle: (-len(cycle), cycle))


def cycle_resolutions(graph: DependencyGraph, cycles: list[list[str]] | None = None) -> list[dict[str, Any]]:
    """Propose de retirer l'arête la plus faible de chaque cycle.

    Une proposition n'est jamais appliquée automatiquement : elle indique
    seulement quelle dépendance semble la moins structurante.
    """
    cycles = cycles if cycles is not None else detect_cycles(graph)
    proposals: list[dict[str, Any]] = []
    for cycle in cycles:
        members = set(cycle)
        internal = [
            edge
            for edge in graph.edges
            if edge.source_id in members and edge.target_id in members
        ]
        if not internal:
            proposals.append(
                {
                    "cycle": list(cycle),
                    "edge_id": None,
                    "reason": "Cycle détecté sans arête interne lisible ; vérifier les identifiants.",
                }
            )
            continue
        weakest = min(internal, key=lambda edge: (edge.weight, edge.source_id, edge.edge_type, edge.target_id))
        proposals.append(
            {
                "cycle": list(cycle),
                "edge_id": weakest.edge_id,
                "source_id": weakest.source_id,
                "target_id": weakest.target_id,
                "edge_type": weakest.edge_type,
                "weight": weakest.weight,
                "reason": "Arête la plus faible du cycle : candidate à requalifier ou supprimer après revue.",
            }
        )
    return proposals


def betweenness_centrality(graph: DependencyGraph) -> dict[str, float]:
    """Centralité d'intermédiation (Brandes) sur le graphe non orienté sous-jacent."""
    adjacency = _adjacency(graph, directed=False)
    nodes = sorted(adjacency)
    centrality = {node: 0.0 for node in nodes}
    for source in nodes:
        predecessors: dict[str, list[str]] = {node: [] for node in nodes}
        sigma: dict[str, float] = {node: 0.0 for node in nodes}
        sigma[source] = 1.0
        distance: dict[str, int] = {source: 0}
        queue: deque[str] = deque([source])
        order: list[str] = []
        while queue:
            current = queue.popleft()
            order.append(current)
            for neighbor in sorted(adjacency.get(current, ())):
                if neighbor not in distance:
                    distance[neighbor] = distance[current] + 1
                    queue.append(neighbor)
                if distance.get(neighbor) == distance[current] + 1:
                    sigma[neighbor] += sigma[current]
                    predecessors[neighbor].append(current)
        dependency = {node: 0.0 for node in nodes}
        while order:
            current = order.pop()
            for predecessor in predecessors[current]:
                if sigma[current]:
                    dependency[predecessor] += (sigma[predecessor] / sigma[current]) * (1.0 + dependency[current])
            if current != source:
                centrality[current] += dependency[current]
    count = len(nodes)
    if count > 2:
        scale = 1.0 / ((count - 1) * (count - 2))
        centrality = {node: value * scale for node, value in centrality.items()}
    return {node: round(value, 6) for node, value in centrality.items()}


def pagerank(graph: DependencyGraph, *, damping: float = 0.85, iterations: int = 40) -> dict[str, float]:
    """PageRank déterministe, pondéré par les arêtes (direction conservée)."""
    nodes = sorted(graph.nodes)
    if not nodes:
        return {}
    rank = {node: 1.0 / len(nodes) for node in nodes}
    outgoing: dict[str, list[tuple[str, float]]] = {node: [] for node in nodes}
    for edge in sorted(graph.edges, key=lambda item: (item.source_id, item.target_id, item.edge_id)):
        if edge.source_id in outgoing and edge.target_id in graph.nodes:
            outgoing[edge.source_id].append((edge.target_id, max(edge.weight, 0.0001)))
    for _ in range(max(1, iterations)):
        updated = {node: (1.0 - damping) / len(nodes) for node in nodes}
        dangling = sum(rank[node] for node in nodes if not outgoing[node])
        if dangling:
            share = damping * dangling / len(nodes)
            updated = {node: value + share for node, value in updated.items()}
        for node in nodes:
            total_weight = sum(weight for _, weight in outgoing[node])
            if not total_weight:
                continue
            for target, weight in outgoing[node]:
                updated[target] += damping * rank[node] * weight / total_weight
        rank = updated
    return {node: round(value, 8) for node, value in rank.items()}


def articulation_points(graph: DependencyGraph) -> list[str]:
    """Points d'articulation du graphe non orienté (candidats single point of failure)."""
    adjacency = _adjacency(graph, directed=False)
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    points: set[str] = set()
    counter = 0

    def visit(node: str) -> None:
        nonlocal counter
        discovery[node] = low[node] = counter
        counter += 1
        children = 0
        for neighbor in sorted(adjacency.get(node, ())):
            if neighbor not in discovery:
                parent[neighbor] = node
                children += 1
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
                if parent.get(node) is None and children > 1:
                    points.add(node)
                if parent.get(node) is not None and low[neighbor] >= discovery[node]:
                    points.add(node)
            elif neighbor != parent.get(node):
                low[node] = min(low[node], discovery[neighbor])

    for node in sorted(adjacency):
        if node not in discovery:
            parent[node] = None
            visit(node)
    return sorted(points)


def _component_count(adjacency: dict[str, set[str]], *, removed: str | None = None) -> int:
    remaining = [node for node in sorted(adjacency) if node != removed and adjacency[node]]
    seen: set[str] = set()
    count = 0
    for node in remaining:
        if node in seen:
            continue
        count += 1
        queue = deque([node])
        seen.add(node)
        while queue:
            current = queue.popleft()
            for neighbor in adjacency.get(current, ()):
                if neighbor != removed and neighbor not in seen and adjacency.get(neighbor):
                    seen.add(neighbor)
                    queue.append(neighbor)
    return count


def critical_nodes(graph: DependencyGraph, *, top_n: int = 10) -> list[dict[str, Any]]:
    """Classe les nœuds par criticité structurelle (centralité + PageRank + SPOF)."""
    betweenness = betweenness_centrality(graph)
    ranks = pagerank(graph)
    points = set(articulation_points(graph))
    adjacency = _adjacency(graph, directed=False)
    base_components = max(_component_count(adjacency), 1)
    max_between = max(betweenness.values(), default=0.0) or 1.0
    max_rank = max(ranks.values(), default=0.0) or 1.0
    results: list[dict[str, Any]] = []
    for node_id, node in sorted(graph.nodes.items()):
        between = betweenness.get(node_id, 0.0)
        rank = ranks.get(node_id, 0.0)
        is_point = node_id in points
        components_after = _component_count(adjacency, removed=node_id) if is_point else base_components
        score = 0.45 * (between / max_between) + 0.45 * (rank / max_rank) + (0.10 if is_point else 0.0)
        reasons: list[str] = []
        if is_point:
            reasons.append(
                f"Point d'articulation : son retrait sépare le graphe en {components_after} composante(s)."
            )
        if between:
            reasons.append(f"Centralité d'intermédiation : {between:.3f}.")
        if rank:
            reasons.append(f"Influence PageRank : {rank:.4f}.")
        if not reasons:
            reasons.append("Nœud isolé ou peu connecté : aucune dépendance structurelle notable.")
        results.append(
            {
                "node_id": node_id,
                "node_type": node.node_type,
                "label": node.label,
                "score": round(min(score, 1.0), 6),
                "betweenness": between,
                "pagerank": rank,
                "single_point_of_failure": is_point,
                "components_after_removal": components_after,
                "reasons": reasons,
            }
        )
    results.sort(key=lambda item: (-item["score"], item["node_id"]))
    return results[: max(0, int(top_n))] if top_n else results


def fragility_report(graph: DependencyGraph, *, top_n: int = 10) -> dict[str, Any]:
    """Rapport de fragilité : SPOF, nœuds critiques, isolats et cycles."""
    critical = critical_nodes(graph, top_n=top_n)
    adjacency = _adjacency(graph, directed=False)
    isolated = sorted(node_id for node_id, neighbors in adjacency.items() if not neighbors)
    points = [item for item in critical if item["single_point_of_failure"]]
    cycles = detect_cycles(graph)
    return {
        "graph_version": graph.version,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "single_points_of_failure": points,
        "critical_nodes": critical,
        "isolated_nodes": isolated,
        "cycles": cycles,
        "cycle_count": len(cycles),
        "disclaimer": (
            "La criticité est structurelle (centralité, PageRank, articulation) et ne préjuge "
            "ni d'une panne certaine ni de la gravité réelle d'un changement."
        ),
    }


def validate_graph(graph: DependencyGraph) -> list[dict[str, Any]]:
    """Contrôle de cohérence non destructif ; retourne des problèmes actionnables."""
    issues: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    for node_id, node in sorted(graph.nodes.items()):
        if ":" not in node_id:
            issues.append(
                {
                    "code": "node_id_format",
                    "severity": "warning",
                    "node_id": node_id,
                    "message": "Identifiant sans préfixe de type : le nœud reste lisible mais n'est pas canonicalisé.",
                }
            )
        else:
            prefix = node_id.split(":", 1)[0]
            if prefix in NODE_TYPES and prefix != node.node_type:
                issues.append(
                    {
                        "code": "node_type_mismatch",
                        "severity": "error",
                        "node_id": node_id,
                        "message": f"Le préfixe « {prefix} » ne correspond pas au type « {node.node_type} ».",
                    }
                )
        if not _clean(node.label):
            issues.append(
                {
                    "code": "empty_label",
                    "severity": "warning",
                    "node_id": node_id,
                    "message": "Libellé vide : l'entité sera affichée par son identifiant.",
                }
            )
    for edge in graph.edges:
        if edge.edge_id in seen_edges:
            issues.append(
                {
                    "code": "duplicate_edge_id",
                    "severity": "error",
                    "edge_id": edge.edge_id,
                    "message": "Deux arêtes partagent le même identifiant.",
                }
            )
        seen_edges.add(edge.edge_id)
        if edge.source_id not in graph.nodes:
            issues.append(
                {
                    "code": "dangling_source",
                    "severity": "error",
                    "edge_id": edge.edge_id,
                    "message": f"Source inconnue : {edge.source_id}.",
                }
            )
        if edge.target_id not in graph.nodes:
            issues.append(
                {
                    "code": "dangling_target",
                    "severity": "error",
                    "edge_id": edge.edge_id,
                    "message": f"Cible inconnue : {edge.target_id}.",
                }
            )
        if edge.source_id == edge.target_id:
            issues.append(
                {
                    "code": "self_loop",
                    "severity": "warning",
                    "edge_id": edge.edge_id,
                    "message": "Boucle sur soi-même : à confirmer, elle fausse la lecture de propagation.",
                }
            )
        if not (0.0 <= edge.weight <= 1.0):
            issues.append(
                {
                    "code": "weight_out_of_range",
                    "severity": "error",
                    "edge_id": edge.edge_id,
                    "message": "Le poids doit être compris entre 0 et 1.",
                }
            )
    if not graph.nodes:
        issues.append(
            {
                "code": "empty_graph",
                "severity": "warning",
                "node_id": None,
                "message": "Le graphe est vide : construis-le depuis les entités locales avant d'analyser un impact.",
            }
        )
    for cycle in detect_cycles(graph):
        issues.append(
            {
                "code": "cycle",
                "severity": "warning",
                "node_id": cycle[0],
                "message": f"Cycle détecté : {' → '.join(cycle)} → {cycle[0]}.",
            }
        )
    return issues


def graph_validation(graph: DependencyGraph) -> dict[str, Any]:
    issues = validate_graph(graph)
    errors = [issue for issue in issues if issue["severity"] == "error"]
    warnings = [issue for issue in issues if issue["severity"] == "warning"]
    return {
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues,
    }


def _order_edges(graph: DependencyGraph, subset: set[str]) -> dict[str, set[str]]:
    """Arêtes « prérequis -> dépendant » limitées à un sous-ensemble."""
    order: dict[str, set[str]] = {node_id: set() for node_id in subset}
    for edge in graph.edges:
        if edge.source_id not in subset or edge.target_id not in subset:
            continue
        if edge.edge_type in _FORWARD_EDGE_TYPES:
            order[edge.source_id].add(edge.target_id)
        elif edge.edge_type in _REVERSE_EDGE_TYPES:
            order[edge.target_id].add(edge.source_id)
    return order


def build_execution_plan(
    graph: DependencyGraph,
    node_ids: Iterable[str],
    *,
    action: str = "apply",
) -> ExecutionPlan:
    """Produit un plan ordonné, ses groupes parallèles et son chemin critique.

    L'ordre suit les dépendances réelles : un prérequis passe avant le nœud qui
    en dépend.  Les nœuds sans contrainte mutuelle partagent un groupe
    parallèle.  En présence d'un cycle, les nœuds restants sont placés dans un
    dernier groupe et signalés dans le motif de l'étape.
    """
    requested = [node_id for node_id in dict.fromkeys(_clean(item, 180) for item in node_ids)]
    subset = {node_id for node_id in requested if node_id in graph.nodes}
    if not subset:
        return ExecutionPlan(
            estimated_duration="0 étape",
            rollback_triggers=["Aucun nœud valide fourni : rien n'est exécuté."],
        )

    order = _order_edges(graph, subset)
    indegree = {node_id: 0 for node_id in subset}
    for targets in order.values():
        for target in targets:
            indegree[target] += 1

    groups: list[list[str]] = []
    remaining = set(subset)
    group_index = 0
    while remaining:
        ready = sorted(node for node in remaining if indegree.get(node, 0) == 0)
        if not ready:
            ready = sorted(remaining)
            cycle_note = "cycle résiduel : ordre imposé par identifiant, à revoir manuellement"
        else:
            cycle_note = ""
        groups.append(ready)
        for node in ready:
            remaining.discard(node)
            for target in order.get(node, ()):
                indegree[target] = max(0, indegree.get(target, 0) - 1)
        group_index += 1
        if group_index > len(subset) + 1:
            break

    group_of: dict[str, int] = {}
    for index, group in enumerate(groups):
        for node_id in group:
            group_of[node_id] = index

    steps: list[ExecutionStep] = []
    for node_id in sorted(subset, key=lambda item: (group_of.get(item, 0), item)):
        node = graph.nodes[node_id]
        dependencies = sorted(
            prerequisite
            for prerequisite, targets in order.items()
            if node_id in targets and prerequisite in subset
        )
        steps.append(
            ExecutionStep(
                step_id=f"step-{len(steps) + 1:02d}",
                node_id=node_id,
                label=node.label,
                action=_clean(action, 40) or "apply",
                depends_on=dependencies,
                estimated_effort=effort_for_impact(
                    "high" if node.node_type in {"requirement", "application"} else "medium",
                    node.node_type,
                ),  # type: ignore[arg-type]
                parallel_group=group_of.get(node_id, 0),
                reason=(
                    "Étape ordonnée par les dépendances du sous-graphe."
                    if not cycle_note
                    else f"Étape ordonnée par identifiant ({cycle_note})."
                ),
            )
        )

    critical_path = _longest_path(graph, order, subset)
    total_rank = sum(_EFFORT_RANK.get(step.estimated_effort, 0) + 1 for step in steps)
    return ExecutionPlan(
        steps=steps,
        parallel_groups=[list(group) for group in groups],
        critical_path=critical_path,
        estimated_duration=f"≈ {len(steps)} étape(s) · charge relative {total_rank} unité(s)",
        rollback_triggers=[
            "Une étape échoue ou un contrôle de cohérence devient rouge.",
            "Un nœud marqué single point of failure est supprimé sans remplacement.",
            "Le graphe obtenu contient un cycle non arbitré.",
        ],
    )


def _longest_path(graph: DependencyGraph, order: dict[str, set[str]], subset: set[str]) -> list[str]:
    """Plus long chemin du sous-graphe de dépendances, départ déterministe."""
    memo: dict[str, list[str]] = {}

    def longest_from(node_id: str, stack: set[str]) -> list[str]:
        if node_id in memo:
            return memo[node_id]
        if node_id in stack:
            return [node_id]
        best: list[str] = [node_id]
        for target in sorted(order.get(node_id, ())):
            if target not in subset:
                continue
            candidate = [node_id, *longest_from(target, stack | {node_id})]
            if len(candidate) > len(best) or (len(candidate) == len(best) and candidate < best):
                best = candidate
        memo[node_id] = best
        return best

    candidates = [longest_from(node_id, set()) for node_id in sorted(subset)]
    if not candidates:
        return []
    return min(candidates, key=lambda path: (-len(path), path))


def graph_from_json(payload: Any) -> DependencyGraph:
    """Charge un graphe depuis du JSON déjà local, avec erreur explicite."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("Le graphe doit être un objet JSON.")
    return DependencyGraph.from_dict(payload)


def graph_to_json(graph: DependencyGraph, *, indent: int | None = None) -> str:
    return json.dumps(graph.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)
