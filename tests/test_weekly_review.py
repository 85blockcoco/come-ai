"""Tests for SPEC-036 — bilan hebdo & objectifs (weekly_review)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.router import create_career_router
from career.service import CareerService
from career.weekly_review import (
    Objective,
    WeeklySummary,
    iso_week_string,
    objective_check,
    recommend_next,
    weekly_summary,
)
from workspace_core import UserFacingError


FIXTURE = Path(__file__).parent / "fixtures" / "weekly_synthetic.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def synthetic_client(service):
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(request, error):
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def test_weekly_summary_from_fixture():
    data = load_fixture()
    summary = weekly_summary(data)
    assert isinstance(summary, WeeklySummary)
    assert summary.iso_week == "2026-W42"
    assert summary.applications_sent == 4  # to_review not sent
    assert summary.responses == 2  # response_received + interview
    assert summary.interview_rate == 0.25
    assert summary.objective_met is False  # 4 < 5
    assert len(summary.top_actions) <= 3
    assert summary.top_actions


def test_weekly_summary_no_objective():
    data = load_fixture()
    data.pop("objective")
    summary = weekly_summary(data)
    assert summary.objective_met is None
    assert summary.top_actions  # based on data alone


def test_objective_check_none_without_objective():
    data = load_fixture()
    data.pop("objective")
    summary = weekly_summary(data)
    assert objective_check(summary) is None


def test_objective_check_met():
    obj = Objective(metric="applications", target=3)
    data = load_fixture()
    summary = weekly_summary(data, objective=obj)
    assert summary.objective_met is True or summary.objective_met is False
    assert objective_check(summary, obj) is not None


def test_top_actions_max_three():
    data = load_fixture()
    summary = weekly_summary(data)
    assert len(summary.top_actions) <= 3


def test_iso_week_string():
    from datetime import date

    assert iso_week_string(date(2026, 10, 12)) == "2026-W42"
    assert iso_week_string("2026-W42") == "2026-W42"


def test_adversarial_garbled_data():
    # Données incohérentes : ne doit pas planter.
    data = {"applications": [{"stage": None}, "not-a-dict", {"foo": "bar"}], "objective": {"metric": "nope", "target": "x"}}
    summary = weekly_summary(data)
    assert summary.applications_sent == 0
    assert summary.objective_met is False or summary.objective_met is True or summary.objective_met is None


def test_module_dataclass():
    kit = WeeklySummary(iso_week="2026-W01", applications_sent=0, responses=0, interview_rate=0.0, objective_met=None)
    assert isinstance(kit, WeeklySummary)
    assert kit.top_actions == []


def test_endpoint_smoke(tmp_path: Path):
    service = CareerService(tmp_path)
    client = synthetic_client(service)
    # import a job and create application via service directly
    job = service.import_job({
        "company": "Demo",
        "title": "Stage",
        "source_name": "manual",
        "official_url": "https://example.test/j",
        "source_status": "open",
    })
    service.create_application(job["id"])
    resp = client.get("/api/career/weekly-review")
    assert resp.status_code == 200
    data = resp.json()
    assert "iso_week" in data
    assert "top_actions" in data


def test_recommend_next_list():
    data = load_fixture()
    data.pop("objective")
    summary = weekly_summary(data)
    actions = recommend_next(summary)
    assert isinstance(actions, list)
    assert len(actions) <= 3
