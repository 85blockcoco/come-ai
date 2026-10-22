"""Registre de traçabilité des exigences (SPEC-011).

Ce module est le **cœur** du registre : des modèles, un registre en mémoire
et les règles métier.  Il ne touche ni au disque, ni au réseau, ni à un
modèle de langage : tout y est déterministe et vérifiable.

CE QUE LE REGISTRE GARANTIT
---------------------------
1. **Une exigence, une trace.**  Chaque exigence extraite d'une offre (SK-02)
   reçoit une :source:`RequirementTrace` avec son texte *verbatim*, sa
   provenance (champ source, locator), sa catégorie, sa criticité et son
   statut.
2. **Une preuve, ou l'absence de preuve.**  Une trace porte soit une preuve
   (``evidence_id`` + ``evidence_quote``), soit le statut ``uncovered`` :
   l'absence de preuve n'est jamais maquillée en couverture.
3. **Un historique immuable.**  Chaque mutation ajoute un :class:`TraceEvent`
   *frozen* ; les événements passés ne sont jamais réécrits ni supprimés.
4. **Une couverture honnête.**  Un lien automatique (matching SK-21) reste
   ``pending`` tant qu'une personne ne l'a pas confirmé : une machine ne
   décide jamais qu'une exigence est couverte.

DÉTERMINISME
------------
Aucun ``random``, aucune horloge système cachée, aucun appel réseau :

* ``trace_id`` est un UUID **version 5** dérivé de ``(source, requirement_id)``
  — réimporter la même exigence retombe sur la même trace ;
* ``event_id`` est un hachage du contenu de l'événement (trace, type,
  horodatage, anciennes et nouvelles valeurs, index) ;
* l'horloge est injectable (``clock``) pour rejouer une scène à l'identique.

INTÉGRATIONS (contrats stables, jamais de dépendance dure)
-----------------------------------------------------------
* **SK-02** — :meth:`TraceabilityRegistry.register_offer_analysis` consomme la
  sortie de ``career.offer_requirements.analyze_offer`` (categories et
  modalités mappées, provenance conservée).
* **SK-10** — les preuves du profil sont consommées à travers
  :func:`evidence_view`, qui lit indifféremment un dictionnaire ou un objet
  portant ``evidence_id``/``claim``/``quote`` : le module ne dépend donc ni
  du centre de preuves (SPEC-008) ni du profil candidat (SK-10), qui vivent
  sur d'autres branches.
* **SK-21** — :func:`auto_link_evidence` propose un lien automatique quand
  la preuve correspond *exactement* à l'exigence (ou que l'exigence est
  citée mot pour mot dans la preuve).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from workspace_core import UserFacingError

from .models import clean_text, normalized_text, utc_now


__all__ = [
    "ACTORS",
    "CATEGORIES",
    "CRITICALITIES",
    "EVENT_TYPES",
    "LINK_ORIGINS",
    "REVIEW_STATES",
    "STATUSES",
    "RequirementTrace",
    "TraceEvent",
    "TraceabilityError",
    "TraceabilityRegistry",
    "auto_link_evidence",
    "evidence_view",
    "map_criticality",
    "map_category",
    "requirement_trace_id",
]


# ── Vocabulaire fermé ───────────────────────────────────────────────────────

#: Catégories métier du registre (vocabulaire de la mission).
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

#: Criticités : une exigence obligatoire n'est jamais « preferred ».
CRITICALITIES: tuple[str, ...] = ("mandatory", "preferred", "nice_to_have", "contextual")

#: Statuts de couverture d'une exigence.
STATUSES: tuple[str, ...] = ("uncovered", "covered", "partial", "contradicted", "waived")

#: Types d'événements.  Les huit premiers sont ceux du contrat SPEC-011 ;
#: ``tags_changed``, ``deleted``, ``link_confirmed`` et ``link_rejected`` sont
#: des extensions nécessaires à la règle « toute modification est tracée »
#: (les tags sont modifiables), à l'objectif « traquer les suppressions » et
#: à la validation manuelle des liaisons automatiques (règle métier n° 3).
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
    "deleted",
    "link_confirmed",
    "link_rejected",
)

#: Auteur d'un événement.
ACTORS: tuple[str, ...] = ("system", "user", "worker")

#: État de validation d'un lien (manuel ou automatique).
REVIEW_STATES: tuple[str, ...] = ("not_required", "pending", "confirmed", "rejected")

#: Origine d'un lien de preuve.
LINK_ORIGINS: tuple[str, ...] = ("manual", "auto")

TRACE_ID_PREFIX = "trace_"
EVENT_ID_PREFIX = "event_"

#: Namespace fixe du UUID déterministe (version 5) des traces.
TRACE_NAMESPACE = uuid.UUID("2f1c9a0e-6d5b-4f2a-9d3c-8b7e5a1c4d90")

#: Bornes de garde : le registre refuse de devenir illisible.
MAX_REQUIREMENT_CHARS = 4_000
MAX_EVIDENCE_QUOTE_CHARS = 4_000
MAX_TAGS = 20
MAX_TAG_CHARS = 60
MAX_COMMENT_CHARS = 2_000
MAX_EVENTS_PER_TRACE = 2_000

#: Longueur minimale (caractères normalisés) pour qu'une citation suffise à
#: établir une correspondance : en dessous, « Python » correspondrait à
#: n'importe quelle preuve qui le contient.
MIN_QUOTE_MATCH_CHARS = 12


class TraceabilityError(UserFacingError):
    """Erreur métier du registre — message affichable, sans trace technique."""


# ── Correspondances avec le contrat SK-02 (Mission 02) ─────────────────────

#: Catégories du contrat SK-02 → catégories du registre.
_SK02_CATEGORY_MAP: dict[str, str] = {
    "technical_skill": "skill",
    "language": "language",
    "education": "education",
    "experience": "experience",
    "availability": "other",
    "mobility": "other",
    "work_authorization": "other",
    "other": "other",
}

#: Modalités du contrat SK-02 → criticités du registre.
_SK02_MODALITY_MAP: dict[str, str] = {
    "required": "mandatory",
    "preferred": "preferred",
    "contextual": "contextual",
    "unknown": "contextual",
}


def map_category(value: Any) -> str:
    """Return the registry category for a SK-02 category (or a raw category).

    An unknown SK-02 category becomes ``other`` — never a guess.  A raw
    registry category that is already valid is kept as-is.
    """
    text = clean_text(value, limit=60).lower()
    if text in CATEGORIES:
        return text
    return _SK02_CATEGORY_MAP.get(text, "other")


def map_criticality(value: Any) -> str:
    """Return the registry criticality for a SK-02 modality (or a raw value).

    ``unknown`` (modalité SK-02) becomes ``contextual`` — the least
    committal criticality — because the registry vocabulary has no
    "unknown"; the original modality is never lost, it stays in the trace's
    ``source_field``/notes of the creation event.
    """
    text = clean_text(value, limit=60).lower()
    if text in CRITICALITIES:
        return text
    return _SK02_MODALITY_MAP.get(text, "contextual")


def requirement_trace_id(source: str, requirement_id: str) -> str:
    """Return the deterministic trace id of ``(source, requirement_id)``.

    UUID version 5 : unique, stable et recalculable.  Deux imports de la
    même exigence produisent donc **la même** trace (import idempotent).
    """
    key = f"{clean_text(source, limit=200)}|{clean_text(requirement_id, limit=200)}"
    digest = uuid.uuid5(TRACE_NAMESPACE, key)
    return f"{TRACE_ID_PREFIX}{digest}"


def _event_id(
    trace_id: str,
    event_type: str,
    timestamp: str,
    old_value: str | None,
    new_value: str | None,
    index: int,
) -> str:
    """Return a deterministic event id (content hash, no randomness)."""
    payload = "|".join(
        [
            trace_id,
            event_type,
            timestamp,
            old_value or "",
            new_value or "",
            str(index),
        ]
    )
    return EVENT_ID_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _collapse(value: Any) -> str:
    """Lowercase and collapse whitespace — used for verbatim containment."""
    return " ".join(str(value or "").lower().split())


def _choice(value: Any, allowed: Sequence[str], label: str, *, default: str | None = None) -> str:
    text = clean_text(value, limit=64).lower()
    if not text:
        if default is not None:
            return default
        raise TraceabilityError(f"{label} est obligatoire.")
    if text not in allowed:
        raise TraceabilityError(
            f"{label} invalide : « {text} ». Valeurs acceptées : {', '.join(allowed)}."
        )
    return text


def _bounded_tags(values: Any) -> list[str]:
    """Normalize a tag list: lowercase, bounded, deduplicated, ordered.

    The order never depends on the hash seed: insertion order is kept.
    """
    if not isinstance(values, (list, tuple)):
        return []
    seen: set[str] = set()
    tags: list[str] = []
    for raw in values:
        tag = clean_text(raw, limit=MAX_TAG_CHARS).lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags


# ── Modèles ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TraceEvent:
    """An immutable entry of a requirement history."""

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
    def from_dict(cls, payload: Mapping[str, Any]) -> "TraceEvent":
        return cls(
            event_id=clean_text(payload.get("event_id"), limit=80),
            timestamp=clean_text(payload.get("timestamp"), limit=40),
            event_type=clean_text(payload.get("event_type"), limit=40),
            old_value=clean_text(payload.get("old_value"), limit=MAX_COMMENT_CHARS) or None,
            new_value=clean_text(payload.get("new_value"), limit=MAX_COMMENT_CHARS) or None,
            actor=clean_text(payload.get("actor"), limit=40) or "system",
            comment=clean_text(payload.get("comment"), limit=MAX_COMMENT_CHARS) or None,
        )


@dataclass
class RequirementTrace:
    """The traceability record of one requirement.

    The dataclass carries the contract of the mission (``trace_id``,
    ``requirement_id``, ``requirement_text``, ``source``, ``category``,
    ``criticality``, ``evidence_id``, ``evidence_quote``, ``status``,
    ``created_at``, ``updated_at``, ``history``, ``tags``) plus the
    provenance needed by the audit reports (``offer_id``, ``cv_id``,
    ``locator``, ``source_field``, ``confidence``) and the review state of an
    automatic link (``link_origin``, ``review_state``, ``match_kind``).
    """

    trace_id: str
    requirement_id: str
    requirement_text: str
    source: str
    category: str = "other"
    criticality: str = "contextual"
    evidence_id: str | None = None
    evidence_quote: str | None = None
    status: str = "uncovered"
    created_at: str = ""
    updated_at: str = ""
    history: list[TraceEvent] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    offer_id: str = ""
    cv_id: str = ""
    locator: str = ""
    source_field: str = ""
    confidence: float | None = None
    link_origin: str = "manual"
    review_state: str = "not_required"
    match_kind: str = ""
    deleted: bool = False
    deleted_at: str = ""

    # -- properties ---------------------------------------------------------
    @property
    def is_deleted(self) -> bool:
        return bool(self.deleted)

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence_id)

    @property
    def is_covered(self) -> bool:
        return self.status == "covered"

    # -- serialisation ------------------------------------------------------
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
            "locator": self.locator,
            "source_field": self.source_field,
            "confidence": self.confidence,
            "link_origin": self.link_origin,
            "review_state": self.review_state,
            "match_kind": self.match_kind,
            "deleted": self.deleted,
            "deleted_at": self.deleted_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RequirementTrace":
        confidence = payload.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        history = [
            TraceEvent.from_dict(event)
            for event in payload.get("history", [])
            if isinstance(event, Mapping)
        ]
        return cls(
            trace_id=clean_text(payload.get("trace_id"), limit=120),
            requirement_id=clean_text(payload.get("requirement_id"), limit=200),
            requirement_text=clean_text(payload.get("requirement_text"), limit=MAX_REQUIREMENT_CHARS),
            source=clean_text(payload.get("source"), limit=200),
            category=map_category(payload.get("category")),
            criticality=map_criticality(payload.get("criticality")),
            evidence_id=clean_text(payload.get("evidence_id"), limit=200) or None,
            evidence_quote=clean_text(payload.get("evidence_quote"), limit=MAX_EVIDENCE_QUOTE_CHARS) or None,
            status=_choice(payload.get("status"), STATUSES, "Statut", default="uncovered"),
            created_at=clean_text(payload.get("created_at"), limit=40),
            updated_at=clean_text(payload.get("updated_at"), limit=40),
            history=history,
            tags=_bounded_tags(payload.get("tags")),
            offer_id=clean_text(payload.get("offer_id"), limit=120),
            cv_id=clean_text(payload.get("cv_id"), limit=120),
            locator=clean_text(payload.get("locator"), limit=200),
            source_field=clean_text(payload.get("source_field"), limit=120),
            confidence=confidence_value,
            link_origin=_choice(payload.get("link_origin"), LINK_ORIGINS, "Origine du lien", default="manual"),
            review_state=_choice(payload.get("review_state"), REVIEW_STATES, "État de validation", default="not_required"),
            match_kind=clean_text(payload.get("match_kind"), limit=60),
            deleted=bool(payload.get("deleted")),
            deleted_at=clean_text(payload.get("deleted_at"), limit=40),
        )


# ── Registre ────────────────────────────────────────────────────────────────


class TraceabilityRegistry:
    """In-memory registry of requirement traces.

    The registry owns the *rules*; the persistence (SQLite) lives in
    ``career.traceability_store``.  Every mutation appends an immutable
    event and refreshes ``updated_at``.
    """

    def __init__(self, *, clock: Callable[[], str] = utc_now) -> None:
        self._clock = clock
        self._traces: dict[str, RequirementTrace] = {}

    # -- helpers ------------------------------------------------------------
    def _now(self) -> str:
        return self._clock()

    def _record(
        self,
        trace: RequirementTrace,
        event_type: str,
        *,
        old_value: str | None = None,
        new_value: str | None = None,
        actor: str = "system",
        comment: str | None = None,
    ) -> TraceEvent:
        timestamp = self._now()
        event = TraceEvent(
            event_id=_event_id(
                trace.trace_id,
                event_type,
                timestamp,
                old_value,
                new_value,
                len(trace.history),
            ),
            timestamp=timestamp,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
            actor=actor,
            comment=clean_text(comment, limit=MAX_COMMENT_CHARS) or None,
        )
        trace.history.append(event)
        trace.updated_at = timestamp
        return event

    def _require(self, trace_id: str) -> RequirementTrace:
        trace = self._traces.get(clean_text(trace_id, limit=120))
        if trace is None or trace.deleted:
            raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
        return trace

    @staticmethod
    def _split_source(source: str) -> tuple[str, str]:
        text = clean_text(source, limit=200)
        if text.startswith("offer_"):
            return "offer", text[len("offer_") :]
        if text.startswith("cv_"):
            return "cv", text[len("cv_") :]
        if text == "manual":
            return "manual", ""
        return "external", text

    # -- creation -----------------------------------------------------------
    def register(
        self,
        requirement_id: str,
        requirement_text: str,
        source: str,
        *,
        category: str = "other",
        criticality: str = "contextual",
        tags: Sequence[str] = (),
        actor: str = "system",
        comment: str | None = None,
        offer_id: str = "",
        cv_id: str = "",
        locator: str = "",
        source_field: str = "",
        confidence: float | None = None,
        status: str = "uncovered",
    ) -> RequirementTrace:
        """Register one requirement — idempotent on ``(source, requirement_id)``.

        Registering the same requirement twice returns the existing trace
        untouched (no duplicated event): importing an offer twice must not
        inflate the audit trail.
        """
        identifier = clean_text(requirement_id, limit=200)
        text = clean_text(requirement_text, limit=MAX_REQUIREMENT_CHARS)
        if not identifier:
            raise TraceabilityError("L’exigence doit avoir un identifiant.")
        if not text:
            raise TraceabilityError("L’exigence doit avoir un texte.")

        source_text = clean_text(source, limit=200) or "manual"
        trace_id = requirement_trace_id(source_text, identifier)
        existing = self._traces.get(trace_id)
        if existing is not None:
            return existing

        kind, source_identifier = self._split_source(source_text)
        resolved_offer = clean_text(offer_id, limit=120) or (source_identifier if kind == "offer" else "")
        resolved_cv = clean_text(cv_id, limit=120) or (source_identifier if kind == "cv" else "")
        status_value = _choice(status, STATUSES, "Statut", default="uncovered")
        if status_value == "covered":
            raise TraceabilityError(
                "Une exigence ne peut pas être créée « covered » sans preuve : lie une preuve d’abord."
            )
        if status_value == "waived":
            raise TraceabilityError("Une exigence ne peut pas être créée « waived » sans justification.")

        timestamp = self._now()
        trace = RequirementTrace(
            trace_id=trace_id,
            requirement_id=identifier,
            requirement_text=text,
            source=source_text,
            category=map_category(category),
            criticality=map_criticality(criticality),
            evidence_id=None,
            evidence_quote=None,
            status=status_value,
            created_at=timestamp,
            updated_at=timestamp,
            history=[],
            tags=_bounded_tags(tags),
            offer_id=resolved_offer,
            cv_id=resolved_cv,
            locator=clean_text(locator, limit=200),
            source_field=clean_text(source_field, limit=120),
            confidence=confidence,
            link_origin="manual",
            review_state="not_required",
        )
        self._record(
            trace,
            "created",
            new_value=status_value,
            actor=actor,
            comment=comment or "Exigence enregistrée dans le registre de traçabilité.",
        )
        self._traces[trace_id] = trace
        return trace

    def register_offer_analysis(
        self,
        analysis: Mapping[str, Any],
        *,
        actor: str = "system",
        comment: str | None = None,
    ) -> list[RequirementTrace]:
        """Register every requirement of a SK-02 ``analyze_offer`` result.

        The SK-02 contract is consumed as-is: the verbatim text, the locator,
        the source field and the confidence are preserved, and the category /
        modality are mapped to the registry vocabulary.  Records without an
        identifier or without text are skipped (nothing is invented), and so
        are the statements flagged ``injection_suspect``: an offer is
        untrusted data, never an instruction, and a flagged statement never
        becomes a requirement.
        """
        payload = analysis or {}
        offer_id = clean_text(payload.get("offer_id"), limit=120)
        source = f"offer_{offer_id}" if offer_id else "manual"
        traces: list[RequirementTrace] = []
        records = payload.get("requirements") or []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            if record.get("injection_suspect"):
                continue
            identifier = clean_text(record.get("id"), limit=200)
            text = clean_text(record.get("text"), limit=MAX_REQUIREMENT_CHARS)
            if not identifier or not text:
                continue
            traces.append(
                self.register(
                    identifier,
                    text,
                    source,
                    category=map_category(record.get("category")),
                    criticality=map_criticality(record.get("modality")),
                    actor=actor,
                    comment=comment or "Enregistrement automatique depuis l’analyse d’offre (SK-02).",
                    offer_id=offer_id,
                    locator=clean_text(record.get("locator"), limit=200),
                    source_field=clean_text(record.get("source_field"), limit=120),
                    confidence=record.get("confidence"),
                )
            )
        return traces

    def register_facts(
        self,
        facts: Iterable[Mapping[str, Any]],
        *,
        cv_id: str,
        actor: str = "system",
        comment: str | None = None,
    ) -> list[RequirementTrace]:
        """Register profile facts (SK-10) as requirements of a CV.

        The facts are read defensively (``id``/``text``/``kind``): the
        registry does not depend on the candidate-profile module.
        """
        source = f"cv_{clean_text(cv_id, limit=120)}" if cv_id else "manual"
        traces: list[RequirementTrace] = []
        for fact in facts or []:
            if not isinstance(fact, Mapping):
                continue
            identifier = clean_text(fact.get("id"), limit=200)
            text = clean_text(fact.get("text") or fact.get("claim"), limit=MAX_REQUIREMENT_CHARS)
            if not identifier or not text:
                continue
            traces.append(
                self.register(
                    identifier,
                    text,
                    source,
                    category=map_category(fact.get("kind") or fact.get("category")),
                    criticality=map_criticality(fact.get("criticality") or fact.get("modality")),
                    actor=actor,
                    comment=comment or "Enregistrement automatique depuis le profil candidat (SK-10).",
                    cv_id=cv_id,
                )
            )
        return traces

    # -- evidence link ------------------------------------------------------
    def link_evidence(
        self,
        trace_id: str,
        *,
        evidence_id: str,
        evidence_quote: str | None = None,
        actor: str = "user",
        comment: str | None = None,
        origin: str = "manual",
        status: str | None = None,
        match_kind: str = "",
    ) -> RequirementTrace:
        """Link an evidence item to a requirement.

        A manual link marks the requirement ``covered`` (the person vouched
        for it).  An automatic link (``origin="auto"``) does **not** claim a
        coverage: the trace stays in review (``review_state="pending"``) until
        a person confirms or rejects it.
        """
        trace = self._require(trace_id)
        evidence = clean_text(evidence_id, limit=200)
        if not evidence:
            raise TraceabilityError("La preuve doit avoir un identifiant.")
        quote = clean_text(evidence_quote, limit=MAX_EVIDENCE_QUOTE_CHARS) or None
        origin_value = _choice(origin, LINK_ORIGINS, "Origine du lien", default="manual")
        actor_value = _choice(actor, ACTORS, "Auteur", default="user")

        old_evidence = trace.evidence_id
        old_quote = trace.evidence_quote
        trace.evidence_id = evidence
        trace.evidence_quote = quote
        trace.link_origin = origin_value
        trace.match_kind = clean_text(match_kind, limit=60)
        trace.review_state = "pending" if origin_value == "auto" else "confirmed"
        # The event is immutable: the replaced proof is written in the comment
        # before the event is recorded, never patched afterwards.
        event_comment = clean_text(comment, limit=MAX_COMMENT_CHARS) or None
        if old_evidence and old_evidence != evidence:
            event_comment = clean_text(
                f"{event_comment or ''} (preuve remplacée : {old_evidence})".strip(),
                limit=MAX_COMMENT_CHARS,
            )
        if old_quote and old_quote != quote:
            event_comment = clean_text(
                f"{event_comment or ''} (citation précédente : {old_quote[:200]})".strip(),
                limit=MAX_COMMENT_CHARS,
            )
        self._record(
            trace,
            "linked",
            old_value=old_evidence,
            new_value=evidence,
            actor=actor_value,
            comment=event_comment,
        )

        if status is not None:
            self.set_status(trace.trace_id, status, actor=actor_value, comment=comment)
        elif origin_value == "manual" and quote and trace.status in {"uncovered", "partial"}:
            # A manual link is only a coverage when it carries its citation:
            # an evidence without a quote proves nothing yet.
            self.set_status(trace.trace_id, "covered", actor=actor_value, comment=comment)
        return trace

    def unlink_evidence(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
        status: str | None = "uncovered",
        review_state: str = "not_required",
    ) -> RequirementTrace:
        """Unlink the evidence of a requirement (the proof stays in history)."""
        trace = self._require(trace_id)
        old_evidence = trace.evidence_id
        old_quote = trace.evidence_quote
        trace.evidence_id = None
        trace.evidence_quote = None
        trace.review_state = _choice(review_state, REVIEW_STATES, "État de validation", default="not_required")
        trace.match_kind = ""
        event_comment = clean_text(comment, limit=MAX_COMMENT_CHARS) or None
        if old_quote:
            event_comment = clean_text(
                f"{event_comment or ''} (citation retirée : {old_quote[:200]})".strip(),
                limit=MAX_COMMENT_CHARS,
            )
        self._record(
            trace,
            "unlinked",
            old_value=old_evidence,
            new_value=None,
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=event_comment,
        )
        if status is not None and trace.status != status:
            self.set_status(trace.trace_id, status, actor=actor, comment=comment)
        return trace

    def confirm_link(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Confirm an automatic link: the requirement becomes ``covered``."""
        trace = self._require(trace_id)
        if not trace.evidence_id:
            raise TraceabilityError("Cette exigence n’a aucune preuve à valider.")
        trace.review_state = "confirmed"
        self._record(
            trace,
            "link_confirmed",
            old_value="pending",
            new_value="confirmed",
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=comment or "Liaison automatique confirmée manuellement.",
        )
        if trace.status != "covered":
            self.set_status(trace.trace_id, "covered", actor=actor, comment=comment)
        return trace

    def reject_link(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        reason: str | None = None,
    ) -> RequirementTrace:
        """Reject an automatic link: the proof is unlinked, status back to open."""
        trace = self._require(trace_id)
        if not trace.evidence_id:
            raise TraceabilityError("Cette exigence n’a aucune preuve à rejeter.")
        old_evidence = trace.evidence_id
        trace.review_state = "rejected"
        self._record(
            trace,
            "link_rejected",
            old_value=old_evidence,
            new_value="rejected",
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=reason or "Liaison automatique rejetée manuellement.",
        )
        self.unlink_evidence(
            trace.trace_id,
            actor=actor,
            comment=None,
            status="uncovered",
            review_state="rejected",
        )
        return trace

    # -- mutations ----------------------------------------------------------
    def set_status(
        self,
        trace_id: str,
        status: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Change the status of a requirement (coherence rules enforced)."""
        trace = self._require(trace_id)
        status_value = _choice(status, STATUSES, "Statut")
        if status_value == "covered" and not (trace.evidence_id and trace.evidence_quote):
            raise TraceabilityError(
                "Une exigence « covered » doit porter une preuve (evidence_id) et sa citation (evidence_quote)."
            )
        if status_value == "waived":
            raise TraceabilityError(
                "Une exigence ne peut être « waived » que via la dérogation motivée (waive)."
            )
        if status_value == trace.status:
            return trace
        old_status = trace.status
        trace.status = status_value
        self._record(
            trace,
            "status_changed",
            old_value=old_status,
            new_value=status_value,
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=comment,
        )
        return trace

    def set_category(
        self,
        trace_id: str,
        category: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        trace = self._require(trace_id)
        value = _choice(category, CATEGORIES, "Catégorie")
        if value == trace.category:
            return trace
        old_value = trace.category
        trace.category = value
        self._record(
            trace,
            "category_changed",
            old_value=old_value,
            new_value=value,
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=comment,
        )
        return trace

    def set_criticality(
        self,
        trace_id: str,
        criticality: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        trace = self._require(trace_id)
        value = _choice(criticality, CRITICALITIES, "Criticité")
        if value == trace.criticality:
            return trace
        old_value = trace.criticality
        trace.criticality = value
        self._record(
            trace,
            "criticality_changed",
            old_value=old_value,
            new_value=value,
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=comment,
        )
        return trace

    def set_tags(
        self,
        trace_id: str,
        tags: Sequence[str],
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        trace = self._require(trace_id)
        values = _bounded_tags(tags)
        if values == trace.tags:
            return trace
        old_value = ", ".join(trace.tags)
        trace.tags = values
        self._record(
            trace,
            "tags_changed",
            old_value=old_value,
            new_value=", ".join(values),
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=comment,
        )
        return trace

    def waive(
        self,
        trace_id: str,
        justification: str,
        *,
        actor: str = "user",
    ) -> RequirementTrace:
        """Waive a requirement — a justification is mandatory."""
        trace = self._require(trace_id)
        reason = clean_text(justification, limit=MAX_COMMENT_CHARS)
        if not reason:
            raise TraceabilityError("Une dérogation doit être justifiée.")
        old_status = trace.status
        trace.status = "waived"
        self._record(
            trace,
            "waived",
            old_value=old_status,
            new_value="waived",
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=reason,
        )
        return trace

    def reopen(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Reopen a waived requirement (the justification stays in history)."""
        trace = self._require(trace_id)
        if trace.status != "waived":
            return trace
        old_status = trace.status
        new_status = "covered" if (trace.evidence_id and trace.evidence_quote) else "uncovered"
        trace.status = new_status
        self._record(
            trace,
            "reopened",
            old_value=old_status,
            new_value=new_status,
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=comment or "Dérogation levée : l’exigence redevient active.",
        )
        return trace

    def delete(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Soft-delete a requirement — the history is kept, never erased."""
        trace = self._require(trace_id)
        if trace.deleted:
            return trace
        trace.deleted = True
        trace.deleted_at = self._now()
        self._record(
            trace,
            "deleted",
            old_value=trace.status,
            new_value="deleted",
            actor=_choice(actor, ACTORS, "Auteur", default="user"),
            comment=comment or "Exigence supprimée du registre (historique conservé).",
        )
        return trace

    # -- reads --------------------------------------------------------------
    def get(self, trace_id: str) -> RequirementTrace | None:
        trace = self._traces.get(clean_text(trace_id, limit=120))
        if trace is None or trace.deleted:
            return None
        return trace

    def all(self, *, include_deleted: bool = False) -> list[RequirementTrace]:
        return [
            trace
            for trace in self._traces.values()
            if include_deleted or not trace.deleted
        ]

    def list_traces(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        criticality: str | None = None,
        offer_id: str | None = None,
        cv_id: str | None = None,
        source: str | None = None,
        tag: str | None = None,
        query: str | None = None,
        review_state: str | None = None,
        include_deleted: bool = False,
    ) -> list[RequirementTrace]:
        """Return the traces matching every given filter (AND semantics)."""
        traces = self.all(include_deleted=include_deleted)
        if status:
            wanted = _choice(status, STATUSES, "Statut")
            traces = [trace for trace in traces if trace.status == wanted]
        if category:
            wanted = _choice(category, CATEGORIES, "Catégorie")
            traces = [trace for trace in traces if trace.category == wanted]
        if criticality:
            wanted = _choice(criticality, CRITICALITIES, "Criticité")
            traces = [trace for trace in traces if trace.criticality == wanted]
        if offer_id:
            wanted = clean_text(offer_id, limit=120)
            traces = [trace for trace in traces if trace.offer_id == wanted]
        if cv_id:
            wanted = clean_text(cv_id, limit=120)
            traces = [trace for trace in traces if trace.cv_id == wanted]
        if source:
            wanted = clean_text(source, limit=200)
            traces = [trace for trace in traces if trace.source == wanted]
        if tag:
            wanted = clean_text(tag, limit=MAX_TAG_CHARS).lower()
            traces = [trace for trace in traces if wanted in trace.tags]
        if review_state:
            wanted = _choice(review_state, REVIEW_STATES, "État de validation")
            traces = [trace for trace in traces if trace.review_state == wanted]
        if query:
            needle = normalized_text(query)
            if needle:
                traces = [
                    trace
                    for trace in traces
                    if needle in normalized_text(trace.requirement_text)
                    or needle in normalized_text(trace.requirement_id)
                    or needle in normalized_text(trace.evidence_quote or "")
                    or any(needle in normalized_text(item) for item in trace.tags)
                ]
        return traces

    def __len__(self) -> int:
        return len(self._traces)

    # -- persistence helpers ------------------------------------------------
    def restore(self, trace: RequirementTrace) -> None:
        """Insert a persisted trace (no new event: its history is already there)."""
        self._traces[trace.trace_id] = trace

    def restore_all(self, traces: Iterable[RequirementTrace]) -> None:
        """Replace the registry content with the persisted traces."""
        self._traces.clear()
        for trace in traces:
            self.restore(trace)


# ── Intégration SK-21 : liaison automatique ─────────────────────────────────


def evidence_view(evidence: Any) -> dict[str, str]:
    """Normalize an evidence item (dict or object) into a flat view.

    The traceability module never imports the evidence center (SPEC-008) nor
    the candidate profile (SK-10): both are read through their public
    attributes only, so the registry works with any of them.
    """

    def read(*names: str) -> Any:
        if isinstance(evidence, Mapping):
            for name in names:
                if name in evidence:
                    return evidence[name]
            return ""
        for name in names:
            if hasattr(evidence, name):
                return getattr(evidence, name)
        return ""

    return {
        "evidence_id": clean_text(read("evidence_id", "id"), limit=200),
        "claim": clean_text(read("claim", "text", "label", "title"), limit=600),
        "quote": clean_text(read("quote", "excerpt", "source_text", "evidence_quote"), limit=MAX_EVIDENCE_QUOTE_CHARS),
        "kind": clean_text(read("kind", "type", "evidence_type"), limit=60),
    }


def _match_kind(trace: RequirementTrace, evidence: Mapping[str, str]) -> str:
    """Return the match kind between a requirement and an evidence.

    ``exact_claim`` — the evidence claim *is* the requirement (normalized).
    ``verbatim_quote`` — the requirement is quoted word for word inside the
    evidence quote (case and whitespace insensitive).

    Anything else is *not* a match: a fuzzy similarity would silently
    declare a requirement covered.
    """
    need = normalized_text(trace.requirement_text)
    if not need:
        return ""
    claim = normalized_text(evidence.get("claim"))
    if claim and claim == need:
        return "exact_claim"
    quote_raw = _collapse(evidence.get("quote"))
    need_raw = _collapse(trace.requirement_text)
    if need_raw and len(need) >= MIN_QUOTE_MATCH_CHARS and need_raw in quote_raw:
        return "verbatim_quote"
    return ""


def auto_link_evidence(
    registry: TraceabilityRegistry,
    evidences: Iterable[Any],
    *,
    actor: str = "system",
    comment: str | None = None,
) -> dict[str, Any]:
    """Propose an automatic link between the registry and the evidences.

    The automatic link is a *proposal*: the requirement keeps the status it
    had (usually ``uncovered``) and the link waits for a human validation
    (``review_state="pending"``).  A machine never decides that a requirement
    is covered.

    Returns a summary: ``linked``, ``pending``, ``skipped``, ``considered``.
    """
    views = [evidence_view(item) for item in evidences or []]
    views = [view for view in views if view["evidence_id"]]
    linked: list[dict[str, str]] = []
    considered = 0
    for trace in registry.all():
        if trace.status == "waived" or trace.evidence_id:
            continue
        considered += 1
        for view in views:
            kind = _match_kind(trace, view)
            if not kind:
                continue
            registry.link_evidence(
                trace.trace_id,
                evidence_id=view["evidence_id"],
                evidence_quote=view.get("quote") or None,
                actor=actor,
                comment=comment or f"Liaison automatique proposée ({kind}).",
                origin="auto",
                status=None,
                match_kind=kind,
            )
            linked.append(
                {
                    "trace_id": trace.trace_id,
                    "requirement_id": trace.requirement_id,
                    "evidence_id": view["evidence_id"],
                    "match_kind": kind,
                }
            )
            break
    return {
        "linked": linked,
        "linked_count": len(linked),
        "considered": considered,
        "skipped": len(views),
    }
