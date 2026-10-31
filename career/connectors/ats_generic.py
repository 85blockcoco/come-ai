"""Generic ATS page fetcher + structured-data parser (SPEC-038).

Bounded, read-only: fetches public HTML, extracts JSON-LD / embedded JSON
when present, and returns a normalized dict (title, location, department,
description, url).  No auth, no submission, honors 429 with backoff.
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from .ats_registry import detect_ats

MAX_BYTES = 4 * 1024 * 1024
TIMEOUT = 10
USER_AGENT = "Come-AI-Career/3.2 (local reader of published job postings)"
RATE_LIMIT_SECONDS = 1.0
_LAST_REQUEST = 0.0


@dataclass
class AtsJob:
    title: str = ""
    location: str = ""
    department: str = ""
    description: str = ""
    url: str = ""
    platform: str = "unknown"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi  # noqa: PLC0415
        ctx = ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    return ctx


def _rate_limit() -> None:
    global _LAST_REQUEST
    now = time.time()
    if now - _LAST_REQUEST < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - (now - _LAST_REQUEST))
    _LAST_REQUEST = time.time()


def fetch_html(url: str) -> str:
    """Fetch public HTML with bounds.  Raises on 429 after backoff."""
    _rate_limit()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("invalid scheme")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as resp:
            body = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            time.sleep(2.0)
            raise
        raise
    if len(body) > MAX_BYTES:
        body = body[:MAX_BYTES]
    return body.decode("utf-8", errors="replace")


def _extract_jsonld(html: str) -> dict[str, Any] | None:
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") in ("JobPosting", "jobPosting"):
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") in ("JobPosting", "jobPosting"):
                    return item
    return None


def _extract_embedded_json(html: str, marker: str) -> dict[str, Any] | None:
    idx = html.find(marker)
    if idx < 0:
        return None
    start = html.find("{", idx)
    if start < 0:
        return None
    depth = 0
    for i in range(start, min(start + 200000, len(html))):
        ch = html[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def parse_job(html: str, url: str = "") -> AtsJob:
    """Parse a job posting from HTML.  Uses JSON-LD first, then embedded JSON."""
    job = AtsJob(url=url, platform=detect_ats(url).name)
    ld = _extract_jsonld(html)
    if ld:
        job.title = str(ld.get("title") or "")
        loc = ld.get("jobLocation")
        if isinstance(loc, dict):
            addr = loc.get("address", {})
            if isinstance(addr, dict):
                job.location = ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressCountry")) if x)
        elif isinstance(loc, list) and loc:
            addr = loc[0].get("address", {}) if isinstance(loc[0], dict) else {}
            if isinstance(addr, dict):
                job.location = ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressCountry")) if x)
        job.department = str(ld.get("occupationalCategory") or ld.get("department") or "")
        desc = ld.get("description")
        if isinstance(desc, str):
            job.description = desc
        elif isinstance(desc, dict):
            job.description = str(desc.get("text") or "")
        return job

    # Greenhouse public board JSON: boards-api.greenhouse.io/v1/boards/.../jobs/...
    gh = _extract_embedded_json(html, "boards-api.greenhouse.io")
    if gh and isinstance(gh, dict) and gh.get("title"):
        job.title = str(gh.get("title") or "")
        loc = gh.get("location")
        if isinstance(loc, dict):
            job.location = str(loc.get("name") or "")
        job.department = str((gh.get("departments") or [{}])[0].get("name") or "") if isinstance(gh.get("departments"), list) else ""
        job.description = str(gh.get("content") or "")
        return job

    # SmartRecruiters
    sr = _extract_embedded_json(html, "smartrecruiters.com")
    if sr and isinstance(sr, dict) and sr.get("name"):
        job.title = str(sr.get("name") or "")
        loc = sr.get("location") or {}
        if isinstance(loc, dict):
            job.location = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
        job.department = str((sr.get("department") or {}).get("label") or "")
        job.description = str(sr.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text") or "")
        return job

    # Fallback: title tag + meta description
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        job.title = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, re.S | re.I)
    if m:
        job.description = m.group(1).strip()
    return job


def parse_job_from_url(url: str) -> AtsJob:
    html = fetch_html(url)
    return parse_job(html, url)


def to_dict(job: AtsJob) -> dict[str, Any]:
    return asdict(job)