"""Duration detection for internships (N100-B02)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
           "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
           "janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
           "juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}


@dataclass
class DurationResult:
    months: int | None
    min_six_months: bool
    end_date: str | None


def parse_duration_months(text: str) -> int | None:
    t = (text or "").lower()
    m = re.search(r"(\d+)\s*[-]?\s*(?:month|mois|months)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:week|semaine)s?", t)
    if m:
        return max(1, int(m.group(1)) // 4)
    return None


def compute_end_date(start: str, months: int | None) -> str | None:
    if not months or not start:
        return None
    try:
        from datetime import datetime
        d = datetime.strptime(start[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    # approximate: add months*30 days
    end = d + timedelta(days=months * 30)
    return end.isoformat()


def detect_duration(text: str, start_date: str = "") -> DurationResult:
    months = parse_duration_months(text)
    min_six = (months is not None and months >= 6)
    end = compute_end_date(start_date, months)
    return DurationResult(months=months, min_six_months=min_six, end_date=end)