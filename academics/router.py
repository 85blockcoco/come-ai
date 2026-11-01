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

    return router
