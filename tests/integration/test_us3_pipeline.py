from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

import career.models as career_models
import career.service as career_service_module
from career.service import CareerService
from come_ai_web import create_app


def test_pipeline_endpoint_tracks_full_local_cycle(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    service.update_profile({"experience": "Automated 500+ files", "skills": "Python Excel"})
    job = service.import_job(
        {
            "company": "Synthetic Bank",
            "title": "Markets Intern",
            "official_url": "https://careers.example.test/pipeline",
            "job_family": "Markets / Quant",
            "requirements": "Python and statistics required.",
            "source_status": "open",
        }
    )
    service.get_job_prep(job["id"])
    service.create_application_kit(job["id"], "en", "markets")

    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.get("/api/career/application-pipeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["automatic_submission"] is False
    item = next(item for item in payload["pipeline"] if item["job_id"] == job["id"])
    assert item["stage"] == "tracking_created"
    assert item["variant"] == "markets"
    assert item["variant_label"] == "Markets / Quant"
    assert item["kit_generated_at"]
    assert item["tracking_stage"] == "to_review"
    assert item["next_action_code"] == "review_kit"
    assert item["source_trust_status"] == "to_verify"
    assert payload["focus_plan"]["automatic_submission"] is False


def test_pipeline_skips_qualification_details_without_changing_stage_status(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    service.update_stage_search(service.get_stage_search()["brief"])
    service.import_job({
        "company": "Synthetic Bank",
        "title": "Finance Intern",
        "official_url": "https://careers.example.test/pipeline-qualification",
        "source_status": "open",
        "employment_type": "Internship",
        "start_date": "2027-01-05",
        "end_date": "2027-07-05",
        "duration_months": 6,
        "country": "United Kingdom",
        "city": "London",
    })

    full = service.list_stage_matches()["matches"][0]
    lightweight = service.list_stage_matches(_include_qualification_details=False)["matches"][0]

    assert lightweight["stage_match"]["qualification_status"] == full["stage_match"]["qualification_status"]
    assert lightweight["qualification"] == {"target_status": full["qualification"]["target_status"]}


def test_pipeline_reuses_the_single_stage_match_job_snapshot(tmp_path: Path, monkeypatch) -> None:
    service = CareerService(tmp_path, curated_sources=())
    service.update_stage_search(service.get_stage_search()["brief"])
    for index in range(5):
        service.import_job(
            {
                "company": f"Synthetic Bank {index}",
                "title": "Finance Intern",
                "official_url": f"https://careers.example.test/pipeline-cache-{index}",
                "source_status": "open",
            }
        )

    calls = 0
    list_jobs = service.list_jobs

    def count_list_jobs(*args, **kwargs):
        nonlocal calls
        calls += 1
        return list_jobs(*args, **kwargs)

    monkeypatch.setattr(service, "list_jobs", count_list_jobs)
    pipeline = service.get_application_pipeline()

    assert calls == 1
    assert len(pipeline["pipeline"]) == 5


def test_pipeline_scopes_short_text_normalization_cache(tmp_path: Path, monkeypatch) -> None:
    service = CareerService(tmp_path, curated_sources=())
    service.update_stage_search(service.get_stage_search()["brief"])
    for index in range(5):
        service.import_job(
            {
                "company": f"Synthetic Bank {index}",
                "title": "Corporate Finance Intern",
                "job_family": "Corporate Finance",
                "official_url": f"https://careers.example.test/pipeline-normalization-{index}",
                "city": "London",
                "country": "United Kingdom",
                "employment_type": "Internship",
                "start_date": "2027-01-04",
                "end_date": "2027-07-04",
                "duration_months": 6,
                "description_original": "Synthetic corporate finance internship.",
                "requirements": "Financial modelling",
                "source_status": "open",
            }
        )

    expected = service.get_application_pipeline()
    counts: Counter[str] = Counter()
    original = career_models._normalize_clean_text

    def count_normalizations(value: str) -> str:
        counts[value] += 1
        return original(value)

    monkeypatch.setattr(career_models, "_normalize_clean_text", count_normalizations)
    actual = service.get_application_pipeline()

    assert actual == expected
    assert counts["corporate finance"] == 1
    # The per-operation cache must be gone after the request; this next call
    # has to normalize the value again instead of retaining profile text.
    career_models.normalized_text("corporate finance")
    assert counts["corporate finance"] == 2


def test_application_pipeline_skips_unused_profile_recommendation_scores(
    tmp_path: Path, monkeypatch
) -> None:
    service = CareerService(tmp_path, curated_sources=())
    service.update_stage_search(service.get_stage_search()["brief"])
    service.import_job(
        {
            "company": "Synthetic Bank",
            "title": "Corporate Finance Intern",
            "job_family": "Corporate Finance",
            "official_url": "https://careers.example.test/pipeline-no-explorer-score",
            "source_status": "open",
        }
    )
    expected = service.get_application_pipeline()

    def unexpected_profile_score(*args, **kwargs):
        raise AssertionError("Pipeline must not calculate Explorer profile recommendation scores")

    monkeypatch.setattr(career_service_module, "score_job", unexpected_profile_score)
    assert service.get_application_pipeline() == expected


def test_pipeline_frontend_contract_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    html = (root / "career_static" / "index.html").read_text(encoding="utf-8")
    js = (root / "career_static" / "career.js").read_text(encoding="utf-8")
    assert 'id="stagehunter-pipeline"' in html
    assert "/api/career/application-pipeline" in js
    assert "renderApplicationPipeline" in js
    assert "Créer le suivi" in js
    assert "focus_plan" in js
    assert "next_action_label" in js
    assert "Tout dépôt reste manuel" in js
    assert "await loadApplicationPipeline();" in js
    assert "focus_plan" in js
    assert "next_action_label" in js
    assert "Tout dépôt reste manuel" in js
