"""FR/EN VC lexicon and conservative term-sheet decoder."""

from __future__ import annotations

import re
from typing import Any

from .cases import normalize_text

CLAUSE_PATTERNS = (
    ("liquidation", ("liquidation preference", "preference de liquidation")),
    ("anti_dilution", ("anti-dilution", "anti dilution", "ratchet", "weighted average")),
    ("board", ("board", "conseil d'administration", "board seat")),
    ("drag_along", ("drag-along", "drag along")),
    ("tag_along", ("tag-along", "tag along")),
    ("pro_rata", ("pro-rata", "pro rata", "preemption")),
    ("participation", ("participating", "participation")),
    ("cap", ("cap", "plafond")),
)


def search_glossary(content, query: str) -> list:
    needle = normalize_text(query)
    if not needle:
        return []
    matches = []
    for entry in content.glossary:
        haystack = normalize_text(
            " ".join((entry.term_fr, entry.term_en, entry.definition, entry.example))
        )
        if needle in haystack:
            matches.append(entry)
    return sorted(matches, key=lambda item: normalize_text(item.term_fr))


def _multiple(line: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*x", line, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _clause_payload(kind: str, line: str) -> dict[str, Any]:
    multiple = _multiple(line)
    normalized = normalize_text(line)
    participating = (
        "participating" in normalized
        and "non participating" not in normalized
        and "non-participating" not in normalized
        and "non participant" not in normalized
    )
    capped = re.search(r"\bcap(?:ped)?\b|\bplafond\b", normalized) is not None
    explanations = {
        "liquidation": "The preferred is repaid before ordinary shares.",
        "anti_dilution": "The conversion price is adjusted in a down round.",
        "board": "The board sets strategic decisions and control rights.",
        "drag_along": "A majority shareholder can drag minority shareholders into a sale.",
        "tag_along": "A minority shareholder can sell on the same terms as a majority shareholder.",
        "pro_rata": "L'investisseur peut maintenir sa part lors d'un futur tour.",
        "participation": "The preferred participates in the residual after its preference.",
        "cap": "The total amount received by the preferred is capped.",
    }
    effects = {
        "liquidation": "Reduces the proceeds available to founders in weak exits.",
        "anti_dilution": "Augmente le nombre d'actions de l'investisseur et dilue les autres.",
        "board": "Grants the investor a control or information right.",
        "drag_along": "Facilite une sortie mais limite le choix des minoritaires.",
        "tag_along": "Protects the minority against an unfair sale.",
        "pro_rata": "Protects against dilution but requires additional capital.",
        "participation": "Augmente la part de l'investisseur dans les sorties modestes.",
        "cap": "Limite le gain de l'investisseur sur les grosses sorties.",
    }
    return {
        "clause": kind,
        "source_line": line,
        "multiple": multiple,
        "participating": participating,
        "capped": capped,
        "explanation": explanations[kind],
        "economic_effect": effects[kind],
    }


def decode_term_sheet(content, text: str) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    unknown: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        normalized = normalize_text(line)
        matched = None
        for kind, needles in CLAUSE_PATTERNS:
            if any(needle in normalized for needle in needles):
                matched = kind
                break
        if matched is None:
            unknown.append(line)
        else:
            clauses.append(_clause_payload(matched, line))
    return {
        "clauses": clauses,
        "unknown_clauses": unknown,
        "notice": "Conservative decoding: unrecognised clauses are not invented.",
    }
