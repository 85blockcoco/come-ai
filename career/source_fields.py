"""Common contract for the material a connector transmits.

A connector reads a public feed and hands the published facts over unchanged:

* every structured value keeps the exact name of the field the source used
  (``greenhouse.first_published``, ``smartrecruiters.postedDate``…);
* the published description is transmitted as published;
* a contradiction between a structured value and the published text is
  preserved — both sides are reported, neither one is arbitrated.

Nothing in this module interprets an offer.  The dates are the business of
``offer_dates``, the prerequisites the business of ``offer_requirements`` and
the confidence in a source the business of ``source_trust``.  A connector that
would have to decide here is a connector that hides a decision.

The module is pure: no network, no clock, no database, no model.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

from .models import clean_text


#: Payload key holding the transmitted source fields.
CONTRACT_KEY = "source_fields"
#: Payload key holding the contradictions kept between source and description.
CONFLICTS_KEY = "source_conflicts"

MAX_SOURCE_FIELDS = 40
MAX_FIELD_TEXT = 4_000
MAX_COLLECTION_ITEMS = 25
MAX_NESTED_FIELDS = 25
MAX_DEPTH = 3

_PROVIDER = re.compile(r"^[a-z0-9_]{1,40}$")


def _bounded_value(value: Any, depth: int = 0) -> Any:
    """Return a JSON-safe, bounded copy of one published value.

    Empty values are dropped: an absent field is not a fact.  The shape of a
    published value is never rewritten, only bounded.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return clean_text(value, limit=MAX_FIELD_TEXT) or None
    if depth >= MAX_DEPTH:
        return None
    if isinstance(value, (list, tuple)):
        items: list[Any] = []
        for item in list(value)[:MAX_COLLECTION_ITEMS]:
            bounded = _bounded_value(item, depth + 1)
            if bounded is None or bounded == [] or bounded == {}:
                continue
            items.append(bounded)
        return items
    if isinstance(value, Mapping):
        fields: dict[str, Any] = {}
        for key, item in list(value.items())[:MAX_NESTED_FIELDS]:
            name = clean_text(key, limit=80)
            if not name:
                continue
            bounded = _bounded_value(item, depth + 1)
            if bounded is None or bounded == [] or bounded == {}:
                continue
            fields[name] = bounded
        return fields
    return None


def collect_source_fields(provider: str, fields: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the published fields of one provider, each under its source name.

    The result is ``{provider: {source_field_name: published_value}}``.  The
    name of a field is never translated, renamed or merged: a consumer can
    always tell which field of which source produced a value.
    """
    name = clean_text(provider, limit=40).lower()
    if not _PROVIDER.match(name):
        raise ValueError("provider name is invalid")
    if not isinstance(fields, Mapping):
        raise TypeError("source fields must be a mapping")
    collected: dict[str, Any] = {}
    for raw_name, raw_value in list(fields.items())[:MAX_SOURCE_FIELDS]:
        field_name = clean_text(raw_name, limit=80)
        if not field_name:
            continue
        bounded = _bounded_value(raw_value)
        if bounded is None or bounded == [] or bounded == {}:
            continue
        collected[field_name] = bounded
    return {name: collected}


def source_fields_of(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Read the transmitted block back without trusting a malformed payload."""
    if not isinstance(payload, Mapping):
        return {}
    block = payload.get(CONTRACT_KEY)
    if not isinstance(block, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for provider, fields in block.items():
        provider_name = clean_text(provider, limit=40).lower()
        if not provider_name or not isinstance(fields, Mapping):
            continue
        result[provider_name] = {
            clean_text(field, limit=80): value
            for field, value in list(fields.items())[:MAX_SOURCE_FIELDS]
            if clean_text(field, limit=80)
        }
    return result


# Contradictions are reported between a structured value and the text, never
# between two interpretations of the same text.  The vocabulary is explicit and
# small: an unknown wording is not a contradiction.
_CONTRACT_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("permanent", re.compile(r"\b(?:cdi|permanent|permanent\s+contract|contrat\s+permanent)\b", re.I)),
    ("fixed_term", re.compile(r"\b(?:cdd|fixed[-\s]term|contrat\s+(?:durée\s+fixe|déterminé)|temporary)\b", re.I)),
    ("internship", re.compile(
        r"\b(?:intern|internship|internships|stagiaire|stages?|alternance|alternant|apprentice|"
        r"apprenticeship|working\s+student|praktikum)\b", re.I)),
)
_DURATION = re.compile(r"(?<![\d.,])\b(\d{1,2})\s*-?\s*(?:mois|months?|semaines?|semestres?)\b", re.I)
#: Name of a published field that carries the contract type.
_CONTRACT_FIELD = re.compile(
    r"(?:employment|contract|commitment|contrat|type_of_employment|typeOfEmployment)", re.I
)


def _published_contract_type(fields: Mapping[str, Any]) -> tuple[str, str]:
    """Return the contract type published by the source, with its field name.

    The published field is looked up, never rewritten: a board that publishes
    ``categories.commitment``, ``employmentType``, ``typeOfEmployment`` or
    ``contract_type`` keeps its own name in the transmitted contract.
    """
    for key, value in fields.items():
        if _CONTRACT_FIELD.search(key):
            if isinstance(value, str) and value.strip():
                return key, value
            if isinstance(value, Mapping):
                for sub_key, sub_value in value.items():
                    if _CONTRACT_FIELD.search(sub_key) and isinstance(sub_value, str) and sub_value.strip():
                        return f"{key}.{sub_key}", sub_value
                for label_key in ("label", "name", "value"):
                    label = value.get(label_key)
                    if isinstance(label, str) and label.strip():
                        return key, label
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, Mapping):
                    continue
                name = item.get("name")
                if not isinstance(name, str) or not _CONTRACT_FIELD.search(name):
                    continue
                label = item.get("value")
                if isinstance(label, str) and label.strip():
                    return key, label
    return "", ""


def _contract_kind(value: str) -> str:
    for kind, pattern in _CONTRACT_MARKERS:
        if pattern.search(value):
            return kind
    return ""


def _excerpt(text: str, start: int, end: int) -> str:
    left = max(0, start - 60)
    right = min(len(text), end + 60)
    return clean_text(text[left:right], limit=240)


def detect_source_conflicts(
    job: Mapping[str, Any],
    description: Any,
    *,
    source_fields: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the contradictions between the structured fields and the text.

    Both sides are reported: the structured value and the wording found in the
    description.  The detector never decides which one is true — it only makes
    the disagreement visible, so that a later layer (dates, requirements,
    trust) can reason about it with the source wording in hand.
    """
    text = clean_text(description, limit=30_000)
    conflicts: list[dict[str, Any]] = []
    if not text:
        return conflicts

    structured_contract = clean_text(job.get("employment_type"), limit=120)
    contract_field = "employment_type"
    if not structured_contract and source_fields:
        contract_field, published = _published_contract_type(source_fields)
        structured_contract = clean_text(published, limit=120)
    if structured_contract:
        source_kind = _contract_kind(structured_contract)
        if source_kind:
            for kind, pattern in _CONTRACT_MARKERS:
                if kind == source_kind:
                    continue
                found = pattern.search(text)
                if not found:
                    continue
                conflicts.append({
                    "kind": "contract",
                    "field": "employment_type",
                    "source_field": contract_field,
                    "source_value": structured_contract,
                    "description_value": clean_text(found.group(0), limit=80),
                    "quote": _excerpt(text, found.start(), found.end()),
                })
                break

    duration = job.get("duration_months")
    if isinstance(duration, int) and not isinstance(duration, bool) and duration > 0:
        for found in _DURATION.finditer(text):
            stated = int(found.group(1))
            if stated == duration:
                continue
            conflicts.append({
                "kind": "duration",
                "field": "duration_months",
                "source_value": duration,
                "description_value": clean_text(found.group(0), limit=40),
                "quote": _excerpt(text, found.start(), found.end()),
            })
            break
    return conflicts


def attach_source_material(
    job: Mapping[str, Any],
    provider: str,
    fields: Mapping[str, Any],
    *,
    description: Any = None,
) -> dict[str, Any]:
    """Return the offer enriched with the material published by its source.

    The canonical fields of the offer are left untouched: the source wording
    is added next to them, never instead of them.
    """
    enriched = dict(job)
    published = collect_source_fields(provider, fields)
    enriched[CONTRACT_KEY] = published
    text = description if description is not None else enriched.get("description_original", "")
    enriched[CONFLICTS_KEY] = detect_source_conflicts(
        enriched, text, source_fields=published.get(clean_text(provider, limit=40).lower(), {})
    )
    return enriched


__all__ = [
    "CONFLICTS_KEY",
    "CONTRACT_KEY",
    "attach_source_material",
    "collect_source_fields",
    "detect_source_conflicts",
    "source_fields_of",
]
