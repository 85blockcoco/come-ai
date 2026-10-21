"""Local pipeline: document text → proposed facts with exact provenance.

This module is pure: it receives text that was already extracted locally and
returns proposals.  It never reads a file, never calls a network service and
never uses a language model.

Every proposal keeps the exact place it was read from — page, start and end
offsets in the extracted text, and the quoted passage — so the person can
check a proposal against the source before approving it.

Nothing in this module can approve a fact: every proposal is created with the
``proposed`` status, OCR text included.  An OCR result is only ever a
proposal, never an approved fact.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Sequence

from .candidate_profile import (
    EXTRACTION_METHOD_EMBEDDED,
    FACT_KIND_CERTIFICATION,
    FACT_KIND_CONTACT,
    FACT_KIND_DATE,
    FACT_KIND_EDUCATION,
    FACT_KIND_EXPERIENCE,
    FACT_KIND_IDENTITY,
    FACT_KIND_LANGUAGE,
    FACT_KIND_PROJECT,
    FACT_KIND_SKILL,
    CandidateFact,
    FactProvenance,
    build_fact,
)
from .profile_import import PROFILE_SECTION_ALIASES, normalise_heading, parse_profile_text


#: A source document longer than this is truncated before any analysis.
MAX_PROFILE_SOURCE_CHARS = 200_000
#: Upper bound on the number of proposals returned for one document.
MAX_PROPOSALS = 300
#: Upper bound on the number of items read from one section.
MAX_ITEMS_PER_SECTION = 120
#: A skill or language item longer than this is a sentence, not an item.
MAX_ITEM_CHARS = 120
#: The extractor joins the pages of a document with this separator.
PAGE_SEPARATOR = "\n\n"


#: The four sections already known by the flat profile parser, mapped to the
#: kinds of the structured profile.
_SECTION_KIND_BY_FIELD: dict[str, str] = {
    "skills": FACT_KIND_SKILL,
    "languages": FACT_KIND_LANGUAGE,
    "education": FACT_KIND_EDUCATION,
    "experience": FACT_KIND_EXPERIENCE,
}

#: One vocabulary of headings is shared with the flat profile parser so both
#: agree on where a section starts, in French and in English.
_SECTION_KIND_BY_ALIAS: dict[str, str] = {
    alias: _SECTION_KIND_BY_FIELD.get(field, field)
    for field, aliases in PROFILE_SECTION_ALIASES.items()
    for alias in aliases
}

# Sections that only make sense in a structured profile.
_SECTION_KIND_BY_ALIAS.update(
    {
        "projets": FACT_KIND_PROJECT,
        "projects": FACT_KIND_PROJECT,
        "realisations": FACT_KIND_PROJECT,
        "achievements": FACT_KIND_PROJECT,
        "certifications": FACT_KIND_CERTIFICATION,
        "certificats": FACT_KIND_CERTIFICATION,
        "certificates": FACT_KIND_CERTIFICATION,
        "attestations": FACT_KIND_CERTIFICATION,
    }
)

_BULLET_RE = re.compile(r"^[-–—•*·>]+\s*")
_DATE_RE = re.compile(
    r"(?:"
    r"\b(?:janv|fév|mar|avr|mai|juin|juil|août|sept|oct|nov|déc|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*\.?\s*\d{4}"
    r"|\b\d{1,2}/\d{4}\b"
    r"|\b(?:19|20)\d{2}\b"
    r")"
)
_DATE_RANGE_RE = re.compile(
    r"(?P<start>(?:19|20)\d{2}|\d{1,2}/\d{4})"
    r"\s*(?:[-–—]|au|à|a|to)\s*"
    r"(?P<end>(?:19|20)\d{2}|\d{1,2}/\d{4}|présent|present|current|now)",
    re.IGNORECASE,
)
_ITEM_SEPARATORS = ",;|"
#: A period written on a document: two years, or a year and "présent".
_DATE_PERIOD_RE = re.compile(
    r"(?:19|20)\d{2}\s*(?:[-–—]|au|à|a|to)\s*(?:(?:19|20)\d{2}|présent|present|current|now)",
    re.IGNORECASE,
)
#: A single year written on a document.
_DATE_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


@dataclass(frozen=True, slots=True)
class SourcePage:
    """One page of the source document and its offsets in the extracted text."""

    page: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class _Section:
    """A detected section of the document."""

    kind: str
    title: str
    start_offset: int
    content_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class _Context:
    """Everything the extraction needs to build a fact with its provenance."""

    text: str
    spans: tuple[SourcePage, ...]
    source_name: str
    extraction_method: str
    created_at: str


def build_source_pages(text: str, pages: Sequence[str] | None = None) -> list[SourcePage]:
    """Return the page spans of a document.

    Args:
        text: The full extracted text.
        pages: The page texts in reading order, as returned by
            ``career.cv_quality.parser.extract_pages_from_bytes``.  Pages are
            joined with :data:`PAGE_SEPARATOR`, exactly like the extractor does.

    Returns:
        The list of page spans, in reading order.
    """
    if not pages:
        return [SourcePage(page=1, start_offset=0, end_offset=len(text))]
    spans: list[SourcePage] = []
    offset = 0
    for index, page_text in enumerate(pages):
        length = len(page_text)
        spans.append(
            SourcePage(page=index + 1, start_offset=offset, end_offset=offset + length)
        )
        offset += length + len(PAGE_SEPARATOR)
    return spans


def page_for_offset(spans: Sequence[SourcePage], offset: int) -> int | None:
    """Return the page holding an offset, or ``None`` when it is unknown."""
    if not spans:
        return None
    for span in spans:
        if span.start_offset <= offset <= span.end_offset:
            return span.page
    for span in reversed(spans):
        if offset >= span.start_offset:
            return span.page
    return None


def propose_profile_facts(
    text: str,
    *,
    pages: Sequence[str] | None = None,
    source_name: str = "",
    source_kind: str = "",
    extraction_method: str = EXTRACTION_METHOD_EMBEDDED,
    created_at: str = "",
) -> list[CandidateFact]:
    """Read a local document and propose facts with their exact provenance.

    Args:
        text: The text extracted locally from the document.
        pages: Optional page texts, used to attach a page number to each fact.
        source_name: Name of the local document, kept in the provenance.
        source_kind: Free label describing the kind of source (cv, export…).
        extraction_method: ``embedded_text`` or ``ocr``.  OCR text is proposed
            like any other text, and is never approved automatically.
        created_at: Timestamp copied on every proposal.

    Returns:
        The proposals, each with the ``proposed`` status.
    """
    source_text = _normalise_source(text)
    context = _Context(
        text=source_text,
        spans=tuple(build_source_pages(source_text, pages)),
        source_name=str(source_name or "")[:160],
        extraction_method=extraction_method,
        created_at=str(created_at or "")[:64],
    )
    facts: list[CandidateFact] = []
    for section in _detect_sections(source_text):
        facts.extend(_propose_from_section(context, section))
    facts.extend(_propose_identity_and_contact(context))

    unique: list[CandidateFact] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        key = (fact.kind, fact.value.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
        if len(unique) >= MAX_PROPOSALS:
            break
    return unique


def _normalise_source(text: str) -> str:
    """Keep the offsets stable while removing characters that break them."""
    raw = str(text or "").replace("\x00", "")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    return raw[:MAX_PROFILE_SOURCE_CHARS]


def _line_spans(text: str) -> list[tuple[int, str]]:
    """Return the offset and content of every line of the text."""
    spans: list[tuple[int, str]] = []
    offset = 0
    for line in text.split("\n"):
        spans.append((offset, line))
        offset += len(line) + 1
    return spans


def _detect_sections(text: str) -> list[_Section]:
    """Find the sections of the document and their exact offsets."""
    lines = _line_spans(text)
    headings: list[tuple[int, str, int]] = []
    for index, (offset, line) in enumerate(lines):
        heading = _heading_kind(line)
        if heading is None:
            continue
        kind, inline_at = heading
        headings.append((index, kind, offset + inline_at))

    sections: list[_Section] = []
    for position, (index, kind, content_offset) in enumerate(headings):
        start_offset = lines[index][0]
        end_offset = (
            lines[headings[position + 1][0]][0] if position + 1 < len(headings) else len(text)
        )
        sections.append(
            _Section(
                kind=kind,
                title=lines[index][1].strip()[:160],
                start_offset=start_offset,
                content_offset=max(start_offset, content_offset),
                end_offset=end_offset,
            )
        )
    return sections


def _heading_kind(line: str) -> tuple[str, int] | None:
    """Return the section kind and the offset of the inline content, if any.

    The offset is relative to the start of the line.  A heading without any
    inline content returns the offset just after the line, so the heading
    itself is never read as a fact.
    """
    candidate = line.strip()
    if not candidate or len(candidate) > 80:
        return None
    leading = len(line) - len(line.lstrip())
    kind = _SECTION_KIND_BY_ALIAS.get(normalise_heading(candidate))
    if kind:
        return kind, len(line) + 1
    for separator in (":", "—", "–", "|"):
        if separator not in candidate:
            continue
        label, _, _inline = candidate.partition(separator)
        kind = _SECTION_KIND_BY_ALIAS.get(normalise_heading(label))
        if kind:
            return kind, leading + len(label) + len(separator)
    return None


def _propose_from_section(context: _Context, section: _Section) -> list[CandidateFact]:
    """Read one section and propose the facts it contains."""
    body = context.text[section.content_offset : section.end_offset]
    if not body.strip():
        return []
    if section.kind == FACT_KIND_SKILL:
        return _propose_items(context, body, section.content_offset, kind=FACT_KIND_SKILL)
    if section.kind == FACT_KIND_LANGUAGE:
        return _propose_items(context, body, section.content_offset, kind=FACT_KIND_LANGUAGE)
    if section.kind == FACT_KIND_EXPERIENCE:
        return _propose_experiences(context, body, section.content_offset)
    return _propose_lines(context, body, section.content_offset, kind=section.kind)


def _split_items(body: str, body_offset: int, separators: str) -> list[tuple[str, int, int]]:
    """Split a section body into items, keeping the offset of each item."""
    items: list[tuple[str, int, int]] = []
    start = 0
    for index, character in enumerate(body):
        if character in separators or character == "\n":
            items.append((body[start:index], body_offset + start, body_offset + index))
            start = index + 1
    items.append((body[start:], body_offset + start, body_offset + len(body)))
    return items


def _trim_item(chunk: str, chunk_start: int) -> tuple[str, int, int]:
    """Remove the whitespace and the bullet marker of one item."""
    stripped = chunk.strip()
    if not stripped:
        return "", 0, 0
    start = chunk_start + (len(chunk) - len(chunk.lstrip()))
    bullet = _BULLET_RE.match(stripped)
    if bullet:
        stripped = stripped[bullet.end() :]
        start += bullet.end()
    stripped = stripped.strip()
    if not stripped:
        return "", 0, 0
    return stripped, start, start + len(stripped)


def _propose_items(
    context: _Context, body: str, body_offset: int, *, kind: str
) -> list[CandidateFact]:
    """Propose one fact per item of a comma or line separated list."""
    facts: list[CandidateFact] = []
    for chunk, chunk_start, _chunk_end in _split_items(body, body_offset, _ITEM_SEPARATORS):
        if len(facts) >= MAX_ITEMS_PER_SECTION:
            break
        item, start, end = _trim_item(chunk, chunk_start)
        if not item or len(item) > MAX_ITEM_CHARS:
            continue
        label = _item_label(item) if kind == FACT_KIND_LANGUAGE else item[:MAX_ITEM_CHARS]
        facts.append(
            _make_fact(
                context,
                kind=kind,
                label=label,
                value=item,
                start=start,
                end=end,
                metadata={"section": kind},
            )
        )
    return facts


def _item_label(item: str) -> str:
    """Return the name of a language, without its level."""
    for separator in ("(", " - ", " — ", " – ", ":", "="):
        if separator in item:
            return item.split(separator, 1)[0].strip()[:160] or item[:160]
    return item[:160]


def _propose_lines(
    context: _Context, body: str, body_offset: int, *, kind: str
) -> list[CandidateFact]:
    """Propose one fact per line of a section (diplomas, projects, certificates)."""
    facts: list[CandidateFact] = []
    for chunk, chunk_start, _chunk_end in _split_items(body, body_offset, ""):
        if len(facts) >= MAX_ITEMS_PER_SECTION:
            break
        item, start, end = _trim_item(chunk, chunk_start)
        if not item or len(item) < 2:
            continue
        facts.append(
            _make_fact(
                context,
                kind=kind,
                label=item[:160],
                value=item,
                start=start,
                end=end,
                metadata={"section": kind},
            )
        )
        # A diploma or a certificate carries its year: the date is a fact of
        # its own, with the exact place it was written.
        facts.extend(_propose_dates(context, item, start, end, owner=kind))
    return facts


def _propose_dates(
    context: _Context, chunk: str, chunk_start: int, chunk_end: int, *, owner: str
) -> list[CandidateFact]:
    """Propose one fact per date written inside a passage.

    A period (``2021-2024``) is preferred over the bare years it contains, so
    a date is never proposed twice for the same passage.
    """
    facts: list[CandidateFact] = []
    taken: list[tuple[int, int]] = []
    for match in _DATE_PERIOD_RE.finditer(chunk):
        start = chunk_start + match.start()
        end = chunk_start + match.end()
        taken.append((match.start(), match.end()))
        facts.append(
            _make_fact(
                context,
                kind=FACT_KIND_DATE,
                label=match.group(0),
                value=match.group(0),
                start=start,
                end=end,
                metadata={"owner": owner},
            )
        )
    for match in _DATE_YEAR_RE.finditer(chunk):
        if any(start <= match.start() and match.end() <= end for start, end in taken):
            continue
        start = chunk_start + match.start()
        end = chunk_start + match.end()
        facts.append(
            _make_fact(
                context,
                kind=FACT_KIND_DATE,
                label=match.group(0),
                value=match.group(0),
                start=start,
                end=end,
                metadata={"owner": owner},
            )
        )
    return facts


def _propose_experiences(
    context: _Context, body: str, body_offset: int
) -> list[CandidateFact]:
    """Propose one fact per experience entry of the experience section."""
    entries = _group_experience_entries(body, body_offset)
    facts: list[CandidateFact] = []
    for entry in entries:
        if len(facts) >= MAX_ITEMS_PER_SECTION:
            break
        value = entry.header if not entry.description else f"{entry.header}\n{entry.description}"
        parts = [part.strip() for part in entry.header.split("|") if part.strip()]
        label = " — ".join(parts) if parts else entry.header
        facts.append(
            _make_fact(
                context,
                kind=FACT_KIND_EXPERIENCE,
                label=label[:160],
                value=value,
                start=entry.start,
                end=entry.end,
                metadata=_experience_metadata(parts, entry.header),
            )
        )
        # The period written on the entry is a fact of its own.
        facts.extend(
            _propose_dates(
                context,
                entry.header,
                entry.header_start,
                entry.header_end,
                owner=FACT_KIND_EXPERIENCE,
            )
        )
    return facts


@dataclass(frozen=True, slots=True)
class _ExperienceEntry:
    """One experience entry and the offsets of its header."""

    header: str
    description: str
    start: int
    end: int
    header_start: int
    header_end: int


def _group_experience_entries(body: str, body_offset: int) -> list[_ExperienceEntry]:
    """Group the lines of an experience section into entries.

    A new entry starts on a line that carries a date and reads like a header:
    a short line, or a line using the ``role | company | dates`` convention.
    """
    entries: list[_ExperienceEntry] = []
    header = ""
    description_lines: list[str] = []
    entry_start = 0
    entry_end = 0
    header_start = 0

    for chunk, chunk_start, chunk_end in _split_items(body, body_offset, ""):
        line = chunk.strip()
        if not line:
            continue
        starts_entry = bool(_DATE_RE.search(line)) and ("|" in line or len(line) <= 90)
        if starts_entry and header:
            entries.append(
                _ExperienceEntry(
                    header=header,
                    description="\n".join(description_lines),
                    start=entry_start,
                    end=entry_end,
                    header_start=header_start,
                    header_end=header_start + len(header),
                )
            )
            header = ""
            description_lines = []
        if not header:
            header = line
            entry_start = chunk_start + (len(chunk) - len(chunk.lstrip()))
            header_start = entry_start
        else:
            description_lines.append(line)
        entry_end = chunk_end

    if header:
        entries.append(
            _ExperienceEntry(
                header=header,
                description="\n".join(description_lines),
                start=entry_start,
                end=entry_end,
                header_start=header_start,
                header_end=header_start + len(header),
            )
        )
    return entries


def _experience_metadata(parts: list[str], header: str) -> dict[str, Any]:
    """Read the company, the role and the dates written on the entry header."""
    metadata: dict[str, Any] = {"header_parts": parts[:4]}
    if len(parts) >= 3:
        metadata["role"] = parts[1][:160]
        metadata["company"] = parts[2][:160]
    elif len(parts) == 2:
        metadata["role"] = parts[0][:160]
        metadata["company"] = parts[1][:160]
    dates = _DATE_RANGE_RE.search(header)
    if dates:
        metadata["start_date"] = dates.group("start")
        metadata["end_date"] = dates.group("end")
    return metadata


def _propose_identity_and_contact(context: _Context) -> list[CandidateFact]:
    """Propose the identity and contact facts found in the document."""
    suggestions = parse_profile_text(context.text)
    values = suggestions.get("values", {})
    if not isinstance(values, dict):
        return []
    facts: list[CandidateFact] = []
    wanted = (
        ("display_name", FACT_KIND_IDENTITY, "Nom"),
        ("contact_email", FACT_KIND_CONTACT, "E-mail"),
        ("contact_phone", FACT_KIND_CONTACT, "Téléphone"),
        ("linkedin_url", FACT_KIND_CONTACT, "Profil LinkedIn"),
    )
    for field, kind, label in wanted:
        value = str(values.get(field) or "").strip()
        if not value:
            continue
        if field == "display_name" and not _looks_like_person_name(value):
            # A sentence is not a name: it is better to propose nothing than
            # to propose something the person has to correct.
            continue
        located = _locate(context.text, value)
        if located is None:
            continue
        start, end = located
        facts.append(
            _make_fact(
                context,
                kind=kind,
                label=label,
                value=value,
                start=start,
                end=end,
                metadata={"field": field},
            )
        )
    return facts


def _locate(text: str, value: str) -> tuple[int, int] | None:
    """Find where a value was read in the text, case-insensitively."""
    if not value:
        return None
    index = text.find(value)
    if index >= 0:
        return index, index + len(value)
    index = text.casefold().find(value.casefold())
    if index >= 0:
        return index, index + len(value)
    if "linkedin.com" in value:
        # The stored URL is canonicalised, so the document keeps a shorter form.
        slug = value.split("linkedin.com", 1)[-1]
        index = text.casefold().find(slug.casefold())
        if index >= 0:
            return index, index + len(slug)
    return None


_NAME_PARTICLES = {"de", "du", "des", "la", "le", "van", "von", "der", "di", "da"}


def _looks_like_person_name(value: str) -> bool:
    """Tell a name apart from a sentence.

    The flat parser proposes a plausible first line; this check keeps a whole
    sentence from being proposed as the identity of the candidate.
    """
    candidate = value.strip()
    if not candidate or candidate.endswith("."):
        return False
    tokens = candidate.split()
    if not 2 <= len(tokens) <= 4:
        return False
    for token in tokens:
        cleaned = token.strip(".,;:!?'\"")
        if not cleaned:
            return False
        if cleaned.casefold() in _NAME_PARTICLES:
            continue
        if not cleaned[:1].isupper():
            return False
    return True


def _make_fact(
    context: _Context,
    *,
    kind: str,
    label: str,
    value: str,
    start: int,
    end: int,
    metadata: dict[str, Any] | None = None,
) -> CandidateFact:
    """Build one proposal with its provenance."""
    provenance = FactProvenance(
        page=page_for_offset(context.spans, start),
        start_offset=start,
        end_offset=end,
        quote=_quote(context.text, start, end),
        source_name=context.source_name,
        extraction_method=context.extraction_method,
    )
    return build_fact(
        fact_id=_fact_id(kind, value, start),
        kind=kind,
        label=label,
        value=value,
        provenance=provenance,
        created_at=context.created_at,
        updated_at=context.created_at,
        metadata=metadata,
    )


def _fact_id(kind: str, value: str, offset: int) -> str:
    """Return a stable identifier so a rebuild keeps the same fact ids."""
    digest = hashlib.sha256(f"{kind}|{value}|{offset}".encode("utf-8")).hexdigest()
    return f"fact_{digest[:12]}"


def _quote(text: str, start: int, end: int, *, limit: int = 240) -> str:
    """Return the quoted passage of a fact, whitespace-normalised."""
    if start < 0 or end > len(text) or end <= start:
        return ""
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    if len(snippet) > limit:
        return snippet[: limit - 1].rstrip() + "…"
    return snippet
