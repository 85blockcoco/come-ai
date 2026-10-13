"""Local workshop integration with fictitious configuration and no remote calls."""
from fastapi.testclient import TestClient
from come_ai_web import create_app


def test_evolution_backlog_settings_persist_and_offline_forces_local_provider(tmp_path):
    (tmp_path / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    app = create_app(tmp_path)
    try:
        with TestClient(app) as client:
            status = client.get("/api/devkit/status").json()
            headers = {"X-Workshop-Token": status["workshop_token"]}
            initial = client.get("/api/devkit/evolution")
            assert initial.status_code == 200
            assert initial.json()["settings"]["model"] == "auto"
            assert initial.json()["provider"]["configured"] is False
            assert client.post("/api/devkit/evolution/settings", json={"provider": "gemini", "model": "auto"}).status_code == 403
            settings = client.post("/api/devkit/evolution/settings", json={"provider": "gemini", "model": "auto", "mode": "offline", "allow_remote": True}, headers=headers)
            assert settings.status_code == 200
            assert settings.json()["provider"] == "ollama"
            assert settings.json()["allow_remote"] is False
            task = client.post("/api/devkit/evolution/tasks", json={"title": "Fixture", "description": "Corriger valeur", "selected_files": ["core.py"]}, headers=headers)
            assert task.status_code == 200
            second = client.get("/api/devkit/evolution").json()
            assert second["tasks"][0]["task_id"] == task.json()["task_id"]
            assert second["mode"] == "offline"
            assert second["automatic_deployment"] is False
            assert second["scheduling"] is False
            assert str(tmp_path) not in client.get("/api/devkit/evolution").text
            performance = client.post("/api/devkit/evolution/settings", json={"provider": "gemini", "model": "auto", "mode": "performance"}, headers=headers).json()
            assert performance["max_output_tokens"] == 6000
            assert performance["timeout_seconds"] == 60
    finally:
        app.state.runtime.task_runner.stop(wait=True, timeout=1)
