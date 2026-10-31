"""Dossier quality scoring (SPEC-042 / CVBOOST-77).

Transparent 0-100 score built from three factors:
  1. validated claims ratio (from claim_check)
  2. exaggeration density penalty
  3. evidence coverage (how many claims have at least one evidence item)

Deterministic, local, no AI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .claim_check import check_claims, ClaimReport, ats_keyword_stuffing


@dataclass
class QualityReport:
    score: float
    validated_ratio: float
    exaggeration_density: float
    evidence_coverage: float
    stuffing_terms: list[str] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)
    claims: list[dict[str, Any]] = field(default_factory=list)


def score_dossier(document: str, evidence: list[str] | None = None) -> QualityReport:
    evidence = evidence or []
    report: ClaimReport = check_claims(document, evidence)
    total = len(report.claims) or 1
    validated = report.summary.get("supported", 0)
    validated_ratio = validated / total
    exaggerations = report.summary.get("inflated", 0) + report.summary.get("invented", 0)
    exaggeration_density = exaggerations / total
    covered = sum(1 for c in report.claims if c.evidence)
    evidence_coverage = covered / total
    stuffing = ats_keyword_stuffing(document)

    # Transparent formula: weighted sum, penalized by stuffing.
    score = (
        0.5 * validated_ratio
        + 0.3 * evidence_coverage
        + 0.2 * (1.0 - exaggeration_density)
    ) * 100.0
    if stuffing:
        score = max(0.0, score - 5.0 * len(stuffing))
    score = round(min(100.0, max(0.0, score)), 1)

    factors = {
        "validated_ratio": round(validated_ratio, 4),
        "evidence_coverage": round(evidence_coverage, 4),
        "exaggeration_density": round(exaggeration_density, 4),
        "stuffing_penalty": float(len(stuffing)),
    }

    return QualityReport(
        score=score,
        validated_ratio=round(validated_ratio, 4),
        exaggeration_density=round(exaggeration_density, 4),
        evidence_coverage=round(evidence_coverage, 4),
        stuffing_terms=stuffing,
        factors=factors,
        claims=[{"text": c.text, "label": c.label, "missing": c.missing, "suggestion": c.suggestion} for c in report.claims],
    )


def to_dict(report: QualityReport) -> dict[str, Any]:
    return {
        "score": report.score,
        "validated_ratio": report.validated_ratio,
        "exaggeration_density": report.exaggeration_density,
        "evidence_coverage": report.evidence_coverage,
        "stuffing_terms": report.stuffing_terms,
        "factors": report.factors,
        "claims": report.claims,
    }