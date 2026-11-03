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


def test_letter_render_check_personalize_and_approve(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        rendered = http.post("/api/career/letter/render", json={"role": "Finance Intern", "company": "Acme", "language": "en"})
        assert rendered.status_code == 200
        body = rendered.json()["body"]
        assert "Finance Intern" in body
        checked = http.post("/api/career/letter/check", json={"letter_body": body, "evidence": []})
        assert checked.status_code == 200
        assert "warnings" in checked.json() and "blockers" in checked.json()
        personalized = http.post("/api/career/letter/personalize", json={"body": body, "company": "Acme", "company_facts": ["has a finance team"]})
        assert personalized.status_code == 200
        approved = http.post("/api/career/letter/approve", json={"letter_id": "synthetic-1", "approved": True})
        assert approved.status_code == 200
        assert approved.json()["approved"] is True


def test_letter_export_refuses_unapproved_binary(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/career/letter/export", json={"letter_body": "Dear Sir or Madam,\n\nCordialement,\nName", "title": "synthetic", "fmt": "pdf", "target": str(tmp_path / "out.pdf")})
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["blockers"]


def test_client_approved_flag_cannot_bypass_server_gate(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/career/letter/export", json={
            "letter_body": "Synthetic letter",
            "title": "not-approved",
            "fmt": "md",
            "target": "/tmp/client-controlled.md",
            "approved": True,
        })
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert not (tmp_path / "client-controlled.md").exists()


def test_approved_letter_exports_only_under_server_directory(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        assert http.post("/api/career/letter/approve", json={"letter_id": "approved-letter", "approved": True}).status_code == 200
        response = http.post("/api/career/letter/export", json={
            "letter_body": "Synthetic approved letter",
            "title": "approved-letter",
            "fmt": "md",
            "target": "/tmp/client-controlled.md",
            "approved": True,
        })
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["path"].endswith("career_data/exports/approved-letter.md")
