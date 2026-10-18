"""Sentence splitting and unit-aware extraction of the figures stated by a course.

The engine only reads numbers **with a unit** (``12 500 €``, ``6 %``…).  A bare
number inside a formula (``CMPC = part dette x cout de la dette``) is a
coefficient, not a reviewable fact, so it is ignored rather than turned into a
question whose expected answer would be invented.
"""

from __future__ import annotations

import re
from typing import Any

from .models import NUMBER_RE, canonical_unit, clean_text, to_float, unit_label

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý«\"'(])")
BLANK = "…"


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences (abbreviations and decimals are safe)."""

    body = clean_text(text)
    if not body:
        return []
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(body) if part and part.strip()]
    return parts or [body]


def find_numbers(text: str) -> list[dict[str, Any]]:
    """Return every number of ``text`` with its unit, span and canonical key."""

    body = str(text or "")
    found: list[dict[str, Any]] = []
    for match in NUMBER_RE.finditer(body):
        value = to_float(match.group(1))
        if value is None:
            continue
        unit = canonical_unit(match.group(2))
        found.append(
            {
                "value": value,
                "unit": unit,
                "unit_raw": (match.group(2) or "").strip(),
                "start": match.start(1),
                "end": match.end(1),
                "has_unit": unit is not None,
            }
        )
    return found


def extract_numeric_facts(text: str) -> list[dict[str, Any]]:
    """Figures a course states explicitly, kept with the sentence that states them.

    Each fact carries the sentence with the number blanked out, which is what a
    fill-in-the-blank exercise may legitimately ask about.
    """

    facts: list[dict[str, Any]] = []
    for sentence in split_sentences(text):
        for number in find_numbers(sentence):
            if not number["has_unit"]:
                continue
            blanked = f"{sentence[: number['start']]}{BLANK}{sentence[number['end']:]}"
            facts.append(
                {
                    "value": number["value"],
                    "unit": number["unit"],
                    "label": unit_label(number["unit"]),
                    "unit_raw": number["unit_raw"],
                    "sentence": sentence,
                    "blanked_sentence": re.sub(r"\s{2,}", " ", blanked).strip(),
                }
            )
    return facts


def blank_value(sentence: str, value: float) -> str:
    """Replace the first mention of ``value`` in ``sentence`` by a blank."""

    for number in find_numbers(sentence):
        if abs(number["value"] - value) < 1e-9:
            blanked = f"{sentence[: number['start']]}{BLANK}{sentence[number['end']:]}"
            return re.sub(r"\s{2,}", " ", blanked).strip()
    return sentence
