"""Offer freshness with TTL and re-verification queue (N100-A06).

An offer older than ``ttl_days`` is stale and must be re-verified before it
can be trusted.  Deterministic; ``today`` is injectable for tests.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass
from typing import Any, Iterable

DEFAULT_TTL_DAYS = 7


@dataclass
class FreshnessRow:
    job_id: str
    fetched_at: str | None
    age_days: int | None
    stale: bool
    needs_recheck: bool


def _parse(value: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def age_days(fetched_at: str, today: str | None = None) -> int | None:
    d = _parse(fetched_at)
    if d is None:
        return None
    today_d = _parse(today) if today else datetime.date.today()
    if today_d is None:
        return None
    return (today_d - d).days


def check_freshness(
    offers: Iterable[dict[str, Any]],
    *,
    fetched_key: str = "fetched_at",
    ttl_days: int = DEFAULT_TTL_DAYS,
    today: str | None = None,
) -> list[FreshnessRow]:
    rows: list[FreshnessRow] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        oid = str(offer.get("id") or offer.get("job_id") or "")
        fetched = offer.get(fetched_key)
        days = age_days(str(fetched or ""), today)
        stale = days is not None and days > ttl_days
        rows.append(
            FreshnessRow(
                job_id=oid,
                fetched_at=str(fetched or "") or None,
                age_days=days,
                stale=stale,
                needs_recheck=stale,
            )
        )
    return rows


def stale_offer_ids(rows: Iterable[FreshnessRow]) -> list[str]:
    return [r.job_id for r in rows if r.stale]


def to_dict(row: FreshnessRow) -> dict[str, Any]:
    return asdict(row)
