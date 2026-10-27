"""Deterministic, local next actions for the Career application pipeline."""

from datetime import date

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
        "source_verified": False,
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
                kit_language="en",
                readiness="prepare_now",
            ),
            _item(
                job_id="interview",
                stage="tracking_created",
                tracking_stage="interview",
                application_id="app-interview",
                kit_generated_at="2026-10-23T08:00:00+00:00",
                kit_language="fr",
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
        "urgent_deadlines": 0,
        "passed_deadlines": 0,
        "sources_to_verify": 3,
        "languages_to_confirm": 0,
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


def test_manual_submission_requires_an_official_destination() -> None:
    unsafe = project_pipeline_item(
        _item(
            tracking_stage="approved_for_manual_submission",
            application_id="app-1",
            official_url="",
            readiness="prepare_now",
        )
    )
    safe = project_pipeline_item(
        _item(
            tracking_stage="approved_for_manual_submission",
            application_id="app-2",
            readiness="prepare_now",
            source_verified=True,
        )
    )

    assert unsafe["next_action_code"] == "locate_official_source"
    assert "source officielle" in unsafe["blockers"][0]
    assert unsafe["can_open_official_source"] is False
    assert safe["next_action_code"] == "manual_submit"
    assert safe["can_open_official_source"] is True


def test_manual_submission_requires_verified_source_not_only_a_url() -> None:
    result = project_pipeline_item(
        _item(
            tracking_stage="approved_for_manual_submission",
            application_id="app-unverified",
            readiness="prepare_now",
            source_verified=False,
        )
    )

    assert result["can_open_official_source"] is True
    assert result["source_trust_status"] == "to_verify"
    assert result["next_action_code"] == "verify_official_source"
    assert "vérifiée" in result["blockers"][-1]


def test_upcoming_deadline_moves_an_active_dossier_into_the_focus_plan() -> None:
    payload = build_application_action_center(
        [
            _item(job_id="normal", readiness="prepare_now", match_score=95),
            _item(
                job_id="urgent",
                readiness="offer_to_verify",
                match_score=40,
                deadline_date="2026-10-26",
            ),
        ],
        today=date(2026, 10, 24),
    )

    urgent = next(item for item in payload["pipeline"] if item["job_id"] == "urgent")
    assert urgent["days_until_deadline"] == 2
    assert urgent["deadline_status"] == "urgent"
    assert urgent["action_priority"] == 1
    assert payload["pipeline"][0]["job_id"] == "urgent"
    assert payload["focus_plan"]["items"][0]["job_id"] == "urgent"
    assert payload["summary"]["urgent_deadlines"] == 1


def test_expired_unsubmitted_offer_is_blocked_but_unknown_deadline_stays_unknown() -> None:
    expired = project_pipeline_item(
        _item(
            tracking_stage="ready_to_apply",
            application_id="app-expired",
            deadline_date="2026-10-20",
        ),
        today=date(2026, 10, 24),
    )
    unknown = project_pipeline_item(
        _item(deadline_date=""),
        today=date(2026, 10, 24),
    )

    assert expired["next_action_code"] == "deadline_passed"
    assert expired["deadline_status"] == "passed"
    assert expired["days_until_deadline"] == -4
    assert "dépassée" in expired["blockers"][-1]
    assert unknown["deadline_status"] == "unknown"
    assert unknown["days_until_deadline"] is None


def test_deadline_does_not_reopen_a_manually_submitted_application() -> None:
    submitted = project_pipeline_item(
        _item(
            tracking_stage="submitted",
            application_id="app-submitted",
            deadline_date="2026-10-20",
        ),
        today=date(2026, 10, 24),
    )

    assert submitted["next_action_code"] == "monitor_response"
    assert submitted["deadline_status"] == "passed"


def test_generated_kit_exposes_its_language_or_requires_confirmation() -> None:
    confirmed = project_pipeline_item(
        _item(
            kit_generated_at="2026-10-24T09:00:00+00:00",
            kit_language="en",
            readiness="prepare_now",
        )
    )
    missing = project_pipeline_item(
        _item(
            kit_generated_at="2026-10-24T09:00:00+00:00",
            kit_language="",
            readiness="prepare_now",
        )
    )

    assert confirmed["kit_language"] == "en"
    assert confirmed["kit_language_label"] == "English"
    assert confirmed["kit_language_status"] == "confirmed"
    assert missing["kit_language_status"] == "to_confirm"
    assert "langue" in missing["blockers"][-1].casefold()
