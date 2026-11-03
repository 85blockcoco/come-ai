"""CV section parser (N100-D02)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CVSections:
    education: list[str] = field(default_factory=list)
    experience: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


_HEADERS = {
    "education": ["education", "formation", "études", "studies"],
    "experience": ["experience", "expérience", "work", "professional"],
    "skills": ["skills", "compétences", "technical"],
    "languages": ["languages", "langues"],
}


def _classify_header(line: str) -> str | None:
    low = line.lower().strip().rstrip(":")
    for section, keys in _HEADERS.items():
        if any(k in low for k in keys):
            return section
    return None


def parse_cv_sections(text: str) -> CVSections:
    sections = CVSections()
    current = "other"
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        sec = _classify_header(line)
        if sec is not None and len(line) < 40:
            current = sec
            continue
        getattr(sections, current).append(line)
    return sections


def to_dict(s: CVSections) -> dict[str, Any]:
    return asdict(s)