"""Bounded, local REST facade for the deterministic academics toolkit."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import finance_core, math_core
from .daily_toolkit import Task, daily_plan
from .research_kit import build_outline


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

    return router
