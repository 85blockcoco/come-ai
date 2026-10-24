"""SPEC-029 — moteur de relances chronologiques (tests synthétiques)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from career.followup_engine import (
    FollowupAction,
    FollowupPlan,
    FollowupPolicy,
    plan_today,
    spam_guard,
)
from career.service import CareerService
from come_ai_web import create_app

FIXTURE = Path("tests/fixtures/followups_synthetic.json")
TODAY = date(2026, 10, 20)


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_dataclasses_basic() -> None:
    action = FollowupAction(
        application_id="app-1",
        due_date="2026-10-20",
        reason="no_response_j7",
        channel="email",
    )
    plan = FollowupPlan(date="2026-10-20", actions=[action], blocked_reasons={"x": "too soon"})
    assert plan.actions[0].reason == "no_response_j7"
    assert plan.blocked_reasons["x"] == "too soon"


def test_first_followup_j7() -> None:
    policy = FollowupPolicy(first_followup_days=7, min_gap_days=5)
    data = load_fixture()
    plan = plan_today(data["applications"], policy=policy, today=TODAY)
    ids = {a.application_id for a in plan.actions}
    assert "app-no-response" in ids
    action = next(a for a in plan.actions if a.application_id == "app-no-response")
    assert action.reason == "no_response_j7"
    assert action.due_date == TODAY.isoformat()


def test_recent_application_not_due() -> None:
    data = load_fixture()
    plan = plan_today(data["applications"], today=TODAY)
    ids = {a.application_id for a in plan.actions}
    assert "app-recent" not in ids


def test_viewed_no_reply() -> None:
    data = load_fixture()
    plan = plan_today(data["applications"], today=TODAY)
    ids_reasons = {a.application_id: a.reason for a in plan.actions}
    assert ids_reasons.get("app-viewed") == "viewed_no_reply"


def test_deadline_soon() -> None:
    data = load_fixture()
    plan = plan_today(data["applications"], today=TODAY)
    ids_reasons = {a.application_id: a.reason for a in plan.actions}
    assert ids_reasons.get("app-deadline") == "deadline_soon"


def test_closed_skipped() -> None:
    data = load_fixture()
    plan = plan_today(data["applications"], today=TODAY)
    ids = {a.application_id for a in plan.actions}
    assert "app-closed" not in ids


def test_spam_guard_blocks_recent_followup() -> None:
    data = load_fixture()
    app = next(a for a in data["applications"] if a["application_id"] == "app-spam")
    assert spam_guard("app-spam", history=data, today=TODAY, application=app) is False


def test_spam_guard_allows_when_gap_ok() -> None:
    data = load_fixture()
    app = next(a for a in data["applications"] if a["application_id"] == "app-no-response")
    assert spam_guard("app-no-response", history=data, today=TODAY, application=app) is True


def test_spam_blocked_in_plan() -> None:
    data = load_fixture()
    plan = plan_today(data["applications"], today=TODAY)
    assert "app-spam" in plan.blocked_reasons


def test_plan_date_and_types() -> None:
    data = load_fixture()
    plan = plan_today(data["applications"], today=TODAY)
    assert isinstance(plan, FollowupPlan)
    assert plan.date == TODAY.isoformat()
    for action in plan.actions:
        assert isinstance(action, FollowupAction)
        assert action.channel in {"email", "portal", "in_person"}


def test_history_dict_of_events() -> None:
    history = {
        "app-x": [
            {"event_type": "stage_updated", "created_at": "2026-10-01T09:00:00+00:00"}
        ]
    }
    apps = [
        {
            "application_id": "app-x",
            "stage": "submitted",
            "receipt_status": "unknown",
            "updated_at": "2026-10-01T09:00:00+00:00",
        }
    ]
    plan = plan_today(apps, history=history, today=TODAY)
    assert any(a.application_id == "app-x" for a in plan.actions)


def test_service_and_rest_smoke(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(
        {
            "company": "Synth",
            "title": "Intern",
            "source_name": "manual",
            "official_url": "https://example.test/job",
            "deadline_date": "2026-12-15",
        }
    )
    app_row = service.create_application(job["id"])
    aid = app_row["id"]
    # Make it look sent + old.
    service.approve_for_manual_submission(aid, True, "ok")
    service.update_application_stage(aid, "submitted", "sent")
    # backdate by direct event? Use application event via service not exposed; plan uses updated_at
    # Force updated_at old via SQL not needed; instead call plan_today directly with override
    result = service.followup_plan(today=TODAY.isoformat())
    assert "date" in result
    assert "actions" in result
    assert "blocked_reasons" in result

    client = TestClient(create_app(career_override=service, base_dir=tmp_path))
    for path in ("/api/career/followups", "/api/career/followup-plan", "/api/career/followups/plan"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
    post = client.post("/api/career/followups/plan", json={"today": TODAY.isoformat()})
    assert post.status_code == 200


def test_adversarial_spam_gap_boundary() -> None:
    # exactly 5 days gap is allowed, 4 is not
    history = {
        "app-1": [{"event_type": "followup", "created_at": "2026-10-15T09:00:00+00:00"}]
    }
    apps = [{"application_id": "app-1", "stage": "submitted", "receipt_status": "unknown", "updated_at": "2026-10-01T09:00:00+00:00"}]
    policy = FollowupPolicy(first_followup_days=1, min_gap_days=5)
    # 5 days after 10-15 = 10-20 exactly
    assert spam_guard("app-1", history=history, today=date(2026, 10, 20), application=apps[0], policy=policy) is True
    assert spam_guard("app-1", history=history, today=date(2026, 10, 19), application=apps[0], policy=policy) is False
