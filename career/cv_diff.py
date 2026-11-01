"""Visual diff between a CV original and a CV variant (N100-E07).

Line/section-level diff built with difflib only.  The output explains every
change so a human can review it — nothing is applied or exported here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import difflib


@dataclass
class CvDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    changed_sections: list[str] = field(default_factory=list)
    summary: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed


def diff_cvs(original: str, variant: str) -> CvDiff:
    orig = [l for l in (original or "").splitlines()]
    var = [l for l in (variant or "").splitlines()]
    result = CvDiff()
    sm = difflib.SequenceMatcher(a=orig, b=var)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        result.chunks.append({"op": tag, "original_index": i1, "variant_index": j1})
        if tag in ("insert", "replace"):
            result.added.extend(var[j1:j2])
        if tag in ("delete", "replace"):
            result.removed.extend(orig[i1:i2])
        result.changed_sections.append(tag)
    n_add, n_rem = len(result.added), len(result.removed)
    if n_add == 0 and n_rem == 0:
        result.summary = "Aucune différence entre original et variante."
    else:
        result.summary = f"{n_add} ligne(s) ajoutée(s), {n_rem} ligne(s) retirée(s)."
    return result


def explain_changes(diff: CvDiff) -> list[str]:
    lines = [f"- {d.summary}" for d in [diff]]
    return lines


def to_dict(d: CvDiff) -> dict[str, Any]:
    return asdict(d)
