from fastapi.testclient import TestClient

from come_ai_web import create_app


def test_vc_http_flow_hides_answers_and_persists_reviews(tmp_path, monkeypatch):
    monkeypatch.setenv("NAGE_VC_HOME", str(tmp_path / "vc"))
    with TestClient(create_app(base_dir=tmp_path)) as client:
        saved = client.post("/api/academics/vc/cards", json={"cards": [{"id": "pm", "topic": "valuation", "front": "Post-money ?", "back": "10", "source": "synthetic"}]})
        assert saved.status_code == 200 and saved.json()["saved"] == 1
        session = client.post("/api/academics/vc/session", json={"today": "2026-11-02", "limit": 1})
        assert session.status_code == 200
        assert session.json()["cards"][0]["id"] == "pm"
        assert "back" not in session.json()["cards"][0]
        session_id = session.json()["session_id"]
        review = client.post("/api/academics/vc/review", json={"card_id": "pm", "quality": 2, "reviewed_on": "2026-11-02"})
        assert review.status_code == 200 and review.json()["review"]["due_on"] == "2026-11-03"
        radar = client.get("/api/academics/vc/radar")
        assert radar.json()["radar"][0]["status"] == "fragile"
        summary = client.post("/api/academics/vc/session/summary", json={"session_id": session_id, "card_ids": ["pm"], "today": "2026-11-02"})
        assert summary.status_code == 200 and summary.json()["summary"]["answered"] == 1
        assert client.get("/api/academics/vc/sessions").json()["sessions"]


def test_vc_route_rejects_unknown_card_without_external_action(tmp_path, monkeypatch):
    monkeypatch.setenv("NAGE_VC_HOME", str(tmp_path / "vc"))
    with TestClient(create_app(base_dir=tmp_path)) as client:
        response = client.post("/api/academics/vc/review", json={"card_id": "missing", "quality": 3})
        assert response.status_code == 200
        assert "introuvable" in response.json()["blockers"][0]


def test_vc_exam_hides_answers_until_grade(tmp_path, monkeypatch):
    monkeypatch.setenv("NAGE_VC_HOME", str(tmp_path / "vc"))
    with TestClient(create_app(base_dir=tmp_path)) as client:
        exam = client.post("/api/academics/vc/exam", json={"limit": 2})
        assert exam.status_code == 200
        payload = exam.json()["exam"]
        assert payload["duration_minutes"] == 30
        assert len(payload["questions"]) == 2
        assert all("answer" not in question for question in payload["questions"])
        result = client.post("/api/academics/vc/exam/grade", json={"exam_id": payload["id"], "limit": 2, "answers": {"q-pm": "10"}})
        assert result.status_code == 200
        assert result.json()["result"]["score"] == 2
        history = client.get("/api/academics/vc/exams")
        assert history.status_code == 200
        assert history.json()["exams"][-1]["exam_id"] == payload["id"]


def test_vc_exam_rejects_unbounded_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("NAGE_VC_HOME", str(tmp_path / "vc"))
    with TestClient(create_app(base_dir=tmp_path)) as client:
        response = client.post("/api/academics/vc/exam", json={"limit": 21})
        assert response.status_code == 422
