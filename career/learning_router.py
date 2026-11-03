"""HTTP surface for the offline NAGe learning pipeline."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .case_practice import CasePracticeEngine
from .exam import ExamEngine
from .ingest import CorpusError, CorpusIndex, DEFAULT_CORPUS_ROOT
from .plan import VC_CHAPTERS, build_plan
from .quiz import QuizEngine
from .srs import SRSStore
from .summary import build_summary, export_plan_pdf, export_summary_pdf
from .tutor import TutorEngine


class IngestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_dir: str | None = Field(default=None, max_length=500)


class TutorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4_000)
    mode: str = Field(default="explanation", max_length=30)
    section: str | None = Field(default=None, max_length=180)


class SRSReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: str = Field(min_length=8, max_length=80)
    quality: int | None = Field(default=None, ge=0, le=5)
    rating: Literal["again", "hard", "good", "easy"] | None = None


class QuizNextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: str = Field(min_length=2, max_length=180)
    difficulty: str | None = Field(default=None, max_length=30)


class QuizAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=8, max_length=80)
    option_index: int = Field(ge=0, le=10)


class ExamPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: int = Field(default=5, ge=1, le=20)
    chapters: list[str] = Field(default_factory=list, max_length=5)
    duration_minutes: int = Field(default=90, ge=5, le=180)


class ExamAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exam_id: str = Field(min_length=16, max_length=64)
    question_id: str = Field(min_length=8, max_length=80)
    option_index: int = Field(ge=0, le=10)


class ExamSubmitPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exam_id: str = Field(min_length=16, max_length=64)


class CasePracticePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: dict[str, str | int | float | None] = Field(max_length=20)


class LearningWorkspace:
    def __init__(self, base_dir: str | Path, *, corpus_root: str | Path | None = None):
        root = Path(base_dir)
        root.mkdir(parents=True, exist_ok=True)
        configured_root = corpus_root or os.environ.get("NAGE_COURSE_CORPUS") or DEFAULT_CORPUS_ROOT
        self.index = CorpusIndex(root / "corpus.sqlite3", corpus_root=configured_root)
        self.srs = SRSStore(root / "srs.sqlite3")
        self.quiz = QuizEngine(self.index, root / "quiz.sqlite3")
        self.exam = ExamEngine(self.quiz)
        self.practice = CasePracticeEngine(self.index, root / "practice.sqlite3")
        self.pdf_dir = root / "summaries"

    def close(self) -> None:
        self.index.close()
        self.srs.close()
        self.quiz.close()
        self.practice.close()

    def ingest(self, source_dir: str | None = None) -> dict[str, Any]:
        directory = Path(source_dir).expanduser() if source_dir else self.index.corpus_root
        # Explicit local filesystem use is allowed only for a directory, never
        # for a browser-provided individual document or a URL.
        if not directory.is_dir():
            raise CorpusError("Le dossier du corpus local est introuvable.")
        self.index.corpus_root = directory.resolve()
        report = self.index.ingest_directory()
        return {"report": report.to_dict(), "manifest": self.index.manifest()}


def _add_aliases(router: APIRouter, path: str, **kwargs: Any):
    router.get(path, **kwargs)
    return router.get("/api" + path, **kwargs)


def create_learning_router(base_dir: str | Path, *, corpus_root: str | Path | None = None) -> APIRouter:
    workspace = LearningWorkspace(base_dir, corpus_root=corpus_root)
    router = APIRouter(tags=["NAGe learning"])

    async def ingest(payload: IngestPayload | None = None) -> dict[str, Any]:
        try:
            return await run_in_threadpool(workspace.ingest, payload.source_dir if payload else None)
        except CorpusError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    for path in ("/career/ingest", "/career/learning/ingest"):
        router.add_api_route(path, ingest, methods=["POST"])
        router.add_api_route("/api" + path, ingest, methods=["POST"])

    async def manifest() -> dict[str, Any]:
        return await run_in_threadpool(workspace.index.manifest)

    async def coverage() -> dict[str, Any]:
        return await run_in_threadpool(workspace.index.coverage)

    for path in ("/career/manifest", "/career/learning/manifest"):
        router.add_api_route(path, manifest, methods=["GET"])
        router.add_api_route("/api" + path, manifest, methods=["GET"])

    async def chapters() -> dict[str, Any]:
        return {"chapters": await run_in_threadpool(workspace.index.sections), "local_only": True}

    async def search(q: str, limit: int = 8) -> dict[str, Any]:
        hits = await run_in_threadpool(workspace.index.search, q, limit=max(1, min(limit, 20)))
        return {"query": q, "results": [item.citation() | {"score": item.score} for item in hits], "local_only": True}

    for path, endpoint, methods in (("/career/chapters", chapters, ["GET"]), ("/career/search", search, ["GET"]), ("/career/learning/search", search, ["GET"]), ("/career/coverage", coverage, ["GET"])):
        router.add_api_route(path, endpoint, methods=methods)
        router.add_api_route("/api" + path, endpoint, methods=methods)

    async def tutor(payload: TutorPayload) -> dict[str, Any]:
        return (await run_in_threadpool(TutorEngine(workspace.index).ask, payload.question, mode=payload.mode, section=payload.section)).to_dict()

    for path in ("/career/tutor/ask", "/career/tutor/explain"):
        router.add_api_route(path, tutor, methods=["POST"])
        router.add_api_route("/api" + path, tutor, methods=["POST"])

    async def summary(chapter: str) -> dict[str, Any]:
        return (await run_in_threadpool(build_summary, workspace.index, chapter)).to_dict()

    async def summary_pdf(chapter: str) -> FileResponse:
        result = await run_in_threadpool(build_summary, workspace.index, chapter)
        if not result.citations:
            raise HTTPException(status_code=404, detail="Chapitre absent du corpus local.")
        target = workspace.pdf_dir / ("summary-" + str(abs(hash(chapter))) + ".pdf")
        await run_in_threadpool(export_summary_pdf, result, target)
        return FileResponse(target, media_type="application/pdf", filename=target.name)

    for path in ("/career/summary/{chapter}", "/career/learning/summary/{chapter}"):
        router.add_api_route(path, summary, methods=["GET"])
        router.add_api_route("/api" + path, summary, methods=["GET"])
        router.add_api_route(path + "/pdf", summary_pdf, methods=["GET"])
        router.add_api_route("/api" + path + "/pdf", summary_pdf, methods=["GET"])

    async def srs_due(limit: int = 20, chapter: str | None = None) -> dict[str, Any]:
        cards = await run_in_threadpool(workspace.srs.due, limit=limit, chapter=chapter)
        stats = await run_in_threadpool(workspace.srs.stats, chapter=chapter)
        return {"cards": [card.to_dict() for card in cards], "stats": stats, "local_only": True}

    async def srs_generate(chapter: str | None = None, limit: int = 40) -> dict[str, Any]:
        cards = await run_in_threadpool(workspace.srs.generate, workspace.index, chapter=chapter, limit=limit)
        return {"cards": [card.to_dict() for card in cards], "stats": workspace.srs.stats(), "local_only": True}

    async def srs_review(payload: SRSReviewPayload) -> dict[str, Any]:
        try:
            if payload.quality is None and payload.rating is None:
                raise ValueError("Choisis une note Again, Hard, Good ou Easy.")
            quality = payload.quality if payload.quality is not None else workspace.srs.rating_quality(payload.rating or "")
            card = await run_in_threadpool(workspace.srs.review, payload.card_id, quality)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"card": card.to_dict(), "stats": workspace.srs.stats(), "local_only": True}

    for path, endpoint, methods in (("/career/srs/due", srs_due, ["GET"]), ("/career/srs/generate", srs_generate, ["POST"]), ("/career/srs/review", srs_review, ["POST"])):
        router.add_api_route(path, endpoint, methods=methods)
        router.add_api_route("/api" + path, endpoint, methods=methods)

    async def quiz_next(payload: QuizNextPayload) -> dict[str, Any]:
        question = await run_in_threadpool(workspace.quiz.next_question, payload.chapter, difficulty=payload.difficulty)
        if question is None:
            raise HTTPException(status_code=404, detail="Chapitre absent du corpus local.")
        return {"question": question.public(), "mastery": workspace.quiz.mastery(payload.chapter), "local_only": True}

    async def quiz_answer(payload: QuizAnswerPayload) -> dict[str, Any]:
        try:
            return await run_in_threadpool(workspace.quiz.answer, payload.question_id, payload.option_index)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    for path, endpoint in (("/career/quiz/next", quiz_next), ("/career/quiz/answer", quiz_answer)):
        router.add_api_route(path, endpoint, methods=["POST"])
        router.add_api_route("/api" + path, endpoint, methods=["POST"])

    async def plan() -> dict[str, Any]:
        return await run_in_threadpool(build_plan, workspace.quiz)

    async def plan_pdf() -> FileResponse:
        result = await run_in_threadpool(build_plan, workspace.quiz)
        target = workspace.pdf_dir / "revision-plan.pdf"
        await run_in_threadpool(export_plan_pdf, result, target)
        return FileResponse(target, media_type="application/pdf", filename=target.name)

    async def exam(payload: ExamPayload) -> dict[str, Any]:
        chapters = payload.chapters or VC_CHAPTERS
        try:
            return await run_in_threadpool(workspace.exam.start, size=payload.size, chapters=chapters, duration_minutes=payload.duration_minutes)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    async def exam_answer(payload: ExamAnswerPayload) -> dict[str, Any]:
        try:
            return await run_in_threadpool(workspace.exam.answer, payload.exam_id, payload.question_id, payload.option_index)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    async def exam_submit(payload: ExamSubmitPayload) -> dict[str, Any]:
        try:
            return await run_in_threadpool(workspace.exam.submit, payload.exam_id)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    async def practice_cases() -> dict[str, Any]:
        return await run_in_threadpool(workspace.practice.list_cases)

    async def practice_submit(case_id: str, payload: CasePracticePayload) -> dict[str, Any]:
        try:
            return await run_in_threadpool(workspace.practice.submit, case_id, payload.answers)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    for path, endpoint, methods in (
        ("/career/practice/cases", practice_cases, ["GET"]),
        ("/career/practice/cases/{case_id}/submit", practice_submit, ["POST"]),
    ):
        router.add_api_route(path, endpoint, methods=methods)
        router.add_api_route("/api" + path, endpoint, methods=methods)

    async def dashboard() -> dict[str, Any]:
        result = await run_in_threadpool(workspace.quiz.dashboard, VC_CHAPTERS)
        for item in result["notions"]:
            item["score_percent"] = round(item["score"] * 100)
            item.update(workspace.srs.stats(chapter=item["chapter"]))
        result["weak_points"] = [item for item in result["notions"] if not item["mastered"]]
        result["cards_due"] = sum(item["due"] for item in result["notions"])
        result["cards_total"] = sum(item["total"] for item in result["notions"])
        result["exam"] = await run_in_threadpool(workspace.exam.stats)
        return result

    routes = (
        ("/career/plan", plan, ["GET"]),
        ("/career/plan/pdf", plan_pdf, ["GET"]),
        ("/career/exam/start", exam, ["POST"]),
        ("/career/exam/answer", exam_answer, ["POST"]),
        ("/career/exam/submit", exam_submit, ["POST"]),
        ("/career/dashboard", dashboard, ["GET"]),
        ("/career/learning/dashboard", dashboard, ["GET"]),
    )
    for path, endpoint, methods in routes:
        router.add_api_route(path, endpoint, methods=methods)
        # ``/api/career/dashboard`` belongs to the existing application
        # dashboard; the learning dashboard has its explicit learning alias.
        if path != "/career/dashboard":
            router.add_api_route("/api" + path, endpoint, methods=methods)

    return router


__all__ = ["LearningWorkspace", "create_learning_router"]
