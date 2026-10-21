"""Turn an imported CV into candidate-profile facts the person reviews.

SK-10 pipeline::

    PDF / DOCX / image
      → local extraction (Mission 01 parser, OCR when there is no text layer)
      → fact proposals (skills, experiences, education, languages, contacts)
      → provenance: page, exact character offsets and verbatim quote
      → approval field by field (the interface)
      → active profile (approved facts only)

Everything here is deterministic and local.  No fact is ever approved
automatically: this module can only produce ``proposed`` facts, and facts
recognised by OCR are flagged ``requires_review`` because a machine-read
page must always be checked by a human before it can justify an application.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from .candidate_profile import (
    CandidateFact,
    CandidateProfile,
    FactProvenance,
    FACT_KIND_CONTACT,
    FACT_KIND_EXPERIENCE,
    FACT_KIND_IDENTITY,
    FACT_KIND_LANGUAGE,
    FACT_KIND_SKILL,
    FACT_STATUS_PROPOSED,
)
from .cv_quality import PagedDocument
from .profile_import import SECTION_ALIASES, normalise_heading


#: Hard ceiling so a pathological document cannot create thousands of facts.
MAX_FACTS = 400
#: Longest value kept for one fact.
MAX_FACT_VALUE_CHARS = 1_200
#: Longest verbatim quote kept for one fact.
MAX_QUOTE_CHARS = 400
#: A heading line longer than this is prose, not a section marker.
MAX_HEADING_CHARS = 80

_FACT_PREFIX = "fact_"

_FIELD_BY_HEADING: dict[str, str] = {
    normalise_heading(alias): field
    for field, aliases in SECTION_ALIASES.items()
    for alias in aliases
}

#: Items are separated by these punctuation marks or by a line break.
_ITEM_SEPARATOR_RE = re.compile(r"[^,;|•·\n]+")

_EMAIL_RE = re.compile(
    r"(?<![\w.!#$%&'*+/=?^`{|}~-])"
    r"([A-Z0-9][A-Z0-9.!#$%&'*+/=?^_`{|}~-]{0,63}"
    r"@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+)"
    r"(?![\w.-])",
    re.IGNORECASE,
)

_PHONE_RE = re.compile(r"(?<![\w+])(?:\+|00)?\s*(?:\(?\d{1,4}\)?[\s.\-]*){2,8}\d(?!\w)")

_LINKEDIN_RE = re.compile(
    r"(?i)(?:https?://)?(?:(?:[a-z]{2,3}|www)\.)?linkedin\.com/"
    r"(?:in|pub)/[a-z0-9%._~-]+(?:/[a-z0-9%._~-]+)*(?:[?#][^\s<>()\[\]{}\"']*)?"
)

_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

_DATE_RANGE_RE = re.compile(
    r"(?i)(?:(?:19|20)\d{2}\s*(?:[-–—]|au|à|to)\s*"
    r"(?:(?:19|20)\d{2}|présent[e]?|present|aujourd'hui|aujourd’hui|actuel|now|current|today)?"
    r"|(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre"
    r"|january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(?:19|20)\d{2}"
    r"|\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)?\d{2,4})"
)

_DEGREE_KEYWORDS = (
    "master",
    "licence",
    "bachelor",
    "diplome",
    "doctorat",
    "mba",
    "msc",
    "ma",
    "dba",
    "msa",
    "degres",
    "btp",
    "bts",
    "dut",
    "deug",
    "prepa",
    "ecole",
    "universite",
    "school",
    "degree",
    "certificat",
    "formation",
)

_EDUCATION_START_RE = re.compile(
    r"(?<!\d)(?:19|20)\d{2}(?!\d)|\b(?:" + "|".join(_DEGREE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

_LANGUAGE_LEVEL_RE = re.compile(
    r"(?i)(?<![a-z0-9])(a1|a2|b1|b2|c1|c2|courant[e]?|courante|professionnel[l]?"
    r"|professionnelle|fluide|notions?|debutant[e]?|intermediaire[s]?|avance[e]?"
    r"|avancee|bilingue|beginner|intermediate|advanced|niveau)(?![a-z0-9])"
)

_NAME_STOP_WORDS = {
    "analyst",
    "analyste",
    "bachelor",
    "candidat",
    "contact",
    "cv",
    "experience",
    "finance",
    "ingenieur",
    "intern",
    "langues",
    "master",
    "mobile",
    "profil",
    "resume",
    "stagiaire",
    "telephone",
    "universite",
}


@dataclass(frozen=True, slots=True)
class FactProposal:
    """One fact suggested by the local extractor, before any human review."""

    kind: str
    label: str
    value: str
    start_offset: int
    end_offset: int
    quote: str
    page: int | None = None
    confidence: float = 0.5


@dataclass(frozen=True, slots=True)
class _Section:
    """One recognised CV section and the region of the document it covers."""

    field: str
    start: int
    end: int
    inline: str
    inline_start: int


def build_fact_proposals(
    document: PagedDocument,
    *,
    source_kind: str = "cv",
) -> list[FactProposal]:
    """Extract reviewable fact proposals from an extracted document.

    Every proposal carries the exact character offsets of the passage it was
    read from and the verbatim quote of that passage.  Nothing is approved
    here: the result is a list of proposals for the person to accept or refuse.
    """
    text = document.text
    if not text.strip():
        return []

    proposals: list[FactProposal] = []
    sections = _find_sections(text)
    for section in sections:
        regions = _section_regions(text, section)
        if section.field == "skills":
            proposals.extend(_skill_proposals(text, document, regions))
        elif section.field == "languages":
            proposals.extend(_language_proposals(text, document, regions))
        elif section.field == "education":
            proposals.extend(_entry_proposals(text, document, regions, "education"))
        elif section.field == "experience":
            proposals.extend(_entry_proposals(text, document, regions, "experience"))

    proposals.extend(_contact_proposals(text, document))
    proposals.extend(_identity_proposals(text, document))

    deduplicated: list[FactProposal] = []
    seen: set[tuple[str, str]] = set()
    for proposal in proposals:
        key = (proposal.kind, proposal.value.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(proposal)
        if len(deduplicated) >= MAX_FACTS:
            break
    return deduplicated


def build_candidate_profile(
    document: PagedDocument,
    *,
    source_kind: str = "cv",
    fact_id_factory: Callable[[], str] | None = None,
    created_at: str = "",
) -> CandidateProfile:
    """Build the reviewable candidate profile of one extracted document.

    Every fact is created ``proposed``.  Facts recognised by OCR are flagged
    ``requires_review``: an OCR result is never treated as read.
    """
    proposals = build_fact_proposals(document, source_kind=source_kind)
    factory = fact_id_factory or (lambda: f"{_FACT_PREFIX}{len(proposals):04d}")
    requires_review = document.extraction == "ocr"
    facts: list[CandidateFact] = []
    for proposal in proposals:
        confidence = proposal.confidence
        if requires_review:
            confidence = min(confidence, 0.4)
        facts.append(
            CandidateFact(
                id=factory(),
                kind=proposal.kind,
                label=proposal.label,
                value=proposal.value,
                status=FACT_STATUS_PROPOSED,
                provenance=FactProvenance(
                    source_document=document.filename or "",
                    source_kind=source_kind,
                    extraction=document.extraction,
                    page=proposal.page,
                    start_offset=proposal.start_offset,
                    end_offset=proposal.end_offset,
                    quote=proposal.quote,
                ),
                original_value=proposal.value,
                confidence=confidence,
                requires_review=requires_review,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return CandidateProfile(
        facts=tuple(facts),
        source_document=document.filename or "",
        source_kind=source_kind,
        extraction=document.extraction,
        page_count=document.page_count,
        created_at=created_at,
        updated_at=created_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Section detection
# ─────────────────────────────────────────────────────────────────────────────


def _iter_lines(text: str) -> Iterator[tuple[str, int, int]]:
    """Yield ``(line, start_offset, end_offset)`` for every line of the text."""
    position = 0
    for raw in text.split("\n"):
        yield raw, position, position + len(raw)
        position += len(raw) + 1


def _heading_of(line: str) -> tuple[str, int | None] | None:
    """Return ``(field, inline_offset)`` when the line is a section heading.

    ``inline_offset`` is ``None`` for a bare heading such as ``FORMATION``:
    such a line carries no value, only the start of a section.
    """
    stripped = line.strip()
    if not stripped:
        return None
    field = _FIELD_BY_HEADING.get(normalise_heading(stripped))
    if field:
        return field, None
    if len(stripped) > MAX_HEADING_CHARS:
        return None
    for separator in (":", "—", "–"):
        if separator not in stripped:
            continue
        label, _, _inline = stripped.partition(separator)
        if len(label) > 40:
            continue
        field = _FIELD_BY_HEADING.get(normalise_heading(label))
        if field:
            return field, len(label) + len(separator)
    return None


def _find_sections(text: str) -> list[_Section]:
    """Locate every recognised section and the document region it covers."""
    lines = list(_iter_lines(text))
    marks: list[tuple[int, str, int | None, int]] = []
    for index, (line, start, end) in enumerate(lines):
        heading = _heading_of(line)
        if heading is None:
            continue
        field, inline_offset = heading
        marks.append((index, field, inline_offset, end))

    sections: list[_Section] = []
    for position, (index, field, inline_offset, heading_end) in enumerate(marks):
        next_index = marks[position + 1][0] if position + 1 < len(marks) else len(lines)
        body_start = heading_end + 1
        body_end = lines[next_index][1] if next_index < len(lines) else len(text)
        line, line_start, _ = lines[index]
        inline = ""
        inline_start = heading_end
        if inline_offset is not None:
            lead = len(line) - len(line.lstrip())
            inline_start = min(line_start + lead + inline_offset, heading_end)
            inline = text[inline_start:heading_end]
        sections.append(
            _Section(
                field=field,
                start=body_start,
                end=max(body_start, body_end),
                inline=inline,
                inline_start=inline_start,
            )
        )
    return sections


def _section_regions(text: str, section: _Section) -> list[tuple[int, int]]:
    """Return the regions holding the values of one section."""
    regions: list[tuple[int, int]] = []
    if section.inline.strip():
        regions.append((section.inline_start, section.inline_start + len(section.inline)))
    if section.start < section.end:
        regions.append((section.start, section.end))
    return regions


# ─────────────────────────────────────────────────────────────────────────────
# Value extraction
# ─────────────────────────────────────────────────────────────────────────────


def _split_items(text: str, start: int, end: int) -> list[tuple[str, int, int]]:
    """Split a region into items, keeping the exact offset of each item."""
    items: list[tuple[str, int, int]] = []
    region = text[start:end]
    for match in _ITEM_SEPARATOR_RE.finditer(region):
        raw = match.group(0)
        item_start = start + match.start()
        leading = len(raw) - len(raw.lstrip())
        item_start += leading
        raw = raw[leading:]
        while raw[:1] in {"-", "–", "—", "*", "•", "·"}:
            raw = raw[1:]
            item_start += 1
            trailing = len(raw) - len(raw.lstrip())
            item_start += trailing
            raw = raw[trailing:]
        value = raw.strip()
        if not value:
            continue
        items.append((value, item_start, item_start + len(value)))
    return items


def _split_entries(
    text: str,
    start: int,
    end: int,
    trigger: re.Pattern[str],
) -> list[tuple[int, int]]:
    """Split a region into entry blocks, keeping the exact offsets."""
    entries: list[tuple[int, int]] = []
    current_start: int | None = None
    for line, line_start, _line_end in _iter_lines(text):
        if line_start < start or line_start >= end:
            continue
        stripped = line.strip()
        if not stripped:
            if current_start is not None:
                entries.append((current_start, line_start))
                current_start = None
            continue
        if current_start is None:
            current_start = line_start
            continue
        if _starts_new_entry(stripped, trigger):
            entries.append((current_start, line_start))
            current_start = line_start
    if current_start is not None:
        entries.append((current_start, end))
    return entries


def _starts_new_entry(line: str, trigger: re.Pattern[str]) -> bool:
    """Return ``True`` when a line opens a new entry.

    A line that only carries a date (``2021 - 2024`` on its own) continues
    the entry started by the line above it.
    """
    match = trigger.search(line)
    if not match:
        return False
    remainder = (line[: match.start()] + " " + line[match.end() :]).strip()
    return len(remainder) >= 2


def _clean_label(value: str) -> str:
    return value.strip(" \t,;|·•-–—:")


def _entry_label(first_line: str, trigger: re.Pattern[str]) -> str:
    """Derive a short display name for one entry block.

    The full date range is removed first: a line such as
    ``2019 - 2022 | Licence Économie`` must be named ``Licence Économie`` and
    not ``2019``.
    """
    candidates: list[tuple[str, str]] = []
    for pattern in (_DATE_RANGE_RE, trigger):
        match = pattern.search(first_line)
        if not match:
            continue
        before = _clean_label(first_line[: match.start()])
        after = _clean_label(first_line[match.end() :])
        candidates.append((before, after))
        if pattern is _DATE_RANGE_RE:
            break

    for before, after in candidates:
        candidate = before if len(before) >= 2 else after
        if not candidate:
            continue
        pieces = re.split(r"\s*\|\s*|\s+[–—-]\s+|\s*,\s*", candidate)
        label = _clean_label(pieces[0]) if pieces else ""
        if label:
            return label[:160]
    return _clean_label(first_line)[:160] or "Entrée"


def _quote(text: str, start: int, end: int) -> str:
    """Return the verbatim passage, bounded but never rewritten."""
    passage = text[start:end]
    if len(passage) > MAX_QUOTE_CHARS:
        passage = passage[:MAX_QUOTE_CHARS].rstrip()
    return passage


# ─────────────────────────────────────────────────────────────────────────────
# Proposal builders
# ─────────────────────────────────────────────────────────────────────────────


def _skill_proposals(
    text: str, document: PagedDocument, regions: Iterable[tuple[int, int]]
) -> list[FactProposal]:
    proposals: list[FactProposal] = []
    for start, end in regions:
        for value, item_start, item_end in _split_items(text, start, end):
            if len(value) > 120:
                continue
            proposals.append(
                FactProposal(
                    kind=FACT_KIND_SKILL,
                    label=value[:120],
                    value=value[:120],
                    start_offset=item_start,
                    end_offset=item_end,
                    quote=_quote(text, item_start, item_end),
                    page=document.page_for_offset(item_start),
                    confidence=0.9,
                )
            )
    return proposals


def _language_proposals(
    text: str, document: PagedDocument, regions: Iterable[tuple[int, int]]
) -> list[FactProposal]:
    proposals: list[FactProposal] = []
    for start, end in regions:
        for value, item_start, item_end in _split_items(text, start, end):
            if len(value) > 120:
                continue
            label = _language_label(value)
            proposals.append(
                FactProposal(
                    kind=FACT_KIND_LANGUAGE,
                    label=label,
                    value=value[:120],
                    start_offset=item_start,
                    end_offset=item_end,
                    quote=_quote(text, item_start, item_end),
                    page=document.page_for_offset(item_start),
                    confidence=0.9,
                )
            )
    return proposals


def _language_label(value: str) -> str:
    """Return the language name, without its level when there is one."""
    match = _LANGUAGE_LEVEL_RE.search(value)
    if not match:
        return value[:120]
    name = _clean_label(value[: match.start()])
    if len(name) < 2:
        return value[:120]
    return name[:120]


def _entry_proposals(
    text: str,
    document: PagedDocument,
    regions: Iterable[tuple[int, int]],
    kind: str,
) -> list[FactProposal]:
    trigger = _DATE_RANGE_RE if kind == FACT_KIND_EXPERIENCE else _EDUCATION_START_RE
    proposals: list[FactProposal] = []
    for start, end in regions:
        for entry_start, entry_end in _split_entries(text, start, end, trigger):
            block = text[entry_start:entry_end].strip()
            if not block:
                continue
            first_line = text[entry_start : entry_end].split("\n", 1)[0]
            value = block[:MAX_FACT_VALUE_CHARS]
            proposals.append(
                FactProposal(
                    kind=kind,
                    label=_entry_label(first_line, trigger),
                    value=value,
                    start_offset=entry_start,
                    end_offset=entry_end,
                    quote=_quote(text, entry_start, entry_end),
                    page=document.page_for_offset(entry_start),
                    confidence=0.75,
                )
            )
    return proposals


def _contact_proposals(text: str, document: PagedDocument) -> list[FactProposal]:
    proposals: list[FactProposal] = []
    email = _EMAIL_RE.search(text)
    if email:
        value = email.group(1).strip(".,;:!?<>()[]{}\"'").lower()
        proposals.append(
            FactProposal(
                kind=FACT_KIND_CONTACT,
                label="email",
                value=value,
                start_offset=email.start(1),
                end_offset=email.end(1),
                quote=_quote(text, email.start(1), email.end(1)),
                page=document.page_for_offset(email.start(1)),
                confidence=0.85,
            )
        )
    for match in _PHONE_RE.finditer(text):
        candidate = match.group(0).strip(" .-–—")
        digits = re.sub(r"\D", "", candidate)
        if not 7 <= len(digits) <= 15 or len(set(digits)) == 1:
            continue
        if _YEAR_RE.search(candidate.replace(" ", "")) and "-" in candidate:
            continue
        proposals.append(
            FactProposal(
                kind=FACT_KIND_CONTACT,
                label="phone",
                value=candidate[:80],
                start_offset=match.start(),
                end_offset=match.end(),
                quote=_quote(text, match.start(), match.end()),
                page=document.page_for_offset(match.start()),
                confidence=0.8,
            )
        )
        break
    linkedin = _LINKEDIN_RE.search(text)
    if linkedin:
        proposals.append(
            FactProposal(
                kind=FACT_KIND_CONTACT,
                label="linkedin",
                value=linkedin.group(0)[:200],
                start_offset=linkedin.start(),
                end_offset=linkedin.end(),
                quote=_quote(text, linkedin.start(), linkedin.end()),
                page=document.page_for_offset(linkedin.start()),
                confidence=0.85,
            )
        )
    return proposals


def _identity_proposals(text: str, document: PagedDocument) -> list[FactProposal]:
    for index, (line, start, end) in enumerate(_iter_lines(text)):
        if index >= 20:
            break
        stripped = line.strip()
        if not stripped or len(stripped) > 120:
            continue
        if "@" in stripped or "/" in stripped or any(character.isdigit() for character in stripped):
            continue
        if _heading_of(line) is not None:
            continue
        tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž'’\-]+", stripped)
        if not 2 <= len(tokens) <= 5:
            continue
        if {token.casefold() for token in tokens} & _NAME_STOP_WORDS:
            continue
        if not any(character.isupper() for character in stripped):
            continue
        return [
            FactProposal(
                kind=FACT_KIND_IDENTITY,
                label="display_name",
                value=stripped[:120],
                start_offset=start,
                end_offset=end,
                quote=_quote(text, start, end),
                page=document.page_for_offset(start),
                confidence=0.5,
            )
        ]
    return []


def profile_summary(profile: CandidateProfile) -> dict[str, Any]:
    """Return a compact, JSON-safe summary of a candidate profile."""
    counts = profile.counts_by_status()
    return {
        "source_document": profile.source_document,
        "source_kind": profile.source_kind,
        "extraction": profile.extraction,
        "page_count": profile.page_count,
        "counts": counts,
        "total": len(profile.facts),
        "usable": len(profile.usable_facts),
        "updated_at": profile.updated_at,
    }
