from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from academics.vc.content import load_content
from academics.vc.course import create_course_router, load_course, source_id
from academics.vc.drills import grade_drill
from academics.vc.storage import VcStore


def client(store: VcStore, source_root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_course_router(store=store, source_root=source_root))
    return TestClient(app)


def test_lessons_cover_every_primary_slide_once_and_checkpoints_stay_private(tmp_path):
    course = load_course()
    assert len(course["chapters"]) == 5
    assert sum(chapter["pages"] for chapter in course["chapters"]) == 170
    assert sum(len(chapter["lessons"]) for chapter in course["chapters"]) == 28
    for chapter in course["chapters"]:
        covered = [page for lesson in chapter["lessons"] for page in range(lesson["pages"][0], lesson["pages"][1] + 1)]
        assert covered == list(range(1, chapter["pages"] + 1))
        for lesson in chapter["lessons"]:
            assert lesson["explain"] and lesson["example"]["steps"] and lesson["quiz"]
    response = client(VcStore(tmp_path / "state"), tmp_path / "sources").get("/api/vc/course")
    assert response.status_code == 200
    quizzes = [
        question for chapter in response.json()["course"]["chapters"] for lesson in chapter["lessons"] for question in lesson["quiz"]
    ]
    assert len(quizzes) == 56
    assert all("answer" not in question and "explanation" not in question for question in quizzes)


def test_reading_review_queue_and_checkpoints_persist_independently(tmp_path):
    store = VcStore(tmp_path / "state")
    http = client(store, tmp_path / "sources")
    lesson = load_course()["chapters"][0]["lessons"][0]
    identifier = lesson["id"]
    opened = http.post("/api/vc/course/state", json={"lesson_id": identifier, "action": "opened"}).json()
    assert opened["read"] == opened["passed"] == 0
    http.post("/api/vc/course/state", json={"lesson_id": identifier, "action": "read"})
    http.post("/api/vc/course/state", json={"lesson_id": identifier, "action": "revisit"})
    answers = {question["id"]: str(question["answer"]) for question in lesson["quiz"]}
    result = http.post("/api/vc/course/quiz", json={"lesson_id": identifier, "answers": answers})
    assert result.status_code == 200 and result.json()["score"] == 100
    restored = client(VcStore(tmp_path / "state"), tmp_path / "sources").get("/api/vc/course/progress").json()
    assert restored["read"] == restored["passed"] == 1
    assert restored["review_later"] == [identifier]
    assert not store.path("progress.json").exists(), "The flashcard schedule must not be rewritten by course progress."
    http.post("/api/vc/course/state", json={"lesson_id": identifier, "action": "clear-review"})
    assert http.get("/api/vc/course/progress").json()["review_later"] == []
    http.post("/api/vc/course/state", json={"lesson_id": identifier, "action": "unread"})
    progress = http.get("/api/vc/course/progress").json()
    assert progress["read"] == 0 and progress["passed"] == 1


def test_every_checkpoint_answer_key_is_accepted_and_wrong_answers_do_not_pass(tmp_path):
    http = client(VcStore(tmp_path / "state"), tmp_path / "sources")
    for chapter in load_course()["chapters"]:
        for lesson in chapter["lessons"]:
            answers = {question["id"]: str(question["answer"]) for question in lesson["quiz"]}
            response = http.post("/api/vc/course/quiz", json={"lesson_id": lesson["id"], "answers": answers})
            assert response.status_code == 200
            assert response.json()["score"] == 100, lesson["id"]
            wrong = {question["id"]: "-999999" for question in lesson["quiz"]}
            result = http.post("/api/vc/course/quiz", json={"lesson_id": lesson["id"], "answers": wrong}).json()
            assert result["score"] == 0
            assert all(not item["correct"] for item in result["results"])
            assert all(item["explanation"] for item in result["results"])


def test_bad_actions_and_incomplete_answers_do_not_change_progress(tmp_path):
    store = VcStore(tmp_path / "state")
    http = client(store, tmp_path / "sources")
    for payload, status in [
        ({"lesson_id": "vc-foundations", "action": "mastered"}, 400),
        ({"lesson_id": "../private", "action": "read"}, 404),
    ]:
        assert http.post("/api/vc/course/state", json=payload).status_code == status
    assert http.post("/api/vc/course/quiz", json={"lesson_id": "vc-foundations", "answers": {}}).status_code == 400
    assert http.get("/api/vc/course/progress").json()["read"] == 0


def test_source_inventory_is_confined_and_originals_are_unchanged(tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=300)
    writer.add_blank_page(width=400, height=300)
    original = root / "Test lecture.pdf"
    writer.write(original)
    private = tmp_path / "private.pdf"
    writer.write(private)
    (root / "outside.pdf").symlink_to(private)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    http = client(VcStore(tmp_path / "state"), root)
    sources = http.get("/api/vc/course/library").json()["sources"]
    assert len(sources) == 1 and sources[0]["pages"] == 2
    identifier = source_id(original.name)
    assert http.get(f"/api/vc/course/source/{identifier}").status_code == 200
    assert http.get(f"/api/vc/course/source/{identifier}/page/2").json()["pages"] == 2
    assert http.get(f"/api/vc/course/source/{identifier}/page/3").status_code == 404
    assert http.get(f"/api/vc/course/source/{source_id('outside.pdf')}").status_code == 404
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest


def test_workbook_preview_reads_saved_values_without_writing(tmp_path):
    from openpyxl import Workbook

    root = tmp_path / "sources"
    root.mkdir()
    book = Workbook()
    book.active.title = "Synthetic example"
    book.active.append(["Investment", 200])
    book.active.append(["Double", "=B1*2"])
    original = root / "Example.xlsx"
    book.save(original)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    http = client(VcStore(tmp_path / "state"), root)
    result = http.get(f"/api/vc/course/workbook/{source_id(original.name)}")
    assert result.status_code == 200
    assert result.json()["sheets"][0]["rows"][0] == ["Investment", "200"]
    assert result.json()["sheets"][0]["formula_rows"][1] == ["Double", "=B1*2"]
    assert not result.json()["sheets"][0]["truncated"]
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest


def test_generated_drill_regressions_are_fixed_and_drafts_stay_inactive():
    content = load_content()
    weighted = content.drill("VC10-D004")
    assert weighted.answer == pytest.approx(5 / 3)
    assert grade_drill(weighted, str(5 / 3))["accepted"]
    assert not grade_drill(weighted, "1.4")["accepted"]
    ratchet = content.drill("VC10-D006")
    assert ratchet.answer == 5000
    assert grade_drill(ratchet, "5000")["accepted"]
    assert not grade_drill(ratchet, "4000")["accepted"]
    assert not any(drill.id.startswith("VC19-") for drill in content.drills)
    proposals = json.loads((Path(__file__).resolve().parents[1] / "academics/vc/content/drills_vc19.json").read_text())["items"]
    assert len(proposals) == 5
    assert all(item["status"] == "draft" and item["draft_reason"] for item in proposals)


def test_key_numerical_checkpoints_match_independent_calculations():
    lessons = {lesson["id"]: lesson for chapter in load_course()["chapters"] for lesson in chapter["lessons"]}
    expected = {
        ("financing-stages", 1): 85 * (1 - 0.18),
        ("exit-returns", 1): (2**0.5 - 1) * 100,
        ("vc-method", 1): (0.2 + 0.2) / (1 - 0.2) * 100,
        ("dcf-scenarios", 0): 0.2 * 0 + 0.5 * 10 + 0.3 * 30,
        ("dcf-scenarios", 1): 1 * 1.03 / (0.13 - 0.03),
        ("convertible-preferred", 0): 2 * 1.08 / 0.25,
        ("participation-cap", 0): 2 + 0.25 * (10 - 2),
        ("note-cap", 1): 0.53 / (5 / 12),
    }
    for (identifier, index), calculated in expected.items():
        question = lessons[identifier]["quiz"][index]
        assert float(question["answer"]) == pytest.approx(calculated, abs=question.get("tolerance", 0.01))


def test_course_recall_filters_background_cards_and_preserves_an_active_session(tmp_path, monkeypatch):
    from dataclasses import replace
    from academics.vc import api

    content = load_content()
    core = next(card for card in content.cards if card.topic_id == "VC01")
    background = next(card for card in content.cards if card.topic_id == "VC19")
    monkeypatch.setattr(api, "load_content", lambda: replace(content, cards=(core, background)))

    def app_for(path):
        app = FastAPI()
        app.include_router(api.create_vc_router(store=VcStore(path), tutor=object()))
        return TestClient(app)

    http = app_for(tmp_path / "core")
    session = http.get("/api/vc/review?scope=course").json()["session"]
    assert session["total"] == 1 and session["current"]["card_id"] == core.id
    assert http.get("/api/vc/review?scope=unknown").status_code == 400
    other = app_for(tmp_path / "all")
    active = other.get("/api/vc/review?scope=all").json()["session"]
    assert active["total"] == 2
    resumed = other.get("/api/vc/review?scope=course").json()["session"]
    assert resumed["session_id"] == active["session_id"] and resumed["total"] == 2
