"""Candidate profile made of *facts* that the person reviews one by one.

SK-10 : a candidate profile is not a free-text blob.  It is a set of facts,
and every fact keeps the exact provenance of the passage it was extracted
from (page, character offsets and verbatim quote) together with one explicit
review status.

The five statuses are:

``proposed``
    Extracted automatically, waiting for a human decision.
``approved``
    Validated by the person: usable for matching and for applications.
``rejected``
    Refused by the person (OCR error, off-topic, duplicate…).
``modified``
    Corrected by the person *after* it had been approved.  A correction is
    only usable once the person approved it, so editing a ``proposed`` fact
    keeps it ``proposed``.
``suspended``
    Put aside temporarily; it can be brought back later.

Only ``approved`` and ``modified`` facts may justify an application.  Every
other fact is excluded from matching and from candidacy generation.

This module is pure data: no network, no OCR, no file system, no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable


FACT_STATUS_PROPOSED = "proposed"
FACT_STATUS_APPROVED = "approved"
FACT_STATUS_REJECTED = "rejected"
FACT_STATUS_MODIFIED = "modified"
FACT_STATUS_SUSPENDED = "suspended"

FactStatus = str

FACT_STATUSES: tuple[str, ...] = (
    FACT_STATUS_PROPOSED,
    FACT_STATUS_APPROVED,
    FACT_STATUS_REJECTED,
    FACT_STATUS_MODIFIED,
    FACT_STATUS_SUSPENDED,
)

#: The only two statuses allowed to feed matching, kits and CV variants.
USABLE_FACT_STATUSES: tuple[str, ...] = (FACT_STATUS_APPROVED, FACT_STATUS_MODIFIED)

FACT_KIND_SKILL = "skill"
FACT_KIND_EXPERIENCE = "experience"
FACT_KIND_EDUCATION = "education"
FACT_KIND_LANGUAGE = "language"
FACT_KIND_CONTACT = "contact"
FACT_KIND_IDENTITY = "identity"

FACT_KINDS: tuple[str, ...] = (
    FACT_KIND_SKILL,
    FACT_KIND_EXPERIENCE,
    FACT_KIND_EDUCATION,
    FACT_KIND_LANGUAGE,
    FACT_KIND_CONTACT,
    FACT_KIND_IDENTITY,
)

#: Which legacy profile field each fact kind feeds when the profile is active.
FACT_KIND_TO_PROFILE_FIELD: dict[str, str] = {
    FACT_KIND_SKILL: "skills",
    FACT_KIND_EXPERIENCE: "experience",
    FACT_KIND_EDUCATION: "education",
    FACT_KIND_LANGUAGE: "languages",
    FACT_KIND_IDENTITY: "display_name",
}

#: Contact sub-kinds and the legacy profile field they feed.
CONTACT_KIND_TO_PROFILE_FIELD: dict[str, str] = {
    "email": "contact_email",
    "phone": "contact_phone",
    "linkedin": "linkedin_url",
}

#: Status changes a person may perform from the interface.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    FACT_STATUS_PROPOSED: (
        FACT_STATUS_APPROVED,
        FACT_STATUS_REJECTED,
        FACT_STATUS_SUSPENDED,
        FACT_STATUS_MODIFIED,
    ),
    FACT_STATUS_APPROVED: (FACT_STATUS_MODIFIED, FACT_STATUS_REJECTED, FACT_STATUS_SUSPENDED),
    FACT_STATUS_MODIFIED: (FACT_STATUS_APPROVED, FACT_STATUS_REJECTED, FACT_STATUS_SUSPENDED),
    FACT_STATUS_REJECTED: (FACT_STATUS_PROPOSED,),
    FACT_STATUS_SUSPENDED: (
        FACT_STATUS_PROPOSED,
        FACT_STATUS_APPROVED,
        FACT_STATUS_REJECTED,
    ),
}

CANDIDATE_PROFILE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class FactProvenance:
    """Where one fact comes from, exactly.

    Attributes:
        source_document: Original file name of the imported document.
        source_kind: ``cv``, ``linkedin_text``… as chosen by the person.
        extraction: ``text_layer`` for an embedded text layer, ``ocr`` when the
            text was recognised from the page image.
        page: 1-based page number, ``None`` when the source has no pages.
        start_offset: First character offset of the passage in the document.
        end_offset: Last character offset (exclusive) of the passage.
        quote: The verbatim passage, used to check the extraction by eye.
    """

    source_document: str = ""
    source_kind: str = "cv"
    extraction: str = "text_layer"
    page: int | None = None
    start_offset: int = 0
    end_offset: int = 0
    quote: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_document": self.source_document,
            "source_kind": self.source_kind,
            "extraction": self.extraction,
            "page": self.page,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "quote": self.quote,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FactProvenance":
        page = data.get("page")
        try:
            page_number = int(page) if page is not None else None
        except (TypeError, ValueError):
            page_number = None
        return cls(
            source_document=str(data.get("source_document") or ""),
            source_kind=str(data.get("source_kind") or "cv"),
            extraction=str(data.get("extraction") or "text_layer"),
            page=page_number,
            start_offset=_as_int(data.get("start_offset")),
            end_offset=_as_int(data.get("end_offset")),
            quote=str(data.get("quote") or ""),
        )


@dataclass(frozen=True, slots=True)
class CandidateFact:
    """One reviewable fact extracted from an imported document.

    Attributes:
        id: Stable local identifier (``fact_…``).
        kind: One of :data:`FACT_KINDS`.
        label: Short human name shown in the review list.
        value: The factual content (a skill, a level, an entry, an email…).
        status: One of :data:`FACT_STATUSES`.
        provenance: Exact origin of the fact.
        original_value: Value extracted automatically, kept when corrected.
        note: Free note written by the person.
        corrected: ``True`` when the person edited the extracted value.
        requires_review: ``True`` for facts coming from OCR, which are never
            trustworthy enough to be treated as read.
        confidence: Deterministic extraction confidence between 0 and 1.
        created_at: ISO timestamp of the creation.
        updated_at: ISO timestamp of the last review.
    """

    id: str
    kind: str
    label: str
    value: str
    status: str = FACT_STATUS_PROPOSED
    provenance: FactProvenance = FactProvenance()
    original_value: str = ""
    note: str = ""
    corrected: bool = False
    requires_review: bool = False
    confidence: float = 0.0
    created_at: str = ""
    updated_at: str = ""

    @property
    def usable(self) -> bool:
        """``True`` when the fact may justify an application."""
        return self.status in USABLE_FACT_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "value": self.value,
            "status": self.status,
            "usable": self.usable,
            "provenance": self.provenance.to_dict(),
            "original_value": self.original_value,
            "note": self.note,
            "corrected": self.corrected,
            "requires_review": self.requires_review,
            "confidence": round(self.confidence, 3),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateFact":
        provenance = data.get("provenance")
        return cls(
            id=str(data.get("id") or ""),
            kind=str(data.get("kind") or ""),
            label=str(data.get("label") or ""),
            value=str(data.get("value") or ""),
            status=str(data.get("status") or FACT_STATUS_PROPOSED),
            provenance=FactProvenance.from_dict(provenance if isinstance(provenance, dict) else {}),
            original_value=str(data.get("original_value") or ""),
            note=str(data.get("note") or ""),
            corrected=bool(data.get("corrected")),
            requires_review=bool(data.get("requires_review")),
            confidence=float(data.get("confidence") or 0.0),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    """The whole reviewable profile: its source document and its facts."""

    facts: tuple[CandidateFact, ...] = ()
    source_document: str = ""
    source_kind: str = "cv"
    extraction: str = "text_layer"
    page_count: int | None = None
    warnings: tuple[str, ...] = ()
    schema_version: int = CANDIDATE_PROFILE_SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""

    @property
    def usable_facts(self) -> tuple[CandidateFact, ...]:
        return tuple(fact for fact in self.facts if fact.usable)

    def counts_by_status(self) -> dict[str, int]:
        counts = {status: 0 for status in FACT_STATUSES}
        for fact in self.facts:
            counts[fact.status] = counts.get(fact.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_document": self.source_document,
            "source_kind": self.source_kind,
            "extraction": self.extraction,
            "page_count": self.page_count,
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "counts": self.counts_by_status(),
            "facts": [fact.to_dict() for fact in self.facts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateProfile":
        raw_facts = data.get("facts")
        facts = tuple(
            CandidateFact.from_dict(item) for item in raw_facts if isinstance(item, dict)
        ) if isinstance(raw_facts, list) else ()
        warnings = data.get("warnings")
        return cls(
            facts=facts,
            source_document=str(data.get("source_document") or ""),
            source_kind=str(data.get("source_kind") or "cv"),
            extraction=str(data.get("extraction") or "text_layer"),
            page_count=_as_optional_int(data.get("page_count")),
            warnings=tuple(str(item) for item in warnings) if isinstance(warnings, list) else (),
            schema_version=_as_int(data.get("schema_version")) or CANDIDATE_PROFILE_SCHEMA_VERSION,
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


def is_usable_status(status: str) -> bool:
    """Return ``True`` when a status may feed matching and applications."""
    return status in USABLE_FACT_STATUSES


def usable_facts(facts: Iterable[CandidateFact]) -> list[CandidateFact]:
    """Keep only the facts the person approved (or corrected after approval)."""
    return [fact for fact in facts if fact.usable]


def can_transition(current: str, target: str) -> bool:
    """Return ``True`` when a person may move a fact from ``current`` to ``target``."""
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, ())


def apply_review(
    fact: CandidateFact,
    *,
    status: str | None = None,
    value: str | None = None,
    note: str | None = None,
    updated_at: str = "",
) -> CandidateFact:
    """Apply one review action to a fact.

    Correcting the value of a fact that was never approved keeps it
    ``proposed``: a correction is not an approval.  Correcting an approved
    fact turns it into ``modified``, which stays usable.
    """
    if status is not None and status not in FACT_STATUSES:
        raise ValueError(f"Statut de fait inconnu : {status}")

    changes: dict[str, Any] = {}
    if value is not None:
        cleaned = value.strip()
        if cleaned != fact.value:
            changes["value"] = cleaned
            changes["corrected"] = True
            if not fact.original_value:
                changes["original_value"] = fact.value
            if fact.status == FACT_STATUS_APPROVED:
                changes["status"] = FACT_STATUS_MODIFIED
    if note is not None:
        changes["note"] = note.strip()

    target_status = status
    if target_status is not None and target_status != fact.status:
        if not can_transition(fact.status, target_status):
            raise ValueError(
                f"Transition de statut interdite : {fact.status} → {target_status}."
            )
        if target_status == FACT_STATUS_MODIFIED and fact.status != FACT_STATUS_APPROVED:
            # A correction cannot stand in for an approval.
            target_status = FACT_STATUS_PROPOSED
        changes["status"] = target_status

    if not changes:
        return fact
    changes["updated_at"] = updated_at or fact.updated_at
    return replace(fact, **changes)


def active_profile_fields(facts: Iterable[CandidateFact]) -> dict[str, str]:
    """Project the approved facts onto the legacy Career profile fields.

    Only usable facts are read.  A rejected, suspended or still-proposed fact
    never reaches this projection, which is what keeps unapproved content out
    of matching and application generation.
    """
    fields: dict[str, str] = {
        "display_name": "",
        "contact_email": "",
        "contact_phone": "",
        "linkedin_url": "",
        "education": "",
        "experience": "",
        "skills": "",
        "languages": "",
    }
    skills: list[str] = []
    languages: list[str] = []
    education: list[str] = []
    experience: list[str] = []

    for fact in usable_facts(facts):
        if fact.kind == FACT_KIND_SKILL:
            skills.append(fact.value)
        elif fact.kind == FACT_KIND_LANGUAGE:
            languages.append(fact.value)
        elif fact.kind == FACT_KIND_EDUCATION:
            education.append(fact.value)
        elif fact.kind == FACT_KIND_EXPERIENCE:
            experience.append(fact.value)
        elif fact.kind == FACT_KIND_IDENTITY:
            fields["display_name"] = fields["display_name"] or fact.value
        elif fact.kind == FACT_KIND_CONTACT:
            target = CONTACT_KIND_TO_PROFILE_FIELD.get(fact.label.lower())
            if target:
                fields[target] = fields[target] or fact.value

    fields["skills"] = ", ".join(skills)
    fields["languages"] = ", ".join(languages)
    fields["education"] = "\n".join(education)
    fields["experience"] = "\n".join(experience)
    return fields


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
