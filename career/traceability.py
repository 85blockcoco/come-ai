"""Registre de traçabilité des exigences — SPEC-011 (CVBOOST-46).

Ce module est le **cœur métier** du registre.  Il ne fait ni réseau, ni
disque, ni appel de modèle : il ne décrit que des faits vérifiables et les
règles qui les rendent cohérents.

Il existe trois objets :

* :class:`RequirementTrace` — une exigence *traçable* : le texte exact d'une
  exigence, sa provenance, sa criticité, son statut, et la preuve qui la
  couvre (ou l'absence de preuve).
* :class:`TraceEvent` — un événement d'historique, **append-only**.
* :class:`TraceabilityRegistry` — le registre et les règles métier.

LES SIX RÈGLES GARANTIES PAR LE REGISTRE
----------------------------------------
1. **Aucune invention.**  Une exigence ``covered`` (ou ``partial``, ou
   ``contradicted``) porte toujours un ``evidence_id`` *et* une
   ``evidence_quote`` non vide.  Aucun statut ne peut être affirmé sans
   preuve citée ; symétriquement, une exigence ``uncovered`` ne porte aucune
   preuve.  Le registre ne fabrique jamais une citation.
2. **Historique immuable.**  Le texte d'une exigence ne change jamais.  Chaque
   mutation ajoute un :class:`TraceEvent` ; les événements existants ne sont
   jamais réécrits ni supprimés — même quand l'exigence est supprimée, son
   historique reste consultable.
3. **Traçabilité des actions.**  Chaque événement porte un ``actor``
   (``system`` / ``user`` / ``worker``), un horodatage ISO 8601, une
   ``origin`` (``auto`` / ``manual``) et, quand elle est utile, une
   justification en clair.
4. **Dérogation justifiée.**  Passer une exigence en ``waived`` exige une
   justification non vide ; une dérogation ne peut pas être posée par un
   simple changement de statut.
5. **Liaison automatique non validée.**  Une liaison ``auto`` (faite par le
   matching SK-21) démarre en ``confirmed=False`` : elle doit être confirmée
   ou rejetée par une personne avant de faire foi.
6. **Déterminisme.**  L'horloge et les identifiants sont injectables : à
   horloge fixée, la même séquence d'opérations produit exactement le même
   registre, bit pour bit.

INTÉGRATION AVEC LES AUTRES SPECS
---------------------------------
* **SK-02 (extraction d'offre)** — :func:`traces_from_offer_analysis` crée
  les traces à partir du contrat d'exigences (texte verbatim, locator,
  catégorie, modalité).  Rejouer l'extraction ne crée pas de doublon.
* **SK-10 (preuves du profil)** — la liaison d'une preuve passe par
  :meth:`TraceabilityRegistry.link_evidence` ; le registre ne connaît pas le
  magasin de preuves, il exige seulement un identifiant **et** une citation.
* **SK-21 (matching)** — :func:`auto_link_from_matching` consomme le résultat
  du matching et crée des liaisons ``auto`` (non validées) qui attendent une
  confirmation humaine.

IDENTIFIANTS
-------------
``trace_id`` n'est pas un UUID aléatoire : c'est ``trc_`` + les 16 premiers
caractères hexadécimaux de ``sha256(source | requirement_id | texte)``.  Il est
donc **unique et stable** : rejouer la même extraction retrouve la même trace
au lieu d'en dupliquer une.  C'est ce qui rend la création automatique
idempotente.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from workspace_core import UserFacingError

from .models import utc_now


# ---------------------------------------------------------------------------
# Vocabulaire du contrat
# ---------------------------------------------------------------------------

CATEGORIES: frozenset[str] = frozenset(
    {
        "skill",
        "experience",
        "education",
        "language",
        "tool",
        "certification",
        "soft_skill",
        "other",
    }
)

CRITICALITIES: frozenset[str] = frozenset(
    {"mandatory", "preferred", "nice_to_have", "contextual"}
)

STATUSES: frozenset[str] = frozenset(
    {"uncovered", "covered", "partial", "contradicted", "waived"}
)

#: Statuts qui affirment une couverture : ils exigent une preuve citée.
LINKED_STATUSES: frozenset[str] = frozenset({"covered", "partial", "contradicted"})

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "created",
        "linked",
        "unlinked",
        "status_changed",
        "category_changed",
        "criticality_changed",
        "waived",
        "reopened",
        # Extensions (le contrat impose les huit premiers ; les suivants
        # rendent les opérations réellement tracables).
        "tags_updated",
        "link_confirmed",
        "link_rejected",
        "deleted",
    }
)

ACTORS: frozenset[str] = frozenset({"system", "user", "worker"})

LINK_ORIGINS: frozenset[str] = frozenset({"auto", "manual"})

MAX_REQUIREMENT_TEXT = 4_000
MAX_COMMENT = 2_000
MAX_TAGS = 24
MAX_TAG_LENGTH = 60


class TraceabilityError(UserFacingError):
    """Erreur métier du registre, affichable telle quelle à la personne."""


# ---------------------------------------------------------------------------
# Objets du contrat
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceEvent:
    """Un événement d'historique, immuable une fois écrit."""

    event_id: str
    timestamp: str
    event_type: str
    old_value: str | None = None
    new_value: str | None = None
    actor: str = "system"
    comment: str | None = None
    origin: str = "manual"
    trace_id: str = ""


@dataclass(frozen=True)
class RequirementTrace:
    """Une exigence reliée à sa preuve, son statut et son historique."""

    trace_id: str
    requirement_id: str
    requirement_text: str
    source: str
    category: str
    criticality: str
    evidence_id: str | None = None
    evidence_quote: str | None = None
    status: str = "uncovered"
    created_at: str = ""
    updated_at: str = ""
    history: tuple[TraceEvent, ...] = ()
    tags: tuple[str, ...] = ()
    # --- Extensions documentées -------------------------------------------
    offer_id: str = ""
    cv_id: str = ""
    locator: str = ""
    source_field: str = ""
    evidence_field: str = ""
    evidence_offset: int | None = None
    link_origin: str = "manual"
    confirmed: bool = True
    waiver_reason: str = ""


# ---------------------------------------------------------------------------
# Identifiants, normalisation
# ---------------------------------------------------------------------------


def _digest(*parts: str) -> str:
    payload = "\x1f".join(part or "" for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def trace_identifier(source: str, requirement_id: str, requirement_text: str) -> str:
    """Identifiant stable et unique d'une exigence tracée."""
    return "trc_" + _digest(source, requirement_id, requirement_text)[:16]


def event_identifier(
    trace_id: str,
    timestamp: str,
    event_type: str,
    sequence: int,
    *,
    old_value: str | None = None,
    new_value: str | None = None,
    comment: str | None = None,
) -> str:
    """Identifiant stable d'un événement (jamais réutilisé).

    Le contenu de l'événement entre dans l'empreinte : deux événements
    distincts ne peuvent pas partager le même identifiant, même s'ils
    tombent à la même milliseconde.
    """
    return "evt_" + _digest(
        trace_id,
        timestamp,
        event_type,
        str(sequence),
        old_value or "",
        new_value or "",
        comment or "",
    )[:16]


def _clean(value: Any, *, limit: int = MAX_REQUIREMENT_TEXT) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


def normalize_tag(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _clean(value, limit=MAX_TAG_LENGTH)).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:MAX_TAG_LENGTH]


def normalize_tags(values: Iterable[Any] | None) -> tuple[str, ...]:
    """Normalise, déduplique et trie les tags métier (ordre stable)."""
    if not values:
        return ()
    seen: dict[str, None] = {}
    for value in values:
        tag = normalize_tag(value)
        if tag:
            seen.setdefault(tag, None)
    return tuple(sorted(seen)[:MAX_TAGS])


# ---------------------------------------------------------------------------
# Correspondance SK-02 → vocabulaire de traçabilité
# ---------------------------------------------------------------------------

#: Catégories du contrat d'exigences (SK-02) → catégories de traçabilité.
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

#: Modalités du contrat d'exigences (SK-02) → criticités de traçabilité.
SK02_MODALITY_MAP: dict[str, str] = {
    "required": "mandatory",
    "preferred": "preferred",
    "contextual": "contextual",
    "unknown": "contextual",
}

#: Une préférence explicite « nice to have » est plus faible qu'une simple
#: préférence : les deux restent non obligatoires, mais elles ne se
#: confondent pas dans les rapports d'audit.
_NICE_TO_HAVE_MARKERS = (
    "nice to have",
    "nice-to-have",
    "nice to-have",
    "souhaitable",
    "souhaitée",
    "un plus",
    "de preference",
    "de préférence",
    "plutôt",
    "plutot",
    "atout",
    "bonus",
    "appreciable",
    "good to have",
)


def category_from_sk02(category: Any) -> str:
    """Traduit une catégorie SK-02 en catégorie de traçabilité."""
    key = _clean(category, limit=80).lower()
    return SK02_CATEGORY_MAP.get(key, "other")


def criticality_from_sk02(modality: Any, text: Any = "") -> str:
    """Traduit une modalité SK-02 en criticité de traçabilité.

    Une modalité ``unknown`` devient ``contextual`` : le registre ne prétend
    jamais qu'une exigence est obligatoire quand l'extraction ne le sait pas.
    """
    key = _clean(modality, limit=40).lower()
    criticality = SK02_MODALITY_MAP.get(key, "contextual")
    if criticality == "preferred":
        lowered = _clean(text, limit=2_000).lower()
        if any(marker in lowered for marker in _NICE_TO_HAVE_MARKERS):
            return "nice_to_have"
    return criticality


# ---------------------------------------------------------------------------
# Sérialisation
# ---------------------------------------------------------------------------


def event_to_dict(event: TraceEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "timestamp": event.timestamp,
        "event_type": event.event_type,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "actor": event.actor,
        "comment": event.comment,
        "origin": event.origin,
    }


def trace_to_dict(trace: RequirementTrace, *, include_history: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
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
        "tags": list(trace.tags),
        "offer_id": trace.offer_id,
        "cv_id": trace.cv_id,
        "locator": trace.locator,
        "source_field": trace.source_field,
        "evidence_field": trace.evidence_field,
        "evidence_offset": trace.evidence_offset,
        "link_origin": trace.link_origin,
        "confirmed": trace.confirmed,
        "waiver_reason": trace.waiver_reason,
    }
    if include_history:
        data["history"] = [event_to_dict(event) for event in trace.history]
    return data


def trace_from_dict(data: Mapping[str, Any]) -> RequirementTrace:
    """Reconstruit une trace depuis sa forme sérialisée."""
    history = tuple(
        TraceEvent(
            event_id=_clean(event.get("event_id"), limit=80),
            timestamp=_clean(event.get("timestamp"), limit=64),
            event_type=_clean(event.get("event_type"), limit=40),
            old_value=event.get("old_value"),
            new_value=event.get("new_value"),
            actor=_clean(event.get("actor") or "system", limit=20),
            comment=event.get("comment"),
            origin=_clean(event.get("origin") or "manual", limit=20),
            trace_id=_clean(event.get("trace_id"), limit=80),
        )
        for event in (data.get("history") or [])
    )
    offset = data.get("evidence_offset")
    return RequirementTrace(
        trace_id=_clean(data.get("trace_id"), limit=80),
        requirement_id=_clean(data.get("requirement_id"), limit=120),
        requirement_text=_clean(data.get("requirement_text")),
        source=_clean(data.get("source"), limit=160),
        category=_clean(data.get("category") or "other", limit=40),
        criticality=_clean(data.get("criticality") or "contextual", limit=40),
        evidence_id=_clean(data.get("evidence_id"), limit=160) or None,
        evidence_quote=_clean(data.get("evidence_quote"), limit=4_000) or None,
        status=_clean(data.get("status") or "uncovered", limit=40),
        created_at=_clean(data.get("created_at"), limit=64),
        updated_at=_clean(data.get("updated_at"), limit=64),
        history=history,
        tags=normalize_tags(data.get("tags") or ()),
        offer_id=_clean(data.get("offer_id"), limit=120),
        cv_id=_clean(data.get("cv_id"), limit=120),
        locator=_clean(data.get("locator"), limit=120),
        source_field=_clean(data.get("source_field"), limit=120),
        evidence_field=_clean(data.get("evidence_field"), limit=120),
        evidence_offset=int(offset) if isinstance(offset, int) else None,
        link_origin=_clean(data.get("link_origin") or "manual", limit=20),
        confirmed=bool(data.get("confirmed", True)),
        waiver_reason=_clean(data.get("waiver_reason"), limit=MAX_COMMENT),
    )


# ---------------------------------------------------------------------------
# Le registre
# ---------------------------------------------------------------------------


class TraceabilityRegistry:
    """Le registre : exigences, preuves, statuts et historique.

    Le registre ne persiste rien.  Il est rechargé depuis le magasin
    (voir :mod:`career.traceability_store`) avant chaque usage applicatif.
    """

    def __init__(self, *, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock or utc_now
        self._traces: dict[str, RequirementTrace] = {}
        self._events: list[TraceEvent] = []

    # -- lecture -----------------------------------------------------------

    def traces(self) -> tuple[RequirementTrace, ...]:
        return tuple(self._traces.values())

    def find(self, trace_id: str) -> RequirementTrace | None:
        return self._traces.get(trace_id)

    def get(self, trace_id: str) -> RequirementTrace:
        trace = self._traces.get(trace_id)
        if trace is None:
            raise TraceabilityError("Cette exigence n'existe pas dans le registre.")
        return trace

    def history(self, trace_id: str | None = None) -> tuple[TraceEvent, ...]:
        """Historique global ou historique d'une exigence (jamais réécrit)."""
        if trace_id is None:
            return tuple(self._events)
        return tuple(event for event in self._events if event.trace_id == trace_id)

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
        query: str | None = None,
    ) -> tuple[RequirementTrace, ...]:
        """Liste filtrée.  Tous les filtres sont facultatifs et cumulables."""
        results = list(self._traces.values())
        if status:
            results = [trace for trace in results if trace.status == status]
        if category:
            results = [trace for trace in results if trace.category == category]
        if criticality:
            results = [trace for trace in results if trace.criticality == criticality]
        if offer_id:
            results = [trace for trace in results if trace.offer_id == offer_id]
        if cv_id:
            results = [trace for trace in results if trace.cv_id == cv_id]
        if source:
            results = [trace for trace in results if trace.source == source]
        if tag:
            results = [trace for trace in results if tag in trace.tags]
        if query:
            needle = _clean(query, limit=200).lower()
            results = [
                trace
                for trace in results
                if needle in trace.requirement_text.lower()
                or needle in (trace.requirement_id or "").lower()
                or needle in (trace.evidence_quote or "").lower()
            ]
        return tuple(results)

    # -- écriture ----------------------------------------------------------

    def load(self, trace: RequirementTrace) -> RequirementTrace:
        """Charge une trace déjà persistée (aucun nouvel événement « created »).

        Utilisé pour recharger le registre depuis le magasin local.  Les
        événements déjà connus ne sont pas dupliqués.
        """
        self._traces[trace.trace_id] = trace
        known = {event.event_id for event in self._events}
        for event in trace.history:
            if event.event_id not in known:
                known.add(event.event_id)
                self._events.append(event)
        return trace

    @classmethod
    def from_traces(
        cls,
        traces: Iterable[RequirementTrace],
        *,
        events: Iterable[TraceEvent] = (),
        clock: Callable[[], str] | None = None,
    ) -> TraceabilityRegistry:
        """Reconstruit un registre depuis des traces et des événements persistés."""
        registry = cls(clock=clock)
        for trace in traces:
            registry.load(trace)
        known = {event.event_id for event in registry._events}
        for event in events:
            if event.event_id not in known:
                known.add(event.event_id)
                registry._events.append(event)
        return registry

    def register(
        self,
        *,
        requirement_text: str,
        source: str,
        category: str = "other",
        criticality: str = "contextual",
        requirement_id: str = "",
        offer_id: str = "",
        cv_id: str = "",
        locator: str = "",
        source_field: str = "",
        tags: Iterable[Any] | None = None,
        evidence_id: str | None = None,
        evidence_quote: str | None = None,
        status: str | None = None,
        actor: str = "user",
        comment: str | None = None,
        origin: str = "manual",
    ) -> RequirementTrace:
        """Enregistre une exigence.  Idempotent sur ``trace_id``."""
        text = _clean(requirement_text)
        origin_key = _clean(source, limit=160)
        if not text:
            raise TraceabilityError("Une exigence sans texte ne peut pas être enregistrée.")
        if not origin_key:
            raise TraceabilityError("Une exigence doit dire d'où elle vient (offre, CV ou saisie manuelle).")
        category_key = _clean(category, limit=40) or "other"
        if category_key not in CATEGORIES:
            raise TraceabilityError("Catégorie d'exigence inconnue.")
        criticality_key = _clean(criticality, limit=40) or "contextual"
        if criticality_key not in CRITICALITIES:
            raise TraceabilityError("Criticité d'exigence inconnue.")
        actor_key = _clean(actor, limit=20) or "user"
        if actor_key not in ACTORS:
            raise TraceabilityError("Acteur inconnu pour l'historique.")
        origin_flag = _clean(origin, limit=20) or "manual"
        if origin_flag not in LINK_ORIGINS:
            raise TraceabilityError("Origine de liaison inconnue.")

        evidence = _clean(evidence_id, limit=160)
        quote = _clean(evidence_quote, limit=4_000)
        if bool(evidence) != bool(quote):
            raise TraceabilityError(
                "Une preuve doit avoir un identifiant ET une citation : l'un sans l'autre ne prouve rien."
            )
        status_key = _clean(status, limit=40) if status else ("covered" if evidence and quote else "uncovered")
        if status_key not in STATUSES:
            raise TraceabilityError("Statut d'exigence inconnu.")
        self._check_evidence_invariant(status_key, evidence, quote)

        trace_id = trace_identifier(origin_key, _clean(requirement_id, limit=120), text)
        existing = self._traces.get(trace_id)
        if existing is not None:
            # La création automatique est rejouable : on ne duplique pas,
            # on ne réécrit pas le texte, on ne refait pas l'événement « created ».
            updated = existing
            if existing.category != category_key:
                updated = self._apply(
                    updated,
                    event_type="category_changed",
                    old_value=existing.category,
                    new_value=category_key,
                    actor=actor_key,
                    comment=comment,
                    origin=origin_flag,
                    category=category_key,
                )
            if existing.criticality != criticality_key:
                updated = self._apply(
                    updated,
                    event_type="criticality_changed",
                    old_value=existing.criticality,
                    new_value=criticality_key,
                    actor=actor_key,
                    comment=comment,
                    origin=origin_flag,
                    criticality=criticality_key,
                )
            return updated

        stamp = self._clock()
        created_event = TraceEvent(
            event_id=event_identifier(
                trace_id,
                stamp,
                "created",
                len(self._events),
                new_value=status_key,
                comment=_clean(comment, limit=MAX_COMMENT) or None,
            ),
            timestamp=stamp,
            event_type="created",
            old_value=None,
            new_value=status_key,
            actor=actor_key,
            comment=_clean(comment, limit=MAX_COMMENT) or None,
            origin=origin_flag,
            trace_id=trace_id,
        )
        self._events.append(created_event)
        trace = RequirementTrace(
            trace_id=trace_id,
            requirement_id=_clean(requirement_id, limit=120),
            requirement_text=text,
            source=origin_key,
            category=category_key,
            criticality=criticality_key,
            evidence_id=evidence or None,
            evidence_quote=quote or None,
            status=status_key,
            created_at=stamp,
            updated_at=stamp,
            history=(created_event,),
            tags=normalize_tags(tags),
            offer_id=_clean(offer_id, limit=120),
            cv_id=_clean(cv_id, limit=120),
            locator=_clean(locator, limit=120),
            source_field=_clean(source_field, limit=120),
            evidence_field="",
            evidence_offset=None,
            link_origin=origin_flag,
            confirmed=origin_flag == "manual",
            waiver_reason="",
        )
        self._traces[trace_id] = trace
        return trace

    def set_status(
        self,
        trace_id: str,
        status: str,
        *,
        actor: str = "user",
        comment: str | None = None,
        origin: str = "manual",
    ) -> RequirementTrace:
        """Change le statut d'une exigence (règle de cohérence appliquée)."""
        trace = self.get(trace_id)
        status_key = _clean(status, limit=40)
        if status_key not in STATUSES:
            raise TraceabilityError("Statut d'exigence inconnu.")
        if status_key == "waived":
            raise TraceabilityError(
                "Une dérogation se justifie : utilise la dérogation pour expliquer pourquoi."
            )
        if status_key == trace.status:
            return trace
        if status_key in LINKED_STATUSES and not (trace.evidence_id and trace.evidence_quote):
            raise TraceabilityError(
                "Impossible d'affirmer une couverture sans preuve : lie d'abord une preuve citée."
            )
        if status_key == "uncovered" and (trace.evidence_id or trace.evidence_quote):
            # Repasser « non couverte » délie la preuve : le journal garde la trace.
            trace = self.unlink_evidence(
                trace_id,
                actor=actor,
                comment=comment or "Statut remis à non couvert.",
                origin=origin,
            )
            if trace.status == "uncovered":
                return trace
        old_status = trace.status
        updated = self._apply(
            trace,
            event_type="status_changed",
            old_value=old_status,
            new_value=status_key,
            actor=actor,
            comment=comment,
            origin=origin,
            status=status_key,
        )
        if status_key == "uncovered":
            updated = replace(updated, waiver_reason="")
        return updated

    def set_category(
        self,
        trace_id: str,
        category: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        trace = self.get(trace_id)
        category_key = _clean(category, limit=40)
        if category_key not in CATEGORIES:
            raise TraceabilityError("Catégorie d'exigence inconnue.")
        if category_key == trace.category:
            return trace
        return self._apply(
            trace,
            event_type="category_changed",
            old_value=trace.category,
            new_value=category_key,
            actor=actor,
            comment=comment,
            category=category_key,
        )

    def set_criticality(
        self,
        trace_id: str,
        criticality: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        trace = self.get(trace_id)
        criticality_key = _clean(criticality, limit=40)
        if criticality_key not in CRITICALITIES:
            raise TraceabilityError("Criticité d'exigence inconnue.")
        if criticality_key == trace.criticality:
            return trace
        return self._apply(
            trace,
            event_type="criticality_changed",
            old_value=trace.criticality,
            new_value=criticality_key,
            actor=actor,
            comment=comment,
            criticality=criticality_key,
        )

    def update_tags(
        self,
        trace_id: str,
        tags: Iterable[Any] | None,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        trace = self.get(trace_id)
        new_tags = normalize_tags(tags)
        if new_tags == trace.tags:
            return trace
        return self._apply(
            trace,
            event_type="tags_updated",
            old_value=", ".join(trace.tags) or None,
            new_value=", ".join(new_tags) or None,
            actor=actor,
            comment=comment,
            tags=new_tags,
        )

    def link_evidence(
        self,
        trace_id: str,
        *,
        evidence_id: str,
        evidence_quote: str,
        status: str = "covered",
        actor: str = "user",
        comment: str | None = None,
        origin: str = "manual",
        evidence_field: str = "",
        evidence_offset: int | None = None,
        confirmed: bool | None = None,
    ) -> RequirementTrace:
        """Lie une preuve citée à l'exigence.

        La preuve doit exister **et** être citée : un identifiant seul ne
        prouve rien, une citation seule ne prouve rien sans sa source.
        """
        trace = self.get(trace_id)
        evidence = _clean(evidence_id, limit=160)
        quote = _clean(evidence_quote, limit=4_000)
        if not evidence:
            raise TraceabilityError("Une preuve doit avoir un identifiant.")
        if not quote:
            raise TraceabilityError(
                "Une preuve doit être citée : aucun statut n'est accordé sans citation."
            )
        status_key = _clean(status, limit=40) or "covered"
        if status_key not in LINKED_STATUSES:
            raise TraceabilityError("Une preuve liée implique un statut de couverture.")
        origin_flag = _clean(origin, limit=20) or "manual"
        if origin_flag not in LINK_ORIGINS:
            raise TraceabilityError("Origine de liaison inconnue.")
        if confirmed is None:
            confirmed = origin_flag == "manual"

        updated = self._apply(
            trace,
            event_type="linked",
            old_value=trace.evidence_id,
            new_value=evidence,
            actor=actor,
            comment=comment,
            origin=origin_flag,
            evidence_id=evidence,
            evidence_quote=quote,
            evidence_field=_clean(evidence_field, limit=120),
            evidence_offset=evidence_offset,
            link_origin=origin_flag,
            confirmed=bool(confirmed),
        )
        if updated.status != status_key:
            updated = self._apply(
                updated,
                event_type="status_changed",
                old_value=updated.status,
                new_value=status_key,
                actor=actor,
                comment=comment,
                origin=origin_flag,
                status=status_key,
            )
        return updated

    def unlink_evidence(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
        origin: str = "manual",
    ) -> RequirementTrace:
        """Délie la preuve : l'exigence redevient non couverte."""
        trace = self.get(trace_id)
        if not trace.evidence_id and not trace.evidence_quote:
            return trace
        updated = self._apply(
            trace,
            event_type="unlinked",
            old_value=trace.evidence_id,
            new_value=None,
            actor=actor,
            comment=comment,
            origin=origin,
            evidence_id=None,
            evidence_quote=None,
            evidence_field="",
            evidence_offset=None,
            confirmed=True,
        )
        if updated.status != "uncovered" and updated.status != "waived":
            updated = self._apply(
                updated,
                event_type="status_changed",
                old_value=updated.status,
                new_value="uncovered",
                actor=actor,
                comment=comment,
                origin=origin,
                status="uncovered",
            )
        return updated

    def confirm_link(
        self,
        trace_id: str,
        *,
        confirmed: bool,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Valide (ou rejette) une liaison automatique faite par le matching."""
        trace = self.get(trace_id)
        if confirmed:
            if trace.confirmed:
                return trace
            return self._apply(
                trace,
                event_type="link_confirmed",
                old_value="pending",
                new_value="confirmed",
                actor=actor,
                comment=comment,
                confirmed=True,
            )
        if not trace.evidence_id and not trace.evidence_quote:
            if trace.confirmed:
                return self._apply(
                    trace,
                    event_type="link_rejected",
                    old_value="confirmed",
                    new_value="rejected",
                    actor=actor,
                    comment=comment,
                    confirmed=False,
                )
            return trace
        self._apply(
            trace,
            event_type="link_rejected",
            old_value=trace.evidence_id,
            new_value=None,
            actor=actor,
            comment=comment,
            confirmed=False,
        )
        return self.unlink_evidence(
            trace_id,
            actor=actor,
            comment=comment or "Liaison automatique rejetée.",
            origin="manual",
        )

    def waive(
        self,
        trace_id: str,
        *,
        justification: str,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Déroge : le statut ``waived`` exige une justification."""
        trace = self.get(trace_id)
        reason = _clean(justification, limit=MAX_COMMENT)
        if not reason:
            raise TraceabilityError("Une dérogation doit être justifiée par un texte.")
        if trace.status == "waived" and trace.waiver_reason == reason:
            return trace
        updated = self._apply(
            trace,
            event_type="waived",
            old_value=trace.status,
            new_value="waived",
            actor=actor,
            comment=comment or reason,
            status="waived",
            waiver_reason=reason,
        )
        return updated

    def reopen(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> RequirementTrace:
        """Annule une dérogation : l'exigence redevient active."""
        trace = self.get(trace_id)
        if trace.status != "waived":
            return trace
        restored = "covered" if (trace.evidence_id and trace.evidence_quote) else "uncovered"
        return self._apply(
            trace,
            event_type="reopened",
            old_value="waived",
            new_value=restored,
            actor=actor,
            comment=comment,
            status=restored,
            waiver_reason="",
        )

    def delete(
        self,
        trace_id: str,
        *,
        actor: str = "user",
        comment: str | None = None,
    ) -> TraceEvent:
        """Supprime l'exigence du registre.  Son historique reste consultable."""
        trace = self.get(trace_id)
        stamp = self._clock()
        reason_text = _clean(comment, limit=MAX_COMMENT) or None
        event = TraceEvent(
            event_id=event_identifier(
                trace_id,
                stamp,
                "deleted",
                len(self._events),
                old_value=trace.status,
                comment=reason_text,
            ),
            timestamp=stamp,
            event_type="deleted",
            old_value=trace.status,
            new_value=None,
            actor=_clean(actor, limit=20) or "user",
            comment=reason_text,
            origin="manual",
            trace_id=trace_id,
        )
        self._events.append(event)
        del self._traces[trace_id]
        return event

    # -- interne -----------------------------------------------------------

    def _apply(
        self,
        trace: RequirementTrace,
        *,
        event_type: str,
        old_value: str | None = None,
        new_value: str | None = None,
        actor: str = "user",
        comment: str | None = None,
        origin: str = "manual",
        **changes: Any,
    ) -> RequirementTrace:
        if event_type not in EVENT_TYPES:
            raise TraceabilityError("Type d'événement inconnu.")
        stamp = self._clock()
        comment_text = _clean(comment, limit=MAX_COMMENT) or None
        event = TraceEvent(
            event_id=event_identifier(
                trace.trace_id,
                stamp,
                event_type,
                len(self._events),
                old_value=old_value,
                new_value=new_value,
                comment=comment_text,
            ),
            timestamp=stamp,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
            actor=_clean(actor, limit=20) or "user",
            comment=comment_text,
            origin=_clean(origin, limit=20) or "manual",
            trace_id=trace.trace_id,
        )
        self._events.append(event)
        updated = replace(
            trace,
            history=trace.history + (event,),
            updated_at=stamp,
            **changes,
        )
        self._traces[trace.trace_id] = updated
        return updated

    @staticmethod
    def _check_evidence_invariant(status: str, evidence_id: str, evidence_quote: str) -> None:
        """Règle 1 : un statut de couverture exige une preuve identifiée et citée."""
        has_evidence = bool(evidence_id) and bool(evidence_quote)
        if status in LINKED_STATUSES and not has_evidence:
            raise TraceabilityError(
                "Une exigence couverte doit porter un identifiant de preuve ET une citation."
            )
        if status == "uncovered" and (evidence_id or evidence_quote):
            raise TraceabilityError(
                "Une exigence non couverte ne peut pas porter de preuve : délie-la d'abord."
            )


# ---------------------------------------------------------------------------
# Intégration SK-02 / SK-21
# ---------------------------------------------------------------------------


def traces_from_offer_analysis(
    registry: TraceabilityRegistry,
    analysis: Mapping[str, Any],
    *,
    source: str | None = None,
    actor: str = "system",
    comment: str | None = None,
) -> list[RequirementTrace]:
    """Crée les traces d'une offre à partir du contrat SK-02.

    * Le texte de l'exigence est repris **verbatim** : jamais de reformulation.
    * Les exigences signalées comme ``injection_suspect`` sont ignorées :
      une offre est une donnée, pas une instruction.
    * L'opération est idempotente : rejouer l'extraction ne duplique rien.
    """
    data = analysis or {}
    offer_id = _clean(data.get("offer_id"), limit=120)
    origin_key = source or (f"offer_{offer_id}" if offer_id else "manual")
    suspects = {str(item) for item in (data.get("injection_suspects") or [])}
    traces: list[RequirementTrace] = []
    for record in data.get("requirements") or []:
        if not isinstance(record, Mapping):
            continue
        requirement_id = _clean(record.get("id"), limit=120)
        if requirement_id and requirement_id in suspects:
            continue
        text = _clean(record.get("text"))
        if not text:
            continue
        traces.append(
            registry.register(
                requirement_text=text,
                source=origin_key,
                category=category_from_sk02(record.get("category")),
                criticality=criticality_from_sk02(record.get("modality"), text),
                requirement_id=requirement_id,
                offer_id=offer_id,
                locator=_clean(record.get("locator"), limit=120),
                source_field=_clean(record.get("source_field"), limit=120),
                actor=actor,
                comment=comment,
                origin="manual",
            )
        )
    return traces


def auto_link_from_matching(
    registry: TraceabilityRegistry,
    matches: Sequence[Mapping[str, Any]],
    *,
    actor: str = "system",
    comment: str | None = None,
) -> list[RequirementTrace]:
    """Lie les preuves proposées par le matching (SK-21).

    Chaque correspondance est lue telle que le matching l'a produite : la clé
    ``requirement_id`` désigne l'exigence, ``evidence_id`` et
    ``evidence_quote`` désignent la preuve.  Une correspondance sans citation
    est ignorée : le registre n'accepte jamais une preuve non citée.

    Les liaisons créées ici sont ``origin="auto"`` et ``confirmed=False`` :
    elles attendent une validation humaine.
    """
    linked: list[RequirementTrace] = []
    for match in matches or ():
        if not isinstance(match, Mapping):
            continue
        requirement_id = _clean(match.get("requirement_id"), limit=120)
        evidence_id = _clean(match.get("evidence_id"), limit=160)
        evidence_quote = _clean(match.get("evidence_quote"), limit=4_000)
        if not requirement_id or not evidence_id or not evidence_quote:
            continue
        candidates = [
            trace
            for trace in registry.traces()
            if trace.requirement_id == requirement_id or trace.trace_id == requirement_id
        ]
        if not candidates:
            continue
        trace = candidates[0]
        status = _clean(match.get("status"), limit=40) or "covered"
        if status not in LINKED_STATUSES:
            status = "covered"
        linked.append(
            registry.link_evidence(
                trace.trace_id,
                evidence_id=evidence_id,
                evidence_quote=evidence_quote,
                status=status,
                actor=actor,
                comment=comment or "Liaison proposée par le matching local.",
                origin="auto",
                evidence_field=_clean(match.get("evidence_field"), limit=120),
                confirmed=False,
            )
        )
    return linked


__all__ = [
    "ACTORS",
    "CATEGORIES",
    "CRITICALITIES",
    "EVENT_TYPES",
    "LINKED_STATUSES",
    "LINK_ORIGINS",
    "SK02_CATEGORY_MAP",
    "SK02_MODALITY_MAP",
    "STATUSES",
    "RequirementTrace",
    "TraceEvent",
    "TraceabilityError",
    "TraceabilityRegistry",
    "auto_link_from_matching",
    "category_from_sk02",
    "criticality_from_sk02",
    "event_identifier",
    "event_to_dict",
    "normalize_tag",
    "normalize_tags",
    "trace_from_dict",
    "trace_identifier",
    "trace_to_dict",
    "traces_from_offer_analysis",
]
