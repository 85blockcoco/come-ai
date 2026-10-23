"""Structure helpers for cover letters (SPEC-022).

A letter is at most four paragraphs:
1. hook
2. proofs
3. projects / courses
4. closing

This module keeps the structural invariants (order, count, connectors) explicit
and reusable by the generator and the triage layer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


KINDS: tuple[str, ...] = ("hook", "proofs", "projects", "closing")
MAX_PARAGRAPHS = 4
MAX_WORDS = 350


@dataclass
class LetterPara:
    kind: str = ""
    text: str = ""
    evidence_refs: list[str] = field(default_factory=list)


def make_paragraph(kind: str, text: str, evidence_refs: Sequence[str] | None = None) -> LetterPara:
    return LetterPara(kind=kind, text=str(text or "").strip(), evidence_refs=list(evidence_refs or []))


def normalize_paragraphs(paragraphs: Iterable[LetterPara | dict[str, Any]] | None) -> list[LetterPara]:
    out: list[LetterPara] = []
    for item in paragraphs or []:
        if isinstance(item, LetterPara):
            out.append(item)
        elif isinstance(item, dict):
            out.append(
                LetterPara(
                    kind=str(item.get("kind") or item.get("type") or ""),
                    text=str(item.get("text") or item.get("paragraph") or ""),
                    evidence_refs=list(item.get("evidence_refs") or []),
                )
            )
        else:
            out.append(LetterPara(kind="", text=str(item)))
    # keep at most MAX_PARAGRAPHS non-empty
    cleaned = [p for p in out if str(p.text).strip()]
    return cleaned[:MAX_PARAGRAPHS]


def ordered_kinds(paragraphs: Sequence[LetterPara]) -> list[str]:
    return [p.kind for p in paragraphs]


def count_words(text: str) -> int:
    return len(str(text or "").split())


def total_words(paragraphs: Sequence[LetterPara]) -> int:
    return sum(count_words(p.text) for p in paragraphs)


def trim_to_word_limit(paragraphs: Sequence[LetterPara], limit: int = MAX_WORDS) -> list[LetterPara]:
    out: list[LetterPara] = []
    used = 0
    for p in paragraphs:
        words = p.text.split()
        if used + len(words) <= limit:
            out.append(p)
            used += len(words)
        else:
            remaining = limit - used
            if remaining > 0:
                trimmed = " ".join(words[:remaining])
                out.append(LetterPara(kind=p.kind, text=trimmed, evidence_refs=list(p.evidence_refs)))
                used = limit
            break
    return out


def validate_structure(paragraphs: Sequence[LetterPara]) -> list[str]:
    issues: list[str] = []
    if len(paragraphs) > MAX_PARAGRAPHS:
        issues.append("too_many_paragraphs")
    if total_words(paragraphs) > MAX_WORDS:
        issues.append("too_many_words")
    for p in paragraphs:
        if not str(p.text).strip():
            issues.append("empty_paragraph")
    return issues


CONNECTORS: dict[str, list[str]] = {
    "hook": [
        "Je suis vivement intéressé(e) par",
        "Votre annonce pour",
        "Le poste de",
    ],
    "proofs": [
        "Mes expériences démontrent",
        "J'ai contribué à",
        "Je mets à profit",
    ],
    "projects": [
        "Mon parcours académique",
        "Mes projets",
        "Au cours de ma formation",
    ],
    "closing": [
        "Je serais ravi(e) d'échanger",
        "Je reste à votre disposition",
        "Dans l'attente de votre retour",
    ],
}


def pick_connector(kind: str, seed: int | None = None) -> str:
    options = CONNECTORS.get(kind, [""])
    if not options:
        return ""
    if seed is None:
        return options[0]
    rng = random.Random(seed)
    return rng.choice(options)


def render_text(paragraphs: Sequence[LetterPara]) -> str:
    return "\n\n".join(p.text for p in paragraphs if str(p.text).strip())


def build_letter_paragraphs(
    *,
    hook: str,
    proofs: str,
    projects: str,
    closing: str,
    evidence: dict[str, list[str]] | None = None,
) -> list[LetterPara]:
    evidence = evidence or {}
    return [
        make_paragraph("hook", hook, evidence.get("hook")),
        make_paragraph("proofs", proofs, evidence.get("proofs")),
        make_paragraph("projects", projects, evidence.get("projects")),
        make_paragraph("closing", closing, evidence.get("closing")),
    ]


__all__ = [
    "LetterPara",
    "KINDS",
    "MAX_PARAGRAPHS",
    "MAX_WORDS",
    "make_paragraph",
    "normalize_paragraphs",
    "ordered_kinds",
    "count_words",
    "total_words",
    "trim_to_word_limit",
    "validate_structure",
    "CONNECTORS",
    "pick_connector",
    "render_text",
    "build_letter_paragraphs",
]


# Compatibility aliases
LetterParagraph = LetterPara
build_paragraphs = build_letter_paragraphs
render = render_text
validate = validate_structure
trim = trim_to_word_limit
