"""Candidate profile made of individually approved facts, each with provenance.

The profile is the bridge between a document (PDF, DOCX, image, pasted text)
and everything that may later justify an application.  The rule of this
module is simple and strict:

    a fact only exists for the user once the user approved it.

Design rules enforced here and by the tests:

* every fact keeps the exact source it came from: page, character offsets and
  the verbatim quote, so any statement can be checked against the document;
* no fact is ever approved automatically -- extraction only produces
  ``proposed`` facts;
* a fact read from an OCR layer is never approved by a machine: approving it
  requires an explicit user action (``actor="user"``);
* only ``approved`` and ``modified`` facts may justify an application; a
  ``proposed``, ``rejected`` or ``suspended`` fact never does.

This module is pure: no file, no network, no clock read.  Timestamps and
identifiers are computed by the caller or injected.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from .models import clean_text


# --- Fact statuses (all decided by the user) --------------------------------

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

#: The only statuses that make a fact usable for matching or application.
JUSTIFIABLE_STATUSES: frozenset[str] = frozenset({STATUS_APPROVED, STATUS_MODIFIED})

#: Allowed status changes.  A rejected fact can only come back to review; a
#: suspended fact can be restored by the user.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_PROPOSED: frozenset({STATUS_APPROVED, STATUS_REJECTED, STATUS_MODIFIED, STATUS_SUSPENDED}),
    STATUS_APPROVED: frozenset({STATUS_PROPOSED, STATUS_REJECTED, STATUS_MODIFIED, STATUS_SUSPENDED}),
    STATUS_REJECTED: frozenset({STATUS_PROPOSED, STATUS_SUSPENDED}),
    STATUS_MODIFIED: frozenset({STATUS_PROPOSED, STATUS_APPROVED, STATUS_REJECTED, STATUS_SUSPENDED}),
    STATUS_SUSPENDED: frozenset({STATUS_PROPOSED, STATUS_APPROVED, STATUS_REJECTED, STATUS_MODIFIED}),
}

#: French labels for the interface.  Kept beside the codes so the API and the
#: UI never invent a sixth status.
STATUS_LABELS: dict[str, str] = {
    STATUS_PROPOSED: "À valider",
    STATUS_APPROVED: "Approuvé",
    STATUS_REJECTED: "Rejeté",
    STATUS_MODIFIED: "Corrigé",
    STATUS_SUSPENDED: "Mis de côté",
}


# --- Fact kinds --------------------------------------------------------------

KIND_SKILL = "skill"
KIND_EXPERIENCE = "experience"
KIND_EDUCATION = "education"
KIND_LANGUAGE = "language"
KIND_DATE = "date"
KIND_CONTACT = "contact"

FACT_KINDS: tuple[str, ...] = (
    KIND_SKILL,
    KIND_EXPERIENCE,
    KIND_EDUCATION,
    KIND_LANGUAGE,
    KIND_DATE,
    KIND_CONTACT,
)

KIND_LABELS: dict[str, str] = {
    KIND_SKILL: "Compétence",
    KIND_EXPERIENCE: "Expérience",
    KIND_EDUCATION: "Diplôme",
    KIND_LANGUAGE: "Langue",
    KIND_DATE: "Date",
    KIND_CONTACT: "Coordonnée",
}


# --- Extraction methods ------------------------------------------------------

EXTRACTION_TEXT_LAYER = "text_layer"
EXTRACTION_OCR = "ocr"

EXTRACTIONS: tuple[str, ...] = (EXTRACTION_TEXT_LAYER, EXTRACTION_OCR)

#: The actor allowed to approve a fact.  ``system`` is used by any automated
#: path; it may never approve an OCR fact.
ACTOR_USER = "user"
ACTOR_SYSTEM = "system"

PROFILE_EXPORT_SCHEMA = "come-candidate-profile/1"


class ProfileError(Exception):
    """Base error for the candidate profile."""


class FactTransitionError(ProfileError):
    """A status change that the model does not allow."""


class AutoApprovalError(ProfileError):
    """A machine tried to approve a fact that only a user may approve."""


class ProvenanceError(ProfileError):
    """A fact whose provenance does not match the document it claims."""


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where one fact comes from, exactly.

    Attributes:
        source_id: Identifier of the source document the fact was read from.
        filename: Original filename of that document.
        filetype: ``pdf``, ``docx``, ``txt`` or ``image``.
        page: 1-based page number, ``None`` when the format has no page.
        start_offset: First character offset of the quote in the document text.
        end_offset: Last character offset (exclusive) of the quote.
        quote: The verbatim text, exactly ``document_text[start:end]``.
        extraction: ``text_layer`` or ``ocr``.
        source_sha256: Checksum of the source document.
    """

    source_id: str
    filename: str
    filetype: str
    page: int | None
    start_offset: int
    end_offset: int
    quote: str
    extraction: str = EXTRACTION_TEXT_LAYER
    source_sha256: str = ""

    def slice_of(self, document_text: str) -> str:
        """Return the text the provenance points at."""
        return document_text[self.start_offset : self.end_offset]

    def matches(self, document_text: str) -> bool:
        """Return whether the quote is exactly the text at the given offsets."""
        if self.start_offset < 0 or self.end_offset < self.start_offset:
            return False
        if self.end_offset > len(document_text):
            return False
        return self.slice_of(document_text) == self.quote

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "filename": self.filename,
            "filetype": self.filetype,
            "page": self.page,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "quote": self.quote,
            "extraction": self.extraction,
            "source_sha256": self.source_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Provenance":
        page = data.get("page")
        return cls(
            source_id=clean_text(data.get("source_id"), limit=120),
            filename=clean_text(data.get("filename"), limit=256),
            filetype=clean_text(data.get("filetype"), limit=20),
            page=int(page) if isinstance(page, int) and page > 0 else None,
            start_offset=int(data.get("start_offset") or 0),
            end_offset=int(data.get("end_offset") or 0),
            quote=clean_text(data.get("quote"), limit=2_000),
            extraction=clean_text(data.get("extraction"), limit=40) or EXTRACTION_TEXT_LAYER,
            source_sha256=clean_text(data.get("source_sha256"), limit=64),
        )


@dataclass(frozen=True, slots=True)
class ProfileFact:
    """One reviewable statement about the candidate.

    Attributes:
        fact_id: Deterministic identifier, stable for the same source passage.
        kind: One of :data:`FACT_KINDS`.
        label: Short human readable name of the fact.
        value: The statement itself, as it would be used.
        status: One of :data:`FACT_STATUSES`.
        provenance: Exact origin of the statement.
        attributes: Extra, bounded details (language level, date position...).
        previous_value: Value before the user corrected it.
        created_at: Creation timestamp, injected by the caller.
        updated_at: Last change timestamp, injected by the caller.
    """

    fact_id: str
    kind: str
    label: str
    value: str
    status: str
    provenance: Provenance
    attributes: dict[str, str] = field(default_factory=dict)
    previous_value: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_justifiable(self) -> bool:
        """Whether this fact may justify a matching or an application."""
        return self.status in JUSTIFIABLE_STATUSES

    @property
    def comes_from_ocr(self) -> bool:
        """Whether the fact was read from an OCR layer."""
        return self.provenance.extraction == EXTRACTION_OCR

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind,
            "kind_label": KIND_LABELS.get(self.kind, self.kind),
            "label": self.label,
            "value": self.value,
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "attributes": dict(self.attributes),
            "previous_value": self.previous_value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "justifiable": self.is_justifiable,
            "ocr": self.comes_from_ocr,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProfileFact":
        raw_attributes = data.get("attributes")
        attributes = (
            {clean_text(key, limit=60): clean_text(value, limit=200) for key, value in raw_attributes.items()}
            if isinstance(raw_attributes, Mapping)
            else {}
        )
        provenance = data.get("provenance")
        return cls(
            fact_id=clean_text(data.get("fact_id"), limit=120),
            kind=clean_text(data.get("kind"), limit=40),
            label=clean_text(data.get("label"), limit=300),
            value=clean_text(data.get("value"), limit=4_000),
            status=clean_text(data.get("status"), limit=40) or STATUS_PROPOSED,
            provenance=Provenance.from_dict(provenance if isinstance(provenance, Mapping) else {}),
            attributes=attributes,
            previous_value=clean_text(data.get("previous_value"), limit=4_000),
            created_at=clean_text(data.get("created_at"), limit=64),
            updated_at=clean_text(data.get("updated_at"), limit=64),
        )


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """The document a profile was built from.

    The full text is kept so every quote can be checked again later, even
    after the original file was deleted.
    """

    document_id: str
    filename: str
    filetype: str
    page_count: int | None
    text: str
    extraction: str = EXTRACTION_TEXT_LAYER
    sha256: str = ""
    created_at: str = ""

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "document_id": self.document_id,
            "filename": self.filename,
            "filetype": self.filetype,
            "page_count": self.page_count,
            "extraction": self.extraction,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "text_chars": len(self.text),
        }
        if include_text:
            data["text"] = self.text
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceDocument":
        page_count = data.get("page_count")
        return cls(
            document_id=clean_text(data.get("document_id"), limit=120),
            filename=clean_text(data.get("filename"), limit=256),
            filetype=clean_text(data.get("filetype"), limit=20),
            page_count=int(page_count) if isinstance(page_count, int) and page_count > 0 else None,
            text=str(data.get("text") or ""),
            extraction=clean_text(data.get("extraction"), limit=40) or EXTRACTION_TEXT_LAYER,
            sha256=clean_text(data.get("sha256"), limit=64),
            created_at=clean_text(data.get("created_at"), limit=64),
        )


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    """A source document and the facts extracted from it."""

    document: SourceDocument
    facts: tuple[ProfileFact, ...] = ()

    def by_status(self, status: str) -> tuple[ProfileFact, ...]:
        return tuple(fact for fact in self.facts if fact.status == status)

    @property
    def active_facts(self) -> tuple[ProfileFact, ...]:
        """The facts the user approved or corrected: the usable profile."""
        return tuple(fact for fact in self.facts if fact.is_justifiable)

    @property
    def proposed_facts(self) -> tuple[ProfileFact, ...]:
        return tuple(fact for fact in self.facts if fact.status == STATUS_PROPOSED)

    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in FACT_STATUSES}
        for fact in self.facts:
            counts[fact.status] = counts.get(fact.status, 0) + 1
        return counts

    def to_dict(self, *, include_source: bool = True) -> dict[str, Any]:
        return {
            "schema": PROFILE_EXPORT_SCHEMA,
            "document": self.document.to_dict(include_text=include_source),
            "facts": [fact.to_dict() for fact in self.facts],
            "counts": self.counts(),
            "active_facts": [fact.fact_id for fact in self.active_facts],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CandidateProfile":
        document = data.get("document")
        raw_facts = data.get("facts")
        facts = tuple(
            ProfileFact.from_dict(item)
            for item in (raw_facts if isinstance(raw_facts, list) else [])
            if isinstance(item, Mapping)
        )
        return cls(
            document=SourceDocument.from_dict(document if isinstance(document, Mapping) else {}),
            facts=facts,
        )


def normalized_label(value: str) -> str:
    """Return a comparable form of a label (accents and case removed)."""
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(text.split())


def make_fact_id(kind: str, label: str, source_id: str, start_offset: int) -> str:
    """Return the deterministic identifier of a fact.

    The identifier depends on the kind, the normalized label, the source and
    the exact position of the quote: re-reading the same document proposes the
    same facts instead of duplicating them.
    """
    payload = "|".join(
        (
            str(kind or ""),
            normalized_label(label),
            str(source_id or ""),
            str(int(start_offset)),
        )
    )
    return "fact_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def can_transition(current: str, target: str) -> bool:
    """Return whether a status change is allowed."""
    if target not in FACT_STATUSES:
        return False
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def transition_fact(
    fact: ProfileFact,
    target: str,
    *,
    actor: str = ACTOR_USER,
    value: str | None = None,
    now: str = "",
) -> ProfileFact:
    """Return the fact with a new status.

    The transition table is enforced: a rejected fact does not jump back to
    approved, it goes back to review.  An OCR fact can only be approved by a
    user, never by a machine.
    """
    if target not in FACT_STATUSES:
        raise FactTransitionError(f"Statut inconnu : {target}")
    if not can_transition(fact.status, target):
        raise FactTransitionError(
            f"Transition impossible : {fact.status} → {target}"
        )
    if target == STATUS_APPROVED and fact.comes_from_ocr and actor != ACTOR_USER:
        raise AutoApprovalError(
            "Un fait issu de l’OCR ne peut être approuvé que par l’utilisateur."
        )
    if target == STATUS_MODIFIED:
        if value is None:
            raise FactTransitionError("Corriger un fact exige une nouvelle valeur.")
        new_value = clean_text(value, limit=4_000)
        if not new_value:
            raise FactTransitionError("Corriger un fact exige une valeur non vide.")
        return replace(
            fact,
            value=new_value,
            previous_value=fact.value,
            status=STATUS_MODIFIED,
            updated_at=clean_text(now, limit=64) or fact.updated_at,
        )
    if value is not None and target != STATUS_MODIFIED:
        raise FactTransitionError("Changer la valeur d’un fact passe par le statut « corrigé ».")
    return replace(fact, status=target, updated_at=clean_text(now, limit=64) or fact.updated_at)


def verify_fact(fact: ProfileFact, document_text: str) -> list[str]:
    """Return the problems of one fact against the text it claims."""
    problems: list[str] = []
    if fact.provenance.source_sha256 and document_text:
        expected = hashlib.sha256(document_text.encode("utf-8")).hexdigest()
        if fact.provenance.source_sha256 != expected:
            problems.append(
                f"{fact.fact_id} : le texte source ne correspond plus au document d’origine."
            )
    if not fact.provenance.matches(document_text):
        problems.append(
            f"{fact.fact_id} : la citation ne correspond pas aux offsets déclarés."
        )
    if not fact.provenance.quote.strip():
        problems.append(f"{fact.fact_id} : la citation est vide.")
    return problems


def verify_profile(profile: CandidateProfile) -> list[str]:
    """Return every provenance problem of a profile."""
    problems: list[str] = []
    seen: set[str] = set()
    for fact in profile.facts:
        for problem in verify_fact(fact, profile.document.text):
            if problem not in seen:
                seen.add(problem)
                problems.append(problem)
    return problems


def active_facts(facts: Iterable[ProfileFact]) -> tuple[ProfileFact, ...]:
    """Return only the facts that may justify an application."""
    return tuple(fact for fact in facts if fact.is_justifiable)


def build_justification(facts: Iterable[ProfileFact]) -> dict[str, Any]:
    """Return what may be used to justify a matching or an application.

    Only the facts the user approved or corrected are included.  A proposed,
    rejected or suspended fact is never part of the answer, and every fact
    keeps the passage it comes from so the justification stays checkable.
    """
    payload: dict[str, list[dict[str, Any]]] = {kind: [] for kind in FACT_KINDS}
    for fact in active_facts(facts):
        payload.setdefault(fact.kind, []).append(
            {
                "fact_id": fact.fact_id,
                "label": fact.label,
                "value": fact.value,
                "status": fact.status,
                "attributes": dict(fact.attributes),
                "provenance": fact.provenance.to_dict(),
            }
        )
    return {
        "justifiable": {kind: values for kind, values in payload.items() if values},
        "fact_ids": [fact.fact_id for fact in active_facts(facts)],
        "count": sum(len(values) for values in payload.values()),
    }


def profile_to_markdown(profile: CandidateProfile) -> str:
    """Render the usable profile as a readable Markdown document."""
    lines: list[str] = [f"# Profil candidat — {profile.document.filename}".strip(), ""]
    lines.append(f"Source : `{profile.document.filename}` ({profile.document.filetype})")
    lines.append(f"Extraction : {profile.document.extraction}")
    lines.append("")
    active = profile.active_facts
    if not active:
        lines.append("Aucun fait approuvé : le profil actif est encore vide.")
        return "\n".join(lines) + "\n"
    for kind in FACT_KINDS:
        facts = [fact for fact in active if fact.kind == kind]
        if not facts:
            continue
        lines.append(f"## {KIND_LABELS.get(kind, kind)}")
        for fact in facts:
            page = fact.provenance.page
            location = f"page {page}" if page else "page inconnue"
            lines.append(f"- **{fact.label}** — {fact.value}")
            lines.append(f"  - Source : {location} · « {fact.provenance.quote} »")
        lines.append("")
    return "\n".join(lines)
