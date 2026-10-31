"""Contract type detection for job offers (N100-B04)."""

from __future__ import annotations

import re

CONTRACT_TYPES = ("stage", "alternance", "cdd", "cdi", "apprentissage", "freelance", "unknown")

_PATTERNS: list[tuple[str, str]] = [
    (r"\bapprentissage\b|\bapprentice\b", "apprentissage"),
    (r"\balternance\b|\balternant\b", "alternance"),
    (r"\bstage\b|\binternship\b|\bintern\b|\bplacement\b|\bpraktikum\b", "stage"),
    (r"\bcdd\b|\bcontrat à durée déterminée\b|\bfixed.term\b", "cdd"),
    (r"\bcdi\b|\bpermanent\b|\bfull.time\b", "cdi"),
    (r"\bfreelance\b|\bindependent\b", "freelance"),
]


def detect_contract_type(text: str) -> str:
    t = (text or "").lower()
    for pat, ctype in _PATTERNS:
        if re.search(pat, t):
            return ctype
    return "unknown"