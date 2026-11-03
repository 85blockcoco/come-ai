from pathlib import Path

from fastapi.testclient import TestClient

from come_ai_web import create_app


class FakeAgent:
    def chat(self, message: str, **kwargs):
        return {
            "answer": "",
            "provider": "offline",
            "model": "fake",
            "tool_events": [],
            "citations": [],
            "usage": {},
        }


def make_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("NAGE_VC_HOME", str(tmp_path / "vc-home"))
    return TestClient(create_app(tmp_path / "workspace", agent_override=FakeAgent()))


def test_vc_session_question_reveal_grade_and_resume(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        status = client.get("/api/academics/vc/status", params={"today": "2026-11-03"})
        assert status.status_code == 200
        assert status.json()["content"]["cards"] >= 1

        started = client.post(
            "/api/academics/vc/session",
            json={"minutes": 5, "mode": "quick", "today": "2026-11-03"},
        )
        assert started.status_code == 200
        session = started.json()["session"]
        session_id = session["session_id"]
        assert session["current"]["question"]
        assert "answer" not in session["current"]

        resumed = client.get(f"/api/academics/vc/session/{session_id}")
        assert resumed.status_code == 200
        assert "answer" not in resumed.json()["session"]["current"]

        revealed = client.post(f"/api/academics/vc/session/{session_id}/reveal")
        assert revealed.status_code == 200
        assert revealed.json()["session"]["current"]["answer"]

        graded = client.post(
            f"/api/academics/vc/session/{session_id}/grade",
            json={"grade": "again", "duration_seconds": 4},
        )
        assert graded.status_code == 200
        assert graded.json()["event"]["grade"] == "again"
        assert graded.json()["event"]["due_after"] == "2026-11-03"
        assert graded.json()["session"]["done"] == 1


def test_vc_invalid_grade_is_rejected_without_writing_progress(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        started = client.post(
            "/api/academics/vc/session",
            json={"minutes": 5, "today": "2026-11-03"},
        )
        session_id = started.json()["session"]["session_id"]
        response = client.post(
            f"/api/academics/vc/session/{session_id}/grade",
            json={"grade": "unknown"},
        )
        assert response.status_code == 422
        current = client.get(f"/api/academics/vc/session/{session_id}").json()["session"]
        assert current["done"] == 0


def test_vc_radar_and_plan_are_local_and_bounded(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        radar = client.get("/api/academics/vc/radar", params={"today": "2026-11-03"})
        plan = client.get(
            "/api/academics/vc/plan",
            params={"minutes": 30, "today": "2026-11-03", "exam_date": "2026-11-06"},
        )
        assert radar.status_code == 200
        assert len(radar.json()["topics"]) == 20
        assert plan.status_code == 200
        assert plan.json()["plan"]["total_minutes"] <= 30


def test_vc_missing_session_returns_blocker(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/academics/vc/session/not-a-real-session/reveal")
        assert response.status_code == 200
        assert response.json()["blockers"]


def test_vc_mock_exam_is_timed_answerable_and_corrected(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        started = client.post(
            "/api/academics/vc/exam",
            json={"questions": 3, "minutes": 5, "seed": 7, "new": True},
        )
        assert started.status_code == 200
        exam = started.json()["exam"]
        exam_id = exam["exam_id"]
        assert exam["remaining_seconds"] > 0
        assert exam["questions"]
        assert "answer" not in exam["questions"][0]

        question = exam["questions"][0]
        answered = client.post(
            f"/api/academics/vc/exam/{exam_id}/answer",
            json={"question_id": question["question_id"], "answer": "synthetic answer"},
        )
        assert answered.status_code == 200
        assert answered.json()["exam"]["answered"] == 1

        submitted = client.post(
            f"/api/academics/vc/exam/{exam_id}/submit",
            json={"now": exam["started_at"]},
        )
        assert submitted.status_code == 200
        result = submitted.json()["result"]
        assert result["status"] == "submitted"
        assert 0 <= result["score"] <= 1
        assert result["details"]
        assert client.get(f"/api/academics/vc/exam/{exam_id}").json()["blockers"]


def test_vc_exam_rejects_answers_for_unknown_questions(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        started = client.post("/api/academics/vc/exam", json={"questions": 1, "minutes": 5, "new": True})
        exam_id = started.json()["exam"]["exam_id"]
        response = client.post(
            f"/api/academics/vc/exam/{exam_id}/answer",
            json={"question_id": "not-in-exam", "answer": "x"},
        )
        assert response.status_code == 200
        assert response.json()["blockers"]
