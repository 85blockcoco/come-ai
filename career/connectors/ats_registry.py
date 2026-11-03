"""ATS platform detection from a career URL (SPEC-038).

Closed, versioned list of known ATS signatures.  No network, no auth.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass
class AtsPlatform:
    name: str
    signature: str
    confidence: float = 1.0


# Ordered by specificity: more specific signatures first.
_SIGNATURES: list[tuple[str, str]] = [
    ("myworkdayjobs.com", "workday"),
    ("workday.com", "workday"),
    ("successfactors", "successfactors"),
    ("greenhouse.io", "greenhouse"),
    ("boards-api.greenhouse.io", "greenhouse"),
    ("taleo.net", "taleo"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("api.smartrecruiters.com", "smartrecruiters"),
    ("camejobs.com", "cameo"),
    ("aplica.ai", "aplica"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
]


def detect_ats(url: str) -> AtsPlatform:
    """Detect the ATS platform of a career URL.  Returns ``unknown`` if no
    signature matches."""
    if not url:
        return AtsPlatform(name="unknown", signature="", confidence=0.0)
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
        haystack = host + path
    except Exception:
        haystack = str(url).lower()
    for sig, name in _SIGNATURES:
        if sig in haystack:
            return AtsPlatform(name=name, signature=sig, confidence=1.0)
    return AtsPlatform(name="unknown", signature="", confidence=0.0)


def load_banks_list(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load the versioned list of banks (name, ats, career_url)."""
    if path is None:
        path = Path(__file__).resolve().parent / "banks_list.json"
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("banks", []))
    return []


def ats_for_bank(bank: dict[str, Any]) -> AtsPlatform:
    """Detect ATS from a bank record's career_url."""
    return detect_ats(str(bank.get("career_url") or bank.get("url") or ""))


def to_dict(p: AtsPlatform) -> dict[str, Any]:
    return asdict(p)