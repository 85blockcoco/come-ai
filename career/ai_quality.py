"""AI output quality scoring (N100-I08)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AIQuality:
    score: float
    length_ok: bool
    has_structure: bool
    no_forbidden: bool


FORBIDDEN = ("invented", "fabricated", "hallucinated")


def score_ai_output(text: str) -> AIQuality:
    text = text or ""
    length_ok = 20 <= len(text) <= 5000
    has_structure = "\n" in text or "." in text
    no_forbidden = not any(w in text.lower() for w in FORBIDDEN)
    score = 0.0
    if length_ok:
        score += 40
    if has_structure:
        score += 30
    if no_forbidden:
        score += 30
    return AIQuality(score=score, length_ok=length_ok, has_structure=has_structure, no_forbidden=no_forbidden)