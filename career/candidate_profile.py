"""Candidate facts with their evidence, decided one by one by the person.

This module is the data model of the SK-10 pipeline:

    document → extraction locale → faits proposés → décision utilisateur → profil actif

Two rules are structural, not conventions:

1. A fact never reaches the matching or a candidature draft before the person
   decided it.  Only ``approved`` and ``modified`` facts are usable; a
   ``proposed``, ``rejected`` or ``suspended`` fact can never justify a
   candidature.
2. Every fact keeps the exact place it comes from: page, offsets and quote.

Nothing here calls a network, a model or an inference engine.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence


# ── Statuses ────────────────────────────────────────────────────────────────
STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_MODIFIED = "modified"
STATUS_SUSPENDED = "suspended"

FACT_STATUSES: tuple[str, ...] = (
    STATUS_PROPOSED,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_MODIFIED,
    STATUS_SUSPENDED,
)

#: The only two statuses whose facts may be used to justify a candidature.
USABLE_STATUSES: frozenset[str] = frozenset({STATUS_APPROVED, STATUS_MODIFIED})

#: Explicit state machine of the review.  A fact always goes back to review
#: before it can be decided again.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_PROPOSED: frozenset({STATUS_APPROVED, STATUS_REJECTED, STATUS_MODIFIED, STATUS_SUSPENDED}),
    STATUS_APPROVED: frozenset({STATUS_PROPOSED, STATUS_REJECTED, STATUS_MODIFIED, STATUS_SUSPENDED}),
    STATUS_REJECTED: frozenset({STATUS_PROPOSED, STATUS_SUSPENDED}),
    STATUS_MODIFIED: frozenset({STATUS_PROPOSED, STATUS_APPROVED, STATUS_REJECTED, STATUS_SUSPENDED}),
    STATUS_SUSPENDED: frozenset({STATUS_PROPOSED, STATUS_APPROVED, STATUS_REJECTED, STATUS_MODIFIED}),
}

#: Only the person decides a fact.  No automated path may approve anything.
ACTOR_USER = "user"
ACTOR_SYSTEM = "system"


# ── Decisions ───────────────────────────────────────────────────────────────
DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISION_SUSPEND = "suspend"
DECISION_MODIFY = "modify"
DECISION_REOPEN = "reopen"

DECISIONS: tuple[str, ...] = (
    DECISION_APPROVE,
    DECISION_REJECT,
    DECISION_SUSPEND,
    DECISION_MODIFY,
    DECISION_REOPEN,
)

DECISION_STATUS: dict[str, str] = {
    DECISION_APPROVE: STATUS_APPROVED,
    DECISION_REJECT: STATUS_REJECTED,
    DECISION_SUSPEND: STATUS_SUSPENDED,
    DECISION_MODIFY: STATUS_MODIFIED,
    DECISION_REOPEN: STATUS_PROPOSED,
}

STATUS_LABELS: dict[str, str] = {
    STATUS_PROPOSED: "À vérifier",
    STATUS_APPROVED: "Approuvé",
    STATUS_REJECTED: "Rejeté",
    STATUS_MODIFIED: "Corrigé",
    STATUS_SUSPENDED: "Mis de côté",
}


# ── Kinds ───────────────────────────────────────────────────────────────────
KIND_SKILL = "skill"
KIND_EXPERIENCE = "experience"
KIND_EDUCATION = "education"
KIND_LANGUAGE = "language"
KIND_PROJECT = "project"
KIND_CERTIFICATION = "certification"
KIND_DATE = "date"
KIND_CONTACT = "contact"
KIND_OTHER = "other"

FACT_KINDS: tuple[str, ...] = (
    KIND_SKILL,
    KIND_EXPERIENCE,
    KIND_EDUCATION,
    KIND_LANGUAGE,
    KIND_PROJECT,
    KIND_CERTIFICATION,
    KIND_DATE,
    KIND_CONTACT,
    KIND_OTHER,
)

KIND_LABELS: dict[str, str] = {
    KIND_SKILL: "Compétence",
    KIND_EXPERIENCE: "Expérience",
    KIND_EDUCATION: "Diplôme / formation",
    KIND_LANGUAGE: "Langue",
    KIND_PROJECT: "Projet",
    KIND_CERTIFICATION: "Certification",
    KIND_DATE: "Date",
    KIND_CONTACT: "Coordonnée",
    KIND_OTHER: "Autre fait",
}

#: Local profile field fed by a fact kind.  Kinds without an entry stay in the
#: portable profile but never rewrite a profile field.
KIND_PROFILE_FIELD: dict[str, str] = {
    KIND_SKILL: "skills",
    KIND_EXPERIENCE: "experience",
    KIND_EDUCATION: "education",
    KIND_LANGUAGE: "languages",
}

#: Profile fields a contact fact can complete.  They only fill an empty
#: field: a value written by the person is never replaced.
PROFILE_CONTACT_FIELDS: frozenset[str] = frozenset({"contact_email", "contact_phone"})


# ── Extraction sources ──────────────────────────────────────────────────────
SOURCE_EMBEDDED_TEXT = "embedded_text"
SOURCE_OCR = "ocr"
SOURCE_MANUAL = "manual"

SOURCE_LABELS: dict[str, str] = {
    SOURCE_EMBEDDED_TEXT: "Texte du document",
    SOURCE_OCR: "Lecture OCR locale",
    SOURCE_MANUAL: "Saisie manuelle",
}

#: Sources whose facts can never be approved without an explicit user action.
OCR_SOURCES: frozenset[str] = frozenset({SOURCE_OCR})


# ── Limits ──────────────────────────────────────────────────────────────────
MAX_LABEL_CHARS = 160
MAX_VALUE_CHARS = 2_000
MAX_QUOTE_CHARS = 400
MAX_NOTE_CHARS = 500

PROFILE_FIELD_LIMITS: dict[str, int] = {
    "education": 1_000,
    "experience": 6_000,
    "skills": 4_000,
    "languages": 2_000,
}

DISCLAIMER = (
    "Profil candidat local : seuls les faits approuvés par la personne peuvent "
    "justifier une correspondance ou une candidature. Chaque fait conservé garde "
    "sa source (page, offsets, citation)."
)


def normalize_text(value: object) -> str:
    """Lowercase, strip accents and collapse spaces (comparison only)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass(frozen=True, slots=True)
class Evidence:
    """Where a fact comes from, exactly enough to verify it again.

    Attributes:
        source: ``embedded_text``, ``ocr`` or ``manual``.
        page: 1-based page number, ``0`` when the page is unknown.
        page_confidence: ``exact``, ``estimated`` or ``unknown``.
        start_offset: First character index of the fact inside the source text.
        end_offset: Last character index (exclusive) of the fact.
        quote: The verbatim source passage.
        filename: Original document name, when the fact comes from a document.
    """

    source: str = SOURCE_EMBEDDED_TEXT
    page: int = 0
    page_confidence: str = "unknown"
    start_offset: int = 0
    end_offset: int = 0
    quote: str = ""
    filename: str = ""


@dataclass(frozen=True, slots=True)
class Fact:
    """One candidate fact, with its evidence and its review status.

    Attributes:
        id: Stable local identifier.
        kind: One of :data:`FACT_KINDS`.
        label: Short display name ("Python", "Master Finance", "Anglais").
        value: Optional detail (language level, corrected value, …).
        status: One of :data:`FACT_STATUSES`.
        evidence: The exact source of the fact.
        original_label: Label before a correction (kept for the audit trail).
        original_value: Value before a correction.
        meta: Structured detail extracted with the fact (company, dates, …).
        note: Free note written by the person.
        source_document: Name of the document the fact comes from.
        source_method: ``embedded_text``, ``ocr`` or ``manual``.
        batch_id: Identifier of the extraction batch that produced the fact.
        created_at: Creation timestamp.
        updated_at: Last change timestamp.
        decided_at: Timestamp of the last explicit decision.
    """

    id: str
    kind: str
    label: str
    value: str = ""
    status: str = STATUS_PROPOSED
    evidence: Evidence = field(default_factory=Evidence)
    original_label: str = ""
    original_value: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    note: str = ""
    source_document: str = ""
    source_method: str = SOURCE_EMBEDDED_TEXT
    batch_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    decided_at: str = ""

    @property
    def is_usable(self) -> bool:
        """True when the person approved this fact (directly or by correcting it)."""
        return self.status in USABLE_STATUSES

    @property
    def requires_review(self) -> bool:
        """True while the fact still waits for an explicit decision."""
        return self.status == STATUS_PROPOSED


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    """The set of facts known about the person, with their review state."""

    facts: tuple[Fact, ...] = ()

    def usable_facts(self) -> list[Fact]:
        """Facts approved by the person; the only ones usable for matching."""
        return [fact for fact in self.facts if fact.is_usable]

    def pending_facts(self) -> list[Fact]:
        """Facts extracted but not yet decided."""
        return [fact for fact in self.facts if fact.requires_review]

    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in FACT_STATUSES}
        for fact in self.facts:
            counts[fact.status] = counts.get(fact.status, 0) + 1
        return counts

    def by_kind(self) -> dict[str, list[Fact]]:
        grouped: dict[str, list[Fact]] = {}
        for fact in self.facts:
            grouped.setdefault(fact.kind, []).append(fact)
        return grouped


def serialize_fact(fact: Fact) -> dict[str, Any]:
    """Return the JSON-safe representation of one fact."""
    return {
        "id": fact.id,
        "kind": fact.kind,
        "kind_label": KIND_LABELS.get(fact.kind, fact.kind),
        "label": fact.label,
        "value": fact.value,
        "status": fact.status,
        "status_label": STATUS_LABELS.get(fact.status, fact.status),
        "usable": fact.is_usable,
        "requires_review": fact.requires_review,
        "original_label": fact.original_label,
        "original_value": fact.original_value,
        "meta": dict(fact.meta),
        "note": fact.note,
        "source_document": fact.source_document,
        "source_method": fact.source_method,
        "source_method_label": SOURCE_LABELS.get(fact.source_method, fact.source_method),
        "from_ocr": fact.source_method in OCR_SOURCES,
        "evidence": {
            "source": fact.evidence.source,
            "page": fact.evidence.page,
            "page_confidence": fact.evidence.page_confidence,
            "start_offset": fact.evidence.start_offset,
            "end_offset": fact.evidence.end_offset,
            "quote": fact.evidence.quote,
            "filename": fact.evidence.filename,
        },
        "batch_id": fact.batch_id,
        "created_at": fact.created_at,
        "updated_at": fact.updated_at,
        "decided_at": fact.decided_at,
    }


def serialize_profile(profile: CandidateProfile) -> dict[str, Any]:
    """Return the JSON-safe representation of the whole profile."""
    counts = profile.counts()
    return {
        "facts": [serialize_fact(fact) for fact in profile.facts],
        "counts": counts,
        "usable_count": sum(counts[status] for status in USABLE_STATUSES),
        "pending_count": counts[STATUS_PROPOSED],
        "disclaimer": DISCLAIMER,
    }


def apply_decision(
    fact: Fact,
    decision: str,
    *,
    actor: str = ACTOR_USER,
    value: str = "",
    note: str = "",
    now: str = "",
) -> Fact:
    """Return the fact after one explicit decision made by the person.

    Raises:
        ValueError: If the decision is unknown, if the transition is not
            allowed, if the actor is not the person, or if a correction has no
            value.
    """
    normalized = str(decision or "").strip().casefold()
    if normalized not in DECISIONS:
        raise ValueError(f"Décision inconnue : {decision}")
    status = DECISION_STATUS[normalized]
    if status not in ALLOWED_TRANSITIONS.get(fact.status, frozenset()):
        raise ValueError(
            f"Transition impossible : {fact.status} → {status}."
        )
    if str(actor or "").strip().casefold() != ACTOR_USER:
        # No automated path may approve a fact, and an OCR fact in particular
        # always waits for a human decision.
        raise ValueError("Seule une décision explicite de la personne peut statuer sur un fait.")
    cleaned_value = str(value or "").strip()[:MAX_VALUE_CHARS]
    cleaned_note = str(note or "").strip()[:MAX_NOTE_CHARS]
    if status == STATUS_MODIFIED and not cleaned_value:
        raise ValueError("Une correction exige une valeur.")

    original_label = fact.original_label or fact.label
    original_value = fact.original_value or fact.value
    new_label = fact.label
    new_value = fact.value
    if status == STATUS_MODIFIED:
        # A fact with a structural value (a language level, for example) is
        # corrected on its value; a fact without one is corrected on its label.
        if fact.value:
            new_value = cleaned_value
        else:
            new_label = cleaned_value

    return replace(
        fact,
        status=status,
        label=new_label,
        value=new_value,
        original_label=original_label,
        original_value=original_value,
        note=cleaned_note or fact.note,
        updated_at=now or fact.updated_at,
        decided_at=now if status != STATUS_PROPOSED else "",
    )


def fact_line(fact: Fact) -> str:
    """Render one fact as the single line used inside a profile field."""
    if fact.kind == KIND_EXPERIENCE:
        dates = str(fact.meta.get("dates", "") or "").strip()
        company = str(fact.meta.get("company", "") or "").strip()
        result = str(fact.meta.get("result", "") or "").strip()
        head = " | ".join(part for part in (dates, fact.label, company) if part)
        return f"{head} — {result}" if result else head
    if fact.value:
        return f"{fact.label} — {fact.value}"
    return fact.label


def _field_lines(value: object) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def profile_target(fact: Fact) -> tuple[str, str]:
    """Return the profile field and the exact text a fact writes into it.

    An empty field name means the fact has no place in the profile fields:
    a project, a certification or a date stay in the portable profile but
    never rewrite a profile field.
    """
    if fact.kind == KIND_CONTACT:
        field_name = str(fact.meta.get("field", "") or "")
        if field_name not in PROFILE_CONTACT_FIELDS:
            return "", ""
        value = (fact.value or fact.label).strip()
        return (field_name, value) if value else ("", "")
    field_name = KIND_PROFILE_FIELD.get(fact.kind, "")
    if not field_name:
        return "", ""
    line = fact_line(fact).strip()
    return (field_name, line) if line else ("", "")


def remove_profile_line(value: str, line: str) -> str:
    """Remove one line from a profile field, keeping the other lines intact.

    The line is matched exactly (blanks aside).  A line that is not there is
    left alone: the profile may have been edited by the person in between.
    """
    target = str(line or "").strip()
    if not target:
        return value
    lines = str(value or "").split("\n")
    for index, existing in enumerate(lines):
        if existing.strip() == target:
            lines.pop(index)
            return "\n".join(lines)
    return value


def merge_usable_facts_with_sources(
    profile: Mapping[str, Any],
    facts: Iterable[Fact],
    *,
    limits: Mapping[str, int] | None = None,
) -> tuple[dict[str, Any], dict[str, tuple[str, str]], set[str]]:
    """Return the merged profile, what each fact wrote, and the applied facts.

    Proposed, rejected and suspended facts are never added: they cannot
    justify a candidature.  The manual profile fields are kept as they are.

    The second element maps a fact id to the ``(field, text)`` it really
    added to the profile.  A fact whose content was already in the profile
    contributes nothing: the manual value stays the person's own, and
    reversing that fact must never remove it.

    The third element lists the facts whose content is present in the merged
    profile, whether they wrote it themselves or it was already there.
    """
    merged = dict(profile)
    usable = [fact for fact in facts if fact.is_usable]
    if not usable:
        return merged, {}, set()
    field_limits = dict(PROFILE_FIELD_LIMITS)
    if limits:
        field_limits.update(limits)

    contributions: dict[str, tuple[str, str]] = {}
    applied: set[str] = set()

    for fact in usable:
        if fact.kind != KIND_CONTACT:
            continue
        field_name = str(fact.meta.get("field", "") or "")
        if field_name not in PROFILE_CONTACT_FIELDS:
            continue
        value = (fact.value or fact.label).strip()
        if not value or str(merged.get(field_name, "")).strip():
            # The person already wrote a contact: theirs wins.
            continue
        merged[field_name] = value
        contributions[fact.id] = (field_name, value)
        applied.add(fact.id)

    for kind, field_name in KIND_PROFILE_FIELD.items():
        existing_lines = _field_lines(merged.get(field_name, ""))
        existing_keys = {normalize_text(line) for line in existing_lines}
        added: list[tuple[Fact, str]] = []
        for fact in usable:
            if fact.kind != kind:
                continue
            line = fact_line(fact).strip()
            if not line:
                continue
            key = normalize_text(line)
            if not key or key in existing_keys:
                # Already in the profile: the fact is applied, but it did
                # not write this line and must not remove it later.
                if any(existing.strip() == line for existing in existing_lines):
                    applied.add(fact.id)
                continue
            existing_keys.add(key)
            added.append((fact, line))
        if not added:
            continue
        combined = existing_lines + [line for _, line in added]
        limit = field_limits.get(field_name, 0)
        kept: list[str] = []
        used = 0
        for line in combined:
            if limit and used + len(line) + 1 > limit:
                break
            kept.append(line)
            used += len(line) + 1
        merged[field_name] = "\n".join(kept)
        for fact, line in added:
            if line in kept:
                contributions[fact.id] = (field_name, line)
                applied.add(fact.id)

    return merged, contributions, applied


def merge_usable_facts(
    profile: Mapping[str, Any],
    facts: Iterable[Fact],
    *,
    limits: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Return a copy of the profile enriched with the approved facts only.

    Proposed, rejected and suspended facts are never added: they cannot
    justify a candidature.  The manual profile fields are kept as they are.
    """
    merged, _, _ = merge_usable_facts_with_sources(profile, facts, limits=limits)
    return merged


def export_profile(
    profile: CandidateProfile,
    *,
    generated_at: str = "",
    source_document: str = "",
) -> dict[str, Any]:
    """Return the portable profile: every fact with its evidence and status."""
    counts = profile.counts()
    active_lines: dict[str, list[str]] = {field: [] for field in KIND_PROFILE_FIELD.values()}
    for fact in profile.usable_facts():
        field_name = KIND_PROFILE_FIELD.get(fact.kind)
        if not field_name:
            continue
        line = fact_line(fact).strip()
        if line:
            active_lines[field_name].append(line)
    return {
        "schema": "come-ai-candidate-profile/1",
        "generated_at": generated_at,
        "source_document": source_document,
        "counts": counts,
        "usable_count": sum(counts[status] for status in USABLE_STATUSES),
        "pending_count": counts[STATUS_PROPOSED],
        "facts": [serialize_fact(fact) for fact in profile.facts],
        "active_profile": {field: lines for field, lines in active_lines.items() if lines},
        "disclaimer": DISCLAIMER,
    }


def facts_from_rows(rows: Sequence[Mapping[str, Any]]) -> CandidateProfile:
    """Build a :class:`CandidateProfile` from serialized fact mappings."""
    facts: list[Fact] = []
    for row in rows:
        evidence_data = row.get("evidence")
        evidence = Evidence(**evidence_data) if isinstance(evidence_data, Mapping) else Evidence()
        meta = row.get("meta") if isinstance(row.get("meta"), Mapping) else {}
        facts.append(
            Fact(
                id=str(row.get("id", "")),
                kind=str(row.get("kind", KIND_OTHER)),
                label=str(row.get("label", "")),
                value=str(row.get("value", "")),
                status=str(row.get("status", STATUS_PROPOSED)),
                evidence=evidence,
                original_label=str(row.get("original_label", "")),
                original_value=str(row.get("original_value", "")),
                meta={str(key): str(value) for key, value in meta.items()},
                note=str(row.get("note", "")),
                source_document=str(row.get("source_document", "")),
                source_method=str(row.get("source_method", SOURCE_EMBEDDED_TEXT)),
                batch_id=str(row.get("batch_id", "")),
                created_at=str(row.get("created_at", "")),
                updated_at=str(row.get("updated_at", "")),
                decided_at=str(row.get("decided_at", "")),
            )
        )
    return CandidateProfile(facts=tuple(facts))
