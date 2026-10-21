"""Deterministic, local-only extraction for CV and exported profile text.

This module is deliberately independent from any LLM, HTTP client, or social
network integration.  It extracts only information explicitly present in a
document or pasted text and leaves the user in control of applying it to the
Career profile.

The parser is intentionally conservative: it recognises a handful of common
French and English headings, plus contact details written in the source.  It
never tries to infer eligibility, nationality, visa status, age, availability,
or any other sensitive attribute.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


# These are the only profile fields an imported document can suggest.  Keeping
# the list explicit prevents a future caller from accidentally applying an
# arbitrary column from an untrusted document to the local profile.
PROFILE_IMPORT_FIELDS: tuple[str, ...] = (
    "display_name",
    "contact_email",
    "contact_phone",
    "linkedin_url",
    "education",
    "experience",
    "skills",
    "languages",
)

# ``linkedin_text`` is for text the user deliberately pasted.  The application
# must not fetch, sign into, or scrape LinkedIn on the user's behalf.
PROFILE_IMPORT_KINDS: set[str] = {
    "cv",
    "linkedin_export",
    "linkedin_text",
    "profile_document",
}

ALLOWED_PROFILE_SUFFIXES: set[str] = {".pdf", ".docx", ".txt", ".md"}

# A Career import is intentionally smaller than the generic document workspace
# upload limit.  The router must enforce this while streaming the upload too;
# this value is kept here so the UI/service/tests share one contract.
MAX_PROFILE_IMPORT_BYTES = 10 * 1024 * 1024
MAX_PROFILE_TEXT_CHARS = 100_000


_FIELD_LIMITS: dict[str, int] = {
    "display_name": 120,
    "contact_email": 320,
    "contact_phone": 80,
    "linkedin_url": 500,
    "education": 5_000,
    "experience": 6_000,
    "skills": 3_000,
    "languages": 1_500,
}

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "education": (
        "formation",
        "formations",
        "education",
        "educations",
        "etudes",
        "parcours academique",
        "academic background",
        "academic education",
        "qualifications",
        "diplomes",
        "diploma",
        "diplomas",
        "degrees",
        "studies",
    ),
    "experience": (
        "experience",
        "experiences",
        "experience professionnelle",
        "experiences professionnelles",
        "parcours professionnel",
        "professional experience",
        "professional experiences",
        "work experience",
        "work history",
        "employment history",
        "career history",
        "professional background",
    ),
    "skills": (
        "competences",
        "competence",
        "competences techniques",
        "competence technique",
        "competences cles",
        "skills",
        "technical skills",
        "key skills",
        "core skills",
        "competencies",
        "expertise",
    ),
    "languages": (
        "langues",
        "langue",
        "languages",
        "language skills",
        "linguistic skills",
    ),
}

# Public vocabulary of section headings.  The structured profile builder
# (``career.profile_builder``) recognises the same French and English headings,
# so both parsers agree on where a section starts without duplicating a list.
PROFILE_SECTION_ALIASES: dict[str, tuple[str, ...]] = _SECTION_ALIASES


def normalise_heading(value: str) -> str:
    """Normalise a possible heading without changing the extracted value."""
    return _normalise_heading(value)


_NAME_STOP_WORDS = {
    "academic",
    "analyst",
    "analyste",
    "bachelor",
    "career",
    "competence",
    "competences",
    "consultant",
    "contact",
    "curriculum",
    "cv",
    "education",
    "email",
    "ecole",
    "experience",
    "finance",
    "formation",
    "intern",
    "langue",
    "langues",
    "languages",
    "linkedin",
    "master",
    "mobile",
    "parcours",
    "profile",
    "profil",
    "resume",
    "school",
    "skills",
    "stagiaire",
    "student",
    "telephone",
    "tel",
    "university",
    "universite",
    "vitae",
}

_EMAIL_RE = re.compile(
    r"(?<![\w.!#$%&'*+/=?^`{|}~-])"
    r"([A-Z0-9][A-Z0-9.!#$%&'*+/=?^_`{|}~-]{0,63}"
    r"@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+)"
    r"(?![\w.-])",
    re.IGNORECASE,
)

# Deliberately broad enough for common French/international representations,
# with follow-up checks to reject date ranges and implausible digit counts.
_PHONE_RE = re.compile(r"(?<![\w+])(?:\+|00)?\s*(?:\(?\d{1,4}\)?[\s.\-]*){2,8}\d(?!\w)")
_YEAR_RANGE_RE = re.compile(r"\b(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)\d{2}\b")

_LINKEDIN_URL_RE = re.compile(
    r"(?i)(?:https?://)?(?:(?:[a-z]{2,3}|www)\.)?linkedin\.com/"
    r"(?:in|pub)/[a-z0-9%._~-]+(?:/[a-z0-9%._~-]+)*(?:[?#][^\s<>()\[\]{}\"']*)?"
)


def _safe_text(value: object, *, limit: int = MAX_PROFILE_TEXT_CHARS) -> tuple[str, bool]:
    """Return display-safe source text and whether it had to be truncated."""
    if isinstance(value, str):
        raw = value
    elif value is None:
        raw = ""
    else:
        raw = str(value)

    raw = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    # Preserve newlines and tabs, but discard other control characters.  This
    # avoids surprising terminal/UI behaviour from text extracted from a file.
    raw = "".join(character if character in {"\n", "\t"} or ord(character) >= 32 else " " for character in raw)
    truncated = len(raw) > limit
    return raw[:limit], truncated


def _normalise_heading(value: str) -> str:
    """Normalise a possible heading without changing the extracted value."""
    text = unicodedata.normalize("NFKD", value).lower()
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"^[\s#>*•·\-–—]+", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_FIELD_BY_HEADING: dict[str, str] = {
    _normalise_heading(alias): field
    for field, aliases in _SECTION_ALIASES.items()
    for alias in aliases
}


def _clean_line(value: str) -> str:
    """Compact whitespace inside one source line while preserving its wording."""
    return re.sub(r"[ \t]+", " ", value.strip())


def _section_marker(line: str) -> tuple[str, str] | None:
    """Return a recognised field and possible same-line content for a heading."""
    candidate = _clean_line(line)
    if not candidate:
        return None
    field = _FIELD_BY_HEADING.get(_normalise_heading(candidate))
    if field:
        return field, ""

    # ``Compétences : Python, Excel`` and its English equivalent are common in
    # one-page CVs.  An em dash/en dash is also used by some PDF exporters.
    for separator in (":", "—", "–"):
        if separator not in candidate:
            continue
        label, inline_value = candidate.split(separator, 1)
        field = _FIELD_BY_HEADING.get(_normalise_heading(label))
        if field:
            return field, _clean_line(inline_value)
    return None


def _compact_section(lines: Iterable[str], *, limit: int) -> str:
    """Keep readable lines/bullets, remove only empty/repeated whitespace."""
    result: list[str] = []
    previous_blank = False
    for source_line in lines:
        line = _clean_line(source_line)
        if not line:
            if result and not previous_blank:
                result.append("")
            previous_blank = True
            continue
        if result and result[-1] == line:
            continue
        result.append(line)
        previous_blank = False

    compacted = "\n".join(result).strip()
    return compacted[:limit].rstrip()


def _section_values(lines: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Extract text lying explicitly below recognised French/English headings."""
    markers: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        marked = _section_marker(line)
        if marked is not None:
            field, inline_value = marked
            markers.append((index, field, inline_value))

    values = {field: "" for field in ("education", "experience", "skills", "languages")}
    evidence: dict[str, list[str]] = {}
    for position, (start, field, inline_value) in enumerate(markers):
        end = markers[position + 1][0] if position + 1 < len(markers) else len(lines)
        content_lines: list[str] = []
        if inline_value:
            content_lines.append(inline_value)
        content_lines.extend(lines[start + 1 : end])
        extracted = _compact_section(content_lines, limit=_FIELD_LIMITS[field])
        if not extracted:
            continue

        existing = values[field]
        separator = "\n\n" if existing else ""
        values[field] = (existing + separator + extracted)[: _FIELD_LIMITS[field]].rstrip()
        _append_evidence(evidence, field, lines[start])
        _append_evidence(evidence, field, extracted)
    return values, evidence


def _append_evidence(evidence: dict[str, list[str]], field: str, value: str) -> None:
    """Retain short provenance hints; never retain a full unbounded document."""
    compacted = re.sub(r"\s+", " ", value).strip()
    if not compacted:
        return
    compacted = compacted[:360].rstrip()
    entries = evidence.setdefault(field, [])
    if compacted not in entries and len(entries) < 3:
        entries.append(compacted)


def _extract_email(text: str) -> str:
    for match in _EMAIL_RE.finditer(text):
        candidate = match.group(1).strip(".,;:!?<>()[]{}\"'").lower()
        if len(candidate) <= _FIELD_LIMITS["contact_email"]:
            return candidate
    return ""


def _looks_like_year_range(value: str) -> bool:
    return bool(_YEAR_RANGE_RE.fullmatch(value.strip()))


def _extract_phone(text: str) -> str:
    for match in _PHONE_RE.finditer(text):
        candidate = re.sub(r"\s+", " ", match.group(0)).strip(" .-–—")
        digits = re.sub(r"\D", "", candidate)
        if not 7 <= len(digits) <= 15:
            continue
        if _looks_like_year_range(candidate):
            continue
        # A run of a single repeated digit is much more likely to be a fake
        # placeholder than contact information.
        if len(set(digits)) == 1:
            continue
        return candidate[: _FIELD_LIMITS["contact_phone"]]
    return ""


def _normalise_linkedin_url(value: str) -> str:
    """Return a public LinkedIn profile URL without tracking/query fragments."""
    candidate = value.strip().rstrip(".,;:!?)]}>\"'")
    if not candidate:
        return ""
    if not re.match(r"(?i)^https?://", candidate):
        candidate = "https://" + candidate
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.username or parsed.password or not (hostname == "linkedin.com" or hostname.endswith(".linkedin.com")):
        return ""
    path = re.sub(r"/+", "/", parsed.path or "/")
    pieces = [piece for piece in path.split("/") if piece]
    if len(pieces) < 2 or pieces[0].lower() not in {"in", "pub"}:
        return ""
    # Host/localisation variants all refer to the same public profile.  Do not
    # preserve query strings or fragments, which often contain trackers.
    canonical_path = "/" + "/".join(pieces)
    return urlunsplit(("https", "www.linkedin.com", canonical_path, "", ""))[: _FIELD_LIMITS["linkedin_url"]]


def _extract_linkedin_url(text: str) -> tuple[str, int]:
    candidates: list[str] = []
    for match in _LINKEDIN_URL_RE.finditer(text):
        normalised = _normalise_linkedin_url(match.group(0))
        if normalised and normalised not in candidates:
            candidates.append(normalised)
    return (candidates[0] if candidates else "", len(candidates))


def _plausible_name(lines: list[str]) -> str:
    """Find a likely name near the top without treating a job title as a name."""
    for source_line in lines[:20]:
        line = _clean_line(source_line)
        if not line or len(line) > _FIELD_LIMITS["display_name"]:
            continue
        if "@" in line or "//" in line or "/" in line or any(character.isdigit() for character in line):
            continue
        if _section_marker(line) is not None:
            continue
        # Avoid sections such as "CV - Jean Dupont" rather than guessing how
        # to rewrite them.  A human can always fill a field the parser omits.
        if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž'’\- .]+", line):
            continue
        tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž]+(?:['’\-][A-Za-zÀ-ÖØ-öø-ÿĀ-ž]+)*", line)
        if not 2 <= len(tokens) <= 5:
            continue
        normalised_tokens = {_normalise_heading(token) for token in tokens}
        if normalised_tokens & _NAME_STOP_WORDS:
            continue
        # In practice CV names are capitalised or uppercase.  Requiring one
        # uppercase character prevents lowercase prose headings from becoming
        # a name suggestion after PDF extraction.
        if not any(character.isupper() for character in line):
            continue
        return line[: _FIELD_LIMITS["display_name"]]
    return ""


def parse_profile_text(text: object) -> dict[str, Any]:
    """Create reviewable profile suggestions from locally supplied text.

    The return value contains a complete ``values`` mapping, so callers can
    render empty fields consistently.  Nothing in this function persists or
    applies a profile update.  Its output must remain a draft until the user
    explicitly chooses the fields to save.
    """
    source_text, truncated = _safe_text(text)
    lines = source_text.split("\n")
    values = {field: "" for field in PROFILE_IMPORT_FIELDS}
    evidence: dict[str, list[str]] = {}
    warnings: list[str] = [
        "Les informations d’éligibilité, de nationalité, de visa, d’âge ou de disponibilité ne sont jamais déduites."
    ]

    if truncated:
        warnings.append("Le texte a été limité à 100 000 caractères avant analyse locale.")

    display_name = _plausible_name(lines)
    if display_name:
        values["display_name"] = display_name
        _append_evidence(evidence, "display_name", display_name)
        warnings.append("Le nom est une suggestion issue de la première ligne plausible : vérifie-le avant de l’appliquer.")

    contact_email = _extract_email(source_text)
    if contact_email:
        values["contact_email"] = contact_email
        _append_evidence(evidence, "contact_email", contact_email)

    contact_phone = _extract_phone(source_text)
    if contact_phone:
        values["contact_phone"] = contact_phone
        _append_evidence(evidence, "contact_phone", contact_phone)

    linkedin_url, linkedin_count = _extract_linkedin_url(source_text)
    if linkedin_url:
        values["linkedin_url"] = linkedin_url
        _append_evidence(evidence, "linkedin_url", linkedin_url)
    if linkedin_count > 1:
        warnings.append("Plusieurs profils LinkedIn ont été trouvés : seul le premier est proposé.")

    sections, section_evidence = _section_values(lines)
    for field, value in sections.items():
        values[field] = value[: _FIELD_LIMITS[field]].rstrip()
    for field, entries in section_evidence.items():
        for entry in entries:
            _append_evidence(evidence, field, entry)

    if not any(values.values()):
        warnings.append("Aucune information de profil exploitable n’a été trouvée dans ce texte.")
    elif not any(values[field] for field in ("education", "experience", "skills", "languages")):
        warnings.append("Aucune rubrique Formation, Expérience, Compétences ou Langues clairement identifiée n’a été trouvée.")

    return {
        "values": values,
        "warnings": warnings,
        "evidence": evidence,
        "text_chars": len(source_text),
        "truncated": truncated,
    }

