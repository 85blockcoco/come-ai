from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from academics.vc.api import create_vc_router
from academics.vc.storage import VcStore


def _client(tmp_path) -> tuple[TestClient, VcStore]:
    store = VcStore(tmp_path)
    app = FastAPI()
    app.include_router(create_vc_router(store=store, tutor=object()))
    return TestClient(app), store


def test_case_list_and_detail_keep_solutions_hidden(tmp_path) -> None:
    http, _store = _client(tmp_path)
    response = http.get("/api/vc/cases")
    assert response.status_code == 200
    cases = response.json()["cases"]
    assert len(cases) == 4
    assert all("model_answer" not in case for case in cases)
    assert all(case["questions"] for case in cases)


def test_case_grade_returns_criterion_feedback_and_persists_attempt(tmp_path) -> None:
    http, store = _client(tmp_path)
    response = http.post(
        "/api/vc/cases/VC03-CASE01/grade",
        json={
            "answers": {
                "q1": "Post-money 10 M€, investor 20%.",
                "q2": "2 million new shares.",
                "q3": "The runway shortens and a bridge may dilute further.",
            }
        },
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert response.json()["source"] == "deterministic"
    assert result["score"] == 1.0
    assert result["criteria"]
    assert result["model_answer"].startswith("Post-money 10 M€")
    assert "not a human grade" in result["notice"].lower()
    assert len(store.load_case_attempts()) == 1


def test_case_grade_rejects_unknown_case_or_question(tmp_path) -> None:
    http, _store = _client(tmp_path)
    missing_case = http.post("/api/vc/cases/no-such-case/grade", json={"answers": {}})
    unknown_question = http.post("/api/vc/cases/VC03-CASE01/grade", json={"answers": {"made-up": "answer"}})
    assert missing_case.status_code == 404
    assert unknown_question.status_code == 400
