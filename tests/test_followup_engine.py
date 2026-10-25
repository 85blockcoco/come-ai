"""SPEC-029 — tests du moteur local de relances chronologiques.

Toutes les données sont synthétiques : aucune candidature réelle, aucun envoi,
aucun réseau.  Les tests couvrent la cadence J+7, l'intervalle minimal de cinq
jours, le plafond anti-spam, chaque raison de blocage, la robustesse aux
enregistrements malformés et le branchement REST sur ``create_app()``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.followup_engine import (
    DEFAULT_POLICY,
    FOLLOWUP_EVENT_TYPE,
    FollowupPolicy,
    application_view,
    followup_reason,
    plan_today,
    spam_guard,
)
from career.service import CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError

TODAY = date(2026, 10, 20)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "followups_synthetic.json"


def synthetic_records() -> list[dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["_meta"]["synthetic"] is True
    return payload["applications"]


def followup_app(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "application_id": "app_test",
        "stage": "submitted",
        "channel": "email",
        "sent_on": "2026-10-13",
        "viewed_on": "",
        "deadline_date": "",
        "availability_status": "open",
        "followups": [],
    }
    payload.update(changes)
    return payload


def action_for(plan, application_id: str):
    return next(
        (action for action in plan.actions if action.application_id == application_id),
        None,
    )


# ---------------------------------------------------------------------------
# Cadence : J+7, intervalle de 5 jours, plafond
# ---------------------------------------------------------------------------


def test_first_followup_is_due_exactly_at_j7() -> None:
    plan = plan_today(
        [followup_app(sent_on="2026-10-13")],
        today=TODAY,
    )
    action = action_for(plan, "app_test")
    assert action is not None
    assert action.due_date == "2026-10-20"
    assert action.reason == "no_response_j7"
    assert action.channel == "email"
    assert plan.blocked_reasons == {}


def test_first_followup_is_refused_before_j7() -> None:
    plan = plan_today([followup_app(sent_on="2026-10-14")], today=TODAY)
    assert plan.actions == []
    assert plan.blocked_reasons["app_test"] == "not_due:2026-10-21"


def test_second_followup_needs_five_days_between_contacts() -> None:
    application = followup_app(
        sent_on="2026-10-01",
        followups=[
            {"date": "2026-10-15", "channel": "email", "reason": "no_response_j7"}
        ],
    )
    blocked = plan_today([application], today=date(2026, 10, 19))
    assert blocked.actions == []
    assert (
        blocked.blocked_reasons["app_test"]
        == "min_interval_not_elapsed:2026-10-20"
    )
    allowed = plan_today([application], today=date(2026, 10, 20))
    action = action_for(allowed, "app_test")
    assert action is not None
    assert action.due_date == "2026-10-20"


def test_maximum_number_of_followups_blocks_over_followup() -> None:
    plan = plan_today(
        [
            followup_app(
                sent_on="2026-09-01",
                followups=[
                    {"date": "2026-09-10"},
                    {"date": "2026-09-18"},
                    {"date": "2026-09-26"},
                ],
            )
        ],
        today=TODAY,
    )
    assert plan.actions == []
    assert plan.blocked_reasons["app_test"] == "max_followups_reached"


def test_custom_policy_is_honoured() -> None:
    policy = FollowupPolicy(
        first_followup_days=10,
        min_interval_days=4,
        max_followups=2,
        deadline_soon_days=3,
    )
    plan = plan_today(
        [followup_app(sent_on="2026-10-13")],
        today=TODAY,
        policy=policy,
    )
    assert plan.actions == []
    assert plan.blocked_reasons["app_test"] == "not_due:2026-10-23"


def test_invalid_policy_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        FollowupPolicy(first_followup_days=0)
    with pytest.raises(ValueError):
        FollowupPolicy(min_interval_days=0)
    with pytest.raises(ValueError):
        FollowupPolicy(default_channel="fax")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Raisons : viewed_no_reply, deadline_soon, états exclus
# ---------------------------------------------------------------------------


def test_viewed_without_reply_uses_the_viewed_reason() -> None:
    plan = plan_today(
        [followup_app(sent_on="2026-10-05", viewed_on="2026-10-12")],
        today=date(2026, 10, 15),
    )
    action = action_for(plan, "app_test")
    assert action is not None
    assert action.due_date == "2026-10-12"
    assert action.reason == "viewed_no_reply"


def test_deadline_soon_takes_priority_over_no_response() -> None:
    application = followup_app(
        sent_on="2026-10-02",
        deadline_date="2026-10-23",
        followups=[{"date": "2026-10-10", "channel": "email"}],
    )
    assert followup_reason(application, on_date=TODAY) == "deadline_soon"
    plan = plan_today([application], today=TODAY)
    action = action_for(plan, "app_test")
    assert action is not None
    assert action.reason == "deadline_soon"


def test_closed_and_responded_stages_are_blocked() -> None:
    plan = plan_today(
        [
            followup_app(application_id="app_closed", stage="rejected"),
            followup_app(application_id="app_interview", stage="interview"),
            followup_app(application_id="app_offer", stage="offer_received"),
        ],
        today=TODAY,
    )
    assert plan.actions == []
    assert plan.blocked_reasons == {
        "app_closed": "closed",
        "app_interview": "responded",
        "app_offer": "responded",
    }


def test_unsent_and_undated_applications_are_blocked() -> None:
    plan = plan_today(
        [
            followup_app(application_id="app_prepare", stage="to_prepare", sent_on=""),
            followup_app(application_id="app_no_date", sent_on=""),
            followup_app(
                application_id="app_future",
                sent_on="2026-12-01",
            ),
        ],
        today=TODAY,
    )
    assert plan.actions == []
    assert plan.blocked_reasons == {
        "app_future": "invalid_sent_date",
        "app_no_date": "missing_sent_date",
        "app_prepare": "not_sent",
    }


def test_closed_offer_and_invalid_channel_are_blocked() -> None:
    plan = plan_today(
        [
            followup_app(
                application_id="app_closed_offer", availability_status="closed"
            ),
            followup_app(application_id="app_bad_channel", channel="pigeon"),
        ],
        today=TODAY,
    )
    assert plan.actions == []
    assert plan.blocked_reasons == {
        "app_bad_channel": "invalid_channel",
        "app_closed_offer": "offer_closed",
    }


def test_spam_guard_exposes_the_next_allowed_date() -> None:
    application = followup_app(sent_on="2026-10-13")
    before = spam_guard(application, on_date="2026-10-19")
    assert before.allowed is False
    assert before.reason == "not_due"
    assert before.next_allowed_date == "2026-10-20"
    after = spam_guard(application, on_date="2026-10-20")
    assert after.allowed is True
    assert after.reason == "due"
    assert after.followups_used == 0


# ---------------------------------------------------------------------------
# Normalisation, déterminisme, robustesse adversariale
# ---------------------------------------------------------------------------


def test_application_view_reads_events_and_ignores_bad_event_dates() -> None:
    events = [
        {
            "event_type": "stage_updated",
            "created_at": "2026-10-01T10:00:00+00:00",
            "detail": "ancien état",
        },
        {
            "event_type": "stage_updated",
            "created_at": "2026-10-13T10:00:00+00:00",
            "detail": "envoi déclaré",
        },
        {
            "event_type": "application_viewed",
            "created_at": "2026-10-16T08:00:00+00:00",
            "detail": "",
        },
        {
            "event_type": FOLLOWUP_EVENT_TYPE,
            "created_at": "2026-10-18T09:00:00+00:00",
            "detail": json.dumps(
                {
                    "date": "2026-10-18",
                    "channel": "email",
                    "reason": "no_response_j7",
                }
            ),
        },
        {
            "event_type": "followup_recorded",
            "created_at": "2026-10-19T09:00:00+00:00",
            "detail": "{json corrompu",
        },
        {
            "event_type": "application_viewed",
            "created_at": "pas-une-date",
            "detail": "",
        },
    ]
    view = application_view(
        {
            "id": "app_events",
            "stage": "submitted",
            "deadline_date": "2026-11-01",
            "source_status": "open",
        },
        events,
    )
    assert view["application_id"] == "app_events"
    assert view["sent_on"] == "2026-10-13"
    assert view["viewed_on"] == "2026-10-16"
    # La charge JSON corrompue retombe sur l'horodatage de l'événement : une
    # relance consignée reste comptée, sans jamais inventer de date impossible.
    assert [item["date"] for item in view["followups"]] == [
        "2026-10-18",
        "2026-10-19",
    ]
    assert view["channel"] == "portal"


def test_duplicate_application_ids_are_refused_without_double_action() -> None:
    plan = plan_today(
        [
            followup_app(application_id="app_dup", sent_on="2026-10-01"),
            followup_app(application_id="app_dup", sent_on="2026-10-01"),
        ],
        today=TODAY,
    )
    assert plan.actions == []
    assert plan.blocked_reasons == {"app_dup": "duplicate_application_id"}


def test_plan_is_deterministic_and_sorted() -> None:
    applications = synthetic_records()
    first = plan_today(applications, today=TODAY)
    second = plan_today(applications, today=TODAY)
    assert first == second
    assert [
        (action.due_date, action.application_id) for action in first.actions
    ] == sorted(
        (action.due_date, action.application_id) for action in first.actions
    )
    assert {action.application_id for action in first.actions} == {
        "app_due_j7",
        "app_viewed_no_reply",
        "app_deadline_soon",
    }


def test_fixture_covers_every_required_blocking_case() -> None:
    plan = plan_today(synthetic_records(), today=TODAY)
    assert plan.blocked_reasons["app_not_due"] == "not_due:2026-10-23"
    assert (
        plan.blocked_reasons["app_interval_blocked"]
        == "min_interval_not_elapsed:2026-10-22"
    )
    assert plan.blocked_reasons["app_max_reached"] == "max_followups_reached"
    assert plan.blocked_reasons["app_closed"] == "closed"
    assert plan.blocked_reasons["app_responded"] == "responded"
    assert plan.blocked_reasons["app_not_sent"] == "not_sent"
    assert plan.blocked_reasons["app_missing_sent_date"] == "missing_sent_date"
    assert plan.blocked_reasons["app_offer_closed"] == "offer_closed"
    assert plan.blocked_reasons["app_bad_channel"] == "invalid_channel"


def test_adversarial_malformed_records_never_raise() -> None:
    plan = plan_today(
        [
            None,
            "pas un enregistrement",
            {},
            {"application_id": "", "stage": "submitted"},
            {
                "application_id": {"nested": "valeur"},
                "stage": ["submitted"],
                "sent_on": ["2026-10-13"],
                "followups": "pas-une-liste",
            },
            {
                "application_id": "app_" + "x" * 5_000,
                "stage": "submitted",
                "sent_on": "9999-99-99",
                "channel": None,
                "followups": [None, 4, {"date": "date-invalide"}],
            },
        ],
        today=TODAY,
    )
    assert plan.date == TODAY.isoformat()
    assert isinstance(plan.actions, list)
    assert isinstance(plan.blocked_reasons, dict)
    # Aucune date inventée et aucune exception : les entrées vides sont
    # simplement ignorées, les autres reçoivent un blocage nommé.
    assert all(len(key) <= 512 for key in plan.blocked_reasons)
    assert "missing_sent_date" in plan.blocked_reasons.values()


def test_engine_module_has_no_network_or_mail_dependency() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "career" / "followup_engine.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "import requests",
        "import smtplib",
        "import socket",
        "import urllib",
        "import http.client",
    ):
        assert forbidden not in source
    assert "smtp" not in source.lower()


# ---------------------------------------------------------------------------
# Service local et REST (create_app) — smoke tests obligatoires
# ---------------------------------------------------------------------------


def manual_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Entreprise Synthétique",
        "title": "Stagiaire Data",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/synthetic-29",
        "job_family": "Tech / Produit",
        "city": "Lyon",
        "country": "France",
        "posted_date": "2026-09-01",
        "deadline_date": "2026-12-15",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": "Python.\nSQL.",
        "description_original": "Stage synthétique de quatre mois.",
    }
    payload.update(changes)
    return payload


def submitted_application(tmp_path: Path, *, sent_at: str = "2026-10-13T10:00:00+00:00"):
    service = CareerService(tmp_path)
    job = service.import_job(manual_job())
    application = service.create_application(job["id"])
    service.approve_for_manual_submission(application["id"], True)
    service.update_application_stage(application["id"], "submitted", "envoi manuel")
    with sqlite3.connect(service.db_path) as connection:
        connection.execute(
            """
            UPDATE application_events
            SET created_at = ?
            WHERE application_id = ? AND event_type = 'stage_updated'
            """,
            (sent_at, application["id"]),
        )
    return service, application


def test_service_plan_uses_the_local_event_journal(tmp_path: Path) -> None:
    service, application = submitted_application(tmp_path)
    plan = service.followup_plan(today=TODAY)
    assert plan["date"] == "2026-10-20"
    assert [action["application_id"] for action in plan["actions"]] == [
        application["id"]
    ]
    assert plan["actions"][0]["reason"] == "no_response_j7"
    assert plan["actions"][0]["due_date"] == "2026-10-20"


def test_empty_database_yields_an_empty_but_valid_plan(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    plan = service.followup_plan(today=TODAY)
    assert plan == {"date": "2026-10-20", "actions": [], "blocked_reasons": {}}


def test_record_followup_persists_and_blocks_immediate_over_followup(
    tmp_path: Path,
) -> None:
    service, application = submitted_application(tmp_path)
    recorded = service.record_followup(
        application["id"], on_date="2026-10-20", channel="email"
    )
    events = [event["event_type"] for event in recorded["events"]]
    assert FOLLOWUP_EVENT_TYPE in events

    plan = service.followup_plan(today=TODAY)
    assert plan["actions"] == []
    assert (
        plan["blocked_reasons"][application["id"]]
        == "min_interval_not_elapsed:2026-10-25"
    )
    with pytest.raises(UserFacingError):
        service.record_followup(
            application["id"], on_date="2026-10-24", channel="email"
        )
    later = service.record_followup(
        application["id"], on_date="2026-10-25", channel="portal"
    )
    assert len(
        [event for event in later["events"] if event["event_type"] == FOLLOWUP_EVENT_TYPE]
    ) == 2


def test_record_followup_refuses_invalid_channel_and_unsent_application(
    tmp_path: Path,
) -> None:
    service, application = submitted_application(tmp_path)
    with pytest.raises(UserFacingError):
        service.record_followup(
            application["id"], on_date="2026-10-20", channel="fax"
        )
    unsent_service = CareerService(tmp_path / "other")
    job = unsent_service.import_job(manual_job(title="Stage non envoyé"))
    unsent = unsent_service.create_application(job["id"])
    with pytest.raises(UserFacingError):
        unsent_service.record_followup(
            unsent["id"], on_date="2026-10-20", channel="portal"
        )


def test_http_followup_plan_and_record_endpoints(tmp_path: Path) -> None:
    service, application = submitted_application(tmp_path)
    client = TestClient(
        create_app(tmp_path, agent_override=object(), career_override=service)
    )

    planned = client.get("/api/career/followups/plan", params={"date": "2026-10-20"})
    assert planned.status_code == 200
    payload = planned.json()
    assert payload["date"] == "2026-10-20"
    assert payload["actions"][0]["application_id"] == application["id"]

    recorded = client.post(
        f"/api/career/followups/{application['id']}/record",
        json={"date": "2026-10-20", "channel": "email"},
    )
    assert recorded.status_code == 201

    after = client.get(
        "/api/career/followups/plan", params={"date": "2026-10-20"}
    ).json()
    assert after["actions"] == []
    assert (
        after["blocked_reasons"][application["id"]]
        == "min_interval_not_elapsed:2026-10-25"
    )

    dashboard = client.get("/api/career/applications/dashboard")
    assert dashboard.status_code == 200
    assert "followup_plan" in dashboard.json()
    assert dashboard.json()["followup_plan"]["date"]


def test_http_validation_errors_are_explicit(tmp_path: Path) -> None:
    service, application = submitted_application(tmp_path)
    client = TestClient(
        create_app(tmp_path, agent_override=object(), career_override=service)
    )
    assert client.get(
        "/api/career/followups/plan", params={"date": "20-10-2026"}
    ).status_code == 422
    assert client.post(
        f"/api/career/followups/{application['id']}/record",
        json={"date": "2026-10-20", "channel": "fax"},
    ).status_code == 422
    assert client.post(
        "/api/career/followups/introuvable/record",
        json={"date": "2026-10-20", "channel": "email"},
    ).status_code == 400


def test_default_policy_matches_the_mission_thresholds() -> None:
    assert DEFAULT_POLICY.first_followup_days == 7
    assert DEFAULT_POLICY.min_interval_days == 5
    assert DEFAULT_POLICY.max_followups == 3
