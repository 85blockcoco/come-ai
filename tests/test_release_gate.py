"""Focused acceptance tests for the Career release gate (local, synthetic)."""

from __future__ import annotations

import json
from pathlib import Path

from career.release_gate import (
    APP_VERIFIED,
    LIVE,
    QUALITY_NOTE,
    SYNTHETIC_PROFILE,
    GateCheck,
    ReleaseReport,
    run_release_gate,
)


def test_release_gate_runs_the_full_journey_over_real_http(tmp_path: Path) -> None:
    report = run_release_gate(tmp_path, browser=False)

    assert report.ok, report.to_markdown()
    assert report.counts["fail"] == 0
    ids = {check.id for check in report.checks}
    assert {
        "health_local_only",
        "profile_import_review_apply",
        "exploration_sources",
        "matching",
        "dedup_reimport",
        "adversarial_offers",
        "job_prep",
        "apply_kit_downloads",
        "pipeline",
        "tracking_approval_checklist",
        "receipt_followup_radar",
        "interview_coach",
        "no_hidden_send",
        "restart_persistence",
        "offline_reads",
        "privacy_scan",
    } <= ids

    # The browser is never claimed when explicitly disabled.
    browser_check = next(check for check in report.checks if check.id == "browser_smoke")
    assert browser_check.status == "skip"
    assert "désactivé" in browser_check.detail

    # Live coverage is never claimed without explicit opt-in, and quality is
    # honestly left unmeasured.
    live_check = next(check for check in report.checks if check.id == "live_public_source")
    assert live_check.status == "skip"
    assert live_check.metric == LIVE
    metrics = report.metrics
    assert metrics["classes"][LIVE] == {"pass": 0, "fail": 0, "skip": 1}
    assert metrics["quality_measurement"] == {"status": "unmeasured", "note": QUALITY_NOTE}
    assert metrics["submission"]["automatic"] is False
    assert APP_VERIFIED in metrics["classes"]


def test_release_gate_report_never_leaks_private_profile_fields(tmp_path: Path) -> None:
    report = run_release_gate(tmp_path, browser=False)
    serialized = report.to_json() + report.to_markdown()

    assert SYNTHETIC_PROFILE["contact_email"] not in serialized
    assert SYNTHETIC_PROFILE["contact_phone"] not in serialized
    assert "RECETTE-SYNTHETIQUE-001" not in serialized
    assert "[ERREUR" not in serialized
    assert SYNTHETIC_PROFILE["display_name"] not in serialized


def test_release_gate_report_is_deterministic_and_marks_failures() -> None:
    failing = ReleaseReport(
        checks=[
            GateCheck("ok", "Check vert", "pass", "app-verified", "fine"),
            GateCheck("ko", "Check rouge", "fail", "app-verified", "broken"),
            GateCheck("skip", "Check ignoré", "skip", "live", "not requested"),
        ],
        generated_at="2026-10-29",
    )

    assert failing.ok is False
    assert failing.counts == {"pass": 1, "fail": 1, "skip": 1}
    assert "FAIL" in failing.to_markdown()
    payload = json.loads(failing.to_json())
    assert payload["ok"] is False
    assert payload["metrics"]["classes"]["live"]["skip"] == 1
    assert payload["checks"][1]["status"] == "fail"


def test_gate_uses_a_fresh_database_and_keeps_existing_data_on_partial(tmp_path: Path) -> None:
    first = run_release_gate(tmp_path, browser=False)
    assert first.ok

    # A second run on the same directory proves the gate tolerates existing
    # state: profile import is idempotent, jobs deduplicate and the partial
    # source still never erases prior offers or applications.
    second = run_release_gate(tmp_path, browser=False)
    assert second.ok, second.to_markdown()
    exploration = next(check for check in second.checks if check.id == "exploration_sources")
    assert exploration.status == "pass"
    offline = next(check for check in second.checks if check.id == "offline_reads")
    assert offline.status == "pass"
