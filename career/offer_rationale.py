"""Explained offer rationale (N100-C05)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class OfferRationale:
    job_id: str
    score: float
    factors: list[tuple[str, float]]
    explanation: str


def build_rationale(job_id: str, score: float, factors: list[tuple[str, float]] | None = None) -> OfferRationale:
    factors = factors or []
    parts = [f"{name} ({val:.2f})" for name, val in factors]
    explanation = f"Offre {job_id} : score {score:.1f}. Facteurs : " + (", ".join(parts) if parts else "aucun")
    return OfferRationale(job_id=job_id, score=score, factors=factors, explanation=explanation)


def to_dict(r: OfferRationale) -> dict[str, Any]:
    return {"job_id": r.job_id, "score": r.score, "factors": r.factors, "explanation": r.explanation}