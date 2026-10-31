"""Bounded read-only connector for UK graduate/internship job boards (SPEC N100-A01).

Targets: Prospects, Gradcracker, TargetJobs.  No auth, no submission, bounded
fetch, honest User-Agent, respect 429.  Tests use synthetic fixtures only.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

_UK_BASES = {
    "prospects": "https://www.prospects.ac.uk",
    "gradcracker": "https://www.gradcracker.com",
    "targetjobs": "https://targetjobs.co.uk",
}

_UK_TIMEOUT = 15
_UK_MAX_ROWS = 200


@dataclass
class UKJob:
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    source: str = ""
    description: str = ""


def parse_prospects_html(html: str, base: str = _UK_BASES["prospects"]) -> list[UKJob]:
    jobs: list[UKJob] = []
    # Look for job cards: <article class="...job..."> or <li> with title link.
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{5,80})</a>', html):
        href, title = m.group(1), m.group(2).strip()
        if "/jobs/" not in href and "/search" not in href:
            continue
        if not any(k in title.lower() for k in ("intern", "graduate", "placement", "trainee")):
            continue
        jobs.append(UKJob(title=title, url=urljoin(base, href), source="prospects"))
    return jobs[:_UK_MAX_ROWS]


def parse_gradcracker_html(html: str, base: str = _UK_BASES["gradcracker"]) -> list[UKJob]:
    jobs: list[UKJob] = []
    for m in re.finditer(r'<a[^>]+href="([^"]*jobs/[^"]+)"[^>]*>([^<]{5,80})</a>', html):
        href, title = m.group(1), m.group(2).strip()
        jobs.append(UKJob(title=title, url=urljoin(base, href), source="gradcracker"))
    return jobs[:_UK_MAX_ROWS]


def parse_targetjobs_html(html: str, base: str = _UK_BASES["targetjobs"]) -> list[UKJob]:
    jobs: list[UKJob] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*job[^"]*"[^>]*>([^<]{5,80})</a>', html, re.I):
        href, title = m.group(1), m.group(2).strip()
        jobs.append(UKJob(title=title, url=urljoin(base, href), source="targetjobs"))
    return jobs[:_UK_MAX_ROWS]


def parse_uk_html(html: str, source: str) -> list[UKJob]:
    source = (source or "").lower()
    if source == "prospects":
        return parse_prospects_html(html)
    if source == "gradcracker":
        return parse_gradcracker_html(html)
    if source == "targetjobs":
        return parse_targetjobs_html(html)
    return []


def to_dict(job: UKJob) -> dict[str, Any]:
    return asdict(job)