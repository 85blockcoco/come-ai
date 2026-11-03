"""Degree level detection for job offers (N100-B05)."""

from __future__ import annotations

import re

LEVELS = ("phd", "mba", "m2", "m1", "bac+4", "bba", "unknown")

_PATTERNS: list[tuple[str, str]] = [
    (r"\bphd\b|\bdoctorat\b|\bdoctorate\b", "phd"),
    (r"\bmba\b", "mba"),
    (r"\bm1\b|\bmaster\s*1\b", "m1"),
    (r"\bm2\b|\bmaster\s*2\b|\bmaster's?\s*degree\b|\bmaster\b", "m2"),
    (r"\bbac\s*\+?\s*4\b|\bbachelor'?s?\s*degree\b|\bbachelor\b", "bac+4"),
    (r"\bbba\b|\bbachelor of business", "bba"),
]


def detect_degree_level(text: str) -> str:
    t = (text or "").lower()
    for pat, level in _PATTERNS:
        if re.search(pat, t):
            return level
    return "unknown"


def is_accessible_bba_bac4(level: str) -> bool:
    return level in ("bba", "bac+4", "m1", "unknown")