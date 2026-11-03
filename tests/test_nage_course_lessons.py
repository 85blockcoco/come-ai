from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from academics.vc.pastpapers import load_papers
from career.course_lessons import (
    EXAM_SCOPE,
    LessonProgressStore,
    VC_LESSONS,
    classify_exam_question,
)
from career.learning_router import create_learning_router


def test_every_course_section_has_a_guided_exercise_and_cited_source() -> None:
    assert len(VC_LESSONS) == 5
    assert sum(len(lesson["sections"]) for lesson in VC_LESSONS) == 27
    for lesson in VC_LESSONS:
        assert lesson["sections"], lesson["chapter"]
        for section in lesson["sections"]:
            example = section.get("example")
            assert example and example.get("prompt"), (lesson["chapter"], section["title"])
            assert example.get("steps") and example.get("answer"), (lesson["chapter"], section["title"])
            assert section.get("sources"), (lesson["chapter"], section["title"])
            for question_id in example.get("exam_refs", []):
                chapter, _ = EXAM_SCOPE[question_id]
                assert chapter == lesson["chapter"], (lesson["chapter"], section["title"], question_id)


def test_every_content_page_in_the_five_primary_lecture_decks_is_referenced() -> None:
    expected_pages = {
        "Topic 1 Introduction to venture capital and the VC ecosystem.pdf": set(range(3, 10)) | set(range(15, 50)),
        "Topic 2 Evaluating startups(1).pdf": set(range(2, 37)),
        "Topic 3 Valuation, ownership and returns(1).pdf": set(range(2, 33)),
        "Topic 4 Term sheets, deal structuring and negotiation(1).pdf": set(range(2, 40)),
        "Topic 5 Governance, monitoring and exit strategies(1).pdf": set(range(2, 15)),
    }
    referenced: dict[str, set[int]] = {name: set() for name in expected_pages}
    for lesson in VC_LESSONS:
        for section in lesson["sections"]:
            for source in section.get("sources", []):
                filename = source.get("file")
                if filename not in referenced:
                    continue
                for start, end in re.findall(r"(?<![A-Za-z])(\d+)\s*(?:[–-]\s*(\d+))?", source.get("pages", "")):
                    first = int(start)
                    last = int(end or start)
                    referenced[filename].update(range(first, last + 1))
    for filename, pages in expected_pages.items():
        assert pages <= referenced[filename], (filename, sorted(pages - referenced[filename]))


def test_every_question_in_the_three_past_papers_has_an_explicit_scope() -> None:
    papers = load_papers()
    question_ids = {question.id for paper in papers for question in paper.questions}
    assert [(paper.year, len(paper.questions)) for paper in papers] == [(2023, 22), (2024, 24), (2025, 21)]
    assert set(EXAM_SCOPE) == question_ids
    assert Counter(EXAM_SCOPE[question_id][1] for question_id in question_ids) == {
        "core": 35,
        "related": 12,
        "outside_vc_scope": 20,
    }
    assert classify_exam_question("future-question") == {
        "course_chapter": None,
        "course_scope": "unclassified",
    }
    for lesson in VC_LESSONS:
        assigned = {
            question_id
            for question_id, (chapter, _scope) in EXAM_SCOPE.items()
            if chapter == lesson["chapter"]
        }
        assert set(lesson["exam_question_ids"]) == assigned, lesson["chapter"]
    for lesson in VC_LESSONS:
        for question_id in lesson["exam_question_ids"]:
            assert EXAM_SCOPE[question_id][0] == lesson["chapter"]


def test_every_parent_question_and_subpart_is_available_through_past_paper_routes(tmp_path: Path) -> None:
    corpus = tmp_path / "empty-corpus"
    corpus.mkdir()
    app = FastAPI()
    app.include_router(create_learning_router(tmp_path / "learning", corpus_root=corpus))
    papers = {paper.year: paper for paper in load_papers()}
    expected_counts = {2023: (22, 8), 2024: (24, 8), 2025: (21, 17)}

    with TestClient(app) as client:
        index = client.get("/career/past-papers").json()
        assert index["question_count"] == 67
        assert len(papers) == len(expected_counts)
        all_prompt_ids: list[str] = []

        for year, (parent_count, part_count) in expected_counts.items():
            source_paper = papers[year]
            response = client.get(f"/career/past-papers/{year}")
            assert response.status_code == 200
            payload = response.json()
            assert payload["selected_count"] == parent_count
            assert len(payload["questions"]) == parent_count
            assert sum(len(question.parts) for question in source_paper.questions) == part_count

            expected_ids = [question.id for question in source_paper.questions]
            expected_ids.extend(part.id for question in source_paper.questions for part in question.parts)
            displayed_ids = [question["id"] for question in payload["questions"]]
            displayed_ids.extend(
                part["id"] for question in payload["questions"] for part in question.get("parts", [])
            )
            assert displayed_ids == expected_ids, year
            all_prompt_ids.extend(displayed_ids)

            assert all("answer" not in question and "solution" not in question for question in payload["questions"])
            assert all(
                "answer" not in part and "solution" not in part
                for question in payload["questions"]
                for part in question.get("parts", [])
            )

    assert len(all_prompt_ids) == 100
    assert len(set(all_prompt_ids)) == 100


def test_lesson_actions_persist_without_claiming_mastery(tmp_path: Path) -> None:
    path = tmp_path / "lessons.sqlite3"
    store = LessonProgressStore(path)
    first = store.decide("topic-3", "practice")
    assert first["status"] == "new"
    assert first["practice_count"] == 1
    reviewed = store.decide("topic-3", "review")
    assert reviewed["status"] == "review"
    store.close()

    reopened = LessonProgressStore(path)
    assert reopened.all()["topic-3"]["status"] == "review"
    assert reopened.all()["topic-3"]["practice_count"] == 1
    understood = reopened.decide("topic-3", "understood")
    assert understood["status"] == "understood"
    reopened.close()


def test_past_paper_routes_hide_answers_and_grade_only_attempted_items(tmp_path: Path) -> None:
    corpus = tmp_path / "empty-corpus"
    corpus.mkdir()
    app = FastAPI()
    app.include_router(create_learning_router(tmp_path / "learning", corpus_root=corpus))
    papers = {paper.year: paper for paper in load_papers()}
    expected = papers[2025].question_by_id["2025-A01"].answer

    with TestClient(app) as client:
        index = client.get("/career/past-papers").json()
        assert index["question_count"] == 67
        assert [item["question_count"] for item in index["papers"]] == [22, 24, 21]
        assert all(item["unclassified_count"] == 0 for item in index["papers"])

        paper = client.get("/career/past-papers/2025").json()
        assert len(paper["questions"]) == 21
        prompt_ids = {
            prompt_id
            for item in paper["questions"]
            for prompt_id in [item["id"], *(part["id"] for part in item.get("parts", []))]
        }
        assert len(prompt_ids) == 38
        assert all("answer" not in item and "solution" not in item for item in paper["questions"])
        assert all(
            "answer" not in part and "solution" not in part
            for item in paper["questions"]
            for part in item.get("parts", [])
        )

        empty = client.post("/career/past-papers/2025/grade", json={"answers": {"2025-A01": ""}})
        assert empty.status_code == 400

        oversized = client.post(
            "/career/past-papers/2025/grade",
            json={"answers": {"2025-A01": "x" * 4_001}},
        )
        assert oversized.status_code == 422

        graded = client.post(
            "/career/past-papers/2025/grade",
            json={"answers": {"2025-A01": expected}},
        )
        assert graded.status_code == 200
        result = graded.json()
        assert result["attempted_item_count"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["question_id"] == "2025-A01"
        assert result["auto_points"] == result["auto_max"] == 1.0
        assert result["auto_percent"] == 100.0
        assert result["local_only"] is True


def test_lesson_action_route_returns_review_queue_and_keeps_progress_local(tmp_path: Path) -> None:
    corpus = tmp_path / "empty-corpus"
    corpus.mkdir()
    app = FastAPI()
    app.include_router(create_learning_router(tmp_path / "learning", corpus_root=corpus))

    with TestClient(app) as client:
        response = client.get("/career/learning/lessons")
        assert response.status_code == 200
        lessons = response.json()["lessons"]
        assert len(lessons) == 5
        assert all(section.get("example") for lesson in lessons for section in lesson["sections"])

        saved = client.post("/career/learning/lessons/topic-2/action", json={"action": "review"})
        assert saved.status_code == 200
        assert saved.json()["progress"]["status"] == "review"
        queue = client.get("/career/learning/lessons").json()["review_queue"]
        assert [item["id"] for item in queue] == ["topic-2"]
        assert saved.json()["local_only"] is True

        missing = client.post("/career/learning/lessons/topic-99/action", json={"action": "understood"})
        assert missing.status_code == 404
