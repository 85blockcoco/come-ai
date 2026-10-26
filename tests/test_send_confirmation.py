"""SPEC-047 — confirmation d'envoi humaine + relance optimale.

Règle centrale testée partout : le module enregistre un envoi que la personne
déclare avoir effectué elle-même ; il ne soumet jamais rien. La relance est un
brouillon local à copier, daté de +7 jours ouvrés (week-ends exclus, aucun
jour férié inventé). Toutes les données sont synthétiques ; aucune base
réelle n'est lue, aucun e-mail n'est envoyé.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from career.send_confirmation import (
    FOLLOWUP_RECORDED_EVENT_TYPE,
    SEND_CONFIRMATION_EVENT_TYPE,
    SendConfirmationError,
    SendEvidence,
    add_business_days,
    build_followup_draft,
    compute_follow_up_due,
    latest_followup_on,
    latest_send_evidence,
    send_record_from_payload,
    validate_evidence,
)
from career.service import CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError

UTC = timezone.utc

SENT_FRIDAY = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
SENT_THURSDAY = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
SENT_BEFORE_BASTILLE = datetime(2026, 7, 13, 9, 0, tzinfo=UTC)
FOLLOWUP_DONE_MONDAY = date(2026, 1, 5)


def manual_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Banque Synthétique",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "SYNTH-42",
        "official_url": "https://careers.example.test/jobs/synthetic-42",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-12-15",
        "source_status": "open",
        "requirements": "Excel modelling.\nEnglish fluency.",
        "description_original": "Offre de test synthétique.",
    }
    payload.update(changes)
    return payload


def approved_application(tmp_path, **job_changes: object) -> tuple[CareerService, dict, dict]:
    """Tracking synthétique prêt pour un envoi déclaré (approbation enregistrée)."""
    service = CareerService(tmp_path)
    job = service.import_job(manual_job(**job_changes))
    application = service.create_application(job["id"])
    service.approve_for_manual_submission(application["id"], True)
    return service, job, application


def declared_send(tmp_path, sent_at: datetime = SENT_FRIDAY, channel: str = "website") -> tuple[CareerService, dict, dict]:
    service, job, application = approved_application(tmp_path)
    service.record_send(job["id"], SendEvidence(channel=channel, sent_at=sent_at))
    return service, job, application


# ---------------------------------------------------------------------------
# Anti-fraude et validation de la preuve déclarée
# ---------------------------------------------------------------------------

def test_sent_at_more_than_24h_in_the_future_is_rejected() -> None:
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    validate_evidence(SendEvidence(channel="website", sent_at=now + timedelta(hours=24)), now=now)
    with pytest.raises(SendConfirmationError):
        validate_evidence(SendEvidence(channel="website", sent_at=now + timedelta(hours=24, seconds=1)), now=now)
    with pytest.raises(SendConfirmationError):
        validate_evidence(SendEvidence(channel="website", sent_at=now + timedelta(hours=48)), now=now)


def test_naive_sent_at_is_read_as_utc_and_past_sends_are_allowed() -> None:
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    naive = datetime(2026, 10, 26, 11, 0)
    validate_evidence(SendEvidence(channel="email", sent_at=naive), now=now)
    validate_evidence(SendEvidence(channel="portal", sent_at=now - timedelta(days=30)), now=now)


def test_unknown_channel_is_rejected() -> None:
    with pytest.raises(SendConfirmationError):
        validate_evidence(
            SendEvidence(channel="carrier_pigeon", sent_at=datetime(2026, 10, 26, 10, 0, tzinfo=UTC)),
            now=datetime(2026, 10, 26, 12, 0, tzinfo=UTC),
        )


def test_service_refuses_future_sends_as_user_facing_error(tmp_path) -> None:
    service, job, _ = approved_application(tmp_path)
    now = datetime.now(timezone.utc)
    evidence = SendEvidence(channel="website", sent_at=now + timedelta(hours=48))
    with pytest.raises(UserFacingError) as error:
        service.record_send(job["id"], evidence, now=now)
    assert "24 h" in str(error.value)


# ---------------------------------------------------------------------------
# +7 jours ouvrés : week-ends exclus, aucun jour férié inventé
# ---------------------------------------------------------------------------

def test_follow_up_due_from_friday_skips_the_weekend() -> None:
    # Vendredi 2 janvier + 7 jours ouvrés → mardi 13 janvier : le week-end est
    # entièrement sauté, aucun jour ouvré n'est inventé.
    due = compute_follow_up_due(sent_at=SENT_FRIDAY)
    assert due.date() == date(2026, 1, 13)
    assert due.date().weekday() == 1  # mardi


def test_follow_up_due_crossing_weekends_stays_on_a_business_day() -> None:
    # Jeudi 1er janvier + 7 jours ouvrés → lundi 12 janvier.
    due = compute_follow_up_due(sent_at=SENT_THURSDAY)
    assert due.date() == date(2026, 1, 12)
    assert due.date().weekday() == 0


def test_holiday_is_counted_when_no_holiday_dataset_exists() -> None:
    # Lundi 13 juillet + 7 jours ouvrés : le 14 juillet (mardi) reste compté —
    # le module n'invente aucun calendrier de jours fériés (inconnu nommé).
    due = compute_follow_up_due(sent_at=SENT_BEFORE_BASTILLE)
    assert due.date() == date(2026, 7, 22)


def test_add_business_days_never_lands_on_a_weekend() -> None:
    for start in (date(2026, 1, 3), date(2026, 1, 4)):  # samedi, dimanche
        due = add_business_days(start, 7)
        assert due.weekday() < 5


def test_followup_already_done_shifts_next_due_by_seven_business_days() -> None:
    # Relance faite le lundi 5 janvier → prochaine échéance mercredi 14 janvier.
    due = compute_follow_up_due(sent_at=SENT_FRIDAY, last_followup_on=FOLLOWUP_DONE_MONDAY)
    assert due.date() == date(2026, 1, 14)


def test_service_records_followup_and_shifts_the_due_date(tmp_path) -> None:
    service, job, _ = declared_send(tmp_path)
    first = service.record_followup_done(job["id"], done_on=FOLLOWUP_DONE_MONDAY)
    assert first["followup_done_on"] == "2026-01-05"
    assert first["record"]["follow_up_due_date"] == "2026-01-14"
    # Idempotent : la même relance déclarée deux fois ne duplique pas l'historique.
    again = service.record_followup_done(job["id"], done_on=FOLLOWUP_DONE_MONDAY)
    events = service.get_application(again["application_id"])["events"]
    assert sum(1 for event in events if event["event_type"] == FOLLOWUP_RECORDED_EVENT_TYPE) == 1


def test_followup_requires_a_declared_send(tmp_path) -> None:
    service, job, _ = approved_application(tmp_path)
    with pytest.raises(UserFacingError):
        service.record_followup_done(job["id"], done_on=FOLLOWUP_DONE_MONDAY)


# ---------------------------------------------------------------------------
# record_send : persistence dans le store existant, idempotence
# ---------------------------------------------------------------------------

def test_record_send_updates_tracking_stage_and_journal(tmp_path) -> None:
    service, job, application = approved_application(tmp_path)
    response = service.record_send(job["id"], SendEvidence(channel="email", sent_at=SENT_FRIDAY, note="Dépôt sur le site"))
    record = response["record"]
    assert record["job_id"] == job["id"]
    assert record["channel"] == "email"
    assert record["sent_at"] == SENT_FRIDAY.isoformat()
    assert record["follow_up_due_date"] == "2026-01-13"
    assert record["note"] == "Dépôt sur le site"
    assert response["created"] is True
    # Le stage ne passe à « envoyée » qu'après la déclaration humaine.
    tracked = service.get_application(application["id"])
    assert tracked["stage"] == "submitted"
    assert tracked["receipt_status"] == "unknown"
    types = [event["event_type"] for event in tracked["events"]]
    assert SEND_CONFIRMATION_EVENT_TYPE in types
    assert "stage_updated" in types


def test_record_send_is_idempotent_for_identical_evidence(tmp_path) -> None:
    service, job, application = declared_send(tmp_path)
    evidence = SendEvidence(channel="website", sent_at=SENT_FRIDAY)
    again = service.record_send(job["id"], evidence)
    assert again["created"] is False
    assert again["record"]["sent_at"] == SENT_FRIDAY.isoformat()
    tracked = service.get_application(application["id"])
    # Un seul envoi dans l'historique, aucun doublon d'événement.
    send_events = [event for event in tracked["events"] if event["event_type"] == SEND_CONFIRMATION_EVENT_TYPE]
    assert len(send_events) == 1
    stage_events = [event for event in tracked["events"] if event["event_type"] == "stage_updated"]
    assert len(stage_events) == 1


def test_double_send_with_different_evidence_updates_in_place(tmp_path) -> None:
    service, job, application = declared_send(tmp_path)
    updated = service.record_send(
        job["id"], SendEvidence(channel="portal", sent_at=SENT_FRIDAY + timedelta(days=1))
    )
    assert updated["created"] is False
    assert updated["record"]["channel"] == "portal"
    assert updated["record"]["sent_at"] == (SENT_FRIDAY + timedelta(days=1)).isoformat()
    tracked = service.get_application(application["id"])
    send_events = [event for event in tracked["events"] if event["event_type"] == SEND_CONFIRMATION_EVENT_TYPE]
    assert len(send_events) == 1


def test_record_send_requires_prior_approval(tmp_path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(manual_job())
    service.create_application(job["id"])
    with pytest.raises(UserFacingError) as error:
        service.record_send(job["id"], SendEvidence(channel="website", sent_at=SENT_FRIDAY))
    assert "Approuve" in str(error.value)


def test_record_send_requires_an_existing_tracking(tmp_path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(manual_job())
    with pytest.raises(UserFacingError):
        service.record_send(job["id"], SendEvidence(channel="website", sent_at=SENT_FRIDAY))


def test_record_send_never_regresses_a_confirmed_application(tmp_path) -> None:
    service, job, application = declared_send(tmp_path)
    service.confirm_receipt(application["id"], "Réf. SYNTH-2026-001")
    response = service.record_send(job["id"], SendEvidence(channel="email", sent_at=SENT_FRIDAY + timedelta(days=2)))
    tracked = service.get_application(application["id"])
    assert tracked["stage"] == "submitted_confirmed"
    assert tracked["receipt_status"] == "confirmed"
    assert response["record"]["channel"] == "email"


# ---------------------------------------------------------------------------
# Brouillon de relance : français, prêt à copier, jamais envoyé
# ---------------------------------------------------------------------------

def test_followup_draft_is_french_copy_ready_and_honest(tmp_path) -> None:
    service, job, _ = declared_send(tmp_path)
    draft = service.build_followup_draft(job["id"])
    assert draft.startswith("[Brouillon local")
    assert "Stagiaire M&A" in draft
    assert "Banque Synthétique" in draft
    assert "2026-01-02" in draft
    assert "n'envoie rien" in draft
    module_draft = build_followup_draft(
        title="Stagiaire M&A",
        company="Banque Synthétique",
        channel="website",
        sent_at=SENT_FRIDAY,
        reference="SYNTH-42",
        candidate_name="Côme",
    )
    assert "site carrières" in module_draft
    assert "SYNTH-42" in module_draft
    assert module_draft.endswith("Côme")


def test_build_followup_draft_without_send_is_a_named_unknown(tmp_path) -> None:
    service, job, _ = approved_application(tmp_path)
    with pytest.raises(UserFacingError):
        service.build_followup_draft(job["id"])


# ---------------------------------------------------------------------------
# Rejouabilité : le SendRecord se reconstruit depuis le seul journal
# ---------------------------------------------------------------------------

def test_send_record_is_replayable_from_events() -> None:
    payload = {"channel": "portal", "sent_at": SENT_FRIDAY.isoformat(), "note": None}
    record = send_record_from_payload("job_123", payload)
    assert record is not None
    assert record.channel == "portal"
    assert record.follow_up_due.date() == date(2026, 1, 13)
    assert send_record_from_payload("job_123", {"channel": "", "sent_at": "pas-une-date"}) is None


def test_latest_send_evidence_and_followup_reading() -> None:
    events = [
        {"id": "e1", "event_type": SEND_CONFIRMATION_EVENT_TYPE, "detail": '{"channel": "website", "sent_at": "2026-01-02T10:00:00+00:00"}', "created_at": "2026-01-02T10:05:00+00:00"},
        {"id": "e2", "event_type": "stage_updated", "detail": "", "created_at": "2026-01-02T10:06:00+00:00"},
        {"id": "e3", "event_type": FOLLOWUP_RECORDED_EVENT_TYPE, "detail": '{"done_on": "2026-01-05"}', "created_at": "2026-01-05T09:00:00+00:00"},
    ]
    send = latest_send_evidence(events)
    assert send is not None
    assert send[0] == "e1"
    assert latest_followup_on(events) == date(2026, 1, 5)
    assert latest_send_evidence([]) is None
    assert latest_followup_on([]) is None


# ---------------------------------------------------------------------------
# Suivi de relance (apply-tracker) : priorisé par échéance, sans réponse
# ---------------------------------------------------------------------------

def test_apply_tracker_prioritizes_by_due_date_and_excludes_answered(tmp_path) -> None:
    service = CareerService(tmp_path)
    early = service.import_job(manual_job(company="Agence Tôt", title="Stagiaire Data", source_id="SYNTH-01", official_url="https://careers.example.test/jobs/synthetic-01"))
    late = service.import_job(manual_job(company="Agence Tard", title="Stagiaire Finance", source_id="SYNTH-02", official_url="https://careers.example.test/jobs/synthetic-02"))
    answered = service.import_job(manual_job(company="Agence Réponse", title="Stagiaire Risk", source_id="SYNTH-03", official_url="https://careers.example.test/jobs/synthetic-03"))
    for job in (early, late, answered):
        service.create_application(job["id"])
        service.approve_for_manual_submission(service.create_application(job["id"])["id"], True)
        service.record_send(job["id"], SendEvidence(channel="website", sent_at=SENT_FRIDAY))
    # Échéances décalées : « early » a été envoyé plus tôt → à relancer en premier.
    service.record_send(early["id"], SendEvidence(channel="website", sent_at=SENT_THURSDAY))
    # La troisième a reçu une réponse : elle sort du suivi de relance.
    answer_app = service.create_application(answered["id"])["id"]
    service.update_application_stage(answer_app, "response_received")

    tracker = service.apply_tracker()
    assert tracker["honesty"]
    assert tracker["totals"]["sent_without_response"] == 2
    assert [item["job_id"] for item in tracker["items"]] == [early["id"], late["id"]]
    first, second = tracker["items"]
    assert first["follow_up_due_date"] <= second["follow_up_due_date"]
    assert first["follow_up_due_date"] == "2026-01-12"
    assert second["follow_up_due_date"] == "2026-01-13"
    assert first["status"] == "due" and first["overdue"] is True
    assert all(item["is_email"] is False for item in tracker["items"])
    assert "Brouillon local" in first["followup_draft"]


def test_apply_tracker_marks_recent_sends_as_upcoming(tmp_path) -> None:
    service, job, _ = declared_send(tmp_path, sent_at=datetime.now(timezone.utc) - timedelta(hours=1))
    tracker = service.apply_tracker()
    assert tracker["totals"]["sent_without_response"] == 1
    item = tracker["items"][0]
    assert item["status"] == "upcoming"
    assert item["overdue"] is False
    assert item["days_waiting"] == 0


# ---------------------------------------------------------------------------
# Smoke test REST : POST /send-confirmation/{job_id} + GET /apply-tracker
# ---------------------------------------------------------------------------

def _client(tmp_path, service: CareerService) -> TestClient:
    return TestClient(create_app(tmp_path, agent_override=object(), career_override=service))


def test_rest_send_confirmation_roundtrip_and_idempotence(tmp_path) -> None:
    service, job, _ = approved_application(tmp_path)
    client = _client(tmp_path, service)
    payload = {"channel": "website", "sent_at": "2026-01-02T10:00:00+00:00", "note": "Dépôt manuel"}
    response = client.post(f"/api/career/send-confirmation/{job['id']}", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["record"]["follow_up_due_date"] == "2026-01-13"
    assert body["stage"] == "submitted"
    assert body["followup_draft"].startswith("[Brouillon local")

    repeat = client.post(f"/api/career/send-confirmation/{job['id']}", json=payload)
    assert repeat.status_code == 201
    assert repeat.json()["created"] is False

    read = client.get(f"/api/career/send-confirmation/{job['id']}")
    assert read.status_code == 200
    assert read.json()["record"]["channel"] == "website"

    tracker = client.get("/api/career/apply-tracker")
    assert tracker.status_code == 200
    items = tracker.json()["items"]
    assert len(items) == 1
    assert items[0]["job_id"] == job["id"]
    assert items[0]["follow_up_due_date"] == "2026-01-13"


def test_rest_send_confirmation_rejects_future_and_bad_payloads(tmp_path) -> None:
    service, job, _ = approved_application(tmp_path)
    client = _client(tmp_path, service)
    future = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
    assert client.post(
        f"/api/career/send-confirmation/{job['id']}",
        json={"channel": "website", "sent_at": future},
    ).status_code == 400
    assert client.post(
        f"/api/career/send-confirmation/{job['id']}",
        json={"channel": "fax", "sent_at": "2026-01-02T10:00:00+00:00"},
    ).status_code == 422
    assert client.post(
        f"/api/career/send-confirmation/{job['id']}",
        json={"channel": "website", "sent_at": "pas-une-date"},
    ).status_code == 422
    assert client.get("/api/career/apply-tracker").status_code == 200
    assert client.get("/api/career/send-confirmation/offer_inconnu").status_code == 400


def test_rest_followup_endpoint_shifts_due_date(tmp_path) -> None:
    service, job, _ = declared_send(tmp_path)
    client = _client(tmp_path, service)
    response = client.post(
        f"/api/career/send-confirmation/{job['id']}/followup",
        json={"done_on": "2026-01-05"},
    )
    assert response.status_code == 200
    assert response.json()["record"]["follow_up_due_date"] == "2026-01-14"
    assert client.post(
        f"/api/career/send-confirmation/{job['id']}/followup",
        json={"done_on": "pas-une-date"},
    ).status_code == 422
