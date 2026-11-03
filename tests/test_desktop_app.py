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
        assert '<option value="studio" selected>Studio professionnel</option>' in page.text
        assert '<option value="terminal">Terminal</option>' in page.text
        assert 'data-view="homework"' in page.text
        assert 'id="view-homework"' in page.text
        assert "Devoirs" in page.text
        assert "/app-static/app.js" in page.text
        assert "content-security-policy" in page.headers
        for asset in ("app.js", "app.css", "icon.png"):
            assert client.get("/app-static/" + asset).status_code == 200
        script = client.get("/app-static/app.js").text
        stylesheet = client.get("/app-static/app.css").text
        assert 'const THEME_STORAGE_KEY = "nage-app-theme-v2"' in script
        assert 'const LANGUAGE_STORAGE_KEY = "nage-kit-language-v1"' in script
        assert 'const DOCUMENT_STORAGE_KEY = "nage-homework-document-v1"' in script
        assert 'return THEMES.has(saved) ? saved : "studio"' in script
        assert 'src: `/career?embed=app#career/${encodeURIComponent(state.careerSection)}`' in script
        assert 'openCareerWorkspace("stagehunter")' in script
        assert 'openCareerWorkspace("profile")' in script
        assert 'const HOMEWORK_ACCEPT = ".pdf,.docx,.pptx,.xlsx,.xlsm,.xls,.csv,.tsv,.txt,.md"' in script
        assert 'await api("/api/files/upload"' in script
        assert 'analyze ? "/api/actions/analyze" : "/api/actions/inspect"' in script
        assert 'selected_file_ids: [file.file_id]' in script
        assert 'allow_cloud_context: false' in script
        assert 'api("/api/study/courses"' in script
        assert '"/api/study/overview"' in script
        assert 'health: async () => (state.health = await api("/api/health"))' in script
        assert "restoreLearningDocument();" in script
        assert "Rechercher un document…" in script
        assert "Parcours créé" in script
        assert "Tuteur conversationnel en pause" in script
        assert "Les outils d’apprentissage restent disponibles." in script
        assert "/api/study/homework/${encodeURIComponent(fileId)}/tasks" in script
        assert "Plan de résolution" in script
        assert "Notes de résolution" in script
        assert "Modèle local configuré" in script
        assert 'languagePicker.hidden = !new Set(["today", "applications", "tracking", "offers", "assistant"]).has(view)' in script
        assert '`${option.id}. ${option.label}`' not in script
        assert "Reprendre ma séance" in script
        assert "/api/study/sessions/${encodeURIComponent(sessionId)}" in script
        assert "Nouvelle séance · 5 questions" in script
        assert "NAGE travaille sur une copie locale et ne modifie jamais l’original." in script
        assert 'target: "_blank"' not in script
        assert "Career ↗" not in page.text
        assert "V5 ↗" not in page.text
        assert "V3 ↗" not in page.text
        assert 'body[data-theme="studio"]' in stylesheet
        assert ".career-embed" in stylesheet
        assert ".homework-layout" in stylesheet
        assert ".homework-drop" in stylesheet
        assert ".study-panel" in stylesheet
        assert ".homework-overview" in stylesheet
        assert ".homework-filter" in stylesheet
        assert ".homework-model-note" in stylesheet
        assert ".homework-task-workspace" in stylesheet
        assert 'window.addEventListener("hashchange"' in script
        assert 'history.pushState(null, "", destination)' in script
        embedded = client.get("/career?embed=app")
        assert embedded.headers["x-frame-options"] == "SAMEORIGIN"
        assert "frame-ancestors 'self'" in embedded.headers["content-security-policy"]
        standalone = client.get("/career")
        assert standalone.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in standalone.headers["content-security-policy"]
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
