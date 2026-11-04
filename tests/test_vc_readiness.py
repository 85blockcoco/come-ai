from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from academics.vc.api import create_vc_router
from academics.vc.storage import VcStore


def test_readiness_is_conservative_and_exposes_priorities(tmp_path) -> None:
    store = VcStore(tmp_path)
    app = FastAPI()
    app.include_router(create_vc_router(store=store, tutor=object()))

    response = TestClient(app).get("/api/vc/readiness")
    assert response.status_code == 200
    payload = response.json()
    readiness = payload["readiness"]
    assert payload["source"] == "deterministic"
    assert readiness["score"] == 0.0
    assert readiness["ready"] is False
    assert readiness["official_paper_questions"] == 67
    assert readiness["graded_cases"] == 16
    assert readiness["priority_topics"]
    assert readiness["priority_topics"][0]["status"] == "untested"

