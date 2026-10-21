"""Structured candidate profile: one reviewed fact per item, each with evidence.

This module is a pure data model.  It performs no I/O, never calls a network
service and never uses a language model.  Its only purpose is to describe a
candidate profile made of individually reviewable facts, each of which keeps
the provenance of the document it was extracted from (page, exact offsets and
the quoted passage).

The status of a fact drives everything downstream:

``proposed``
    Extracted automatically, waiting for a human decision.
``approved``
    Validated by the person: usable for matching and for a candidacy.
``rejected``
    Refused by the person (OCR error, out of scope, wrong document).
``modified``
    Corrected by the person: the value was rewritten with their own words.
``suspended``
    Set aside temporarily.

Only ``approved`` and ``modified`` facts may justify a candidacy.  A fact can
never reach one of those two statuses without a recorded human decision
(``decided_at``): that invariant is what guarantees an OCR result, or any
other machine-extracted value, is never approved automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable


FACT_STATUS_PROPOSED = "proposed"
FACT_STATUS_APPROVED = "approved"
FACT_STATUS_REJECTED = "rejected"
FACT_STATUS_MODIFIED = "modified"
FACT_STATUS_SUSPENDED = "suspended"

#: The five statuses a fact can hold.  The order is the reading order used by
#: the review UI: a proposal first, then the four decisions a person can take.
FACT_STATUSES: tuple[str, ...] = (
    FACT_STATUS_PROPOSED,
    FACT_STATUS_APPROVED,
    FACT_STATUS_REJECTED,
    FACT_STATUS_MODIFIED,
    FACT_STATUS_SUSPENDED,
)

FACT_STATUS_LABELS: dict[str, str] = {
    FACT_STATUS_PROPOSED: "À vérifier",
    FACT_STATUS_APPROVED: "Approuvé",
    FACT_STATUS_REJECTED: "Rejeté",
    FACT_STATUS_MODIFIED: "Corrigé",
    FACT_STATUS_SUSPENDED: "Mis de côté",
}

#: Statuses a person can set explicitly.  ``proposed`` is only reachable again
#: by reopening a rejected or suspended fact, never by the machine.
FACT_DECISIONS: tuple[str, ...] = (
    FACT_STATUS_APPROVED,
    FACT_STATUS_REJECTED,
    FACT_STATUS_MODIFIED,
    FACT_STATUS_SUSPENDED,
)

#: A fact is usable for a candidacy only when a person explicitly validated it.
#: ``modified`` counts as validated: the person rewrote the value with their
#: own words, so the value is theirs and not the machine's.
USER_VALIDATED_STATUSES: frozenset[str] = frozenset(
    {FACT_STATUS_APPROVED, FACT_STATUS_MODIFIED}
)

#: Allowed status changes.  Anything else is rejected instead of silently
#: applied, so a review UI can never lose the history of a decision.
ALLOWED_FACT_TRANSITIONS: dict[str, frozenset[str]] = {
    FACT_STATUS_PROPOSED: frozenset(
        {
            FACT_STATUS_APPROVED,
            FACT_STATUS_REJECTED,
            FACT_STATUS_MODIFIED,
            FACT_STATUS_SUSPENDED,
        }
    ),
    FACT_STATUS_APPROVED: frozenset(
        {FACT_STATUS_REJECTED, FACT_STATUS_MODIFIED, FACT_STATUS_SUSPENDED}
    ),
    FACT_STATUS_REJECTED: frozenset(
        {FACT_STATUS_PROPOSED, FACT_STATUS_MODIFIED, FACT_STATUS_SUSPENDED}
    ),
    FACT_STATUS_MODIFIED: frozenset(
        {FACT_STATUS_APPROVED, FACT_STATUS_REJECTED, FACT_STATUS_SUSPENDED}
    ),
    FACT_STATUS_SUSPENDED: frozenset(
        {
            FACT_STATUS_PROPOSED,
            FACT_STATUS_APPROVED,
            FACT_STATUS_REJECTED,
            FACT_STATUS_MODIFIED,
        }
    ),
}

#: The kinds of fact a profile can hold.  ``identity`` and ``contact`` describe
#: who the person is; the other kinds describe what the CV claims.
FACT_KIND_IDENTITY = "identity"
FACT_KIND_CONTACT = "contact"
FACT_KIND_SKILL = "skill"
FACT_KIND_EXPERIENCE = "experience"
FACT_KIND_EDUCATION = "education"
FACT_KIND_LANGUAGE = "language"
FACT_KIND_CERTIFICATION = "certification"
FACT_KIND_PROJECT = "project"

FACT_KINDS: tuple[str, ...] = (
    FACT_KIND_IDENTITY,
    FACT_KIND_CONTACT,
    FACT_KIND_SKILL,
    FACT_KIND_EXPERIENCE,
    FACT_KIND_EDUCATION,
    FACT_KIND_LANGUAGE,
    FACT_KIND_CERTIFICATION,
    FACT_KIND_PROJECT,
)

FACT_KIND_LABELS: dict[str, str] = {
    FACT_KIND_IDENTITY: "Identité",
    FACT_KIND_CONTACT: "Coordonnées",
    FACT_KIND_SKILL: "Compétence",
    FACT_KIND_EXPERIENCE: "Expérience",
    FACT_KIND_EDUCATION: "Formation",
    FACT_KIND_LANGUAGE: "Langue",
    FACT_KIND_CERTIFICATION: "Certification",
    FACT_KIND_PROJECT: "Projet",
}

#: How the text of a fact was obtained.  ``ocr`` is explicitly listed because
#: an OCR result must never be trusted without a human reading it.
EXTRACTION_METHOD_EMBEDDED = "embedded_text"
EXTRACTION_METHOD_OCR = "ocr"
EXTRACTION_METHOD_MANUAL = "manual"

EXTRACTION_METHODS: tuple[str, ...] = (
    EXTRACTION_METHOD_EMBEDDED,
    EXTRACTION_METHOD_OCR,
    EXTRACTION_METHOD_MANUAL,
)

DEFAULT_PROFILE_ID = "candidate_profile"

MAX_FACT_LABEL_CHARS = 160
MAX_FACT_VALUE_CHARS = 4_000
MAX_FACT_NOTE_CHARS = 1_000
MAX_QUOTE_CHARS = 240


class ProfileRuleError(ValueError):
    """Raised when a rule of the profile model is broken."""


@dataclass(frozen=True, slots=True)
class FactProvenance:
    """Where a fact comes from, kept so the person can check it against the source.

    Attributes:
        page: 1-based page number in the source document, ``None`` when the
            source has no reliable pagination (plain text, OCR blob).
        start_offset: First character offset of the passage in the extracted text.
        end_offset: Offset just after the last character of the passage.
        quote: The passage itself, whitespace-normalised and shortened.
        source_name: Name of the local document the fact was extracted from.
        extraction_method: ``embedded_text``, ``ocr`` or ``manual``.
    """

    page: int | None = None
    start_offset: int = 0
    end_offset: int = 0
    quote: str = ""
    source_name: str = ""
    extraction_method: str = EXTRACTION_METHOD_EMBEDDED

    @property
    def is_ocr(self) -> bool:
        """True when the passage was read by OCR instead of the embedded text layer."""
        return self.extraction_method == EXTRACTION_METHOD_OCR

    @property
    def requires_review(self) -> bool:
        """True when the value was produced by a machine and still needs a human."""
        return self.extraction_method in (EXTRACTION_METHOD_EMBEDDED, EXTRACTION_METHOD_OCR)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "quote": self.quote,
            "source_name": self.source_name,
            "extraction_method": self.extraction_method,
            "is_ocr": self.is_ocr,
            "requires_review": self.requires_review,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "FactProvenance":
        if not isinstance(payload, dict):
            return cls()
        page = payload.get("page")
        method = str(payload.get("extraction_method") or EXTRACTION_METHOD_EMBEDDED)
        if method not in EXTRACTION_METHODS:
            method = EXTRACTION_METHOD_EMBEDDED
        return cls(
            page=int(page) if isinstance(page, int) and page > 0 else None,
            start_offset=max(0, int(payload.get("start_offset") or 0)),
            end_offset=max(0, int(payload.get("end_offset") or 0)),
            quote=str(payload.get("quote") or "")[:MAX_QUOTE_CHARS],
            source_name=str(payload.get("source_name") or "")[:MAX_FACT_LABEL_CHARS],
            extraction_method=method,
        )


@dataclass(frozen=True, slots=True)
class CandidateFact:
    """One reviewable item of the candidate profile.

    Attributes:
        id: Stable local identifier of the fact.
        kind: One of :data:`FACT_KINDS`.
        label: Short human label shown in the review UI.
        value: The fact itself; this is what a candidacy would rely on.
        status: One of :data:`FACT_STATUSES`.
        provenance: Where the value was read in the source document.
        original_value: The machine-extracted value, kept when a person
            corrects a fact so the correction stays auditable.
        note: Free note written by the person.
        decided_at: Timestamp of the human decision.  Empty while the fact is
            still ``proposed``; this is what makes automatic approval impossible.
        created_at: Creation timestamp.
        updated_at: Last change timestamp.
        metadata: Extra structured detail (company, role, dates…) used by the
            matching pipeline.  Never a reason to skip the review.
    """

    id: str
    kind: str
    label: str
    value: str
    status: str = FACT_STATUS_PROPOSED
    provenance: FactProvenance | None = None
    original_value: str = ""
    note: str = ""
    decided_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def is_usable(self) -> bool:
        """True when the fact was validated by a person and may justify a candidacy."""
        return self.status in USER_VALIDATED_STATUSES and bool(self.decided_at)

    @property
    def is_ocr(self) -> bool:
        """True when the fact was read by OCR."""
        return bool(self.provenance and self.provenance.is_ocr)

    @property
    def status_label(self) -> str:
        return FACT_STATUS_LABELS.get(self.status, self.status)

    @property
    def kind_label(self) -> str:
        return FACT_KIND_LABELS.get(self.kind, self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "kind_label": self.kind_label,
            "label": self.label,
            "value": self.value,
            "status": self.status,
            "status_label": self.status_label,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "original_value": self.original_value,
            "note": self.note,
            "decided_at": self.decided_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "is_usable": self.is_usable,
            "is_ocr": self.is_ocr,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "CandidateFact":
        if not isinstance(payload, dict):
            raise ProfileRuleError("Un fait de profil est invalide.")
        status = str(payload.get("status") or FACT_STATUS_PROPOSED)
        if status not in FACT_STATUSES:
            raise ProfileRuleError("Un fait de profil porte un statut inconnu.")
        kind = str(payload.get("kind") or FACT_KIND_SKILL)
        if kind not in FACT_KINDS:
            raise ProfileRuleError("Un fait de profil porte un type inconnu.")
        metadata = payload.get("metadata")
        return cls(
            id=str(payload.get("id") or "")[:120],
            kind=kind,
            label=str(payload.get("label") or "")[:MAX_FACT_LABEL_CHARS],
            value=str(payload.get("value") or "")[:MAX_FACT_VALUE_CHARS],
            status=status,
            provenance=FactProvenance.from_dict(payload.get("provenance")),
            original_value=str(payload.get("original_value") or "")[:MAX_FACT_VALUE_CHARS],
            note=str(payload.get("note") or "")[:MAX_FACT_NOTE_CHARS],
            decided_at=str(payload.get("decided_at") or "")[:64],
            created_at=str(payload.get("created_at") or "")[:64],
            updated_at=str(payload.get("updated_at") or "")[:64],
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    """The candidate profile: every fact with its status and its evidence."""

    id: str = DEFAULT_PROFILE_ID
    facts: tuple[CandidateFact, ...] = ()
    source_name: str = ""
    source_kind: str = ""
    source_file: str = ""
    extraction_method: str = EXTRACTION_METHOD_EMBEDDED
    created_at: str = ""
    updated_at: str = ""

    def fact(self, fact_id: str) -> CandidateFact | None:
        """Return one fact by identifier, or ``None`` when it does not exist."""
        identifier = str(fact_id or "")
        for fact in self.facts:
            if fact.id == identifier:
                return fact
        return None

    def facts_with_status(self, status: str) -> tuple[CandidateFact, ...]:
        """Return every fact holding one status."""
        return tuple(fact for fact in self.facts if fact.status == status)

    @property
    def usable_facts(self) -> tuple[CandidateFact, ...]:
        """Facts validated by the person; the only ones a candidacy may use."""
        return tuple(fact for fact in self.facts if fact.is_usable)

    @property
    def pending_facts(self) -> tuple[CandidateFact, ...]:
        """Facts still waiting for a human decision."""
        return self.facts_with_status(FACT_STATUS_PROPOSED)

    def counts(self) -> dict[str, int]:
        """Number of facts per status; every status is always present."""
        counts = {status: 0 for status in FACT_STATUSES}
        for fact in self.facts:
            counts[fact.status] = counts.get(fact.status, 0) + 1
        return counts

    def usable_summary(self) -> dict[str, list[str]]:
        """Approved values grouped by kind.

        This is the contract the matching pipeline (SK-11) must consume: a
        proposal, a rejection or a suspended fact never appears here.
        """
        summary: dict[str, list[str]] = {kind: [] for kind in FACT_KINDS}
        for fact in self.usable_facts:
            summary.setdefault(fact.kind, []).append(fact.value)
        return summary

    def with_fact(self, fact: CandidateFact) -> "CandidateProfile":
        """Return a copy of the profile where one fact is added or replaced."""
        facts = [existing for existing in self.facts if existing.id != fact.id]
        facts.append(fact)
        return replace(self, facts=tuple(facts))

    def without_fact(self, fact_id: str) -> "CandidateProfile":
        """Return a copy of the profile where one fact is removed."""
        return replace(self, facts=tuple(fact for fact in self.facts if fact.id != fact_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "facts": [fact.to_dict() for fact in self.facts],
            "source_name": self.source_name,
            "source_kind": self.source_kind,
            "source_file": self.source_file,
            "extraction_method": self.extraction_method,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "CandidateProfile":
        if not isinstance(payload, dict):
            return cls()
        raw_facts = payload.get("facts")
        facts: list[CandidateFact] = []
        if isinstance(raw_facts, list):
            for item in raw_facts:
                try:
                    facts.append(CandidateFact.from_dict(item))
                except ProfileRuleError:
                    # A single unreadable fact must not hide the whole profile.
                    continue
        method = str(payload.get("extraction_method") or EXTRACTION_METHOD_EMBEDDED)
        if method not in EXTRACTION_METHODS:
            method = EXTRACTION_METHOD_EMBEDDED
        return cls(
            id=str(payload.get("id") or DEFAULT_PROFILE_ID)[:120],
            facts=tuple(facts),
            source_name=str(payload.get("source_name") or "")[:MAX_FACT_LABEL_CHARS],
            source_kind=str(payload.get("source_kind") or "")[:80],
            source_file=str(payload.get("source_file") or "")[:180],
            extraction_method=method,
            created_at=str(payload.get("created_at") or "")[:64],
            updated_at=str(payload.get("updated_at") or "")[:64],
        )


def build_fact(
    *,
    fact_id: str,
    kind: str,
    label: str,
    value: str,
    provenance: FactProvenance | None = None,
    status: str = FACT_STATUS_PROPOSED,
    original_value: str = "",
    note: str = "",
    decided_at: str = "",
    created_at: str = "",
    updated_at: str = "",
    metadata: dict[str, Any] | None = None,
) -> CandidateFact:
    """Create one fact.

    The status defaults to ``proposed`` on purpose: a machine may propose a
    fact, it may never approve one.  ``decided_at`` stays empty until a person
    takes a decision, and :func:`validate_profile` refuses any profile where a
    usable fact has no recorded decision.
    """
    if kind not in FACT_KINDS:
        raise ProfileRuleError("Type de fait de profil inconnu.")
    if status not in FACT_STATUSES:
        raise ProfileRuleError("Statut de fait de profil inconnu.")
    return CandidateFact(
        id=str(fact_id)[:120],
        kind=kind,
        label=str(label or "")[:MAX_FACT_LABEL_CHARS],
        value=str(value or "")[:MAX_FACT_VALUE_CHARS],
        status=status,
        provenance=provenance,
        original_value=str(original_value or "")[:MAX_FACT_VALUE_CHARS],
        note=str(note or "")[:MAX_FACT_NOTE_CHARS],
        decided_at=str(decided_at or "")[:64],
        created_at=str(created_at or "")[:64],
        updated_at=str(updated_at or "")[:64],
        metadata=dict(metadata or {}),
    )


def decide_fact(
    fact: CandidateFact,
    *,
    decision: str,
    value: str = "",
    note: str = "",
    decided_at: str = "",
) -> CandidateFact:
    """Apply one explicit human decision to a fact.

    Args:
        fact: The fact to decide on.
        decision: One of :data:`FACT_DECISIONS`, or ``proposed`` to reopen a
            rejected or suspended fact.
        value: New value, used when the person corrects the fact.
        note: Optional note written by the person.
        decided_at: Timestamp of the decision; it is what marks the fact as
            validated by a person.

    Returns:
        A new fact carrying the decision.

    Raises:
        ProfileRuleError: When the decision is unknown, the transition is not
            allowed, or an approval would leave the fact without a value.
    """
    if decision not in FACT_STATUSES:
        raise ProfileRuleError("Décision de profil inconnue.")
    allowed = ALLOWED_FACT_TRANSITIONS.get(fact.status, frozenset())
    if decision not in allowed:
        raise ProfileRuleError(
            f"Impossible de passer un fait « {FACT_STATUS_LABELS.get(fact.status, fact.status)} » "
            f"à « {FACT_STATUS_LABELS.get(decision, decision)} »."
        )
    if decision == FACT_STATUS_MODIFIED:
        new_value = str(value or "").strip()[:MAX_FACT_VALUE_CHARS]
        if not new_value:
            raise ProfileRuleError("Un fait corrigé doit garder une valeur.")
    else:
        new_value = fact.value
    if decision in USER_VALIDATED_STATUSES and not new_value.strip():
        raise ProfileRuleError("Un fait approuvé doit garder une valeur.")
    timestamp = str(decided_at or "")[:64]
    if decision == FACT_STATUS_PROPOSED:
        # Reopening a fact clears the decision: the fact is pending again.
        return replace(
            fact,
            status=FACT_STATUS_PROPOSED,
            decided_at="",
            note=str(note or "")[:MAX_FACT_NOTE_CHARS],
            updated_at=timestamp,
        )
    return replace(
        fact,
        status=decision,
        value=new_value,
        original_value=fact.original_value or fact.value,
        note=str(note or fact.note or "")[:MAX_FACT_NOTE_CHARS],
        decided_at=timestamp,
        updated_at=timestamp,
    )


def validate_profile(profile: CandidateProfile) -> list[str]:
    """Return every rule broken by the profile; an empty list means it is sound.

    The rules are the guarantees of this feature:

    * a status is always one of the five known statuses;
    * a fact that justifies a candidacy was validated by a person
      (``decided_at`` is set) — this is what stops an OCR result from being
      approved automatically;
    * a usable fact still carries the source it came from.
    """
    problems: list[str] = []
    seen_ids: set[str] = set()
    for fact in profile.facts:
        if fact.status not in FACT_STATUSES:
            problems.append(f"Le fait {fact.id} porte un statut inconnu : {fact.status}.")
            continue
        if fact.id in seen_ids:
            problems.append(f"Le fait {fact.id} est présent plusieurs fois.")
        seen_ids.add(fact.id)
        if fact.status in USER_VALIDATED_STATUSES and not fact.decided_at:
            problems.append(
                f"Le fait {fact.id} est utilisable sans décision humaine enregistrée."
            )
        if fact.status in USER_VALIDATED_STATUSES and not fact.value.strip():
            problems.append(f"Le fait {fact.id} est utilisable mais vide.")
        if fact.provenance is None:
            problems.append(f"Le fait {fact.id} n’a conservé aucune source.")
            continue
        if fact.provenance.extraction_method != EXTRACTION_METHOD_MANUAL:
            if not fact.provenance.quote.strip():
                problems.append(f"Le fait {fact.id} n’a conservé aucune citation source.")
            if fact.provenance.end_offset < fact.provenance.start_offset:
                problems.append(f"Le fait {fact.id} a des offsets source incohérents.")
    return problems


def assert_profile_rules(profile: CandidateProfile) -> None:
    """Raise :class:`ProfileRuleError` when the profile breaks a rule."""
    problems = validate_profile(profile)
    if problems:
        raise ProfileRuleError(" ".join(problems))


def merge_facts(existing: Iterable[CandidateFact], proposals: Iterable[CandidateFact]) -> tuple[CandidateFact, ...]:
    """Add proposals that are not already known, keeping every decided fact.

    A fact is considered already known when it has the same kind and the same
    normalised value.  This keeps a second import from duplicating facts the
    person already approved, without ever overwriting a decision.
    """
    kept = list(existing)
    known = {(fact.kind, _normalise_value(fact.value)) for fact in kept}
    for proposal in proposals:
        key = (proposal.kind, _normalise_value(proposal.value))
        if key in known:
            continue
        known.add(key)
        kept.append(proposal)
    return tuple(kept)


def _normalise_value(value: str) -> str:
    return " ".join(str(value or "").casefold().split())
