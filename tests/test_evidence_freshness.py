"""SPEC-012 — Fraîcheur des preuves : policies, surveillance, alertes, downgrade.

Toutes les données sont synthétiques : aucune preuve réelle n'est utilisée,
aucune requête réseau n'est émise et aucun envoi n'est déclenché.  Le module
est local : il lit et écrit un unique fichier JSON dans le dossier privé
Career.

Les tests couvrent quatre niveaux :

1. le contrat (politics, statuts, identifiants déterministes) ;
2. les actions automatiques (downgrade, archivage, révocation, réactivation) ;
3. la persistance locale (droits, atomicité, historique, snapshots) ;
4. l'API HTTP et le tableau de bord.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.evidence_freshness import (
    ACTION_ARCHIVE,
    ACTION_DOWNGRADE,
    ACTION_EXTENDED,
    ACTION_REACTIVATED,
    ACTION_REVOKED,
    ACTION_TO_REVERIFY,
    ACTION_VERIFIED,
    CADENCE_DAILY,
    CADENCE_MONTHLY,
    CADENCE_QUARTERLY,
    CADENCE_WEEKLY,
    COVERAGE_ARCHIVED,
    COVERAGE_COVERED,
    COVERAGE_WARNING,
    FRESHNESS_POLICIES,
    SourceCheck,
    blocks_export,
    build_alerts,
    build_evidence,
    make_alert_id,
    parse_timestamp,
    policy_for,
    refresh_evidence,
    resolve_cadence,
)
from career.evidence_freshness_audit import (
    build_audit_report,
    build_freshness_report,
    build_trends,
    render_report_markdown,
)
from career.evidence_freshness_store import FreshnessStore, FreshnessStoreError
from come_ai_web import create_app

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


# ── helpers ─────────────────────────────────────────────────────────────


def make_evidence(
    evidence_type: str = "certification",
    *,
    evidence_id: str = "ev_test",
    title: str = "Preuve synthétique",
    mandatory: bool = True,
    created_at: datetime = NOW,
    coverage_status: str = COVERAGE_COVERED,
    **kwargs,
):
    """One proof built from the documented policy of its type."""
    policy = policy_for(evidence_type)
    return build_evidence(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        created_at=created_at,
        policy=policy,
        title=title,
        mandatory=mandatory,
        coverage_status=coverage_status,
        **kwargs,
    )


@pytest.fixture()
def store(tmp_path: Path) -> FreshnessStore:
    return FreshnessStore(tmp_path / "career_data" / "evidence_freshness")


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path)
    return TestClient(app)


# ── 1. contrat ──────────────────────────────────────────────────────────


def test_policies_match_the_spec_contract() -> None:
    """Les huit policies documentées sont exactement celles de SPEC-012."""
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


def test_unknown_evidence_type_never_expires() -> None:
    """Un type inconnu n'expire pas : l'inconnu reste inconnu."""
    policy = policy_for("mystery")
    assert policy.max_age_days is None
    assert policy.warning_days is None
    assert policy.auto_expire is False

    evidence = make_evidence("mystery")
    assert evidence.expires_at is None
    assert evidence.warning_at is None
    assert evidence.status == "fresh"

    refreshed, actions = refresh_evidence(evidence, NOW + timedelta(days=5000), policy)
    assert refreshed.status == "fresh"
    assert actions == []


def test_policy_override_replaces_the_base_policy() -> None:
    """L'override global puis l'override local priment sur la policy de base."""
    overrides = {"certification": {"max_age_days": 90, "warning_days": 10, "auto_expire": False}}
    policy = policy_for("certification", overrides)
    assert policy.max_age_days == 90
    assert policy.warning_days == 10
    assert policy.auto_expire is False

    local = policy_for("certification", overrides, {"max_age_days": 30})
    assert local.max_age_days == 30
    assert local.warning_days == 10


def test_policy_validation_rejects_impossible_values() -> None:
    """Un délai d'alerte plus long que la validité est refusé."""
    from career.evidence_freshness import validate_policy_values

    with pytest.raises(ValueError):
        validate_policy_values(30, 60, True)
    with pytest.raises(ValueError):
        validate_policy_values(-1, 10, True)
    with pytest.raises(ValueError):
        validate_policy_values(30, -5, True)


def test_dates_are_computed_from_the_policy() -> None:
    """L'expiration et la fenêtre d'avertissement dérivent de la policy."""
    evidence = make_evidence("certification")
    assert evidence.expires_at == "2027-10-22T12:00:00+00:00"
    assert evidence.warning_at == "2027-09-22T12:00:00+00:00"

    education = make_evidence("education", evidence_id="ev_edu")
    assert education.expires_at is None
    assert education.warning_at is None


def test_status_follows_the_dates() -> None:
    """fresh → warning → expired, aux boundaries exactes."""
    evidence = make_evidence("certification")
    policy = policy_for("certification")

    before, _ = refresh_evidence(evidence, NOW, policy)
    assert before.status == "fresh"

    at_warning, _ = refresh_evidence(evidence, parse_timestamp(evidence.warning_at), policy)
    assert at_warning.status == "warning"

    at_expiry, _ = refresh_evidence(evidence, parse_timestamp(evidence.expires_at), policy)
    assert at_expiry.status == "expired"


def test_archived_status_wins_over_the_dates() -> None:
    """Une preuve archivée reste archivée, même si elle est expirée."""
    evidence = make_evidence("certification")
    from dataclasses import replace

    archived = replace(evidence, archived=True)
    policy = policy_for("certification")
    refreshed, _ = refresh_evidence(archived, NOW + timedelta(days=1000), policy)
    assert refreshed.status == "archived"


def test_pinned_dates_survive_a_policy_change() -> None:
    """Une date fixée à la main n'est pas écrasée par une nouvelle policy."""
    from dataclasses import replace

    evidence = make_evidence("certification")
    pinned = replace(evidence, expires_at="2030-01-01T00:00:00+00:00", dates_pinned=True)
    strict = policy_for("certification", {"certification": {"max_age_days": 30, "warning_days": 5}})
    refreshed, _ = refresh_evidence(pinned, NOW, strict)
    assert refreshed.expires_at == "2030-01-01T00:00:00+00:00"


# ── 2. actions automatiques ────────────────────────────────────────────


def test_expired_mandatory_proof_is_downgraded() -> None:
    """Une preuve obligatoire expirée passe de covered à warning."""
    evidence = make_evidence("certification", mandatory=True, coverage_status=COVERAGE_COVERED)
    policy = policy_for("certification")
    refreshed, actions = refresh_evidence(evidence, NOW + timedelta(days=400), policy)
    assert refreshed.status == "expired"
    assert refreshed.coverage_status == COVERAGE_WARNING
    assert ACTION_DOWNGRADE in actions
    assert blocks_export(refreshed) is True


def test_expired_optional_proof_is_archived() -> None:
    """Une preuve optionnelle expirée est archivée, pas dégradée."""
    evidence = make_evidence("certification", mandatory=False, coverage_status=COVERAGE_COVERED)
    policy = policy_for("certification")
    refreshed, actions = refresh_evidence(evidence, NOW + timedelta(days=400), policy)
    assert refreshed.status == "archived"
    assert refreshed.archived is True
    assert refreshed.coverage_status == COVERAGE_ARCHIVED
    assert ACTION_ARCHIVE in actions


def test_policy_without_auto_expire_records_but_does_not_degrade() -> None:
    """Une policy sans auto_expire signale l'expiration sans rien changer."""
    evidence = make_evidence("skill_technical", coverage_status=COVERAGE_COVERED)
    policy = policy_for("skill_technical")
    refreshed, actions = refresh_evidence(evidence, NOW + timedelta(days=900), policy)
    assert refreshed.status == "expired"
    assert refreshed.coverage_status == COVERAGE_COVERED
    assert refreshed.archived is False
    assert actions == ["expired_no_auto_action"]


def test_removed_source_expires_the_proof_immediately() -> None:
    """Une certification révoquée expire immédiatement."""
    evidence = make_evidence("certification")
    revoked_at = NOW + timedelta(days=10)
    check = SourceCheck(
        check_id="chk_test",
        checked_at=revoked_at.isoformat(),
        source_url=None,
        method="manual",
        result="removed",
        details={},
    )
    from career.evidence_freshness import apply_source_check

    updated, actions = apply_source_check(evidence, check, revoked_at, policy_for("certification"))
    assert updated.status == "expired"
    assert updated.expires_at == revoked_at.isoformat(timespec="seconds")
    assert ACTION_REVOKED in actions


def test_updated_source_flags_the_proof_for_reverification() -> None:
    """Une source modifiée marque la preuve « à revérifier »."""
    from career.evidence_freshness import apply_source_check

    evidence = make_evidence("certification")
    check = SourceCheck(
        check_id="chk_test",
        checked_at=NOW.isoformat(),
        source_url=None,
        method="manual",
        result="updated",
        details={},
    )
    updated, actions = apply_source_check(evidence, check, NOW, policy_for("certification"))
    assert updated.needs_reverification is True
    assert ACTION_TO_REVERIFY in actions
    assert updated.status == "fresh"


def test_unchanged_source_restarts_the_timer() -> None:
    """Une vérification sans changement relance le compteur."""
    from career.evidence_freshness import apply_source_check

    evidence = make_evidence("certification")
    check = SourceCheck(
        check_id="chk_test",
        checked_at=NOW.isoformat(),
        source_url=None,
        method="manual",
        result="unchanged",
        details={},
    )
    updated, actions = apply_source_check(evidence, check, NOW, policy_for("certification"))
    assert updated.last_verified_at == NOW.isoformat(timespec="seconds")
    assert updated.expires_at == "2027-10-22T12:00:00+00:00"
    assert ACTION_VERIFIED in actions
    assert len(updated.source_checks) == 1


def test_reactivation_resets_the_timer() -> None:
    """Réactiver une preuve relance son compteur depuis maintenant."""
    from career.evidence_freshness import reactivate_evidence

    evidence = make_evidence("certification")
    expired_at = NOW + timedelta(days=400)
    refreshed, actions = reactivate_evidence(evidence, expired_at, policy_for("certification"))
    assert refreshed.status == "fresh"
    assert refreshed.last_verified_at == expired_at.isoformat(timespec="seconds")
    assert refreshed.expires_at == "2028-11-25T12:00:00+00:00"
    assert ACTION_REACTIVATED in actions


def test_extend_expiry_moves_the_date() -> None:
    """Prolonger une preuve repousse son expiration."""
    from career.evidence_freshness import extend_expiry

    evidence = make_evidence("certification")
    extended, actions = extend_expiry(evidence, 30, NOW, policy_for("certification"))
    assert extended.expires_at == "2027-11-21T12:00:00+00:00"
    assert ACTION_EXTENDED in actions
    with pytest.raises(ValueError):
        extend_expiry(evidence, 0, NOW, policy_for("certification"))


# ── 3. alertes ──────────────────────────────────────────────────────────


def test_alert_levels_follow_the_urgency() -> None:
    """info dans la zone d'avertissement, warning sous 7 jours, critical si expirée."""
    evidence = make_evidence("certification")

    far = refresh_evidence(evidence, parse_timestamp(evidence.warning_at), policy_for("certification"))[0]
    far_alerts = build_alerts(far, parse_timestamp(evidence.warning_at))
    assert [alert.level for alert in far_alerts] == ["info"]

    soon = NOW + timedelta(days=358)
    close = refresh_evidence(evidence, soon, policy_for("certification"))[0]
    close_alerts = build_alerts(close, soon)
    assert [alert.level for alert in close_alerts] == ["warning"]

    late = NOW + timedelta(days=400)
    expired = refresh_evidence(evidence, late, policy_for("certification"))[0]
    expired_alerts = build_alerts(expired, late)
    assert [alert.level for alert in expired_alerts] == ["critical"]


def test_alert_ids_are_deterministic() -> None:
    """Le même contenu produit toujours le même identifiant d'alerte."""
    first = make_alert_id("ev_1", "expired", "2027-01-01T00:00:00+00:00")
    second = make_alert_id("ev_1", "expired", "2027-01-01T00:00:00+00:00")
    assert first == second
    assert first.startswith("alert_")
    assert first != make_alert_id("ev_1", "expired", "2028-01-01T00:00:00+00:00")
    assert first != make_alert_id("ev_2", "expired", "2027-01-01T00:00:00+00:00")


# ── 4. surveillance ─────────────────────────────────────────────────────


def test_cadence_follows_the_surveillance_table() -> None:
    """Quotidien sous 30 jours, hebdo pour certification/langue sous 90 jours."""
    certification = make_evidence("certification")
    assert resolve_cadence(certification, NOW) == CADENCE_MONTHLY

    # La certification expire dans 365 jours : surveillance mensuelle.
    assert resolve_cadence(certification, NOW + timedelta(days=200)) == CADENCE_MONTHLY
    # Il reste 90 jours : surveillance hebdomadaire.
    assert resolve_cadence(certification, NOW + timedelta(days=275)) == CADENCE_WEEKLY
    # Il reste 30 jours : surveillance quotidienne.
    assert resolve_cadence(certification, NOW + timedelta(days=335)) == CADENCE_DAILY

    technical = make_evidence("skill_technical", evidence_id="ev_skill")
    assert resolve_cadence(technical, NOW) == CADENCE_MONTHLY

    experience = make_evidence("experience", evidence_id="ev_exp")
    assert resolve_cadence(experience, NOW) == CADENCE_QUARTERLY


def test_plan_is_ordered_by_urgency(store: FreshnessStore) -> None:
    """Le plan de surveillance commence par la vérification la plus urgente."""
    store.register_evidence(
        evidence_type="experience",
        evidence_id="ev_exp",
        title="Expérience ancienne",
        created_at=NOW,
        now=NOW,
    )
    store.register_evidence(
        evidence_type="certification",
        evidence_id="ev_cert",
        title="Certification proche",
        created_at=NOW,
        expires_at=(NOW + timedelta(days=10)).isoformat(),
        now=NOW,
    )
    planned = store.plan(now=NOW)
    assert [check.evidence_id for check in planned][0] == "ev_cert"
    assert planned[0].cadence == CADENCE_DAILY
    assert planned[0].priority == "high"


# ── 5. persistance ──────────────────────────────────────────────────────


def test_store_round_trip_and_private_permissions(store: FreshnessStore) -> None:
    """La preuve est relue après rechargement, dans un fichier privé."""
    evidence = store.register_evidence(
        evidence_type="certification",
        evidence_id="ev_1",
        title="AWS SAA",
        mandatory=True,
        created_at=NOW,
        now=NOW,
    )
    assert store.path.exists()
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.base_dir.stat().st_mode) == 0o700

    reloaded = store.get_evidence("ev_1", now=NOW)
    assert reloaded is not None
    assert reloaded.title == "AWS SAA"
    assert reloaded.evidence_id == evidence.evidence_id
    assert reloaded.expires_at == "2027-10-22T12:00:00+00:00"

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert "ev_1" in payload["evidence"]


def test_store_refuses_a_newer_schema(store: FreshnessStore) -> None:
    """Un fichier écrit par une version plus récente n'est pas réinterprété."""
    store.base_dir.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"schema_version": 99, "evidence": {}, "policies": {}, "alerts": {}, "history": []}),
        encoding="utf-8",
    )
    with pytest.raises(FreshnessStoreError):
        store.read_state()


def test_store_history_is_bounded(store: FreshnessStore) -> None:
    """L'historique reste borné, même après beaucoup d'événements."""
    for index in range(60):
        store.register_evidence(
            evidence_type="tool",
            evidence_id=f"ev_{index}",
            created_at=NOW,
            now=NOW,
        )
    events = store.history(limit=10_000)
    assert len(events) <= 500
    assert any(event["event"] == "register" for event in events)


def test_policy_change_recomputes_the_dates_of_unpinned_proofs(store: FreshnessStore) -> None:
    """Un changement de policy recalcule les dates non fixées, jamais les dates fixées."""
    store.register_evidence(
        evidence_type="certification",
        evidence_id="ev_free",
        created_at=NOW,
        now=NOW,
    )
    store.register_evidence(
        evidence_type="certification",
        evidence_id="ev_pinned",
        created_at=NOW,
        expires_at="2030-01-01T00:00:00+00:00",
        now=NOW,
    )
    store.set_policy("certification", max_age_days=90, warning_days=10, now=NOW)

    free = store.get_evidence("ev_free", now=NOW)
    pinned = store.get_evidence("ev_pinned", now=NOW)
    assert free is not None and pinned is not None
    assert free.expires_at == "2027-01-20T12:00:00+00:00"
    assert pinned.expires_at == "2030-01-01T00:00:00+00:00"


def test_delete_removes_the_attached_alerts(store: FreshnessStore) -> None:
    """Supprimer une preuve supprime aussi ses alertes."""
    store.register_evidence(
        evidence_type="certification",
        evidence_id="ev_1",
        created_at=NOW,
        expires_at=(NOW - timedelta(days=1)).isoformat(),
        now=NOW,
    )
    store.refresh(now=NOW)
    assert store.list_alerts(now=NOW)

    assert store.delete_evidence("ev_1", now=NOW) is True
    assert store.list_alerts(now=NOW) == []
    assert store.get_evidence("ev_1", now=NOW) is None


def test_alerts_are_not_duplicated_by_a_refresh(store: FreshnessStore) -> None:
    """Un refresh répété ne duplique pas les alertes."""
    store.register_evidence(
        evidence_type="certification",
        evidence_id="ev_1",
        created_at=NOW,
        expires_at=(NOW - timedelta(days=1)).isoformat(),
        now=NOW,
    )
    store.refresh(now=NOW)
    store.refresh(now=NOW)
    store.refresh(now=NOW)
    assert len(store.list_alerts(now=NOW)) == 1


def test_acknowledged_alert_stays_acknowledged(store: FreshnessStore) -> None:
    """Une alerte acquittée ne réapparaît pas au refresh suivant."""
    store.register_evidence(
        evidence_type="certification",
        evidence_id="ev_1",
        created_at=NOW,
        expires_at=(NOW - timedelta(days=1)).isoformat(),
        now=NOW,
    )
    store.refresh(now=NOW)
    alert = store.list_alerts(now=NOW)[0]
    acknowledged = store.acknowledge_alert(alert.alert_id, now=NOW)
    assert acknowledged.acknowledged is True

    store.refresh(now=NOW)
    assert store.list_alerts(active_only=True, now=NOW) == []
    assert len(store.list_alerts(active_only=False, now=NOW)) == 1


def test_store_snapshots_feed_the_trends(store: FreshnessStore) -> None:
    """Un snapshot quotidien est écrit et alimente les tendances."""
    store.register_evidence(evidence_type="tool", evidence_id="ev_1", created_at=NOW, now=NOW)
    store.refresh(now=NOW)
    store.refresh(now=NOW + timedelta(days=1))
    history = store.history(limit=500)
    snapshots = [entry for entry in history if entry["event"] == "snapshot"]
    assert len(snapshots) == 2
    assert snapshots[0]["counts"]["fresh"] == 1


# ── 6. rapports ─────────────────────────────────────────────────────────


def test_report_counts_and_ratios() -> None:
    """Le rapport compte les statuts et calcule les parts."""
    fresh = make_evidence("certification", evidence_id="ev_fresh")
    expired = make_evidence("skill_technical", evidence_id="ev_expired", created_at=NOW - timedelta(days=900))
    evidences = [
        fresh,
        expired,
    ]
    report = build_freshness_report(evidences, [], now=NOW)
    assert report["totals"]["total"] == 2
    assert report["totals"]["fresh"] == 1
    assert report["totals"]["expired"] == 1
    assert report["ratios"]["fresh"] == 0.5
    assert set(report["by_type"]) == {"certification", "skill_technical"}


def test_report_timeline_buckets() -> None:
    """La timeline range les expiritions dans les horizons 7/30/90 jours."""
    soon = make_evidence(
        "certification",
        evidence_id="ev_soon",
        created_at=NOW,
        expires_at=(NOW + timedelta(days=3)).isoformat(),
    )
    report = build_freshness_report([soon], [], now=NOW)
    assert [entry["evidence_id"] for entry in report["timeline"]["7"]] == ["ev_soon"]
    assert [entry["evidence_id"] for entry in report["timeline"]["90"]] == ["ev_soon"]


def test_trends_are_rebuilt_from_the_snapshots() -> None:
    """Les tendances sortent des snapshots journaliers."""
    history = [
        {"event": "snapshot", "date": "2026-10-20", "total": 4, "counts": {"fresh": 2, "warning": 1, "expired": 1, "archived": 0}},
        {"event": "snapshot", "date": "2026-10-21", "total": 4, "counts": {"fresh": 3, "warning": 1, "expired": 0, "archived": 0}},
        {"event": "snapshot", "date": "2026-10-22", "total": 4, "counts": {"fresh": 4, "warning": 0, "expired": 0, "archived": 0}},
    ]
    trends = build_trends(history, now=NOW)
    assert trends["30"]["points"] == 3
    assert trends["30"]["latest"]["fresh_ratio"] == 1.0
    assert trends["30"]["fresh_drift"] == 0.5
    assert trends["365"]["points"] == 3


def test_audit_report_contains_the_verification_history() -> None:
    """Le rapport d'audit expose l'historique de vérification."""
    evidence = make_evidence("certification")
    report = build_audit_report([evidence], [], [], now=NOW)
    assert report["verification_history"][0]["evidence_id"] == "ev_test"
    assert "markdown" not in report
    markdown = render_report_markdown(report)
    assert "# Fraîcheur des preuves" in markdown
    assert "| **total** | **1** | 100% |" in markdown


# ── 7. API HTTP ─────────────────────────────────────────────────────────


def test_status_endpoint_returns_the_dashboard(client: TestClient) -> None:
    """Le statut global expose compteurs, preuves, alertes et planning."""
    response = client.get("/api/career/evidence-freshness/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["totals"]["total"] == 0
    assert payload["evidence"] == []
    assert payload["alerts"] == []
    assert "schedule" in payload
    assert "certification" in payload["policies"]


def test_register_read_and_delete_a_proof(client: TestClient) -> None:
    """Le cycle complet d'une preuve passe par l'API locale."""
    created = client.post(
        "/api/career/evidence-freshness/evidence",
        json={
            "evidence_type": "certification",
            "title": "Certification synthétique",
            "mandatory": True,
            "notes": "Donnée de test",
        },
    )
    assert created.status_code == 201
    evidence = created.json()
    evidence_id = evidence["evidence_id"]
    assert evidence["status"] == "fresh"
    assert evidence["expires_at"]

    listing = client.get("/api/career/evidence-freshness/evidence")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1

    detail = client.get(f"/api/career/evidence-freshness/evidence/{evidence_id}")
    assert detail.status_code == 200
    assert detail.json()["evidence"]["title"] == "Certification synthétique"

    deleted = client.delete(f"/api/career/evidence-freshness/evidence/{evidence_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert client.get("/api/career/evidence-freshness/evidence").json()["count"] == 0


def test_patch_endpoint_overrides_the_dates(client: TestClient) -> None:
    """Le PATCH épingle les dates et prolonge une preuve."""
    created = client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "tool", "title": "Outil synthétique"},
    ).json()
    evidence_id = created["evidence_id"]

    patched = client.patch(
        f"/api/career/evidence-freshness/evidence/{evidence_id}",
        json={"expires_at": "2031-05-04T00:00:00+00:00", "title": "Outil vérifié"},
    )
    assert patched.status_code == 200
    assert patched.json()["expires_at"] == "2031-05-04T00:00:00+00:00"
    assert patched.json()["dates_pinned"] is True

    extended = client.patch(
        f"/api/career/evidence-freshness/evidence/{evidence_id}",
        json={"extend_days": 30},
    )
    assert extended.status_code == 200
    assert extended.json()["expires_at"] == "2031-06-03T00:00:00+00:00"


def test_policy_endpoint_updates_the_policy(client: TestClient) -> None:
    """La policy d'un type se modifie et se réinitialise."""
    updated = client.post(
        "/api/career/evidence-freshness/policy",
        json={"evidence_type": "tool", "max_age_days": 120, "warning_days": 15, "auto_expire": True},
    )
    assert updated.status_code == 200
    assert updated.json()["max_age_days"] == 120

    policies = client.get("/api/career/evidence-freshness/policy").json()["policies"]
    assert policies["tool"]["overridden"] is True

    reset = client.post(
        "/api/career/evidence-freshness/policy",
        json={"evidence_type": "tool", "reset": True},
    )
    assert reset.status_code == 200
    assert reset.json()["max_age_days"] == 730


def test_check_endpoint_records_a_manual_verification(client: TestClient) -> None:
    """La vérification manuelle est journalisée dans la preuve."""
    created = client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "certification", "title": "Certification synthétique"},
    ).json()
    evidence_id = created["evidence_id"]

    checked = client.post(
        f"/api/career/evidence-freshness/check/{evidence_id}",
        json={"method": "manual", "result": "unchanged"},
    )
    assert checked.status_code == 200
    assert len(checked.json()["evidence"]["source_checks"]) == 1
    assert checked.json()["summary"]["checks_count"] == 1
    assert checked.json()["summary"]["last_checked_at"] is not None


def test_check_endpoint_rejects_an_unknown_method(client: TestClient) -> None:
    """Une méthode de vérification inconnue est refusée."""
    created = client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "certification", "title": "Certification synthétique"},
    ).json()
    response = client.post(
        f"/api/career/evidence-freshness/check/{created['evidence_id']}",
        json={"method": "telepathy", "result": "unchanged"},
    )
    assert response.status_code == 400
    assert "méthode" in response.json()["detail"].lower()


def test_expired_proof_raises_a_critical_alert_that_can_be_acknowledged(client: TestClient) -> None:
    """Une preuve expirée déclenche une alerte critique, acquittable."""
    created = client.post(
        "/api/career/evidence-freshness/evidence",
        json={
            "evidence_type": "certification",
            "title": "Certification expirée",
            "mandatory": True,
            "expires_at": "2020-01-01T00:00:00+00:00",
        },
    ).json()
    evidence_id = created["evidence_id"]

    status = client.get("/api/career/evidence-freshness/status").json()
    assert status["report"]["totals"]["expired"] == 1
    assert status["report"]["blocking_export"] == [evidence_id]
    critical = [alert for alert in status["alerts"] if alert["level"] == "critical"]
    assert critical

    acknowledged = client.post(
        f"/api/career/evidence-freshness/acknowledge/{critical[0]['alert_id']}"
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged"] is True

    alerts = client.get("/api/career/evidence-freshness/alerts").json()
    assert alerts["count"] == 0


def test_report_endpoint_returns_the_audit(client: TestClient) -> None:
    """Le rapport complet expose les tendances et l'historique."""
    response = client.get("/api/career/evidence-freshness/report")
    assert response.status_code == 200
    payload = response.json()
    assert "trends" in payload
    assert "30" in payload["trends"]
    assert "verification_history" in payload
    assert payload["markdown"].startswith("# Fraîcheur des preuves")


def test_unknown_proof_returns_404(client: TestClient) -> None:
    """Une preuve inconnue renvoie une erreur explicite."""
    response = client.get("/api/career/evidence-freshness/evidence/ev_missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "Preuve introuvable."


def test_unknown_alert_returns_404(client: TestClient) -> None:
    """Une alerte inconnue renvoie une erreur explicite."""
    response = client.post("/api/career/evidence-freshness/acknowledge/alert_missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "Alerte introuvable."


def test_invalid_date_returns_400(client: TestClient) -> None:
    """Une date illisible est refusée avec un message lisible."""
    response = client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "certification", "expires_at": "pas-une-date"},
    )
    assert response.status_code == 400
    assert "date" in response.json()["detail"].lower()


# ── 8. interface et pureté ──────────────────────────────────────────────


def test_dashboard_script_exists_and_is_wired() -> None:
    """Le tableau de bord est bien branché dans la page Career."""
    script = ROOT / "career_static" / "js" / "evidence-freshness.js"
    html = (ROOT / "career_static" / "index.html").read_text(encoding="utf-8")
    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "/api/career/evidence-freshness" in source
    assert "tab-evidence-freshness" in html
    assert "/career-static/js/evidence-freshness.js" in html
    # Le tableau de bord se rafraîchit seul quand la vue est visible.
    assert "setInterval" in source
    # Aucune donnée utilisateur n'est injectée en HTML brut.
    assert "innerHTML" not in source
    assert "eval(" not in source


def test_core_module_has_no_implicit_clock() -> None:
    """Le cœur du module ne lit jamais l'horloge système ni le réseau."""
    source = (ROOT / "career" / "evidence_freshness.py").read_text(encoding="utf-8")
    assert "datetime.now" not in source
    assert "time.time" not in source
    assert "urllib" not in source
    assert "requests" not in source


def test_store_file_is_not_world_readable(store: FreshnessStore) -> None:
    """Le fichier local de fraîcheur n'est jamais lisible par d'autres."""
    store.register_evidence(evidence_type="tool", created_at=NOW, now=NOW)
    mode = store.path.stat().st_mode
    assert not mode & stat.S_IROTH
    assert not mode & stat.S_IRGRP
    assert os.path.basename(store.path.name) == "evidence_freshness.json"


# ── 9. cas limites ──────────────────────────────────────────────────────


def test_unknown_evidence_type_is_refused_by_the_api(client: TestClient) -> None:
    """Un type de preuve hors contrat est refusé avec la liste des types."""
    response = client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "mystery", "title": "Preuve inconnue"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Type de preuve inconnu" in detail
    assert "certification" in detail


def test_revocation_expires_the_proof_and_raises_a_critical_alert(client: TestClient) -> None:
    """Une source disparue expire la preuve et lève une alerte critique."""
    created = client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "certification", "title": "Certification révoquée", "mandatory": True},
    ).json()
    evidence_id = created["evidence_id"]

    checked = client.post(
        f"/api/career/evidence-freshness/check/{evidence_id}",
        json={"method": "manual", "result": "removed"},
    )
    assert checked.status_code == 200
    assert checked.json()["summary"]["status"] == "expired"

    status = client.get("/api/career/evidence-freshness/status").json()
    critical = [alert for alert in status["alerts"] if alert["level"] == "critical"]
    assert critical
    assert status["report"]["blocking_export"] == [evidence_id]


def test_local_policy_override_changes_the_expiry(client: TestClient) -> None:
    """Une policy posée sur une seule preuve change son expiration."""
    created = client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "tool", "title": "Outil synthétique"},
    ).json()
    evidence_id = created["evidence_id"]
    reference = datetime.now(timezone.utc)
    first_expiry = parse_timestamp(created["expires_at"])
    assert first_expiry is not None
    assert 729 <= (first_expiry - reference).days <= 730

    patched = client.patch(
        f"/api/career/evidence-freshness/evidence/{evidence_id}",
        json={"policy": {"max_age_days": 30, "warning_days": 5}},
    )
    assert patched.status_code == 200
    assert patched.json()["policy_override"]["max_age_days"] == 30
    second_expiry = parse_timestamp(patched.json()["expires_at"])
    assert second_expiry is not None
    assert 29 <= (second_expiry - reference).days <= 30


def test_evidence_list_filters_by_status_and_type(client: TestClient) -> None:
    """La liste se filtre par statut et par type."""
    client.post(
        "/api/career/evidence-freshness/evidence",
        json={"evidence_type": "tool", "title": "Outil synthétique"},
    )
    client.post(
        "/api/career/evidence-freshness/evidence",
        json={
            "evidence_type": "certification",
            "title": "Certification expirée",
            "mandatory": True,
            "expires_at": "2020-01-01T00:00:00+00:00",
        },
    )
    expired = client.get("/api/career/evidence-freshness/evidence?status=expired").json()
    assert expired["count"] == 1
    assert expired["evidence"][0]["evidence_type"] == "certification"

    tools = client.get("/api/career/evidence-freshness/evidence?evidence_type=tool").json()
    assert tools["count"] == 1
    assert tools["evidence"][0]["title"] == "Outil synthétique"


def test_store_writes_never_leave_a_partial_file(store: FreshnessStore) -> None:
    """Chaque écriture laisse un fichier JSON valide et aucun fichier temporaire."""
    for index in range(5):
        store.register_evidence(
            evidence_type="project",
            evidence_id=f"ev_{index}",
            created_at=NOW,
            now=NOW,
        )
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert len(payload["evidence"]) == 5
    assert list(store.base_dir.glob("*.tmp")) == []


def test_serialization_round_trip_keeps_the_contract_fields() -> None:
    """Une preuve sérialisée puis relue garde tous les champs du contrat."""
    from career.evidence_freshness import evidence_from_dict

    evidence = make_evidence("certification")
    payload = evidence.to_dict()
    for key in (
        "evidence_id",
        "evidence_type",
        "created_at",
        "last_verified_at",
        "expires_at",
        "warning_at",
        "status",
        "source_checks",
        "auto_actions",
    ):
        assert key in payload

    reloaded = evidence_from_dict(payload)
    assert reloaded.evidence_id == evidence.evidence_id
    assert reloaded.expires_at == evidence.expires_at
    assert reloaded.status == evidence.status
    assert reloaded.auto_actions == evidence.auto_actions


def test_parse_timestamp_accepts_zulu_and_rejects_garbage() -> None:
    """Les dates ISO sont lues, les autres chaînes sont refusées."""
    parsed = parse_timestamp("2026-10-22T12:00:00Z")
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-22T12:00:00+00:00"
    assert parse_timestamp("") is None
    with pytest.raises(ValueError):
        parse_timestamp("hier")
