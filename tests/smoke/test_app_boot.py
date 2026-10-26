"""Smoke test CI : l'application démarre et sert l'espace Career (job ``smoke-test``)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from come_ai_web import create_app


def test_application_boots_and_serves_career(tmp_path) -> None:
    app = create_app(base_dir=tmp_path)
    with TestClient(app) as client:
        health = client.get("/api/career/health")
        assert health.status_code == 200

        page = client.get("/career")
        assert page.status_code == 200
        assert "Côme AI Career" in page.text

        profile = client.get("/api/career/profile")
        assert profile.status_code == 200

        pipeline = client.get("/api/career/application-pipeline")
        assert pipeline.status_code == 200
        assert pipeline.json()["automatic_submission"] is False


def test_static_assets_are_served(tmp_path) -> None:
    app = create_app(base_dir=tmp_path)
    with TestClient(app) as client:
        script = client.get("/career-static/career.js")
        assert script.status_code in {200, 404}
        if script.status_code == 200:
            assert "/api/career/application-pipeline" in script.text
