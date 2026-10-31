"""Bounded read-only connector for German graduate/internship job boards (N100-A02)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

_DE_BASES = {
    "absolventa": "https://www.absolventa.de",
    "stepstone": "https://www.stepstone.de",
}

_MAX_ROWS = 200


@dataclass
class DEJob:
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    source: str = ""
    description: str = ""


def parse_absolventa_html(html: str, base: str = _DE_BASES["absolventa"]) -> list[DEJob]:
    jobs: list[DEJob] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{5,80})</a>', html):
        href, title = m.group(1), m.group(2).strip()
        if not any(k in title.lower() for k in ("praktikum", "trainee", "werkstudent", "absolvent")):
            continue
        jobs.append(DEJob(title=title, url=urljoin(base, href), source="absolventa"))
    return jobs[:_MAX_ROWS]


def parse_stepstone_html(html: str, base: str = _DE_BASES["stepstone"]) -> list[DEJob]:
    jobs: list[DEJob] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*job[^"]*"[^>]*>([^<]{5,80})</a>', html, re.I):
        href, title = m.group(1), m.group(2).strip()
        jobs.append(DEJob(title=title, url=urljoin(base, href), source="stepstone"))
    return jobs[:_MAX_ROWS]


def parse_de_html(html: str, source: str) -> list[DEJob]:
    source = (source or "").lower()
    if source == "absolventa":
        return parse_absolventa_html(html)
    if source == "stepstone":
        return parse_stepstone_html(html)
    return []


def to_dict(job: DEJob) -> dict[str, Any]:
    return asdict(job)