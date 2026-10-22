"""Registre de traçabilité des exigences (SPEC-011 — CVBOOST-46).

Ce que ces tests verrouillent :

1. Une exigence « covered » porte toujours sa preuve ; sinon elle reste
   visible comme un manque.
2. L'historique est append-only : un événement écrit n'est jamais réécrit.
3. Une renonciation exige une justification, et la justification est
   conservée.
4. Le registre survit au redémarrage (fichier local, écriture atomique) et
   se ré-importe tel qu'il a été exporté.
5. Les rapports d'audit disent la vérité : couverture, gaps, renonciations,
   historique.
6. Les intégrations SK-02 (création), SK-10 (preuve) et SK-21 (matching)
   fonctionnent sur des données synthétiques.

Toutes les données sont synthétiques : aucune offre réelle, aucun CV réel,
aucun appel réseau.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.offer_requirements import analyze_offer
from career.router import create_career_router
from career.service import CareerService
from career.traceability import (
    TraceabilityError,
    TraceabilityRegistry,
    link_evidence_item,
    link_matching_actions,
    traces_from_offer_analysis,
)
from career.traceability_audit import (
    audit_summary,
    coverage_by_cv,
    coverage_by_offer,
    coverage_over_time,
    critical_gaps,
    history_timeline,
    waived_requirements,
)
from career.traceability_store import TraceabilityStore
from workspace_core import UserFacingError


# ── Fixtures synthétiques ────────────────────────────────────────────────────


def synthetic_offer() -> dict[str, object]:
    """A clearly synthetic offer; it references no real company or posting."""

    return {
        "id": "offre_demo_1",
        "offer_id": "offre_demo_1",
        "company": "Banque de Démo",
        "title": "Stagiaire M&A",
        "requirements": "Maîtrise d'Excel\nAnglais courant",
        "languages_required": "Anglais C1",
        "description_original": "Stage synthétique de quatre mois en fusion-acquisition.",
    }


@pytest.fixture()
def registry() -> TraceabilityRegistry:
    return TraceabilityRegistry()


@pytest.fixture()
def populated() -> TraceabilityRegistry:
    registry = TraceabilityRegistry()
    excel = registry.create(
        requirement_id="req_excel",
        requirement_text="Maîtrise d'Excel",
        source="offer_42",
        category="tool",
        criticality="mandatory",
        now="2026-10-20T09:00:00+00:00",
    )
    registry.link_evidence(
        excel.trace_id,
        "ev_excel",
        "Excel :建模 et reporting (CV p.2)",
        actor="user",
        comment="Preuve CV",
        now="2026-10-20T09:05:00+00:00",
    )
    english = registry.create(
        requirement_id="req_english",
        requirement_text="Anglais courant",
        source="offer_42",
        category="language",
        criticality="preferred",
        now="2026-10-20T09:01:00+00:00",
    )
    registry.create(
        requirement_id="req_python",
        requirement_text="Python",
        source="offer_99",
        category="skill",
        criticality="mandatory",
        tags=["data"],
        now="2026-10-20T09:02:00+00:00",
    )
    registry.waive(
        english.trace_id,
        "Non pertinent pour ce poste",
        actor="user",
        now="2026-10-20T09:10:00+00:00",
    )
    return registry


# ── 1. Cœur du registre ──────────────────────────────────────────────────────


def test_create_records_the_first_event(registry: TraceabilityRegistry) -> None:
    trace = registry.create(
        requirement_id="req_1",
        requirement_text="Excel",
        source="offer_42",
        category="tool",
        criticality="mandatory",
    )
    assert trace.status == "uncovered"
    assert trace.evidence_id is None
    assert [event.event_type for event in trace.history] == ["created"]
    assert trace.history[0].actor == "system"
    assert trace.offer_id == "42"
    assert trace.cv_id == ""


def test_covered_requirement_always_carries_its_proof(registry: TraceabilityRegistry) -> None:
    with pytest.raises(TraceabilityError):
        registry.create(requirement_text="Excel", status="covered")
    trace = registry.create(requirement_text="Excel")
    with pytest.raises(TraceabilityError):
        registry.update(trace.trace_id, status="covered")
    with pytest.raises(TraceabilityError):
        registry.link_evidence(trace.trace_id, "ev_1")


def test_link_then_unlink_keeps_the_truth_visible(registry: TraceabilityRegistry) -> None:
    trace = registry.create(requirement_text="Excel", criticality="mandatory")
    linked = registry.link_evidence(trace.trace_id, "ev_1", "Excel, 3 ans")
    assert linked.status == "covered"
    assert linked.evidence_id == "ev_1"
    assert linked.evidence_quote == "Excel, 3 ans"
    assert [event.event_type for event in linked.history] == ["created", "linked", "status_changed"]

    unlinked = registry.unlink_evidence(trace.trace_id, comment="Preuve retirée")
    assert unlinked.status == "uncovered"
    assert unlinked.evidence_id is None
    assert [event.event_type for event in unlinked.history][-2:] == ["unlinked", "status_changed"]


def test_waiver_requires_a_justification_and_keeps_it(registry: TraceabilityRegistry) -> None:
    trace = registry.create(requirement_text="Excel")
    with pytest.raises(TraceabilityError):
        registry.waive(trace.trace_id, "")
    waived = registry.waive(trace.trace_id, "Non pertinent pour ce poste", actor="user")
    assert waived.status == "waived"
    assert waived.justification() == "Non pertinent pour ce poste"
    reopened = registry.reopen(trace.trace_id, actor="user")
    assert reopened.status == "uncovered"
    assert [event.event_type for event in reopened.history][-1] == "reopened"


def test_history_is_append_only(registry: TraceabilityRegistry) -> None:
    trace = registry.create(requirement_text="Excel", now="2026-10-20T09:00:00+00:00")
    first_event = trace.history[0]
    registry.update(trace.trace_id, tags=["finance"], now="2026-10-20T09:01:00+00:00")
    registry.update(trace.trace_id, criticality="preferred", now="2026-10-20T09:02:00+00:00")
    updated = registry.require(trace.trace_id)
    assert updated.history[0] == first_event
    assert len(updated.history) == 3
    assert updated.history[0].event_id == first_event.event_id


def test_update_records_one_event_per_changed_field(registry: TraceabilityRegistry) -> None:
    trace = registry.create(requirement_text="Excel")
    updated = registry.update(
        trace.trace_id,
        category="skill",
        criticality="preferred",
        tags=["finance", "m&a"],
        comment="Revue manuelle",
        actor="user",
    )
    kinds = [event.event_type for event in updated.history]
    assert kinds == ["created", "category_changed", "criticality_changed", "status_changed"]
    assert updated.category == "skill"
    assert updated.criticality == "preferred"
    assert updated.tags == ["finance", "m&a"]


def test_delete_keeps_the_audit_trail(populated: TraceabilityRegistry) -> None:
    trace = populated.require(registry_id(populated))
    deleted = populated.delete(trace.trace_id, actor="user", comment="Exigence retirée")
    assert deleted.history[-1].event_type == "deleted"
    assert populated.get(trace.trace_id) is None
    assert populated.deleted_traces()[0].trace_id == trace.trace_id
    assert len(populated.deleted_traces()[0].history) == len(deleted.history)


def registry_id(registry: TraceabilityRegistry) -> str:
    return registry.traces()[0].trace_id


def test_filters_are_exact(populated: TraceabilityRegistry) -> None:
    assert len(populated.filter(status="uncovered")) == 1
    assert len(populated.filter(criticality="mandatory")) == 2
    assert len(populated.filter(offer_id="42")) == 2
    assert len(populated.filter(offer_id="99")) == 1
    assert len(populated.filter(tag="data")) == 1
    assert len(populated.filter(text="anglais")) == 1
    assert populated.filter(status="inexistant") == []


def test_unknown_values_are_never_guessed(registry: TraceabilityRegistry) -> None:
    with pytest.raises(TraceabilityError):
        registry.create(requirement_text="Excel", category="physique")
    with pytest.raises(TraceabilityError):
        registry.create(requirement_text="Excel", criticality="obligatoire")
    trace = registry.create(requirement_text="Excel")
    with pytest.raises(TraceabilityError):
        registry.update(trace.trace_id, status="couverte")


# ── 2. Persistance ───────────────────────────────────────────────────────────


def test_store_round_trip(populated: TraceabilityRegistry, tmp_path: Path) -> None:
    store = TraceabilityStore(tmp_path / "registry.json")
    store.save(populated)
    reloaded = store.load()
    assert len(reloaded) == len(populated)
    assert reloaded.traces()[0].to_dict() == populated.traces()[0].to_dict()
    assert reloaded.traces()[0].history[0].event_id == populated.traces()[0].history[0].event_id


def test_store_never_leaves_a_half_written_file(populated: TraceabilityRegistry, tmp_path: Path) -> None:
    store = TraceabilityStore(tmp_path / "nested" / "registry.json")
    store.save(populated)
    assert store.path.is_file()
    assert not list(store.path.parent.glob("*.tmp"))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["traces"]) == len(populated)


def test_store_refuses_a_corrupted_file(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text("{ ceci n'est pas du json", encoding="utf-8")
    store = TraceabilityStore(path)
    with pytest.raises(UserFacingError):
        store.load()
    # Le fichier corrompu n'est jamais remplacé par un registre vide.
    assert path.read_text(encoding="utf-8") == "{ ceci n'est pas du json"


def test_store_refuses_a_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"schema_version": 99, "traces": []}), encoding="utf-8")
    with pytest.raises(UserFacingError):
        TraceabilityStore(path).load()


def test_export_import_round_trip(populated: TraceabilityRegistry, tmp_path: Path) -> None:
    store = TraceabilityStore(tmp_path / "registry.json")
    exported = store.export_json(populated)
    imported = store.import_json(exported)
    assert len(imported) == len(populated)
    assert imported.traces()[0].to_dict() == populated.traces()[0].to_dict()

    csv_export = store.export_csv(populated)
    assert csv_export.splitlines()[0].startswith("trace_id;requirement_id;requirement_text")
    assert len(csv_export.strip().splitlines()) == len(populated) + 1


# ── 3. Rapports d'audit ──────────────────────────────────────────────────────


def test_coverage_reports(populated: TraceabilityRegistry) -> None:
    by_offer = {report["offer_id"]: report for report in coverage_by_offer(populated)}
    assert by_offer["42"]["total"] == 2
    assert by_offer["42"]["covered"] == 1
    assert by_offer["42"]["waived"] == 1
    assert by_offer["42"]["covered_pct"] == 100.0  # l'exigence renoncée sort du calcul
    assert by_offer["99"]["uncovered"] == 1
    assert by_offer["99"]["covered_pct"] == 0.0

    assert coverage_by_cv(populated) == []  # aucune exigence n'est rattachée à un CV ici

    gaps = critical_gaps(populated)
    assert [gap["requirement_id"] for gap in gaps] == ["req_python"]
    assert all(gap["criticality"] == "mandatory" for gap in gaps)

    waived = waived_requirements(populated)
    assert len(waived) == 1
    assert "Non pertinent" in waived[0]["justification"]

    summary = audit_summary(populated)
    assert summary["total"] == 3
    assert summary["critical_gaps"] == 1
    assert summary["linked_evidence"] == 1


def test_history_timeline_is_filtered(populated: TraceabilityRegistry) -> None:
    events = history_timeline(populated)
    assert [event["event_type"] for event in events][0] == "created"
    assert all(event["timestamp"] <= events[-1]["timestamp"] for event in events)

    linked = history_timeline(populated, event_type="linked")
    assert len(linked) == 1
    assert linked[0]["actor"] == "user"

    per_source = history_timeline(populated, source_filter="offer_99")
    assert len(per_source) == 1


def test_coverage_over_time_is_rebuilt_from_the_history(populated: TraceabilityRegistry) -> None:
    points = coverage_over_time(populated)
    assert points
    assert points[0]["covered"] == 0
    assert points[-1]["covered"] == 1
    assert points[-1]["timestamp"] >= points[0]["timestamp"]


# ── 4. Intégrations SK-02 / SK-10 / SK-21 ────────────────────────────────────


def test_offer_analysis_creates_the_traces(registry: TraceabilityRegistry) -> None:
    analysis = analyze_offer(synthetic_offer())
    drafts = traces_from_offer_analysis(analysis)
    assert drafts
    assert all(draft.source == "offer_offre_demo_1" for draft in drafts)
    assert all(draft.status == "uncovered" for draft in drafts)
    assert all(draft.history[0].event_type == "created" for draft in drafts)

    summary = registry.sync_offer_analysis(analysis)
    assert len(summary["created"]) == len(drafts)
    assert summary["updated"] == []

    # La synchronisation est idempotente : réanalyser la même offre ne
    # duplique rien.
    again = registry.sync_offer_analysis(analysis)
    assert again["created"] == []
    assert len(again["unchanged"]) == len(drafts)
    assert len(registry) == len(drafts)


def test_unknown_modality_never_becomes_mandatory(registry: TraceabilityRegistry) -> None:
    analysis = {
        "offer_id": "offre_demo_2",
        "requirements": [
            {"id": "req_x", "text": "Passage flou", "category": "other", "modality": "unknown"},
        ],
    }
    drafts = traces_from_offer_analysis(analysis)
    assert drafts[0].criticality == "contextual"


def test_matching_links_the_proof(populated: TraceabilityRegistry) -> None:
    outcomes = link_matching_actions(
        populated,
        [
            {
                "requirement_id": "req_excel",
                "code": "HIGHLIGHT",
                "evidence": {"quote": "Excel : modélisation", "field": "skills", "offset": 120},
            },
            {
                "requirement_id": "req_python",
                "code": "DO_NOT_ADD",
                "evidence": None,
            },
        ],
    )
    statuses = {outcome["requirement_id"]: outcome["status"] for outcome in outcomes}
    assert statuses["req_excel"] == "covered"
    assert statuses["req_python"] == "uncovered"
    assert populated.require(populated.traces()[0].trace_id).evidence_quote


def test_matching_without_quote_never_covers(populated: TraceabilityRegistry) -> None:
    outcomes = link_matching_actions(
        populated,
        [{"requirement_id": "req_python", "code": "HIGHLIGHT", "evidence": {"field": "skills"}}],
    )
    assert outcomes[0]["status"] == "uncovered"
    assert all(trace.status != "covered" for trace in populated.traces() if trace.requirement_id == "req_python")


def test_unknown_requirement_is_skipped_not_guessed(populated: TraceabilityRegistry) -> None:
    outcomes = link_matching_actions(
        populated,
        [{"requirement_id": "req_inconnue", "code": "HIGHLIGHT", "evidence": {"quote": "x"}}],
    )
    assert outcomes[0]["status"] == "skipped"
    assert "Aucune traçabilité" in outcomes[0]["reason"]


def test_evidence_item_links_to_the_requirement(populated: TraceabilityRegistry) -> None:
    trace = next(item for item in populated.traces() if item.requirement_id == "req_python")
    linked = link_evidence_item(
        populated,
        trace.trace_id,
        {"id": "fact_7", "quote": "Python — 2 ans"},
        actor="user",
    )
    assert linked.status == "covered"
    assert linked.evidence_id == "fact_7"


# ── 5. API HTTP ──────────────────────────────────────────────────────────────


def traceability_client(service: CareerService) -> TestClient:
    """Minimal app with the same error contract as the real FastAPI app."""

    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return traceability_client(CareerService(tmp_path))


def test_http_crud_cycle(client: TestClient) -> None:
    created = client.post(
        "/traceability/requirements",
        json={
            "requirement_text": "Maîtrise d'Excel",
            "source": "offer_42",
            "category": "tool",
            "criticality": "mandatory",
        },
    )
    assert created.status_code == 201
    trace = created.json()
    assert trace["status"] == "uncovered"
    trace_id = trace["trace_id"]

    linked = client.post(
        f"/api/career/traceability/requirements/{trace_id}/link-evidence",
        json={"evidence_id": "ev_1", "evidence_quote": "Excel (CV p.2)"},
    )
    assert linked.status_code == 200
    assert linked.json()["status"] == "covered"

    detail = client.get(f"/traceability/requirements/{trace_id}")
    assert detail.status_code == 200
    assert [event["event_type"] for event in detail.json()["history"]] == [
        "created",
        "linked",
        "status_changed",
    ]

    patched = client.patch(
        f"/traceability/requirements/{trace_id}",
        json={"tags": ["finance"], "comment": "Revue"},
    )
    assert patched.status_code == 200
    assert patched.json()["tags"] == ["finance"]

    waived = client.post(
        f"/traceability/requirements/{trace_id}/waive",
        json={"justification": "Non pertinent pour ce poste"},
    )
    assert waived.status_code == 200
    assert waived.json()["status"] == "waived"

    listing = client.get("/traceability/requirements", params={"status": "waived"})
    assert listing.status_code == 200
    assert listing.json()["count"] == 1


def test_http_refuses_a_covered_status_without_proof(client: TestClient) -> None:
    created = client.post("/traceability/requirements", json={"requirement_text": "Excel"})
    trace_id = created.json()["trace_id"]
    refused = client.patch(f"/traceability/requirements/{trace_id}", json={"status": "covered"})
    assert refused.status_code == 400
    assert "evidence" in refused.json()["detail"]


def test_http_unknown_requirement_is_a_clean_error(client: TestClient) -> None:
    response = client.get("/traceability/requirements/trace_inconnu")
    assert response.status_code == 400
    assert "introuvable" in response.json()["detail"]


def test_http_audit_and_export(client: TestClient) -> None:
    client.post(
        "/traceability/requirements",
        json={
            "requirement_text": "Anglais courant",
            "source": "offer_42",
            "category": "language",
            "criticality": "mandatory",
        },
    )
    coverage = client.get("/traceability/audit/coverage")
    assert coverage.status_code == 200
    assert coverage.json()["summary"]["total"] == 1
    assert coverage.json()["by_offer"][0]["offer_id"] == "42"

    gaps = client.get("/traceability/audit/gaps")
    assert gaps.status_code == 200
    assert gaps.json()["count"] == 1

    history = client.get("/traceability/audit/history")
    assert history.status_code == 200
    assert history.json()["events"]

    waived = client.get("/traceability/audit/waived")
    assert waived.status_code == 200
    assert waived.json()["count"] == 0

    exported = client.get("/traceability/export", params={"export_format": "json"})
    assert exported.status_code == 200
    assert exported.json()["traces"]

    csv_export = client.get("/traceability/export", params={"export_format": "csv"})
    assert csv_export.status_code == 200
    assert csv_export.text.splitlines()[0].startswith("trace_id;")


def test_http_import_replaces_the_registry(client: TestClient) -> None:
    client.post("/traceability/requirements", json={"requirement_text": "Excel"})
    exported = client.get("/traceability/export", params={"export_format": "json"}).json()
    imported = client.post("/traceability/import", json={"registry": exported, "mode": "replace"})
    assert imported.status_code == 200
    assert imported.json()["imported"] == 1


def test_http_sync_offer_creates_the_traces(client: TestClient) -> None:
    response = client.post("/traceability/sync-offer", json={"offer": synthetic_offer()})
    assert response.status_code == 200
    assert len(response.json()["summary"]["created"]) >= 1
    listing = client.get("/traceability/requirements")
    assert listing.json()["count"] >= 1
    assert all(trace["source"] == "offer_offre_demo_1" for trace in listing.json()["traces"])


def test_registry_survives_a_new_client(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    first = traceability_client(service)
    first.post(
        "/traceability/requirements",
        json={"requirement_text": "Excel", "source": "offer_42", "criticality": "mandatory"},
    )
    second = traceability_client(service)
    listing = second.get("/traceability/requirements")
    assert listing.json()["count"] == 1
