"""Generation report for CV variants (N100-E10)."""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CvReport:
    cv_id: str
    variant_id: str
    target_role: str
    language: str
    evidence_used: int
    gaps_reported: int
    quality_score: float
    approved: bool
    diff_added: int
    diff_removed: int
    warnings: list[str] = field(default_factory=list)
    generated_at: str = ""


def build_cv_report(
    *,
    cv_id: str,
    variant_id: str,
    target_role: str,
    language: str,
    evidence_used: list[str],
    gaps_reported: list[str],
    quality_score: float,
    approved: bool,
    diff_added: int,
    diff_removed: int,
    warnings: list[str] | None = None,
    at: str = "",
) -> CvReport:
    return CvReport(
        cv_id=cv_id,
        variant_id=variant_id,
        target_role=target_role,
        language=language,
        evidence_used=len(evidence_used or []),
        gaps_reported=len(gaps_reported or []),
        quality_score=quality_score,
        approved=approved,
        diff_added=diff_added,
        diff_removed=diff_removed,
        warnings=list(warnings or []),
        generated_at=at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )


def write_reports(reports: list[CvReport], target: str | Path) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def to_dict(r: CvReport) -> dict[str, Any]:
    return asdict(r)
