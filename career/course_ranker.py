"""Ranking helpers for course/education sections (SPEC-021)."""

from __future__ import annotations

from typing import Any

from .course_reformulate import (
    EducationPlan,
    ReformulatedCourse,
    reformulate_education,
)


def _as_plan(profile: Any, offer: Any = None, plan: Any = None) -> EducationPlan:
    if isinstance(plan, EducationPlan):
        return plan
    if isinstance(profile, EducationPlan):
        return profile
    return reformulate_education(profile=profile, offer=offer)


def rank_courses(items: Any, offer: Any = None, profile: Any = None, **kwargs: Any) -> list[str]:
    """Return course ids ordered by relevance (jury score)."""
    offer = offer if offer is not None else kwargs.get("offer") or kwargs.get("job")
    profile = profile if profile is not None else kwargs.get("profile")
    offer_keywords = kwargs.get("offer_keywords") or kwargs.get("keywords")
    if isinstance(items, EducationPlan):
        courses = items.courses
    elif isinstance(items, (list, tuple)):
        # list of strings: return as-is (optionally filtered) to support simple callers
        if items and all(isinstance(x, str) for x in items):
            # If keywords provided, we cannot score strings; return stable original order.
            return list(items)
        courses = list(items)
    else:
        plan = _as_plan(profile, offer, items)
        courses = plan.courses

    # Normalize to ReformulatedCourse-like.
    normalized: list[ReformulatedCourse] = []
    for item in courses:
        if isinstance(item, ReformulatedCourse):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(
                ReformulatedCourse(
                    course_id=str(item.get("course_id", "")),
                    original_title=str(item.get("original_title", item.get("title", ""))),
                    adapted_title=str(item.get("adapted_title", item.get("title", ""))),
                    link_to_stage=str(item.get("link_to_stage", "")),
                    evidence_refs=list(item.get("evidence_refs", [])),
                    rank_delta=int(item.get("rank_delta", 0)),
                    jury_score=float(item.get("jury_score", 0.0)),
                )
            )
    normalized.sort(key=lambda c: (-c.jury_score, c.course_id))
    return [c.course_id for c in normalized]


def rank_education(profile: Any = None, offer: Any = None, **kwargs: Any) -> EducationPlan:
    offer = offer if offer is not None else kwargs.get("offer") or kwargs.get("job")
    profile = profile if profile is not None else kwargs.get("profile")
    return reformulate_education(profile=profile, offer=offer, **{k: v for k, v in kwargs.items() if k not in {"offer", "profile", "job"}})


def reorder_education(profile: Any = None, offer: Any = None, **kwargs: Any) -> EducationPlan:
    return rank_education(profile=profile, offer=offer, **kwargs)


def rank_course_list(profile: Any = None, offer: Any = None, courses: Any = None, **kwargs: Any) -> list[str]:
    if courses is not None:
        return rank_courses(courses, offer=offer, profile=profile)
    plan = rank_education(profile=profile, offer=offer, **kwargs)
    return list(plan.reordered_list)


def apply_ranking(plan: Any) -> list[str]:
    if isinstance(plan, EducationPlan):
        return list(plan.reordered_list)
    if isinstance(plan, dict):
        return list(plan.get("reordered_list", []))
    return [str(item) for item in plan] if isinstance(plan, (list, tuple)) else []


# Aliases
reorder_courses = rank_courses
order_education = rank_education
sort_courses = rank_courses

__all__ = [
    "rank_courses",
    "rank_education",
    "reorder_education",
    "rank_course_list",
    "apply_ranking",
    "reorder_courses",
    "order_education",
    "sort_courses",
]
