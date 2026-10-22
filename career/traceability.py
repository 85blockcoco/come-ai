"""Requirement traceability registry for the local Career workspace (SPEC-011).

This module is the **core domain** of the traceability registry.  It is pure
Python: no database, no network, no model, no clock of its own (the clock is
injectable so every audit run is reproducible).

WHAT THE REGISTRY SOLVES
Offer requirements extracted by ``career.offer_requirements`` (SK-02) and the
profile evidence that backs them (SK-10 / SPEC-008) live in two different
worlds.  The registry is the single place where one requirement is linked to
one proof, carries one status, and keeps one **immutable** history of every
change that was made to it.

DESIGN RULES (from the SPEC-011 mission)
1. *Creation* — every requirement of an offer becomes a ``RequirementTrace``.
2. *Linking* — a trace points to at most one evidence item, always quoting the
   exact passage that proves it.
3. *History* — every change appends one immutable ``TraceEvent``.  Events are
   frozen and never rewritten, so the audit trail cannot be edited after the
   fact.
4. *Coherence* — a ``covered`` requirement always carries an ``evidence_id``
   **and** an ``evidence_quote``.  A link without a quote is not a proof.
5. *Audit trail* — every event carries an actor (``system``, ``user`` or
   ``worker``), an ISO 8601 timestamp and an optional comment.
6. *No invention* — the registry never derives a requirement that was not
   extracted, never rewrites the requirement text and never fabricates a
   quote.  Automatic linking only happens when the matcher returned the exact
   excerpt that proves the requirement.

The two integrations with the other Spec Kit modules are **adapters** at the
bottom of this file:

- ``sync_offer_analysis()`` consumes the SK-02 contract
  (``analyze_offer()``) and creates/updates the matching traces.
- ``apply_match_result()`` consumes the SK-21 matching result
  (``MatchResult.actions``) and links the evidence it returned.

Both adapters accept plain dictionaries or dataclass-like objects, so the
registry keeps working before SK-10 and SK-21 are merged into this branch.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Sequence

from workspace_core import UserFacingError

from .models import clean_text, normalized_text, utc_now


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

CATEGORIES: tuple[str, ...] = (
    "skill",
    "experience",
    "education",
    "language",
    "tool",
    "certification",
    "soft_skill",
    "other",
)

CRITICALITIES: tuple[str, ...] = ("mandatory", "preferred", "nice_to_have", "contextual")

STATUSES: tuple[str, ...] = ("uncovered", "covered", "partial", "contradicted", "waived")

# The eight event types of the mission contract, plus four explicit
# extensions used by the operations the mission also asks for (batch tag
# updates, requirement re-synchronisation, deletion and link validation).
EVENT_TYPES: tuple[str, ...] = (
    "created",
    "linked",
    "unlinked",
    "status_changed",
    "category_changed",
    "criticality_changed",
    "waived",
    "reopened",
    "tags_changed",
    "requirement_updated",
    "deleted",
    "validated",
)

ACTORS: tuple[str, ...] = ("system", "user", "worker")

#: Statuses that require a reference to a proof.
STATUSES_REQUIRING_EVIDENCE: frozenset[str] = frozenset({"covered", "contradicted"})

#: Statuses that mean "the requirement is satisfied by a proof".
COVERED_STATUSES: frozenset[str] = frozenset({"covered"})

STATUS_LABELS: dict[str, str] = {
    "uncovered": "Non couverte",
    "covered": "Couverte",
    "partial": "Partiellement couverte",
    "contradicted": "Contradictoire",
    "waived": "Écartée",
}

CATEGORY_LABELS: dict[str, str] = {
    "skill": "Compétence",
    "experience": "Expérience",
    "education": "Formation",
    "language": "Langue",
    "tool": "Outil",
    "certification": "Certification",
    "soft_skill": "Compétence comportementale",
    "other": "Autre",
}

CRITICALITY_LABELS: dict[str, str] = {
    "mandatory": "Obligatoire",
    "preferred": "Appréciée",
    "nice_to_have": "Atout",
    "contextual": "Contextuelle",
}

#: SK-02 requirement categories mapped onto the traceability vocabulary.
OFFER_CATEGORY_MAP: dict[str, str] = {
    "technical_skill": "skill",
    "language": "language",
    "education": "education",
    "experience": "experience",
    "availability": "other",
    "mobility": "other",
    "work_authorization": "other",
    "other": "other",
}

#: SK-02 modalities mapped onto the traceability criticalities.
OFFER_MODALITY_MAP: dict[str, str] = {
    "required": "mandatory",
    "preferred": "preferred",
    "contextual": "contextual",
    "unknown": "contextual",
}

#: Markers that turn a "preferred" statement into an explicit "nice to have".
_NICE_TO_HAVE_MARKERS: tuple[str, ...] = (
    "nice to have",
    "nice to",
    "un plus",
    "atout",
    "souhaitable",
    "de preference",
    "bonus",
)

#: Default confidence above which an automatic link is considered a full proof.
AUTO_LINK_COVERED_THRESHOLD = 0.8

MAX_TAGS = 24
MAX_REQUIREMENT_TEXT = 4_000
MAX_EVIDENCE_QUOTE = 4_000
MAX_COMMENT = 2_000


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One immutable entry of a traceability history.

    The event is frozen on purpose: once written, an event can never be
    edited.  Correcting a mistake is done by appending a new event, never by
    rewriting the past.
    """

    event_id: str
    timestamp: str
    event_type: str
    old_value: str | None = None
    new_value: str | None = None
    actor: str = "system"
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "actor": self.actor,
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraceEvent":
        return cls(
            event_id=str(payload.get("event_id") or uuid.uuid4()),
            timestamp=str(payload.get("timestamp") or utc_now()),
            event_type=str(payload.get("event_type") or "status_changed"),
            old_value=_optional_text(payload.get("old_value")),
            new_value=_optional_text(payload.get("new_value")),
            actor=str(payload.get("actor") or "system"),
            comment=_optional_text(payload.get("comment")),
        )


@dataclass
class RequirementTrace:
    """One offer requirement, its proof, its status and its history.

    The field names of the SPEC-011 contract are kept verbatim
    (``trace_id``, ``requirement_id``, ``requirement_text``, ``source``,
    ``category``, ``criticality``, ``evidence_id``, ``evidence_quote``,
    ``status``, ``created_at``, ``updated_at``, ``history``, ``tags``).
    The remaining fields carry the provenance needed by the audit reports and
    by the filters of the API.
    """

    trace_id: str
    requirement_id: str = ""
    requirement_text: str = ""
    source: str = "manual"
    category: str = "other"
    criticality: str = "contextual"
    evidence_id: str | None = None
    evidence_quote: str | None = None
    status: str = "uncovered"
    created_at: str = ""
    updated_at: str = ""
    history: list[TraceEvent] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # -- provenance and audit extensions ------------------------------------
    offer_id: str = ""
    cv_id: str = ""
    source_field: str = ""
    locator: str = ""
    confidence: float | None = None
    auto_linked: bool = False
    validated: bool | None = None
    waiver_reason: str | None = None
    deleted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "requirement_id": self.requirement_id,
            "requirement_text": self.requirement_text,
            "source": self.source,
            "category": self.category,
            "criticality": self.criticality,
            "evidence_id": self.evidence_id,
            "evidence_quote": self.evidence_quote,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": [event.to_dict() for event in self.history],
            "tags": list(self.tags),
            "offer_id": self.offer_id,
            "cv_id": self.cv_id,
            "source_field": self.source_field,
            "locator": self.locator,
            "confidence": self.confidence,
            "auto_linked": self.auto_linked,
            "validated": self.validated,
            "waiver_reason": self.waiver_reason,
            "deleted": self.deleted,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "category_label": CATEGORY_LABELS.get(self.category, self.category),
            "criticality_label": CRITICALITY_LABELS.get(self.criticality, self.criticality),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RequirementTrace":
        events = payload.get("history")
        history = [TraceEvent.from_dict(item) for item in events if isinstance(item, dict)] if isinstance(events, list) else []
        confidence = payload.get("confidence")
        validated = payload.get("validated")
        return cls(
            trace_id=str(payload.get("trace_id") or uuid.uuid4()),
            requirement_id=clean_text(payload.get("requirement_id"), limit=160),
            requirement_text=clean_text(payload.get("requirement_text"), limit=MAX_REQUIREMENT_TEXT),
            source=clean_text(payload.get("source"), limit=160) or "manual",
            category=clean_text(payload.get("category"), limit=40) or "other",
            criticality=clean_text(payload.get("criticality"), limit=40) or "contextual",
            evidence_id=_optional_text(payload.get("evidence_id")),
            evidence_quote=_optional_text(payload.get("evidence_quote")),
            status=clean_text(payload.get("status"), limit=40) or "uncovered",
            created_at=clean_text(payload.get("created_at"), limit=40),
            updated_at=clean_text(payload.get("updated_at"), limit=40),
            history=history,
            tags=[clean_text(tag, limit=80) for tag in payload.get("tags", []) if isinstance(tag, str)],
            offer_id=clean_text(payload.get("offer_id"), limit=160),
            cv_id=clean_text(payload.get("cv_id"), limit=160),
            source_field=clean_text(payload.get("source_field"), limit=80),
            locator=clean_text(payload.get("locator"), limit=80),
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            auto_linked=bool(payload.get("auto_linked")),
            validated=bool(validated) if isinstance(validated, bool) else None,
            waiver_reason=_optional_text(payload.get("waiver_reason")),
            deleted=bool(payload.get("deleted")),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = clean_text(value, limit=MAX_COMMENT)
    return text or None


def _validate_choice(value: Any, allowed: Sequence[str], label: str) -> str:
    text = clean_text(value, limit=40).lower().replace(" ", "_")
    if text not in allowed:
        raise UserFacingError(f"{label} est invalide.")
    return text


def _validate_actor(actor: Any) -> str:
    text = clean_text(actor, limit=20).lower() or "system"
    if text not in ACTORS:
        raise UserFacingError("L'acteur de l'événement est invalide.")
    return text


def _clean_tags(tags: Iterable[Any] | None) -> list[str]:
    cleaned: list[str] = []
    for tag in tags or []:
        text = clean_text(tag, limit=80)
        if not text:
            continue
        if text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= MAX_TAGS:
            break
    return cleaned


def _default_id_factory() -> str:
    return str(uuid.uuid4())


def _requirement_fingerprint(requirement_text: str) -> str:
    return hashlib.sha256(normalized_text(requirement_text).encode("utf-8")).hexdigest()


def evidence_reference(evidence: Any) -> tuple[str, str]:
    """Return ``(evidence_id, quote)`` for an evidence-like object.

    The registry never depends on the EvidenceItem class of SPEC-008: any
    object (or dictionary) exposing an id and a quote is accepted, so the
    registry can be used before that module is merged.
    """
    if isinstance(evidence, dict):
        evidence_id = evidence.get("evidence_id") or evidence.get("id") or ""
        quote = evidence.get("evidence_quote") or evidence.get("quote") or evidence.get("text") or ""
    else:
        evidence_id = (
            getattr(evidence, "evidence_id", None)
            or getattr(evidence, "id", None)
            or ""
        )
        quote = (
            getattr(evidence, "evidence_quote", None)
            or getattr(evidence, "quote", None)
            or getattr(evidence, "text", None)
            or ""
        )
    return clean_text(evidence_id, limit=160), clean_text(quote, limit=MAX_EVIDENCE_QUOTE)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TraceabilityRegistry:
    """In-memory traceability registry with an immutable history.

    The registry is the domain model: it owns the coherence rules (a
    ``covered`` requirement always cites a proof) and the audit trail.  The
    persistence layer (``career.traceability_store``) rebuilds a registry from
    the database and saves it back after each change.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._traces: dict[str, RequirementTrace] = {}
        self._clock = clock or utc_now
        self._id_factory = id_factory or _default_id_factory

    # -- reading -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._traces)

    def __contains__(self, trace_id: object) -> bool:
        return str(trace_id) in self._traces

    def get(self, trace_id: str) -> RequirementTrace | None:
        return self._traces.get(clean_text(trace_id, limit=80))

    def require(self, trace_id: str) -> RequirementTrace:
        trace = self.get(trace_id)
        if trace is None:
            raise UserFacingError("Cette exigence de traçabilité est introuvable.")
        return trace

    def list(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        criticality: str | None = None,
        offer_id: str | None = None,
        cv_id: str | None = None,
        source: str | None = None,
        tag: str | None = None,
        include_deleted: bool = False,
    ) -> list[RequirementTrace]:
        """Return the traces matching every provided filter.

        The order is deterministic (creation date, then trace id) so two runs
        on the same data always produce the same list.
        """
        wanted_status = clean_text(status, limit=40).lower()
        wanted_category = clean_text(category, limit=40).lower()
        wanted_criticality = clean_text(criticality, limit=40).lower()
        wanted_offer = clean_text(offer_id, limit=160)
        wanted_cv = clean_text(cv_id, limit=160)
        wanted_source = clean_text(source, limit=160)
        wanted_tag = clean_text(tag, limit=80)

        selected = []
        for trace in self._traces.values():
            if trace.deleted and not include_deleted:
                continue
            if wanted_status and trace.status != wanted_status:
                continue
            if wanted_category and trace.category != wanted_category:
                continue
            if wanted_criticality and trace.criticality != wanted_criticality:
                continue
            if wanted_offer and trace.offer_id != wanted_offer:
                continue
            if wanted_cv and trace.cv_id != wanted_cv:
                continue
            if wanted_source and trace.source != wanted_source:
                continue
            if wanted_tag and wanted_tag not in trace.tags:
                continue
            selected.append(trace)
        return sorted(selected, key=lambda item: (item.created_at, item.trace_id))

    def history(self, trace_id: str) -> list[TraceEvent]:
        """Return the immutable history of one trace (oldest first)."""
        return list(self.require(trace_id).history)

    def all_events(self) -> list[TraceEvent]:
        events: list[TraceEvent] = []
        for trace in self._traces.values():
            events.extend(trace.history)
        return sorted(events, key=lambda event: (event.timestamp, event.event_id))

    # -- writing -----------------------------------------------------------

    def restore(self, trace: RequirementTrace) -> RequirementTrace:
        """Insert an already persisted trace (no new event is written)."""
        self._traces[trace.trace_id] = trace
        return trace

    def create(
        self,
        *,
        requirement_id: str = "",
        requirement_text: str,
        source: str = "manual",
        category: str = "other",
        criticality: str = "contextual",
        offer_id: str = "",
        cv_id: str = "",
        tags: Iterable[Any] | None = None,
        source_field: str = "",
        locator: str = "",
        confidence: float | None = None,
        status: str = "uncovered",
        actor: str = "system",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Create a new trace and record its ``created`` event."""
        text = clean_text(requirement_text, limit=MAX_REQUIREMENT_TEXT)
        if not text:
            raise UserFacingError("Le texte de l'exigence est obligatoire.")
        chosen_status = _validate_choice(status, STATUSES, "Le statut de traçabilité")
        chosen_category = _validate_choice(category, CATEGORIES, "La catégorie de traçabilité")
        chosen_criticality = _validate_choice(criticality, CRITICALITIES, "La criticité de traçabilité")
        stamp = self._clock()
        trace = RequirementTrace(
            trace_id=self._id_factory(),
            requirement_id=clean_text(requirement_id, limit=160),
            requirement_text=text,
            source=clean_text(source, limit=160) or "manual",
            category=chosen_category,
            criticality=chosen_criticality,
            status=chosen_status,
            created_at=stamp,
            updated_at=stamp,
            tags=_clean_tags(tags),
            offer_id=clean_text(offer_id, limit=160),
            cv_id=clean_text(cv_id, limit=160),
            source_field=clean_text(source_field, limit=80),
            locator=clean_text(locator, limit=80),
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        )
        trace = self._append_event(
            trace,
            event_type="created",
            old_value=None,
            new_value=chosen_status,
            actor=actor,
            comment=comment,
        )
        self._traces[trace.trace_id] = trace
        return trace

    def update(
        self,
        trace_id: str,
        *,
        status: str | None = None,
        category: str | None = None,
        criticality: str | None = None,
        tags: Iterable[Any] | None = None,
        comment: str | None = None,
        actor: str = "user",
    ) -> RequirementTrace:
        """Update the mutable part of a trace and audit every change."""
        trace = self.require(trace_id)
        working = replace(trace, history=list(trace.history), tags=list(trace.tags))

        if category is not None:
            chosen = _validate_choice(category, CATEGORIES, "La catégorie de traçabilité")
            if chosen != working.category:
                working = self._append_event(
                    working,
                    event_type="category_changed",
                    old_value=working.category,
                    new_value=chosen,
                    actor=actor,
                    comment=comment,
                )
                working.category = chosen

        if criticality is not None:
            chosen = _validate_choice(criticality, CRITICALITIES, "La criticité de traçabilité")
            if chosen != working.criticality:
                working = self._append_event(
                    working,
                    event_type="criticality_changed",
                    old_value=working.criticality,
                    new_value=chosen,
                    actor=actor,
                    comment=comment,
                )
                working.criticality = chosen

        if tags is not None:
            cleaned = _clean_tags(tags)
            if cleaned != working.tags:
                working = self._append_event(
                    working,
                    event_type="tags_changed",
                    old_value=",".join(working.tags),
                    new_value=",".join(cleaned),
                    actor=actor,
                    comment=comment,
                )
                working.tags = cleaned

        if status is not None:
            working = self._change_status(
                working,
                new_status=status,
                actor=actor,
                comment=comment,
            )

        self._traces[working.trace_id] = working
        return working

    def update_requirement_text(
        self,
        trace_id: str,
        *,
        requirement_text: str,
        actor: str = "system",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Refresh the text of a requirement after the extractor changed it.

        The new text replaces the old one and the change is audited: the
        history keeps the previous wording, so a reader can always see what
        the requirement said before.
        """
        trace = self.require(trace_id)
        text = clean_text(requirement_text, limit=MAX_REQUIREMENT_TEXT)
        if not text or text == trace.requirement_text:
            return trace
        working = replace(trace, history=list(trace.history), tags=list(trace.tags))
        working = self._append_event(
            working,
            event_type="requirement_updated",
            old_value=trace.requirement_text[:200],
            new_value=text[:200],
            actor=actor,
            comment=comment,
        )
        working.requirement_text = text
        self._traces[working.trace_id] = working
        return working

    def link_evidence(
        self,
        trace_id: str,
        *,
        evidence_id: str,
        evidence_quote: str,
        status: str | None = None,
        actor: str = "user",
        comment: str | None = None,
        auto: bool = False,
    ) -> RequirementTrace:
        """Link a proof to a requirement.

        A link always quotes the exact passage that proves the requirement:
        a proof without a quote is not a proof, and the registry refuses it.
        """
        trace = self.require(trace_id)
        quote = clean_text(evidence_quote, limit=MAX_EVIDENCE_QUOTE)
        reference = clean_text(evidence_id, limit=160)
        if not reference:
            raise UserFacingError("La liaison de preuve doit référencer un identifiant de preuve.")
        if not quote:
            raise UserFacingError("La liaison de preuve doit citer l'extrait exact qui la prouve.")
        if trace.evidence_id == reference and trace.evidence_quote == quote:
            return trace

        working = replace(trace, history=list(trace.history), tags=list(trace.tags))
        working.evidence_id = reference
        working.evidence_quote = quote
        working.auto_linked = bool(auto)
        working.validated = None if auto else True
        working = self._append_event(
            working,
            event_type="linked",
            old_value=trace.evidence_id,
            new_value=reference,
            actor=actor,
            comment=comment,
        )
        if status is not None:
            working = self._change_status(
                working,
                new_status=status,
                actor=actor,
                comment=comment,
                allow_missing_evidence=False,
            )
        elif working.status == "uncovered":
            working = self._change_status(
                working,
                new_status="covered",
                actor=actor,
                comment=comment,
                allow_missing_evidence=False,
            )
        self._traces[working.trace_id] = working
        return working

    def unlink_evidence(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Detach the proof of a requirement and audit the change."""
        trace = self.require(trace_id)
        if not trace.evidence_id:
            raise UserFacingError("Cette exigence n'a aucune preuve liée.")
        working = replace(trace, history=list(trace.history), tags=list(trace.tags))
        working.evidence_id = None
        working.evidence_quote = None
        working.auto_linked = False
        working.validated = None
        working = self._append_event(
            working,
            event_type="unlinked",
            old_value=trace.evidence_id,
            new_value=None,
            actor=actor,
            comment=comment,
        )
        if working.status != "waived":
            working = self._change_status(
                working,
                new_status="uncovered",
                actor=actor,
                comment=comment,
                allow_missing_evidence=False,
            )
        self._traces[working.trace_id] = working
        return working

    def waive(
        self,
        trace_id: str,
        *,
        justification: str,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Mark a requirement as waived, with a mandatory justification."""
        reason = clean_text(justification, limit=MAX_COMMENT)
        if not reason:
            raise UserFacingError("Une exigence écartée doit porter une justification.")
        trace = self.require(trace_id)
        working = replace(trace, history=list(trace.history), tags=list(trace.tags))
        working.waiver_reason = reason
        working = self._append_event(
            working,
            event_type="waived",
            old_value=trace.status,
            new_value="waived",
            actor=actor,
            comment=comment or reason,
        )
        working.status = "waived"
        working.updated_at = self._clock()
        self._traces[working.trace_id] = working
        return working

    def reopen(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Reopen a waived requirement."""
        trace = self.require(trace_id)
        if trace.status != "waived":
            raise UserFacingError("Seule une exigence écartée peut être rouverte.")
        working = replace(trace, history=list(trace.history), tags=list(trace.tags))
        working.waiver_reason = None
        restored_status = "covered" if working.evidence_id and working.evidence_quote else "uncovered"
        working = self._append_event(
            working,
            event_type="reopened",
            old_value="waived",
            new_value=restored_status,
            actor=actor,
            comment=comment,
        )
        working.status = restored_status
        working.updated_at = self._clock()
        self._traces[working.trace_id] = working
        return working

    def validate_link(
        self,
        trace_id: str,
        *,
        approved: bool,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Confirm or reject an automatic link made by the matcher."""
        trace = self.require(trace_id)
        if not trace.evidence_id:
            raise UserFacingError("Cette exigence n'a aucune preuve à valider.")
        working = replace(trace, history=list(trace.history), tags=list(trace.tags))
        working = self._append_event(
            working,
            event_type="validated",
            old_value="pending" if working.validated is None else str(working.validated).lower(),
            new_value="approved" if approved else "rejected",
            actor=actor,
            comment=comment,
        )
        working.validated = bool(approved)
        if not approved:
            working.evidence_id = None
            working.evidence_quote = None
            working.auto_linked = False
            working = self._append_event(
                working,
                event_type="unlinked",
                old_value=trace.evidence_id,
                new_value=None,
                actor=actor,
                comment=comment,
            )
            if working.status != "waived":
                working = self._change_status(
                    working,
                    new_status="uncovered",
                    actor=actor,
                    comment=comment,
                    allow_missing_evidence=False,
                )
        self._traces[working.trace_id] = working
        return working

    def delete(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Delete a trace without destroying its history.

        Deleting a requirement is itself an audited event: the trace is kept
        (flagged as deleted) so the audit trail stays complete.
        """
        trace = self.require(trace_id)
        working = replace(trace, history=list(trace.history), tags=list(trace.tags))
        working = self._append_event(
            working,
            event_type="deleted",
            old_value="active",
            new_value="deleted",
            actor=actor,
            comment=comment,
        )
        working.deleted = True
        self._traces[working.trace_id] = working
        return working

    # -- internals ---------------------------------------------------------

    def _append_event(
        self,
        trace: RequirementTrace,
        *,
        event_type: str,
        old_value: str | None,
        new_value: str | None,
        actor: str,
        comment: str | None,
    ) -> RequirementTrace:
        if event_type not in EVENT_TYPES:
            raise UserFacingError("Le type d'événement de traçabilité est invalide.")
        stamp = self._clock()
        event = TraceEvent(
            event_id=self._id_factory(),
            timestamp=stamp,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
            actor=_validate_actor(actor),
            comment=_optional_text(comment),
        )
        # The history list is replaced, never mutated in place: a snapshot
        # taken before the change keeps its own (immutable) events.
        trace.history = [*trace.history, event]
        trace.updated_at = stamp
        return trace

    def _change_status(
        self,
        trace: RequirementTrace,
        *,
        new_status: str,
        actor: str,
        comment: str | None,
        allow_missing_evidence: bool = False,
    ) -> RequirementTrace:
        chosen = _validate_choice(new_status, STATUSES, "Le statut de traçabilité")
        if chosen == trace.status:
            return trace
        if chosen == "waived":
            raise UserFacingError("Une exigence écartée doit porter une justification : utilise l'action « écarter ».")
        if chosen in STATUSES_REQUIRING_EVIDENCE and not allow_missing_evidence:
            if not trace.evidence_id or not trace.evidence_quote:
                raise UserFacingError(
                    "Une exigence couverte doit référencer une preuve (evidence_id + evidence_quote). "
                    "Relie d'abord une preuve, puis change le statut."
                )
        if chosen == "uncovered" and trace.evidence_id:
            previous_evidence = trace.evidence_id
            trace.evidence_id = None
            trace.evidence_quote = None
            trace.auto_linked = False
            trace.validated = None
            trace = self._append_event(
                trace,
                event_type="unlinked",
                old_value=previous_evidence,
                new_value=None,
                actor=actor,
                comment=comment,
            )
        trace = self._append_event(
            trace,
            event_type="status_changed",
            old_value=trace.status,
            new_value=chosen,
            actor=actor,
            comment=comment,
        )
        trace.status = chosen
        return trace


# ---------------------------------------------------------------------------
# Adapters — SK-02 (offer requirements) and SK-21 (matching)
# ---------------------------------------------------------------------------


def criticality_from_modality(
    modality: str, requirement_text: str = "", heading: str = ""
) -> str:
    """Map an SK-02 modality onto a traceability criticality.

    SK-02 groups every optional statement under ``preferred``.  The
    distinction between "appreciated" and "nice to have" is carried by the
    section heading or by an explicit marker, so both are inspected here.
    """
    key = clean_text(modality, limit=40).lower()
    criticality = OFFER_MODALITY_MAP.get(key, "contextual")
    if criticality != "preferred":
        return criticality
    normalized = normalized_text(f"{heading} {requirement_text}")
    if any(marker in normalized for marker in _NICE_TO_HAVE_MARKERS):
        return "nice_to_have"
    return criticality


def category_from_offer_category(category: str) -> str:
    """Map an SK-02 category onto a traceability category."""
    key = clean_text(category, limit=40).lower()
    mapped = OFFER_CATEGORY_MAP.get(key, "other")
    return mapped if mapped in CATEGORIES else "other"


def sync_offer_analysis(
    registry: TraceabilityRegistry,
    analysis: dict[str, Any],
    *,
    actor: str = "system",
    comment: str | None = None,
    include_injection_suspects: bool = False,
) -> dict[str, Any]:
    """Create or refresh the traces of one SK-02 offer analysis.

    The analysis is the documented contract of ``analyze_offer()``.  Only the
    requirements that the extractor actually found become traces; the text is
    copied verbatim and never rewritten.  Requirements flagged as injection
    suspects are skipped by default: an offer is untrusted data, never an
    instruction.
    """
    if not isinstance(analysis, dict):
        raise UserFacingError("L'analyse d'offre est invalide.")
    offer_id = clean_text(analysis.get("offer_id"), limit=160)
    source = f"offer_{offer_id}" if offer_id else "manual"
    records = analysis.get("requirements")
    if not isinstance(records, list):
        records = []

    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    skipped: list[dict[str, str]] = []

    by_requirement_id = {
        trace.requirement_id: trace
        for trace in registry.list()
        if trace.requirement_id and trace.source == source
    }

    for record in records:
        if not isinstance(record, dict):
            continue
        requirement_id = clean_text(record.get("id"), limit=160)
        requirement_text = clean_text(record.get("text"), limit=MAX_REQUIREMENT_TEXT)
        if not requirement_text:
            continue
        if record.get("injection_suspect") and not include_injection_suspects:
            skipped.append({"requirement_id": requirement_id, "reason": "injection_suspect"})
            continue
        category = category_from_offer_category(record.get("category"))
        criticality = criticality_from_modality(
            record.get("modality"), requirement_text, record.get("heading")
        )
        confidence = record.get("confidence")
        confidence_value = float(confidence) if isinstance(confidence, (int, float)) else None

        existing = by_requirement_id.get(requirement_id) if requirement_id else None
        if existing is None:
            trace = registry.create(
                requirement_id=requirement_id,
                requirement_text=requirement_text,
                source=source,
                category=category,
                criticality=criticality,
                offer_id=offer_id,
                source_field=clean_text(record.get("source_field"), limit=80),
                locator=clean_text(record.get("locator"), limit=80),
                confidence=confidence_value,
                actor=actor,
                comment=comment,
            )
            created.append(trace.trace_id)
            continue

        changed = False
        if existing.requirement_text != requirement_text:
            existing = registry.update_requirement_text(
                existing.trace_id,
                requirement_text=requirement_text,
                actor=actor,
                comment=comment,
            )
            changed = True
        if existing.category != category:
            existing = registry.update(existing.trace_id, category=category, actor=actor, comment=comment)
            changed = True
        if existing.criticality != criticality:
            existing = registry.update(existing.trace_id, criticality=criticality, actor=actor, comment=comment)
            changed = True
        if changed:
            updated.append(existing.trace_id)
        else:
            unchanged.append(existing.trace_id)

    return {
        "source": source,
        "offer_id": offer_id,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "skipped": skipped,
    }


def apply_match_result(
    registry: TraceabilityRegistry,
    match_result: Any,
    *,
    actor: str = "system",
    comment: str | None = None,
    evidence_by_requirement: dict[str, str] | None = None,
    covered_threshold: float = AUTO_LINK_COVERED_THRESHOLD,
) -> dict[str, Any]:
    """Link the proofs returned by the SK-21 matcher to the matching traces.

    ``match_result`` is duck-typed on purpose: the SK-21 module exposes
    ``MatchResult.actions`` (one action per requirement, with the verbatim CV
    excerpt when a proof exists) and this adapter works with that shape as
    well as with a plain dictionary.

    Only the actions that carry an actual excerpt are linked, and the link
    is flagged ``auto``: a human still confirms or rejects it.
    """
    actions = _match_actions(match_result)
    evidence_map = {
        normalized_text(key): value for key, value in (evidence_by_requirement or {}).items()
    }
    linked: list[dict[str, Any]] = []
    already_linked: list[str] = []
    no_evidence: list[str] = []
    unmatched: list[str] = []

    for action in actions:
        requirement_text = clean_text(
            _action_value(action, "requirement_text") or _action_value(action, "requirement"), limit=MAX_REQUIREMENT_TEXT
        )
        if not requirement_text:
            continue
        evidence_text = clean_text(
            _action_value(action, "cv_evidence_text") or _action_value(action, "evidence_text"), limit=MAX_EVIDENCE_QUOTE
        )
        if not evidence_text:
            no_evidence.append(requirement_text)
            continue

        trace = _find_trace_by_text(registry, requirement_text)
        if trace is None:
            unmatched.append(requirement_text)
            continue
        if trace.evidence_id and trace.evidence_quote == evidence_text:
            already_linked.append(trace.trace_id)
            continue

        confidence = _action_value(action, "confidence")
        confidence_value = float(confidence) if isinstance(confidence, (int, float)) else 0.0
        status = "covered" if confidence_value >= covered_threshold else "partial"
        evidence_id = evidence_map.get(normalized_text(requirement_text)) or _synthetic_evidence_id(evidence_text)
        registry.link_evidence(
            trace.trace_id,
            evidence_id=evidence_id,
            evidence_quote=evidence_text,
            status=status,
            actor=actor,
            comment=comment or clean_text(_action_value(action, "reason"), limit=MAX_COMMENT) or None,
            auto=True,
        )
        linked.append(
            {
                "trace_id": trace.trace_id,
                "requirement_text": requirement_text,
                "evidence_id": evidence_id,
                "status": status,
                "confidence": confidence_value,
            }
        )

    return {
        "linked": linked,
        "already_linked": already_linked,
        "no_evidence": no_evidence,
        "unmatched": unmatched,
    }


# ---------------------------------------------------------------------------
# Export / import
# ---------------------------------------------------------------------------

EXPORT_SCHEMA_VERSION = 1

CSV_COLUMNS: tuple[str, ...] = (
    "trace_id",
    "requirement_id",
    "requirement_text",
    "source",
    "offer_id",
    "cv_id",
    "category",
    "criticality",
    "status",
    "evidence_id",
    "evidence_quote",
    "tags",
    "auto_linked",
    "validated",
    "waiver_reason",
    "source_field",
    "locator",
    "confidence",
    "created_at",
    "updated_at",
    "history_length",
)


def export_traces(traces: Sequence[RequirementTrace], *, export_format: str = "json") -> str:
    """Export the registry as JSON (with the history) or CSV (current state)."""
    fmt = clean_text(export_format, limit=10).lower() or "json"
    if fmt == "csv":
        return export_traces_csv(traces)
    if fmt != "json":
        raise UserFacingError("Le format d'export doit être json ou csv.")
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": utc_now(),
        "traces": [trace.to_dict() for trace in traces],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def export_traces_csv(traces: Sequence[RequirementTrace]) -> str:
    """Export the current state of the registry as CSV."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for trace in traces:
        writer.writerow(
            [
                trace.trace_id,
                trace.requirement_id,
                trace.requirement_text,
                trace.source,
                trace.offer_id,
                trace.cv_id,
                trace.category,
                trace.criticality,
                trace.status,
                trace.evidence_id or "",
                trace.evidence_quote or "",
                "|".join(trace.tags),
                "1" if trace.auto_linked else "0",
                "" if trace.validated is None else ("1" if trace.validated else "0"),
                trace.waiver_reason or "",
                trace.source_field,
                trace.locator,
                "" if trace.confidence is None else trace.confidence,
                trace.created_at,
                trace.updated_at,
                len(trace.history),
            ]
        )
    return buffer.getvalue()


def import_traces(
    registry: TraceabilityRegistry,
    payload: dict[str, Any],
    *,
    actor: str = "system",
    comment: str | None = None,
) -> dict[str, Any]:
    """Import traces exported by :func:`export_traces`.

    The import is conservative: a trace that already exists is skipped (the
    local history wins), and an invalid trace is reported instead of being
    silently repaired.
    """
    if not isinstance(payload, dict):
        raise UserFacingError("Le contenu d'import est invalide.")
    records = payload.get("traces")
    if not isinstance(records, list):
        raise UserFacingError("Le contenu d'import ne contient aucune trace.")
    imported: list[str] = []
    skipped: list[str] = []
    invalid: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            invalid.append({"reason": "not_an_object"})
            continue
        trace_id = clean_text(record.get("trace_id"), limit=80)
        if trace_id and trace_id in registry:
            skipped.append(trace_id)
            continue
        try:
            trace = RequirementTrace.from_dict(record)
        except (TypeError, ValueError):
            invalid.append({"trace_id": trace_id, "reason": "invalid_payload"})
            continue
        if not trace.requirement_text:
            invalid.append({"trace_id": trace_id, "reason": "missing_requirement_text"})
            continue
        registry.restore(trace)
        imported.append(trace.trace_id)
    return {
        "imported": imported,
        "skipped": skipped,
        "invalid": invalid,
        "actor": actor,
        "comment": comment,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _action_value(action: Any, name: str) -> Any:
    if isinstance(action, dict):
        return action.get(name)
    return getattr(action, name, None)


def _match_actions(match_result: Any) -> list[Any]:
    actions = _action_value(match_result, "actions")
    if actions is None and isinstance(match_result, (list, tuple)):
        actions = match_result
    return list(actions) if isinstance(actions, (list, tuple)) else []


def _find_trace_by_text(registry: TraceabilityRegistry, requirement_text: str) -> RequirementTrace | None:
    exact = normalized_text(requirement_text)
    if not exact:
        return None
    candidates = [trace for trace in registry.list() if not trace.deleted]
    for trace in candidates:
        if trace.requirement_text == requirement_text:
            return trace
    for trace in candidates:
        if normalized_text(trace.requirement_text) == exact:
            return trace
    fingerprint = _requirement_fingerprint(requirement_text)
    for trace in candidates:
        if _requirement_fingerprint(trace.requirement_text) == fingerprint:
            return trace
    return None


def _synthetic_evidence_id(evidence_text: str) -> str:
    digest = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()[:16]
    return f"evidence_auto_{digest}"
