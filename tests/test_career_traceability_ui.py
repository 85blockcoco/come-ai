"""Static and HTTP contract for the NAGE Career traceability surface."""

from fastapi.testclient import TestClient

from come_ai_web import create_app


class FakeAgent:
    def provider_status(self):
        return {"provider": "synthetic", "available": False}


def test_traceability_ui_assets_and_controls_are_connected(tmp_path, monkeypatch):
    monkeypatch.setenv("COME_AI_MEMORY_DIR", str(tmp_path / "memory_data"))
    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        page = client.get("/career")
        assert page.status_code == 200
        assert 'id="traceability-detail-panel"' in page.text
        assert 'id="traceability-detail-title"' in page.text
        assert 'id="traceability-gaps"' in page.text

        stylesheet = client.get("/career-static/traceability.css")
        constitution_stylesheet = client.get("/career-static/constitution.css")
        script = client.get("/career-static/js/traceability.js")
        assert stylesheet.status_code == 200
        assert stylesheet.headers["content-type"].startswith("text/css")
        assert ".traceability-row" in stylesheet.text
        assert constitution_stylesheet.status_code == 200
        assert constitution_stylesheet.headers["content-type"].startswith("text/css")
        assert ".constitution-table-wrap" in constitution_stylesheet.text
        assert script.status_code == 200
        assert 'filters.addEventListener("submit"' in script.text
        assert 'exportJson.addEventListener("click"' in script.text
        assert 'selectAll.addEventListener("change"' in script.text
