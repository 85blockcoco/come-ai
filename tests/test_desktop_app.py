"""HTTP startup contract for the desktop shell, without a real provider."""

from fastapi.testclient import TestClient

from come_ai_web import create_app


class FakeAgent:
    def provider_status(self):
        return {"provider": "synthetic", "available": False}


def test_desktop_shell_and_assets_are_served_with_local_protections(tmp_path, monkeypatch):
    monkeypatch.setenv("COME_AI_MEMORY_DIR", str(tmp_path / "memory_data"))
    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        page = client.get("/app")
        assert page.status_code == 200
        assert 'lang="fr"' in page.text
        assert "Navigation principale" in page.text
        assert 'id="themeSelect"' in page.text
        assert '<option value="terminal">NAGE Terminal</option>' in page.text
        assert '<option value="studio">NAGE Studio</option>' in page.text
        assert "/app-static/app.js" in page.text
        assert "content-security-policy" in page.headers
        for asset in ("app.js", "app.css", "icon.png"):
            assert client.get("/app-static/" + asset).status_code == 200
        script = client.get("/app-static/app.js").text
        stylesheet = client.get("/app-static/app.css").text
        assert 'const THEME_STORAGE_KEY = "nage-app-theme"' in script
        assert 'body[data-theme="studio"]' in stylesheet
        assert client.get("/app", headers={"Host": "attacker.example.test"}).status_code == 400


def test_desktop_missions_endpoint_is_read_only_when_registry_is_absent(tmp_path, monkeypatch):
    import come_ai_web

    static = tmp_path / "desktop_static"
    static.mkdir()
    monkeypatch.setattr(come_ai_web, "DESKTOP_STATIC_DIR", static)
    monkeypatch.setenv("COME_AI_MEMORY_DIR", str(tmp_path / "memory_data"))
    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        payload = client.get("/api/app/missions").json()
        assert payload["available"] is False
        assert payload["workers"] is None
        assert not (tmp_path / "missions_registry.json").exists()
