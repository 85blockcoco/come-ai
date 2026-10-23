"""Triage / ranking helpers for cover letters (SPEC-022).

Generates and ranks drafts. Also exposes simple matching insights that would
normally come from SPEC-021 (course) and SK-21 (matching).
"""

from __future__ import annotations

import random
from typing import Any, Sequence


def rank_drafts(drafts: Sequence[Any]) -> list[Any]:
    """Rank drafts by jury_score (desc), then draft_id for stability."""
    return sorted(drafts, key=lambda d: (-float(getattr(d, "jury_score", 0.0) or 0.0), str(getattr(d, "draft_id", ""))))


def best_draft_id(drafts: Sequence[Any]) -> str:
    ranked = rank_drafts(drafts)
    if not ranked:
        return ""
    return str(getattr(ranked[0], "draft_id", "") or "")


def triage_drafts(drafts: Sequence[Any]) -> dict[str, Any]:
    ranked = rank_drafts(drafts)
    return {
        "ranked_ids": [str(getattr(d, "draft_id", "")) for d in ranked],
        "best_id": best_draft_id(drafts),
        "scores": {str(getattr(d, "draft_id", "")): float(getattr(d, "jury_score", 0.0) or 0.0) for d in drafts},
    }


def course_insight(profile: dict[str, Any] | None, offer: dict[str, Any] | None) -> str:
    """Simple deterministic course-to-stage link (SPEC-021 style)."""
    profile = profile or {}
    offer = offer or {}
    courses = profile.get("courses") or profile.get("education") or ""
    title = offer.get("title") or offer.get("job_title") or "ce stage"
    if isinstance(courses, list):
        course = courses[0] if courses else ""
        if isinstance(course, dict):
            course = course.get("title") or course.get("name") or ""
    else:
        course = str(courses).splitlines()[0] if str(courses).strip() else ""
    if course:
        return f"le cours « {course} » prépare directement à {title}"
    return f"ma formation prépare directement à {title}"


def matching_insight(profile: dict[str, Any] | None, offer: dict[str, Any] | None) -> list[str]:
    """Return overlap keywords between profile skills and offer requirements."""
    profile = profile or {}
    offer = offer or {}
    prof_skills = _to_list(profile.get("skills"))
    req_text = " ".join(str(offer.get(k) or "") for k in ("requirements", "description", "description_original", "skills", "title"))
    req_tokens = {t.lower().strip(".,;:") for t in req_text.split() if len(t) > 3}
    hits = []
    for s in prof_skills:
        if str(s).lower() in req_tokens or any(str(s).lower() in t for t in req_tokens):
            hits.append(str(s))
    # dedupe
    out = []
    for h in hits:
        if h not in out:
            out.append(h)
    return out


def _to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        return [x.strip() for x in value.replace(";", ",").split(",") if x.strip()]
    return [value]


def vary(items: Sequence[Any], seed: int) -> list[Any]:
    rng = random.Random(seed)
    out = list(items)
    rng.shuffle(out)
    return out


__all__ = [
    "rank_drafts",
    "best_draft_id",
    "triage_drafts",
    "course_insight",
    "matching_insight",
    "vary",
]


# Compatibility aliases
triage = triage_drafts
rank = rank_drafts
