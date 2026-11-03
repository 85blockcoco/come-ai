"""Generation report for cover letters (N100-F10).

A deterministic summary of every letter generation: language, tone, evidence
used/missing, facts and quality scores, approval state.  No personal data
beyond what the caller already supplied.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LetterReport:
    letter_id: str
    language: str
    tone: str
    template_id: str
    evidence_used: int
    evidence_missing: int
    facts_score: float
    completeness_score: float
    approved: bool
    warnings: list[str] = field(default_factory=list)
    generated_at: str = ""


def build_letter_report(
    *,
    letter_id: str,
    language: str,
    tone: str,
    template_id: str,
    evidence_used: list[str],
    evidence_missing: list[str],
    facts_score: float,
    completeness_score: float,
    approved: bool,
    warnings: list[str] | None = None,
    at: str = "",
) -> LetterReport:
    return LetterReport(
        letter_id=letter_id,
        language=language,
        tone=tone,
        template_id=template_id,
        evidence_used=len(evidence_used or []),
        evidence_missing=len(evidence_missing or []),
        facts_score=facts_score,
        completeness_score=completeness_score,
        approved=approved,
        warnings=list(warnings or []),
        generated_at=at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )


def write_report(reports: list[LetterReport], target: str | Path) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def to_dict(r: LetterReport) -> dict[str, Any]:
    return asdict(r)
