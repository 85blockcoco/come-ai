"""One-app integration contract for the local, persistent learning journey."""

import json

from pathlib import Path

from fastapi.testclient import TestClient

from come_ai_web import create_app


class FakeAgent:
    def provider_status(self):
        return {"provider": "synthetic", "available": False}


COURSE = """
Convertible bonds and option sensitivities

Delta measures how the convertible value changes when the share price changes.
Gamma measures how delta changes when the share price changes.
Vega measures sensitivity to implied volatility.
Theta measures the effect of the passage of time on the option component.

For a hedged position, the analyst first estimates delta, then calculates the
number of shares required to offset the equity exposure. The calculation must
state the sign of the hedge and check that all quantities use compatible units.
"""


def test_document_to_persistent_revision_session_stays_inside_the_local_app(tmp_path, monkeypatch):
    monkeypatch.setenv("COME_AI_MEMORY_DIR", str(tmp_path / "memory_data"))
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "cours-convertibles.txt").write_text(COURSE, encoding="utf-8")

    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        files = client.get("/api/files").json()["files"]
        file_id = files[0]["file_id"]
        course_response = client.post("/api/study/courses", json={"file_id": file_id})
        assert course_response.status_code == 200
        course = course_response.json()
        assert course["notion_count"] >= 1
        assert course["title"] == "cours-convertibles.txt"
        assert all(notion["title"].casefold() not in {"you", "your"} for notion in course["notions"])

        session_response = client.post(
            f"/api/study/courses/{course['id']}/sessions",
            json={"size": 3},
        )
        assert session_response.status_code == 200
        session = session_response.json()
        assert session["total"] >= 1
        assert session["question"]["id"]

        answered = 0
        while session.get("question") is not None:
            question = session["question"]
            options = question.get("options") or []
            answer = options[0]["id"] if options else "Je définis le concept à partir du cours."
            response = client.post(
                f"/api/study/sessions/{session['session_id']}/answers",
                json={"question_id": question["id"], "value": answer},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["correction"]["status"] in {"correct", "partiel", "incorrect", "non_evaluable"}
            session["question"] = payload["question"]
            answered += 1
        assert answered == session["total"]

    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        overview = client.get("/api/study/overview")
        assert overview.status_code == 200
        body = overview.json()
        assert any(item["id"] == course["id"] for item in body["courses"])
        assert body["progress"]["stats"]["questions_seen"] == answered


def test_study_routes_reject_unknown_workspace_identifiers(tmp_path, monkeypatch):
    monkeypatch.setenv("COME_AI_MEMORY_DIR", str(tmp_path / "memory_data"))
    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        response = client.post("/api/study/courses", json={"file_id": "f_unknown"})
        assert response.status_code == 400
        assert "espace de travail" in response.json()["detail"]
        session = client.post("/api/study/courses/syll_unknown/sessions", json={"size": 5})
        assert session.status_code == 400
        assert "Programme de révision inconnu" in session.json()["detail"]


def test_homework_task_plan_persists_status_and_notes_locally(tmp_path, monkeypatch):
    monkeypatch.setenv("COME_AI_MEMORY_DIR", str(tmp_path / "memory_data"))
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "assignment.txt").write_text(
        "TD Finance\nQ1. Calculer la duration de l'obligation.\n"
        "Q2. Expliquer le signe de la convexité.\n",
        encoding="utf-8",
    )

    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        file_id = client.get("/api/files").json()["files"][0]["file_id"]
        initial = client.get(f"/api/study/homework/{file_id}/tasks")
        assert initial.status_code == 200
        body = initial.json()
        assert body["total"] == 2
        assert body["completed"] == 0
        first = body["tasks"][0]

        updated = client.put(
            f"/api/study/homework/{file_id}/tasks/{first['id']}",
            json={"status": "done", "notes": "Duration obtenue avec les flux du pricer synthétique."},
        )
        assert updated.status_code == 200
        assert updated.json()["completed"] == 1
        assert updated.json()["completion_percent"] == 50

    progress_path = Path(tmp_path) / "study_data" / "homework_progress.json"
    assert progress_path.is_file()
    assert progress_path.stat().st_mode & 0o077 == 0

    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        restored = client.get(f"/api/study/homework/{file_id}/tasks").json()
        assert restored["tasks"][0]["status"] == "done"
        assert "pricer synthétique" in restored["tasks"][0]["notes"]
        missing = client.put(
            f"/api/study/homework/{file_id}/tasks/task_unknown",
            json={"status": "todo", "notes": ""},
        )
        assert missing.status_code == 400

    progress_path.write_text(
        json.dumps({"schema_version": 1, "files": {file_id: {"tasks": {first["id"]: "valeur corrompue"}}}}),
        encoding="utf-8",
    )
    with TestClient(create_app(tmp_path, agent_override=FakeAgent())) as client:
        recovered = client.get(f"/api/study/homework/{file_id}/tasks")
        assert recovered.status_code == 200
        assert recovered.json()["tasks"][0]["status"] == "todo"
