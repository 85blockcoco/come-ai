"""Bounded read-only connector for Spanish job boards (N100-A03)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

_ES_BASES = {"infojobs": "https://www.infojobs.net", "iefp": "https://www.iefp.pt"}


@dataclass
class ESJob:
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    source: str = ""
    description: str = ""


def parse_infojobs_html(html: str, base: str = _ES_BASES["infojobs"]) -> list[ESJob]:
    jobs: list[ESJob] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{5,80})</a>', html):
        href, title = m.group(1), m.group(2).strip()
        if not any(k in title.lower() for k in ("prácticas", "becario", "intern", "trainee")):
            continue
        jobs.append(ESJob(title=title, url=urljoin(base, href), source="infojobs"))
    return jobs[:200]


def parse_es_html(html: str, source: str) -> list[ESJob]:
    source = (source or "").lower()
    if source == "infojobs":
        return parse_infojobs_html(html)
    return []


def to_dict(job: ESJob) -> dict[str, Any]:
    return asdict(job)