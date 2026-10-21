"""Unique versioned offer-intelligence snapshot (SPEC SK-07 / CVBOOST-28).

WHAT THIS MODULE IS
Every Career screen used to recompute its own idea of an offer: the explorer
showed a deadline column, the detailed view showed another one, the matching
panel showed a third.  This module builds **one** snapshot per offer and per
source-content fingerprint.  Every consumer (explorer, detailed view, matching,
CV preparation, cover letter, application checklist) reads that snapshot, so a
requirement keeps the same identifier everywhere.

WHAT THE SNAPSHOT CONTAINS
- ``temporal_facts``    — publication, deadline, start, end and duration facts
                          (reused from :mod:`career.offer_dates`, SPEC SK-02).
- ``requirements``      — the canonical prerequisite records with their stable
                          identifiers (reused from
                          :mod:`career.offer_requirements`).
- ``qualifications``    — the contractual qualification of the offer
                          (:mod:`career.offer_qualification`).
- ``trust``             — the explicit trust decision on the official link
                          (reused from :mod:`career.source_trust`, SPEC SK-01).
- ``geo`` / ``lang``    — location and language facts.
- ``contradictions``    — conflicting evidences, kept side by side.
- ``missing``           — what is *not* known, always phrased "à vérifier".
- ``source_hash``       — the fingerprint of the exact source text used.
- ``provenance_map``    — for every fact, the passage (quote + offsets) it
                          comes from.

RULES
- Pure and deterministic: no clock (unless one is injected), no randomness, no
  network, no model.  The same offer always yields the same snapshot and the
  same identifiers.
- Nothing is invented: a confirmed fact always resolves to a source passage
  with its offsets.  A month-only statement never becomes an exact day, a
  deadline never becomes a start date, an upper bound never becomes a minimum.
- Missing stays missing, but it is phrased "à vérifier" — never "absente" and
  never silently dropped.
- The snapshot never contains candidate-profile data: it describes the offer,
  not the person.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from .models import clean_text, normalized_text

SCHEMA_VERSION = 1

# Fields of the source that can change a derived fact.  User state (note,
# shortlist, application stage) is deliberately absent: it never invalidates an
# analysis and it is never touched by a re-import.
SOURCE_FIELDS: tuple[str, ...] = (
    "title",
    "company",
    "source_name",
    "source_id",
    "official_url",
    "description_original",
    "requirements",
    "languages_required",
    "eligibility_requirement",
    "role_level",
    "employment_type",
    "posted_date",
    "deadline_date",
    "start_date",
    "end_date",
    "duration_months",
    "city",
    "country",
)

TEMPORAL_KINDS: tuple[str, ...] = ("publication", "deadline", "start", "end", "duration")
PRECISIONS: tuple[str, ...] = ("exact_date", "month", "year", "range", "bound", "unknown")
CONFIDENCE_STATES: tuple[str, ...] = ("confirmed", "ambiguous", "contradicted", "unknown")

SOURCE_KINDS: tuple[str, ...] = ("official_field", "official_text", "public_enrichment")

# Source-attributed qualification facts kept in the snapshot.  A field that
# depends on the person's own criteria or on the current day is deliberately
# absent: it must never create a new version of the analysis.
QUALIFICATION_FIELDS: tuple[str, ...] = (
    "contract_type",
    "contract_status",
    "posted_date",
    "start_date",
    "end_date",
    "duration_min_months",
    "duration_max_months",
    "language",
    "country",
    "city",
    "source_name",
    "source_id",
    "official_url",
    "verification_status",
)

# The evidence and the unknown fields of the contractual qualification.  They
# describe the offer, never the person, so they belong to the snapshot: every
# qualification fact resolves to a passage instead of floating without proof.
QUALIFICATION_EVIDENCE_FIELDS: tuple[str, ...] = ("provenance", "missing_fields")

MAX_FACTS = 200
MAX_REQUIREMENTS = 200
MAX_MISSING = 40
MAX_CONTRADICTIONS = 40
MAX_QUOTE = 400


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _digest(*parts: str) -> str:
    return _sha256("|".join(parts))


def _bounded(value: Any, limit: int = MAX_QUOTE) -> str:
    return clean_text(value, limit=limit)


# --------------------------------------------------------------------- models


@dataclass(frozen=True)
class Evidence:
    """Where a fact comes from: the field, the passage and its exact offsets."""

    source_kind: str
    source_id: str
    source_field: str
    locator: str
    quote: str
    start_offset: int | None = None
    end_offset: int | None = None
    retrieved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "source_field": self.source_field,
            "locator": self.locator,
            "quote": self.quote,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "retrieved_at": self.retrieved_at,
        }


@dataclass(frozen=True)
class TemporalFact:
    """One dated statement, with its bound and its confidence state."""

    id: str
    kind: str
    precision: str
    value: str | None
    lower_bound: str | None
    upper_bound: str | None
    confidence_state: str
    source_fact_id: str
    evidence: Evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "precision": self.precision,
            "value": self.value,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "confidence_state": self.confidence_state,
            "source_fact_id": self.source_fact_id,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class Requirement:
    """One prerequisite, with the canonical identifier used by every screen."""

    id: str
    text: str
    source_field: str
    locator: str
    category: str
    modality: str
    confidence: float
    negated: bool
    injection_suspect: bool
    evidence: Evidence
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source_field": self.source_field,
            "locator": self.locator,
            "category": self.category,
            "modality": self.modality,
            "confidence": self.confidence,
            "negated": self.negated,
            "injection_suspect": self.injection_suspect,
            "notes": list(self.notes),
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class Contradiction:
    """Two evidences that cannot both be true; neither one is arbitrated."""

    id: str
    topic: str
    kind: str
    left: dict[str, Any]
    right: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "kind": self.kind,
            "left": self.left,
            "right": self.right,
        }


@dataclass(frozen=True)
class MissingInformation:
    """Something the source does not prove; the answer stays "à vérifier"."""

    id: str
    field: str
    label: str
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "field": self.field,
            "label": self.label,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OfferIntelligenceSnapshot:
    """The versioned derived analysis of one offer for one source fingerprint."""

    job_id: str
    schema_version: int
    source_hash: str
    temporal_facts: tuple[TemporalFact, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()
    missing: tuple[MissingInformation, ...] = ()
    qualifications: Mapping[str, Any] = field(default_factory=dict)
    trust: Mapping[str, Any] = field(default_factory=dict)
    geo: Mapping[str, Any] = field(default_factory=dict)
    lang: Mapping[str, Any] = field(default_factory=dict)
    provenance_map: Mapping[str, Evidence] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    created_at: str | None = None
    updated_at: str | None = None

    # -- accessors ---------------------------------------------------------
    @property
    def source_fingerprint(self) -> str:
        """Alias kept for the existing qualification snapshot vocabulary."""
        return self.source_hash

    def requirement(self, requirement_id: str) -> Requirement | None:
        for record in self.requirements:
            if record.id == requirement_id:
                return record
        return None

    def fact(self, fact_id: str) -> TemporalFact | None:
        for record in self.temporal_facts:
            if record.id == fact_id:
                return record
        return None

    def requirement_ids(self) -> tuple[str, ...]:
        return tuple(record.id for record in self.requirements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "schema_version": self.schema_version,
            "source_hash": self.source_hash,
            "source_fingerprint": self.source_hash,
            "temporal_facts": [record.to_dict() for record in self.temporal_facts],
            "requirements": [record.to_dict() for record in self.requirements],
            "contradictions": [record.to_dict() for record in self.contradictions],
            "missing": [record.to_dict() for record in self.missing],
            "qualifications": dict(self.qualifications),
            "trust": dict(self.trust),
            "geo": dict(self.geo),
            "lang": dict(self.lang),
            "provenance_map": {
                key: value.to_dict() for key, value in self.provenance_map.items()
            },
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OfferIntelligenceSnapshot":
        """Rebuild a snapshot from its stored JSON representation."""
        data = payload if isinstance(payload, Mapping) else {}

        def _evidence(raw: Any) -> Evidence:
            block = raw if isinstance(raw, Mapping) else {}
            return Evidence(
                source_kind=str(block.get("source_kind") or "official_text"),
                source_id=str(block.get("source_id") or ""),
                source_field=str(block.get("source_field") or ""),
                locator=str(block.get("locator") or ""),
                quote=str(block.get("quote") or ""),
                start_offset=block.get("start_offset"),
                end_offset=block.get("end_offset"),
                retrieved_at=block.get("retrieved_at"),
            )

        facts = tuple(
            TemporalFact(
                id=str(item.get("id") or ""),
                kind=str(item.get("kind") or "unknown"),
                precision=str(item.get("precision") or "unknown"),
                value=item.get("value"),
                lower_bound=item.get("lower_bound"),
                upper_bound=item.get("upper_bound"),
                confidence_state=str(item.get("confidence_state") or "unknown"),
                source_fact_id=str(item.get("source_fact_id") or ""),
                evidence=_evidence(item.get("evidence")),
            )
            for item in data.get("temporal_facts") or []
            if isinstance(item, Mapping)
        )
        requirements = tuple(
            Requirement(
                id=str(item.get("id") or ""),
                text=str(item.get("text") or ""),
                source_field=str(item.get("source_field") or ""),
                locator=str(item.get("locator") or ""),
                category=str(item.get("category") or "other"),
                modality=str(item.get("modality") or "unknown"),
                confidence=float(item.get("confidence") or 0.0),
                negated=bool(item.get("negated")),
                injection_suspect=bool(item.get("injection_suspect")),
                notes=tuple(str(note) for note in item.get("notes") or []),
                evidence=_evidence(item.get("evidence")),
            )
            for item in data.get("requirements") or []
            if isinstance(item, Mapping)
        )
        contradictions = tuple(
            Contradiction(
                id=str(item.get("id") or ""),
                topic=str(item.get("topic") or ""),
                kind=str(item.get("kind") or ""),
                left=dict(item.get("left") or {}),
                right=dict(item.get("right") or {}),
            )
            for item in data.get("contradictions") or []
            if isinstance(item, Mapping)
        )
        missing = tuple(
            MissingInformation(
                id=str(item.get("id") or ""),
                field=str(item.get("field") or ""),
                label=str(item.get("label") or ""),
                status=str(item.get("status") or "to_verify"),
                reason=str(item.get("reason") or ""),
            )
            for item in data.get("missing") or []
            if isinstance(item, Mapping)
        )
        provenance = {
            str(key): _evidence(value)
            for key, value in (data.get("provenance_map") or {}).items()
            if isinstance(value, Mapping)
        }
        return cls(
            job_id=str(data.get("job_id") or ""),
            schema_version=int(data.get("schema_version") or SCHEMA_VERSION),
            source_hash=str(data.get("source_hash") or ""),
            temporal_facts=facts,
            requirements=requirements,
            contradictions=contradictions,
            missing=missing,
            qualifications=dict(data.get("qualifications") or {}),
            trust=dict(data.get("trust") or {}),
            geo=dict(data.get("geo") or {}),
            lang=dict(data.get("lang") or {}),
            provenance_map=provenance,
            warnings=tuple(str(item) for item in data.get("warnings") or []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# ------------------------------------------------------------------ helpers


def _source_text(value: Any) -> str:
    """Return the exact source text of one field, without truncating it.

    The fingerprint must cover the whole passage: a change beyond a
    truncation boundary is still a change, and a stale analysis must never
    survive it.
    """
    if isinstance(value, str):
        return value.replace("\x00", "").strip()
    return clean_text(value, limit=1_000_000)


def compute_source_hash(offer: Mapping[str, Any]) -> str:
    """Return the stable fingerprint of the exact source content of an offer.

    Only source fields participate: a personal note, a shortlist flag or an
    application stage never invalidates an analysis.  The whole text is
    hashed — not only the part the analyzers read — so that any change of the
    source really produces a new analysis: nothing is cut, so an edit is
    always visible.
    """
    payload = {}
    for name in SOURCE_FIELDS:
        value = offer.get(name)
        if value is None:
            continue
        if isinstance(value, (int, float, bool)):
            payload[name] = value
        else:
            payload[name] = _source_text(value)
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _source_kind(source_field: str) -> str:
    """Structured fields are official data, free text is an official passage."""
    return "official_field" if source_field in _STRUCTURED_SOURCE_FIELDS else "official_text"


_STRUCTURED_SOURCE_FIELDS: frozenset[str] = frozenset(
    {
        "requirements",
        "languages_required",
        "eligibility_requirement",
        "role_level",
        "deadline_date",
        "posted_date",
        "start_date",
        "end_date",
        "duration_months",
        "country",
        "city",
        "title",
        "company",
        "employment_type",
        "official_url",
    }
)


def _offsets(source_text: str, quote: str) -> tuple[int | None, int | None]:
    """Return the exact offsets of ``quote`` inside ``source_text``."""
    if not source_text or not quote:
        return None, None
    position = source_text.find(quote)
    if position < 0:
        return None, None
    return position, position + len(quote)


def _iso_date(value: Mapping[str, Any]) -> str | None:
    """Render a date fact without ever inventing a day."""
    year = value.get("year")
    month = value.get("month")
    day = value.get("day")
    if not isinstance(year, int) or not isinstance(month, int):
        return None
    if isinstance(day, int):
        return f"{year:04d}-{month:02d}-{day:02d}"
    return f"{year:04d}-{month:02d}"


def _year_only(value: Mapping[str, Any]) -> str | None:
    year = value.get("year")
    if not isinstance(year, int):
        return None
    return f"{year:04d}"


def _date_value(value: Mapping[str, Any], precision: str) -> str | None:
    if precision == "exact_date":
        return _iso_date(value)
    if precision == "month":
        return _iso_date(value)
    if precision == "year":
        return _year_only(value)
    return None


def _duration_bounds(fact_type: str, value: Mapping[str, Any]) -> tuple[str | None, str | None]:
    minimum = value.get("months_min")
    maximum = value.get("months_max")
    low = f"{minimum}" if isinstance(minimum, int) else None
    high = f"{maximum}" if isinstance(maximum, int) else None
    if fact_type == "duration_exact":
        return low, high
    if fact_type == "duration_min":
        return low, None
    if fact_type == "duration_max":
        return None, high
    return low, high


def _duration_precision(fact_type: str) -> str:
    """A duration is never a date: it is an interval or a single bound."""
    if fact_type in {"duration_exact", "duration_range"}:
        return "range"
    return "bound"


def _fact_kind(fact_type: str) -> str:
    """Map a fact type of the temporal analyzer to the vocabulary of a snapshot."""
    if fact_type == "published":
        return "publication"
    if fact_type in {"deadline", "start", "end"}:
        return fact_type
    if fact_type.startswith("duration"):
        return "duration"
    return "unknown"


def _precision(fact_type: str, precision: str) -> str:
    if fact_type.startswith("duration"):
        return _duration_precision(fact_type)
    return {"day": "exact_date", "month": "month", "year": "year"}.get(precision, "unknown")


def _confidence_state(confidence: str, contradicted: bool) -> str:
    if contradicted:
        return "contradicted"
    if confidence == "confirmed":
        return "confirmed"
    if confidence in {"inferred", "ambiguous"}:
        return "ambiguous"
    return "unknown"


# --------------------------------------------------------------- extraction


def _extract_temporal_facts(
    offer: Mapping[str, Any], source_id: str
) -> tuple[list[TemporalFact], dict[str, tuple[str, ...]]]:
    """Read the dated statements of an offer (reuses SPEC SK-02)."""
    try:
        from .offer_dates import extract_offer_dates
    except ImportError:  # pragma: no cover - the analyzer is part of the product
        return [], {}

    facts: list[TemporalFact] = []
    links: dict[str, tuple[str, ...]] = {}
    try:
        raw_facts = extract_offer_dates(dict(offer))
    except (TypeError, ValueError):
        return [], {}

    for raw in raw_facts[:MAX_FACTS]:
        payload = raw.to_dict() if hasattr(raw, "to_dict") else dict(raw)
        fact_type = str(payload.get("fact_type") or "")
        kind = _fact_kind(fact_type)
        if kind not in TEMPORAL_KINDS:
            continue
        source_field = str(payload.get("source_field") or "")
        quote = _bounded(payload.get("quote"))
        value = payload.get("value") if isinstance(payload.get("value"), Mapping) else {}
        precision = _precision(fact_type, str(payload.get("precision") or "unknown"))
        contradictions = payload.get("contradictions") or []
        confidence_state = _confidence_state(
            str(payload.get("confidence") or "unknown"), bool(contradictions)
        )
        links[str(payload.get("fact_id") or "")] = tuple(
            str(item) for item in contradictions if isinstance(item, str)
        )
        if kind == "duration":
            lower, upper = _duration_bounds(fact_type, value)
            canonical_value = lower if (lower is not None and lower == upper) else None
        else:
            lower = upper = None
            canonical_value = _date_value(value, precision)
        identifier = "tf_" + _digest(
            kind, source_field, canonical_value or lower or upper or "", quote
        )[:16]
        evidence = Evidence(
            source_kind=_source_kind(source_field),
            source_id=source_id,
            source_field=source_field,
            locator=f"offset:{payload.get('start_offset')}:{payload.get('end_offset')}",
            quote=quote,
            start_offset=payload.get("start_offset"),
            end_offset=payload.get("end_offset"),
            retrieved_at=None,
        )
        facts.append(
            TemporalFact(
                id=identifier,
                kind=kind,
                precision=precision,
                value=canonical_value,
                lower_bound=lower,
                upper_bound=upper,
                confidence_state=confidence_state,
                source_fact_id=str(payload.get("fact_id") or ""),
                evidence=evidence,
            )
        )
    return facts, links


def _requirement_evidence(
    offer: Mapping[str, Any], record: Mapping[str, Any], source_id: str
) -> Evidence:
    """Return the verbatim passage and the offsets of one requirement."""
    source_field = str(record.get("source_field") or "")
    locator = str(record.get("locator") or "")
    text = _bounded(record.get("text"))
    try:
        from .offer_requirements import resolve_locator
    except ImportError:  # pragma: no cover - the contract is part of the product
        resolve_locator = None  # type: ignore[assignment]

    passage = ""
    if resolve_locator is not None:
        try:
            passage = _bounded(resolve_locator(dict(offer), source_field, locator))
        except (TypeError, ValueError):
            passage = ""
    if not passage:
        passage = text
    raw_field = offer.get(source_field)
    raw_text = raw_field if isinstance(raw_field, str) else ""
    start, end = _offsets(raw_text, text)
    quote = text
    if start is None:
        # The statement is not a verbatim slice of the raw field (HTML was
        # removed, for instance): the whole source line is then cited, and no
        # offset is claimed because none can be proven.
        quote = passage or text
        start, end = _offsets(raw_text, quote)
    return Evidence(
        source_kind=_source_kind(source_field),
        source_id=source_id,
        source_field=source_field,
        locator=locator,
        quote=quote,
        start_offset=start,
        end_offset=end,
        retrieved_at=None,
    )


def _extract_requirements(
    offer: Mapping[str, Any], source_id: str
) -> tuple[list[Requirement], list[dict[str, Any]], list[str], list[str], bool]:
    """Read the canonical prerequisite records (reuses the SK-02/SK-03 contract)."""
    try:
        from .offer_requirements import analyze_offer
    except ImportError:  # pragma: no cover - the contract is part of the product
        return [], [], [], [], False

    try:
        analysis = analyze_offer(dict(offer))
    except (TypeError, ValueError):
        return [], [], [], [], False

    records: list[Requirement] = []
    for item in (analysis.get("requirements") or [])[:MAX_REQUIREMENTS]:
        if not isinstance(item, Mapping):
            continue
        identifier = str(item.get("id") or "")
        if not identifier:
            continue
        records.append(
            Requirement(
                id=identifier,
                text=_bounded(item.get("text")),
                source_field=str(item.get("source_field") or ""),
                locator=str(item.get("locator") or ""),
                category=str(item.get("category") or "other"),
                modality=str(item.get("modality") or "unknown"),
                confidence=float(item.get("confidence") or 0.0),
                negated=bool(item.get("negated")),
                injection_suspect=bool(item.get("injection_suspect")),
                notes=tuple(str(note) for note in item.get("notes") or []),
                evidence=_requirement_evidence(offer, item, source_id),
            )
        )
    contradictions = [item for item in analysis.get("contradictions") or [] if isinstance(item, Mapping)]
    warnings = [str(item) for item in analysis.get("warnings") or []]
    suspects = [str(item) for item in analysis.get("injection_suspects") or []]
    truncated = bool(analysis.get("truncated"))
    return records, contradictions, warnings, suspects, truncated


def _temporal_contradictions(
    offer: Mapping[str, Any],
    facts: Iterable[TemporalFact],
    links: Mapping[str, tuple[str, ...]],
) -> list[Contradiction]:
    """Pair the temporal facts that cannot both be true.

    The pairing comes from the temporal analyzer itself (SPEC SK-02) and is
    completed by a value comparison, so a conflict stated by the source and a
    conflict deduced from two incompatible values are both visible.

    A coarser statement is **not** a contradiction: "January 2026" and
    "2026-01-15" describe the same period, and "six months" is compatible
    with "up to six months".  Only two statements that cannot both be true
    are reported, and a given pair is reported once.
    """
    facts = list(facts)
    by_source_id = {fact.source_fact_id: fact for fact in facts if fact.source_fact_id}
    seen: set[tuple[str, str]] = set()
    contradictions: list[Contradiction] = []

    def _topic(left: TemporalFact, right: TemporalFact) -> str:
        if left.kind == right.kind:
            return left.kind
        return f"{left.kind}/{right.kind}"

    def _register(
        left_key: str,
        right_key: str,
        topic: str,
        kind: str,
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> None:
        pair = tuple(sorted((left_key, right_key)))
        if pair in seen:
            return
        seen.add(pair)
        contradictions.append(
            Contradiction(
                id="ctr_" + _digest(pair[0], pair[1])[:16],
                topic=topic,
                kind=kind,
                left=left,
                right=right,
            )
        )

    for fact in facts:
        for other_id in links.get(fact.source_fact_id, ()):  # conflicts stated by the analyzer
            other = by_source_id.get(other_id)
            if other is not None and other.id != fact.id:
                _register(
                    fact.id,
                    other.id,
                    _topic(fact, other),
                    "temporal_conflict",
                    _fact_side(fact),
                    _fact_side(other),
                )
    for fact in facts:
        for other in facts:
            if other.id == fact.id:
                continue
            if _facts_conflict(fact, other):
                _register(
                    fact.id,
                    other.id,
                    _topic(fact, other),
                    "temporal_conflict",
                    _fact_side(fact),
                    _fact_side(other),
                )
    _structured_vs_text_contradictions(offer, facts, register=_register)
    return contradictions[:MAX_CONTRADICTIONS]


def _fact_side(fact: TemporalFact) -> dict[str, Any]:
    return {
        "fact_id": fact.id,
        "kind": fact.kind,
        "value": fact.value,
        "lower_bound": fact.lower_bound,
        "upper_bound": fact.upper_bound,
        "precision": fact.precision,
        "confidence_state": fact.confidence_state,
        "quote": fact.evidence.quote,
        "source_field": fact.evidence.source_field,
    }


def _date_interval(value: str | None, precision: str) -> tuple[str | None, str | None]:
    """Return the interval a date value proves, at the precision it carries.

    A month-only statement covers its whole month: it is compatible with every
    day of that month and it contradicts another month.  An unknown value
    proves nothing and contradicts nothing.
    """
    if not value:
        return None, None
    if precision == "exact_date" and len(value) == 10:
        return value, value
    if precision == "month" and len(value) == 7:
        return f"{value}-01", f"{value}-31"
    if precision == "year" and len(value) == 4:
        return f"{value}-01-01", f"{value}-12-31"
    return None, None


def _infer_date_interval(value: str | None) -> tuple[str | None, str | None]:
    """Return the interval a structured date proves, whatever its precision.

    Only the canonical shapes are understood: a value that is not a date
    (``"15/11/2026"``, ``"soon"``…) proves nothing, so a malformed field can
    never invent a contradiction.
    """
    text = _bounded(value, limit=40).strip()
    if _ISO_DATE.match(text):
        return _date_interval(text, "exact_date")
    if _ISO_MONTH.match(text):
        return _date_interval(text, "month")
    if _ISO_YEAR.match(text):
        return _date_interval(text, "year")
    return None, None


def _duration_interval(fact: TemporalFact) -> tuple[int | None, int | None]:
    """Return the proven bounds of a duration; a missing bound stays unbounded."""
    lower = int(fact.lower_bound) if str(fact.lower_bound or "").isdigit() else None
    upper = int(fact.upper_bound) if str(fact.upper_bound or "").isdigit() else None
    return lower, upper


def _intervals_conflict(
    left: tuple[Any, Any], right: tuple[Any, Any]
) -> bool:
    """Tell whether two proven intervals cannot both hold.

    An interval that proves nothing (``None, None``) contradicts nothing: an
    unknown value stays unknown instead of becoming an invented conflict.  A
    single missing bound means "unbounded" on that side, which is how an upper
    bound ("up to six months") stays compatible with an exact duration.
    """
    left_min, left_max = left
    right_min, right_max = right
    if (left_min is None and left_max is None) or (right_min is None and right_max is None):
        return False
    if left_max is not None and right_min is not None and left_max < right_min:
        return True
    if right_max is not None and left_min is not None and right_max < left_min:
        return True
    return False


def _facts_conflict(left: TemporalFact, right: TemporalFact) -> bool:
    """Two facts conflict when their proven intervals cannot both hold.

    The comparison is done on the intervals, not on the raw strings: a
    month-only statement and the exact day it contains agree, and an upper
    bound and the duration it allows agree too.  Only genuinely incompatible
    statements are exposed as a contradiction.
    """
    if left.kind != right.kind:
        return False
    if left.kind == "duration":
        return _intervals_conflict(_duration_interval(left), _duration_interval(right))
    return _intervals_conflict(
        _date_interval(left.value, left.precision),
        _date_interval(right.value, right.precision),
    )


def _requirement_contradictions(
    raw_contradictions: Iterable[Mapping[str, Any]]
) -> list[Contradiction]:
    """Keep the structured-versus-description contradictions of the contract."""
    contradictions: list[Contradiction] = []
    for item in raw_contradictions:
        structured = item.get("structured") if isinstance(item.get("structured"), Mapping) else {}
        described = item.get("described") if isinstance(item.get("described"), Mapping) else {}
        left_id = str(structured.get("id") or "")
        right_id = str(described.get("id") or "")
        if not left_id or not right_id:
            continue
        contradictions.append(
            Contradiction(
                id="ctr_" + _digest(left_id, right_id)[:16],
                topic=str(item.get("topic") or "requirement"),
                kind=str(item.get("kind") or "structured_vs_description"),
                left={
                    "requirement_id": left_id,
                    "text": _bounded(structured.get("text")),
                    "source_field": str(structured.get("source_field") or ""),
                    "modality": str(structured.get("modality") or ""),
                },
                right={
                    "requirement_id": right_id,
                    "text": _bounded(described.get("text")),
                    "source_field": str(described.get("source_field") or ""),
                    "modality": str(described.get("modality") or ""),
                },
            )
        )
    return contradictions[:MAX_CONTRADICTIONS]


_STRUCTURED_DATE_FIELDS: dict[str, str] = {
    "posted_date": "publication",
    "deadline_date": "deadline",
    "start_date": "start",
    "end_date": "end",
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")
_ISO_YEAR = re.compile(r"^\d{4}$")


def _structured_vs_text_contradictions(
    offer: Mapping[str, Any],
    facts: Iterable[TemporalFact],
    *,
    register: Callable[[str, str, str, str, dict[str, Any], dict[str, Any]], None],
) -> None:
    """Compare the structured dates of the offer with the dates of its text.

    The comparison respects the precision of each side: a structured day and a
    month-only sentence about the same month agree, only genuinely different
    dates are exposed as a contradiction.

    The comparison writes into the shared registry: a clash already reported
    between two facts is never reported a second time.
    """
    facts = list(facts)
    for name, kind in _STRUCTURED_DATE_FIELDS.items():
        raw = offer.get(name)
        if not isinstance(raw, str) or not raw.strip():
            continue
        structured_value = _bounded(raw, limit=40).strip()
        structured_interval = _infer_date_interval(structured_value)
        if structured_interval == (None, None):
            # A value that is not a date proves nothing: it can never invent
            # a contradiction.
            continue
        for fact in facts:
            if fact.kind != kind:
                continue
            if fact.evidence.source_field == name:
                continue
            fact_interval = _date_interval(fact.value, fact.precision)
            if not _intervals_conflict(structured_interval, fact_interval):
                continue
            anchor = next(
                (
                    other.id
                    for other in facts
                    if other.kind == kind and other.evidence.source_field == name
                ),
                f"field:{name}",
            )
            register(
                anchor,
                fact.id,
                kind,
                "structured_vs_description",
                {
                    "source_field": name,
                    "value": structured_value,
                    "quote": _bounded(raw),
                    "confidence_state": "confirmed",
                },
                _fact_side(fact),
            )


def _geo_fact(offer: Mapping[str, Any], source_id: str) -> dict[str, Any]:
    """Read the location of the offer; an unknown place stays "à vérifier"."""
    country = _bounded(offer.get("country"), limit=120)
    city = _bounded(offer.get("city"), limit=160)
    if country or city:
        status = "known"
        reason = "Localisation fournie par la source."
    else:
        status = "to_verify"
        reason = "Aucune ville ni pays dans la source : la localisation reste à vérifier."
    geo_field = "country" if country else ("city" if city else "")
    geo_quote = country or city
    start, end = _offsets(str(offer.get(geo_field) or ""), geo_quote) if geo_field else (None, None)
    return {
        "country": country or None,
        "city": city or None,
        "status": status,
        "reason": reason,
        "source_field": geo_field,
        "evidence": {
            "source_kind": "official_field" if geo_field else "official_text",
            "source_id": source_id,
            "source_field": geo_field,
            "locator": f"field:{geo_field}" if geo_field else "",
            "quote": geo_quote,
            "start_offset": start,
            "end_offset": end,
        },
    }


def _lang_fact(
    offer: Mapping[str, Any], requirements: Iterable[Requirement], source_id: str
) -> dict[str, Any]:
    """Read the language facts of the offer from the canonical requirements."""
    language_ids = [
        record.id for record in requirements if record.category == "language"
    ]
    structured = _bounded(offer.get("languages_required"), limit=2_000)
    declared = _bounded(offer.get("language"), limit=40)
    if language_ids or structured:
        status = "known"
        reason = "Les langues exigées sont citées par la source."
    else:
        status = "to_verify"
        reason = "Aucune langue exigée dans la source : les langues restent à vérifier."
    return {
        "required": structured or None,
        "declared": declared or None,
        "status": status,
        "reason": reason,
        "requirement_ids": language_ids,
        "source_field": "languages_required" if structured else "",
        "evidence": {
            "source_kind": "official_field" if structured else "official_text",
            "source_id": source_id,
            "source_field": "languages_required" if structured else "",
            "locator": "field:languages_required" if structured else "",
            "quote": structured,
            "start_offset": _offsets(str(offer.get("languages_required") or ""), structured)[0]
            if structured
            else None,
            "end_offset": _offsets(str(offer.get("languages_required") or ""), structured)[1]
            if structured
            else None,
        },
    }


def _trust_fact(
    offer: Mapping[str, Any],
    *,
    clock: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Read the trust decision of the official link (reuses SPEC SK-01).

    The decision itself never reads a clock.  The stamp is only filled when
    the caller injects one: an unstamped snapshot stays reproducible, so two
    builds of the same offer always yield the very same document.
    """
    try:
        from .source_trust import check_trust
    except ImportError:  # pragma: no cover - the contract is part of the product
        return {"status": "missing", "reasons": ["Le contrat de confiance n’est pas disponible."], "checked_at": None}
    url = _bounded(offer.get("official_url"), limit=2_000)
    stamp = clock() if clock is not None else None
    try:
        result = check_trust(
            url,
            employer_hint=_bounded(offer.get("company"), limit=200) or None,
            declared_provider=_bounded(offer.get("source_name"), limit=60) or None,
            clock=(lambda: stamp) if stamp is not None else (lambda: ""),
        )
    except (TypeError, ValueError):
        return {"status": "missing", "reasons": ["La confiance de la source n’a pas pu être établie."], "checked_at": None}
    payload = dict(result.to_dict())
    payload["checked_at"] = stamp
    return payload


def _missing_information(
    offer: Mapping[str, Any],
    facts: Iterable[TemporalFact],
    requirements: Iterable[Requirement],
    qualifications: Mapping[str, Any],
    trust: Mapping[str, Any],
) -> list[MissingInformation]:
    """List what the source does not prove; every entry stays "à vérifier"."""
    kinds = {fact.kind for fact in facts}
    categories = {record.category for record in requirements}
    missing: list[MissingInformation] = []

    def _add(field: str, label: str, reason: str) -> None:
        if len(missing) >= MAX_MISSING:
            return
        missing.append(
            MissingInformation(
                id="mis_" + _digest(field, label)[:16],
                field=field,
                label=label,
                status="to_verify",
                reason=reason,
            )
        )

    if "deadline" not in kinds:
        _add(
            "deadline_date",
            "Date limite de candidature",
            "Aucune date limite n’est prouvée par la source : à vérifier sur la page officielle.",
        )
    if "start" not in kinds:
        _add(
            "start_date",
            "Date de début",
            "Aucune date de début n’est prouvée par la source : à vérifier.",
        )
    if "duration" not in kinds:
        _add(
            "duration_months",
            "Durée du contrat",
            "Aucune durée n’est prouvée par la source : à vérifier.",
        )
    if "publication" not in kinds:
        _add(
            "posted_date",
            "Date de publication",
            "Aucune date de publication n’est prouvée par la source : à vérifier.",
        )
    if not _bounded(offer.get("city")) and not _bounded(offer.get("country")):
        _add(
            "location",
            "Localisation",
            "Ni ville ni pays dans la source : la localisation reste à vérifier.",
        )
    if not requirements:
        _add(
            "requirements",
            "Prérequis",
            "Aucun prérequis n’est cité par la source : les prérequis restent à vérifier.",
        )
    elif not categories & {"education", "work_authorization", "mobility"}:
        _add(
            "requirements",
            "Prérequis structurants",
            "Aucun prérequis de formation, d’autorisation de travail ou de mobilité n’est cité : à vérifier.",
        )
    if "language" not in categories:
        _add(
            "languages_required",
            "Langues requises",
            "Aucune langue exigée n’est citée par la source : à vérifier.",
        )
    contract_type = str(qualifications.get("contract_type") or "unknown")
    if contract_type in {"", "unknown"}:
        _add(
            "contract_type",
            "Type de contrat",
            "Le type de contrat n’est pas établi par la source : à vérifier.",
        )
    if str(trust.get("status") or "missing") != "verified":
        _add(
            "official_url",
            "Source officielle",
            "Le lien officiel n’est pas vérifié localement : la source reste à vérifier.",
        )
    return missing


def build_snapshot(
    offer_raw: Mapping[str, Any],
    qualified_data: Mapping[str, Any] | None = None,
    *,
    clock: Callable[[], str] | None = None,
    trust_clock: Callable[[], str] | None = None,
) -> OfferIntelligenceSnapshot:
    """Build the versioned intelligence snapshot of one offer.

    ``offer_raw`` is the stored offer.  ``qualified_data`` is the contractual
    qualification already computed for that offer (the result of
    :func:`career.offer_qualification.qualify_offer`); when it is missing the
    qualification block stays empty instead of being guessed.

    The function is pure: the offer is never modified, no clock is read unless
    one is injected, and no network call is ever made.
    """
    offer = dict(offer_raw or {})
    job_id = _bounded(offer.get("id"), limit=80)
    source_id = _bounded(offer.get("source_id"), limit=240) or _bounded(
        offer.get("source_name"), limit=120
    )
    source_hash = compute_source_hash(offer)

    facts, temporal_links = _extract_temporal_facts(offer, source_id)
    requirements, raw_contradictions, warnings, suspects, truncated = _extract_requirements(offer, source_id)
    trust = _trust_fact(offer, clock=trust_clock or clock)

    qualifications: dict[str, Any] = {}
    if isinstance(qualified_data, Mapping):
        # Only the source-attributed, time-independent facts are kept.  A
        # status that depends on the person's own criteria (target status,
        # geographic admissibility) belongs to the matching layer: it must not
        # create a new version of the analysis when a preference changes.
        qualifications = {
            key: qualified_data.get(key)
            for key in QUALIFICATION_FIELDS
            if key in qualified_data
        }
        # The evidence of the qualification travels with it: a contractual fact
        # without a passage would be a fact nobody can check.
        provenance = qualified_data.get("provenance")
        if isinstance(provenance, Mapping):
            qualifications["provenance"] = {
                str(name): dict(block)
                for name, block in provenance.items()
                if isinstance(block, Mapping)
            }
        missing_fields = qualified_data.get("missing_fields")
        if isinstance(missing_fields, (list, tuple)):
            qualifications["missing_fields"] = [str(item) for item in missing_fields]

    contradictions = _temporal_contradictions(offer, facts, temporal_links)
    contradictions.extend(_requirement_contradictions(raw_contradictions))

    geo = _geo_fact(offer, source_id)
    lang = _lang_fact(offer, requirements, source_id)
    missing = _missing_information(offer, facts, requirements, qualifications, trust)

    provenance: dict[str, Evidence] = {}
    for fact in facts:
        provenance[fact.id] = fact.evidence
    for record in requirements:
        provenance[record.id] = record.evidence

    all_warnings = list(warnings)
    if truncated and not any("tronqu" in warning for warning in all_warnings):
        all_warnings.append(
            "Le texte de l’offre est tronqué : la liste des exigences peut être incomplète."
        )
    if suspects and not any("instruction" in warning for warning in all_warnings):
        all_warnings.append(
            "Un passage de l’offre tente de donner des instructions au programme de lecture : "
            "il reste affiché tel quel, traité comme donnée, jamais exécuté."
        )

    now = clock() if clock is not None else None
    return OfferIntelligenceSnapshot(
        job_id=job_id,
        schema_version=SCHEMA_VERSION,
        source_hash=source_hash,
        temporal_facts=tuple(facts),
        requirements=tuple(requirements),
        contradictions=tuple(contradictions[:MAX_CONTRADICTIONS]),
        missing=tuple(missing),
        qualifications=qualifications,
        trust=trust,
        geo=geo,
        lang=lang,
        provenance_map=provenance,
        warnings=tuple(all_warnings),
        created_at=now,
        updated_at=now,
    )


# ------------------------------------------------------------------ summary


def snapshot_summary(snapshot: OfferIntelligenceSnapshot | Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact view of a snapshot used by the explorer list.

    The identifiers are the very same ones as in the detailed view: the list
    never recomputes a requirement, it only points at the snapshot.
    """
    if isinstance(snapshot, OfferIntelligenceSnapshot):
        payload = snapshot.to_dict()
    else:
        payload = dict(snapshot or {})

    requirements = payload.get("requirements") or []
    facts = payload.get("temporal_facts") or []
    return {
        "job_id": payload.get("job_id"),
        "schema_version": payload.get("schema_version"),
        "source_hash": payload.get("source_hash"),
        "requirement_ids": [str(item.get("id")) for item in requirements if isinstance(item, Mapping)],
        "temporal_fact_ids": [str(item.get("id")) for item in facts if isinstance(item, Mapping)],
        "requirements_total": len(requirements),
        "temporal_facts_total": len(facts),
        "contradictions_total": len(payload.get("contradictions") or []),
        "missing_total": len(payload.get("missing") or []),
        "missing_fields": [
            str(item.get("field"))
            for item in payload.get("missing") or []
            if isinstance(item, Mapping)
        ],
        "to_verify": [
            str(item.get("label"))
            for item in payload.get("missing") or []
            if isinstance(item, Mapping)
        ],
        "trust_status": str((payload.get("trust") or {}).get("status") or "missing"),
        "geo_status": str((payload.get("geo") or {}).get("status") or "to_verify"),
        "lang_status": str((payload.get("lang") or {}).get("status") or "to_verify"),
        "contract_status": str((payload.get("qualifications") or {}).get("contract_status") or ""),
        "contract_type": str((payload.get("qualifications") or {}).get("contract_type") or ""),
    }


def requirement_index(snapshot: OfferIntelligenceSnapshot | Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the ``identifier -> requirement`` index of a snapshot."""
    if isinstance(snapshot, OfferIntelligenceSnapshot):
        payload = snapshot.to_dict()
    else:
        payload = dict(snapshot or {})
    index: dict[str, dict[str, Any]] = {}
    for item in payload.get("requirements") or []:
        if not isinstance(item, Mapping):
            continue
        identifier = str(item.get("id") or "")
        if identifier:
            index[identifier] = dict(item)
    return index


def align_display_requirements(
    display_requirements: Iterable[Mapping[str, Any]],
    snapshot: OfferIntelligenceSnapshot | Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Attach the canonical identifier to already displayed requirements.

    The alignment is textual and deterministic: the displayed statement is
    matched with the canonical record that carries the same normalized text.
    A displayed statement without a canonical counterpart keeps a null
    identifier — it is never given an invented one.
    """
    index = requirement_index(snapshot)
    by_text: dict[str, str] = {}
    for identifier, record in index.items():
        key = normalized_text(str(record.get("text") or ""))
        if key and key not in by_text:
            by_text[key] = identifier
    aligned: list[dict[str, Any]] = []
    for item in display_requirements:
        entry = dict(item)
        key = normalized_text(str(entry.get("text") or ""))
        entry["requirement_id"] = by_text.get(key)
        aligned.append(entry)
    return aligned


__all__ = [
    "CONFIDENCE_STATES",
    "Contradiction",
    "Evidence",
    "MissingInformation",
    "OfferIntelligenceSnapshot",
    "PRECISIONS",
    "Requirement",
    "SCHEMA_VERSION",
    "SOURCE_FIELDS",
    "SOURCE_KINDS",
    "TEMPORAL_KINDS",
    "TemporalFact",
    "align_display_requirements",
    "build_snapshot",
    "compute_source_hash",
    "requirement_index",
    "snapshot_summary",
]
