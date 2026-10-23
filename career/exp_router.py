"""FastAPI router for the experience reformulator (SPEC-020).

Endpoints:
    POST /reformulate/experience
    POST /reformulate/section
    POST /reformulate/{bullet_id}/apply
    POST /reformulate/{bullet_id}/reject
    GET  /reformulate/{offer_id}/score
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from career.exp_reformulate import (
    ReformulatedBullet,
    build_verdict,
    gap_signals,
    reformulate_experience_async,
    reformulate_section,
)


class ExperienceRequest(BaseModel):
    offer_id: str = Field(default="", max_length=200)
    block_id: str = Field(default="", max_length=200)
    original_text: str = Field(default="", max_length=10_000)
    offer_keywords: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    evidence_text: str = Field(default="", max_length=20_000)
    current_text: str = Field(default="", max_length=10_000)
    profile_skills: list[str] = Field(default_factory=list, max_length=200)
    required_skills: list[str] = Field(default_factory=list, max_length=200)


class SectionRequest(BaseModel):
    offer_id: str = Field(default="", max_length=200)
    blocks: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    offer_keywords: list[str] = Field(default_factory=list, max_length=100)


class ApplyRequest(BaseModel):
    accepted: bool = True
    note: str = Field(default="", max_length=2_000)


# In-memory tracking (best-effort, per-process).
_APPLIED: dict[str, dict[str, Any]] = {}
_REJECTED: dict[str, dict[str, Any]] = {}
_BULLET_STORE: dict[str, ReformulatedBullet] = {}


def _bullet_to_dict(b: ReformulatedBullet) -> dict[str, Any]:
    return {
        "original_block_id": b.original_block_id,
        "text_fr": b.text_fr,
        "variant_actions": list(b.variant_actions),
        "keyword_hits": list(b.keyword_hits),
        "evidence_refs": list(b.evidence_refs),
        "ats_score": b.ats_score,
        "jury_score": b.jury_score,
        "provider": b.provider,
        "version": b.version,
    }


def create_exp_router() -> APIRouter:
    router = APIRouter()

    @router.post("/reformulate/experience")
    async def reformulate_experience_endpoint(payload: ExperienceRequest) -> dict[str, Any]:
        bullets = await reformulate_experience_async(
            original_text=payload.original_text,
            block_id=payload.block_id or "block-0",
            offer_keywords=payload.offer_keywords,
            evidence_refs=payload.evidence_refs,
            evidence_text=payload.evidence_text or payload.original_text,
        )
        verdict = build_verdict(bullets, payload.current_text)
        for b in bullets:
            _BULLET_STORE[b.text_fr] = b
        result = {
            "bullets": [_bullet_to_dict(b) for b in bullets],
            "recommended_combo": list(verdict.recommended_combo),
            "diff_vs_current": verdict.diff_vs_current,
            "gaps": gap_signals(payload.profile_skills, payload.required_skills),
        }
        return result

    @router.post("/reformulate/section")
    async def reformulate_section_endpoint(payload: SectionRequest) -> dict[str, Any]:
        bullets = reformulate_section(
            payload.blocks,
            offer_keywords=payload.offer_keywords,
        )
        for b in bullets:
            _BULLET_STORE[b.text_fr] = b
        return {
            "bullets": [_bullet_to_dict(b) for b in bullets],
            "count": len(bullets),
        }

    @router.post("/reformulate/{bullet_id}/apply")
    async def apply_bullet(bullet_id: str, payload: ApplyRequest | None = None) -> dict[str, Any]:
        # bullet_id may be url-encoded text; look up
        bullet = _BULLET_STORE.get(bullet_id)
        _APPLIED[bullet_id] = {"accepted": True if payload is None else payload.accepted, "note": "" if payload is None else payload.note}
        return {
            "bullet_id": bullet_id,
            "applied": True,
            "found": bullet is not None,
            "diff": bullet.text_fr if bullet else None,
        }

    @router.post("/reformulate/{bullet_id}/reject")
    async def reject_bullet(bullet_id: str, payload: ApplyRequest | None = None) -> dict[str, Any]:
        _REJECTED[bullet_id] = {"note": "" if payload is None else payload.note}
        return {"bullet_id": bullet_id, "rejected": True}

    @router.get("/reformulate/{offer_id}/score")
    async def score_endpoint(offer_id: str) -> dict[str, Any]:
        applied = [b for bid, b in _BULLET_STORE.items() if True]
        # aggregate
        if not applied:
            return {"offer_id": offer_id, "ats_before": 0.0, "ats_after": 0.0, "coverage": 0.0, "gaps": []}
        ats_vals = [b.ats_score for b in applied]
        return {
            "offer_id": offer_id,
            "ats_before": 0.0,
            "ats_after": round(sum(ats_vals) / len(ats_vals), 4),
            "coverage": round(sum(b.ats_score for b in applied) / len(applied), 4),
            "gaps": [],
        }

    return router


# Backwards-friendly alias
def create_router() -> APIRouter:
    return create_exp_router()
