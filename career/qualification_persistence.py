"""Safe persistence helpers for deterministic offer qualification snapshots.

Qualification is derived metadata, not a replacement for source fields.  This
module therefore stores a bounded snapshot beside the job instead of turning a
month-only observation into an invented exact date or overwriting user edits.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import clean_text


SNAPSHOT_SCHEMA_VERSION = 1
_FACT_FIELDS = (
    "contract_type",
    "contract_status",
    "posted_date",
    "start_date",
    "end_date",
    "start_month",
    "duration_min_months",
    "duration_max_months",
    "language",
    "country",
    "city",
    "geography_status",
    "source_name",
    "source_id",
    "official_url",
    "verification_status",
    "target_status",
    "temporal_facts",
    "source_provenance",
    "source_conflicts",
    "dedup_reasons",
)


def _bounded_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        # A list of quoted facts (missions, SK-18) is persisted as readable
        # text, never as a Python repr.
        return "\n".join(
            clean_text(item, limit=300) for item in value if clean_text(item, limit=300)
        )[:2_000]
    return clean_text(value, limit=2_000)


def _bounded_temporal_facts(value: Any) -> list[dict[str, Any]]:
    """Keep a bounded, allow-listed copy of temporal evidence from offer text."""
    if not isinstance(value, (list, tuple)):
        return []
    allowed = {
        "fact_type", "value", "precision", "source_field", "quote", "start_offset",
        "end_offset", "confidence", "contradictions", "fact_id", "lang",
    }
    facts: list[dict[str, Any]] = []
    for item in value[:200]:
        if not isinstance(item, dict):
            continue
        bounded: dict[str, Any] = {}
        for key in allowed:
            raw = item.get(key)
            if key == "value" and isinstance(raw, dict):
                bounded[key] = {
                    clean_text(name, limit=80): _bounded_scalar(field_value)
                    for name, field_value in list(raw.items())[:8]
                    if isinstance(name, str)
                }
            elif key == "contradictions" and isinstance(raw, (list, tuple)):
                bounded[key] = [clean_text(entry, limit=200) for entry in raw[:40] if isinstance(entry, str)]
            elif key in {"start_offset", "end_offset"}:
                bounded[key] = raw if type(raw) is int and raw >= 0 else 0
            elif key in {"fact_type", "precision", "source_field", "quote", "confidence", "fact_id", "lang"}:
                bounded[key] = clean_text(raw, limit=1_000 if key == "quote" else 160)
        if bounded.get("fact_type") and bounded.get("quote"):
            facts.append(bounded)
    return facts


def _bounded_source_provenance(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    fields = ("source_name", "source_id", "official_url", "trust", "is_representative")
    result = []
    for item in value[:25]:
        if not isinstance(item, dict):
            continue
        result.append({
            key: (bool(item.get(key)) if key == "is_representative" else clean_text(item.get(key), limit=2_000 if key == "official_url" else 240))
            for key in fields
        })
    return result


def _bounded_source_conflicts(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for field, entries in list(value.items())[:20]:
        if not isinstance(entries, dict):
            continue
        result[clean_text(field, limit=80)] = {
            clean_text(source, limit=160): clean_text(text, limit=300)
            for source, text in list(entries.items())[:10]
        }
    return result


def normalize_qualification_snapshot(
    qualification: dict[str, Any], source_payload: dict[str, Any]
) -> dict[str, Any]:
    """Return a bounded, JSON-safe snapshot with field-level provenance."""
    if not isinstance(qualification, dict):
        raise TypeError("qualification must be an object")

    facts: dict[str, Any] = {}
    for field in _FACT_FIELDS:
        value = qualification.get(field)
        if field == "temporal_facts":
            temporal = _bounded_temporal_facts(value)
            if temporal:
                facts[field] = temporal
        elif field == "source_provenance":
            provenance_items = _bounded_source_provenance(value)
            if provenance_items:
                facts[field] = provenance_items
        elif field == "source_conflicts":
            conflicts = _bounded_source_conflicts(value)
            if conflicts:
                facts[field] = conflicts
        elif field == "dedup_reasons":
            if isinstance(value, (list, tuple)):
                reasons = [clean_text(item, limit=200) for item in value[:20]]
                if reasons:
                    facts[field] = [item for item in reasons if item]
        elif value not in (None, ""):
            facts[field] = _bounded_scalar(value)
    raw_provenance = qualification.get("provenance")
    provenance: dict[str, dict[str, Any]] = {}
    if isinstance(raw_provenance, dict):
        for field, evidence in raw_provenance.items():
            if not isinstance(field, str) or not isinstance(evidence, dict):
                continue
            source = clean_text(evidence.get("source"), limit=160)
            quote = clean_text(evidence.get("quote"), limit=1_000)
            if not source:
                continue
            provenance[clean_text(field, limit=120)] = {
                "value": _bounded_scalar(evidence.get("value")),
                "source": source,
                "quote": quote,
            }

    missing = qualification.get("missing_fields")
    missing_fields = [clean_text(item, limit=160) for item in missing] if isinstance(missing, (list, tuple)) else []
    missing_fields = [item for item in missing_fields if item]
    reasons = qualification.get("reasons")
    reason_items = [clean_text(item, limit=500) for item in reasons] if isinstance(reasons, (list, tuple)) else []
    reason_items = [item for item in reason_items if item]

    source_identity = {
        "source_name": clean_text(source_payload.get("source_name"), limit=120),
        "source_id": clean_text(source_payload.get("source_id"), limit=240),
        "official_url": clean_text(source_payload.get("official_url"), limit=2_000),
        "description_sha256": hashlib.sha256(
            clean_text(source_payload.get("description_original"), limit=30_000).encode("utf-8")
        ).hexdigest(),
    }
    fingerprint = hashlib.sha256(
        json.dumps(source_identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "facts_json": json.dumps(facts, ensure_ascii=False, sort_keys=True),
        "provenance_json": json.dumps(provenance, ensure_ascii=False, sort_keys=True),
        "missing_fields_json": json.dumps(missing_fields, ensure_ascii=False),
        "reasons_json": json.dumps(reason_items, ensure_ascii=False),
        "source_fingerprint": fingerprint,
    }


def decode_qualification_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Decode a joined database snapshot without trusting malformed JSON."""
    if row.get("qualification_schema_version") is None:
        return {}
    try:
        facts = json.loads(row.get("qualification_facts_json") or "{}")
        provenance = json.loads(row.get("qualification_provenance_json") or "{}")
        missing = json.loads(row.get("qualification_missing_json") or "[]")
        reasons = json.loads(row.get("qualification_reasons_json") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(facts, dict) or not isinstance(provenance, dict):
        return {}
    return {
        **facts,
        "provenance": provenance,
        "missing_fields": missing if isinstance(missing, list) else [],
        "reasons": reasons if isinstance(reasons, list) else [],
        "source_fingerprint": clean_text(row.get("qualification_source_fingerprint"), limit=64),
        "qualified_at": clean_text(row.get("qualification_updated_at"), limit=40),
        "snapshot_schema_version": row.get("qualification_schema_version"),
    }


def snapshot_matches_current_source(job: dict[str, Any]) -> bool:
    """Return whether a decoded snapshot still describes the current source.

    The comparison deliberately excludes editable notes and derived ranking.
    A source refresh changing its identity, URL or description invalidates the
    old verification instead of silently carrying trust to different text.
    """
    snapshot = job.get("qualification_facts")
    if not isinstance(snapshot, dict):
        return False
    expected = clean_text(snapshot.get("source_fingerprint"), limit=64)
    if not expected:
        return False
    current = normalize_qualification_snapshot({}, job)["source_fingerprint"]
    return expected == current
