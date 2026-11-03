"""Sector filter for job offers (N100-C06)."""

from __future__ import annotations

from typing import Any, Iterable

SECTORS = ("finance", "tech", "consulting", "marketing", "other")

_KEYWORDS: dict[str, list[str]] = {
    "finance": ["finance", "banking", "m&a", "audit", "risk", "trading", "investment"],
    "tech": ["tech", "software", "data", "engineering", "developer", "it"],
    "consulting": ["consulting", "conseil", "strategy", "advisory"],
    "marketing": ["marketing", "communication", "brand", "digital"],
}


def classify_sector(text: str) -> str:
    t = (text or "").lower()
    scores = {s: 0 for s in SECTORS}
    for sector, kws in _KEYWORDS.items():
        for kw in kws:
            if kw in t:
                scores[sector] += 1
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "other"
    return best


def filter_by_sector(offers: Iterable[dict[str, Any]], sector: str) -> list[dict[str, Any]]:
    s = (sector or "").lower()
    if s in ("", "all", "*"):
        return list(offers)
    return [o for o in offers if classify_sector(str(o.get("sector", "") or o.get("description", "") or o.get("title", ""))) == s]