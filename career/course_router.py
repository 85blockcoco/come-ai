"""HTTP routes for course/education reformulation (SPEC-021)."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from workspace_core import to_jsonable

from .course_reformulate import (
    EducationPlan,
    apply_education_plan,
    education_plan_to_dict,
    reformulate_education,
)


class EducationReformulatePayload(BaseModel):
    profile: dict[str, Any] | None = None
    offer: dict[str, Any] | None = None
    job: dict[str, Any] | None = None


class EducationApplyPayload(BaseModel):
    offer_id: str = Field(default="", max_length=120)
    plan: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None


def _build_plan(service: Any, offer_id: str, payload: EducationReformulatePayload | None) -> EducationPlan:
    profile = None
    offer = None
    if payload is not None:
        profile = payload.profile
        offer = payload.offer or payload.job
    if profile is None and service is not None:
        try:
            profile = service.get_profile()
        except Exception:
            profile = {}
    if offer is None and service is not None:
        try:
            offer = service.get_job(offer_id)
        except Exception:
            offer = {"id": offer_id}
    if profile is None:
        profile = {}
    if offer is None:
        offer = {"id": offer_id}
    return reformulate_education(profile=profile, offer=offer)


def create_course_router(
    service: Any = None,
    *,
    ai_generator: Callable[[str], dict[str, Any]] | None = None,
    course_reformulator: Callable[..., Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    reformulator = course_reformulator or reformulate_education

    async def _reformulate_handler(offer_id: str, payload: EducationReformulatePayload | None = None) -> Any:
        plan = await run_in_threadpool(lambda: _build_plan(service, offer_id, payload))
        # Allow injected reformulator override.
        if course_reformulator is not None:
            try:
                profile = payload.profile if payload and payload.profile is not None else (service.get_profile() if service else {})
                offer = (payload.offer or payload.job) if payload else None
                if offer is None and service is not None:
                    offer = service.get_job(offer_id)
                plan = course_reformulator(profile=profile, offer=offer)
            except Exception:
                pass
        if not isinstance(plan, EducationPlan):
            # Best effort conversion.
            try:
                plan = reformulate_education(profile=plan.get("profile", {}) if isinstance(plan, dict) else {}, offer={})
            except Exception:
                pass
        return to_jsonable(education_plan_to_dict(plan))

    async def _apply_handler(payload: EducationApplyPayload) -> Any:
        plan = payload.plan
        if plan is None:
            # Rebuild from service if possible.
            try:
                profile = payload.profile or (service.get_profile() if service else {})
                offer = service.get_job(payload.offer_id) if service and payload.offer_id else {"id": payload.offer_id}
                plan = education_plan_to_dict(reformulate_education(profile=profile, offer=offer))
            except Exception:
                plan = {"courses": [], "reordered_list": [], "certifications_boosted": []}
        profile = payload.profile or (service.get_profile() if service else {})
        result = apply_education_plan(profile, plan)
        return to_jsonable(result)

    apply_paths = (
        "/reformulate/education/apply",
        "/education/apply",
        "/api/reformulate/education/apply",
    )
    for path in apply_paths:
        router.add_api_route(path, _apply_handler, methods=["POST"], name=f"apply_education_{path}")

    paths = (
        "/reformulate/education/{offer_id}",
        "/education/{offer_id}",
        "/api/reformulate/education/{offer_id}",
    )
    for path in paths:
        router.add_api_route(path, _reformulate_handler, methods=["POST"], name=f"reformulate_education_{path}")

    return router


create_router = create_course_router
router = create_course_router()

__all__ = ["create_course_router", "create_router", "router", "EducationReformulatePayload", "EducationApplyPayload"]
