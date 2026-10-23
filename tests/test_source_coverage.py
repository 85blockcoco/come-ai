"""Tests for the exact source coverage metrics (SPEC-SK04).

The module measures one explorer run.  These tests pin the two rules the
mission insists on: synthetic data never inflates a live counter, and every
published number stays recalculable and coherent.
"""

from __future__ import annotations

import json

import pytest

from career.service import CareerService
from career.source_coverage import (
    BUCKETS,
    CareerDatabaseLoader,
    CoverageMetrics,
    CoveragePayload,
    CoverageRunNotFound,
    _coherence_violations,
    compute_coverage,
    compute_metrics,
    is_synthetic_source,
    synthetic_fixture_metrics,
    synthetic_fixture_payload,
)


METRIC_NAMES = (
    "sources_planned",
    "sources_queried",
    "sources_succeeded",
    "sources_cached",
    "sources_failed",
    "unique_employers",
    "raw_offers",
    "valid_offers",
    "offers_pre_dedup",
    "offers_post_dedup",
    "offers_verified_url",
    "offers_with_location",
    "offers_with_published_date",
    "offers_with_start_date",
    "offers_with_duration",
    "offers_with_requirements",
    "compliant",
    "to_verify",
    "non_compliant",
)


def source(
    source_id: str = "registry:greenhouse:live",
    *,
    status: str = "success",
    provider: str = "greenhouse",
    company: str = "Live Employer",
    **counts: object,
) -> dict[str, object]:
    outcome: dict[str, object] = {
        "source_id": source_id,
        "provider": provider,
        "company": company,
        "status": status,
        "attempted": status not in {"not_queried", "unsupported"},
    }
    outcome.update(counts)
    return outcome


def offer(
    job_id: str = "job-1",
    *,
    source_name: str = "greenhouse",
    source_id: str = "ats-1",
    company: str = "Live Employer",
    url: str = "https://boards.greenhouse.io/live/jobs/1",
    **facts: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "job_id": job_id,
        "source_name": source_name,
        "source_id": source_id,
        "company": company,
        "title": "Stage - Finance",
        "official_url": url,
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "start_date": "2027-01-05",
        "duration_months": 6,
        "requirements": "Excel",
        "verification_status": "verified",
        "target_status": "conforming",
    }
    record.update(facts)
    return record


def payload(
    *,
    sources: tuple[dict[str, object], ...] = (),
    offers: tuple[dict[str, object], ...] = (),
    run_id: str = "explore_test",
) -> CoveragePayload:
    return CoveragePayload(run_id=run_id, sources=sources, offers=offers, computed_at="2026-10-20T10:00:00+00:00")


# --------------------------------------------------------------------------
# Shape of the measurement
# --------------------------------------------------------------------------


def test_the_nineteen_measures_are_published() -> None:
    assert tuple(CoverageMetrics().to_dict()) == METRIC_NAMES
    assert len(METRIC_NAMES) >= 19


def test_the_report_keeps_one_entry_per_bucket() -> None:
    report = compute_coverage(payload())
    assert tuple(report.metrics) == BUCKETS
    assert report.to_dict()["schema"] == "come-career-source-coverage/1"


def test_the_report_is_json_serialisable() -> None:
    report = compute_coverage(payload(sources=(source(),), offers=(offer(),)))
    assert json.loads(json.dumps(report.to_dict(), ensure_ascii=False))["run_id"] == "explore_test"


def test_the_measurement_is_deterministic() -> None:
    material = payload(sources=(source(),), offers=(offer(),))
    assert compute_coverage(material).to_dict() == compute_coverage(material).to_dict()


def test_the_computed_at_is_the_timestamp_of_the_run_not_of_the_measurement() -> None:
    report = compute_coverage(payload())
    assert report.computed_at == "2026-10-20T10:00:00+00:00"


# --------------------------------------------------------------------------
# Synthetic and live never share a counter
# --------------------------------------------------------------------------


def test_synthetic_offers_never_inflate_the_live_counters() -> None:
    material = payload(
        sources=(
            source("registry:greenhouse:live", raw_count=10, retained_count=2),
            source("registry:synthetic:live", provider="synthetic", company="Synthetic Employer",
                   raw_count=60, retained_count=60),
        ),
        offers=(
            offer("job-1"),
            offer("job-2", source_id="ats-2", url="https://boards.greenhouse.io/live/jobs/2"),
            offer("synthetic-1", source_name="synthetic", source_id="synthetic:1", company="Synthetic Employer",
                  url="https://example.org/synthetic/1"),
        ),
    )
    report = compute_coverage(material)
    live = report.metrics["live"]
    synthetic = report.metrics["synthetic"]
    assert live.offers_post_dedup == 2
    assert live.raw_offers == 10
    assert live.sources_planned == 1
    assert synthetic.offers_post_dedup == 1
    assert synthetic.raw_offers == 60
    assert live.unique_employers == 1
    assert synthetic.unique_employers == 1
    assert report.coherence["ok"] is True


def test_a_synthetic_offer_read_from_a_live_source_stays_synthetic() -> None:
    material = payload(
        sources=(source(raw_count=3, retained_count=3),),
        offers=(
            offer("live-1"),
            offer("synthetic-1", source_name="synthetic", source_id="synthetic:1",
                  url="https://example.org/synthetic/1"),
        ),
    )
    report = compute_coverage(material)
    assert report.metrics["live"].offers_post_dedup == 1
    assert report.metrics["synthetic"].offers_post_dedup == 1


def test_the_bundled_synthetic_dataset_is_measured_apart() -> None:
    metrics = synthetic_fixture_metrics()
    assert metrics.offers_post_dedup == 36
    assert metrics.raw_offers == 36
    assert metrics.sources_planned == 1
    assert metrics.compliant + metrics.to_verify + metrics.non_compliant == metrics.valid_offers


def test_the_synthetic_dataset_never_enters_the_live_bucket() -> None:
    material = synthetic_fixture_payload()
    report = compute_coverage(material)
    assert report.metrics["live"].offers_post_dedup == 0
    assert report.metrics["live"].raw_offers == 0
    assert report.metrics["live"].sources_planned == 0
    assert report.metrics["synthetic"].offers_post_dedup > 0


def test_synthetic_markers_are_detected_on_the_source_identity_only() -> None:
    assert is_synthetic_source("synthetic", "ats-1") is True
    assert is_synthetic_source("demo_feed") is True
    assert is_synthetic_source("greenhouse", "curated:live:ats-1") is False
    # A real employer may look like a marker: the company is never a proof.
    assert is_synthetic_source("greenhouse", "ats-1") is False


def test_offers_without_an_identifiable_source_are_reported_apart() -> None:
    material = payload(
        sources=(source(),),
        offers=(offer(), offer("manual-1", source_name="manual", source_id="", url="")),
    )
    report = compute_coverage(material)
    assert report.metrics["live"].offers_post_dedup == 1
    assert report.metrics["synthetic"].offers_post_dedup == 0
    assert report.unattributed["offers"] == 1


# --------------------------------------------------------------------------
# Source health
# --------------------------------------------------------------------------


def test_the_source_sums_are_coherent() -> None:
    material = payload(
        sources=(
            source("registry:greenhouse:ok", raw_count=4, retained_count=2),
            source("registry:greenhouse:empty", company="Empty Employer", raw_count=3, retained_count=0),
            source("registry:greenhouse:down", company="Down Employer", status="error", error_code="timeout"),
            source("registry:greenhouse:cached", company="Cached Employer", status="cached", raw_count=2, retained_count=1),
            source("registry:greenhouse:skipped", company="Skipped Employer", status="not_queried"),
        ),
    )
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.sources_planned == 5
    assert metrics.sources_queried == 4
    assert metrics.sources_succeeded == 1
    assert metrics.sources_cached == 1
    assert metrics.sources_failed == 2
    assert metrics.sources_succeeded + metrics.sources_cached + metrics.sources_failed == metrics.sources_queried
    assert metrics.sources_queried <= metrics.sources_planned


def test_a_source_that_answers_without_a_valid_offer_is_not_a_success() -> None:
    material = payload(sources=(source(status="success", raw_count=5, retained_count=0),))
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.sources_queried == 1
    assert metrics.sources_succeeded == 0
    assert metrics.sources_failed == 1


def test_a_partial_source_with_offers_is_a_success() -> None:
    material = payload(sources=(source(status="partial", raw_count=5, retained_count=1),))
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.sources_succeeded == 1
    assert metrics.sources_failed == 0


def test_an_unsupported_source_is_planned_but_never_consulted() -> None:
    material = payload(sources=(source(status="unsupported"),))
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.sources_planned == 1
    assert metrics.sources_queried == 0
    assert metrics.sources_failed == 0


def test_a_source_is_never_counted_twice() -> None:
    material = payload(sources=(source(raw_count=4, retained_count=1), source(raw_count=4, retained_count=1)))
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.sources_planned == 1
    assert metrics.raw_offers == 4


# --------------------------------------------------------------------------
# Announcements
# --------------------------------------------------------------------------


def test_duplicates_are_removed_after_deduplication() -> None:
    material = payload(
        sources=(source(raw_count=2, retained_count=2),),
        offers=(
            offer("job-1", url="https://boards.greenhouse.io/live/jobs/1"),
            offer("job-2", source_id="ats-2", url="https://boards.greenhouse.io/live/jobs/1?utm_source=newsletter"),
        ),
    )
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.offers_pre_dedup == 2
    assert metrics.offers_post_dedup == 1
    assert metrics.valid_offers == 1
    assert metrics.compliant == 1


def test_the_offer_facts_are_counted_once_per_announcement() -> None:
    material = payload(
        sources=(source(raw_count=3, retained_count=3),),
        offers=(
            offer("job-1"),
            offer("job-2", source_id="ats-2", url="https://boards.greenhouse.io/live/jobs/2",
                  city="", country="", posted_date="", start_date="", duration_months=None,
                  requirements="", verification_status="unverified", target_status="to_verify"),
            offer("job-3", source_id="ats-3", url="https://boards.greenhouse.io/live/jobs/3",
                  company="Second Employer", target_status="non_conforming"),
        ),
    )
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.offers_post_dedup == 3
    assert metrics.unique_employers == 2
    assert metrics.valid_offers == 3
    assert metrics.compliant == 1
    assert metrics.to_verify == 1
    assert metrics.non_compliant == 1
    assert metrics.compliant + metrics.to_verify + metrics.non_compliant == metrics.valid_offers
    assert metrics.offers_verified_url == 2
    assert metrics.offers_with_location == 2
    assert metrics.offers_with_published_date == 2
    assert metrics.offers_with_start_date == 2
    assert metrics.offers_with_duration == 2
    assert metrics.offers_with_requirements == 2


def test_an_offer_without_a_recorded_verdict_is_not_a_valid_offer() -> None:
    material = payload(
        sources=(source(raw_count=1, retained_count=1),),
        offers=(offer(target_status="", verification_status=""),),
    )
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.valid_offers == 0
    assert metrics.compliant + metrics.to_verify + metrics.non_compliant == 0
    assert metrics.raw_offers >= metrics.valid_offers


def test_a_verified_offer_needs_a_usable_official_url() -> None:
    material = payload(
        sources=(source(raw_count=2, retained_count=2),),
        offers=(
            offer("job-1", url=""),
            offer("job-2", source_id="ats-2", url="https://boards.greenhouse.io/live/jobs/2"),
        ),
    )
    metrics = compute_coverage(material).metrics["live"]
    assert metrics.offers_verified_url == 1


# --------------------------------------------------------------------------
# Coherence net
# --------------------------------------------------------------------------


def test_a_broken_measurement_is_reported() -> None:
    broken = CoverageMetrics(sources_planned=1, sources_queried=3, sources_succeeded=1)
    violations = _coherence_violations(
        {"synthetic": CoverageMetrics(), "live": broken},
        {"synthetic": (), "live": ()},
        0,
        0,
    )
    assert violations
    assert any("succès" in violation for violation in violations)
    assert any("prévues" in violation for violation in violations)


def test_a_healthy_measurement_reports_no_violation() -> None:
    material = payload(sources=(source(raw_count=2, retained_count=2),), offers=(offer(),))
    report = compute_coverage(material)
    assert report.coherence == {"ok": True, "violations": []}


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


class FakeLoader:
    def __init__(self, material: CoveragePayload) -> None:
        self.material = material
        self.requested: list[str] = []

    def load(self, run_id: str) -> CoveragePayload:
        self.requested.append(run_id)
        if run_id != self.material.run_id:
            raise CoverageRunNotFound("parcours inconnu")
        return self.material


def test_compute_metrics_binds_the_run_to_the_loader() -> None:
    loader = FakeLoader(payload(run_id="explore_abc", sources=(source(),), offers=(offer(),)))
    report = compute_metrics("explore_abc", loader=loader)
    assert loader.requested == ["explore_abc"]
    assert report.run_id == "explore_abc"
    assert report.metrics["live"].offers_post_dedup == 1


def test_compute_metrics_needs_a_run_id() -> None:
    with pytest.raises(CoverageRunNotFound):
        compute_metrics("", loader=FakeLoader(payload()))


def test_compute_metrics_reports_an_unknown_run() -> None:
    with pytest.raises(CoverageRunNotFound):
        compute_metrics("explore_missing", loader=FakeLoader(payload(run_id="explore_abc")))


def test_a_missing_database_is_reported_clearly(tmp_path) -> None:
    loader = CareerDatabaseLoader.from_base_dir(tmp_path)
    with pytest.raises(CoverageRunNotFound):
        loader.load("explore_abc")


# --------------------------------------------------------------------------
# Local Career database
# --------------------------------------------------------------------------


def _qualification() -> dict[str, object]:
    return {
        "contract_type": "internship",
        "contract_status": "confirmed",
        "posted_date": "2026-10-01",
        "start_date": "2027-01-05",
        "start_month": 1,
        "duration_min_months": 6,
        "duration_max_months": 6,
        "country": "France",
        "city": "Paris",
        "geography_status": "allowed",
        "source_name": "greenhouse",
        "source_id": "ats-1",
        "official_url": "https://boards.greenhouse.io/live/jobs/1",
        "verification_status": "verified",
        "target_status": "conforming",
    }


def _seed_run(service: CareerService, run_id: str = "explore_local") -> str:
    job = service.import_job(
        {
            "company": "Live Employer",
            "title": "Stage - Finance",
            "source_name": "greenhouse",
            "source_id": "ats-1",
            "official_url": "https://boards.greenhouse.io/live/jobs/1?utm_source=newsletter",
            "city": "Paris",
            "country": "France",
            "posted_date": "2026-10-01",
            "start_date": "2027-01-05",
            "duration_months": 6,
            "requirements": "Excel",
            "source_status": "open",
            "description_original": "Stage de six mois au sein d'une équipe finance.",
            "qualification": _qualification(),
        }
    )
    snapshot = {
        "run_id": run_id,
        "started_at": "2026-10-20T09:59:00+00:00",
        "finished_at": "2026-10-20T10:00:00+00:00",
        "brief_fingerprint": "fingerprint",
        "outcomes": [
            {"source_id": "registry:greenhouse:live", "provider": "greenhouse", "company": "Live Employer",
             "status": "success", "attempted": True, "raw_count": 4, "evaluated_count": 4, "invalid_count": 0,
             "confirmed_count": 2, "uncertain_count": 0, "excluded_count": 2, "relevant_count": 2,
             "filtered_criteria_count": 0, "retained_count": 1},
            {"source_id": "registry:greenhouse:empty", "provider": "greenhouse", "company": "Empty Employer",
             "status": "success", "attempted": True, "raw_count": 3, "evaluated_count": 3, "invalid_count": 0,
             "confirmed_count": 0, "uncertain_count": 0, "excluded_count": 3, "relevant_count": 0,
             "filtered_criteria_count": 0, "retained_count": 0},
            {"source_id": "registry:greenhouse:down", "provider": "greenhouse", "company": "Down Employer",
             "status": "error", "attempted": True, "error_code": "timeout"},
            {"source_id": "registry:greenhouse:skipped", "provider": "greenhouse", "company": "Skipped Employer",
             "status": "not_queried"},
        ],
        "summary": {"sources_total": 4, "sources_attempted": 3, "sources_succeeded": 1, "retained_count": 1},
        "match_refs": [
            {"job_id": job["id"], "source_id": "registry:greenhouse:live", "verified_at": "2026-10-20T10:00:00+00:00"}
        ],
    }
    with service._connection() as connection:
        connection.execute(
            "INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?) "
            "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
            ("stage_explorer_last_result", json.dumps(snapshot, ensure_ascii=False)),
        )
    return job["id"]


def test_the_database_loader_measures_the_last_run(tmp_path) -> None:
    service = CareerService(tmp_path)
    _seed_run(service)
    loader = CareerDatabaseLoader.from_base_dir(tmp_path)
    report = compute_metrics("explore_local", loader=loader)

    assert report.run_id == "explore_local"
    assert report.computed_at == "2026-10-20T10:00:00+00:00"
    live = report.metrics["live"]
    assert live.sources_planned == 4
    assert live.sources_queried == 3
    assert live.sources_succeeded == 1
    assert live.sources_failed == 2
    assert live.raw_offers == 7
    assert live.offers_post_dedup == 1
    assert live.valid_offers == 1
    assert live.compliant == 1
    assert live.offers_verified_url == 1
    assert live.offers_with_location == 1
    assert live.offers_with_published_date == 1
    assert live.offers_with_start_date == 1
    assert live.offers_with_duration == 1
    assert live.offers_with_requirements == 1
    assert report.metrics["synthetic"].offers_post_dedup == 0
    assert report.coherence["ok"] is True


def test_the_database_loader_refuses_an_unknown_run(tmp_path) -> None:
    service = CareerService(tmp_path)
    _seed_run(service)
    loader = CareerDatabaseLoader.from_base_dir(tmp_path)
    with pytest.raises(CoverageRunNotFound):
        loader.load("explore_other")


def test_the_database_loader_reports_a_database_without_run(tmp_path) -> None:
    CareerService(tmp_path)
    loader = CareerDatabaseLoader.from_base_dir(tmp_path)
    with pytest.raises(CoverageRunNotFound):
        loader.load("explore_local")


def test_a_deleted_offer_does_not_break_the_measurement(tmp_path) -> None:
    service = CareerService(tmp_path)
    job_id = _seed_run(service)
    with service._connection() as connection:
        connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    report = compute_metrics("explore_local", loader=CareerDatabaseLoader.from_base_dir(tmp_path))
    assert report.metrics["live"].offers_post_dedup == 0
    assert report.metrics["live"].sources_planned == 4
    assert report.coherence["ok"] is True
