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


def test_rank_orders_unknown_deadline_last(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/career/offers/rank", json={"today": "2026-11-01", "offers": [
            {"id": "unknown", "deadline": ""}, {"id": "urgent", "deadline": "2026-11-02"},
        ]})
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["ordered"]] == ["urgent", "unknown"]


def test_shortlist_text_dashboard(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.get("/api/career/shortlist?fmt=text")
        assert response.status_code == 200
        assert "SHORTLIST" in response.json()["text"]


def test_shortlist_export_uses_server_target(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/career/shortlist/export", json={"fmt": "json", "target": "/tmp/should-not-use.json", "offers": [{"id": "synthetic"}]})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["path"].endswith("career_data/exports/shortlist.json")


def test_shortlist_export_empty_is_refused(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/career/shortlist/export", json={"fmt": "csv", "offers": []})
        assert response.status_code == 200
        assert response.json()["blockers"]
