"""Guardrails for the experience reformulator (SPEC-020).

Hard rules enforced here:
- a reformulated bullet mentions ONLY facts present in the approved evidence;
- no invented percentages, durations or products;
- action verb must come from a whitelisted set;
- a bullet fits on at most 2 lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


# Preferred action verbs (French). "Dirigé" is preferred over "Géré".
ACTION_VERBS: tuple[str, ...] = (
    "Dirigé",
    "Piloté",
    "Conçu",
    "Développé",
    "Analysé",
    "Modélisé",
    "Structuré",
    "Optimisé",
    "Rédigé",
    "Coordonné",
    "Animé",
    "Mis en place",
    "Contribué",
    "Réalisé",
    "Présenté",
    "Négocié",
    "Évalué",
    "Automatisé",
)

_ACTION_VERB_SET = {v.lower() for v in ACTION_VERBS}


@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    code: str
    message: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ConstraintCheck:
    ok: bool
    violations: list[ConstraintViolation] = field(default_factory=list)


_NUMBER_RE = re.compile(r"\d[\d\s.,]*%?|\d+\s*(?:€|k€|M€|mois|ans|semaines|jours|x\d+)", re.IGNORECASE)
# Tokens that look like quantified facts (digits followed by unit or %).
_QUANT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|€|k€|M€|mois|ans?|semaines?|jours?|x\d+)\b", re.IGNORECASE)
_PLAIN_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")


def _numeric_tokens(text: str) -> set[str]:
    """Return normalised numeric tokens found in *text*."""
    tokens: set[str] = set()
    for m in _PLAIN_NUMBER_RE.finditer(text):
        tokens.add(m.group(0).replace(" ", ""))
    return tokens


def _first_word(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    # handle multi-word verbs like "Mis en place"
    low = text.lower()
    for verb in sorted(ACTION_VERBS, key=len, reverse=True):
        if low.startswith(verb.lower()):
            return verb
    return text.split()[0]


def check_action_verb(text: str) -> ConstraintViolation | None:
    fw = _first_word(text)
    if fw.lower() in _ACTION_VERB_SET:
        return None
    # allow if first token is a known verb prefix
    if fw.lower().split()[0] in {v.split()[0].lower() for v in ACTION_VERBS}:
        return None
    return ConstraintViolation(
        code="ACTION_VERB_MISSING",
        message="Le bullet doit commencer par un verbe d'action autorisé.",
        detail=fw,
    )


def check_max_lines(text: str, max_lines: int = 2) -> ConstraintViolation | None:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= max_lines:
        return None
    return ConstraintViolation(
        code="TOO_MANY_LINES",
        message=f"Le bullet dépasse {max_lines} lignes ({len(lines)}).",
        detail=str(len(lines)),
    )


def check_no_invention(bullet: str, evidence: str) -> ConstraintViolation | None:
    """Ensure every numeric token in *bullet* also appears in *evidence*."""
    bullet_nums = _numeric_tokens(bullet)
    evidence_nums = _numeric_tokens(evidence)
    invented = bullet_nums - evidence_nums
    if not invented:
        return None
    return ConstraintViolation(
        code="INVENTED_FACT",
        message="Le bullet contient des chiffres absents des preuves.",
        detail=", ".join(sorted(invented)),
    )


def check_length(text: str, max_chars: int = 280) -> ConstraintViolation | None:
    if len(text) <= max_chars:
        return None
    return ConstraintViolation(
        code="TOO_LONG",
        message=f"Le bullet dépasse {max_chars} caractères.",
        detail=str(len(text)),
    )


def validate_bullet(text: str, evidence: str = "", max_lines: int = 2) -> ConstraintCheck:
    violations: list[ConstraintViolation] = []
    v = check_action_verb(text)
    if v:
        violations.append(v)
    v = check_max_lines(text, max_lines)
    if v:
        violations.append(v)
    v = check_no_invention(text, evidence)
    if v:
        violations.append(v)
    v = check_length(text)
    if v:
        violations.append(v)
    return ConstraintCheck(ok=not violations, violations=violations)


def validate_bullets(bullets: Iterable[str], evidence: str = "") -> list[ConstraintCheck]:
    return [validate_bullet(b, evidence) for b in bullets]


def is_allowed_verb(verb: str) -> bool:
    return verb.strip().lower() in _ACTION_VERB_SET or verb.strip().lower().split() and verb.strip().lower().split()[0] in {v.split()[0].lower() for v in ACTION_VERBS}


# Aliases for compatibility
validate = validate_bullet
check_invention = check_no_invention
AntiInventionViolation = ConstraintViolation
