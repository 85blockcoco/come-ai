"""Application dossier checklist (N100-G07).

Required documents per dossier type; completeness computed from files the
user actually has.  No generation, no sending.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass
class ChecklistItem:
    document: str
    required: bool
    present: bool


DOSSIERS = ("stage", "international", "banque")


_CHECKS: dict[str, tuple[tuple[str, bool], ...]] = {
    "stage": (
        ("cv", True),
        ("lettre_motivation", True),
        ("id_piece", False),
        ("convention_stage", False),
        ("releves_notes", False),
    ),
}
_CHECKS["international"] = _CHECKS["stage"] + (("couverture_assurance", False),)
_CHECKS["banque"] = _CHECKS["stage"] + (("transcript_english", True),)


def checklist_for(dossier: str, provided: Iterable[str] = ()) -> list[ChecklistItem]:
    key = (dossier or "stage").lower()
    if key not in _CHECKS:
        key = "stage"
    provided_set = {str(p).lower().strip() for p in provided if str(p).strip()}
    return [
        ChecklistItem(document=doc, required=req, present=doc in provided_set)
        for doc, req in _CHECKS[key]
    ]


def completeness(items: Iterable[ChecklistItem]) -> dict[str, Any]:
    it = list(items)
    required = [i for i in it if i.required]
    missing_required = [i.document for i in required if not i.present]
    ok = not missing_required
    ratio = round(sum(1 for i in it if i.present) / len(it), 2) if it else 0.0
    return {"ok": ok, "ratio": ratio, "missing_required": missing_required, "total": len(it)}


def to_dict(i: ChecklistItem) -> dict[str, Any]:
    return asdict(i)
