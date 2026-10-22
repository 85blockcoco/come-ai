"""Typed records for the local personal style memory (SPEC-023).

These structures are deliberately small and JSON-friendly.  They carry only
what the résumé-reformulation workflow needs in order to remember a person's
explicit and implicitly repeated choices.  Nothing here performs I/O, calls a
model, or reaches the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PreferenceSource = Literal["user_pick", "auto_infer", "manual"]

SOURCE_LABELS: dict[str, str] = {
    "user_pick": "Choix explicite",
    "auto_infer": "Déduit des choix répétés",
    "manual": "Réglage manuel",
}


@dataclass(frozen=True, slots=True)
class StylePreference:
    """One remembered stylistic preference.

    ``confidence`` rises with repeated observations and crosses the automatic
    application threshold (0.8) after three identical choices.  ``source``
    distinguishes an explicit pick, an inference, and a manual setting.
    """

    key: str
    value: str
    confidence: float
    source: PreferenceSource
    updated_at: str
    occurrences: int = 1
    auto_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "source_label": SOURCE_LABELS.get(self.source, self.source),
            "updated_at": self.updated_at,
            "occurrences": self.occurrences,
            "auto_applied": self.auto_applied,
        }


@dataclass(frozen=True, slots=True)
class PastChoice:
    """A reversible record of one reformulation choice."""

    context: str
    chosen: dict[str, Any] = field(default_factory=dict)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    id: str = ""
    undone_at: str | None = None

    @property
    def undone(self) -> bool:
        return bool(self.undone_at)

    def to_dict(self, *, include_undone: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "context": self.context,
            "chosen": self.chosen,
            "rejected": self.rejected,
            "evidence_refs": self.evidence_refs,
            "created_at": self.created_at,
            "undone": self.undone,
        }
        if include_undone:
            payload["undone_at"] = self.undone_at
        return payload


@dataclass(frozen=True, slots=True)
class Glossary:
    """A glossary entry learned from a chosen option."""

    term: str
    definition: str
    key: str
    source: PreferenceSource
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "definition": self.definition,
            "key": self.key,
            "source": self.source,
            "source_label": SOURCE_LABELS.get(self.source, self.source),
            "updated_at": self.updated_at,
        }
