"""Fresh-number practice variants never change the underlying VC method."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from academics.vc.api import create_vc_router
from academics.vc.content import load_content
from academics.vc.course import create_course_router, load_course
from academics.vc.storage import VcStore
from academics.vc.variants import generated_drill, lesson_variant


def test_lesson_variant_changes_example_and_keeps_formula() -> None:
    lesson = next(item for chapter in load_course()["chapters"] for item in chapter["lessons"] if item["id"] == "financing-stages")
    first = lesson_variant(lesson, 10)
    second = lesson_variant(lesson, 11)
    assert first["variant_id"] != second["variant_id"]
    assert first["example"]["context"] != second["example"]["context"]
    assert first["quiz"][0]["answer"] != second["quiz"][0]["answer"]
    assert "×" in first["example"]["steps"][0]


def test_course_variant_can_be_checked_with_its_own_answers(tmp_path) -> None:
    app = FastAPI()
    app.include_router(create_course_router(store=VcStore(tmp_path), source_root=tmp_path))
    with TestClient(app) as http:
        variant = http.get("/api/vc/course/lesson/financing-stages/variant?seed=42").json()
        assert all("answer" not in question and "explanation" not in question for question in variant["quiz"])
        lesson = next(item for chapter in load_course()["chapters"] for item in chapter["lessons"] if item["id"] == "financing-stages")
        private_variant = lesson_variant(lesson, 42)
        answers = {question["id"]: str(question["answer"]) for question in private_variant["quiz"]}
        result = http.post(
            "/api/vc/course/quiz",
            json={"lesson_id": "financing-stages", "variant_id": variant["variant_id"], "answers": answers},
        )
        assert result.status_code == 200
        assert result.json()["score"] == 100


def test_generated_drills_use_new_numbers_and_are_gradeable(tmp_path) -> None:
    first = generated_drill("VC03", 1)
    second = generated_drill("VC03", 2)
    assert first and second and first.answer != second.answer
    app = FastAPI()
    app.include_router(create_vc_router(store=VcStore(tmp_path)))
    with TestClient(app) as http:
        draw = http.post("/api/vc/drill/draw", json={"topic_id": "VC03", "seed": 7}).json()["drill"]
        expected = generated_drill("VC03", 7).answer
        graded = http.post("/api/vc/drill/grade", json={"drill_id": draw["drill_id"], "answer": str(expected)})
        assert graded.status_code == 200
        assert graded.json()["accepted"] is True


def test_generated_method_drills_never_use_zero_denominators() -> None:
    for topic_id in ("VC03", "VC04", "VC05", "VC07", "VC09"):
        drill = generated_drill(topic_id, 42)
        assert drill is not None
        assert drill.answer > 0


def test_exam_content_includes_fresh_variants() -> None:
    content = load_content()
    ids = {question.id for question in content.exams}
    assert {"VC03-V001", "VC05-V001", "VC09-V001"} <= ids
