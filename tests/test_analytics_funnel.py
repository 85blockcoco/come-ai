"""Tests SPEC-025 — entonnoir analytics des candidatures (données synthétiques)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.analytics_funnel import (
    FUNNEL_STAGES,
    FunnelReport,
    FunnelStage,
    compute_funnel,
    funnel_by_channel,
    iso_week,
    normalize_channel,
    weakest_stage,
)
from career.service import SCHEMA_VERSION, CareerService
from come_ai_web import create_app

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "analytics_synthetic.json"
EXPECTED_COUNTS = [6, 4, 4, 3, 1, 2, 1]


def synthetic_records() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def manual_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Entreprise Synthétique",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/funnel-1",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-12-15",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": "SQL.\nPython.",
        "description_original": "Stage synthétique de quatre mois.",
    }
    payload.update(changes)
    return payload


# ---------------------------------------------------------------------------
# Contrat de structure
# ---------------------------------------------------------------------------

def test_report_matches_contract_and_stage_order() -> None:
    report = compute_funnel(synthetic_records())
    assert isinstance(report, FunnelReport)
    assert [stage.stage for stage in report.stages] == list(FUNNEL_STAGES)
    assert len(report.stages) == 7
    assert isinstance(report.weekly_series, dict)
    assert isinstance(report.per_channel, dict)
    assert isinstance(report.bottleneck_stage, str)


def test_counts_are_truthful_per_milestone() -> None:
    report = compute_funnel(synthetic_records())
    assert [stage.count for stage in report.stages] == EXPECTED_COUNTS


def test_conversions_stay_in_unit_interval() -> None:
    report = compute_funnel(synthetic_records())
    for stage in report.stages:
        assert 0.0 <= stage.conversion_from_prev <= 1.0
    conversions = {stage.stage: stage.conversion_from_prev for stage in report.stages}
    assert conversions["sent"] == 1.0
    assert conversions["viewed"] == pytest.approx(4 / 6, abs=1e-4)
    assert conversions["lettered"] == pytest.approx(3 / 4, abs=1e-4)
    assert conversions["followed_up"] == pytest.approx(1 / 3, abs=1e-4)
    # Une étape peut être plus large que la précédente (jalons non strictement
    # séquentiels) : la conversion est plafonnée, jamais > 1.
    assert conversions["interview"] == 1.0


def test_bottleneck_is_the_weakest_observed_transition() -> None:
    report = compute_funnel(synthetic_records())
    assert report.bottleneck_stage == "followed_up"
    assert weakest_stage(report) == "followed_up"
    assert weakest_stage(report.stages) == "followed_up"


# ---------------------------------------------------------------------------
# Honnêteté des jalons
# ---------------------------------------------------------------------------

def test_preparation_alone_never_counts_as_sent() -> None:
    prep_only = {
        "stage": "to_prepare",
        "has_draft": True,
        "has_letter": True,
        "events": [
            {"event_type": "checklist", "detail": '{"items": {"cv_reviewed": true, "letter_customized": true}}'}
        ],
    }
    report = compute_funnel([prep_only])
    counts = {stage.stage: stage.count for stage in report.stages}
    assert counts["prepped"] == 1
    assert counts["lettered"] == 1
    # Aucune ligne SQLite ni brouillon ne prouve un dépôt manuel.
    assert counts["sent"] == 0
    assert counts["viewed"] == 0
    assert counts["interview"] == 0


def test_free_text_notes_are_never_treated_as_proof() -> None:
    noisy = [
        {
            "stage": "to_review",
            "events": [
                {"event_type": "stage_updated", "detail": "candidature envoyée puis entretien puis offre"},
                {"event_type": "note", "detail": "sent viewed interview offer"},
            ],
        }
    ]
    report = compute_funnel(noisy)
    assert all(stage.count == 0 for stage in report.stages)


def test_late_status_implies_the_upstream_proof_it_logically_requires() -> None:
    report = compute_funnel([{"stage": "offer_received"}])
    counts = {stage.stage: stage.count for stage in report.stages}
    assert counts["sent"] == 1
    assert counts["viewed"] == 1
    assert counts["interview"] == 1
    assert counts["offer"] == 1
    # L'offre ne prouve ni relance planifiée ni lettre matériellement écrite.
    assert counts["followed_up"] == 0
    assert counts["lettered"] == 0


# ---------------------------------------------------------------------------
# Cas limites et adversarial
# ---------------------------------------------------------------------------

def test_empty_funnel_is_degenerate_without_division_by_zero() -> None:
    report = compute_funnel([])
    assert [stage.count for stage in report.stages] == [0] * 7
    assert all(stage.conversion_from_prev == 0.0 for stage in report.stages)
    assert report.weekly_series == {}
    assert report.per_channel == {}
    assert report.bottleneck_stage == ""
    assert weakest_stage(report) == ""


def test_malformed_records_do_not_crash_or_invent_data() -> None:
    garbage = [
        None,
        {},
        {"stage": {"inattendu": "dictionnaire"}},
        {"stage": 42, "events": "pas une liste"},
        {"stage": "submitted", "events": [None, "sent", 3.14]},
        {"stage": "submitted", "events": [{"event_type": "checklist", "detail": "{pas du json"}]},
        "texte libre",
        7,
    ]
    report = compute_funnel(garbage)
    assert [stage.count for stage in report.stages] == [2, 0, 0, 0, 0, 0, 0]
    for stage in report.stages:
        assert 0.0 <= stage.conversion_from_prev <= 1.0


def test_duplicate_events_do_not_double_count() -> None:
    record = {
        "stage": "submitted",
        "events": [
            {"event_type": "application_sent"},
            {"event_type": "application_sent"},
            {"event_type": "application_sent"},
        ],
    }
    report = compute_funnel([record])
    assert report.stages[0].count == 1


def test_unknown_or_blank_channel_is_explicit() -> None:
    assert normalize_channel("") == "unknown"
    assert normalize_channel(None) == "unknown"
    assert normalize_channel("  LinkedIn  ") == "linkedin"
    report = compute_funnel([{"stage": "submitted"}, {"stage": "submitted", "channel": "   "}])
    assert set(report.per_channel) == {"unknown"}
    assert report.per_channel["unknown"][0].count == 2


def test_channel_filter_is_case_and_space_insensitive() -> None:
    filtered = compute_funnel(synthetic_records(), channel="  LINKEDIN ")
    counts = {stage.stage: stage.count for stage in filtered.stages}
    assert counts["sent"] == 2
    assert counts["viewed"] == 1
    unknown = compute_funnel(synthetic_records(), channel="salon-inexistant")
    assert [stage.count for stage in unknown.stages] == [0] * 7
    assert unknown.bottleneck_stage == ""


# ---------------------------------------------------------------------------
# Séries hebdomadaires et canaux
# ---------------------------------------------------------------------------

def test_iso_week_normalizes_to_utc() -> None:
    assert iso_week("2026-10-05") == "2026-W41"
    assert iso_week("2026-10-05T00:30:00+02:00") == "2026-W40"
    assert iso_week("pas-une-date") is None
    assert iso_week("") is None


def test_weekly_series_groups_cohorts_by_iso_week() -> None:
    report = compute_funnel(synthetic_records())
    assert list(report.weekly_series) == ["2026-W41", "2026-W42", "2026-W43"]
    assert report.weekly_series["2026-W41"]["sent"] == 4
    assert report.weekly_series["2026-W42"]["sent"] == 1
    assert report.weekly_series["2026-W43"]["viewed"] == 1


def test_per_channel_funnels_are_grouped_and_sorted() -> None:
    report = compute_funnel(synthetic_records())
    assert list(report.per_channel) == ["direct", "linkedin", "school board", "unknown"]
    linkedin = {stage.stage: stage.count for stage in report.per_channel["linkedin"]}
    assert linkedin["sent"] == 2
    assert linkedin["prepped"] == 1
    assert funnel_by_channel(synthetic_records()) == report.per_channel


def test_determinism() -> None:
    assert compute_funnel(synthetic_records()) == compute_funnel(synthetic_records())


# ---------------------------------------------------------------------------
# Intégration service + API
# ---------------------------------------------------------------------------

def test_service_and_api_smoke_on_synthetic_data(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(manual_job())
    application = service.create_application(job["id"])
    application_id = str(application["id"])

    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        empty = client.get("/api/career/analytics/funnel")
        assert empty.status_code == 200
        payload = empty.json()
        assert [stage["stage"] for stage in payload["stages"]] == list(FUNNEL_STAGES)
        assert all(stage["count"] == 0 for stage in payload["stages"])
        assert payload["automatic_submission"] is False

        # Un dossier local préparé ne devient jamais « envoyé » par magie.
        service.create_application_draft(job["id"], "fr")
        service.set_application_checklist(application_id, ["cv_reviewed", "followup_planned"])
        prepared = client.get("/api/career/analytics/funnel").json()
        prepared_counts = {stage["stage"]: stage["count"] for stage in prepared["stages"]}
        assert prepared_counts["sent"] == 0
        assert prepared_counts["prepped"] == 1
        assert prepared_counts["lettered"] == 1
        assert prepared_counts["followed_up"] == 1

        # L'envoi est une action déclarée, après approbation explicite.
        service.approve_for_manual_submission(application_id, True)
        service.update_application_stage(application_id, "submitted")
        service.confirm_receipt(application_id, "SYNTH-REF-2026-001")
        sent = client.get("/api/career/analytics/funnel").json()
        sent_counts = {stage["stage"]: stage["count"] for stage in sent["stages"]}
        assert sent_counts["sent"] == 1
        assert sent_counts["viewed"] == 1
        assert sent["applications_counted"] == 1
        assert sent["channel_filter"] == ""

        manual = client.get("/api/career/analytics/funnel", params={"channel": "MANUAL"}).json()
        assert {stage["stage"]: stage["count"] for stage in manual["stages"]}["sent"] == 1
        other = client.get("/api/career/analytics/funnel", params={"channel": "linkedin"}).json()
        assert all(stage["count"] == 0 for stage in other["stages"])

        assert client.get("/api/career/analytics/funnel", params={"channel": "x" * 121}).status_code == 422


def test_endpoint_does_not_change_schema(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.analytics_funnel()
    with service._connection() as connection:  # noqa: SLF001 - vérification de migration
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 8


def test_funnel_stage_dataclass_contract() -> None:
    stage = FunnelStage(stage="sent", count=3, conversion_from_prev=1.0)
    assert stage.stage == "sent"
    assert stage.count == 3
    assert stage.conversion_from_prev == 1.0
