"""Integration tests for the VC Révisions API (``/api/vc``).

The app is built with an isolated base_dir and an offline tutor, so these
tests never read the real ``~/.nage/vc`` store, the real ``.env``, or the
network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from come_ai_web import create_app


@pytest.fixture(autouse=True)
def isolated_provider_sources(tmp_path: Path, monkeypatch):
    import os
    import vc_tutor
    import academics.vc.api as vc_api

    for name in tuple(os.environ):
        if vc_tutor._provider_setting(name):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(vc_tutor, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vc_tutor, "_CENTRAL_PROVIDER_ENV", tmp_path / "providers.env")
    monkeypatch.setenv("NAGE_VC_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(vc_api, "_keychain_environment", lambda: {})


def test_keychain_keys_are_reloaded_without_returning_secrets(tmp_path, monkeypatch):
    from fastapi import FastAPI
    import academics.vc.api as vc_api
    from academics.vc.storage import VcStore

    keys = {"GEMINI_API_KEY": "synthetic-primary-key-123456789"}
    monkeypatch.setenv("VC_TUTOR_CLOUD", "1")
    monkeypatch.setattr(vc_api, "_keychain_environment", lambda: dict(keys))
    app = FastAPI()
    app.include_router(vc_api.create_vc_router(store=VcStore(tmp_path)))
    with TestClient(app) as http:
        assert http.get("/api/vc/status").json()["tutor"]["gemini_key_count"] == 1
        keys.update({"GEMINI_API_KEY_2": "synthetic-second-key-123456789", "GEMINI_API_KEY_3": "synthetic-third-key-123456789"})
        response = http.post("/api/vc/tutor/reload", json={})
        assert response.status_code == 200
        assert response.json()["tutor"]["gemini_key_count"] == 3
        assert all(secret not in response.text for secret in keys.values())
        assert http.get("/api/vc/status").json()["tutor"]["gemini_key_count"] == 3


def test_reload_keeps_injected_tutor_and_never_reads_keychain(tmp_path, monkeypatch):
    import academics.vc.api as vc_api
    def forbidden_read():
        raise AssertionError("An isolated test app must not open a real keychain")
    monkeypatch.setattr(vc_api, "_keychain_environment", forbidden_read)
    with client(tmp_path) as http:
        result = http.post("/api/vc/tutor/reload", json={})
        assert result.status_code == 200
        assert result.json()["tutor"]["mode"] == "offline"


def test_locked_keychain_does_not_break_revision_status(tmp_path, monkeypatch):
    from fastapi import FastAPI
    import academics.vc.api as vc_api
    from academics.vc.storage import VcStore
    from academics.vc.keychain import KeychainError

    def locked():
        raise KeychainError("Keychain unavailable")
    monkeypatch.setattr(vc_api, "_keychain_environment", locked)
    monkeypatch.setenv("VC_TUTOR_CLOUD", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-env-key-123456789")
    app = FastAPI()
    app.include_router(vc_api.create_vc_router(store=VcStore(tmp_path)))
    with TestClient(app) as http:
        result = http.get("/api/vc/status")
        assert result.status_code == 200
        assert result.json()["tutor"]["gemini_key_count"] == 1


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


class FakeTutor:
    """Records the pedagogical context it receives; never calls a model."""

    def __init__(self) -> None:
        self.last_kwargs = None

    def provider_status(self) -> dict:
        return {"mode": "offline", "cloud_enabled": False}

    def tutor_chat(self, message: str, **kwargs):
        self.last_kwargs = {"message": message, **kwargs}
        return {
            "text": "Fake tutor answer.",
            "source": "ai",
            "mode": kwargs.get("mode", "explain"),
            "passages": [{"citation": "Topic 3 Valuation.txt"}],
            "model": "fake",
        }


class BrokenTutor:
    def provider_status(self) -> dict:
        return {"mode": "gemini", "cloud_enabled": True, "gemini_key_count": 1}

    def tutor_chat(self, **_kwargs):
        raise RuntimeError("synthetic provider interruption")


def test_explicit_workspace_keeps_tutor_config_local(tmp_path: Path, monkeypatch) -> None:
    """A test workspace must never create config in the user's VC home."""
    from vc_tutor import VCTutor

    unrelated_home = tmp_path / "unrelated-private-home"
    monkeypatch.setenv("NAGE_VC_HOME", str(unrelated_home))
    monkeypatch.setenv("VC_TUTOR_CLOUD", "1")

    def forbidden_env_read(self):
        raise AssertionError("An explicit test workspace must not read .env")

    monkeypatch.setattr(VCTutor, "load_env", forbidden_env_read)
    with TestClient(create_app(tmp_path / "workspace", agent_override=FakeAgent())) as http:
        tutor = http.app.state.vc_tutor
        assert tutor.tutor_config_path == tmp_path / "workspace" / "vc" / "tutor_config.json"
        assert tutor.tutor_config_path.is_file()
        assert not tutor.cloud_enabled
        assert not unrelated_home.exists()


def test_production_tutor_requires_explicit_cloud_consent(tmp_path: Path, monkeypatch) -> None:
    from fastapi import FastAPI
    from academics.vc.api import create_vc_router
    from academics.vc.storage import VcStore

    import vc_tutor

    monkeypatch.setattr(vc_tutor, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vc_tutor, "_CENTRAL_PROVIDER_ENV", tmp_path / "providers.env")
    monkeypatch.delenv("VC_TUTOR_CLOUD", raising=False)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=synthetic-config-key\n")
    app = FastAPI()
    app.include_router(create_vc_router(store=VcStore(tmp_path)))
    with TestClient(app) as http:
        result = http.get("/api/vc/status")
        assert result.status_code == 200
        status = result.json()["tutor"]
        assert status["cloud_enabled"] is False
        assert status["gemini_key_count"] == 1
    assert (tmp_path / "tutor_config.json").is_file()


def test_production_tutor_honors_cloud_consent_from_private_file(tmp_path: Path, monkeypatch) -> None:
    from fastapi import FastAPI
    from academics.vc.api import create_vc_router
    from academics.vc.storage import VcStore
    import vc_tutor

    monkeypatch.setattr(vc_tutor, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vc_tutor, "_CENTRAL_PROVIDER_ENV", tmp_path / "providers.env")
    monkeypatch.delenv("VC_TUTOR_CLOUD", raising=False)
    (tmp_path / "providers.env").write_text("GEMINI_API_KEY=synthetic-private-key\nVC_TUTOR_CLOUD=1\n")
    app = FastAPI()
    app.include_router(create_vc_router(store=VcStore(tmp_path)))
    with TestClient(app) as http:
        result = http.get("/api/vc/status")
        assert result.json()["tutor"]["cloud_enabled"] is True
        assert "synthetic-private-key" not in result.text


def client(tmp_path: Path, tutor: FakeTutor | None = None) -> TestClient:
    from career.service import CareerService

    return TestClient(
        create_app(
            tmp_path,
            agent_override=FakeAgent(),
            career_override=CareerService(tmp_path),
            vc_tutor_override=tutor or FakeTutor(),
        )
    )


def test_status_reports_content_counts_and_offline_tutor(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        status = http.get("/api/vc/status").json()
        assert status["subject"] == "Venture Capital"
        assert status["exam_duration_minutes"] == 90
        assert status["counts"]["topics"] == 21
        assert status["counts"]["cards"] == 189
        # Compare against the content pack itself: guards content loss without
        # breaking every time a drill is added.
        from academics.vc.content import load_content

        assert status["counts"]["drills"] == len(load_content().drills)
        assert status["tutor"]["mode"] == "offline"


def test_tutor_provider_failure_keeps_the_learning_flow_available(tmp_path: Path) -> None:
    with client(tmp_path, BrokenTutor()) as http:
        response = http.post("/api/vc/tutor", json={"message": "synthetic answer", "topic_id": "VC01", "mode": "correct"})
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "offline"
        assert "temporarily unavailable" in body["text"]
        assert "synthetic provider" not in response.text


def test_status_never_leaks_api_key(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        body = http.get("/api/vc/status").text
        assert "GEMINI_API_KEY" not in body
        assert "MISTRAL_API_KEY" not in body
        assert "AQ." not in body
        assert "mstrl_" not in body


def test_coverage_lists_every_topic(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        topics = http.get("/api/vc/coverage").json()["topics"]
        assert len(topics) == 21
        assert {t["topic_id"] for t in topics} == {f"VC{i:02d}" for i in range(1, 22)}


def test_radar_marks_untested_topics_as_untested(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        radar = http.get("/api/vc/radar").json()
        assert len(radar["topics"]) == 21
        # Fresh store: nothing may be presented as mastered.
        assert len(radar["untested"]) == 21
        for topic in radar["topics"]:
            assert topic["status"] == "untested"


def test_plan_and_next_return_bounded_activities(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        plan = http.get("/api/vc/plan", params={"minutes": 60}).json()["plan"]
        assert plan["capacity_minutes"] == 60
        assert plan["total_minutes"] <= 60
        assert plan["activities"]
        nxt = http.get("/api/vc/next", params={"minutes": 30}).json()
        assert nxt["activity"] is not None
        assert "kind" in nxt["activity"]


def test_plan_rejects_absurd_duration(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        assert http.get("/api/vc/plan", params={"minutes": 0}).status_code == 400
        assert http.get("/api/vc/plan", params={"minutes": 5000}).status_code == 400


def test_tutor_receives_mastery_and_error_context(tmp_path: Path) -> None:
    tutor = FakeTutor()
    with client(tmp_path, tutor) as http:
        response = http.post(
            "/api/vc/tutor",
            json={
                "message": "Explain post-money",
                "mode": "hint",
                "topic_id": "VC04",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "ai"
        assert payload["mastery"]["topic_id"] == "VC04"
        sent = tutor.last_kwargs
        assert sent["mode"] == "hint"
        assert sent["mastery"]["status"] == "untested"


def test_tutor_rejects_unknown_topic(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/vc/tutor", json={"message": "hi", "topic_id": "VC99"})
        assert response.status_code == 400


def test_review_session_roundtrip(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        started = http.get("/api/vc/review", params={"minutes": 10, "mode": "quick"})
        assert started.status_code == 200
        session = started.json()["session"]
        assert session["total"] >= 1
        assert session["current"] is not None
        # The question is shown; the answer must not be revealed.
        assert "answer" not in session["current"]

        answered = http.post("/api/vc/review/answer", json={"grade": "good", "duration_seconds": 3})
        assert answered.status_code == 200
        after = answered.json()
        # `last_result` lives inside the session payload, as in the CLI.
        assert after["session"]["last_result"]["grade"] == "good"
        assert after["session"]["done"] >= 1


def test_review_rejects_invalid_grade(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        http.get("/api/vc/review")
        response = http.post("/api/vc/review/answer", json={"grade": "perfect"})
        assert response.status_code == 400


def test_drill_draw_and_grade(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        drawn = http.post("/api/vc/drill/draw", json={"topic_id": "VC04", "seed": 1})
        assert drawn.status_code == 200
        drill = drawn.json()["drill"]
        assert drill["topic_id"] == "VC04"
        # The drawn payload must not leak the answer.
        assert "answer" not in drill

        graded = http.post(
            "/api/vc/drill/grade",
            json={"drill_id": drill["drill_id"], "answer": "2"},
        )
        assert graded.status_code == 200
        body = graded.json()
        assert body["source"] == "deterministic"
        assert isinstance(body["accepted"], bool)
        assert body["steps"]  # step-by-step correction available


def test_drill_grade_unknown_id_is_400(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/vc/drill/grade", json={"drill_id": "NOPE-D999", "answer": "1"})
        assert response.status_code == 400


def test_exam_start_grade_and_submit_flow(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        state = http.get("/api/vc/exam/state").json()
        assert state["active"] is None

        started = http.post("/api/vc/exam/start", json={"questions": 5, "minutes": 90, "seed": 7})
        assert started.status_code == 200
        body = started.json()
        assert body["resumed"] is False
        exam = body["active"]
        assert exam["duration_minutes"] == 90
        assert exam["total_questions"] == 5
        assert len(exam["questions"]) == 5
        # No answers nor corrections while the exam runs.
        for question in exam["questions"]:
            assert "answer" not in question
            assert "solution" not in question

        # A second start resumes instead of rebuilding.
        again = http.post("/api/vc/exam/start", json={"questions": 5, "minutes": 90})
        assert again.json()["resumed"] is True

        answers = {q["question_id"]: "" for q in exam["questions"]}
        submitted = http.post(
            "/api/vc/exam/submit",
            json={"exam_id": exam["exam_id"], "answers": answers},
        )
        assert submitted.status_code == 200
        result = submitted.json()["result"]
        assert result["score"] is not None
        assert "per_topic" in result

        last = http.get("/api/vc/exam/last")
        assert last.status_code == 200
        assert last.json()["result"]["exam_id"] == exam["exam_id"]


def test_exam_submit_wrong_id_is_409(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/api/vc/exam/submit", json={"exam_id": "exam_nope", "answers": {}})
        assert response.status_code == 409


def test_papers_list_show_and_grade(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        papers = http.get("/api/vc/papers").json()["papers"]
        assert {p["year"] for p in papers} == {2023, 2024, 2025}

        shown = http.get("/api/vc/papers/2025")
        assert shown.status_code == 200
        assert shown.json()["source"] == "official_exam"
        # Exam paper payload must not include solutions by default.
        for question in shown.json()["paper"]["questions"]:
            assert "solution" not in question

        with_solutions = http.get("/api/vc/papers/2025", params={"solutions": True})
        assert with_solutions.json()["source"] == "official_solutions"

        missing = http.get("/api/vc/papers/1999")
        assert missing.status_code == 404


def test_errors_endpoint_starts_empty(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        dashboard = http.get("/api/vc/errors").json()["dashboard"]
        assert dashboard["total_errors"] == 0
        assert dashboard["categories"] == []


def test_formulas_sheet_is_available_offline(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        payload = http.get("/api/vc/formulas").json()
        assert payload["source"] == "deterministic"
        assert payload["sheet"]["groups"]


def test_offline_tutor_returns_clear_fallback(tmp_path: Path, monkeypatch) -> None:
    from vc_tutor import VCTutor

    monkeypatch.setattr(VCTutor, "call_ollama", lambda *args, **kwargs: None)
    offline = VCTutor(cloud=False, load_env=False, data_dir=tmp_path / "offline")
    with client(tmp_path, tutor=offline) as http:
        response = http.post("/api/vc/tutor", json={"message": "What is IRR?"})
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "offline"
        assert "No model available" in body["text"]


def test_progress_survives_app_recreation(tmp_path: Path) -> None:
    """Same base_dir twice = same store: progress persists across restarts."""
    from career.service import CareerService

    def build() -> TestClient:
        return TestClient(
            create_app(
                tmp_path,
                agent_override=FakeAgent(),
                career_override=CareerService(tmp_path),
                vc_tutor_override=FakeTutor(),
            )
        )

    with build() as first:
        first.get("/api/vc/review")
        first.post("/api/vc/review/answer", json={"grade": "easy"})
        done = first.get("/api/vc/status").json()["counts"]["cards"]

    with build() as second:
        radar = second.get("/api/vc/radar").json()
        reviewed = [t for t in radar["topics"] if t["attempts"] > 0]
        assert reviewed, "review events must survive an app restart"
        assert second.get("/api/vc/status").json()["counts"]["cards"] == done
