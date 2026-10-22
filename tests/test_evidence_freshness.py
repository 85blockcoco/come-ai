"""SPEC-012 — Fraîcheur des preuves : règles, persistance, rapports et API.

Toutes les fixtures sont synthétiques : aucune donnée réelle n'est utilisée,
aucun appel réseau n'est effectué et aucune horloge système n'est consultée
pour les décisions testées (le « maintenant » est toujours injecté).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.evidence_freshness import (
    ALERT_CRITICAL,
    ALERT_INFO,
    ALERT_WARNING,
    COVERAGE_ARCHIVED,
    COVERAGE_COVERED,
    COVERAGE_WARNING,
    FRESHNESS_POLICIES,
    STATUS_ARCHIVED,
    STATUS_EXPIRED,
    STATUS_FRESH,
    STATUS_WARNING,
    apply_actions,
    build_alerts,
    check_frequency,
    evaluate_evidence,
    freshness_to_dict,
    is_check_due,
    normalize_policy,
    planned_actions,
    policy_for,
    refresh,
    source_check_alert,
)
from career.evidence_freshness_audit import (
    dashboard as build_dashboard,
    export_gate,
    report as build_report,
    trend_series,
)
from career.evidence_freshness_store import EvidenceFreshnessStore, normalize_check
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def evidence_record(**changes: object) -> dict[str, object]:
    """Return a synthetic proof the tests can bend as they need."""
    record: dict[str, object] = {
        "id": "ev_demo",
        "type": "certification",
        "label": "Certification de démonstration",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_verified_at": "2026-01-01T00:00:00+00:00",
        "mandatory": True,
        "archived": False,
        "coverage_status": COVERAGE_COVERED,
        "policy_overrides": {},
        "source_checks": [],
        "auto_actions": [],
    }
    record.update(changes)
    return record


def freshness_client(service: CareerService) -> TestClient:
    """Build a minimal app with the same error contract as the real one."""
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Policies
# ---------------------------------------------------------------------------


def test_policies_ship_the_contracted_values() -> None:
    assert FRESHNESS_POLICIES == {
        "certification": {"max_age_days": 365, "warning_days": 30, "auto_expire": True},
        "skill_technical": {"max_age_days": 730, "warning_days": 90, "auto_expire": False},
        "skill_soft": {"max_age_days": 1095, "warning_days": 180, "auto_expire": False},
        "experience": {"max_age_days": 1825, "warning_days": 365, "auto_expire": False},
        "education": {"max_age_days": None, "warning_days": None, "auto_expire": False},
        "language": {"max_age_days": 730, "warning_days": 90, "auto_expire": True},
        "tool": {"max_age_days": 730, "warning_days": 90, "auto_expire": False},
        "project": {"max_age_days": 1095, "warning_days": 180, "auto_expire": False},
    }


def test_policy_normalisation_keeps_valid_values() -> None:
    assert normalize_policy({"max_age_days": 120, "warning_days": 30, "auto_expire": True}) == {
        "max_age_days": 120,
        "warning_days": 30,
        "auto_expire": True,
    }


def test_policy_normalisation_refuses_a_warning_wider_than_the_validity() -> None:
    with pytest.raises(UserFacingError):
        normalize_policy({"max_age_days": 30, "warning_days": 90})


def test_policy_without_expiry_drops_the_warning_window() -> None:
    assert normalize_policy({"max_age_days": None, "warning_days": 30}) == {
        "max_age_days": None,
        "warning_days": None,
        "auto_expire": False,
    }


def test_policy_override_replaces_only_the_given_type() -> None:
    overrides = {"certification": {"max_age_days": 30, "warning_days": 5, "auto_expire": False}}
    assert policy_for("certification", overrides)["max_age_days"] == 30
    assert policy_for("tool", overrides)["max_age_days"] == 730


# ---------------------------------------------------------------------------
# 2. Evaluation
# ---------------------------------------------------------------------------


def test_a_fresh_proof_reports_its_dates_without_expiring() -> None:
    freshness = evaluate_evidence(evidence_record(), now=NOW)
    assert freshness.status == STATUS_FRESH
    assert freshness.expires_at == "2027-01-01T00:00:00+00:00"
    assert freshness.warning_at == "2026-12-02T00:00:00+00:00"


def test_a_proof_without_expiry_policy_never_expires() -> None:
    freshness = evaluate_evidence(
        evidence_record(type="education", created_at="2000-01-01T00:00:00+00:00"), now=NOW
    )
    assert freshness.status == STATUS_FRESH
    assert freshness.expires_at is None
    assert freshness.warning_at is None


def test_a_proof_moves_from_fresh_to_warning_then_expired() -> None:
    record = evidence_record(last_verified_at="2026-01-01T00:00:00+00:00")
    assert evaluate_evidence(record, now=NOW).status == STATUS_FRESH
    warning = evaluate_evidence(record, now=datetime(2026, 12, 10, tzinfo=timezone.utc))
    assert warning.status == STATUS_WARNING
    expired = evaluate_evidence(record, now=datetime(2027, 2, 1, tzinfo=timezone.utc))
    assert expired.status == STATUS_EXPIRED


def test_an_explicit_expiry_overrides_the_policy() -> None:
    record = evidence_record(expires_at="2026-11-15T00:00:00+00:00")
    freshness = evaluate_evidence(record, now=NOW)
    assert freshness.expires_at == "2026-11-15T00:00:00+00:00"
    # The warning window is recomputed from the explicit expiry.
    assert freshness.warning_at == "2026-10-16T00:00:00+00:00"


def test_an_archived_proof_is_reported_as_archived() -> None:
    freshness = evaluate_evidence(evidence_record(archived=True), now=NOW)
    assert freshness.status == STATUS_ARCHIVED


def test_an_unreadable_date_is_never_replaced_by_another_one() -> None:
    freshness = evaluate_evidence(
        evidence_record(created_at="pas une date", last_verified_at=""), now=NOW
    )
    assert freshness.created_at == ""
    assert freshness.expires_at is None
    assert freshness.status == STATUS_FRESH


# ---------------------------------------------------------------------------
# 3. Alerts
# ---------------------------------------------------------------------------


def test_alert_levels_follow_the_contract() -> None:
    record = evidence_record(last_verified_at="2026-01-01T00:00:00+00:00")
    warning_zone = evaluate_evidence(record, now=datetime(2026, 12, 10, tzinfo=timezone.utc))
    assert build_alerts([record], [warning_zone], now=datetime(2026, 12, 10, tzinfo=timezone.utc))[0]["level"] == ALERT_INFO

    expiring = evaluate_evidence(record, now=datetime(2026, 12, 28, tzinfo=timezone.utc))
    assert build_alerts([record], [expiring], now=datetime(2026, 12, 28, tzinfo=timezone.utc))[0]["level"] == ALERT_WARNING

    expired = evaluate_evidence(record, now=datetime(2027, 2, 1, tzinfo=timezone.utc))
    assert build_alerts([record], [expired], now=datetime(2027, 2, 1, tzinfo=timezone.utc))[0]["level"] == ALERT_CRITICAL


def test_one_expired_proof_raises_a_single_critical_alert() -> None:
    record = evidence_record(last_verified_at="2026-01-01T00:00:00+00:00")
    freshness = evaluate_evidence(record, now=datetime(2027, 2, 1, tzinfo=timezone.utc))
    alerts = build_alerts([record], [freshness])
    assert len(alerts) == 1
    assert alerts[0]["code"] == "evidence_expired"


def test_a_fresh_proof_raises_no_alert() -> None:
    record = evidence_record()
    freshness = evaluate_evidence(record, now=NOW)
    assert build_alerts([record], [freshness]) == []


# ---------------------------------------------------------------------------
# 4. Automatic actions
# ---------------------------------------------------------------------------


def test_an_expired_mandatory_proof_is_downgraded_and_an_optional_one_archived() -> None:
    mandatory = evidence_record(id="ev_mandatory", mandatory=True, last_verified_at="2025-01-01T00:00:00+00:00")
    optional = evidence_record(id="ev_optional", mandatory=False, last_verified_at="2025-01-01T00:00:00+00:00")
    now = datetime(2027, 2, 1, tzinfo=timezone.utc)

    mandatory_actions = planned_actions(mandatory, evaluate_evidence(mandatory, now=now), now=now)
    assert "downgrade_to_warning" in mandatory_actions
    assert apply_actions(mandatory, mandatory_actions, now=now)["coverage_status"] == COVERAGE_WARNING

    optional_actions = planned_actions(optional, evaluate_evidence(optional, now=now), now=now)
    assert "archive_optional" in optional_actions
    assert apply_actions(optional, optional_actions, now=now)["coverage_status"] == COVERAGE_ARCHIVED


def test_an_archived_optional_proof_keeps_the_truth_of_its_expiry() -> None:
    record = evidence_record(mandatory=False, last_verified_at="2025-01-01T00:00:00+00:00")
    now = datetime(2027, 2, 1, tzinfo=timezone.utc)
    freshness = evaluate_evidence(record, now=now)
    updated = apply_actions(record, planned_actions(record, freshness, now=now), now=now)
    assert updated["coverage_status"] == COVERAGE_ARCHIVED
    assert evaluate_evidence(updated, now=now).status == STATUS_EXPIRED


def test_automatic_actions_are_applied_only_once() -> None:
    record = evidence_record(mandatory=True, last_verified_at="2025-01-01T00:00:00+00:00")
    now = datetime(2027, 2, 1, tzinfo=timezone.utc)
    first = apply_actions(record, planned_actions(record, evaluate_evidence(record, now=now), now=now), now=now)
    second = apply_actions(first, planned_actions(first, evaluate_evidence(first, now=now), now=now), now=now)
    assert second["coverage_status"] == COVERAGE_WARNING
    assert len(second["auto_actions"]) == len(first["auto_actions"])


def test_the_refresh_cycle_reports_the_changed_proofs() -> None:
    record = evidence_record(mandatory=True, last_verified_at="2025-01-01T00:00:00+00:00")
    result = refresh([record], now=datetime(2027, 2, 1, tzinfo=timezone.utc))
    assert result.changed == ["ev_demo"]
    assert result.records[0]["coverage_status"] == COVERAGE_WARNING
    assert result.alerts[0]["level"] == ALERT_CRITICAL


def test_the_refresh_cycle_can_be_run_without_writing() -> None:
    record = evidence_record(mandatory=True, last_verified_at="2025-01-01T00:00:00+00:00")
    result = refresh([record], now=datetime(2027, 2, 1, tzinfo=timezone.utc), apply=False)
    assert result.changed == []
    assert result.records[0]["coverage_status"] == COVERAGE_COVERED


# ---------------------------------------------------------------------------
# 5. Source checks
# ---------------------------------------------------------------------------


def test_an_unchanged_source_refreshes_the_anchor() -> None:
    record = evidence_record(last_verified_at="2026-01-01T00:00:00+00:00")
    check = normalize_check(method="http", result="unchanged", source_url="https://exemple.test/cert")
    assert check.method == "http"
    assert check.result == "unchanged"
    freshness = evaluate_evidence({**record, "last_verified_at": "2026-10-22T12:00:00+00:00"}, now=NOW)
    assert freshness.expires_at == "2027-10-22T12:00:00+00:00"


def test_a_changed_source_asks_for_a_new_verification() -> None:
    record = evidence_record()
    check = normalize_check(method="api", result="updated")
    alert = source_check_alert(record, check)
    assert alert is not None
    assert alert["code"] == "source_changed"
    assert alert["level"] == ALERT_WARNING


def test_a_removed_source_is_treated_as_a_revocation() -> None:
    record = evidence_record()
    check = normalize_check(method="http", result="removed")
    alert = source_check_alert(record, check)
    assert alert is not None
    assert alert["code"] == "source_revoked"
    assert alert["level"] == ALERT_CRITICAL


def test_a_failed_check_does_not_change_the_status_of_the_proof() -> None:
    record = evidence_record()
    check = normalize_check(method="http", result="error")
    alert = source_check_alert(record, check)
    assert alert is not None
    assert alert["code"] == "source_check_failed"
    assert alert["level"] == ALERT_INFO


def test_an_unknown_check_method_is_refused() -> None:
    with pytest.raises(ValueError):
        normalize_check(method="telepathy", result="unchanged")
    with pytest.raises(ValueError):
        normalize_check(method="http", result="maybe")


# ---------------------------------------------------------------------------
# 6. Scheduling
# ---------------------------------------------------------------------------


def test_check_frequency_follows_the_scheduling_table() -> None:
    certification = evaluate_evidence(evidence_record(type="certification"), now=NOW)
    assert check_frequency(evidence_record(type="certification"), certification, now=NOW) == "weekly"

    tool = evaluate_evidence(evidence_record(type="tool"), now=NOW)
    assert check_frequency(evidence_record(type="tool"), tool, now=NOW) == "monthly"

    experience = evaluate_evidence(evidence_record(type="experience"), now=NOW)
    assert check_frequency(evidence_record(type="experience"), experience, now=NOW) == "quarterly"


def test_a_proof_in_the_warning_window_is_checked_every_day() -> None:
    record = evidence_record(last_verified_at="2026-01-01T00:00:00+00:00")
    reference = datetime(2026, 12, 10, tzinfo=timezone.utc)
    freshness = evaluate_evidence(record, now=reference)
    assert freshness.status == STATUS_WARNING
    assert check_frequency(record, freshness, now=reference) == "daily"


def test_a_check_is_due_when_the_interval_has_passed() -> None:
    assert is_check_due(None, "weekly", now=NOW) is True
    assert is_check_due("2026-10-20T12:00:00+00:00", "weekly", now=NOW) is False
    assert is_check_due("2026-10-22T12:00:00+00:00", "daily", now=NOW) is False
    assert is_check_due("2026-10-20T12:00:00+00:00", "daily", now=NOW) is True
    assert is_check_due("2026-10-01T12:00:00+00:00", "weekly", now=NOW) is True


# ---------------------------------------------------------------------------
# 7. Store
# ---------------------------------------------------------------------------


def test_the_store_round_trips_the_proofs_and_the_policies(tmp_path: Path) -> None:
    store = EvidenceFreshnessStore(tmp_path)
    store.save_evidence(evidence_record())
    store.set_policy("certification", {"max_age_days": 90, "warning_days": 15, "auto_expire": True})

    reopened = EvidenceFreshnessStore(tmp_path)
    assert [item["id"] for item in reopened.list_evidence()] == ["ev_demo"]
    assert reopened.policies()["certification"]["max_age_days"] == 90
    assert reopened.effective_policies()["tool"]["max_age_days"] == 730


def test_the_store_keeps_the_state_private(tmp_path: Path) -> None:
    store = EvidenceFreshnessStore(tmp_path)
    store.save_evidence(evidence_record())
    assert store.path.exists()
    assert store.path.parent.name == "evidence_freshness"
    assert oct(store.path.stat().st_mode)[-3:] == "600"


def test_the_store_does_not_duplicate_an_open_alert(tmp_path: Path) -> None:
    store = EvidenceFreshnessStore(tmp_path)
    first = store.add_alert({"evidence_id": "ev_demo", "code": "evidence_expired", "level": "critical"})
    second = store.add_alert({"evidence_id": "ev_demo", "code": "evidence_expired", "level": "critical"})
    assert first["alert_id"] == second["alert_id"]
    assert len(store.list_alerts()) == 1


def test_acknowledging_an_alert_removes_it_from_the_active_list(tmp_path: Path) -> None:
    store = EvidenceFreshnessStore(tmp_path)
    alert = store.add_alert({"evidence_id": "ev_demo", "code": "evidence_expired", "level": "critical"})
    assert store.acknowledge_alert(alert["alert_id"]) is not None
    assert store.list_alerts(active_only=True) == []
    assert len(store.list_alerts(active_only=False)) == 1


def test_deleting_a_proof_removes_its_alerts(tmp_path: Path) -> None:
    store = EvidenceFreshnessStore(tmp_path)
    store.save_evidence(evidence_record())
    store.add_alert({"evidence_id": "ev_demo", "code": "evidence_expired", "level": "critical"})
    assert store.delete_evidence("ev_demo") is True
    assert store.list_alerts(active_only=False) == []


def test_the_store_survives_a_corrupted_state_file(tmp_path: Path) -> None:
    store = EvidenceFreshnessStore(tmp_path)
    store.save_evidence(evidence_record())
    store.path.write_text("{pas du json", encoding="utf-8")
    assert EvidenceFreshnessStore(tmp_path).list_evidence() == []


def test_the_store_reset_removes_the_whole_state(tmp_path: Path) -> None:
    store = EvidenceFreshnessStore(tmp_path)
    store.save_evidence(evidence_record())
    store.record_snapshot({"at": "2026-10-22T12:00:00+00:00", "counts": {"fresh": 1}, "total": 1, "fresh_ratio": 1.0})
    store.reset()
    assert store.list_evidence() == []
    assert store.snapshots() == []


def test_the_store_lists_the_checks_that_are_due(tmp_path: Path) -> None:
    store = EvidenceFreshnessStore(tmp_path)
    store.save_evidence(evidence_record(type="tool"))
    freshness = evaluate_evidence(evidence_record(type="tool"), now=NOW)
    due = store.due_checks([freshness], now=NOW)
    assert due[0]["evidence_id"] == "ev_demo"
    assert due[0]["frequency"] == "monthly"


# ---------------------------------------------------------------------------
# 8. Audit
# ---------------------------------------------------------------------------


def test_the_dashboard_reports_the_distribution_and_the_timeline() -> None:
    records = [
        evidence_record(id="ev_fresh", last_verified_at="2026-10-01T00:00:00+00:00"),
        evidence_record(id="ev_warning", last_verified_at="2025-11-01T00:00:00+00:00"),
        evidence_record(id="ev_expired", last_verified_at="2025-01-01T00:00:00+00:00"),
    ]
    freshnesses = [evaluate_evidence(record, now=NOW) for record in records]
    payload = build_dashboard(freshnesses, records=records, now=NOW)
    assert payload["counts"]["total"] == 3
    assert payload["counts"]["fresh"] == 1
    assert payload["counts"]["warning"] == 1
    assert payload["counts"]["expired"] == 1
    assert payload["ratios"]["fresh"] == 33.3
    assert payload["by_type"]["certification"]["total"] == 3
    assert payload["timeline"]["buckets"]["90d"] >= 1


def test_the_export_gate_blocks_on_a_critical_alert() -> None:
    alerts = [{"level": "critical", "acknowledged": False, "label": "Certification", "message": "Expirée"}]
    gate = export_gate(alerts)
    assert gate["blocked"] is True
    assert gate["blockers"][0]["label"] == "Certification"
    assert export_gate([])["blocked"] is False


def test_the_trend_series_only_uses_the_recorded_snapshots() -> None:
    snapshots = [
        {"at": "2026-10-20T12:00:00+00:00", "counts": {"fresh": 2}, "total": 3, "fresh_ratio": 0.66},
        {"at": "2026-10-21T12:00:00+00:00", "counts": {"fresh": 3}, "total": 3, "fresh_ratio": 1.0},
    ]
    series = trend_series(snapshots, 30)
    assert [point["at"] for point in series] == ["2026-10-20T12:00:00+00:00", "2026-10-21T12:00:00+00:00"]
    assert series[-1]["fresh_ratio"] == 1.0


def test_the_report_gathers_the_policies_and_the_trends() -> None:
    records = [evidence_record()]
    freshnesses = [evaluate_evidence(record, now=NOW) for record in records]
    payload = build_report(
        freshnesses,
        records=records,
        policies={"certification": FRESHNESS_POLICIES["certification"]},
        snapshots=[{"at": "2026-10-21T12:00:00+00:00", "counts": {"fresh": 1}, "total": 1, "fresh_ratio": 1.0}],
        now=NOW,
    )
    assert "30d" in payload["trends"]
    assert payload["policies"]["certification"]["max_age_days"] == 365
    assert payload["history_size"] == 1


def test_the_freshness_is_serialized_for_the_api() -> None:
    freshness = evaluate_evidence(evidence_record(), now=NOW)
    payload = freshness_to_dict(freshness)
    assert payload["evidence_id"] == "ev_demo"
    assert payload["status"] == STATUS_FRESH
    assert payload["source_checks"] == []


# ---------------------------------------------------------------------------
# 9. Service
# ---------------------------------------------------------------------------


def test_the_service_creates_updates_and_deletes_a_proof(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    created = service.create_evidence(
        {"evidence_type": "certification", "label": "Certification démo", "created_at": "2026-01-01"}
    )
    evidence_id = created["evidence"]["id"]
    assert created["freshness"]["status"] == STATUS_FRESH

    updated = service.update_evidence(evidence_id, {"last_verified_at": "2026-10-01", "mandatory": False})
    assert updated["freshness"]["last_verified_at"] == "2026-10-01T00:00:00+00:00"

    service.delete_evidence(evidence_id)
    with pytest.raises(UserFacingError):
        service.evidence_freshness_detail(evidence_id)


def test_the_service_refuses_an_unknown_proof_type(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    with pytest.raises(UserFacingError):
        service.create_evidence({"evidence_type": "astrology", "label": "Étoiles"})


def test_the_service_refuses_an_unreadable_date(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    with pytest.raises(UserFacingError):
        service.create_evidence({"evidence_type": "certification", "label": "Démo", "expires_at": "bientôt"})


def test_the_service_sweeps_and_degrades_the_expired_proofs(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.create_evidence(
        {
            "evidence_type": "certification",
            "label": "Certification expirée",
            "created_at": "2024-01-01",
            "last_verified_at": "2024-01-01",
            "mandatory": True,
        }
    )
    result = service.run_evidence_freshness_monitor()
    assert result["checked"] == 1
    assert len(result["changed"]) == 1
    assert result["alerts"][0]["level"] == ALERT_CRITICAL
    assert result["snapshot"]["counts"]["expired"] == 1

    records = service._freshness_records()
    assert records[0]["coverage_status"] == COVERAGE_WARNING


def test_the_sweep_is_idempotent(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.create_evidence(
        {"evidence_type": "certification", "label": "Certification expirée", "last_verified_at": "2024-01-01"}
    )
    service.run_evidence_freshness_monitor()
    second = service.run_evidence_freshness_monitor()
    assert second["changed"] == []
    assert len(second["alerts"]) == 1


def test_the_service_sets_a_policy_and_keeps_the_other_types(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    result = service.set_evidence_freshness_policy(
        {"evidence_type": "certification", "max_age_days": 90, "warning_days": 15}
    )
    assert result["policy"]["max_age_days"] == 90
    assert result["policies"]["tool"]["max_age_days"] == 730


def test_the_service_records_a_manual_check(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    created = service.create_evidence({"evidence_type": "tool", "label": "Excel", "last_verified_at": "2025-01-01"})
    evidence_id = created["evidence"]["id"]
    result = service.trigger_evidence_check(evidence_id, {"method": "manual", "result": "unchanged"})
    assert result["check"]["result"] == "unchanged"
    assert result["freshness"]["status"] == STATUS_FRESH
    assert len(result["evidence"]["source_checks"]) == 1


def test_the_service_raises_a_critical_alert_on_a_removed_source(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    created = service.create_evidence({"evidence_type": "certification", "label": "Certif démo"})
    evidence_id = created["evidence"]["id"]
    result = service.trigger_evidence_check(evidence_id, {"method": "http", "result": "removed"})
    assert result["alert"]["level"] == ALERT_CRITICAL
    assert result["freshness"]["status"] == STATUS_EXPIRED


def test_the_service_status_reports_the_policies_and_the_due_checks(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.create_evidence({"evidence_type": "tool", "label": "Excel"})
    status = service.evidence_freshness_status()
    assert status["counts"]["total"] == 1
    assert status["policies"]["tool"]["max_age_days"] == 730
    assert status["due_checks"][0]["evidence_id"]


def test_the_privacy_export_contains_the_freshness_state(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.create_evidence({"evidence_type": "certification", "label": "Certif démo"})
    service.run_evidence_freshness_monitor()
    path = service.export_personal_data()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["evidence_freshness"]["evidence"]) == 1
    assert payload["evidence_freshness"]["snapshots"]


def test_resetting_the_personal_data_erases_the_freshness_state(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.create_evidence({"evidence_type": "certification", "label": "Certif démo"})
    service.reset_personal_data("SUPPRIMER MES DONNÉES CAREER")
    assert service._freshness_records() == []


# ---------------------------------------------------------------------------
# 10. HTTP API
# ---------------------------------------------------------------------------


def test_the_api_exposes_the_freshness_endpoints(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = freshness_client(service)

    created = client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "certification", "label": "Certification démo", "created_at": "2026-01-01"},
    )
    assert created.status_code == 201
    evidence_id = created.json()["evidence"]["id"]

    status = client.get("/api/career/evidence-freshness/status")
    assert status.status_code == 200
    assert status.json()["counts"]["total"] == 1

    detail = client.get(f"/api/career/evidence-freshness/evidence/{evidence_id}")
    assert detail.status_code == 200
    assert detail.json()["freshness"]["evidence_id"] == evidence_id

    listing = client.get("/api/career/evidence-freshness/evidence")
    assert listing.json()["count"] == 1

    patched = client.patch(
        f"/api/career/evidence-freshness/evidence/{evidence_id}",
        json={"last_verified_at": "2026-10-01"},
    )
    assert patched.status_code == 200
    assert patched.json()["freshness"]["last_verified_at"] == "2026-10-01T00:00:00+00:00"

    policy = client.post(
        "/api/career/evidence-freshness/policy",
        json={"evidence_type": "certification", "max_age_days": 120, "warning_days": 20},
    )
    assert policy.status_code == 200
    assert policy.json()["policy"]["max_age_days"] == 120

    check = client.post(
        f"/api/career/evidence-freshness/check/{evidence_id}",
        json={"method": "manual", "result": "unchanged"},
    )
    assert check.status_code == 200

    monitor = client.post("/api/career/evidence-freshness/monitor")
    assert monitor.status_code == 200
    assert monitor.json()["checked"] == 1

    alerts = client.get("/api/career/evidence-freshness/alerts")
    assert alerts.status_code == 200

    report = client.get("/api/career/evidence-freshness/report")
    assert report.status_code == 200
    assert "trends" in report.json()

    policies = client.get("/api/career/evidence-freshness/policy")
    assert policies.status_code == 200
    assert policies.json()["policies"]["certification"]["max_age_days"] == 120

    schedule = client.get("/api/career/evidence-freshness/schedule")
    assert schedule.status_code == 200
    assert schedule.json()["intervals"]["weekly"] == 7

    deleted = client.delete(f"/api/career/evidence-freshness/evidence/{evidence_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/career/evidence-freshness/evidence/{evidence_id}").status_code == 400


def test_the_api_refuses_an_unknown_proof_with_a_readable_message(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = freshness_client(service)
    response = client.get("/api/career/evidence-freshness/evidence/ev_inconnue")
    assert response.status_code == 400
    assert "preuve" in response.json()["detail"].lower()


def test_the_api_acknowledges_an_alert(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = freshness_client(service)
    client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "certification", "label": "Vieille certif", "last_verified_at": "2024-01-01"},
    )
    client.post("/api/career/evidence-freshness/monitor")
    alerts = client.get("/api/career/evidence-freshness/alerts").json()["alerts"]
    assert alerts
    acknowledged = client.post(f"/api/career/evidence-freshness/acknowledge/{alerts[0]['alert_id']}")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["alert"]["acknowledged"] is True
    assert client.get("/api/career/evidence-freshness/alerts").json()["count"] == 0


def test_the_api_refuses_a_policy_with_an_impossible_window(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = freshness_client(service)
    response = client.post(
        "/api/career/evidence-freshness/policy",
        json={"evidence_type": "certification", "max_age_days": 30, "warning_days": 90},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 11. UI
# ---------------------------------------------------------------------------


def test_the_freshness_view_is_reachable_from_the_navigation() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "career_static" / "index.html").read_text(encoding="utf-8")
    assert 'id="tab-freshness"' in html
    assert 'data-view="freshness"' in html
    assert 'id="view-freshness"' in html
    assert '/career-static/js/evidence-freshness.js' in html


def test_the_freshness_module_exposes_the_expected_surfaces() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "career_static" / "js" / "evidence-freshness.js").read_text(encoding="utf-8")
    for marker in (
        "/api/career/evidence-freshness/status",
        "/api/career/evidence-freshness/evidence",
        "/api/career/evidence-freshness/report",
        "/api/career/evidence-freshness/monitor",
        "/api/career/evidence-freshness/acknowledge/",
        "applyFreshnessBatch",
        "startFreshnessTimer",
    ):
        assert marker in source


def test_the_timeline_buckets_cover_the_contracted_windows() -> None:
    from career.evidence_freshness_audit import TIMELINE_BUCKETS, TREND_WINDOWS

    assert TIMELINE_BUCKETS == (7, 30, 90)
    assert TREND_WINDOWS == (30, 90, 365)


def test_a_proof_never_expires_before_its_own_window() -> None:
    record = evidence_record(type="language", last_verified_at="2026-01-01T00:00:00+00:00")
    reference = NOW
    for offset in range(0, 800, 25):
        moment = reference + timedelta(days=offset)
        freshness = evaluate_evidence(record, now=moment)
        if freshness.status == STATUS_EXPIRED:
            assert moment >= datetime(2027, 7, 1, tzinfo=timezone.utc)
            break
    else:  # pragma: no cover - the proof must expire inside the window
        raise AssertionError("la preuve aurait dû expirer")
