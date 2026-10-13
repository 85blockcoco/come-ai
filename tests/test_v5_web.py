"""End-to-end offline tests for the V5 HTTP vertical slice.

These exercise the real queue, orchestrator, local workbook analysis and
SQLite/FTS memory against ``tmp_path``. No model/provider is constructed or
contacted, and no real project data is touched.
"""

from __future__ import annotations

from io import BytesIO
import time
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from come_ai_web import create_app


def wait_for_task(client: TestClient, task_id: str, *, timeout: float = 3.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v5/tasks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.02)
    raise AssertionError("La tâche V5 n’a pas atteint un état terminal.")


def upload(client: TestClient, name: str, content: bytes, content_type: str) -> str:
    response = client.post("/api/files/upload", files=[("files", (name, content, content_type))])
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "importé"
    return result["file_id"]


def test_v5_local_plan_runs_multiple_real_tools_and_creates_confirmed_report(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    try:
        page = client.get("/v5")
        assert page.status_code == 200
        assert "Côme AI 5.0" in page.text
        assert "content-security-policy" in page.headers

        file_id = upload(
            client,
            "budget.csv",
            b"mois;revenus;couts\nJanvier;100;40\nFevrier;130;55\n",
            "text/csv",
        )
        created = client.post(
            "/api/v5/tasks",
            json={
                "message": "Analyse financière en profondeur le fichier sélectionné et crée un rapport.",
                "selected_file_ids": [file_id],
                "allow_write": True,
            },
        )
        assert created.status_code == 200, created.text
        initial = created.json()
        assert [step["tool"] for step in initial["plan"]] == [
            "inspect_file",
            "analyze_table",
            "create_analysis_workbook",
        ]

        finished = wait_for_task(client, initial["task_id"])
        assert finished["status"] == "completed", finished
        result = finished["result"]
        assert result["remote_model_used"] is False
        assert [event["tool"] for event in result["events"]] == [
            "inspect_file",
            "analyze_table",
            "create_analysis_workbook",
        ]
        assert all(event["status"] == "done" for event in result["events"])
        output_name = result["events"][-1]["result"]["output_file"]
        assert (tmp_path / "output" / output_name).is_file()

        health = client.get("/api/v5/overview")
        assert health.status_code == 200
        assert health.json()["task_queue"]["available"] is True
        assert health.json()["memory"]["available"] is True
        assert str(tmp_path) not in health.text
    finally:
        app.state.runtime.task_runner.stop(wait=True, timeout=1.0)  # type: ignore[union-attr]


def test_v5_memory_is_source_cited_and_survives_app_restart(tmp_path: Path) -> None:
    first_app = create_app(tmp_path)
    first_client = TestClient(first_app)
    try:
        file_id = upload(
            first_client,
            "cours-finance.md",
            "# Finance\nLa VAN actualise les flux futurs et aide à comparer des projets.\n".encode(),
            "text/markdown",
        )
        project_response = first_client.post("/api/v5/memory/projects", json={"name": "Révisions finance"})
        assert project_response.status_code == 200, project_response.text
        project_id = project_response.json()["project"]["project_id"]

        indexed = first_client.post(
            "/api/v5/memory/import-file",
            json={"file_id": file_id, "project_id": project_id},
        )
        assert indexed.status_code == 200, indexed.text
        assert indexed.json()["status"] == "indexed"

        before_restart = first_client.get(f"/api/v5/memory/search?q=VAN&project_id={project_id}")
        assert before_restart.status_code == 200
        found = before_restart.json()
        assert found["count"] == 1
        assert found["results"][0]["citation"].startswith("cours-finance.md")
        assert "flux futurs" in found["results"][0]["excerpt"]
    finally:
        first_app.state.runtime.task_runner.stop(wait=True, timeout=1.0)  # type: ignore[union-attr]

    second_app = create_app(tmp_path)
    second_client = TestClient(second_app)
    try:
        after_restart = second_client.get("/api/v5/memory/search?q=VAN")
        assert after_restart.status_code == 200
        assert after_restart.json()["count"] == 1
        sources = second_client.get("/api/v5/memory/sources")
        assert sources.status_code == 200
        assert sources.json()["sources"][0]["title"] == "cours-finance.md"
        assert str(tmp_path) not in sources.text
    finally:
        second_app.state.runtime.task_runner.stop(wait=True, timeout=1.0)  # type: ignore[union-attr]


def test_v5_memory_index_task_is_persistent_source_cited_and_reports_safe_storage(tmp_path: Path) -> None:
    """A real queue job indexes a course without a provider or raw paths."""

    app = create_app(tmp_path)
    client = TestClient(app)
    try:
        file_id = upload(
            client,
            "cours-valuation.md",
            b"# Valorisation\nLa VAN actualise les flux futurs selon un taux approprie.\n",
            "text/markdown",
        )
        created = client.post(
            "/api/v5/memory/index-tasks",
            json={"file_id": file_id, "project_id": None},
        )
        assert created.status_code == 200, created.text
        initial = created.json()
        assert initial["kind"] == "memory_index"
        assert initial["plan"] == [
            {
                "step_id": "memory-index-1",
                "tool": "index_memory",
                "label": "Indexer le document dans la mémoire locale",
                "requires_confirmation": False,
            }
        ]

        finished = wait_for_task(client, initial["task_id"])
        assert finished["status"] == "completed", finished
        result = finished["result"]
        assert result["remote_model_used"] is False
        assert result["status"] == "indexed"
        assert result["source"]["title"] == "cours-valuation.md"
        assert str(tmp_path) not in str(result)

        found = client.get("/api/v5/memory/search?q=VAN")
        assert found.status_code == 200, found.text
        assert found.json()["count"] == 1
        assert found.json()["results"][0]["citation"].startswith("cours-valuation.md")

        storage = client.get("/api/v5/memory/storage")
        assert storage.status_code == 200, storage.text
        snapshot = storage.json()
        assert snapshot["available"] is True
        assert snapshot["storage"]["disk"]["free_bytes"] > 0
        assert snapshot["storage"]["storage"]["file_count"] >= 1
        assert snapshot["indexing"]["active_count"] == 0
        assert str(tmp_path) not in str(snapshot)

        page = client.get("/v5")
        script = client.get("/v5-static/v5.js")
        assert "Mémoire &amp; stockage" in page.text
        assert "/api/v5/memory/index-tasks" in script.text
        assert "/api/v5/memory/storage" in script.text
    finally:
        app.state.runtime.task_runner.stop(wait=True, timeout=1.0)  # type: ignore[union-attr]


def test_v5_memory_index_task_indexes_excel_sheets_without_provider(tmp_path: Path) -> None:
    """Excel knowledge becomes searchable through the same controlled queue."""

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Valorisation"
    sheet.append(["Metric", "Valeur"])
    sheet.append(["EBITDA", 125])
    sheet.append(["WACC", 0.08])
    payload = BytesIO()
    workbook.save(payload)

    app = create_app(tmp_path)
    client = TestClient(app)
    try:
        file_id = upload(
            client,
            "modele-valuation.xlsx",
            payload.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        created = client.post("/api/v5/memory/index-tasks", json={"file_id": file_id})
        assert created.status_code == 200, created.text
        finished = wait_for_task(client, created.json()["task_id"])
        assert finished["status"] == "completed", finished
        assert finished["result"]["remote_model_used"] is False

        found = client.get("/api/v5/memory/search?q=EBITDA")
        assert found.status_code == 200, found.text
        result = found.json()
        assert result["count"] >= 1
        assert result["results"][0]["source_title"] == "modele-valuation.xlsx"
        assert "Valorisation" in result["results"][0]["citation"]
        assert str(tmp_path) not in found.text
    finally:
        app.state.runtime.task_runner.stop(wait=True, timeout=1.0)  # type: ignore[union-attr]


def test_v5_write_plan_needs_confirmation_and_does_not_call_a_provider(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    try:
        file_id = upload(client, "budget.csv", b"mois;revenus\nJanvier;100\n", "text/csv")
        created = client.post(
            "/api/v5/tasks",
            json={"message": "Analyse ce fichier et crée un rapport.", "selected_file_ids": [file_id]},
        )
        assert created.status_code == 200
        finished = wait_for_task(client, created.json()["task_id"])
        assert finished["status"] == "completed"
        report_event = finished["result"]["events"][-1]
        assert report_event["tool"] == "create_analysis_workbook"
        assert report_event["status"] == "needs_confirmation"
        assert list((tmp_path / "output").glob("*.xlsx")) == []
        assert finished["result"]["remote_model_used"] is False
    finally:
        app.state.runtime.task_runner.stop(wait=True, timeout=1.0)  # type: ignore[union-attr]
