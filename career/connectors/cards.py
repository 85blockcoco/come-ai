"""Reading of the attributes published by a job card.

Job boards publish one card per posting.  Besides the visible fields, a card
may carry the identifier and the timestamp of the posting in its own
attributes.  The attribute name is the name of the source field: it is
transmitted as published, never translated into a date the source did not
label as one.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..models import clean_text


MAX_CARD_ATTRIBUTES = 12
MAX_ATTRIBUTE_TEXT = 200
#: Name under which a ``<time datetime="...">`` element is transmitted.
TIME_ATTRIBUTE = "datetime"


def card_attributes(attrs: Iterable[tuple[str, str | None]]) -> dict[str, str]:
    """Return the bounded data attributes published by a card."""
    collected: dict[str, str] = {}
    for name, value in attrs:
        if not name.startswith("data-"):
            continue
        text = clean_text(value, limit=MAX_ATTRIBUTE_TEXT)
        if not text:
            continue
        collected[name] = text
        if len(collected) >= MAX_CARD_ATTRIBUTES:
            break
    return collected


def time_attribute(attrs: Iterable[tuple[str, str | None]]) -> str:
    """Return the timestamp published by a ``<time>`` element, if any."""
    for name, value in attrs:
        if name.lower() != "datetime":
            continue
        return clean_text(value, limit=80)
    return ""


def published_fields(card: dict[str, Any], attributes: dict[str, str] | None = None) -> dict[str, Any]:
    """Return the visible fields and the attributes of one card."""
    fields: dict[str, Any] = {
        "title": card.get("title"),
        "company": card.get("company"),
        "location": card.get("location"),
        "contract_type": card.get("contract_type"),
        "url": card.get("url"),
    }
    for name, value in (attributes or {}).items():
        fields[name] = value
    return fields


__all__ = ["MAX_CARD_ATTRIBUTES", "TIME_ATTRIBUTE", "card_attributes", "published_fields", "time_attribute"]
