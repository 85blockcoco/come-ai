"""Bounded, local REST facade for the deterministic academics toolkit."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import finance_core, math_core
from .daily_toolkit import Task, daily_plan
from .research_kit import build_outline
from .vc.content import load_content
from .vc.dates import now_iso, today_iso
from .vc.errors import ContentError, InputError, StorageError
from .vc.mastery import build_study_plan, coverage_summary, mastery_radar, radar_payload
from .vc.exams import build_exam, exam_payload, grade_exam, record_exam_result
from .vc.scheduler import (
    answer_session,
    session_payload,
    start_session,
)
from .vc.storage import VcStore


class CalculationPayload(BaseModel):
    operation: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class DailyPlanPayload(BaseModel):
    tasks: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    minutes_per_day: int = Field(default=120, ge=1, le=1_440)
    today: str | None = Field(default=None, max_length=32)


class ResearchOutlinePayload(BaseModel):
    topic: str = Field(default="", max_length=500)
    sections: list[str] = Field(default_factory=list, max_length=30)
    facts: list[str] = Field(default_factory=list, max_length=100)


class VcSessionPayload(BaseModel):
    minutes: int = Field(default=10, ge=1, le=180)
    mode: Literal["quick", "long", "exam_eve", "custom"] = "quick"
    today: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class VcGradePayload(BaseModel):
    grade: Literal["again", "hard", "good", "easy"]
    duration_seconds: int = Field(default=0, ge=0, le=86_400)


class VcExamPayload(BaseModel):
    questions: int = Field(default=20, ge=1, le=100)
    minutes: int = Field(default=30, ge=1, le=240)
    seed: int = Field(default=0, ge=-2_147_483_648, le=2_147_483_647)
    topic_ids: list[str] = Field(default_factory=list, max_length=20)
    new: bool = False


class VcExamAnswerPayload(BaseModel):
    question_id: str = Field(min_length=1, max_length=160)
    answer: str = Field(default="", max_length=12_000)


class VcExamSubmitPayload(BaseModel):
    now: str | None = Field(default=None, max_length=40)


def _vc_context(today: str | None = None):
    """Load only local VC content and learner state for one request."""
    store = VcStore()
    content = load_content().with_cards(store.load_deck())
    day = today or today_iso()
    return store, content, day


def _vc_error(error: Exception) -> dict[str, Any]:
    return {"result": None, "warnings": [], "blockers": [str(error)]}


def _vc_session_view(store: VcStore, content, session, *, reveal: bool = False) -> dict[str, Any]:
    return session_payload(session, content, store.load_progress(), reveal=reveal)


FINANCE_OPERATIONS: dict[str, Callable[..., Any]] = {
    "future_value": finance_core.future_value,
    "present_value": finance_core.present_value,
    "annuity_pv": finance_core.annuity_pv,
    "annuity_fv": finance_core.annuity_fv,
    "npv": finance_core.npv,
    "irr": finance_core.irr,
    "bond_price": finance_core.bond_price,
    "current_ratio": finance_core.current_ratio,
    "quick_ratio": finance_core.quick_ratio,
    "debt_to_equity": finance_core.debt_to_equity,
    "net_margin": finance_core.net_margin,
    "roe": finance_core.roe,
    "compound_rate": finance_core.compound_rate,
}

MATH_OPERATIONS: dict[str, Callable[..., Any]] = {
    "mean": math_core.mean,
    "median": math_core.median,
    "mode": math_core.mode,
    "percentile": math_core.percentile,
    "variance_sample": math_core.variance_sample,
    "values_std": math_core.values_std,
    "zscore": math_core.zscore,
    "outliers_iqr": math_core.outliers_iqr,
    "binomial_pmf": math_core.binomial_pmf,
    "normal_cdf": math_core.normal_cdf,
    "normal_inv": math_core.normal_inv,
    "confidence_interval": math_core.confidence_interval,
    "linear_fit": math_core.linear_fit,
    "solve_linear_system": math_core.solve_linear_system,
    "roots_quadratic": math_core.roots_quadratic,
}


def _calculate(operations: dict[str, Callable[..., Any]], payload: CalculationPayload) -> dict[str, Any]:
    function = operations.get(payload.operation)
    if function is None:
        return {"result": None, "warnings": [], "blockers": ["Opération non autorisée."]}
    try:
        result = function(**payload.arguments)
    except (TypeError, ValueError) as error:
        return {"result": None, "warnings": [], "blockers": [str(error)]}
    if is_dataclass(result):
        result = asdict(result)
    blockers = [] if result is not None else ["Les données fournies ne permettent pas un calcul valide."]
    return {"operation": payload.operation, "result": result, "warnings": [], "blockers": blockers}


def create_academics_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/academics/finance/calculate")
    async def finance_calculate(payload: CalculationPayload) -> dict[str, Any]:
        return _calculate(FINANCE_OPERATIONS, payload)

    @router.post("/api/academics/math/calculate")
    async def math_calculate(payload: CalculationPayload) -> dict[str, Any]:
        return _calculate(MATH_OPERATIONS, payload)

    @router.post("/api/academics/daily/plan")
    async def academics_daily_plan(payload: DailyPlanPayload) -> dict[str, Any]:
        try:
            tasks = [Task(**item) for item in payload.tasks]
        except (TypeError, ValueError) as error:
            return {"plan": None, "warnings": [], "blockers": [str(error)]}
        result = daily_plan(tasks, minutes_per_day=payload.minutes_per_day, today=payload.today)
        result["tasks"] = [asdict(task) for task in result["tasks"]]
        return {"plan": result, "warnings": [], "blockers": []}

    @router.post("/api/academics/research/outline")
    async def research_outline(payload: ResearchOutlinePayload) -> dict[str, Any]:
        outline = build_outline(payload.topic, payload.sections, payload.facts)
        blockers = [] if outline.ok else list(outline.checks)
        return {"outline": asdict(outline), "warnings": [], "blockers": blockers}

    @router.get("/api/academics/vc/status")
    async def vc_status(today: str | None = None) -> dict[str, Any]:
        try:
            store, content, day = _vc_context(today)
            records = mastery_radar(
                content,
                store.load_reviews(),
                today=day,
                case_attempts=store.load_case_attempts(),
                exam_results=store.load_exam_history(),
                progress=store.load_progress(),
            )
            active = store.load_active_session()
            return {
                "content": {
                    "topics": len(content.topics),
                    "cards": len(content.cards),
                    "drills": len(content.drills),
                    "cases": len(content.cases),
                },
                "coverage": coverage_summary(records),
                "due_cards": sum(record.due_cards for record in records),
                "session": _vc_session_view(store, content, active) if active else None,
                "warnings": list(store.warnings),
                "blockers": [],
            }
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.get("/api/academics/vc/radar")
    async def vc_radar(today: str | None = None) -> dict[str, Any]:
        try:
            store, content, day = _vc_context(today)
            records = mastery_radar(
                content,
                store.load_reviews(),
                today=day,
                case_attempts=store.load_case_attempts(),
                exam_results=store.load_exam_history(),
                progress=store.load_progress(),
            )
            return {
                **radar_payload(records, generated_at=now_iso()),
                "coverage": coverage_summary(records),
                "warnings": list(store.warnings),
                "blockers": [],
            }
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.get("/api/academics/vc/plan")
    async def vc_plan(
        minutes: int = 60,
        today: str | None = None,
        exam_date: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= minutes <= 1_440:
            return _vc_error(ValueError("minutes doit être compris entre 1 et 1440."))
        try:
            store, content, day = _vc_context(today)
            records = mastery_radar(
                content,
                store.load_reviews(),
                today=day,
                case_attempts=store.load_case_attempts(),
                exam_results=store.load_exam_history(),
                progress=store.load_progress(),
            )
            plan = build_study_plan(
                content,
                records,
                minutes=minutes,
                today=day,
                exam_date=exam_date or store.load_settings().get("exam_date"),
            )
            return {"plan": plan.to_dict(), "warnings": list(store.warnings), "blockers": []}
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.post("/api/academics/vc/session")
    async def vc_start_session(payload: VcSessionPayload) -> dict[str, Any]:
        try:
            store, content, day = _vc_context(payload.today)
            session = start_session(
                store,
                content,
                minutes=payload.minutes,
                mode=payload.mode,
                today=day,
            )
            return {
                "session": _vc_session_view(store, content, session),
                "warnings": list(store.warnings),
                "blockers": [],
            }
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.get("/api/academics/vc/session/{session_id}")
    async def vc_get_session(session_id: str) -> dict[str, Any]:
        try:
            store, content, _ = _vc_context()
            session = store.load_active_session()
            if session is None or session.session_id != session_id:
                return _vc_error(InputError("Session VC active introuvable ou déjà terminée."))
            return {
                "session": _vc_session_view(store, content, session),
                "warnings": list(store.warnings),
                "blockers": [],
            }
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.post("/api/academics/vc/session/{session_id}/reveal")
    async def vc_reveal_session(session_id: str) -> dict[str, Any]:
        try:
            store, content, _ = _vc_context()
            session = store.load_active_session()
            if session is None or session.session_id != session_id:
                return _vc_error(InputError("Session VC active introuvable ou déjà terminée."))
            return {
                "session": _vc_session_view(store, content, session, reveal=True),
                "warnings": list(store.warnings),
                "blockers": [],
            }
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.post("/api/academics/vc/session/{session_id}/grade")
    async def vc_grade_session(session_id: str, payload: VcGradePayload) -> dict[str, Any]:
        try:
            store, content, _ = _vc_context()
            session = store.load_active_session()
            if session is None or session.session_id != session_id:
                return _vc_error(InputError("Session VC active introuvable ou déjà terminée."))
            session, event = answer_session(
                store,
                content,
                session,
                payload.grade,
                duration_seconds=payload.duration_seconds,
            )
            return {
                "session": _vc_session_view(store, content, session),
                "event": event.to_dict(),
                "warnings": list(store.warnings),
                "blockers": [],
            }
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.post("/api/academics/vc/exam")
    async def vc_start_exam(payload: VcExamPayload) -> dict[str, Any]:
        try:
            store, content, _ = _vc_context()
            active = store.load_active_exam()
            if active is not None and not payload.new:
                exam = exam_payload(active, content)
                exam["resumed"] = True
                return {"exam": exam, "warnings": list(store.warnings), "blockers": []}
            if active is not None:
                store.clear_active_exam()
            exam_model = build_exam(
                content,
                questions=payload.questions,
                minutes=payload.minutes,
                seed=payload.seed,
                topic_ids=payload.topic_ids,
            )
            store.save_active_exam(exam_model)
            exam = exam_payload(exam_model, content)
            exam["resumed"] = False
            return {"exam": exam, "warnings": list(store.warnings), "blockers": []}
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.get("/api/academics/vc/exam/{exam_id}")
    async def vc_get_exam(exam_id: str) -> dict[str, Any]:
        try:
            store, content, _ = _vc_context()
            active = store.load_active_exam()
            if active is None or active.exam_id != exam_id:
                return _vc_error(InputError("Examen actif introuvable ou déjà corrigé."))
            return {"exam": exam_payload(active, content), "warnings": list(store.warnings), "blockers": []}
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.post("/api/academics/vc/exam/{exam_id}/answer")
    async def vc_answer_exam(exam_id: str, payload: VcExamAnswerPayload) -> dict[str, Any]:
        try:
            store, content, _ = _vc_context()
            active = store.load_active_exam()
            if active is None or active.exam_id != exam_id:
                return _vc_error(InputError("Examen actif introuvable ou déjà corrigé."))
            question_ids = {str(item.get("ref_id")) for item in active.questions}
            if payload.question_id not in question_ids:
                return _vc_error(InputError("Cette question ne fait pas partie de l’examen actif."))
            active.answers[payload.question_id] = payload.answer
            store.save_active_exam(active)
            return {"exam": exam_payload(active, content), "warnings": list(store.warnings), "blockers": []}
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    @router.post("/api/academics/vc/exam/{exam_id}/submit")
    async def vc_submit_exam(exam_id: str, payload: VcExamSubmitPayload) -> dict[str, Any]:
        try:
            store, content, _ = _vc_context()
            active = store.load_active_exam()
            if active is None or active.exam_id != exam_id:
                return _vc_error(InputError("Examen actif introuvable ou déjà corrigé."))
            result = grade_exam(active, content, now=payload.now)
            record_exam_result(store, result)
            return {"result": result, "warnings": list(store.warnings), "blockers": []}
        except (ContentError, InputError, StorageError, ValueError) as error:
            return _vc_error(error)

    return router
