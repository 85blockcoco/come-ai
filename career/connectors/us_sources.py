"""Bounded read-only connector for US internship job boards (N100-A04)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

_US_BASES = {"handshake": "https://app.joinhandshake.com", "usajobs": "https://www.usajobs.gov"}


@dataclass
class USJob:
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    source: str = ""
    description: str = ""


def parse_handshake_html(html: str, base: str = _US_BASES["handshake"]) -> list[USJob]:
    jobs: list[USJob] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{5,80})</a>', html):
        href, title = m.group(1), m.group(2).strip()
        if not any(k in title.lower() for k in ("intern", "internship", "co-op", "coop")):
            continue
        jobs.append(USJob(title=title, url=urljoin(base, href), source="handshake"))
    return jobs[:200]


def parse_us_html(html: str, source: str) -> list[USJob]:
    source = (source or "").lower()
    if source == "handshake":
        return parse_handshake_html(html)
    return []


def to_dict(job: USJob) -> dict[str, Any]:
    return asdict(job)