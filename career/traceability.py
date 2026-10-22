"""Registre de traçabilité des exigences (SPEC-011 — CVBOOST-46).

Le registre relie chaque exigence extraite d'une offre (SK-02) à la preuve
qui l'étaye (SK-10 / SK-21) et garde l'historique immuable de chaque
changement.  Il est la fondation de l'audit et de la conformité : une
exigence sans preuve reste visible comme un manque, jamais comme un acquis.

PRINCIPES STRUCTURELS (pas des conventions)
1. **Une exigence couverte porte toujours sa preuve.**  ``status="covered"``
   exige ``evidence_id`` *et* ``evidence_quote``.  Le registre ne couvre
   jamais une exigence à la place de l'utilisateur.
2. **L'historique est append-only.**  Un événement écrit n'est jamais
   modifié ni supprimé ; une correction passe par un nouvel événement.
3. **Rien n'est deviné.**  Une preuve, une citation ou un statut qui ne
   vient pas d'une source reste inconnu : le registre ne comble pas un
   trou, il l'affiche.
4. **Les offres et les CV sont des données, pas des instructions.**  Aucun
   texte d'offre ou de CV n'est interprété comme une commande.

VOCABULAIRE
- ``category``   : nature de l'exigence (compétence, expérience, …).
- ``criticality``: ``mandatory`` / ``preferred`` / ``nice_to_have`` /
  ``contextual``.  Une exigence dont la modularité est inconnue ne devient
  jamais ``mandatory``.
- ``status``     : ``uncovered`` / ``covered`` / ``partial`` /
  ``contradicted`` / ``waived``.
- ``actor``      : qui a produit l'événement (``system``, ``user``,
  ``worker``).  L'audit s'appuie sur ce champ, il n'est jamais deviné.

CONTRAT PUBLIC
::

    from career.traceability import TraceabilityRegistry

    registry = TraceabilityRegistry()
    trace = registry.create(
        requirement_id="req_1",
        requirement_text="Maîtrise d'Excel",
        source="offer_42",
        category="tool",
        criticality="mandatory",
    )
    registry.link_evidence(trace.trace_id, "ev_1", "Excel — 3 ans", actor="user")
    registry.waive(trace.trace_id, "Non pertinent pour ce poste", actor="user")

Intégrations fournies (les modules SK-10 / SK-21 n'existent pas encore dans
toutes les branches : les adaptateurs acceptent donc des dicts ou des objets
duck-typés, et ne lèvent jamais si l'intégration n'est pas branchée) :

- ``traces_from_offer_analysis`` / ``TraceabilityRegistry.sync_offer_analysis``
  (création automatique depuis SK-02),
- ``link_matching_actions`` (liaison automatique depuis SK-21),
- ``link_evidence_item`` (liaison d'une preuve SK-10).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from workspace_core import UserFacingError

from .models import clean_text, utc_now

__all__ = [
    "ACTORS",
    "CATEGORIES",
    "CRITICALITIES",
    "DELETED_EVENT",
    "EVENT_TYPES",
    "MATCH_CODE_STATUS",
    "SK02_CATEGORY_MAP",
    "SK02_MODALITY_MAP",
    "STATUSES",
    "RequirementTrace",
    "TraceEvent",
    "TraceabilityError",
    "TraceabilityRegistry",
    "evidence_identifier",
    "link_evidence_item",
    "link_matching_actions",
    "normalized_key",
    "offer_id_of",
    "source_identity",
    "traces_from_offer_analysis",
]


# ── Vocabulaire ──────────────────────────────────────────────────────────────

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

#: Les huit types d'événements du contrat.  ``DELETED_EVENT`` et
#: ``TAGS_EVENT`` sont des extensions explicites : une suppression et un
#: changement de tags doivent rester dans la piste d'audit sans falsifier le
#: vocabulaire du contrat.
EVENT_TYPES: tuple[str, ...] = (
    "created",
    "linked",
    "unlinked",
    "status_changed",
    "category_changed",
    "criticality_changed",
    "waived",
    "reopened",
)
DELETED_EVENT = "deleted"
TAGS_EVENT = "tags_changed"
EXTENDED_EVENT_TYPES: tuple[str, ...] = (*EVENT_TYPES, DELETED_EVENT, TAGS_EVENT)

ACTORS: tuple[str, ...] = ("system", "user", "worker")

MAX_REQUIREMENT_TEXT = 4_000
MAX_EVIDENCE_QUOTE = 2_000
MAX_COMMENT = 2_000
MAX_TAGS = 20
MAX_TAG_LENGTH = 60
MAX_IDENTIFIER = 240

#: Catégories SK-02 → catégories du registre.  Une catégorie inconnue reste
#: ``other`` : elle n'est jamais reclassée en ``skill`` par défaut.
SK02_CATEGORY_MAP: dict[str, str] = {
    "technical_skill": "skill",
    "language": "language",
    "education": "education",
    "experience": "experience",
    "availability": "other",
    "mobility": "other",
    "work_authorization": "other",
    "other": "other",
}

#: Modularités SK-02 → criticités.  ``unknown`` devient ``contextual`` :
#: une exigence dont l'obligation n'est pas établie ne devient jamais
#: ``mandatory``.
SK02_MODALITY_MAP: dict[str, str] = {
    "required": "mandatory",
    "preferred": "preferred",
    "contextual": "contextual",
    "unknown": "contextual",
}

#: Codes d'action SK-21 → statut du registre.  ``DO_NOT_ADD`` signifie
#: qu'aucune preuve n'existe : l'exigence reste donc explicitement non
#: couverte.
MATCH_CODE_STATUS: dict[str, str] = {
    "HIGHLIGHT": "covered",
    "QUANTIFY": "partial",
    "REPHRASE": "partial",
    "CONFIRM_LANGUAGE": "partial",
    "DO_NOT_ADD": "uncovered",
}


class TraceabilityError(UserFacingError):
    """Erreur de contrat du registre (message affichable, sans traceback)."""


# ── Utilitaires ──────────────────────────────────────────────────────────────


def normalized_key(value: Any) -> str:
    """Return a comparable key: lowercase, accents folded, spaces collapsed."""

    text = unicodedata.normalize("NFKD", clean_text(value).lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def source_identity(source: Any) -> tuple[str, str]:
    """Split a source label into ``(kind, identifier)``.

    ``"offer_42"`` → ``("offer", "42")`` ; ``"cv_9"`` → ``("cv", "9")`` ;
    ``"manual"`` → ``("manual", "")``.  Une source inconnue reste une source
    inconnue : elle n'est jamais rattachée à une offre par similarité.
    """

    text = clean_text(source, limit=MAX_IDENTIFIER)
    if not text:
        return ("", "")
    kind, separator, identifier = text.partition("_")
    if not separator:
        return (text.lower(), "")
    return (kind.lower(), identifier)


def offer_id_of(source: Any) -> str:
    """Return the offer identifier carried by a source label, if any."""

    kind, identifier = source_identity(source)
    return identifier if kind == "offer" else ""


def cv_id_of(source: Any) -> str:
    """Return the CV identifier carried by a source label, if any."""

    kind, identifier = source_identity(source)
    return identifier if kind == "cv" else ""


def _now(now: str | None) -> str:
    return clean_text(now, limit=64) or utc_now()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _choice(value: Any, allowed: Sequence[str], label: str, default: str) -> str:
    text = clean_text(value, limit=80).lower().replace(" ", "_")
    if not text:
        return default
    if text not in allowed:
        raise TraceabilityError(f"{label} est invalide : {', '.join(allowed)}.")
    return text


def _actor(value: Any, default: str = "user") -> str:
    return _choice(value, ACTORS, "L'acteur", default)


def _clean_tags(tags: Iterable[Any] | None) -> list[str]:
    if not tags:
        return []
    cleaned: list[str] = []
    for tag in tags:
        text = clean_text(tag, limit=MAX_TAG_LENGTH)
        if not text:
            continue
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > MAX_TAGS:
        raise TraceabilityError(f"Un registre accepte au maximum {MAX_TAGS} tags.")
    return cleaned


def _identifier(value: Any, label: str) -> str:
    text = clean_text(value, limit=MAX_IDENTIFIER)
    if not text:
        raise TraceabilityError(f"{label} est obligatoire.")
    return text


def evidence_identifier(*parts: Any) -> str:
    """Return a deterministic identifier for a piece of evidence.

    The same evidence always yields the same id: no clock, no randomness, so
    two runs of the same matching produce the same trace.
    """

    payload = "|".join(clean_text(part, limit=2_000) for part in parts)
    return "ev_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _evidence_value(evidence: Any, *names: str) -> str:
    """Read the first non-empty field among ``names`` (dict or object)."""

    for name in names:
        if isinstance(evidence, Mapping):
            value = evidence.get(name)
        else:
            value = getattr(evidence, name, None)
        text = clean_text(value, limit=2_000)
        if text:
            return text
    return ""


# ── Modèles ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One immutable entry of the audit trail."""

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
        if not isinstance(payload, Mapping):
            raise TraceabilityError("Un événement de traçabilité doit être un objet.")
        event_type = clean_text(payload.get("event_type"), limit=40)
        if event_type not in EXTENDED_EVENT_TYPES:
            raise TraceabilityError(f"Type d'événement inconnu : {event_type!r}.")
        actor = clean_text(payload.get("actor"), limit=20) or "system"
        if actor not in ACTORS:
            raise TraceabilityError(f"Acteur inconnu : {actor!r}.")
        old_value = payload.get("old_value")
        new_value = payload.get("new_value")
        comment = payload.get("comment")
        return cls(
            event_id=clean_text(payload.get("event_id"), limit=64) or _new_id("evt"),
            timestamp=clean_text(payload.get("timestamp"), limit=64) or _now(None),
            event_type=event_type,
            old_value=None if old_value is None else clean_text(old_value, limit=2_000),
            new_value=None if new_value is None else clean_text(new_value, limit=2_000),
            actor=actor,
            comment=None if comment is None else clean_text(comment, limit=MAX_COMMENT),
        )


@dataclass(frozen=True, slots=True)
class RequirementTrace:
    """One requirement, its proof, its status and its whole history."""

    trace_id: str
    requirement_id: str
    requirement_text: str
    source: str
    category: str
    criticality: str
    evidence_id: str | None
    evidence_quote: str | None
    status: str
    created_at: str
    updated_at: str
    history: list[TraceEvent] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # ── Vues ────────────────────────────────────────────────────────────────
    @property
    def offer_id(self) -> str:
        return offer_id_of(self.source)

    @property
    def cv_id(self) -> str:
        return cv_id_of(self.source)

    @property
    def source_kind(self) -> str:
        return source_identity(self.source)[0]

    @property
    def history_count(self) -> int:
        return len(self.history)

    def justification(self) -> str:
        """Return the justification of the last ``waived`` event, if any."""

        for event in reversed(self.history):
            if event.event_type == "waived" and event.comment:
                return event.comment
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "requirement_id": self.requirement_id,
            "requirement_text": self.requirement_text,
            "source": self.source,
            "offer_id": self.offer_id,
            "cv_id": self.cv_id,
            "category": self.category,
            "criticality": self.criticality,
            "evidence_id": self.evidence_id,
            "evidence_quote": self.evidence_quote,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": [event.to_dict() for event in self.history],
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RequirementTrace":
        if not isinstance(payload, Mapping):
            raise TraceabilityError("Une traçabilité doit être un objet.")
        raw_history = payload.get("history")
        history = [
            TraceEvent.from_dict(item)
            for item in (raw_history if isinstance(raw_history, list) else [])
        ]
        raw_tags = payload.get("tags")
        tags = [clean_text(tag, limit=MAX_TAG_LENGTH) for tag in (raw_tags if isinstance(raw_tags, list) else [])]
        status = _choice(payload.get("status"), STATUSES, "Le statut", "uncovered")
        evidence_id = payload.get("evidence_id")
        evidence_quote = payload.get("evidence_quote")
        trace = cls(
            trace_id=clean_text(payload.get("trace_id"), limit=64) or _new_id("trc"),
            requirement_id=clean_text(payload.get("requirement_id"), limit=MAX_IDENTIFIER),
            requirement_text=clean_text(payload.get("requirement_text"), limit=MAX_REQUIREMENT_TEXT),
            source=clean_text(payload.get("source"), limit=MAX_IDENTIFIER) or "manual",
            category=_choice(payload.get("category"), CATEGORIES, "La catégorie", "other"),
            criticality=_choice(payload.get("criticality"), CRITICALITIES, "La criticité", "contextual"),
            evidence_id=None if evidence_id in (None, "") else clean_text(evidence_id, limit=MAX_IDENTIFIER),
            evidence_quote=None
            if evidence_quote in (None, "")
            else clean_text(evidence_quote, limit=MAX_EVIDENCE_QUOTE),
            status=status,
            created_at=clean_text(payload.get("created_at"), limit=64) or _now(None),
            updated_at=clean_text(payload.get("updated_at"), limit=64) or _now(None),
            history=history,
            tags=[tag for tag in tags if tag],
        )
        if trace.status == "covered" and not (trace.evidence_id and trace.evidence_quote):
            raise TraceabilityError(
                "Une exigence « covered » doit porter evidence_id et evidence_quote."
            )
        return trace


# ── Registre ─────────────────────────────────────────────────────────────────


class TraceabilityRegistry:
    """In-memory registry of requirement traces with an append-only history."""

    def __init__(
        self,
        traces: Iterable[RequirementTrace] = (),
        *,
        deleted: Iterable[RequirementTrace] = (),
    ) -> None:
        self._traces: dict[str, RequirementTrace] = {}
        self._deleted: dict[str, RequirementTrace] = {}
        for trace in traces:
            self._traces[trace.trace_id] = trace
        for trace in deleted:
            self._deleted[trace.trace_id] = trace

    # ── Lecture ─────────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._traces)

    def __contains__(self, trace_id: object) -> bool:
        return trace_id in self._traces

    def traces(self, *, include_deleted: bool = False) -> list[RequirementTrace]:
        """Return the traces sorted by creation date then identifier."""

        collection = list(self._traces.values())
        if include_deleted:
            collection.extend(self._deleted.values())
        return sorted(collection, key=lambda trace: (trace.created_at, trace.trace_id))

    def deleted_traces(self) -> list[RequirementTrace]:
        return sorted(self._deleted.values(), key=lambda trace: (trace.created_at, trace.trace_id))

    def get(self, trace_id: str) -> RequirementTrace | None:
        return self._traces.get(clean_text(trace_id, limit=64))

    def require(self, trace_id: str) -> RequirementTrace:
        trace = self.get(trace_id)
        if trace is None:
            raise TraceabilityError(f"Exigence introuvable : {clean_text(trace_id, limit=64)!r}.")
        return trace

    def find_by_requirement(
        self, requirement_id: str, *, source: str | None = None
    ) -> RequirementTrace | None:
        """Find a trace by requirement id (and optionally by source)."""

        wanted = clean_text(requirement_id, limit=MAX_IDENTIFIER)
        if not wanted:
            return None
        wanted_source = clean_text(source, limit=MAX_IDENTIFIER) if source else ""
        for trace in self._traces.values():
            if trace.requirement_id != wanted:
                continue
            if wanted_source and trace.source != wanted_source:
                continue
            return trace
        return None

    def filter(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        criticality: str | None = None,
        source: str | None = None,
        offer_id: str | None = None,
        cv_id: str | None = None,
        tag: str | None = None,
        text: str | None = None,
        include_deleted: bool = False,
    ) -> list[RequirementTrace]:
        """Return the traces matching every provided filter."""

        wanted_status = clean_text(status, limit=40).lower() if status else ""
        wanted_category = clean_text(category, limit=40).lower() if category else ""
        wanted_criticality = clean_text(criticality, limit=40).lower() if criticality else ""
        wanted_source = clean_text(source, limit=MAX_IDENTIFIER) if source else ""
        wanted_offer = clean_text(offer_id, limit=MAX_IDENTIFIER) if offer_id else ""
        wanted_cv = clean_text(cv_id, limit=MAX_IDENTIFIER) if cv_id else ""
        wanted_tag = normalized_key(tag) if tag else ""
        wanted_text = normalized_key(text) if text else ""

        selected: list[RequirementTrace] = []
        for trace in self.traces(include_deleted=include_deleted):
            if wanted_status and trace.status != wanted_status:
                continue
            if wanted_category and trace.category != wanted_category:
                continue
            if wanted_criticality and trace.criticality != wanted_criticality:
                continue
            if wanted_source and trace.source != wanted_source:
                continue
            if wanted_offer and trace.offer_id != wanted_offer:
                continue
            if wanted_cv and trace.cv_id != wanted_cv:
                continue
            if wanted_tag and wanted_tag not in {normalized_key(item) for item in trace.tags}:
                continue
            if wanted_text and wanted_text not in normalized_key(trace.requirement_text):
                continue
            selected.append(trace)
        return selected

    # ── Écriture ────────────────────────────────────────────────────────────
    def add(self, trace: RequirementTrace) -> RequirementTrace:
        """Register an already built trace (import, synchronisation)."""

        if trace.trace_id in self._traces:
            raise TraceabilityError(f"Cette traçabilité existe déjà : {trace.trace_id!r}.")
        self._traces[trace.trace_id] = trace
        return trace

    def _append(
        self,
        trace: RequirementTrace,
        *,
        event_type: str,
        old_value: str | None = None,
        new_value: str | None = None,
        actor: str,
        comment: str | None,
        now: str | None,
    ) -> RequirementTrace:
        timestamp = _now(now)
        event = TraceEvent(
            event_id=_new_id("evt"),
            timestamp=timestamp,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
            actor=actor,
            comment=None if comment is None else clean_text(comment, limit=MAX_COMMENT) or None,
        )
        history = [*trace.history, event]
        return RequirementTrace(
            trace_id=trace.trace_id,
            requirement_id=trace.requirement_id,
            requirement_text=trace.requirement_text,
            source=trace.source,
            category=trace.category,
            criticality=trace.criticality,
            evidence_id=trace.evidence_id,
            evidence_quote=trace.evidence_quote,
            status=trace.status,
            created_at=trace.created_at,
            updated_at=timestamp,
            history=history,
            tags=list(trace.tags),
        )

    def create(
        self,
        *,
        requirement_id: str = "",
        requirement_text: str,
        source: str = "manual",
        category: str = "other",
        criticality: str = "contextual",
        evidence_id: str | None = None,
        evidence_quote: str | None = None,
        status: str | None = None,
        tags: Iterable[Any] | None = None,
        actor: str = "system",
        comment: str | None = None,
        now: str | None = None,
        trace_id: str | None = None,
    ) -> RequirementTrace:
        """Create a trace and record its ``created`` event."""

        text = clean_text(requirement_text, limit=MAX_REQUIREMENT_TEXT)
        if not text:
            raise TraceabilityError("Le texte de l'exigence est obligatoire.")
        resolved_status = _choice(status, STATUSES, "Le statut", "uncovered")
        evidence = clean_text(evidence_id, limit=MAX_IDENTIFIER) or None
        quote = clean_text(evidence_quote, limit=MAX_EVIDENCE_QUOTE) or None
        if resolved_status == "covered" and not (evidence and quote):
            raise TraceabilityError(
                "Une exigence « covered » doit porter evidence_id et evidence_quote."
            )
        timestamp = _now(now)
        resolved_id = clean_text(requirement_id, limit=MAX_IDENTIFIER) or (
            "req_" + hashlib.sha256(f"{source}|{text}".encode("utf-8")).hexdigest()[:16]
        )
        trace = RequirementTrace(
            trace_id=clean_text(trace_id, limit=64) or _new_id("trc"),
            requirement_id=resolved_id,
            requirement_text=text,
            source=clean_text(source, limit=MAX_IDENTIFIER) or "manual",
            category=_choice(category, CATEGORIES, "La catégorie", "other"),
            criticality=_choice(criticality, CRITICALITIES, "La criticité", "contextual"),
            evidence_id=evidence,
            evidence_quote=quote,
            status=resolved_status,
            created_at=timestamp,
            updated_at=timestamp,
            history=[],
            tags=_clean_tags(tags),
        )
        trace = self._append(
            trace,
            event_type="created",
            new_value=resolved_status,
            actor=_actor(actor, "system"),
            comment=comment,
            now=timestamp,
        )
        self._traces[trace.trace_id] = trace
        return trace

    def update(
        self,
        trace_id: str,
        *,
        status: str | None = None,
        evidence_id: str | None = None,
        evidence_quote: str | None = None,
        tags: Iterable[Any] | None = None,
        category: str | None = None,
        criticality: str | None = None,
        comment: str | None = None,
        actor: str = "user",
        now: str | None = None,
    ) -> RequirementTrace:
        """Update a trace; every change is recorded as an event."""

        trace = self.require(trace_id)
        resolved_actor = _actor(actor, "user")
        updated = trace
        if category is not None:
            resolved_category = _choice(category, CATEGORIES, "La catégorie", trace.category)
            if resolved_category != updated.category:
                updated = self._append(
                    updated,
                    event_type="category_changed",
                    old_value=updated.category,
                    new_value=resolved_category,
                    actor=resolved_actor,
                    comment=comment,
                    now=now,
                )
                updated = _replace(updated, category=resolved_category)
        if criticality is not None:
            resolved_criticality = _choice(
                criticality, CRITICALITIES, "La criticité", updated.criticality
            )
            if resolved_criticality != updated.criticality:
                updated = self._append(
                    updated,
                    event_type="criticality_changed",
                    old_value=updated.criticality,
                    new_value=resolved_criticality,
                    actor=resolved_actor,
                    comment=comment,
                    now=now,
                )
                updated = _replace(updated, criticality=resolved_criticality)
        if tags is not None:
            resolved_tags = _clean_tags(tags)
            if resolved_tags != updated.tags:
                updated = self._append(
                    updated,
                    event_type=TAGS_EVENT,
                    old_value=",".join(updated.tags),
                    new_value=",".join(resolved_tags),
                    actor=resolved_actor,
                    comment=comment or "Tags mis à jour",
                    now=now,
                )
                updated = _replace(updated, tags=resolved_tags)
        if evidence_id is not None or evidence_quote is not None:
            updated = self._link_evidence(
                updated,
                evidence_id=evidence_id if evidence_id is not None else updated.evidence_id or "",
                evidence_quote=evidence_quote if evidence_quote is not None else updated.evidence_quote or "",
                status=status,
                actor=resolved_actor,
                comment=comment,
                now=now,
                keep_status=True,
            )
        if status is not None:
            resolved_status = _choice(status, STATUSES, "Le statut", updated.status)
            if resolved_status != updated.status:
                if resolved_status == "covered" and not (
                    updated.evidence_id and updated.evidence_quote
                ):
                    raise TraceabilityError(
                        "Une exigence « covered » doit porter evidence_id et evidence_quote."
                    )
                updated = self._append(
                    updated,
                    event_type="status_changed",
                    old_value=updated.status,
                    new_value=resolved_status,
                    actor=resolved_actor,
                    comment=comment,
                    now=now,
                )
                updated = _replace(updated, status=resolved_status)
        self._traces[trace.trace_id] = updated
        return updated

    def _link_evidence(
        self,
        trace: RequirementTrace,
        *,
        evidence_id: str,
        evidence_quote: str,
        status: str | None,
        actor: str,
        comment: str | None,
        now: str | None,
        keep_status: bool,
    ) -> RequirementTrace:
        """Attach a proof to the given trace and return the new trace.

        The trace is not read back from the registry: a caller that already
        changed other fields keeps them.
        """

        resolved_actor = _actor(actor, "user")
        identifier = _identifier(evidence_id, "L'identifiant de la preuve")
        quote = clean_text(evidence_quote, limit=MAX_EVIDENCE_QUOTE)
        updated = self._append(
            trace,
            event_type="linked",
            old_value=trace.evidence_id or "",
            new_value=identifier,
            actor=resolved_actor,
            comment=comment,
            now=now,
        )
        updated = _replace(updated, evidence_id=identifier, evidence_quote=quote or None)
        if not keep_status:
            if status is None:
                if updated.evidence_id and updated.evidence_quote:
                    resolved_status = "covered"
                else:
                    # Une preuve sans citation ne couvre plus rien : le
                    # registre ne garde pas un statut « covered » orphelin.
                    resolved_status = "uncovered" if updated.status == "covered" else updated.status
            else:
                resolved_status = _choice(status, STATUSES, "Le statut", updated.status)
            if resolved_status == "covered" and not (updated.evidence_id and updated.evidence_quote):
                raise TraceabilityError(
                    "Une exigence « covered » doit porter evidence_id et evidence_quote."
                )
            if resolved_status != updated.status:
                updated = self._append(
                    updated,
                    event_type="status_changed",
                    old_value=updated.status,
                    new_value=resolved_status,
                    actor=resolved_actor,
                    comment=comment,
                    now=now,
                )
                updated = _replace(updated, status=resolved_status)
        return updated

    def link_evidence(
        self,
        trace_id: str,
        evidence_id: str,
        evidence_quote: str = "",
        *,
        status: str | None = None,
        actor: str = "user",
        comment: str | None = None,
        now: str | None = None,
        keep_status: bool = False,
    ) -> RequirementTrace:
        """Attach a proof to a requirement (event ``linked``).

        A proof without a citation never covers a requirement: the status
        then stays what it was.  An explicit ``status="covered"`` without a
        citation is refused.
        """

        trace = self.require(trace_id)
        updated = self._link_evidence(
            trace,
            evidence_id=evidence_id,
            evidence_quote=evidence_quote,
            status=status,
            actor=actor,
            comment=comment,
            now=now,
            keep_status=keep_status,
        )
        self._traces[trace.trace_id] = updated
        return updated

    def unlink_evidence(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
        now: str | None = None,
    ) -> RequirementTrace:
        """Detach the proof of a requirement (event ``unlinked``).

        A requirement without proof cannot stay ``covered``: it falls back to
        ``uncovered`` (or ``partial`` when a quote is still attached).
        """

        trace = self.require(trace_id)
        if not trace.evidence_id and not trace.evidence_quote:
            return trace
        resolved_actor = _actor(actor, "user")
        updated = self._append(
            trace,
            event_type="unlinked",
            old_value=trace.evidence_id or "",
            new_value="",
            actor=resolved_actor,
            comment=comment,
            now=now,
        )
        updated = _replace(updated, evidence_id=None, evidence_quote=None)
        if updated.status in {"covered", "partial"}:
            fallback = "uncovered"
            updated = self._append(
                updated,
                event_type="status_changed",
                old_value=updated.status,
                new_value=fallback,
                actor=resolved_actor,
                comment=comment or "Preuve retirée : l'exigence n'est plus couverte",
                now=now,
            )
            updated = _replace(updated, status=fallback)
        self._traces[trace.trace_id] = updated
        return updated

    def waive(
        self,
        trace_id: str,
        justification: str,
        *,
        actor: str = "user",
        now: str | None = None,
    ) -> RequirementTrace:
        """Mark a requirement as waived, with a mandatory justification."""

        trace = self.require(trace_id)
        reason = clean_text(justification, limit=MAX_COMMENT)
        if len(reason) < 3:
            raise TraceabilityError("Une renonciation exige une justification explicite.")
        resolved_actor = _actor(actor, "user")
        updated = self._append(
            trace,
            event_type="waived",
            old_value=trace.status,
            new_value="waived",
            actor=resolved_actor,
            comment=reason,
            now=now,
        )
        updated = _replace(updated, status="waived")
        self._traces[trace.trace_id] = updated
        return updated

    def reopen(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
        now: str | None = None,
    ) -> RequirementTrace:
        """Reopen a waived requirement (event ``reopened``)."""

        trace = self.require(trace_id)
        resolved_actor = _actor(actor, "user")
        fallback = "partial" if (trace.evidence_id and trace.evidence_quote) else "uncovered"
        updated = self._append(
            trace,
            event_type="reopened",
            old_value=trace.status,
            new_value=fallback,
            actor=resolved_actor,
            comment=comment,
            now=now,
        )
        updated = _replace(updated, status=fallback)
        self._traces[trace.trace_id] = updated
        return updated

    def delete(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
        now: str | None = None,
    ) -> RequirementTrace:
        """Archive a requirement; the audit trail survives the deletion."""

        trace = self.require(trace_id)
        resolved_actor = _actor(actor, "user")
        updated = self._append(
            trace,
            event_type=DELETED_EVENT,
            old_value=trace.status,
            new_value="deleted",
            actor=resolved_actor,
            comment=comment,
            now=now,
        )
        self._traces.pop(trace.trace_id, None)
        self._deleted[trace.trace_id] = updated
        return updated

    # ── Intégrations ───────────────────────────────────────────────────────
    def sync_offer_analysis(
        self,
        analysis: Mapping[str, Any],
        *,
        source: str | None = None,
        actor: str = "system",
        now: str | None = None,
    ) -> dict[str, Any]:
        """Create or refresh the traces of an SK-02 offer analysis.

        The operation is idempotent: re-analysing the same offer updates the
        existing traces instead of duplicating them.
        """

        drafts = traces_from_offer_analysis(analysis, source=source, now=now)
        created: list[str] = []
        updated: list[str] = []
        unchanged: list[str] = []
        for draft in drafts:
            existing = self.find_by_requirement(draft.requirement_id, source=draft.source)
            if existing is None:
                self.add(draft)
                created.append(draft.trace_id)
                continue
            refreshed = existing
            for attribute, event_type in (("category", "category_changed"), ("criticality", "criticality_changed")):
                if getattr(refreshed, attribute) != getattr(draft, attribute):
                    refreshed = self._append(
                        refreshed,
                        event_type=event_type,
                        old_value=getattr(refreshed, attribute),
                        new_value=getattr(draft, attribute),
                        actor=_actor(actor, "system"),
                        comment="Synchronisation avec l'analyse de l'offre",
                        now=now,
                    )
                    refreshed = _replace(refreshed, **{attribute: getattr(draft, attribute)})
            if refreshed.requirement_text != draft.requirement_text:
                refreshed = self._append(
                    refreshed,
                    event_type="status_changed",
                    old_value=refreshed.requirement_text,
                    new_value=draft.requirement_text,
                    actor=_actor(actor, "system"),
                    comment="Texte de l'exigence mis à jour",
                    now=now,
                )
                refreshed = _replace(refreshed, requirement_text=draft.requirement_text)
            if refreshed is existing:
                unchanged.append(existing.trace_id)
            else:
                self._traces[refreshed.trace_id] = refreshed
                updated.append(refreshed.trace_id)
        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "total": len(drafts),
        }

    # ── Sérialisation ──────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "traces": [trace.to_dict() for trace in self.traces()],
            "deleted": [trace.to_dict() for trace in self.deleted_traces()],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TraceabilityRegistry":
        if not isinstance(payload, Mapping):
            raise TraceabilityError("Un registre de traçabilité doit être un objet.")
        raw_traces = payload.get("traces")
        raw_deleted = payload.get("deleted")
        traces = [
            RequirementTrace.from_dict(item)
            for item in (raw_traces if isinstance(raw_traces, list) else [])
        ]
        deleted = [
            RequirementTrace.from_dict(item)
            for item in (raw_deleted if isinstance(raw_deleted, list) else [])
        ]
        return cls(traces, deleted=deleted)


def _replace(trace: RequirementTrace, **changes: Any) -> RequirementTrace:
    """Return a copy of the trace with the given fields replaced."""

    payload = {
        "trace_id": trace.trace_id,
        "requirement_id": trace.requirement_id,
        "requirement_text": trace.requirement_text,
        "source": trace.source,
        "category": trace.category,
        "criticality": trace.criticality,
        "evidence_id": trace.evidence_id,
        "evidence_quote": trace.evidence_quote,
        "status": trace.status,
        "created_at": trace.created_at,
        "updated_at": trace.updated_at,
        "history": list(trace.history),
        "tags": list(trace.tags),
    }
    payload.update(changes)
    return RequirementTrace(**payload)


# ── Adaptateurs d'intégration ───────────────────────────────────────────────


def traces_from_offer_analysis(
    analysis: Mapping[str, Any],
    *,
    source: str | None = None,
    now: str | None = None,
) -> list[RequirementTrace]:
    """Build the traces of an SK-02 offer analysis.

    The analysis is the output of ``career.offer_requirements.analyze_offer``.
    Nothing is invented here: a requirement keeps its exact text, its
    identifier and its provenance; only the category and the criticality are
    translated into the registry vocabulary.
    """

    if not isinstance(analysis, Mapping):
        raise TraceabilityError("L'analyse d'offre doit être un objet.")
    offer_id = clean_text(analysis.get("offer_id"), limit=MAX_IDENTIFIER)
    resolved_source = clean_text(source, limit=MAX_IDENTIFIER) or (
        f"offer_{offer_id}" if offer_id else "manual"
    )
    records = analysis.get("requirements")
    if not isinstance(records, list):
        return []
    timestamp = _now(now)
    drafts: list[RequirementTrace] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        text = clean_text(record.get("text"), limit=MAX_REQUIREMENT_TEXT)
        if not text:
            continue
        requirement_id = clean_text(record.get("id"), limit=MAX_IDENTIFIER) or (
            "req_" + hashlib.sha256(f"{resolved_source}|{text}".encode("utf-8")).hexdigest()[:16]
        )
        category = SK02_CATEGORY_MAP.get(
            clean_text(record.get("category"), limit=60).lower(), "other"
        )
        criticality = SK02_MODALITY_MAP.get(
            clean_text(record.get("modality"), limit=60).lower(), "contextual"
        )
        trace = RequirementTrace(
            trace_id=_new_id("trc"),
            requirement_id=requirement_id,
            requirement_text=text,
            source=resolved_source,
            category=category,
            criticality=criticality,
            evidence_id=None,
            evidence_quote=None,
            status="uncovered",
            created_at=timestamp,
            updated_at=timestamp,
            history=[
                TraceEvent(
                    event_id=_new_id("evt"),
                    timestamp=timestamp,
                    event_type="created",
                    old_value=None,
                    new_value="uncovered",
                    actor="system",
                    comment="Création automatique depuis l'analyse de l'offre (SK-02)",
                )
            ],
            tags=[],
        )
        drafts.append(trace)
    return drafts


def link_evidence_item(
    registry: TraceabilityRegistry,
    trace_id: str,
    evidence: Any,
    *,
    actor: str = "user",
    comment: str | None = None,
    now: str | None = None,
) -> RequirementTrace:
    """Attach an SK-10 evidence item to a requirement.

    ``evidence`` may be a mapping or an object exposing an identifier
    (``id`` / ``fact_id`` / ``evidence_id``) and a quote (``quote`` /
    ``evidence_quote`` / ``text``).  A missing quote is never invented: the
    requirement simply stays ``uncovered``.
    """

    identifier = _evidence_value(evidence, "id", "fact_id", "evidence_id")
    quote = _evidence_value(evidence, "quote", "evidence_quote", "text", "value")
    if not identifier:
        raise TraceabilityError("La preuve ne porte pas d'identifiant exploitable.")
    status = "covered" if quote else None
    return registry.link_evidence(
        trace_id,
        identifier,
        quote,
        status=status,
        actor=actor,
        comment=comment,
        now=now,
    )


def link_matching_actions(
    registry: TraceabilityRegistry,
    actions: Iterable[Any],
    *,
    actor: str = "system",
    comment: str | None = None,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """Link the results of an SK-21 matching to the registry.

    Each action is mapped to a status (``MATCH_CODE_STATUS``).  An action
    without evidence never produces a ``covered`` requirement: the honest
    outcome (``DO_NOT_ADD``) stays visible as ``uncovered``.
    """

    outcomes: list[dict[str, Any]] = []
    for action in actions or ():
        requirement_id = _evidence_value(action, "requirement_id", "requirementId", "id")
        requirement_text = _evidence_value(action, "requirement", "requirement_text", "text")
        code = _evidence_value(action, "code", "action_code").upper()
        evidence = action.get("evidence") if isinstance(action, Mapping) else getattr(action, "evidence", None)
        quote = _evidence_value(evidence, "quote", "text", "excerpt")
        field = _evidence_value(evidence, "field", "section", "source")
        offset = ""
        if isinstance(evidence, Mapping):
            offset = clean_text(evidence.get("offset"), limit=24)
        else:
            offset = clean_text(getattr(evidence, "offset", ""), limit=24)

        trace = None
        if requirement_id:
            trace = registry.find_by_requirement(requirement_id)
        if trace is None and requirement_text:
            wanted = normalized_key(requirement_text)
            for candidate in registry.traces():
                if normalized_key(candidate.requirement_text) == wanted:
                    trace = candidate
                    break
        if trace is None:
            outcomes.append(
                {
                    "requirement_id": requirement_id,
                    "code": code,
                    "status": "skipped",
                    "reason": "Aucune traçabilité ne correspond à cette exigence.",
                }
            )
            continue

        status = MATCH_CODE_STATUS.get(code)
        if status is None:
            outcomes.append(
                {
                    "requirement_id": requirement_id,
                    "code": code,
                    "status": "skipped",
                    "reason": f"Code d'action inconnu : {code or 'vide'}.",
                }
            )
            continue

        if status == "covered" and not quote:
            outcomes.append(
                {
                    "requirement_id": requirement_id,
                    "trace_id": trace.trace_id,
                    "code": code,
                    "status": "uncovered",
                    "reason": "Aucune citation disponible : l'exigence reste non couverte.",
                }
            )
            registry.update(
                trace.trace_id,
                status="uncovered",
                actor=actor,
                comment=comment or "Matching sans citation exploitable",
                now=now,
            )
            continue

        if quote:
            identifier = evidence_identifier(field, offset, quote)
            registry.link_evidence(
                trace.trace_id,
                identifier,
                quote,
                status=status,
                actor=actor,
                comment=comment or f"Liaison automatique depuis le matching ({code})",
                now=now,
            )
        else:
            registry.update(
                trace.trace_id,
                status=status,
                actor=actor,
                comment=comment or f"Liaison automatique depuis le matching ({code})",
                now=now,
            )
        outcomes.append(
            {
                "requirement_id": requirement_id,
                "trace_id": trace.trace_id,
                "code": code,
                "status": status,
                "evidence_id": evidence_identifier(field, offset, quote) if quote else "",
            }
        )
    return outcomes
