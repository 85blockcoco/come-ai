"""SPEC-013 — dépendances et analyse d'impact : tests synthétiques.

Toutes les entités sont inventées (offre, exigence, preuve, candidature).  Le
module ne fait aucun appel réseau et n'écrit que dans ``tmp_path``.  Les tests
couvrent les neuf ponts demandés, la propagation pondérée, les cycles, la
centralité, les scénarios ``what-if``, la persistance versionnée et les routes
HTTP (alias ``/dependencies`` et ``/api/career/dependencies``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.dependencies import (
    DependencyGraph,
    DependencyNode,
    analyze_impact,
    articulation_points,
    betweenness_centrality,
    build_execution_plan,
    build_graph,
    critical_nodes,
    cycle_resolutions,
    detect_cycles,
    fragility_report,
    graph_from_json,
    graph_to_json,
    graph_validation,
    impact_level_for_score,
    node_id_for,
    pagerank,
    validate_graph,
)
from career.dependencies_store import DependencyStore
from career.impact_analysis import (
    ImpactEngine,
    apply_change,
    apply_changes,
    simulate_scenarios,
)
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


# ---------------------------------------------------------------------------
# Fixtures synthétiques
# ---------------------------------------------------------------------------


def synthetic_entities() -> dict[str, object]:
    return {
        "profile": {
            "id": "profile-demo",
            "display_name": "Personne Démo",
            "education": "Master Finance (démo)",
            "experience": "Projet étudiant chiffré : 12 000 € simulés",
            "skills": "Excel, analyse financière",
            "languages": "Français, anglais C1",
        },
        "offers": [
            {
                "id": "offer-1",
                "company": "Banque de Démo",
                "title": "Stagiaire M&A",
                "source_status": "open",
            }
        ],
        "requirements": [
            {
                "id": "req-excel",
                "text": "Maîtrise avancée d'Excel",
                "offer_id": "offer-1",
                "category": "skill",
                "criticality": "high",
                "skills": ["Excel"],
            },
            {
                "id": "req-english",
                "text": "Anglais professionnel",
                "offer_id": "offer-1",
                "category": "language",
                "criticality": "medium",
                "skills": ["Anglais"],
            },
        ],
        "evidences": [
            {
                "id": "ev-excel",
                "title": "Projet de modélisation Excel",
                "quality": "documented",
                "validates": ["req-excel"],
                "weight": 0.9,
            },
            {
                "id": "ev-english",
                "title": "Certification d'anglais (démo)",
                "quality": "documented",
                "validates": ["req-english"],
                "weight": 0.6,
            },
        ],
        "matchings": [
            {
                "id": "match-1",
                "label": "Matching local démo",
                "requirement_id": "req-excel",
                "evidence_id": "ev-excel",
                "score": 0.9,
            }
        ],
        "applications": [
            {
                "id": "app-1",
                "job_id": "offer-1",
                "company": "Banque de Démo",
                "title": "Stagiaire M&A",
                "stage": "to_prepare",
                "evidence_ids": ["ev-excel"],
            }
        ],
    }


def demo_graph(**overrides: object) -> DependencyGraph:
    payload = synthetic_entities()
    payload.update(overrides)
    return build_graph(**payload)


@pytest.fixture()
def graph() -> DependencyGraph:
    return demo_graph()


class StubService:
    """Service minimal : le routeur n'a besoin que d'un répertoire privé."""

    def __init__(self, root: Path):
        self.data_dir = root / "career_data"


def client_for(service: object) -> TestClient:
    app = FastAPI()
    app.include_router(create_career_router(service))  # type: ignore[arg-type]

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Construction du graphe
# ---------------------------------------------------------------------------


def test_build_graph_creates_all_node_types(graph: DependencyGraph) -> None:
    node_types = {node.node_type for node in graph.nodes.values()}
    assert {"profile", "offer", "requirement", "evidence", "matching", "application", "skill"} <= node_types
    assert len(graph.nodes) == 10
    assert graph.version == 0
    assert graph.updated_at == ""


def test_build_graph_links_requirements_to_offer_and_skills(graph: DependencyGraph) -> None:
    assert any(
        edge.source_id == "requirement:req-excel"
        and edge.target_id == "offer:offer-1"
        and edge.edge_type == "requires"
        for edge in graph.edges
    )
    assert any(
        edge.source_id == "requirement:req-excel"
        and edge.target_id == "skill:excel"
        and edge.edge_type == "provides"
        for edge in graph.edges
    )


def test_build_graph_evidence_validates_requirement(graph: DependencyGraph) -> None:
    edge = next(edge for edge in graph.edges if edge.source_id == "evidence:ev-excel" and edge.target_id == "requirement:req-excel")
    assert edge.edge_type == "validates"
    assert edge.weight == 0.9


def test_build_graph_matching_derives_from_requirement_and_evidence(graph: DependencyGraph) -> None:
    targets = {
        edge.target_id
        for edge in graph.edges
        if edge.source_id == "matching:match-1" and edge.edge_type == "derives_from"
    }
    assert targets == {"requirement:req-excel", "evidence:ev-excel"}


def test_build_graph_application_requires_offer_profile_and_evidence(graph: DependencyGraph) -> None:
    targets = {
        edge.target_id
        for edge in graph.edges
        if edge.source_id == "application:app-1" and edge.edge_type == "requires"
    }
    assert {"offer:offer-1", "profile:profile-demo", "evidence:ev-excel"} <= targets


def test_build_graph_merges_and_splits_evidence() -> None:
    payload = synthetic_entities()
    payload["merges"] = [{"merged_id": "ev-excel", "source_ids": ["ev-english"]}]
    payload["splits"] = [{"original_id": "ev-english", "new_ids": ["ev-excel"]}]
    graph = build_graph(**payload)
    merge_edge = next(
        edge
        for edge in graph.edges
        if edge.source_id == "evidence:ev-excel"
        and edge.target_id == "evidence:ev-english"
        and edge.edge_type == "derives_from"
    )
    split_edge = next(
        edge
        for edge in graph.edges
        if edge.source_id == "evidence:ev-excel"
        and edge.target_id == "evidence:ev-english"
        and edge.edge_type == "derives_from"
    )
    assert merge_edge.weight == 0.8
    assert split_edge.weight == 0.8


def test_build_graph_accepts_manual_edges_and_deduplicates() -> None:
    payload = synthetic_entities()
    payload["manual_edges"] = [
        {
            "source_id": "requirement:req-english",
            "target_id": "requirement:req-excel",
            "edge_type": "enables",
            "weight": 0.4,
        },
        {
            "source_id": "requirement:req-english",
            "target_id": "requirement:req-excel",
            "edge_type": "enables",
            "weight": 0.7,
        },
    ]
    graph = build_graph(**payload)
    edges = [
        edge
        for edge in graph.edges
        if edge.source_id == "requirement:req-english" and edge.target_id == "requirement:req-excel"
    ]
    assert len(edges) == 1
    assert edges[0].weight == 0.7
    assert edges[0].metadata["manual"] is True


def test_build_graph_clamps_weight_and_keeps_unknown_reference_visible() -> None:
    graph = build_graph(
        requirements=[{"id": "req-1", "text": "Exigence", "offer_id": "missing-offer"}],
        evidences=[{"id": "ev-1", "validates": ["unknown-req"], "weight": 9}],
    )
    assert "offer:missing-offer" in graph.nodes
    assert graph.nodes["offer:missing-offer"].metadata["incomplete"] is True
    assert "requirement:unknown-req" in graph.nodes
    edge = next(edge for edge in graph.edges if edge.source_id == "evidence:ev-1")
    assert edge.weight == 1.0


def test_node_id_for_is_canonical_and_deterministic() -> None:
    assert node_id_for("evidence", "ev-1") == "evidence:ev-1"
    assert node_id_for("evidence", "evidence:ev-1") == "evidence:ev-1"
    assert node_id_for("evidence", "", label="Projet Excel") == node_id_for("evidence", "", label="Projet Excel")
    anonymous = node_id_for("profile", "", label="")
    assert anonymous.startswith("profile:") and anonymous == node_id_for("profile", "", label="")


def test_graph_serialization_roundtrip_is_stable(graph: DependencyGraph) -> None:
    payload = graph_to_json(graph)
    restored = graph_from_json(payload)
    assert restored.to_dict() == graph.to_dict()
    assert json.loads(payload)["nodes"] == graph.to_dict()["nodes"]


def test_build_graph_is_independent_of_input_order() -> None:
    first = synthetic_entities()
    second = {key: list(reversed(value)) if isinstance(value, list) else value for key, value in first.items()}
    assert build_graph(**first).to_dict() == build_graph(**second).to_dict()


# ---------------------------------------------------------------------------
# 2. Propagation d'impact
# ---------------------------------------------------------------------------


def test_impact_levels_are_prudential() -> None:
    assert impact_level_for_score(0.0) == "none"
    assert impact_level_for_score(0.20) == "low"
    assert impact_level_for_score(0.31) == "medium"
    assert impact_level_for_score(0.56) == "high"
    assert impact_level_for_score(0.80) == "critical"
    assert impact_level_for_score(0.89, threshold=0.95) == "none"


def test_delete_evidence_propagates_to_requirement_and_skill(graph: DependencyGraph) -> None:
    analysis = analyze_impact(graph, "evidence:ev-excel", "delete")
    levels = {node.node_id: node.impact_level for node in analysis.impacted_nodes}
    assert levels["requirement:req-excel"] == "critical"
    assert levels["skill:excel"] == "high"
    assert analysis.propagation_depth >= 2
    assert analysis.critical_path[0] == "evidence:ev-excel"
    assert analysis.critical_path[-1] in {"skill:excel", "matching:match-1"}
    assert analysis.recommended_order[0] == "evidence:ev-excel"


def test_each_impacted_node_has_reason_path_and_effort(graph: DependencyGraph) -> None:
    analysis = analyze_impact(graph, "evidence:ev-excel", "delete")
    assert analysis.impacted_nodes
    for node in analysis.impacted_nodes:
        assert node.impact_reasons
        assert node.affected_paths
        assert node.affected_paths[0][0] == "evidence:ev-excel"
        assert node.estimated_effort in {"trivial", "low", "medium", "high", "blocking"}


def test_threshold_stops_low_weight_propagation(graph: DependencyGraph) -> None:
    analysis = analyze_impact(graph, "evidence:ev-english", "delete", threshold=0.9)
    assert analysis.impacted_nodes == []
    assert analysis.critical_path == ["evidence:ev-english"]


def test_max_depth_bounds_propagation(graph: DependencyGraph) -> None:
    shallow = analyze_impact(graph, "evidence:ev-excel", "delete", max_depth=1)
    assert {node.node_id for node in shallow.impacted_nodes} == {
        "requirement:req-excel",
        "matching:match-1",
        "application:app-1",
    }
    assert shallow.impacted_nodes[0].affected_paths[0] == ["evidence:ev-excel", shallow.impacted_nodes[0].node_id]


def test_delete_offer_cascades_to_requirement_and_application(graph: DependencyGraph) -> None:
    analysis = analyze_impact(graph, "offer:offer-1", "delete")
    levels = {node.node_id: node.impact_level for node in analysis.impacted_nodes}
    assert levels["requirement:req-excel"] == "critical"
    assert levels["application:app-1"] == "critical"
    assert any("fragilise" in item for item in analysis.breaking_changes)


def test_update_offer_impact_is_lower_than_delete(graph: DependencyGraph) -> None:
    deleted = analyze_impact(graph, "offer:offer-1", "delete")
    updated = analyze_impact(graph, "offer:offer-1", "update")
    assert deleted.impacted_nodes[0].impact_level == "critical"
    assert updated.impacted_nodes[0].impact_level in {"high", "medium"}
    assert all(node.impact_level != "critical" for node in updated.impacted_nodes)


def test_impact_on_cycle_terminates(graph: DependencyGraph) -> None:
    graph.add_edge(source_id="requirement:req-excel", target_id="requirement:req-english", edge_type="requires")
    graph.add_edge(source_id="requirement:req-english", target_id="requirement:req-excel", edge_type="requires")
    analysis = analyze_impact(graph, "requirement:req-excel", "update", max_depth=10)
    assert analysis.impacted_nodes
    assert len({node.node_id for node in analysis.impacted_nodes}) == len(analysis.impacted_nodes)


def test_unknown_source_and_change_type_are_rejected(graph: DependencyGraph) -> None:
    with pytest.raises(KeyError):
        analyze_impact(graph, "evidence:missing", "delete")
    with pytest.raises(ValueError):
        analyze_impact(graph, "evidence:ev-excel", "explode")


def test_apply_change_does_not_mutate_original(graph: DependencyGraph) -> None:
    before = graph.to_dict()
    updated = apply_change(graph, {"change_type": "delete", "node_id": "evidence:ev-excel"})
    assert graph.to_dict() == before
    assert "evidence:ev-excel" not in updated.nodes
    assert all(edge.source_id != "evidence:ev-excel" for edge in updated.edges)


def test_apply_change_update_status_link_and_unlink(graph: DependencyGraph) -> None:
    updated = apply_change(
        graph,
        {"change_type": "update", "node_id": "requirement:req-excel", "details": {"label": "Excel avancé"}},
    )
    assert updated.nodes["requirement:req-excel"].label == "Excel avancé"

    staged = apply_change(
        updated,
        {"change_type": "status_change", "node_id": "application:app-1", "details": {"status": "submitted"}},
    )
    assert staged.nodes["application:app-1"].metadata["status"] == "submitted"
    assert staged.nodes["application:app-1"].metadata["previous_status"] == "to_prepare"

    linked = apply_change(
        staged,
        {
            "change_type": "link",
            "node_id": "requirement:req-excel",
            "details": {
                "source_id": "requirement:req-excel",
                "target_id": "evidence:ev-english",
                "edge_type": "validates",
                "weight": 0.4,
            },
        },
    )
    edge = next(
        edge
        for edge in linked.edges
        if edge.source_id == "requirement:req-excel"
        and edge.target_id == "evidence:ev-english"
        and edge.edge_type == "validates"
    )
    unlinked = apply_change(linked, {"change_type": "unlink", "node_id": "requirement:req-excel", "details": {"edge_id": edge.edge_id}})
    assert unlinked.edge_for(edge.edge_id) is None


def test_apply_changes_sequence_is_deterministic(graph: DependencyGraph) -> None:
    changes = [
        {"change_type": "update", "node_id": "offer:offer-1", "details": {"label": "Offre mise à jour"}},
        {"change_type": "status_change", "node_id": "application:app-1", "details": {"status": "interview"}},
    ]
    assert apply_changes(graph, changes).to_dict() == apply_changes(graph, changes).to_dict()


# ---------------------------------------------------------------------------
# 3. Cycles, centralité, fragilité, validation
# ---------------------------------------------------------------------------


def test_detect_cycles_finds_two_cycle_and_self_loop(graph: DependencyGraph) -> None:
    graph.add_edge(source_id="requirement:req-excel", target_id="requirement:req-english", edge_type="requires")
    graph.add_edge(source_id="requirement:req-english", target_id="requirement:req-excel", edge_type="requires")
    graph.add_edge(source_id="skill:excel", target_id="skill:excel", edge_type="provides")
    cycles = detect_cycles(graph)
    assert ["requirement:req-english", "requirement:req-excel"] in cycles
    assert ["skill:excel"] in cycles
    assert cycles == sorted(cycles, key=lambda cycle: (-len(cycle), cycle))


def test_cycle_resolutions_choose_weakest_edge(graph: DependencyGraph) -> None:
    graph.add_edge(
        source_id="requirement:req-excel",
        target_id="requirement:req-english",
        edge_type="requires",
        weight=0.8,
    )
    graph.add_edge(
        source_id="requirement:req-english",
        target_id="requirement:req-excel",
        edge_type="requires",
        weight=0.2,
    )
    resolutions = cycle_resolutions(graph)
    assert len(resolutions) == 1
    assert resolutions[0]["weight"] == 0.2
    assert resolutions[0]["edge_id"] is not None


def test_betweenness_and_pagerank_are_deterministic(graph: DependencyGraph) -> None:
    assert betweenness_centrality(graph) == betweenness_centrality(graph)
    ranks = pagerank(graph)
    assert ranks == pagerank(graph)
    assert abs(sum(ranks.values()) - 1.0) < 1e-6
    assert max(ranks, key=ranks.get) in graph.nodes


def test_articulation_points_identify_fragile_hub() -> None:
    graph = DependencyGraph()
    for node_id in ("a", "b", "c"):
        graph.add_node(DependencyNode(node_id=f"requirement:{node_id}", node_type="requirement", label=node_id))
    graph.add_edge(source_id="requirement:a", target_id="requirement:b", edge_type="requires")
    graph.add_edge(source_id="requirement:b", target_id="requirement:c", edge_type="requires")
    assert articulation_points(graph) == ["requirement:b"]


def test_critical_nodes_are_ranked_and_explain_their_score(graph: DependencyGraph) -> None:
    ranked = critical_nodes(graph, top_n=5)
    assert ranked
    assert ranked == sorted(ranked, key=lambda item: (-item["score"], item["node_id"]))
    assert ranked[0]["single_point_of_failure"] is True
    assert ranked[0]["reasons"]
    assert 0.0 <= ranked[0]["score"] <= 1.0


def test_fragility_report_contains_spof_and_disclaimer(graph: DependencyGraph) -> None:
    report = fragility_report(graph)
    assert report["node_count"] == len(graph.nodes)
    assert report["single_points_of_failure"]
    assert "préjuge" in report["disclaimer"]
    assert isinstance(report["isolated_nodes"], list)


def test_validate_graph_reports_dangling_edges_and_type_mismatch(graph: DependencyGraph) -> None:
    graph.add_node(DependencyNode(node_id="evidence:bad", node_type="requirement", label="Incohérent"))
    graph.add_edge(source_id="evidence:missing", target_id="requirement:req-excel", edge_type="validates")
    issues = validate_graph(graph)
    codes = {issue["code"] for issue in issues}
    assert "dangling_source" in codes
    assert "node_type_mismatch" in codes
    assert graph_validation(graph)["valid"] is False


def test_validate_clean_graph_has_no_error(graph: DependencyGraph) -> None:
    validation = graph_validation(graph)
    assert validation["valid"] is True
    assert validation["error_count"] == 0


# ---------------------------------------------------------------------------
# 4. Plan d'exécution
# ---------------------------------------------------------------------------


def test_execution_plan_orders_prerequisites_before_dependents(graph: DependencyGraph) -> None:
    plan = build_execution_plan(graph, list(graph.nodes))
    order = [step.node_id for step in plan.steps]
    assert order.index("offer:offer-1") < order.index("requirement:req-excel")
    assert order.index("requirement:req-excel") < order.index("skill:excel")
    assert plan.parallel_groups
    assert sum(len(group) for group in plan.parallel_groups) == len(plan.steps)
    assert plan.critical_path[0] != plan.critical_path[-1] or len(plan.critical_path) == 1


def test_execution_plan_groups_parallel_ready_nodes(graph: DependencyGraph) -> None:
    plan = build_execution_plan(graph, ["offer:offer-1", "profile:profile-demo", "evidence:ev-excel"])
    assert plan.parallel_groups[0] == ["evidence:ev-excel", "offer:offer-1", "profile:profile-demo"]
    assert plan.estimated_duration
    assert plan.rollback_triggers


def test_execution_plan_handles_unknown_and_empty_input(graph: DependencyGraph) -> None:
    assert build_execution_plan(graph, ["missing:node"]).steps == []
    assert build_execution_plan(graph, []).steps == []


# ---------------------------------------------------------------------------
# 5. Scénarios what-if
# ---------------------------------------------------------------------------


def test_scenario_aggregates_multiple_changes(graph: DependencyGraph) -> None:
    simulation = simulate_scenarios(
        graph,
        [
            {"change_type": "delete", "node_id": "evidence:ev-excel"},
            {"change_type": "status_change", "node_id": "application:app-1", "details": {"status": "submitted"}},
        ],
    )
    assert len(simulation.analyses) == 2
    assert simulation.impacted_nodes
    assert simulation.recommended_order
    assert simulation.graph_version == graph.version
    assert "2 changement" in simulation.net_effect


def test_scenario_create_is_analyzed_after_creation(graph: DependencyGraph) -> None:
    simulation = simulate_scenarios(
        graph,
        [
            {
                "change_type": "create",
                "node_id": "ev-new",
                "details": {"node_type": "evidence", "label": "Nouvelle preuve"},
            }
        ],
    )
    assert len(simulation.analyses) == 1
    assert simulation.analyses[0].source_node_id == "evidence:ev-new"
    assert simulation.impacted_nodes == []


def test_scenario_does_not_mutate_source_graph(graph: DependencyGraph) -> None:
    before = graph.to_dict()
    simulate_scenarios(graph, [{"change_type": "delete", "node_id": "evidence:ev-excel"}])
    assert graph.to_dict() == before


def test_scenario_include_applied_graph(graph: DependencyGraph) -> None:
    simulation = simulate_scenarios(
        graph,
        [{"change_type": "delete", "node_id": "evidence:ev-english"}],
        include_applied_graph=True,
    )
    assert "evidence:ev-english" not in simulation.applied_graph["nodes"]
    assert simulation.to_dict(include_graph=True)["applied_graph"]["nodes"]


def test_scenario_rejects_empty_invalid_and_too_many_changes(graph: DependencyGraph) -> None:
    with pytest.raises(ValueError):
        simulate_scenarios(graph, [])
    with pytest.raises(ValueError):
        simulate_scenarios(graph, [{"change_type": "explode", "node_id": "offer:offer-1"}])
    with pytest.raises(ValueError):
        simulate_scenarios(graph, [{"change_type": "update", "node_id": "offer:offer-1"}] * 51)


def test_impact_engine_facade(graph: DependencyGraph) -> None:
    engine = ImpactEngine(graph, threshold=0.2, max_depth=4)
    assert engine.analyze("evidence:ev-excel", "delete").impacted_nodes
    assert engine.simulate([{"change_type": "delete", "node_id": "evidence:ev-excel"}]).impacted_nodes
    assert engine.critical(top_n=3)
    assert engine.fragility()["cycle_resolutions"] == []
    assert engine.cycles()["count"] == 0
    assert engine.validate()["valid"] is True
    assert engine.plan(["offer:offer-1", "requirement:req-excel"]).steps


# ---------------------------------------------------------------------------
# 6. Persistance versionnée
# ---------------------------------------------------------------------------


def test_store_saves_loads_and_versions(tmp_path: Path, graph: DependencyGraph) -> None:
    store = DependencyStore(tmp_path / "dependencies")
    assert store.load().nodes == {}

    first = store.save(graph, action="build")
    assert first.version == 1
    assert first.updated_at
    assert store.load().to_dict() == first.to_dict()

    second = store.save(first)
    assert second.version == 2
    assert store.load().version == 2
    assert [entry["version"] for entry in store.history()] == [2, 1]


def test_store_snapshot_and_rollback(tmp_path: Path, graph: DependencyGraph) -> None:
    store = DependencyStore(tmp_path / "dependencies")
    v1 = store.save(graph)
    snapshot = store.snapshot("avant suppression")
    assert snapshot["action"] == "snapshot"
    assert snapshot["version"] == v1.version

    mutated = v1.copy()
    mutated.remove_node("evidence:ev-excel")
    v2 = store.save(mutated)
    assert v2.version == 2
    assert "evidence:ev-excel" not in store.load().nodes

    restored = store.rollback(v1.version)
    assert restored.version == 3
    assert "evidence:ev-excel" in store.load().nodes
    assert any(entry["action"] == "rollback" for entry in store.history())


def test_store_rejects_rollback_to_missing_snapshot(tmp_path: Path, graph: DependencyGraph) -> None:
    store = DependencyStore(tmp_path / "dependencies")
    store.save(graph)
    with pytest.raises(KeyError):
        store.rollback(99)


def test_store_snapshot_requires_a_saved_graph(tmp_path: Path) -> None:
    store = DependencyStore(tmp_path / "dependencies")
    with pytest.raises(ValueError):
        store.snapshot("vide")


def test_store_files_are_private(tmp_path: Path, graph: DependencyGraph) -> None:
    store = DependencyStore(tmp_path / "dependencies")
    store.save(graph)
    store.snapshot("privé")
    assert oct(store.graph_path.stat().st_mode & 0o777) == "0o600"
    assert oct(store.history_path.stat().st_mode & 0o777) == "0o600"
    assert oct(store.root.stat().st_mode & 0o777) == "0o700"


def test_store_reset_removes_everything(tmp_path: Path, graph: DependencyGraph) -> None:
    store = DependencyStore(tmp_path / "dependencies")
    store.save(graph)
    store.snapshot("x")
    store.reset()
    assert store.load().nodes == {}
    assert store.history() == []


def test_store_exists_and_load_or_none(tmp_path: Path, graph: DependencyGraph) -> None:
    store = DependencyStore(tmp_path / "dependencies")
    assert store.exists() is False
    assert store.load_or_none() is None
    store.save(graph)
    assert store.exists() is True
    assert store.load_or_none() is not None


# ---------------------------------------------------------------------------
# 7. API HTTP
# ---------------------------------------------------------------------------


def graph_body() -> dict[str, object]:
    entities = synthetic_entities()
    return {
        **entities,
        "refresh_from_career": False,
        "replace": True,
    }


def test_api_build_read_and_node_detail(tmp_path: Path) -> None:
    client = client_for(StubService(tmp_path))
    response = client.post("/dependencies/graph", json=graph_body())
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["graph"]["version"] == 1
    assert payload["validation"]["valid"] is True

    alias = client.get("/api/career/dependencies/graph")
    assert alias.status_code == 200
    assert alias.json()["graph"]["version"] == 1

    node = client.get("/dependencies/graph/nodes/evidence:ev-excel")
    assert node.status_code == 200
    assert node.json()["node"]["node_type"] == "evidence"
    assert "requirement:req-excel" in node.json()["neighbors"]["outgoing"]

    missing = client.get("/dependencies/graph/nodes/evidence:absent")
    assert missing.status_code == 404


def test_api_edge_crud(tmp_path: Path) -> None:
    client = client_for(StubService(tmp_path))
    client.post("/dependencies/graph", json=graph_body())
    created = client.post(
        "/dependencies/edges",
        json={
            "source_id": "requirement:req-english",
            "target_id": "requirement:req-excel",
            "edge_type": "enables",
            "weight": 0.4,
        },
    )
    assert created.status_code == 200, created.text
    edge_id = created.json()["edge"]["edge_id"]
    assert created.json()["graph_version"] == 2

    removed = client.delete(f"/dependencies/edges/{edge_id}")
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    assert client.delete("/dependencies/edges/edge:missing").status_code == 404


def test_api_edge_rejects_unknown_nodes(tmp_path: Path) -> None:
    client = client_for(StubService(tmp_path))
    client.post("/dependencies/graph", json=graph_body())
    response = client.post(
        "/dependencies/edges",
        json={"source_id": "missing:a", "target_id": "missing:b", "edge_type": "requires"},
    )
    assert response.status_code == 400


def test_api_impact_and_scenario(tmp_path: Path) -> None:
    client = client_for(StubService(tmp_path))
    client.post("/dependencies/graph", json=graph_body())

    impact = client.post(
        "/dependencies/impact",
        json={"source_node_id": "evidence:ev-excel", "change_type": "delete", "details": {}},
    )
    assert impact.status_code == 200, impact.text
    levels = {node["node_id"]: node["impact_level"] for node in impact.json()["analysis"]["impacted_nodes"]}
    assert levels["requirement:req-excel"] == "critical"

    scenario = client.post(
        "/dependencies/scenario",
        json={
            "changes": [
                {"change_type": "delete", "node_id": "evidence:ev-excel"},
                {"change_type": "create", "node_id": "ev-backup", "details": {"node_type": "evidence", "label": "Secours"}},
            ]
        },
    )
    assert scenario.status_code == 200, scenario.text
    assert len(scenario.json()["analyses"]) == 2

    bad = client.post(
        "/dependencies/impact",
        json={"source_node_id": "evidence:absent", "change_type": "delete"},
    )
    assert bad.status_code == 400


def test_api_critical_cycles_fragility_validate(tmp_path: Path) -> None:
    client = client_for(StubService(tmp_path))
    client.post("/dependencies/graph", json=graph_body())

    critical = client.get("/dependencies/critical-nodes?top_n=3")
    assert critical.status_code == 200
    assert len(critical.json()["nodes"]) == 3

    cycles = client.get("/dependencies/cycles")
    assert cycles.status_code == 200
    assert cycles.json()["count"] == 0

    fragility = client.get("/dependencies/fragility")
    assert fragility.status_code == 200
    assert "cycle_resolutions" in fragility.json()

    validation = client.post("/dependencies/validate")
    assert validation.status_code == 200
    assert validation.json()["validation"]["valid"] is True


def test_api_plan_requires_known_nodes(tmp_path: Path) -> None:
    client = client_for(StubService(tmp_path))
    client.post("/dependencies/graph", json=graph_body())
    plan = client.post(
        "/dependencies/plan",
        json={"node_ids": ["offer:offer-1", "requirement:req-excel"]},
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["plan"]["steps"]
    assert plan.json()["plan"]["parallel_groups"]

    bad = client.post("/dependencies/plan", json={"node_ids": ["missing:node"]})
    assert bad.status_code == 400


def test_api_snapshot_history_and_rollback(tmp_path: Path) -> None:
    client = client_for(StubService(tmp_path))
    client.post("/dependencies/graph", json=graph_body())
    snapshot = client.post("/dependencies/snapshot", json={"label": "avant revue"})
    assert snapshot.status_code == 200, snapshot.text
    version = snapshot.json()["version"]

    history = client.get("/dependencies/history")
    assert history.status_code == 200
    assert any(entry["action"] == "snapshot" for entry in history.json()["entries"])

    rebuilt = client.post(
        "/dependencies/graph",
        json={**graph_body(), "requirements": []},
    )
    assert rebuilt.status_code == 200
    rollback = client.post("/dependencies/rollback", json={"version": version})
    assert rollback.status_code == 200, rollback.text
    assert "requirement:req-excel" in rollback.json()["graph"]["nodes"]


def test_api_auto_builds_from_career_data(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile(
        {
            "display_name": "Personne Démo",
            "education": "Master Finance (démo)",
            "experience": "Projet chiffré de 12 000 € (démo)",
            "skills": "Excel, analyse financière",
            "languages": "Français, anglais C1",
        }
    )
    job = service.import_job(
        {
            "company": "Banque de Démo",
            "title": "Stagiaire M&A",
            "source_name": "manual",
            "source_id": "REF-DEMO-013",
            "official_url": "https://careers.example.test/jobs/demo-13",
            "job_family": "M&A / Investment Banking",
            "city": "Paris",
            "country": "France",
            "source_status": "open",
            "requirements": "Maîtrise avancée d'Excel.\nAnglais professionnel.",
            "description_original": "Stage de démonstration synthétique.",
        }
    )
    service.create_application(job["id"])
    client = client_for(service)
    response = client.post("/dependencies/graph", json={"refresh_from_career": True})
    assert response.status_code == 200, response.text
    nodes = response.json()["graph"]["nodes"]
    assert any(node["node_type"] == "offer" for node in nodes.values())
    assert any(node["node_type"] == "requirement" for node in nodes.values())
    assert any(node["node_type"] == "application" for node in nodes.values())
    assert any(node["node_type"] == "evidence" for node in nodes.values())


def test_api_non_replace_merges_into_existing_graph(tmp_path: Path) -> None:
    client = client_for(StubService(tmp_path))
    client.post("/dependencies/graph", json=graph_body())
    response = client.post(
        "/dependencies/graph",
        json={
            "refresh_from_career": False,
            "replace": False,
            "evidences": [
                {"id": "ev-new", "title": "Preuve ajoutée", "validates": ["req-english"], "weight": 0.5}
            ],
        },
    )
    assert response.status_code == 200, response.text
    nodes = response.json()["graph"]["nodes"]
    assert "evidence:ev-new" in nodes
    assert "evidence:ev-excel" in nodes


# ---------------------------------------------------------------------------
# 8. Interface statique (graphe, filtres, zoom, chemin critique)
# ---------------------------------------------------------------------------


def test_dependency_ui_is_wired_in_the_career_page() -> None:
    root = Path(__file__).resolve().parents[1] / "career_static"
    html = (root / "index.html").read_text(encoding="utf-8")
    assert 'data-view="dependencies"' in html
    assert 'id="view-dependencies"' in html
    assert "/career-static/dependencies.css" in html
    assert "/career-static/js/dependencies.js" in html
    assert html.index("/career-static/js/dependencies.js") < html.index("/career-static/career.js")
    assert (root / "dependencies.css").is_file()
    assert (root / "js" / "dependencies.js").is_file()


def test_dependency_ui_offers_zoom_filters_and_critical_path() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "career_static" / "js" / "dependencies.js"
    ).read_text(encoding="utf-8")
    for marker in ("wheel", "data-dependency-filter", "criticalPath", "viewBox", "pointerdown", "snapshot"):
        assert marker in source
    assert 'fetch("http' not in source
    assert "https://" not in source


def test_career_js_routes_to_dependencies_view() -> None:
    source = (Path(__file__).resolve().parents[1] / "career_static" / "career.js").read_text(encoding="utf-8")
    assert '"dependencies"' in source
    assert "CareerDependencies" in source


# ---------------------------------------------------------------------------
# 9. Garde-fous statiques
# ---------------------------------------------------------------------------


def test_modules_stay_offline_and_deterministic() -> None:
    root = Path(__file__).resolve().parents[1] / "career"
    forbidden = ("requests", "urllib.request", "httpx", "socket", "http.client")
    for name in ("dependencies.py", "dependencies_store.py", "impact_analysis.py"):
        source = (root / name).read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{name} ne doit jamais appeler le réseau ({marker})."


def test_no_automatic_application_or_submission_wording() -> None:
    source = (Path(__file__).resolve().parents[1] / "career" / "dependencies.py").read_text(encoding="utf-8")
    assert "envoi automatique" not in source.lower()
    assert "rejet certain" not in source.lower()
