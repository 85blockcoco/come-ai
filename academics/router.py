"""Bounded, local REST facade for the deterministic academics toolkit."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date
import inspect
import math
from types import UnionType
from typing import Annotated, Any, Callable, Union, get_args, get_origin, get_type_hints

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, field_validator

from . import finance_core, math_core
from .daily_toolkit import Task, daily_plan
from .research_kit import build_outline
from .vc.models import Card
from .vc.scheduler import start_session, submit_review, summarize_session
from .vc.storage import VCStore
from .vc.mastery import build_radar
from .vc.exams import build_mock_exam, grade_mock_exam


class CalculationPayload(BaseModel):
    operation: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=12)


class TaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=300)
    due: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    estimate_minutes: int = Field(ge=1, le=1_440)
    priority: int = Field(default=2, ge=1, le=3)
    done: bool = False

    @field_validator("due")
    @classmethod
    def valid_due_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class DailyPlanPayload(BaseModel):
    tasks: list[TaskPayload] = Field(default_factory=list, max_length=100)
    minutes_per_day: int = Field(default=120, ge=1, le=1_440)
    today: date | None = None


class ResearchOutlinePayload(BaseModel):
    topic: str = Field(default="", max_length=500)
    sections: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=30)
    facts: list[Annotated[str, Field(max_length=2_000)]] = Field(default_factory=list, max_length=100)


class VCCardsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cards: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class VCSessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    today: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    limit: int = Field(default=10, ge=1, le=100)
    seed: int = Field(default=0, ge=0, le=1_000_000)
    topic: str | None = Field(default=None, max_length=80)
    weak_only: bool = False


class VCReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    card_id: str = Field(min_length=1, max_length=160)
    quality: int = Field(ge=0, le=5)
    reviewed_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class VCExamPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    limit: int = Field(default=5, ge=1, le=20)


class VCExamGradePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    exam_id: str = Field(min_length=1, max_length=160)
    limit: int = Field(default=5, ge=1, le=20)
    answers: dict[str, str] = Field(default_factory=dict, max_length=100)
    elapsed_minutes: int = Field(default=0, ge=0, le=1_440)


class VCSessionSummaryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str = Field(min_length=1, max_length=160)
    card_ids: list[str] = Field(default_factory=list, max_length=100)
    today: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


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


def _bounded_type(annotation: Any, *, matrix: bool = False) -> Any:
    """Infer strict input models only from the fixed, trusted functions above."""
    if annotation is float:
        return Annotated[float, Field(ge=-1e12, le=1e12)]
    if annotation is int:
        return Annotated[int, Field(ge=-10_000, le=10_000)]
    if get_origin(annotation) in (Union, UnionType):
        return Union[tuple(_bounded_type(arg, matrix=matrix) for arg in get_args(annotation))]
    if get_origin(annotation) in (list, tuple):
        item = _bounded_type(get_args(annotation)[0], matrix=matrix)
        # JSON arrays serve both tuple and list annotations in these pure modules.
        return Annotated[list[item], Field(max_length=40 if matrix else 256)]
    raise TypeError("Unsupported input in an academics operation")


def _operation_model(function: Callable[..., Any]) -> type[BaseModel]:
    hints = get_type_hints(function)
    fields = {}
    for name, parameter in inspect.signature(function).parameters.items():
        annotation = _bounded_type(hints[name], matrix=name == "matrix")
        fields[name] = (annotation, ... if parameter.default is inspect.Parameter.empty else parameter.default)
    return create_model(
        f"{function.__name__}Inputs", __config__=ConfigDict(strict=True, extra="forbid", allow_inf_nan=False), **fields,
    )


INPUT_MODELS = {function: _operation_model(function) for function in (*FINANCE_OPERATIONS.values(), *MATH_OPERATIONS.values())}


def _json_result(value: Any) -> Any:
    if isinstance(value, complex):
        return {"real": _json_result(value.real), "imag": _json_result(value.imag)}
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Résultat non fini")
    if isinstance(value, dict):
        return {key: _json_result(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_result(item) for item in value]
    return value


def _calculate(operations: dict[str, Callable[..., Any]], payload: CalculationPayload) -> dict[str, Any]:
    function = operations.get(payload.operation)
    if function is None:
        return {"result": None, "warnings": [], "blockers": ["Opération non autorisée."]}
    try:
        arguments = INPUT_MODELS[function].model_validate(payload.arguments).model_dump()
        if "years" in arguments and arguments["years"] * arguments.get("freq", 2) > 10_000:
            raise ValueError("Trop de périodes de calcul.")
        if payload.operation == "linear_fit" and len(arguments["xs"]) != len(arguments["ys"]):
            raise ValueError("Les deux séries doivent avoir la même longueur.")
        result = function(**arguments)
        result = _json_result(asdict(result) if is_dataclass(result) else result)
    except (ValidationError, TypeError, ValueError, ArithmeticError):
        return {"result": None, "warnings": [], "blockers": ["Vérifie les types, les dimensions et les bornes du calcul."]}
    blockers = [] if result is not None else ["Les données fournies ne permettent pas un calcul valide."]
    return {"operation": payload.operation, "result": result, "warnings": [], "blockers": blockers}


def create_academics_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/academics/finance/calculate")
    def finance_calculate(payload: CalculationPayload) -> dict[str, Any]:
        return _calculate(FINANCE_OPERATIONS, payload)

    @router.post("/api/academics/math/calculate")
    def math_calculate(payload: CalculationPayload) -> dict[str, Any]:
        return _calculate(MATH_OPERATIONS, payload)

    @router.post("/api/academics/daily/plan")
    async def academics_daily_plan(payload: DailyPlanPayload) -> dict[str, Any]:
        try:
            tasks = [Task(**item.model_dump()) for item in payload.tasks]
            for task in tasks:
                date.fromisoformat(task.due)
        except (TypeError, ValueError) as error:
            return {"plan": None, "warnings": [], "blockers": [str(error)]}
        result = daily_plan(tasks, minutes_per_day=payload.minutes_per_day, today=payload.today.isoformat() if payload.today else None)
        result["tasks"] = [asdict(task) for task in result["tasks"]]
        return {"plan": result, "warnings": [], "blockers": []}

    @router.post("/api/academics/research/outline")
    async def research_outline(payload: ResearchOutlinePayload) -> dict[str, Any]:
        outline = build_outline(payload.topic, payload.sections, payload.facts)
        blockers = [] if outline.ok else list(outline.checks)
        return {"outline": asdict(outline), "warnings": [], "blockers": blockers}

    @router.get("/api/academics/vc/status")
    def vc_status() -> dict[str, Any]:
        store = VCStore()
        cards = store.load_cards()
        reviews = store.load_reviews()
        today = date.today().isoformat()
        due = sum(1 for card in cards if card.approved and (card.id not in reviews or str(reviews[card.id].get("due_on", "")) <= today))
        return {"local_only": True, "cards": len(cards), "reviews": len(reviews), "due": due, "suggested_minutes": min(30, max(5, due * 2)) if due else 0, "cloud": False}

    @router.post("/api/academics/vc/cards")
    def vc_cards(payload: VCCardsPayload) -> dict[str, Any]:
        try:
            cards = [Card(**item) for item in payload.cards]
            store = VCStore()
            store.save_cards(cards)
            return {"saved": len(cards), "warnings": [], "blockers": []}
        except (TypeError, ValueError) as error:
            return {"saved": 0, "warnings": [], "blockers": [str(error)]}

    @router.get("/api/academics/vc/cards/{card_id}")
    def vc_card(card_id: str) -> dict[str, Any]:
        card = next((item for item in VCStore().load_cards() if item.id == card_id), None)
        if card is None:
            return {"card": None, "warnings": [], "blockers": ["Carte VC introuvable."]}
        return {"card": {"id": card.id, "topic": card.topic, "back": card.back, "source": card.source}, "warnings": [], "blockers": []}

    @router.post("/api/academics/vc/session")
    def vc_session(payload: VCSessionPayload) -> dict[str, Any]:
        try:
            session_id, cards = start_session(VCStore(), today=payload.today, limit=payload.limit, seed=payload.seed, topic=payload.topic, weak_only=payload.weak_only)
            # Never send the answer in the session response.
            public_cards = [{"id": card.id, "topic": card.topic, "front": card.front, "source": card.source} for card in cards]
            return {"session_id": session_id, "cards": public_cards, "warnings": [], "blockers": []}
        except (TypeError, ValueError) as error:
            return {"session_id": None, "cards": [], "warnings": [], "blockers": [str(error)]}

    @router.post("/api/academics/vc/exam")
    def vc_exam(payload: VCExamPayload) -> dict[str, Any]:
        try:
            exam = build_mock_exam(limit=payload.limit)
            questions = [{"id": item.id, "topic": item.topic, "prompt": item.prompt, "points": item.points} for item in exam.questions]
            return {"exam": {"id": exam.id, "duration_minutes": exam.duration_minutes, "questions": questions}, "warnings": [], "blockers": []}
        except ValueError as error:
            return {"exam": None, "warnings": [], "blockers": [str(error)]}

    @router.post("/api/academics/vc/exam/grade")
    def vc_exam_grade(payload: VCExamGradePayload) -> dict[str, Any]:
        try:
            exam = build_mock_exam(exam_id=payload.exam_id, limit=payload.limit)
            result = grade_mock_exam(exam, payload.answers, elapsed_minutes=payload.elapsed_minutes)
            result_payload = asdict(result)
            VCStore().save_exam(result_payload)
            return {"result": result_payload, "warnings": [], "blockers": []}
        except ValueError as error:
            return {"result": None, "warnings": [], "blockers": [str(error)]}

    @router.get("/api/academics/vc/exams")
    def vc_exams() -> dict[str, Any]:
        return {"exams": VCStore().load_exams(), "warnings": [], "blockers": []}

    @router.post("/api/academics/vc/review")
    def vc_review(payload: VCReviewPayload) -> dict[str, Any]:
        try:
            store = VCStore()
            card = next((item for item in store.load_cards() if item.id == payload.card_id), None)
            if card is None:
                return {"review": None, "warnings": [], "blockers": ["Carte VC introuvable."]}
            review = submit_review(store, card, payload.quality, reviewed_on=payload.reviewed_on)
            return {"review": asdict(review), "warnings": [], "blockers": []}
        except (TypeError, ValueError) as error:
            return {"review": None, "warnings": [], "blockers": [str(error)]}

    @router.post("/api/academics/vc/session/summary")
    def vc_session_summary(payload: VCSessionSummaryPayload) -> dict[str, Any]:
        try:
            summary = asdict(summarize_session(VCStore(), payload.card_ids, today=payload.today, session_id=payload.session_id))
            summary["completed_on"] = payload.today
            VCStore().save_session(summary)
            return {"summary": summary, "warnings": [], "blockers": []}
        except (TypeError, ValueError) as error:
            return {"summary": None, "warnings": [], "blockers": [str(error)]}

    @router.get("/api/academics/vc/sessions")
    def vc_sessions() -> dict[str, Any]:
        return {"sessions": VCStore().load_sessions(), "warnings": [], "blockers": []}

    @router.get("/api/academics/vc/radar")
    def vc_radar() -> dict[str, Any]:
        store = VCStore()
        return {"radar": build_radar(store.load_cards(), store.load_reviews()), "warnings": [], "blockers": []}

    @router.get("/api/academics/vc/card-stats")
    def vc_card_stats() -> dict[str, Any]:
        store = VCStore()
        reviews = store.load_reviews()
        stats = []
        for card in store.load_cards():
            if not card.approved:
                continue
            review = reviews.get(card.id, {})
            stats.append({"id": card.id, "topic": card.topic, "front": card.front, "quality": review.get("quality"), "repetitions": int(review.get("repetitions", 0))})
        stats.sort(key=lambda item: (item["quality"] is not None, item["quality"] if item["quality"] is not None else -1, -item["repetitions"]))
        return {"cards": stats[:50], "warnings": [], "blockers": []}

    return router
