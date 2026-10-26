"""Tests CVBOOST-84 / SPEC-047 — confirmation d'envoi manuelle + relance.

Règle absolue : aucune soumission automatique. Ces tests vérifient que le
module *enregistre* un envoi déclaré par la personne, calcule la relance à
+7 jours ouvrés et ne prétend jamais envoyer quoi que ce soit.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.send_confirmation import (
    FOLLOWUP_BUSINESS_DAYS,
    SendConfirmationError,
    SendEvidence,
    advance_follow_up_due,
    build_followup_draft,
    build_send_record,
    compute_follow_up_due,
    followup_due_status,
    parse_sent_at,
    prioritize_followups,
)
from career.service import CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError

FROZEN = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
WHEN = datetime.now(timezone.utc).replace(microsecond=0)


def manual_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Banque Synthétique",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/send-42",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-12-15",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": "Excel modelling.",
        "description_original": "Stage de quatre mois.",
    }
    payload.update(changes)
    return payload


def sent_application(tmp_path: Path) -> tuple[CareerService, dict]:
    service = CareerService(tmp_path)
    job = service.import_job(manual_job())
    application = service.create_application(job["id"])
    service.approve_for_manual_submission(application["id"], True)
    return service, job


# ---------------------------------------------------------------------------
# Logique pure : validation anti-fraude
# ---------------------------------------------------------------------------


def test_evidence_more_than_24h_in_future_is_a_business_error() -> None:
    evidence = SendEvidence(
        channel="website", sent_at=FROZEN + timedelta(hours=30)
    )
    with pytest.raises(SendConfirmationError) as error:
        build_send_record("job_1", evidence, now=FROZEN)
    assert "24 h" in str(error.value)


def test_evidence_in_the_past_or_within_24h_is_accepted() -> None:
    past = SendEvidence(channel="email", sent_at=FROZEN - timedelta(days=3))
    record = build_send_record("job_1", past, now=FROZEN)
    assert record.channel == "email"
    margin = SendEvidence(channel="portal", sent_at=FROZEN + timedelta(hours=23))
    assert build_send_record("job_2", margin, now=FROZEN).sent_at == margin.sent_at


def test_unknown_channel_is_rejected() -> None:
    evidence = SendEvidence(channel="bot", sent_at=FROZEN)  # type: ignore[arg-type]
    with pytest.raises(SendConfirmationError):
        build_send_record("job_1", evidence, now=FROZEN)


# ---------------------------------------------------------------------------
# Logique pure : +7 jours ouvrés
# ---------------------------------------------------------------------------


def test_follow_up_due_is_seven_business_days_later() -> None:
    # Wednesday 21/10/2026 → 7 ouvrés : Wed(1), Thu(2), Fri(3), Mon(4),
    # Tue(5), Wed(6), Thu(7).
    sent = datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)
    due = compute_follow_up_due(sent)
    assert due.date() == date(2026, 10, 29)


def test_friday_send_is_due_the_following_monday() -> None:
    sent = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)  # vendredi
    due = compute_follow_up_due(sent)
    assert due.date() == date(2026, 11, 2)  # lundi (vendredi → lundi)
    assert due.weekday() == 0


def test_weekend_send_counts_from_the_next_business_day() -> None:
    sent = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)  # samedi
    due = compute_follow_up_due(sent)
    assert due.date() == date(2026, 11, 3)  # lundi ×6 puis mardi = 7ᵉ ouvré


def test_holidays_are_excluded_when_data_is_available() -> None:
    # Envoi lundi 27/07/2026 : le mercredi 29/07 férié (fourni) décale
    # l'échéance d'un jour ouvré supplémentaire.
    sent = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    supplied = [date(2026, 7, 29)]
    due = compute_follow_up_due(sent, supplied)
    assert due.date() == date(2026, 8, 5)
    # « Hors données » : aucun jour férié retiré, échéance = mardi 04/08.
    plain = compute_follow_up_due(sent)
    assert plain.date() == date(2026, 8, 4)


def test_second_followup_is_seven_business_days_after_the_first() -> None:
    previous_due = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)  # lundi
    due = advance_follow_up_due(previous_due)
    assert due.date() == date(2026, 11, 3)
    assert FOLLOWUP_BUSINESS_DAYS == 7


# ---------------------------------------------------------------------------
# Brouillon de relance
# ---------------------------------------------------------------------------


def test_followup_draft_is_short_french_and_copied_by_hand() -> None:
    draft = build_followup_draft(
        title="Stagiaire M&A",
        company="Banque Synthétique",
        channel="email",
        sent_at=datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc),
        followup_count=0,
    )
    assert "Objet :" in draft
    assert "Banque Synthétique" in draft
    assert "23/10/2026" in draft
    assert "première" in draft
    assert "relance" in draft
    # Le brouillon n'est jamais envoyé par le programme : il précise que
    # l'envoi reste manuel.
    assert "vous-même" in draft
    second = build_followup_draft(
        title="x", company="y", channel="portal",
        sent_at=datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc),
        followup_count=1,
    )
    assert "2ᵉ" in second


# ---------------------------------------------------------------------------
# Service : persistance idempotente
# ---------------------------------------------------------------------------


def test_record_send_persists_and_moves_stage(tmp_path: Path) -> None:
    service, job = sent_application(tmp_path)
    record = service.record_send(
        job["id"],
        SendEvidence(channel="website", sent_at=WHEN),
    )
    assert record["job_id"] == job["id"]
    assert record["channel"] == "website"
    # Échéance = 7ᵉ jour ouvré après l'envoi, même horloge que l'instant d'envoi.
    expected_due = compute_follow_up_due(WHEN)
    assert record["follow_up_due"] == expected_due.isoformat()
    assert parse_sent_at(record["follow_up_due"]).weekday() < 5
    applications = service.list_applications()
    tracked = next(app for app in applications if app["job_id"] == job["id"])
    # tracking_stage : « envoyée » uniquement après la confirmation humaine.
    assert tracked["stage"] == "submitted"
    assert tracked["receipt_status"] == "unknown"


def test_duplicate_send_updates_without_duplicating_history(tmp_path: Path) -> None:
    service, job = sent_application(tmp_path)
    service.record_send(job["id"], SendEvidence(channel="email", sent_at=WHEN))
    again = service.record_send(
        job["id"],
        SendEvidence(channel="portal", sent_at=WHEN + timedelta(minutes=5), note="corrigé"),
    )
    assert again["channel"] == "portal"
    application = service.get_application(service.create_application(job["id"])["id"])
    send_events = [e for e in application["events"] if e["event_type"] == "send_recorded"]
    # Idempotence : un seul événement d'envoi, jamais d'historique dupliqué.
    assert len(send_events) == 1


def test_send_without_approved_submission_is_refused(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(manual_job())
    service.create_application(job["id"])
    with pytest.raises(UserFacingError):
        service.record_send(job["id"], SendEvidence(channel="website", sent_at=WHEN))


def test_send_followup_replans_due_date(tmp_path: Path) -> None:
    service, job = sent_application(tmp_path)
    service.record_send(job["id"], SendEvidence(channel="website", sent_at=WHEN))
    after = service.record_followup(job["id"], "relance envoyée")
    assert int(after["followup_count"]) == 1
    assert after["last_followup_at"] >= after["sent_at"]
    # Prochaine échéance : +7 jours ouvrés après la relance.
    assert parse_sent_at(after["follow_up_due"]) == compute_follow_up_due(
        parse_sent_at(after["last_followup_at"])
    )


# ---------------------------------------------------------------------------
# Tracker : envoyés sans réponse, priorisés
# ---------------------------------------------------------------------------


def test_prioritize_orders_overdue_first_then_by_due_date() -> None:
    records = [
        {"job_id": "a", "follow_up_due": "2026-10-19T12:00:00+00:00"},
        {"job_id": "b", "follow_up_due": "2026-10-18T12:00:00+00:00"},
        {"job_id": "c", "follow_up_due": "2026-10-28T12:00:00+00:00"},
        {"job_id": "d", "follow_up_due": "2026-10-17T12:00:00+00:00", "response_received": True},
    ]
    prioritized = prioritize_followups(records, now=FROZEN)
    ids = [str(item["job_id"]) for item in prioritized]
    # Échus d'abord (le plus en retard devant), puis à venir ; la candidature
    # avec réponse est sortie du tracker.
    assert ids == ["b", "a", "c"]
    assert prioritized[0]["due_status"] == "overdue"
    assert prioritized[-1]["due_status"] == "scheduled"
    assert followup_due_status(
        datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc), now=FROZEN
    ) == "due"


def test_apply_tracker_service_endpoint(tmp_path: Path) -> None:
    service, job = sent_application(tmp_path)
    service.record_send(job["id"], SendEvidence(channel="email", sent_at=WHEN - timedelta(days=30)))
    tracker = service.get_apply_tracker()
    assert tracker["automatic_followup"] is False
    assert tracker["count"] == 1
    item = tracker["items"][0]
    assert item["job_id"] == job["id"]
    assert item["due_status"] == "overdue"


# ---------------------------------------------------------------------------
# REST (schema_version et pattern Career inchangés)
# ---------------------------------------------------------------------------


def rest_client(tmp_path: Path, service: CareerService) -> TestClient:
    return TestClient(create_app(tmp_path, agent_override=object(), career_override=service))


def test_rest_send_confirmation_flow(tmp_path: Path) -> None:
    service, job = sent_application(tmp_path)
    client = rest_client(tmp_path, service)
    confirm = client.post(
        f"/api/career/send-confirmation/{job['id']}",
        json={"channel": "email", "sent_at": WHEN.isoformat(), "note": "dépôt portail"},
    )
    # Code 201 au premier enregistrement.
    assert confirm.status_code == 201, confirm.text
    body = confirm.json()
    assert body["channel"] == "email"
    draft = client.get(f"/api/career/send-confirmation/{job['id']}/draft")
    assert draft.status_code == 200
    assert draft.json()["automatic_send"] is False
    assert "Objet :" in draft.json()["draft"]
    tracker = client.get("/api/career/apply-tracker")
    assert tracker.status_code == 200
    payload = tracker.json()
    assert payload["automatic_followup"] is False
    assert payload["count"] == 1

    anti_fraud = client.post(
        f"/api/career/send-confirmation/{job['id']}",
        json={"channel": "email", "sent_at": (WHEN + timedelta(days=3)).isoformat()},
    )
    # Un envoi prédit à trois jours est refusé (erreur métier, pas un crash).
    assert anti_fraud.status_code == 400


def test_rest_rejects_unknown_channel(tmp_path: Path) -> None:
    service, job = sent_application(tmp_path)
    client = rest_client(tmp_path, service)
    bad = client.post(
        f"/api/career/send-confirmation/{job['id']}",
        json={"channel": "carrier_pigeon", "sent_at": WHEN.isoformat()},
    )
    assert bad.status_code == 422
