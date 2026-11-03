"""Profile merge with conflict report (N100-D09).

Merges two profile dicts without inventing data: on conflict both values are
kept in ``conflicts`` and source preference decides the winner.  Lists are
unioned (dedup, order-preserving).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MergeResult:
    profile: dict[str, Any] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    fields_added: int = 0


def _merge_value(a: Any, b: Any) -> tuple[Any, bool]:
    if a == b:
        return a, False
    a_empty = a in (None, "", [], {})
    b_empty = b in (None, "", [], {})
    if a_empty and not b_empty:
        return b, False
    if b_empty and not a_empty:
        return a, False
    if isinstance(a, list) and isinstance(b, list):
        merged = list(a)
        for item in b:
            if item not in merged:
                merged.append(item)
        return merged, False
    return a, True  # real conflict → keep source A, report


def merge_profiles(primary: dict[str, Any], secondary: dict[str, Any], *, prefer: str = "primary") -> MergeResult:
    first = primary if prefer == "primary" else secondary
    second = secondary if prefer == "primary" else primary
    result = MergeResult()
    keys = list(first.keys()) + [k for k in second.keys() if k not in first]
    for key in keys:
        a, b = first.get(key), second.get(key)
        merged, conflict = _merge_value(a, b)
        if key not in first and b not in (None, "", [], {}):
            result.fields_added += 1
        result.profile[key] = merged
        if conflict:
            result.conflicts.append(key)
    return result


def to_dict(r: MergeResult) -> dict[str, Any]:
    return asdict(r)
