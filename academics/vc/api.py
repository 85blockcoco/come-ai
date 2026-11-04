"""REST facade for the VC revision engine (Révisions tab).

Every endpoint reuses the deterministic engines already used by
``nage.py vc``; nothing is re-implemented here.  The only generative
component is the tutor, and its replies always carry ``source: "ai"``
so the UI can separate them from deterministic or official results.
"""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .cases import case_payload, case_result_payload, evaluate_case
from .content import load_content
from .course import create_course_router, load_course
from .cram import formula_payload
from .dates import new_id, now_iso, today_iso
from .drills import drill_payload, grade_drill, random_drill
from .error_dashboard import error_dashboard
from .exams import build_exam, exam_payload, grade_exam, record_exam_result
from .errors import ContentError, InputError, VcError
from .mastery import build_study_plan, coverage_report, mastery_radar, radar_payload
from .models import DrillAttempt
from .pastpapers import find_paper, grade_paper, load_papers, paper_payload
from .scheduler import answer_session, session_payload, start_session
from .storage import VcStore
from .keychain import KeychainError
from .variants import generated_drill, variant_seed


def _keychain_environment() -> dict[str, str]:
    """Read only NAGe's three Gemini slots; never return them over HTTP."""
    from .keychain import gemini_key_environment

    def bounded_security(args, **kwargs):
        kwargs["timeout"] = 3
        return subprocess.run(args, **kwargs)

    return gemini_key_environment(runner=bounded_security)


# ----------------------------------------------------------------- payloads
class TutorRequest(BaseModel):
    message: str = Field(default="", max_length=4_000)
    mode: str = Field(default="explain", max_length=16)
    topic_id: str | None = Field(default=None, max_length=16)
    student_answer: str | None = Field(default=None, max_length=4_000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)


class ReviewAnswerRequest(BaseModel):
    grade: str = Field(max_length=8)
    duration_seconds: int = Field(default=0, ge=0, le=3_600)


class DrillGradeRequest(BaseModel):
    drill_id: str = Field(min_length=1, max_length=32)
    answer: str = Field(max_length=200)


class DrillDrawRequest(BaseModel):
    topic_id: str | None = Field(default=None, max_length=16)
    seed: int | None = None


class CaseGradeRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class ExamStartRequest(BaseModel):
    questions: int = Field(default=20, ge=1, le=100)
    minutes: int = Field(default=90, ge=1, le=240)
    seed: int | None = None
    topic_ids: list[str] = Field(default_factory=list, max_length=20)
    new: bool = False


class ExamSubmitRequest(BaseModel):
    exam_id: str = Field(min_length=1, max_length=32)
    answers: dict[str, str] = Field(default_factory=dict)


class PaperGradeRequest(BaseModel):
    year: int
    answers: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------- router
def create_vc_router(
    store: VcStore | None = None,
    tutor: Any | None = None,
    *,
    tutor_factory: Any | None = None,
) -> APIRouter:
    """Build the ``/api/vc`` router.

    ``store`` and ``tutor`` are injectable so tests never touch the real
    ``~/.nage/vc`` data or the network.  ``tutor_factory`` is called lazily
    on the first tutor request, keeping app startup free of key handling.
    """
    router = APIRouter()
    # Single-user local app, but FastAPI runs sync handlers in a thread
    # pool: serialise read-modify-write on sessions and exams.
    lock = threading.Lock()
    local_store = store
    local_tutor = tutor

    def get_store() -> VcStore:
        nonlocal local_store
        if local_store is None:
            local_store = VcStore()
        return local_store

    def get_tutor() -> Any:
        nonlocal local_tutor
        if local_tutor is None:
            if tutor_factory is None:
                from vc_tutor import VCTutor

                # Production reads explicitly authorized provider configuration.
                # Loading credentials alone never enables cloud: VC_TUTOR_CLOUD
                # must be true. Explicit-base test apps inject an offline tutor.
                try:
                    credential_env = _keychain_environment()
                except (KeychainError, OSError):
                    # A locked/missing Keychain must not break the course or
                    # prevent use of the explicitly configured .env keys.
                    credential_env = {}
                local_tutor = VCTutor(
                    load_env=True, data_dir=get_store().home,
                    environ={**os.environ, **credential_env},
                )
            else:
                local_tutor = tutor_factory()
        return local_tutor

    def get_content():
        return load_content().with_cards(get_store().load_deck())

    @router.post("/api/vc/tutor/reload")
    def reload_tutor():
        nonlocal local_tutor
        with lock:
            # An injected offline/test tutor must remain injected after reload.
            local_tutor = tutor
            return {"status": "reloaded", "tutor": get_tutor().provider_status()}

    def _radar(content, store: VcStore, day: str):
        return mastery_radar(
            content,
            store.load_reviews(),
            today=day,
            case_attempts=store.load_case_attempts(),
            exam_results=store.load_exam_history(),
            drill_attempts=store.load_drill_attempts(),
            paper_attempts=store.load_paper_attempts(),
            progress=store.load_progress(),
        )

    def _wrap(callable_, *args, **kwargs):
        try:
            return callable_(*args, **kwargs)
        except (InputError, ContentError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except VcError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    # ------------------------------------------------------------- status
    @router.get("/api/vc/status")
    def vc_status() -> dict[str, Any]:
        store = get_store()
        content = get_content()
        settings = store.load_settings()
        exam_date = settings.get("exam_date")
        days_left = None
        if exam_date:
            from datetime import date

            try:
                target = date.fromisoformat(str(exam_date))
                days_left = (target - date.today()).days
            except ValueError:
                days_left = None
        history = store.load_exam_history()
        last_exam = history[-1] if history else None
        try:
            tutor_status = get_tutor().provider_status()
        except Exception:
            tutor_status = {"mode": "unknown", "last_error": "Tutor unavailable."}
        return {
            "subject": "Venture Capital",
            "exam_date": exam_date,
            "exam_duration_minutes": settings.get("exam_duration_minutes", 90),
            "days_left": days_left,
            "counts": {
                "topics": len(content.topics),
                "cards": len(content.cards),
                "drills": len(content.drills),
                "cases": len(content.cases),
                "exam_questions": len(content.exams),
                "papers": len(load_papers()),
            },
            "last_exam": None
            if last_exam is None
            else {
                "exam_id": last_exam.get("exam_id"),
                "score": last_exam.get("score"),
                "submitted_at": last_exam.get("submitted_at"),
            },
            "tutor": tutor_status,
        }

    # ------------------------------------------------------------ coverage
    @router.get("/api/vc/coverage")
    def vc_coverage() -> dict[str, Any]:
        return {"topics": _wrap(coverage_report, get_content())}

    # --------------------------------------------------------------- cases
    @router.get("/api/vc/cases")
    def vc_cases() -> dict[str, Any]:
        content = get_content()
        return {"cases": [case_payload(case) for case in content.cases]}

    @router.post("/api/vc/cases/{case_id}/grade")
    def vc_case_grade(case_id: str, payload: CaseGradeRequest) -> dict[str, Any]:
        content = get_content()
        try:
            case = content.case(case_id)
        except ContentError as error:
            raise HTTPException(status_code=404, detail="Case not found.") from error
        question_ids = {question.id for question in case.questions}
        if set(payload.answers) - question_ids:
            raise HTTPException(status_code=400, detail="Answer contains an unknown case question.")
        if len(payload.answers) > len(question_ids) or any(len(answer) > 4_000 for answer in payload.answers.values()):
            raise HTTPException(status_code=422, detail="Case answers exceed the allowed size.")
        attempt = _wrap(evaluate_case, case, payload.answers)
        with lock:
            get_store().append_case_attempt(attempt)
        return {"result": case_result_payload(attempt), "source": "deterministic"}

    # -------------------------------------------------------------- radar
    @router.get("/api/vc/radar")
    def vc_radar() -> dict[str, Any]:
        store = get_store()
        day = today_iso()
        records = _radar(get_content(), store, day)
        return _wrap(radar_payload, records, generated_at=now_iso())

    # --------------------------------------------------------------- plan
    def _build_plan(minutes: int) -> dict[str, Any]:
        store = get_store()
        content = get_content()
        day = today_iso()
        records = _radar(content, store, day)
        plan = _wrap(
            build_study_plan,
            content,
            records,
            minutes=minutes,
            today=day,
            exam_date=store.load_settings().get("exam_date"),
        )
        return plan.to_dict()

    @router.get("/api/vc/plan")
    def vc_plan(minutes: int = 90) -> dict[str, Any]:
        if not 1 <= minutes <= 600:
            raise HTTPException(status_code=400, detail="minutes must be 1..600")
        return {"plan": _build_plan(minutes)}

    @router.get("/api/vc/next")
    def vc_next(minutes: int = 90) -> dict[str, Any]:
        if not 1 <= minutes <= 600:
            raise HTTPException(status_code=400, detail="minutes must be 1..600")
        plan = _build_plan(minutes)
        activity = plan["activities"][0] if plan.get("activities") else None
        return {"activity": activity, "plan": plan}

    # -------------------------------------------------------------- tutor
    @router.post("/api/vc/tutor")
    def vc_tutor(payload: TutorRequest) -> dict[str, Any]:
        store = get_store()
        content = get_content()
        day = today_iso()

        mastery = None
        if payload.topic_id:
            records = _radar(content, store, day)
            for record in records:
                if record.topic_id == payload.topic_id:
                    mastery = record.to_dict()
                    break
            if mastery is None:
                raise HTTPException(status_code=400, detail=f"Unknown topic: {payload.topic_id}")

        # Recent mistakes, most frequent first, so the tutor can target them.
        errors = _wrap(
            error_dashboard,
            content,
            reviews=store.load_reviews(),
            case_attempts=store.load_case_attempts(),
            drill_attempts=store.load_drill_attempts(),
            exam_results=store.load_exam_history(),
            paper_attempts=store.load_paper_attempts(),
        )
        flat_errors: list[dict[str, Any]] = []
        for entry in errors.get("categories") or []:
            category = str(entry.get("category", ""))
            for topic_id, count in (entry.get("topics") or {}).items():
                flat_errors.append({"category": category, "topic_id": topic_id, "count": count})
        flat_errors.sort(key=lambda item: -int(item["count"]))

        try:
            result = get_tutor().tutor_chat(
                payload.message,
                mode=payload.mode,
                topic_id=payload.topic_id,
                mastery=mastery,
                errors=flat_errors,
                student_answer=payload.student_answer,
                history=payload.history,
            )
        except Exception:
            # A transient provider or local retrieval failure must not turn a
            # tutoring turn into an HTTP 500. Preserve the learning flow and
            # invite a retry without exposing provider details or secrets.
            result = {
                "text": "The tutor is temporarily unavailable. Your answer was not lost. Try again in a moment; the course, drills and mock exams remain available offline.",
                "source": "offline",
                "mode": payload.mode,
                "passages": [],
                "model": None,
                "error": "temporary tutor failure",
            }
        return {
            **result,
            "mastery": mastery,
            "source": result.get("source", "ai"),
        }

    # ------------------------------------------------------------- review
    @router.get("/api/vc/review")
    def vc_review(minutes: int = 10, mode: str = "quick", scope: str = "course") -> dict[str, Any]:
        if scope not in {"course", "all"}:
            raise HTTPException(status_code=400, detail="Review scope must be course or all.")
        store = get_store()
        content = get_content()
        selection = content
        if scope == "course":
            core_topics = {topic for chapter in load_course()["chapters"] for lesson in chapter["lessons"] for topic in lesson["topic_ids"]}
            selection = replace(content, cards=tuple(card for card in content.cards if card.topic_id in core_topics))
        with lock:
            session = _wrap(start_session, store, selection, minutes=minutes, mode=mode)
            payload = _wrap(session_payload, session, content, store.load_progress())
        return {"session": payload, "source": "deterministic"}

    @router.post("/api/vc/review/answer")
    def vc_review_answer(payload: ReviewAnswerRequest) -> dict[str, Any]:
        if payload.grade not in ("again", "hard", "good", "easy"):
            raise HTTPException(status_code=400, detail="grade must be again/hard/good/easy")
        store = get_store()
        content = get_content()
        with lock:
            session = store.load_active_session()
            if session is None:
                raise HTTPException(status_code=409, detail="No active session.")
            session, event = _wrap(
                answer_session,
                store,
                content,
                session,
                payload.grade,
                duration_seconds=payload.duration_seconds,
            )
            result = _wrap(session_payload, session, content, store.load_progress())
        result["last_result"] = {
            "card_id": event.card_id,
            "grade": event.grade,
            "due_after": event.due_after,
        }
        return {"session": result, "source": "deterministic"}

    # -------------------------------------------------------------- drills
    @router.post("/api/vc/drill/draw")
    def vc_drill_draw(payload: DrillDrawRequest) -> dict[str, Any]:
        content = get_content()
        fresh = generated_drill(payload.topic_id, payload.seed if payload.seed is not None else 0)
        if fresh is not None:
            return {"drill": drill_payload(fresh), "source": "generated_variant"}
        drill = _wrap(
            random_drill,
            content.drills,
            topic_id=payload.topic_id,
            seed=payload.seed if payload.seed is not None else 0,
        )
        return {"drill": drill_payload(drill), "source": "deterministic"}

    @router.post("/api/vc/drill/grade")
    def vc_drill_grade(payload: DrillGradeRequest) -> dict[str, Any]:
        store = get_store()
        content = get_content()
        try:
            drill = content.drill(payload.drill_id)
        except ContentError as error:
            seed = variant_seed(payload.drill_id)
            if seed is None:
                raise HTTPException(status_code=400, detail=str(error)) from error
            topic_id = payload.drill_id.split("-", 2)[1].upper()
            drill = generated_drill(topic_id, seed)
            if drill is None:
                raise HTTPException(status_code=400, detail="Unknown drill variant.") from error
        result = grade_drill(drill, payload.answer)
        given = result.get("given")
        given_value = given.get("value") if isinstance(given, dict) else None
        with lock:
            store.append_drill_attempt(
                DrillAttempt(
                    attempt_id=new_id("drill"),
                    drill_id=drill.id,
                    topic_id=drill.topic_id,
                    answer=payload.answer,
                    accepted=bool(result.get("accepted")),
                    expected=float(result.get("expected", drill.answer)),
                    expected_unit=str(result.get("expected_unit", drill.answer_unit)),
                    given_value=given_value,
                    diagnostic=result.get("diagnostic"),
                    submitted_at=now_iso(),
                    message=str(result.get("message", "")),
                )
            )
        return {
            **result,
            "steps": [dict(step) for step in drill.steps],
            "source": "deterministic",
        }

    # --------------------------------------------------------------- exams
    @router.get("/api/vc/exam/state")
    def vc_exam_state() -> dict[str, Any]:
        store = get_store()
        content = get_content()
        active = store.load_active_exam()
        if active is None:
            return {"active": None, "history_size": len(store.load_exam_history())}
        return {
            "active": _wrap(exam_payload, active, content),
            "history_size": len(store.load_exam_history()),
        }

    @router.post("/api/vc/exam/start")
    def vc_exam_start(payload: ExamStartRequest) -> dict[str, Any]:
        store = get_store()
        content = get_content()
        with lock:
            active = store.load_active_exam()
            if active is not None and not payload.new:
                return {
                    "active": _wrap(exam_payload, active, content),
                    "resumed": True,
                    "source": "deterministic",
                }
            if active is not None:
                store.clear_active_exam()
            exam = _wrap(
                build_exam,
                content,
                questions=payload.questions,
                minutes=payload.minutes,
                seed=payload.seed if payload.seed is not None else 0,
                topic_ids=payload.topic_ids,
            )
            store.save_active_exam(exam)
        return {
            "active": _wrap(exam_payload, exam, content),
            "resumed": False,
            "source": "deterministic",
        }

    @router.post("/api/vc/exam/submit")
    def vc_exam_submit(payload: ExamSubmitRequest) -> dict[str, Any]:
        store = get_store()
        content = get_content()
        with lock:
            active = store.load_active_exam()
            if active is None or active.exam_id != payload.exam_id:
                raise HTTPException(status_code=409, detail="Active exam not found.")
            active.answers.update(payload.answers)
            result = _wrap(grade_exam, active, content)
            record_exam_result(store, result)
        return {"result": result, "source": "deterministic"}

    @router.get("/api/vc/exam/last")
    def vc_exam_last() -> dict[str, Any]:
        store = get_store()
        history = store.load_exam_history()
        if not history:
            raise HTTPException(status_code=404, detail="No exam history.")
        return {"result": history[-1], "source": "deterministic"}

    # -------------------------------------------------------------- papers
    @router.get("/api/vc/papers")
    def vc_papers() -> dict[str, Any]:
        return {
            "papers": [
                {
                    "year": paper.year,
                    "title": paper.title,
                    "questions": len(paper.questions),
                    "points": sum(q.points for q in paper.questions),
                }
                for paper in load_papers()
            ]
        }

    @router.get("/api/vc/papers/{year}")
    def vc_paper(year: int, solutions: bool = False) -> dict[str, Any]:
        papers = load_papers()
        try:
            paper = find_paper(year, papers)
        except (InputError, ContentError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {
            "paper": _wrap(paper_payload, paper, solutions=solutions),
            # Official solutions come from the EDHEC correction files.
            "source": "official_solutions" if solutions else "official_exam",
        }

    @router.post("/api/vc/papers/{year}/grade")
    def vc_paper_grade(year: int, payload: PaperGradeRequest) -> dict[str, Any]:
        papers = load_papers()
        try:
            paper = find_paper(year, papers)
        except (InputError, ContentError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        result = _wrap(grade_paper, paper, payload.answers)
        # Same per-topic roll-up as `nage.py vc paper grade`, so the
        # mastery radar sees API submissions exactly like CLI ones.
        per_topic: dict[str, dict[str, float]] = {}
        for item in result.get("items", []):
            if item.get("status") == "self_assess":
                continue
            topic_id = str(item.get("topic_id") or "")
            if not topic_id:
                continue
            bucket = per_topic.setdefault(topic_id, {"attempts": 0, "correct": 0, "earned": 0.0, "max": 0.0})
            bucket["attempts"] += 1
            if item.get("status") == "correct":
                bucket["correct"] += 1
            bucket["earned"] += float(item.get("earned") or 0.0)
            bucket["max"] += float(item.get("max") or 0.0)
        from .models import PaperAttempt

        with lock:
            store = get_store()
            store.append_paper_attempt(
                PaperAttempt(
                    attempt_id=new_id("paper"),
                    paper_id=paper.paper_id,
                    year=paper.year,
                    submitted_at=now_iso(),
                    auto_points=float(result.get("auto_points", 0.0)),
                    auto_max=float(result.get("auto_max", 0.0)),
                    auto_percent=(float(result["auto_percent"]) if result.get("auto_percent") is not None else None),
                    per_topic=per_topic,
                    self_assessment_points=float(result.get("self_assessment_points", 0.0)),
                    notice=str(result.get("notice", "")),
                )
            )
        return {"result": result, "source": "official_solutions"}

    # -------------------------------------------------------------- errors
    @router.get("/api/vc/errors")
    def vc_errors() -> dict[str, Any]:
        store = get_store()
        content = get_content()
        return {
            "dashboard": _wrap(
                error_dashboard,
                content,
                reviews=store.load_reviews(),
                case_attempts=store.load_case_attempts(),
                drill_attempts=store.load_drill_attempts(),
                exam_results=store.load_exam_history(),
                paper_attempts=store.load_paper_attempts(),
            )
        }

    # ------------------------------------------------------------- formulas
    @router.get("/api/vc/formulas")
    def vc_formulas() -> dict[str, Any]:
        return {"sheet": formula_payload(), "source": "deterministic"}

    router.include_router(create_course_router(store=store))
    return router
