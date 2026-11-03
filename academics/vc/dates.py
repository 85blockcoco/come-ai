"""Date and id helpers with an injectable clock."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta


def parse_date(value: str) -> date:
    """Parse an ISO date and raise a readable error."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"date attendue au format AAAA-MM-JJ : {value!r}") from error


def today_iso() -> str:
    return date.today().isoformat()


def add_days(value: str, days: int) -> str:
    return (parse_date(value) + timedelta(days=days)).isoformat()


def days_between(start: str, end: str) -> int:
    return (parse_date(end) - parse_date(start)).days


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def stable_id(prefix: str, *parts: object) -> str:
    """Build a short deterministic id from a prefix and parts."""
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:12]}"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
