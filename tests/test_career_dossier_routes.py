from pathlib import Path

from fastapi.testclient import TestClient

from career.service import CareerService
from come_ai_web import create_app


class FakeAgent:
    def chat(self, message: str, **kwargs):
        return {"answer": "", "provider": "offline", "model": "fake", "tool_events": [], "citations": [], "usage": {}}


def client(tmp_path: Path) -> TestClient:
    service = CareerService(tmp_path)
    return TestClient(create_app(tmp_path, agent_override=FakeAgent(), career_override=service))


def test_ats_fields_prefill_profile_and_report_missing(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        http.put("/api/career/profile", json={"display_name": "Synthetic Candidate", "contact_email": "candidate@example.test"})
        response = http.get("/api/career/ats/fields?platform=greenhouse")
        assert response.status_code == 200
        fields = {field["name"]: field for field in response.json()["fields"]}
        assert fields["full_name"]["value"] == "Synthetic Candidate"
        assert response.json()["blockers"]


def test_dossier_checklist_complete_required_documents(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/career/dossier/checklist", json={"dossier": "stage", "provided": ["cv", "lettre_motivation"]})
        assert response.status_code == 200
        assert response.json()["completeness"]["ok"] is True
        assert response.json()["blockers"] == []


def test_dossier_checklist_missing_required_is_blocked(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/career/dossier/checklist", json={"dossier": "banque", "provided": ["cv"]})
        assert response.status_code == 200
        assert response.json()["completeness"]["ok"] is False
        assert response.json()["blockers"]


def test_dossier_preview_is_read_only_and_warns_on_missing(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/career/dossier/preview", json={
            "dossier_id": "synthetic-001",
            "documents": [["cv", "present"], ["letter", "missing"]],
            "stage_summary": "Synthetic finance internship",
        })
        assert response.status_code == 200
        payload = response.json()
        assert payload["document_count"] == 2
        assert payload["warnings"]
        assert "send" not in payload
