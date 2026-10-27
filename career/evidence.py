"""Centre de preuves unifié — la source de vérité des preuves du profil.

La provenance existe déjà à plusieurs endroits du Career local (analyse
d'offre, exigences, profil candidat, exploration).  Ce module ne déplace
aucun de ces modules : il les rassemble dans **un seul endroit** où chaque
preuve du candidat est :

* **nominée** — une affirmation courte (``claim``) : « Analyse financière et
  valorisation » ;
* **citée** — une source, un emplacement et une citation verbatim
  (``source_document``, ``source_location``, ``quote``) ;
* **qualifiée** — un type (``experience``, ``education``, ``skill``,
  ``language``, ``project``, ``certification``) et une confiance
  (``direct``, ``inferred``, ``declared``) ;
* **décidée** — ``approved`` n'est vrai que si la personne l'a décidé ;
* **suivie** — chaque usage dans un CV ou une lettre est horodaté.

Trois règles sont structurelles, pas des conventions :

1. Une preuve non approuvée n'est jamais une preuve : elle reste visible,
   jamais transformée en affirmation.  « Unknown » reste préféré à
   « inferred ».
2. Une fusion de doublons ne perd jamais une provenance : l'identifiant
   gardé absorbe les citations des preuves fusionnées et l'historique de
   fusion conserve les instantanés complets.
3. Rien ici n'appelle un réseau, un modèle ou un moteur d'inférence.  Les
   dates, les statuts et les compteurs sont déterministes et locaux.

Le module ne touche pas au stockage : la persistance est dans
``career/evidence_store.py``.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from workspace_core import UserFacingError

from .models import clean_text, normalized_text, utc_now


if TYPE_CHECKING:  # pragma: no cover - import de typage uniquement
    from .evidence_store import EvidenceStore


# ── Vocabulaire fermé ───────────────────────────────────────────────────────
EVIDENCE_TYPES: tuple[str, ...] = (
    "experience",
    "education",
    "skill",
    "language",
    "project",
    "certification",
)

CONFIDENCE_LEVELS: tuple[str, ...] = ("direct", "inferred", "declared")

USAGE_TARGETS: tuple[str, ...] = ("cv", "letter")

EVIDENCE_ID_PREFIX = "evidence_"

#: Version du format d'export portable et du schéma logique du centre.
SCHEMA_VERSION = 1

# ── Bornes ──────────────────────────────────────────────────────────────────
MAX_CLAIM_CHARS = 400
MAX_QUOTE_CHARS = 4_000
MAX_SOURCE_CHARS = 260
MAX_LOCATION_CHARS = 260
MAX_TAGS = 20
MAX_TAG_CHARS = 60
MAX_CONTEXT_CHARS = 200
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

_ID_PATTERN = re.compile(r"^evidence_[a-z0-9]{4,40}$")


def _now() -> str:
    return utc_now()


def claim_key(value: Any) -> str:
    """Return the comparison key of a claim (lowercase, no accent)."""
    return normalized_text(value)


def _sorted_by_recency(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Sort the evidences from the most recent to the oldest.

    The tie is broken by the identifier, in ascending order : two runs on the
    same data always return the same list.
    """
    ordered = sorted(items, key=lambda entry: entry.id)
    ordered.sort(key=lambda entry: entry.created_at, reverse=True)
    return ordered


def _safe_file_name(value: Any) -> str:
    """Return a short, harmless file name (never a path)."""
    name = Path(str(value or "")).name
    name = "".join(character for character in name if ord(character) >= 32).strip().lstrip(".")
    if not name or name in {".", ".."}:
        return ""
    return name[:MAX_SOURCE_CHARS]


def _bounded_tags(values: Any) -> list[str]:
    """Normalize a tag list: lowercase, bounded, deduplicated, ordered.

    Only an ordered container is accepted : the order of the tags must not
    depend on the hash seed of the interpreter.
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


def _parse_moment(value: Any) -> datetime | None:
    """Parse an ISO-8601 date or timestamp into an aware datetime."""
    text = clean_text(value, limit=40)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_expired(expires_at: str, now: str) -> bool:
    """Return whether an evidence reached its expiry date.

    An empty expiry date never expires: a proof without a stated validity
    window stays valid until the person says otherwise.  A date-only expiry
    (``2026-12-31``) covers the whole day: the proof expires the next
    morning.  An unparseable date is rejected when it is written, so it can
    never silently mean « never expires ».
    """
    deadline = _parse_moment(expires_at)
    if deadline is None:
        return False
    text = clean_text(expires_at, limit=40)
    if len(text) == 10:
        deadline = deadline + timedelta(days=1)
    reference = _parse_moment(now) or datetime.now(timezone.utc)
    return deadline <= reference


def _validated_expiry(value: Any) -> str:
    """Return a normalized expiry date, or raise when it cannot be read.

    A typo must never be read as « this proof never expires ».
    """
    text = clean_text(value, limit=32)
    if not text:
        return ""
    if _parse_moment(text) is None:
        raise UserFacingError("La date d’expiration doit être au format AAAA-MM-JJ.")
    return text


@dataclass
class EvidenceUsage:
    """One recorded use of an evidence in a CV or a cover letter."""

    target: str
    context: str = ""
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "context": self.context, "at": self.at}

    @classmethod
    def from_dict(cls, payload: Any) -> "EvidenceUsage":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            target=clean_text(data.get("target"), limit=20),
            context=clean_text(data.get("context"), limit=MAX_CONTEXT_CHARS),
            at=clean_text(data.get("at"), limit=40),
        )


@dataclass
class EvidenceItem:
    """One proven (or not yet proven) statement about the candidate.

    The eleven first fields are the public contract of the center.  The
    remaining fields carry the local bookkeeping the contract implies:
    attachments, usage, blocking, expiry and merge history.
    """

    id: str
    claim: str
    source_document: str
    source_location: str
    quote: str
    evidence_type: str
    confidence: str
    approved: bool
    created_at: str
    updated_at: str
    tags: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    usage: list[EvidenceUsage] = field(default_factory=list)
    blocked: bool = False
    expires_at: str = ""
    merged_from: list[str] = field(default_factory=list)
    additional_sources: list[dict[str, str]] = field(default_factory=list)

    # -- sérialisation ------------------------------------------------------
    def to_dict(self, now: str = "") -> dict[str, Any]:
        """Return the JSON-safe representation of the evidence."""
        reference = clean_text(now, limit=40) or _now()
        return {
            "id": self.id,
            "claim": self.claim,
            "source_document": self.source_document,
            "source_location": self.source_location,
            "quote": self.quote,
            "evidence_type": self.evidence_type,
            "confidence": self.confidence,
            "approved": bool(self.approved),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": list(self.tags),
            "attachments": [dict(entry) for entry in self.attachments],
            "usage": [usage.to_dict() for usage in self.usage],
            "blocked": bool(self.blocked),
            "expires_at": self.expires_at,
            "merged_from": list(self.merged_from),
            "additional_sources": [dict(source) for source in self.additional_sources],
            "expired": self.is_expired(reference),
            "proven": self.is_proven(reference),
            "used_in_cv": self.used_in("cv"),
            "used_in_letters": self.used_in("letter"),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "EvidenceItem":
        """Rebuild an evidence from its serialized form."""
        data = payload if isinstance(payload, dict) else {}
        usage = [EvidenceUsage.from_dict(entry) for entry in data.get("usage") or []]
        attachments = [dict(entry) for entry in data.get("attachments") or [] if isinstance(entry, dict)]
        sources = [
            {
                "source_document": clean_text(source.get("source_document"), limit=MAX_SOURCE_CHARS),
                "source_location": clean_text(source.get("source_location"), limit=MAX_LOCATION_CHARS),
                "quote": clean_text(source.get("quote"), limit=MAX_QUOTE_CHARS),
                "approved": bool(source.get("approved")),
            }
            for source in data.get("additional_sources") or []
            if isinstance(source, dict)
        ]
        return cls(
            id=clean_text(data.get("id"), limit=60),
            claim=clean_text(data.get("claim"), limit=MAX_CLAIM_CHARS),
            source_document=clean_text(data.get("source_document"), limit=MAX_SOURCE_CHARS),
            source_location=clean_text(data.get("source_location"), limit=MAX_LOCATION_CHARS),
            quote=clean_text(data.get("quote"), limit=MAX_QUOTE_CHARS),
            evidence_type=clean_text(data.get("evidence_type"), limit=40),
            confidence=clean_text(data.get("confidence"), limit=40),
            approved=bool(data.get("approved")),
            created_at=clean_text(data.get("created_at"), limit=40),
            updated_at=clean_text(data.get("updated_at"), limit=40),
            tags=_bounded_tags(data.get("tags")),
            attachments=attachments,
            usage=usage,
            blocked=bool(data.get("blocked")),
            expires_at=clean_text(data.get("expires_at"), limit=32),
            merged_from=[clean_text(item, limit=60) for item in data.get("merged_from") or [] if clean_text(item, limit=60)],
            additional_sources=sources,
        )

    # -- état ───────────────────────────────────────────────────────────────
    def is_expired(self, now: str = "") -> bool:
        return _is_expired(self.expires_at, clean_text(now, limit=40) or _now())

    def used_in(self, target: str) -> bool:
        """Return whether the evidence was already used in a CV or a letter."""
        return any(usage.target == target for usage in self.usage)

    def approved_sources(self) -> list[str]:
        """Return the sources that carry an approval, including merged ones."""
        sources = []
        if self.approved:
            sources.append("citation principale")
        for source in self.additional_sources:
            if isinstance(source, dict) and source.get("approved"):
                location = clean_text(source.get("source_location"), limit=MAX_LOCATION_CHARS)
                sources.append(location or "source fusionnée")
        return sources

    def is_proven(self, now: str = "") -> bool:
        """Return whether the evidence counts as a proof.

        A proof is approved by the person — on its own citation or on a
        citation it absorbed during a merge — not expired, and not blocked
        for usage.  A declared-but-unapproved evidence stays visible in the
        grid but never counts as a proven skill.
        """
        reference = clean_text(now, limit=40) or _now()
        if self.blocked or self.is_expired(reference):
            return False
        return bool(self.approved_sources())


#: Statuts d'un fait candidat SK-10 qui autorisent la personne à l'utiliser.
USABLE_FACT_STATUSES: frozenset[str] = frozenset({"approved", "modified"})

#: Seuils déterministes de conversion d'un score SK-03 (0-1) vers le
#: vocabulaire de confiance du centre.  Ils sont écrits ici, et non calculés
#: par un modèle : la conversion reste auditable.
FIT_DIRECT_THRESHOLD = 0.8
FIT_INFERRED_THRESHOLD = 0.5


@dataclass
class EvidenceUsageStats:
    """Global counters of the evidence center."""

    total_evidence: int
    approved: int
    used_in_cv: int
    used_in_letters: int
    expired: int
    by_type: dict[str, int]
    by_confidence: dict[str, int]
    # Compléments (toujours présents, valeurs par défaut) : ils évitent de
    # recalculer la couverture côté client.
    blocked: int = 0
    unapproved: int = 0
    claims: int = 0
    proven_claims: int = 0
    unproven_claims: int = 0
    attachments: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evidence": self.total_evidence,
            "approved": self.approved,
            "used_in_cv": self.used_in_cv,
            "used_in_letters": self.used_in_letters,
            "expired": self.expired,
            "by_type": dict(self.by_type),
            "by_confidence": dict(self.by_confidence),
            "blocked": self.blocked,
            "unapproved": self.unapproved,
            "claims": self.claims,
            "proven_claims": self.proven_claims,
            "unproven_claims": self.unproven_claims,
            "attachments": self.attachments,
        }


def _derived_id(*parts: Any) -> str:
    """Return a deterministic identifier built from the content of a source.

    An import that is replayed must not create a second proof : the same
    source always produces the same identifier.
    """
    digest = hashlib.sha256("|".join(clean_text(part, limit=400) for part in parts).encode("utf-8"))
    return f"{EVIDENCE_ID_PREFIX}{digest.hexdigest()[:12]}"


def evidence_from_candidate_fact(fact: dict[str, Any]) -> EvidenceItem | None:
    """Convert one SK-10 candidate fact into an evidence item.

    The adapter reads the *serialized* contract of the candidate profile
    (label, value, status, evidence) and never imports the SK-10 module: the
    center can therefore be used before, with or after that module lands.

    The identifier is derived from the fact: importing the same fact twice
    updates the same proof instead of creating a duplicate.

    ``None`` is returned when the fact is not a proof the center can hold —
    a contact or a date is not a proof of a skill.
    """
    data = fact if isinstance(fact, dict) else {}
    kind = clean_text(data.get("kind"), limit=40)
    if kind not in EVIDENCE_TYPES:
        return None
    label = clean_text(data.get("label"), limit=MAX_CLAIM_CHARS)
    if not label:
        return None
    value = clean_text(data.get("value"), limit=MAX_CLAIM_CHARS)
    claim = f"{label} — {value}" if value and value.lower() != label.lower() else label
    source = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
    quote = clean_text(source.get("quote"), limit=MAX_QUOTE_CHARS)
    document = clean_text(source.get("filename"), limit=MAX_SOURCE_CHARS) or clean_text(
        data.get("source_document"), limit=MAX_SOURCE_CHARS
    )
    location = ""
    page = source.get("page")
    if page not in (None, ""):
        location = f"page {page}"
    status = clean_text(data.get("status"), limit=20)
    fact_id = clean_text(data.get("id"), limit=80)
    identifier = _derived_id("fact", fact_id or claim, kind, document, quote) if (fact_id or claim) else ""
    return EvidenceItem(
        id=identifier,
        claim=claim,
        source_document=document,
        source_location=location,
        quote=quote,
        evidence_type=kind,
        confidence="direct" if quote else "declared",
        approved=status in USABLE_FACT_STATUSES,
        created_at=clean_text(data.get("created_at"), limit=40),
        updated_at=clean_text(data.get("updated_at"), limit=40),
        tags=[status] if status else [],
    )


def evidence_from_fit_verdict(verdict: dict[str, Any]) -> EvidenceItem | None:
    """Convert one SK-03 requirement-fit verdict into an evidence item.

    Only a ``supported`` verdict carries a proof of the candidate side.  The
    item stays **unapproved**: the correspondence is computed locally, but
    only the person decides that it is a proof.
    """
    data = verdict if isinstance(verdict, dict) else {}
    if clean_text(data.get("verdict"), limit=20) != "supported":
        return None
    quote = clean_text(data.get("profile_evidence"), limit=MAX_QUOTE_CHARS)
    if not quote:
        return None
    requirement = clean_text(data.get("requirement_text"), limit=MAX_CLAIM_CHARS)
    claim = f"{requirement} — {quote}" if requirement else quote
    raw_confidence = data.get("confidence")
    confidence = "declared"
    if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
        if raw_confidence >= FIT_DIRECT_THRESHOLD:
            confidence = "direct"
        elif raw_confidence >= FIT_INFERRED_THRESHOLD:
            confidence = "inferred"
    requirement_id = clean_text(data.get("requirement_id"), limit=MAX_LOCATION_CHARS)
    return EvidenceItem(
        id=_derived_id("fit", requirement_id, quote),
        claim=claim,
        source_document="requirements_fit",
        source_location=requirement_id,
        quote=quote,
        evidence_type="skill",
        confidence=confidence,
        approved=False,
        created_at="",
        updated_at="",
        tags=["requirements_fit"],
    )


class EvidenceCenter:
    """The single source of truth of the candidate's proofs.

    The center owns the rules (validation, merge, coverage, statistics) and
    delegates the persistence to an ``EvidenceStore``.  It never performs a
    network call and never approves anything by itself.
    """

    def __init__(
        self,
        store: "EvidenceStore",
        *,
        attachments_dir: Path | None = None,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._store = store
        self._attachments_dir = Path(attachments_dir) if attachments_dir else None
        self._clock = clock

    # -- helpers ------------------------------------------------------------
    def _now(self) -> str:
        return clean_text(self._clock(), limit=40) or _now()

    def _require(self, evidence_id: str) -> EvidenceItem:
        item = self.get_evidence(evidence_id)
        if item is None:
            raise UserFacingError("Cette preuve n’existe pas.")
        return item

    @staticmethod
    def _validated(item: EvidenceItem) -> EvidenceItem:
        """Check the public contract of one evidence."""
        if item.evidence_type not in EVIDENCE_TYPES:
            raise UserFacingError("Le type de preuve est inconnu.")
        if item.confidence not in CONFIDENCE_LEVELS:
            raise UserFacingError("Le niveau de confiance est inconnu.")
        if not item.claim:
            raise UserFacingError("Une preuve doit nommer ce qu’elle démontre.")
        if not item.quote and not item.source_document:
            raise UserFacingError("Une preuve doit citer sa source ou sa citation.")
        return item

    # -- CRUD ---------------------------------------------------------------
    def add_evidence(self, item: EvidenceItem) -> str:
        """Register one evidence and return its identifier."""
        now = self._now()
        identifier = clean_text(item.id, limit=60)
        if not identifier:
            identifier = f"{EVIDENCE_ID_PREFIX}{uuid.uuid4().hex[:12]}"
        if not _ID_PATTERN.match(identifier):
            raise UserFacingError("L’identifiant de preuve est invalide.")
        if self.get_evidence(identifier) is not None:
            raise UserFacingError("Cette preuve existe déjà.")
        item.id = identifier
        self._prepare(item, now)
        self._store.save(item)
        return item.id

    def upsert_evidence(self, item: EvidenceItem) -> str:
        """Register or refresh one evidence with the same identifier.

        Used by the imports (SK-03, SK-10) : replaying an import must not
        create a second proof.  A refresh never revokes a decision of the
        person and never drops the usage or the attached documents.
        """
        identifier = clean_text(item.id, limit=60)
        if not identifier:
            return self.add_evidence(item)
        if not _ID_PATTERN.match(identifier):
            raise UserFacingError("L’identifiant de preuve est invalide.")
        existing = self.get_evidence(identifier)
        if existing is None:
            self._prepare(item, self._now())
            self._store.save(item)
            return item.id
        item.approved = bool(existing.approved or item.approved)
        item.blocked = bool(existing.blocked)
        item.expires_at = existing.expires_at or item.expires_at
        item.attachments = list(existing.attachments)
        item.usage = list(existing.usage)
        item.merged_from = list(existing.merged_from)
        item.additional_sources = list(existing.additional_sources)
        item.created_at = existing.created_at
        self._prepare(item, self._now())
        self._store.save(item)
        return item.id

    def _prepare(self, item: EvidenceItem, now: str) -> None:
        """Normalize and check one evidence before it is stored."""
        item.claim = clean_text(item.claim, limit=MAX_CLAIM_CHARS)
        item.source_document = clean_text(item.source_document, limit=MAX_SOURCE_CHARS)
        item.source_location = clean_text(item.source_location, limit=MAX_LOCATION_CHARS)
        item.quote = clean_text(item.quote, limit=MAX_QUOTE_CHARS)
        item.tags = _bounded_tags(item.tags)
        item.expires_at = _validated_expiry(item.expires_at)
        item.merged_from = [clean_text(entry, limit=60) for entry in item.merged_from if clean_text(entry, limit=60)]
        item.usage = [EvidenceUsage.from_dict(usage.to_dict()) for usage in item.usage]
        item.created_at = clean_text(item.created_at, limit=40) or now
        item.updated_at = now
        self._validated(item)

    def get_evidence(self, evidence_id: str) -> EvidenceItem | None:
        """Return one evidence, or ``None`` when it does not exist."""
        identifier = clean_text(evidence_id, limit=60)
        if not identifier:
            return None
        return self._store.get(identifier)

    def list_evidence(
        self,
        *,
        query: str = "",
        evidence_type: str = "",
        confidence: str = "",
        approved: bool | None = None,
        blocked: bool | None = None,
        expired: bool | None = None,
        used: str = "",
    ) -> list[EvidenceItem]:
        """Return the evidences matching the filters, most recent first."""
        now = self._now()
        items = self._store.all()
        wanted_type = clean_text(evidence_type, limit=40)
        wanted_confidence = clean_text(confidence, limit=40)
        wanted_usage = clean_text(used, limit=20)
        if wanted_usage and wanted_usage not in USAGE_TARGETS:
            raise UserFacingError("Le filtre d’usage est inconnu.")
        needle = claim_key(query)
        selected: list[EvidenceItem] = []
        for item in items:
            if wanted_type and item.evidence_type != wanted_type:
                continue
            if wanted_confidence and item.confidence != wanted_confidence:
                continue
            if approved is not None and bool(item.approved) is not approved:
                continue
            if blocked is not None and bool(item.blocked) is not blocked:
                continue
            if expired is not None and item.is_expired(now) is not expired:
                continue
            if wanted_usage and not item.used_in(wanted_usage):
                continue
            if needle and not self._matches(needle, self._haystack(item)):
                continue
            selected.append(item)
        return _sorted_by_recency(selected)

    def search_evidence(self, query: str, type: str | None = None) -> list[EvidenceItem]:
        """Search the claim, the quote, the source and the tags of a proof."""
        evidence_type = clean_text(type, limit=40) if type else ""
        return self.list_evidence(query=query, evidence_type=evidence_type)

    def get_evidence_for_claim(self, claim: str) -> list[EvidenceItem]:
        """Return every evidence proving the same claim."""
        wanted = claim_key(claim)
        if not wanted:
            return []
        items = [item for item in self._store.all() if claim_key(item.claim) == wanted]
        return _sorted_by_recency(items)

    def update_evidence(self, evidence_id: str, changes: dict[str, Any]) -> EvidenceItem:
        """Apply the editable fields of one evidence.

        The change is built on a **copy** and validated before it is stored:
        a refused change never leaves a half-written proof behind.
        """
        item = self._require(evidence_id)
        limits = {
            "claim": MAX_CLAIM_CHARS,
            "source_document": MAX_SOURCE_CHARS,
            "source_location": MAX_LOCATION_CHARS,
            "quote": MAX_QUOTE_CHARS,
        }
        allowed = {
            "claim",
            "source_document",
            "source_location",
            "quote",
            "evidence_type",
            "confidence",
            "tags",
            "expires_at",
            "approved",
            "blocked",
        }
        candidate = EvidenceItem.from_dict(item.to_dict())
        for key, value in (changes or {}).items():
            if key not in allowed:
                continue
            if key == "tags":
                candidate.tags = _bounded_tags(value)
            elif key == "approved":
                candidate.approved = bool(value)
            elif key == "blocked":
                candidate.blocked = bool(value)
            elif key == "evidence_type":
                candidate.evidence_type = clean_text(value, limit=40)
            elif key == "confidence":
                candidate.confidence = clean_text(value, limit=40)
            elif key == "expires_at":
                candidate.expires_at = _validated_expiry(value)
            else:
                setattr(candidate, key, clean_text(value, limit=limits[key]))
        candidate.updated_at = self._now()
        self._validated(candidate)
        self._store.save(candidate)
        return candidate

    def delete_evidence(self, evidence_id: str) -> bool:
        """Remove one evidence and the documents it attached.

        The copies of the attached documents are erased too: a proof that no
        longer exists must not leave a personal document on disk.
        """
        identifier = clean_text(evidence_id, limit=60)
        item = self.get_evidence(identifier)
        if item is None:
            return False
        deleted = self._store.delete(identifier)
        self._remove_attachments(item)
        return deleted

    def _remove_attachments(self, item: EvidenceItem) -> None:
        """Erase the attached files of one evidence from the private folder."""
        if self._attachments_dir is None:
            return
        for entry in item.attachments:
            if not isinstance(entry, dict):
                continue
            name = Path(str(entry.get("name", ""))).name
            if not name:
                continue
            try:
                (self._attachments_dir / name).unlink(missing_ok=True)
            except OSError:
                pass

    # -- décisions ----------------------------------------------------------
    def mark_approved(self, evidence_id: str, approved: bool) -> None:
        """Record the person's decision on one evidence."""
        item = self._require(evidence_id)
        item.approved = bool(approved)
        item.updated_at = self._now()
        self._store.save(item)

    def set_blocked(self, evidence_id: str, blocked: bool) -> None:
        """Block (or unblock) the usage of one evidence."""
        item = self._require(evidence_id)
        item.blocked = bool(blocked)
        item.updated_at = self._now()
        self._store.save(item)

    def set_expires_at(self, evidence_id: str, expires_at: str) -> None:
        """Set the expiry date of one evidence (empty means "no expiry")."""
        item = self._require(evidence_id)
        item.expires_at = _validated_expiry(expires_at)
        item.updated_at = self._now()
        self._store.save(item)

    # -- usage --------------------------------------------------------------
    def record_usage(self, evidence_id: str, target: str, context: str = "") -> None:
        """Record that an evidence was used in a CV or a cover letter."""
        wanted = clean_text(target, limit=20)
        if wanted not in USAGE_TARGETS:
            raise UserFacingError("La cible d’usage doit être « cv » ou « letter ».")
        item = self._require(evidence_id)
        if item.blocked:
            raise UserFacingError("Cette preuve est bloquée pour l’usage.")
        item.usage.append(
            EvidenceUsage(
                target=wanted,
                context=clean_text(context, limit=MAX_CONTEXT_CHARS),
                at=self._now(),
            )
        )
        item.updated_at = self._now()
        self._store.save(item)

    # -- pièces jointes -----------------------------------------------------
    def attach_document(self, evidence_id: str, doc_path: str, original_name: str = "") -> None:
        """Attach a local document to one evidence.

        The file is copied into the private attachment directory under an
        opaque name: only the file name, its checksum and its size are kept
        in the index.  An original path is never persisted.
        """
        item = self._require(evidence_id)
        source = Path(str(doc_path)).expanduser()
        try:
            resolved = source.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise UserFacingError("Le document à attacher est introuvable.") from error
        if not resolved.is_file():
            raise UserFacingError("Le document à attacher est introuvable.")
        size = resolved.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise UserFacingError("Le document à attacher est trop volumineux (maximum 10 Mo).")
        if self._attachments_dir is None:
            raise UserFacingError("Aucune pièce jointe ne peut être attachée ici.")
        self._attachments_dir.mkdir(parents=True, exist_ok=True)
        label = _safe_file_name(original_name) or resolved.name[:MAX_SOURCE_CHARS]
        suffix = Path(label).suffix.lower()[:12]
        destination = self._attachments_dir / f"{item.id}_{uuid.uuid4().hex[:12]}{suffix}"
        payload = resolved.read_bytes()
        # The permissions are set before the bytes are written : a personal
        # document is never briefly readable by another account.
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
        except OSError as error:
            destination.unlink(missing_ok=True)
            raise UserFacingError("La pièce jointe n’a pas pu être enregistrée.") from error
        item.attachments.append(
            {
                "name": destination.name,
                "original_name": label,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": size,
                "attached_at": self._now(),
            }
        )
        item.updated_at = self._now()
        self._store.save(item)

    # -- fusion -------------------------------------------------------------
    def merge_evidence(self, ids: list[str], keep_id: str) -> None:
        """Merge duplicated proofs into one identifier.

        The kept identifier absorbs the citations, the tags, the attachments
        and the usage of the merged proofs.  The merged proofs are deleted
        but their complete snapshot is kept in the merge history: a merge
        never loses a provenance.

        The approval of the person is **never** transferred from one citation
        to another: an absorbed proof keeps its own approval flag inside
        ``additional_sources``.  The claim stays proven because a source of
        the merged proof was approved, and the detail panel says which one.
        """
        keeper_id = clean_text(keep_id, limit=60)
        wanted: list[str] = []
        for raw in ids or []:
            identifier = clean_text(raw, limit=60)
            if identifier and identifier not in wanted:
                wanted.append(identifier)
        if not wanted:
            raise UserFacingError("Aucune preuve à fusionner.")
        if keeper_id not in wanted:
            raise UserFacingError("La preuve à conserver doit faire partie de la fusion.")
        keeper = self._require(keeper_id)
        others = [self._require(identifier) for identifier in wanted if identifier != keeper_id]
        if not others:
            # Une fusion d'une seule preuve n'est pas une fusion : rien à
            # absorber, rien à tracer.
            return
        now = self._now()
        for other in others:
            keeper.tags = _bounded_tags(list(keeper.tags) + list(other.tags))
            keeper.attachments.extend(dict(entry) for entry in other.attachments)
            keeper.usage.extend(EvidenceUsage.from_dict(usage.to_dict()) for usage in other.usage)
            keeper.additional_sources.append(
                {
                    "source_document": other.source_document,
                    "source_location": other.source_location,
                    "quote": other.quote,
                    "approved": bool(other.approved),
                }
            )
            keeper.additional_sources.extend(dict(source) for source in other.additional_sources)
            keeper.merged_from.append(other.id)
            keeper.merged_from.extend(other.merged_from)
            # Le blocage et l'expiration les plus restrictifs sont conservés.
            keeper.blocked = bool(keeper.blocked or other.blocked)
            keeper.expires_at = self._strictest_expiry(keeper.expires_at, other.expires_at)
        keeper.merged_from = sorted({entry for entry in keeper.merged_from if entry})
        keeper.updated_at = now
        self._validated(keeper)
        snapshots = [other.to_dict(now) for other in others]
        # Une seule transaction : soit la fusion et son historique sont
        # écrits, soit rien ne l'est. Une provenance ne peut pas disparaître
        # entre deux écritures.
        self._store.merge_items(keeper, [other.id for other in others], snapshots)

    @staticmethod
    def _strictest_expiry(first: str, second: str) -> str:
        """Return the earliest of two expiry dates (the most restrictive)."""
        left = clean_text(first, limit=32)
        right = clean_text(second, limit=32)
        if not left:
            return right
        if not right:
            return left
        return min(left, right)

    # -- couverture et statistiques -----------------------------------------
    def get_claim_coverage(self, claims: list[str]) -> list[dict[str, Any]]:
        """Return, for each claim, whether a proof exists and which ones.

        A claim without proof is **not** a failed claim: it is simply not
        proven yet.  The center never turns an absence into a negative fact.
        """
        items = self._store.all()
        by_claim: dict[str, list[EvidenceItem]] = {}
        for item in items:
            by_claim.setdefault(claim_key(item.claim), []).append(item)
        now = self._now()
        coverage: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in claims or []:
            label = clean_text(raw, limit=MAX_CLAIM_CHARS)
            key = claim_key(label)
            if not key or key in seen:
                continue
            seen.add(key)
            matching = by_claim.get(key, [])
            proven = [item for item in matching if item.is_proven(now)]
            coverage.append(
                {
                    "claim": label,
                    "key": key,
                    "proven": bool(proven),
                    "evidence_ids": [item.id for item in matching],
                    "proven_evidence_ids": [item.id for item in proven],
                    "evidence_count": len(matching),
                }
            )
        return coverage

    def get_usage_stats(self) -> EvidenceUsageStats:
        """Return the global counters of the center."""
        now = self._now()
        items = self._store.all()
        by_type = {name: 0 for name in EVIDENCE_TYPES}
        by_confidence = {name: 0 for name in CONFIDENCE_LEVELS}
        approved = 0
        used_cv = 0
        used_letter = 0
        expired = 0
        blocked = 0
        attachments = 0
        claims: dict[str, list[EvidenceItem]] = {}
        for item in items:
            by_type[item.evidence_type] = by_type.get(item.evidence_type, 0) + 1
            by_confidence[item.confidence] = by_confidence.get(item.confidence, 0) + 1
            if item.approved:
                approved += 1
            if item.used_in("cv"):
                used_cv += 1
            if item.used_in("letter"):
                used_letter += 1
            if item.is_expired(now):
                expired += 1
            if item.blocked:
                blocked += 1
            attachments += len(item.attachments)
            claims.setdefault(claim_key(item.claim), []).append(item)
        proven_claims = sum(
            1 for entries in claims.values() if any(entry.is_proven(now) for entry in entries)
        )
        return EvidenceUsageStats(
            total_evidence=len(items),
            approved=approved,
            used_in_cv=used_cv,
            used_in_letters=used_letter,
            expired=expired,
            by_type=by_type,
            by_confidence=by_confidence,
            blocked=blocked,
            unapproved=len(items) - approved,
            claims=len(claims),
            proven_claims=proven_claims,
            unproven_claims=len(claims) - proven_claims,
            attachments=attachments,
        )

    # -- export -------------------------------------------------------------
    def export_payload(self) -> dict[str, Any]:
        """Return the portable export of the center (JSON-safe)."""
        now = self._now()
        items = _sorted_by_recency(self._store.all())
        payload = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": now,
            "items": [item.to_dict(now) for item in items],
            "stats": self.get_usage_stats().to_dict(),
            "claims": self.get_claim_coverage([item.claim for item in items]),
            "merges": self._store.merges(),
        }
        return payload

    def export_markdown(self) -> str:
        """Return a readable document of the proven and unproven claims."""
        now = self._now()
        items = _sorted_by_recency(self._store.all())
        stats = self.get_usage_stats()
        lines: list[str] = [
            "# Centre de preuves — export local",
            "",
            f"Exporté le {now} · {stats.total_evidence} preuves · "
            f"{stats.proven_claims} affirmations prouvées sur {stats.claims}.",
            "",
            "## Vue d'ensemble",
            "",
            f"- Preuves approuvées : {stats.approved} / {stats.total_evidence}",
            f"- Utilisées dans un CV : {stats.used_in_cv}",
            f"- Utilisées dans une lettre : {stats.used_in_letters}",
            f"- Expirées : {stats.expired}",
            f"- Bloquées pour l'usage : {stats.blocked}",
            "",
        ]
        by_claim: dict[str, list[EvidenceItem]] = {}
        for item in items:
            by_claim.setdefault(claim_key(item.claim), []).append(item)
        for key, entries in by_claim.items():
            title = entries[0].claim.replace("\n", " ").replace("\r", " ").strip()
            proven = any(entry.is_proven(now) for entry in entries)
            lines.append(f"## {title}")
            lines.append("")
            lines.append(f"Statut : **{'prouvé' if proven else 'non prouvé'}**")
            lines.append("")
            for entry in entries:
                state = "approuvée" if entry.approved else "non approuvée"
                if entry.is_expired(now):
                    state += " · expirée"
                if entry.blocked:
                    state += " · bloquée"
                lines.append(f"- **{entry.evidence_type}** · confiance `{entry.confidence}` · {state}")
                if entry.source_document:
                    location = entry.source_location or "emplacement non précisé"
                    lines.append(f"  - Source : `{entry.source_document}` — {location}")
                if entry.quote:
                    citation = entry.quote.replace("\n", " ").replace("\r", " ").strip()
                    lines.append(f"  - Citation : « {citation} »")
                if entry.tags:
                    lines.append(f"  - Étiquettes : {', '.join(entry.tags)}")
            lines.append("")
        return "\n".join(lines)

    # -- interne ------------------------------------------------------------
    @staticmethod
    def _haystack(item: EvidenceItem) -> str:
        """Return the normalized searchable text of one evidence."""
        parts = [item.claim, item.quote, item.source_document, item.source_location]
        parts.extend(item.tags)
        parts.extend(source.get("quote", "") for source in item.additional_sources)
        return normalized_text(" ".join(part for part in parts if part))

    @staticmethod
    def _matches(needle: str, haystack: str) -> bool:
        """Return whether a normalized query matches a normalized text.

        Three deterministic rules, tried in order :

        1. the whole query is a substring of the text ;
        2. every meaningful word of the query (three characters or more)
           starts one word of the text — a search-as-you-type prefix ;
        3. every meaningful word of the query (four characters or more)
           shares its five first letters with one word of the text.

        The third rule exists because French inserts vowels: « finance »
        must find « financière ».  Nothing is scored and nothing is ranked by
        relevance : the result is the same list, in the same order, on every
        machine.
        """
        if not needle:
            return True
        if needle in haystack:
            return True
        words = haystack.split()
        tokens = [token for token in needle.split() if len(token) >= 3]
        if not tokens:
            return False
        return all(EvidenceCenter._token_matches(token, words) for token in tokens)

    @staticmethod
    def _token_matches(token: str, words: list[str]) -> bool:
        """Return whether one query word matches one text word."""
        if any(word == token or word.startswith(token) for word in words):
            return True
        if len(token) < 4:
            return False
        stem = token[:5]
        return any(word[:5] == stem for word in words)
