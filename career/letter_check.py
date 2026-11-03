"""Fact verification and quality score for cover letters (N100-F05, N100-F06).

Reuses ``claim_check`` for fact tracing and adds letter-specific checks:
salutation/close, placeholders, length.  No auto-send, deterministic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from career.claim_check import check_claims

_PLACEHOLDER_MARKS = ("COMPLÉTER", "COMPLETAR", "AUSZUFÜLLEN", "[NOM]", "[ENTREPRISE]")
_SALUTATIONS = ("madame", "monsieur", "dear", "sehr geehrte", "estimados", "bonjour")
_CLOSINGS = ("cordialement", "sincerely", "grüßen", "atentamente", "bien à vous")
_MIN_WORDS = 40
_MAX_WORDS = 500


@dataclass
class LetterCheckResult:
    facts_ok: bool
    facts_score: float
    invented: int
    inflated: int
    unverifiable: int
    completeness_score: float  # F06 quality 0-100
    violations: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def verify_letter_facts(letter_body: str, evidence: Iterable[str] | None = None) -> dict[str, Any]:
    report = check_claims(letter_body or "", list(evidence or []))
    return {
        "facts_score": report.score,
        "summary": dict(report.summary),
        "invented": report.summary.get("invented", 0),
        "inflated": report.summary.get("inflated", 0),
        "unverifiable": report.summary.get("unverifiable", 0),
    }


def score_letter(letter_body: str, evidence: Iterable[str] | None = None) -> LetterCheckResult:
    text = (letter_body or "").strip()
    low = text.lower()
    violations: list[str] = []
    blockers: list[str] = []

    facts = verify_letter_facts(text, evidence)
    facts_ok = facts["invented"] == 0
    if not facts_ok:
        blockers.append(f"{facts['invented']} affirmation(s) inventée(s)")

    low_words = len(low.split())
    if low_words < _MIN_WORDS:
        violations.append(f"lettre trop courte ({low_words} < {_MIN_WORDS} mots)")
    elif low_words > _MAX_WORDS:
        violations.append(f"lettre trop longue ({low_words} > {_MAX_WORDS} mots)")

    if not any(s in low for s in _SALUTATIONS):
        violations.append("salutation manquante")
    if not any(c in low for c in _CLOSINGS):
        violations.append("formule de politesse manquante")

    ph = [m for m in _PLACEHOLDER_MARKS if m in (letter_body or "")]
    if ph:
        blockers.append(f"placeholder restant: {', '.join(ph[:3])}")

    # F06 completeness score: start from facts, cap deductions for structure.
    score = facts["facts_score"]
    blocked_by_structure = len(violations)
    score = max(0.0, score - 10.0 * blocked_by_structure)
    if blockers:
        score = max(0.0, score - 20.0)
    return LetterCheckResult(
        facts_ok=facts_ok,
        facts_score=facts["facts_score"],
        invented=facts["invented"],
        inflated=facts["inflated"],
        unverifiable=facts["unverifiable"],
        completeness_score=round(score, 1),
        violations=violations,
        blockers=blockers,
    )


def to_dict(r: LetterCheckResult) -> dict[str, Any]:
    return asdict(r)
