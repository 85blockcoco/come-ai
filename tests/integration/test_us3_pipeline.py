from pathlib import Path

from fastapi.testclient import TestClient

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
            "deadline_date": "2027-01-15",
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
    assert item["stage_label"] == "Kit et suivi créés"
    assert item["next_action_code"] == "review_kit"
    assert item["progress_percent"] == 85
    assert item["kit_ready"] is True
    assert item["deadline_date"] == "2027-01-15"
    assert payload["focus_plan"]["budget_minutes"] == 60
    assert payload["focus_plan"]["automatic_submission"] is False
    assert payload["focus_plan"]["items"][0]["job_id"] == job["id"]


def test_pipeline_keeps_an_early_tracker_as_an_incomplete_local_cycle(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    job = service.import_job(
        {
            "company": "Synthetic Bank",
            "title": "Finance Intern",
            "official_url": "https://careers.example.test/early-tracker",
            "source_status": "open",
        }
    )
    application = service.create_application(job["id"])

    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.get("/api/career/application-pipeline")

    assert response.status_code == 200
    item = next(row for row in response.json()["pipeline"] if row["job_id"] == job["id"])
    assert item["application_id"] == application["id"]
    assert item["stage"] != "tracking_created"
    assert item["tracking_exists"] is True
    assert item["kit_ready"] is False
    assert item["next_action_code"] == "create_kit"


def test_pipeline_frontend_contract_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    html = (root / "career_static" / "index.html").read_text(encoding="utf-8")
    js = (root / "career_static" / "career.js").read_text(encoding="utf-8")
    assert 'id="stagehunter-pipeline"' in html
    assert "/api/career/application-pipeline" in js
    assert "renderApplicationPipeline" in js
    assert "Créer le suivi" in js
    assert "Prochaine action" in js
    assert "pipeline-progress" in js
    assert "stage_label" in js
    assert "Plan de travail local" in js
    assert "focus_plan" in js
    assert "estimated_minutes" in js
    assert "deadline_status" in js
    assert "échéances proches" in js
