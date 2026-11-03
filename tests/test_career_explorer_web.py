"""Actual public HTTP interfaces, using an isolated synthetic source registry."""
from pathlib import Path

from fastapi.testclient import TestClient

from career.discovery import GreenhouseJobBoardConnector
from career.service import CareerService
from come_ai_web import create_app


SYNTHETIC_SOURCE = {
    "id": "registry:greenhouse:synthetic-explorer", "provider": "greenhouse",
    "company": "Banque fictive", "board_token": "synthetic-explorer",
    "public_url": "https://boards.greenhouse.io/synthetic-explorer",
    "provenance_url": "https://careers.example.test/synthetic", "verified_at": "2026-10-13T22:00:00Z",
}


class SyntheticTransport:
    def __init__(self):
        self.calls = 0

    def get_json(self, endpoint, timeout_seconds):
        self.calls += 1
        assert endpoint.startswith("https://boards-api.greenhouse.io/")
        return {"jobs": [
            {"id": "stage", "title": "Corporate Finance Intern", "location": {"name": "London, United Kingdom"},
             "absolute_url": "https://careers.example.test/stage",
             "content": "<p>Stage synthétique en corporate finance.</p><h3>Requirements</h3><p>Excel required.</p>"},
            {"id": "senior", "title": "Senior Corporate Finance Director", "location": {"name": "London, United Kingdom"},
             "absolute_url": "https://careers.example.test/senior", "content": "<p>Permanent position, CDI.</p>"},
        ]}


def test_zero_personal_boards_http_explore_prepare_track_and_cache(tmp_path: Path) -> None:
    transport = SyntheticTransport()
    service = CareerService(tmp_path, curated_sources=(SYNTHETIC_SOURCE,),
        exploration_connectors={"greenhouse": GreenhouseJobBoardConnector(transport)})
    app = create_app(base_dir=tmp_path, career_override=service)
    with TestClient(app) as client:
        assert client.get("/api/career/discovery-sources").json()["sources"] == []
        assert "Explorer les stages" in client.get("/career").text
        assert client.get("/api/career/stage-search/explore").status_code == 200
        assert transport.calls == 0, "opening the UI never fetches a source"
        assert client.put("/api/career/stage-search", json={"domains":["Corporate Finance"], "cities":["London"]}).status_code == 200
        response = client.post("/api/career/stage-search/explore", json={"force":False})
        assert response.status_code == 200
        report = response.json()
        assert report["summary"]["sources_attempted"] == 1
        assert report["summary"]["retained_count"] == 1
        assert report["matches"][0]["job"]["title"] == "Corporate Finance Intern"
        assert report["matches"][0]["internship"]["status"] == "confirmed"
        assert report["matches"][0]["stage_match"]["score"] > 0
        job_id = report["matches"][0]["job"]["id"]
        assert client.put("/api/career/profile", json={"skills":"Excel"}).status_code == 200
        prep = client.get(f"/api/career/jobs/{job_id}/prep").json()
        assert prep["matched_elements"]
        application = client.post("/api/career/applications", json={"job_id":job_id})
        assert application.status_code == 201
        application_id = application.json()["id"]
        assert client.patch(f"/api/career/applications/{application_id}", json={"stage":"to_prepare", "note":"Fixture note"}).status_code == 200
        refusal = client.patch(f"/api/career/applications/{application_id}", json={"stage":"submitted"})
        assert refusal.status_code == 400
        cached = client.post("/api/career/stage-search/explore", json={"force":False}).json()
        assert cached["summary"]["sources_cached"] == 1
        assert transport.calls == 1
        assert client.get("/api/career/discovery-sources").json()["sources"] == []
        assert client.get(f"/api/career/applications/{application_id}").json()["stage"] == "to_prepare"


def test_full_career_http_journey_explore_to_persisted_manual_kit(tmp_path: Path) -> None:
    """Exercise the user-facing internship path over HTTP with synthetic data only."""
    transport = SyntheticTransport()
    service = CareerService(
        tmp_path,
        curated_sources=(SYNTHETIC_SOURCE,),
        exploration_connectors={"greenhouse": GreenhouseJobBoardConnector(transport)},
    )
    app = create_app(base_dir=tmp_path, career_override=service)

    with TestClient(app) as client:
        criteria = client.put(
            "/api/career/stage-search",
            json={"domains": ["Corporate Finance"], "cities": ["London"]},
        )
        assert criteria.status_code == 200
        report = client.post("/api/career/stage-search/explore", json={"force": False}).json()
        match = report["matches"][0]
        job_id = match["job"]["id"]
        assert match["job"]["title"] == "Corporate Finance Intern"
        assert match["internship"]["status"] == "confirmed"

        profile = client.put(
            "/api/career/profile",
            json={
                "display_name": "Synthetic Candidate",
                "education": "MSc Finance",
                "experience": "Built a financial model for a synthetic case study.",
                "skills": "Excel, valuation",
            },
        )
        assert profile.status_code == 200
        prep = client.get(f"/api/career/jobs/{job_id}/prep").json()
        assert prep["recommended_variant"] == "corporate_finance"

        kit = client.post(
            "/api/career/application-kits",
            json={"job_id": job_id, "language": "en", "variant": "corporate_finance"},
        )
        assert kit.status_code == 200
        payload = kit.json()
        assert payload["automatic_submission"] is False
        assert payload["draft"]["variant"] == "corporate_finance"
        assert payload["draft"]["language"] == "en"

        pipeline = client.get("/api/career/application-pipeline")
        assert pipeline.status_code == 200
        item = next(row for row in pipeline.json()["pipeline"] if row["job_id"] == job_id)
        assert item["stage"] == "tracking_created"
        assert item["tracking_stage"] == "to_review"
        assert item["next_action_code"] == "review_kit"
        assert item["source_trust_status"] == "to_verify"
        assert pipeline.json()["automatic_submission"] is False

        # Data survives a fresh service instance and no submission route was invoked.
        reloaded = CareerService(tmp_path, curated_sources=())
        persisted = reloaded.get_application_pipeline()
        saved = next(row for row in persisted["pipeline"] if row["job_id"] == job_id)
        assert saved["stage"] == "tracking_created"
        assert saved["variant"] == "corporate_finance"
        assert transport.calls == 1


def test_job_summary_endpoint_returns_local_summary(tmp_path: Path) -> None:
    transport = SyntheticTransport()
    service = CareerService(tmp_path, curated_sources=(SYNTHETIC_SOURCE,),
        exploration_connectors={"greenhouse": GreenhouseJobBoardConnector(transport)})
    app = create_app(base_dir=tmp_path, career_override=service)
    with TestClient(app) as client:
        assert client.put("/api/career/stage-search", json={"domains":["Corporate Finance"], "cities":["London"]}).status_code == 200
        report = client.post("/api/career/stage-search/explore", json={"force":False}).json()
        job_id = report["matches"][0]["job"]["id"]
        response = client.get(f"/api/career/jobs/{job_id}/summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["job_id"] == job_id
        assert payload["title"] == "Corporate Finance Intern"
        assert payload["mode"] == "local"
        assert payload["ai_used"] is False
        post_response = client.post(f"/api/career/jobs/{job_id}/summary", json={"mode":"local"})
        assert post_response.status_code == 200
        assert post_response.json()["job_id"] == job_id


def test_exploration_api_rejects_unknown_payload_types(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.post("/api/career/stage-search/explore", json={"force":{"arbitrary":"data"}})
        assert response.status_code == 422
