"""Focused offline coverage for the dashboard's computed Career next steps."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from career.service import CareerService


def _job_payload(identifier: str, **changes: object) -> dict[str, object]:
    """Create a valid local offer without depending on an external board."""
    payload: dict[str, object] = {
        "company": "Banque Exemple",
        "title": f"M&A Intern {identifier}",
        "source_name": "manual",
        "official_url": f"https://careers.example.test/jobs/{identifier}",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "deadline_date": (date.today() + timedelta(days=2)).isoformat(),
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "description_original": "Stage local de modélisation financière.",
    }
    payload.update(changes)
    return payload


def _action_ids(service: CareerService) -> list[str]:
    return [str(action["id"]) for action in service.dashboard()["action_plan"]]


def test_action_plan_does_not_repeat_a_manual_submission_after_receipt_is_unknown(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_job_payload("receipt"))
    application = service.create_application(job["id"])
    service.approve_for_manual_submission(application["id"], True, "Relecture locale terminée")

    assert "applications-manual-submission" in _action_ids(service)

    # Once the person records that the receipt is unknown, the useful next
    # step is follow-up.  The dashboard must not suggest submitting again.
    service.mark_receipt_unknown(application["id"], "Pas de confirmation reçue")
    action_ids = _action_ids(service)
    assert "applications-receipt" in action_ids
    assert "applications-manual-submission" not in action_ids


def test_action_plan_excludes_post_submission_history_from_deadline_work(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_job_payload("submitted"))
    application = service.create_application(job["id"])
    service.approve_for_manual_submission(application["id"], True, "Prêt pour dépôt manuel")
    service.confirm_receipt(application["id"], "Confirmation officielle")

    dashboard = service.dashboard()
    action_ids = [str(action["id"]) for action in dashboard["action_plan"]]
    assert "discover-jobs" in action_ids
    assert "offers-deadline" not in action_ids
    assert "offers-verification" not in action_ids
    assert "applications-manual-submission" not in action_ids
    assert dashboard["upcoming_deadlines"] == []


def test_action_plan_ignores_archived_history_and_keeps_french_pluralization(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    intake_action = next(action for action in service.dashboard()["action_plan"] if action["id"] == "intake-completion")
    assert "6 questions" in intake_action["detail"]

    job = service.import_job(_job_payload("archived"))
    # Simulate a pre-existing archived row from the local tracker.  The
    # dashboard remains read-only and should not revive it as an urgency.
    with sqlite3.connect(service.db_path) as connection:
        connection.execute("UPDATE jobs SET status = 'archived' WHERE id = ?", (job["id"],))

    dashboard = service.dashboard()
    action_ids = [str(action["id"]) for action in dashboard["action_plan"]]
    assert "discover-jobs" in action_ids
    assert "offers-deadline" not in action_ids
    assert "offers-verification" not in action_ids
    assert dashboard["upcoming_deadlines"] == []

    for answer in ("M&A", "Paris", "Banques", "Analyse", "Excel", "Stage"):
        intake = service.answer_intake(answer)
    assert intake["completed"] is True
    assert "intake-completion" not in _action_ids(service)
