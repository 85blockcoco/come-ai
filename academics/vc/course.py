"""Source-grounded, offline VC lessons and explicit learning evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .dates import now_iso
from .drills import parse_number
from .storage import VcStore

CURRICULUM_PATH = Path(__file__).parent / "content" / "course_curriculum.json"


@lru_cache(maxsize=1)
def load_course() -> dict[str, Any]:
    payload = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
    ids = [lesson["id"] for chapter in payload["chapters"] for lesson in chapter["lessons"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate lesson identifier.")
    for chapter in payload["chapters"]:
        mapped = [page for lesson in chapter["lessons"] for page in range(lesson["pages"][0], lesson["pages"][1] + 1)]
        if mapped != list(range(1, chapter["pages"] + 1)):
            raise ValueError(f"Course pages are missing or duplicated in {chapter['id']}.")
    return payload


def source_id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:20]


def _lessons() -> dict[str, dict[str, Any]]:
    return {lesson["id"]: lesson for chapter in load_course()["chapters"] for lesson in chapter["lessons"]}


def _progress_payload(store: VcStore) -> dict[str, Any]:
    progress = store.load_course_progress()
    states = progress.get("lessons", {})
    known = _lessons()
    visible = {key: value for key, value in states.items() if key in known and isinstance(value, dict)}
    return {
        "lessons": visible,
        "last_lesson": progress.get("last_lesson"),
        "read": sum(bool(value.get("read_at")) for value in visible.values()),
        "passed": sum(value.get("last_score", 0) >= 80 for value in visible.values()),
        "review_later": [key for key, value in visible.items() if value.get("review_later")],
        "total": len(known),
    }


@lru_cache(maxsize=64)
def _file_metadata(path_text: str, modified: int, size: int) -> dict[str, Any]:
    path = Path(path_text)
    result: dict[str, Any] = {"bytes": size}
    try:
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            result["pages"] = len(PdfReader(path).pages)
        elif path.suffix.lower() == ".xlsx":
            from openpyxl import load_workbook

            book = load_workbook(path, read_only=True, data_only=False)
            try:
                result["sheets"] = book.sheetnames
            finally:
                book.close()
    except Exception:
        result["notice"] = "Preview unavailable; the original file is still available."
    return result


class CourseStateRequest(BaseModel):
    lesson_id: str = Field(max_length=80)
    action: str = Field(max_length=20)


class CourseQuizRequest(BaseModel):
    lesson_id: str = Field(max_length=80)
    answers: dict[str, str] = Field(default_factory=dict, max_length=10)
    variant_id: str | None = Field(default=None, max_length=100)


def create_course_router(store: VcStore | None = None, *, source_root: Path | None = None) -> APIRouter:
    router = APIRouter()
    lock = threading.Lock()
    render_lock = threading.Lock()
    local_store = store
    root = (source_root or Path.home() / "Desktop" / "EDHEC COURS" / "VENTURE CAPITAL").resolve()

    def get_store() -> VcStore:
        nonlocal local_store
        if local_store is None:
            local_store = VcStore()
        return local_store

    def source_paths() -> dict[str, Path]:
        if not root.is_dir():
            return {}
        return {
            source_id(path.name): path
            for path in root.iterdir()
            if path.is_file() and path.suffix.lower() in {".pdf", ".xlsx"} and path.resolve().parent == root
        }

    def lesson_or_404(identifier: str) -> dict[str, Any]:
        lesson = _lessons().get(identifier)
        if lesson is None:
            raise HTTPException(status_code=404, detail="Lesson not found.")
        return lesson

    @router.get("/api/vc/course")
    def course_catalog() -> dict[str, Any]:
        catalog = copy.deepcopy(load_course())
        for chapter in catalog["chapters"]:
            identifier = source_id(chapter["filename"])
            chapter["source_id"] = identifier
            chapter["source_available"] = identifier in source_paths()
            for lesson in chapter["lessons"]:
                for question in lesson["quiz"]:
                    question.pop("answer", None)
                    question.pop("explanation", None)
        return {"course": catalog, "progress": _progress_payload(get_store())}

    @router.get("/api/vc/course/progress")
    def course_progress() -> dict[str, Any]:
        return _progress_payload(get_store())

    @router.post("/api/vc/course/state")
    def set_course_state(payload: CourseStateRequest) -> dict[str, Any]:
        lesson_or_404(payload.lesson_id)
        if payload.action not in {"opened", "read", "unread", "revisit", "clear-review"}:
            raise HTTPException(status_code=400, detail="Unknown learning action.")
        target = get_store()
        with lock:
            data = target.load_course_progress()
            entry = data.setdefault("lessons", {}).setdefault(payload.lesson_id, {})
            data["last_lesson"] = payload.lesson_id
            if payload.action == "read":
                entry["read_at"] = now_iso()
            elif payload.action == "unread":
                entry.pop("read_at", None)
            elif payload.action in {"revisit", "clear-review"}:
                entry["review_later"] = payload.action == "revisit"
            target.save_course_progress(data)
        return _progress_payload(target)

    @router.post("/api/vc/course/quiz")
    def submit_course_quiz(payload: CourseQuizRequest) -> dict[str, Any]:
        lesson = lesson_or_404(payload.lesson_id)
        questions = lesson["quiz"]
        if payload.variant_id:
            from .variants import lesson_variant

            prefix = f"lesson-{payload.lesson_id}-"
            try:
                seed = int(payload.variant_id.removeprefix(prefix))
            except ValueError as error:
                raise HTTPException(status_code=400, detail="Unknown lesson variant.") from error
            generated = lesson_variant(lesson, seed)
            if generated["variant_id"] != payload.variant_id:
                raise HTTPException(status_code=400, detail="Unknown lesson variant.")
            questions = generated["quiz"]
        expected_ids = {question["id"] for question in questions}
        if set(payload.answers) - expected_ids:
            raise HTTPException(status_code=400, detail="Unknown checkpoint question.")
        if not all(str(payload.answers.get(identifier, "")).strip() for identifier in expected_ids):
            raise HTTPException(status_code=400, detail="Answer each checkpoint question before checking.")
        if any(len(answer) > 500 for answer in payload.answers.values()):
            raise HTTPException(status_code=422, detail="Checkpoint answer is too long.")
        results = []
        for question in questions:
            raw = payload.answers[question["id"]].strip()
            correct = False
            if question["kind"] == "numeric":
                try:
                    given, _unit = parse_number(raw.replace("$", ""), "ratio")
                    correct = math.isfinite(given) and abs(given - float(question["answer"])) <= question.get("tolerance", 0.01)
                except (ValueError, TypeError):
                    correct = False
                expected = f"{question['answer']:g} {question.get('unit', '')}"
            else:
                correct = raw == question["answer"]
                expected = question["choices"][int(question["answer"])]
            results.append({"id": question["id"], "correct": correct, "expected": expected, "explanation": question["explanation"]})
        score = round(100 * sum(result["correct"] for result in results) / len(results))
        target = get_store()
        with lock:
            data = target.load_course_progress()
            entry = data.setdefault("lessons", {}).setdefault(payload.lesson_id, {})
            entry.update(
                last_score=score,
                best_score=max(score, entry.get("best_score", 0)),
                attempts=entry.get("attempts", 0) + 1,
                checked_at=now_iso(),
            )
            data["last_lesson"] = payload.lesson_id
            target.save_course_progress(data)
            target.append_course_quiz(
                {"lesson_id": payload.lesson_id, "score": score, "answers": payload.answers, "results": results, "submitted_at": now_iso()}
            )
        return {"score": score, "passed": score >= 80, "results": results, "progress": _progress_payload(target)}

    @router.get("/api/vc/course/lesson/{lesson_id}/variant")
    def course_lesson_variant(lesson_id: str, seed: int | None = None) -> dict[str, Any]:
        lesson = lesson_or_404(lesson_id)
        from .variants import lesson_variant

        chosen_seed = seed if seed is not None else int.from_bytes(os.urandom(4), "big")
        return lesson_variant(lesson, chosen_seed)

    @router.get("/api/vc/course/library")
    def course_library() -> dict[str, Any]:
        primary = {chapter["filename"] for chapter in load_course()["chapters"]}
        sources = []
        for identifier, path in sorted(source_paths().items(), key=lambda pair: pair[1].name.lower()):
            stat = path.stat()
            metadata = _file_metadata(str(path), stat.st_mtime_ns, stat.st_size)
            sources.append(
                {"id": identifier, "name": path.name, "kind": path.suffix.lower()[1:], "primary": path.name in primary, **metadata}
            )
        return {
            "sources": sources,
            "primary_pages_mapped": sum(chapter["pages"] for chapter in load_course()["chapters"]),
            "notice": "All available source files are listed. Lesson coverage maps the main lecture slides; supplementary papers, charts and workbooks remain available in full.",
        }

    @router.get("/api/vc/course/source/{identifier}")
    def original_source(identifier: str):
        path = source_paths().get(identifier)
        if path is None:
            raise HTTPException(status_code=404, detail="Course source not found.")
        return FileResponse(path, filename=path.name, content_disposition_type="inline", headers={"Cache-Control": "no-store"})

    def pdf_page(identifier: str, page: int):
        path = source_paths().get(identifier)
        if path is None or path.suffix.lower() != ".pdf":
            raise HTTPException(status_code=404, detail="Course PDF not found.")
        from pypdf import PdfReader

        reader = PdfReader(path)
        if not 1 <= page <= len(reader.pages):
            raise HTTPException(status_code=404, detail="Course page not found.")
        return path, reader

    @router.get("/api/vc/course/source/{identifier}/page/{page}")
    def source_page(identifier: str, page: int) -> dict[str, Any]:
        path, reader = pdf_page(identifier, page)
        return {
            "name": path.name,
            "page": page,
            "pages": len(reader.pages),
            "text": reader.pages[page - 1].extract_text() or "",
            "image_url": f"/api/vc/course/source/{identifier}/page/{page}/image",
        }

    @router.get("/api/vc/course/source/{identifier}/page/{page}/image")
    def source_page_image(identifier: str, page: int):
        path, reader = pdf_page(identifier, page)
        preview_dir = get_store().path("course", "previews")
        preview_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        output = preview_dir / f"{identifier}-{path.stat().st_mtime_ns}-{page}.png"
        with render_lock:
            if not output.is_file():
                with tempfile.TemporaryDirectory(dir=preview_dir) as temp:
                    candidates = [
                        shutil.which("pdftoppm"),
                        str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/pdftoppm"),
                        "/opt/homebrew/bin/pdftoppm",
                        "/usr/local/bin/pdftoppm",
                    ]
                    renderer = next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)
                    if renderer:
                        command = [
                            renderer,
                            "-f",
                            str(page),
                            "-l",
                            str(page),
                            "-singlefile",
                            "-scale-to",
                            "1600",
                            "-png",
                            str(path),
                            str(Path(temp) / "page"),
                        ]
                    elif Path("/usr/bin/sips").is_file():
                        from pypdf import PdfWriter

                        writer = PdfWriter()
                        writer.add_page(reader.pages[page - 1])
                        writer.write(Path(temp) / "page.pdf")
                        command = [
                            "/usr/bin/sips",
                            "-s",
                            "format",
                            "png",
                            str(Path(temp) / "page.pdf"),
                            "--out",
                            str(Path(temp) / "page.png"),
                        ]
                    else:
                        raise HTTPException(
                            status_code=503, detail="Page image preview is unavailable. The original file and text remain accessible."
                        )
                    try:
                        subprocess.run(command, check=True, timeout=35, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        os.replace(Path(temp) / "page.png", output)
                        os.chmod(output, 0o600)
                    except (OSError, subprocess.SubprocessError) as error:
                        raise HTTPException(
                            status_code=503, detail="Could not render this source page; use the text or open the original."
                        ) from error
        return FileResponse(output, media_type="image/png", headers={"Cache-Control": "no-store"})

    @router.get("/api/vc/course/workbook/{identifier}")
    def workbook_preview(identifier: str) -> dict[str, Any]:
        path = source_paths().get(identifier)
        if path is None or path.suffix.lower() != ".xlsx":
            raise HTTPException(status_code=404, detail="Course workbook not found.")
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True, data_only=True)
        formulas = load_workbook(path, read_only=True, data_only=False)
        try:
            sheets = []
            for sheet in book.worksheets:
                rows, formula_rows, row_numbers = [], [], []
                row_limit, column_limit = min(sheet.max_row, 1000), min(sheet.max_column, 64)
                saved = sheet.iter_rows(min_row=1, max_row=row_limit, max_col=column_limit, values_only=True)
                expressions = formulas[sheet.title].iter_rows(min_row=1, max_row=row_limit, max_col=column_limit, values_only=True)
                for number, (cells, raw_cells) in enumerate(zip(saved, expressions), 1):
                    row = ["" if value is None else str(value) for value in cells]
                    formula_row = ["" if value is None else str(value) for value in raw_cells]
                    if any(row) or any(formula_row):
                        rows.append(row)
                        formula_rows.append(formula_row)
                        row_numbers.append(number)
                sheets.append(
                    {
                        "name": sheet.title,
                        "rows": rows,
                        "formula_rows": formula_rows,
                        "row_numbers": row_numbers,
                        "total_rows": sheet.max_row,
                        "total_columns": sheet.max_column,
                        "truncated": sheet.max_row > row_limit or sheet.max_column > column_limit,
                    }
                )
            return {
                "name": path.name,
                "sheets": sheets,
                "notice": "Read-only table preview. Switch between saved values and formulas; no calculation or writing occurs. Charts and formatting remain in the original workbook. Large sheets are limited to 1,000 rows and 64 columns.",
            }
        finally:
            book.close()
            formulas.close()

    return router
