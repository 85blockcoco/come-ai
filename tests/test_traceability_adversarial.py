"""SPEC-011 — campagne adversariale du registre de traçabilité.

Ce fichier ne teste pas des fonctionnalités : il teste les **garanties** du
registre face à des situations où il pourrait mentir.

Chaque test porte sur un défaut **réellement reproduit** avant la campagne
(correctifs appliqués dans ``career/traceability.py``,
``career/traceability_store.py`` et ``career/traceability_audit.py``) :

1. la courbe de couverture ne comptait que les exigences *déjà créées* ;
2. une liaison automatique pouvait laisser une exigence « couverte » ;
3. une liaison automatique pouvait *déclarer* une couverture ;
4. une mise à jour refusée laissait la mémoire et la base divergées ;
5. un import pouvait forger l'identité d'une exigence (double trace) ;
6. un import perdait l'état de validation d'une version plus récente ;
7. le résumé d'une liaison automatique annonçait des comptements faux ;
8. une exigence retirée de l'offre restait un « gap » éternel ;
9. une exigence supprimée puis retrouvée disparaissait du registre ;
10. une confirmation sans citation échouait *après* avoir muté l'exigence.

Toutes les données sont synthétiques.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.service import CareerService
from career.traceability import (
    RequirementTrace,
    TraceabilityError,
    TraceabilityRegistry,
    auto_link_evidence,
    requirement_trace_id,
)
from career.traceability_audit import (
    audit_report,
    coverage_over_time,
    coverage_summary,
    critical_gaps,
    superseded_requirements,
)
from career.traceability_store import TraceabilityService

from come_ai_web import create_app


# ── Helpers ─────────────────────────────────────────────────────────────────


def _clock(start: str = "2026-10-01T09:00:00+00:00"):
    """Return a deterministic, monotonically increasing clock."""
    counter = {"value": 0}

    def now() -> str:
        counter["value"] += 1
        return f"{start[:-6]}{int(start[-6:-4]) * 60 + counter['value']:02d}:00+00:00"

    return now


def _registry() -> TraceabilityRegistry:
    return TraceabilityRegistry(clock=_clock())


def _trace(registry: TraceabilityRegistry, **kwargs) -> RequirementTrace:
    payload = {
        "requirement_id": "req_1",
        "requirement_text": "Excel modelling and valuation",
        "source": "offer_job_1",
        "category": "skill",
        "criticality": "mandatory",
    }
    payload.update(kwargs)
    return registry.register(**payload)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path), raise_server_exceptions=False)


def _analysis(*records: dict, offer_id: str = "job_1", **extra) -> dict:
    payload = {"offer_id": offer_id, "requirements": list(records)}
    payload.update(extra)
    return payload


def _requirement_record(identifier: str, text: str, **extra) -> dict:
    record = {
        "id": identifier,
        "text": text,
        "category": "technical_skill",
        "modality": "required",
        "locator": "line:1",
        "source_field": "requirements",
        "confidence": 0.9,
        "injection_suspect": False,
    }
    record.update(extra)
    return record


# ── 1. La courbe de couverture ne ment pas sur le dénominateur ──────────────


def test_the_coverage_curve_only_counts_the_requirements_that_existed() -> None:
    """Un point de la courbe ne compte que les exigences déjà créées."""
    registry = _registry()
    first = _trace(registry, requirement_id="req_1")
    second = _trace(registry, requirement_id="req_2")
    registry.link_evidence(first.trace_id, evidence_id="ev-1", evidence_quote="Excel modelling and valuation")

    evolution = coverage_over_time(registry.all())

    # Le premier point ne connaît qu'une exigence : la seconde n'existe pas
    # encore, elle ne peut pas dégrader le taux de ce moment-là.
    assert evolution[0]["evaluated"] == 1
    assert evolution[0]["coverage_rate"] == 0.0
    # Le dernier point connaît les deux exigences, dont une couverte.
    assert evolution[-1]["evaluated"] == 2
    assert evolution[-1]["covered"] == 1
    assert evolution[-1]["coverage_rate"] == pytest.approx(0.5)
    assert second.trace_id in {point["trace_id"] for point in evolution}


def test_the_coverage_curve_stays_monotonic_in_the_denominator() -> None:
    """Le dénominateur ne rétrécit jamais quand une exigence est créée."""
    registry = _registry()
    _trace(registry, requirement_id="req_1")
    _trace(registry, requirement_id="req_2")
    _trace(registry, requirement_id="req_3")

    denominators = [point["evaluated"] for point in coverage_over_time(registry.all())]
    assert denominators == sorted(denominators)
    assert denominators[-1] == 3


# ── 2. Une liaison automatique ne porte jamais une couverture ──────────────


def test_an_automatic_link_never_keeps_a_coverage() -> None:
    """Remplacer une preuve confirmée par une proposition automatique retire la couverture."""
    registry = _registry()
    trace = _trace(registry)
    registry.link_evidence(trace.trace_id, evidence_id="ev-1", evidence_quote="Excel modelling and valuation")
    assert trace.status == "covered"

    registry.link_evidence(
        trace.trace_id,
        evidence_id="ev-2",
        evidence_quote="Excel modelling and valuation",
        origin="auto",
    )

    assert trace.status == "uncovered"
    assert trace.review_state == "pending"
    report = audit_report(registry.all())
    assert report["inconsistencies"] == []


def test_an_automatic_link_cannot_claim_a_coverage() -> None:
    """``origin="auto"`` + ``status="covered"`` est refusé, et rien n'est muté."""
    registry = _registry()
    trace = _trace(registry)

    with pytest.raises(TraceabilityError):
        registry.link_evidence(
            trace.trace_id,
            evidence_id="ev-2",
            evidence_quote="Excel modelling and valuation",
            origin="auto",
            status="covered",
        )

    assert trace.status == "uncovered"
    assert trace.evidence_id is None
    assert trace.review_state == "not_required"
    assert [event.event_type for event in trace.history] == ["created"]


def test_a_pending_link_cannot_be_declared_covered_by_hand() -> None:
    """Tant que la liaison automatique n'est pas validée, le statut « covered » est refusé."""
    registry = _registry()
    trace = _trace(registry)
    registry.link_evidence(
        trace.trace_id,
        evidence_id="ev-1",
        evidence_quote="Excel modelling and valuation",
        origin="auto",
    )

    with pytest.raises(TraceabilityError):
        registry.set_status(trace.trace_id, "covered")

    assert trace.status == "uncovered"


def test_confirming_a_link_without_a_quote_is_refused_before_any_mutation() -> None:
    """La confirmation d'une liaison sans citation échoue sans rien modifier."""
    registry = _registry()
    trace = _trace(registry)
    registry.link_evidence(trace.trace_id, evidence_id="ev-1", origin="auto")

    with pytest.raises(TraceabilityError):
        registry.confirm_link(trace.trace_id)

    assert trace.review_state == "pending"
    assert trace.status == "uncovered"
    assert [event.event_type for event in trace.history] == ["created", "linked"]


# ── 3. Un changement refusé ne laisse aucun état divergent ──────────────────


def test_a_refused_update_leaves_memory_and_disk_identical(tmp_path: Path) -> None:
    """Un PATCH refusé ne doit pas laisser la catégorie en mémoire mais pas en base."""
    service = TraceabilityService(tmp_path / "traceability.sqlite3", clock=_clock())
    created = service.create_requirement(
        {"requirement_id": "req_1", "requirement_text": "Excel modelling", "source": "offer_job_1"}
    )
    trace_id = created["trace_id"]

    with pytest.raises(TraceabilityError):
        service.update_requirement(
            trace_id,
            {"category": "tool", "tags": ["finance"], "status": "covered"},
        )

    in_memory = service.get_requirement(trace_id)
    persisted = service.store.get_trace(trace_id)
    assert in_memory["category"] == persisted.category == "other"
    assert in_memory["tags"] == persisted.tags == []
    assert in_memory["status"] == persisted.status == "uncovered"
    # L'historique n'a pas été pollué par la tentative refusée.
    assert [event["event_type"] for event in in_memory["history"]] == ["created"]


def test_a_refused_link_leaves_no_half_applied_proof(tmp_path: Path) -> None:
    """Une liaison refusée ne doit pas retirer la preuve d'une exigence couverte."""
    service = TraceabilityService(tmp_path / "traceability.sqlite3", clock=_clock())
    created = service.create_requirement(
        {"requirement_id": "req_1", "requirement_text": "Excel modelling", "source": "offer_job_1"}
    )
    trace_id = created["trace_id"]
    service.link_evidence(trace_id, {"evidence_id": "ev-1", "evidence_quote": "Excel modelling"})

    with pytest.raises(TraceabilityError):
        service.link_evidence(
            trace_id,
            {"evidence_id": "ev-2", "evidence_quote": "Excel modelling", "origin": "auto", "status": "covered"},
        )

    stored = service.get_requirement(trace_id)
    assert stored["status"] == "covered"
    assert stored["evidence_id"] == "ev-1"
    assert stored["review_state"] == "confirmed"
    assert service.store.get_trace(trace_id).evidence_id == "ev-1"


def test_an_unknown_status_is_refused_without_touching_the_requirement(tmp_path: Path) -> None:
    """Un statut hors vocabulaire ne modifie rien."""
    service = TraceabilityService(tmp_path / "traceability.sqlite3", clock=_clock())
    created = service.create_requirement(
        {"requirement_id": "req_1", "requirement_text": "Excel modelling", "source": "offer_job_1"}
    )
    trace_id = created["trace_id"]

    with pytest.raises(TraceabilityError):
        service.update_requirement(trace_id, {"status": "quasi-couvert"})

    assert service.get_requirement(trace_id)["status"] == "uncovered"


# ── 4. Un import ne peut pas forger l'identité d'une exigence ───────────────


def test_an_import_cannot_forge_the_identity_of_a_requirement(tmp_path: Path) -> None:
    """Un identifiant de trace truqué est refusé : une exigence, une trace."""
    service = TraceabilityService(tmp_path / "traceability.sqlite3", clock=_clock())
    service.create_requirement(
        {"requirement_id": "req_1", "requirement_text": "Excel modelling", "source": "offer_job_1"}
    )
    forged = {
        "schema_version": 1,
        "traces": [
            {
                "trace_id": "trace_forged",
                "requirement_id": "req_1",
                "requirement_text": "Excel modelling",
                "source": "offer_job_1",
                "offer_id": "job_1",
                "status": "uncovered",
                "created_at": "2026-10-01T09:00:00+00:00",
                "updated_at": "2026-10-01T09:00:00+00:00",
                "history": [],
            }
        ],
    }

    summary = service.import_traces(forged)

    assert summary["imported"] == 0
    assert summary["invalid"] == 1
    assert service.list_requirements({})["count"] == 1


def test_an_import_keeps_the_identity_of_a_legitimate_trace(tmp_path: Path) -> None:
    """L'export/import officiel reste accepté (aller-retour intact)."""
    service = TraceabilityService(tmp_path / "traceability.sqlite3", clock=_clock())
    service.create_requirement(
        {"requirement_id": "req_1", "requirement_text": "Excel modelling", "source": "offer_job_1"}
    )
    exported = json.loads(json.dumps(service.store.export_json()))

    target = TraceabilityService(tmp_path / "target.sqlite3", clock=_clock())
    summary = target.import_traces(exported)

    assert summary["imported"] == 1
    assert summary["invalid"] == 0
    assert target.list_requirements({})["count"] == 1


def test_an_import_restores_the_review_state_of_a_newer_version(tmp_path: Path) -> None:
    """La fusion copie l'état complet de la version la plus récente."""
    service = TraceabilityService(tmp_path / "traceability.sqlite3", clock=_clock())
    created = service.create_requirement(
        {"requirement_id": "req_1", "requirement_text": "Excel modelling", "source": "offer_job_1"}
    )
    trace_id = created["trace_id"]
    exported = json.loads(json.dumps(service.store.export_json()))
    record = exported["traces"][0]
    record["review_state"] = "confirmed"
    record["link_origin"] = "auto"
    record["updated_at"] = "2026-11-01T09:00:00+00:00"

    service.import_traces({"schema_version": 1, "traces": [record]})

    stored = service.get_requirement(trace_id)
    assert stored["review_state"] == "confirmed"
    assert stored["link_origin"] == "auto"


def test_the_import_orders_two_versions_by_instant_not_by_string(tmp_path: Path) -> None:
    """``…:17.123456+00:00`` est après ``…:17+00:00``, malgré l'ordre des chaînes."""
    service = TraceabilityService(tmp_path / "traceability.sqlite3", clock=_clock())
    created = service.create_requirement(
        {"requirement_id": "req_1", "requirement_text": "Texte local", "source": "offer_job_1"}
    )
    trace_id = created["trace_id"]
    exported = json.loads(json.dumps(service.store.export_json()))
    record = exported["traces"][0]
    record["requirement_text"] = "Texte importé"
    record["updated_at"] = "2026-10-01T09:00:00+00:00"

    # La version locale est plus récente (à la microseconde près).
    service.registry.get(trace_id).updated_at = "2026-10-01T09:00:00.500000+00:00"
    service.store.save_trace(service.registry.get(trace_id))

    service.import_traces({"schema_version": 1, "traces": [record]})

    assert service.get_requirement(trace_id)["requirement_text"] == "Texte local"


# ── 5. Le résumé d'une liaison automatique dit ce qu'il compte ─────────────


def test_the_auto_link_summary_counts_what_it_says() -> None:
    """``considered``, ``skipped`` et ``evidence_count`` disent la vérité."""
    registry = _registry()
    _trace(registry, requirement_id="req_1", requirement_text="Excel modelling and valuation")
    _trace(registry, requirement_id="req_2", requirement_text="Bloomberg terminal")
    linked = _trace(registry, requirement_id="req_3", requirement_text="Excel modelling and valuation")
    registry.link_evidence(
        linked.trace_id,
        evidence_id="ev-0",
        evidence_quote="Excel modelling and valuation",
        origin="auto",
    )

    summary = auto_link_evidence(
        registry,
        [
            {"evidence_id": "ev-1", "claim": "Excel modelling and valuation", "quote": "Excel modelling"},
            {"evidence_id": "", "claim": "Sans identifiant", "quote": ""},
        ],
    )

    assert summary["evidence_count"] == 1  # la preuve sans identifiant est ignorée
    assert summary["considered"] == 2  # req_1 et req_2
    assert summary["skipped"] == 1  # req_3 porte déjà une proposition
    assert summary["linked_count"] == 1
    assert summary["pending_count"] == 1


# ── 6. Une exigence retirée de l'offre n'est plus un gap éternel ────────────


def test_a_requirement_that_left_the_offer_is_superseded_and_not_a_gap() -> None:
    """Une exigence absente de la nouvelle analyse est supersédée, plus un gap."""
    registry = _registry()
    registry.register_offer_analysis(
        _analysis(
            _requirement_record("req_1", "Excel modelling and valuation skills."),
            _requirement_record("req_2", "Fluent English required."),
        ),
        supersede_missing=True,
    )

    registry.register_offer_analysis(
        _analysis(_requirement_record("req_1", "Excel modelling and valuation skills.")),
        supersede_missing=True,
    )

    traces = {trace.requirement_id: trace for trace in registry.all()}
    assert traces["req_1"].is_superseded is False
    assert traces["req_2"].is_superseded is True
    assert "superseded" in [event.event_type for event in traces["req_2"].history]
    # Un gap est une exigence obligatoire encore demandée : celle-ci ne l'est
    # plus, l'autre (toujours demandée, sans preuve) reste un gap.
    gaps = critical_gaps(registry.all())
    assert [gap["requirement_id"] for gap in gaps] == ["req_1"]
    # Et l'exigence remplacée sort du dénominateur de couverture.
    summary = coverage_summary(registry.all())
    assert summary["total"] == 2
    assert summary["evaluated"] == 1
    assert summary["superseded_count"] == 1


def test_a_truncated_analysis_never_supersedes_a_requirement() -> None:
    """Une extraction tronquée ne prouve pas qu'une exigence a disparu."""
    registry = _registry()
    registry.register_offer_analysis(
        _analysis(
            _requirement_record("req_1", "Excel modelling and valuation skills."),
            _requirement_record("req_2", "Fluent English required."),
        ),
        supersede_missing=True,
    )

    registry.register_offer_analysis(
        _analysis(_requirement_record("req_1", "Excel modelling and valuation skills."), truncated=True),
        supersede_missing=True,
    )

    traces = {trace.requirement_id: trace for trace in registry.all()}
    assert traces["req_2"].is_superseded is False
    # Les deux exigences restent demandées : elles restent deux gaps.
    assert [gap["requirement_id"] for gap in critical_gaps(registry.all())] == ["req_1", "req_2"]


def test_the_generic_import_path_never_supersedes_a_requirement() -> None:
    """Seule l'intégration SK-02 (analyse complète) supersède une exigence."""
    registry = _registry()
    registry.register_offer_analysis(
        _analysis(
            _requirement_record("req_1", "Excel modelling and valuation skills."),
            _requirement_record("req_2", "Fluent English required."),
        )
    )

    registry.register_offer_analysis(
        _analysis(_requirement_record("req_1", "Excel modelling and valuation skills."))
    )

    traces = {trace.requirement_id: trace for trace in registry.all()}
    assert traces["req_2"].is_superseded is False


def test_the_audit_report_lists_the_superseded_requirements() -> None:
    """Le rapport d'audit expose les exigences remplacées."""
    registry = _registry()
    registry.register_offer_analysis(
        _analysis(
            _requirement_record("req_1", "Excel modelling and valuation skills."),
            _requirement_record("req_2", "Fluent English required."),
        ),
        supersede_missing=True,
    )
    registry.register_offer_analysis(
        _analysis(_requirement_record("req_1", "Excel modelling and valuation skills.")),
        supersede_missing=True,
    )

    report = audit_report(registry.all())
    assert len(report["superseded"]) == 1
    assert report["superseded"][0]["requirement_id"] == "req_2"
    assert len(superseded_requirements(registry.all())) == 1


# ── 7. Une exigence modifiée ou retrouvée reste tracée ──────────────────────


def test_a_changed_requirement_text_is_traced() -> None:
    """Le texte verbatim suit la source, et le changement reste dans l'historique."""
    registry = _registry()
    trace = _trace(registry)
    registry.register(
        "req_1",
        "Excel modelling and valuation (mise à jour)",
        "offer_job_1",
        category="skill",
        criticality="mandatory",
    )

    assert trace.requirement_text == "Excel modelling and valuation (mise à jour)"
    assert "requirement_changed" in [event.event_type for event in trace.history]
    # Un ré-enregistrement identique ne produit aucun événement de plus.
    registry.register(
        "req_1",
        "Excel modelling and valuation (mise à jour)",
        "offer_job_1",
        category="skill",
        criticality="mandatory",
    )
    assert [event.event_type for event in trace.history].count("requirement_changed") == 1


def test_a_deleted_requirement_found_again_comes_back_with_an_event() -> None:
    """Une exigence supprimée puis retrouvée dans sa source redevient active."""
    registry = _registry()
    trace = _trace(registry)
    registry.delete(trace.trace_id)
    assert registry.get(trace.trace_id) is None

    registry.register(
        "req_1",
        "Excel modelling and valuation",
        "offer_job_1",
        category="skill",
        criticality="mandatory",
    )

    restored = registry.get(trace.trace_id)
    assert restored is not None
    assert restored.deleted is False
    assert "restored" in [event.event_type for event in restored.history]


def test_unlinking_a_proof_keeps_a_waiver() -> None:
    """Retirer une preuve n'annule pas silencieusement une dérogation motivée."""
    registry = _registry()
    trace = _trace(registry)
    registry.waive(trace.trace_id, "Exigence non applicable à ce poste.")

    registry.unlink_evidence(trace.trace_id)

    assert trace.status == "waived"


# ── 8. La garantie centrale : « covered » = preuve citée + lien validé ──────


@pytest.mark.parametrize(
    "operation",
    [
        lambda registry, trace: registry.link_evidence(
            trace.trace_id, evidence_id="ev-1", evidence_quote="Excel modelling and valuation", origin="auto"
        ),
        lambda registry, trace: registry.link_evidence(
            trace.trace_id, evidence_id="ev-2", evidence_quote="Excel modelling and valuation", origin="auto"
        ),
        lambda registry, trace: registry.set_status(trace.trace_id, "covered"),
        lambda registry, trace: registry.confirm_link(trace.trace_id),
    ],
)
def test_no_operation_declares_a_coverage_without_a_confirmed_cited_proof(operation) -> None:
    """Invariant : « covered » implique une preuve citée et un lien validé."""
    registry = _registry()
    trace = _trace(registry)
    registry.link_evidence(
        trace.trace_id,
        evidence_id="ev-0",
        evidence_quote="Excel modelling and valuation",
        origin="auto",
    )
    try:
        operation(registry, trace)
    except TraceabilityError:
        pass

    if trace.status == "covered":
        assert trace.evidence_id
        assert trace.evidence_quote
        assert trace.review_state == "confirmed"
    report = audit_report(registry.all())
    assert "covered_without_review" not in {problem["code"] for problem in report["inconsistencies"]}


# ── 9. Intégration Career : l'offre drives le registre ──────────────────────


def test_an_offer_that_loses_a_requirement_leaves_no_permanent_gap(tmp_path: Path) -> None:
    """Le cycle import → offre modifiée → ré-import reste cohérent."""
    service = CareerService(tmp_path)
    job = service.import_job(
        {
            "company": "Banque Démo",
            "title": "Summer Analyst",
            "source_name": "manual",
            "requirements": "Excel modelling and valuation skills.\nFluent English required.",
            "description_original": "",
        }
    )
    assert service.traceability.list_requirements({"offer_id": job["id"]})["count"] == 2

    # La même offre est réimportée avec une exigence en moins : l'offre est
    # rafraîchie, l'analyse SK-02 change, l'exigence disparue est supersédée.
    service.import_job(
        {
            "company": "Banque Démo",
            "title": "Summer Analyst",
            "source_name": "manual",
            "requirements": "Excel modelling and valuation skills.",
            "description_original": "",
        }
    )

    traces = service.traceability.list_requirements({"offer_id": job["id"]})["requirements"]
    assert len(traces) == 2
    superseded = [trace for trace in traces if trace["superseded_at"]]
    assert len(superseded) == 1
    assert superseded[0]["requirement_text"] == "Fluent English required."


def test_the_http_api_refuses_a_forged_import(tmp_path: Path) -> None:
    """L'endpoint d'import refuse une identité truquée."""
    client = _client(tmp_path)
    client.post(
        "/api/career/traceability/requirements",
        json={"requirement_id": "req_1", "requirement_text": "Excel modelling", "source": "offer_job_1"},
    )
    forged = {
        "schema_version": 1,
        "traces": [
            {
                "trace_id": "trace_forged",
                "requirement_id": "req_1",
                "requirement_text": "Excel modelling",
                "source": "offer_job_1",
                "status": "uncovered",
                "created_at": "2026-10-01T09:00:00+00:00",
                "updated_at": "2026-10-01T09:00:00+00:00",
                "history": [],
            }
        ],
    }

    response = client.post("/api/career/traceability/import", json={"registry": forged})

    assert response.status_code == 200
    assert response.json()["invalid"] == 1
    assert client.get("/api/career/traceability/requirements").json()["count"] == 1


def test_the_http_api_exposes_the_superseded_requirements(tmp_path: Path) -> None:
    """Le rapport « remplacées » est servi par l'API locale."""
    client = _client(tmp_path)
    response = client.get("/api/career/traceability/audit/superseded")
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_the_http_api_never_declares_a_coverage_without_a_validation(tmp_path: Path) -> None:
    """Une proposition automatique reste « à valider » jusqu'à la confirmation."""
    client = _client(tmp_path)
    created = client.post(
        "/api/career/traceability/requirements",
        json={
            "requirement_id": "req_1",
            "requirement_text": "Excel modelling and valuation",
            "source": "offer_job_1",
            "criticality": "mandatory",
        },
    )
    trace_id = created.json()["trace_id"]

    proposed = client.post(
        "/api/career/traceability/auto-link",
        json={
            "evidences": [
                {
                    "evidence_id": "profile.skills",
                    "claim": "Excel modelling and valuation",
                    "quote": "Excel modelling and valuation",
                }
            ]
        },
    )
    assert proposed.status_code == 200
    assert proposed.json()["linked_count"] == 1

    pending = client.get(f"/api/career/traceability/requirements/{trace_id}").json()
    assert pending["review_state"] == "pending"
    assert pending["status"] == "uncovered"

    refused = client.patch(
        f"/api/career/traceability/requirements/{trace_id}",
        json={"status": "covered"},
    )
    assert refused.status_code == 400
    assert client.get(f"/api/career/traceability/requirements/{trace_id}").json()["status"] == "uncovered"

    confirmed = client.post(
        f"/api/career/traceability/requirements/{trace_id}/confirm",
        json={"comment": "Validée."},
    )
    assert confirmed.json()["status"] == "covered"
    assert confirmed.json()["review_state"] == "confirmed"


def test_the_trace_id_of_a_requirement_is_always_derivable() -> None:
    """L'identité d'une trace se recalcule : elle ne dépend que de sa source."""
    registry = _registry()
    trace = _trace(registry)
    assert trace.trace_id == requirement_trace_id("offer_job_1", "req_1")
    assert requirement_trace_id("offer_job_1", "req_1") != requirement_trace_id("offer_job_2", "req_1")
