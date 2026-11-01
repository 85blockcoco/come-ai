from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from career.service import CareerService
from come_ai_web import create_app


class FakeAgent:
    def chat(self, message: str, **kwargs):
        return {"answer": "", "provider": "offline", "model": "fake", "tool_events": [], "citations": [], "usage": {}}


def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path, agent_override=FakeAgent(), career_override=CareerService(tmp_path)))


def test_finance_and_math_calculations_are_whitelisted(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        finance = http.post("/api/academics/finance/calculate", json={"operation": "future_value", "arguments": {"pv": 100, "rate": 0.1, "periods": 2}})
        assert finance.status_code == 200
        assert finance.json()["result"] == pytest.approx(121.0)
        math = http.post("/api/academics/math/calculate", json={"operation": "mean", "arguments": {"values": [1, 2, 3]}})
        assert math.json()["result"] == 2.0


def test_arbitrary_function_dispatch_is_refused(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/academics/finance/calculate", json={"operation": "__import__", "arguments": {}})
        assert response.status_code == 200
        assert response.json()["result"] is None
        assert response.json()["blockers"]


def test_daily_plan_is_bounded_and_serializable(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/academics/daily/plan", json={"minutes_per_day": 60, "today": "2026-11-01", "tasks": [
            {"title": "Devoir NPV", "due": "2026-11-02", "estimate_minutes": 45, "priority": 1},
            {"title": "Révisions", "due": "2026-11-03", "estimate_minutes": 30, "priority": 2},
        ]})
        assert response.status_code == 200
        assert [task["title"] for task in response.json()["plan"]["tasks"]] == ["Devoir NPV"]


def test_research_outline_never_fills_missing_section(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/academics/research/outline", json={"topic": "Finance", "sections": ["Introduction", ""], "facts": []})
        assert response.status_code == 200
        payload = response.json()
        assert payload["outline"]["sections"][1]["placeholder"] is True
        assert payload["blockers"]
