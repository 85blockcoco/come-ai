"""Deterministic, local next actions for the Career application pipeline."""

from career.action_center import build_application_action_center, project_pipeline_item


def _item(**changes):
    item = {
        "job_id": "job-1",
        "company": "Synthetic Bank",
        "title": "Finance Intern",
        "stage": "sprint_queued",
        "readiness": "offer_to_verify",
        "match_score": 82,
        "tracking_stage": None,
        "application_id": None,
        "official_url": "https://careers.example.test/jobs/1",
        "kit_generated_at": None,
    }
    item.update(changes)
    return item


def test_offer_to_verify_has_an_explicit_safe_next_action() -> None:
    result = project_pipeline_item(_item())
    assert result["stage_label"] == "Dans la liste express"
    assert result["next_action_code"] == "verify_offer"
    assert result["progress_percent"] == 35
    assert result["blockers"] == ["Des faits de l’offre restent à vérifier sur la source officielle."]


def test_early_tracking_record_does_not_hide_missing_kit() -> None:
    result = project_pipeline_item(
        _item(tracking_stage="to_review", application_id="app-1")
    )
    assert result["next_action_code"] == "create_kit"
    assert result["tracking_exists"] is True
    assert result["kit_ready"] is False


def test_generated_kit_and_interview_receive_higher_priority_actions() -> None:
    payload = build_application_action_center(
        [
            _item(job_id="verify"),
            _item(
                job_id="kit",
                stage="tracking_created",
                tracking_stage="to_review",
                application_id="app-kit",
                kit_generated_at="2026-10-24T08:00:00+00:00",
                readiness="prepare_now",
            ),
            _item(
                job_id="interview",
                stage="tracking_created",
                tracking_stage="interview",
                application_id="app-interview",
                kit_generated_at="2026-10-23T08:00:00+00:00",
                readiness="prepare_now",
            ),
        ]
    )
    assert [item["job_id"] for item in payload["pipeline"]] == ["interview", "kit", "verify"]
    assert payload["summary"] == {
        "total": 3,
        "actions_now": 3,
        "facts_to_verify": 1,
        "kits_ready": 2,
        "tracked": 2,
        "interviews": 1,
    }
    assert payload["automatic_submission"] is False
    assert "jamais" in payload["disclaimer"]


def test_focus_plan_fills_a_bounded_work_session_without_auto_submission() -> None:
    payload = build_application_action_center(
        [
            _item(
                job_id="interview",
                tracking_stage="interview",
                application_id="app-interview",
                readiness="prepare_now",
            ),
            _item(
                job_id="manual",
                tracking_stage="approved_for_manual_submission",
                application_id="app-manual",
                readiness="prepare_now",
            ),
            _item(job_id="verify"),
            _item(job_id="analyse", readiness="prepare_now"),
        ]
    )

    focus = payload["focus_plan"]
    assert focus["budget_minutes"] == 60
    assert focus["planned_minutes"] <= 60
    assert [item["job_id"] for item in focus["items"]] == [
        "interview",
        "manual",
        "verify",
    ]
    assert focus["deferred_count"] == 1
    assert focus["automatic_submission"] is False
    assert all(item["estimated_minutes"] > 0 for item in focus["items"])


def test_focus_plan_ignores_closed_and_passive_monitoring_rows() -> None:
    payload = build_application_action_center(
        [
            _item(job_id="closed", tracking_stage="rejected", application_id="app-closed"),
            _item(job_id="waiting", tracking_stage="submitted", application_id="app-waiting"),
        ]
    )

    assert payload["focus_plan"]["items"] == []
    assert payload["focus_plan"]["planned_minutes"] == 0
    assert payload["focus_plan"]["deferred_count"] == 0
