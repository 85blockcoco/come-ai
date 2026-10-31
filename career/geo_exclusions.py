"""Geographic exclusions for job offers (N100-B07)."""

from __future__ import annotations

from typing import Any, Iterable


def is_excluded(location: str, exclusions: Iterable[str]) -> bool:
    loc = (location or "").lower()
    for ex in exclusions or []:
        if str(ex).lower().strip() in loc:
            return True
    return False


def filter_excluded(offers: Iterable[dict[str, Any]], exclusions: Iterable[str], location_key: str = "location") -> list[dict[str, Any]]:
    out = []
    for o in offers:
        loc = str(o.get(location_key, "") or "")
        if not is_excluded(loc, exclusions):
            out.append(o)
    return out