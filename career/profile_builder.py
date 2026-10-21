"""Local pipeline: extracted document text → proposed candidate facts.

The builder reuses the Mission 01 parser and structure engine
(:mod:`career.cv_quality`) so the same local text drives both the structural
diagnosis and the fact proposals.

Hard rule of this module: **nothing is ever approved here**.  Every fact it
returns has the ``proposed`` status, including the facts read by OCR.  The
person decides each fact afterwards, one by one, through the API.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .candidate_profile import (
    Evidence,
    Fact,
    KIND_CERTIFICATION,
    KIND_CONTACT,
    KIND_DATE,
    KIND_EDUCATION,
    KIND_EXPERIENCE,
    KIND_LANGUAGE,
    KIND_PROJECT,
    KIND_SKILL,
    MAX_LABEL_CHARS,
    MAX_QUOTE_CHARS,
    MAX_VALUE_CHARS,
    SOURCE_EMBEDDED_TEXT,
    SOURCE_OCR,
    STATUS_PROPOSED,
    normalize_text,
)
from .cv_quality import DocumentInput, analyze_cv


# ── Limits ──────────────────────────────────────────────────────────────────
MAX_FACTS_PER_KIND = 60
MAX_FACTS_TOTAL = 300
MAX_SKILL_CHARS = 80
MAX_ITEM_CHARS = 200
MAX_FACT_DESCRIPTION_CHARS = 240


# ── Section mapping ─────────────────────────────────────────────────────────
SECTION_KINDS: dict[str, str] = {
    "Compétences": KIND_SKILL,
    "Langues": KIND_LANGUAGE,
    "Formation": KIND_EDUCATION,
    "Expérience": KIND_EXPERIENCE,
    "Projets": KIND_PROJECT,
    "Certifications": KIND_CERTIFICATION,
}


# ── Local vocabulary ────────────────────────────────────────────────────────
_SKILL_STOP_LABELS = {
    "competences",
    "competence",
    "compétences",
    "competences techniques",
    "competences cles",
    "competence technique",
    "langues",
    "langue",
    "outils",
    "technologies",
    "autres",
    "soft skills",
    "savoir faire",
    "presentation",
    "présentation",
    "experiences",
    "experience",
    "formation",
    "langues et Noel",
}

_LEVEL_WORDS = (
    "natif",
    "native",
    "courant",
    "fluent",
    "avance",
    "avancé",
    "intermediaire",
    "intermédiaire",
    "elementaire",
    "élémentaire",
    "professionnel",
    "professional",
    "debutant",
    "débutant",
    "beginner",
)

_LEVEL_RE = re.compile(
    r"\b(?:" + "|".join(_LEVEL_WORDS) + r"|[ABC][12])\b",
    re.IGNORECASE,
)

_DEGREE_RE = re.compile(
    r"\b(master|m1|m2|mba|msc|licence|licence pro|doctorat|phd|bts|dts|dipl[oô]me|"
    r"degrees?|bachelor|ba\b|bsc|engineering|engineer|formation|cycle|universite|"
    r"université|ecole|école)\b",
    re.IGNORECASE,
)

_DATE_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\s*[-–—/]\s*((?:19|20)\d{2}|present|présent|actuel|en cours)\b",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

_MONTH_YEAR_RE = re.compile(
    r"\b(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)

_LIST_SEPARATORS = re.compile(r"[,;•·]")

#: Characters that introduce a bullet item.  They are never part of the fact.
_BULLET_CHARS = "-–—*•·"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

_PHONE_RE = re.compile(r"(?:\+|00)?\s*(?:\(?\d{1,4}\)?[\s.\-]*){2,8}\d")

_YEAR_RANGE_ONLY = re.compile(r"^(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)\d{2}$")


@dataclass(frozen=True, slots=True)
class PageSpan:
    """One page inside the extracted text.

    Attributes:
        page: 1-based page number.
        start: First character index of the page.
        end: Last character index (exclusive) of the page.
        confidence: ``exact`` when the page list is known, ``estimated``
            when the page was guessed from the text layout.
    """

    page: int
    start: int
    end: int
    confidence: str


@dataclass(frozen=True, slots=True)
class _Item:
    """One candidate line inside a section, with its absolute offsets."""

    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Entry:
    """One experience entry of the Expérience section."""

    role: str
    company: str
    dates: str
    result: str
    start: int
    end: int


def _strip_accents(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    return "".join(character for character in text if not unicodedata.combining(character))


def _clean_line(value: str) -> str:
    """Compact the whitespace of one source line without changing its wording."""
    return re.sub(r"[ \t]+", " ", value.replace("\r", "")).strip()


def page_spans(
    text: str,
    pages: Sequence[str] | None = None,
    page_count: int | None = None,
    *,
    page_confidence: str = "exact",
) -> list[PageSpan]:
    """Return the page boundaries inside the extracted text.

    When the per-page texts are known, the boundaries are exact.  When only the
    number of pages is known (a flat OCR reading), the text is split evenly
    and the confidence is ``estimated``.  Otherwise the whole text is one
    block: the page is then a hint, never a proof.

    ``page_confidence`` qualifies the known-pages case: a DOCX has no page
    information, so its single block stays ``estimated``.
    """
    if pages:
        spans: list[PageSpan] = []
        cursor = 0
        for number, page in enumerate(pages, start=1):
            spans.append(PageSpan(number, cursor, cursor + len(page), page_confidence))
            cursor += len(page) + 2
        return spans

    if page_count and page_count > 1 and text:
        size = max(1, len(text) // page_count)
        spans = []
        for number in range(page_count):
            start = number * size
            end = len(text) if number == page_count - 1 else min((number + 1) * size, len(text))
            spans.append(PageSpan(number + 1, start, end, "estimated"))
        return spans

    return [PageSpan(1, 0, len(text), "estimated")] if text else []


def page_for_offset(spans: Sequence[PageSpan], offset: int) -> tuple[int, str]:
    """Return the page number and its confidence for one character offset."""
    for span in spans:
        if span.start <= offset < span.end:
            return span.page, span.confidence
    if spans and offset >= spans[-1].end:
        return spans[-1].page, spans[-1].confidence
    return 0, "unknown"


def _content_span(raw_line: str) -> tuple[int, int]:
    """Return the span of the line content, without its bullet nor its blanks."""
    start = 0
    length = len(raw_line)
    while start < length and (raw_line[start].isspace() or raw_line[start] in _BULLET_CHARS):
        start += 1
    end = length
    while end > start and raw_line[end - 1].isspace():
        end -= 1
    return start, end


def _trim_span(raw_line: str, start: int, end: int) -> tuple[int, int]:
    """Return a span without its leading and trailing blanks."""
    while start < end and raw_line[start].isspace():
        start += 1
    while end > start and raw_line[end - 1].isspace():
        end -= 1
    return start, end


def _split_spans(raw_line: str, content_start: int, content_end: int) -> list[tuple[int, int]]:
    """Split a list item on its separators, keeping the exact span of each piece."""
    spans: list[tuple[int, int]] = []
    cursor = content_start
    for match in _LIST_SEPARATORS.finditer(raw_line, content_start, content_end):
        piece_start, piece_end = _trim_span(raw_line, cursor, match.start())
        if piece_end > piece_start:
            spans.append((piece_start, piece_end))
        cursor = match.end()
    piece_start, piece_end = _trim_span(raw_line, cursor, content_end)
    if piece_end > piece_start:
        spans.append((piece_start, piece_end))
    return spans


def _section_items(text: str, start: int, end: int, *, split_lists: bool) -> list[_Item]:
    """Return the candidate items of one section, with exact source offsets.

    The offsets always point at the raw source text: the passage
    ``text[start:end]`` is the verbatim item the fact comes from, so the
    stored quote can be checked against the document character by character.
    Only the displayed label is normalised (blanks collapsed).
    """
    items: list[_Item] = []
    cursor = start
    for raw_line in text[start:end].split("\n"):
        line_start = cursor
        cursor += len(raw_line) + 1
        content_start, content_end = _content_span(raw_line)
        if content_end <= content_start:
            continue
        if split_lists:
            for piece_start, piece_end in _split_spans(raw_line, content_start, content_end):
                items.append(
                    _Item(
                        _clean_line(raw_line[piece_start:piece_end]),
                        line_start + piece_start,
                        line_start + piece_end,
                    )
                )
            continue
        items.append(
            _Item(
                _clean_line(raw_line[content_start:content_end]),
                line_start + content_start,
                line_start + content_end,
            )
        )
    return items


def _quote(text: str, start: int, end: int) -> str:
    """Return the verbatim passage of a fact, bounded for a readable review.

    The quote is the source text itself: ``text[start:end]``.  Only a very
    long passage is shortened, and the shortening is visible (it ends with
    an ellipsis).
    """
    excerpt = text[start:end]
    if len(excerpt) > MAX_QUOTE_CHARS:
        excerpt = excerpt[:MAX_QUOTE_CHARS].rstrip() + "…"
    return excerpt


def _detect_date(text: str) -> str:
    """Return the first date range or year found in a line."""
    match = _DATE_RANGE_RE.search(text)
    if match:
        start = match.group(1)
        end = match.group(2)
        if end.lower() in {"present", "présent", "actuel"}:
            end = "Présent"
        elif end.lower() == "en cours":
            end = "En cours"
        return f"{start} – {end}"
    match = _MONTH_YEAR_RE.search(text)
    if match:
        return f"{_strip_accents(match.group(1)).capitalize()} {match.group(2)}"
    match = _YEAR_RE.search(text)
    if match:
        return match.group(0)
    return ""


def _language_parts(line: str) -> tuple[str, str]:
    """Split a language line into its name and its level."""
    match = _LEVEL_RE.search(line)
    if not match:
        return line.strip(), ""
    name = line[: match.start()].strip(" \t-–—:|,()")
    level = match.group(0).strip()
    if not name:
        name = line.strip()
    return name, level


def _education_parts(line: str) -> tuple[str, dict[str, str]]:
    """Return the education label and the structured detail found in a line."""
    match = _DEGREE_RE.search(line)
    meta: dict[str, str] = {}
    label = line
    if match:
        meta["diploma"] = match.group(0)
    year = _detect_date(line)
    if year:
        meta["date"] = year
    if len(label) > MAX_LABEL_CHARS:
        label = label[:MAX_LABEL_CHARS].rstrip()
    return label, meta


def _make_fact(
    *,
    kind: str,
    label: str,
    value: str,
    text: str,
    start: int,
    end: int,
    spans: Sequence[PageSpan],
    source: str,
    source_method: str,
    filename: str,
    batch_id: str,
    created_at: str,
    meta: dict[str, str] | None = None,
) -> Fact:
    """Build one proposed fact with its exact provenance."""
    page, confidence = page_for_offset(spans, start)
    return Fact(
        id=f"fact_{uuid.uuid4().hex}",
        kind=kind,
        label=label[:MAX_LABEL_CHARS],
        value=value[:MAX_VALUE_CHARS],
        status=STATUS_PROPOSED,
        evidence=Evidence(
            source=source,
            page=page,
            page_confidence=confidence,
            start_offset=start,
            end_offset=end,
            quote=_quote(text, start, end),
            filename=filename,
        ),
        original_label="",
        original_value="",
        meta=dict(meta or {}),
        note="",
        source_document=filename,
        source_method=source_method,
        batch_id=batch_id,
        created_at=created_at,
        updated_at=created_at,
        decided_at="",
    )


def _is_section_title(item_text: str, section_title: str) -> bool:
    """True when a line is only the title of its own section."""
    normalized = normalize_text(item_text)
    if not normalized:
        return True
    title = normalize_text(section_title)
    return bool(title) and normalized == title


def _skill_facts(
    text: str,
    section_start: int,
    section_end: int,
    section_title: str,
    *,
    spans: Sequence[PageSpan],
    source: str,
    source_method: str,
    filename: str,
    batch_id: str,
    created_at: str,
) -> list[Fact]:
    facts: list[Fact] = []
    for item in _section_items(text, section_start, section_end, split_lists=True):
        label = item.text.strip()
        if not label or len(label) > MAX_SKILL_CHARS:
            continue
        normalized = normalize_text(label)
        if not normalized or normalized in _SKILL_STOP_LABELS:
            continue
        if _is_section_title(label, section_title):
            continue
        facts.append(
            _make_fact(
                kind=KIND_SKILL,
                label=label,
                value="",
                text=text,
                start=item.start,
                end=item.end,
                spans=spans,
                source=source,
                source_method=source_method,
                filename=filename,
                batch_id=batch_id,
                created_at=created_at,
            )
        )
    return facts


def _language_facts(
    text: str,
    section_start: int,
    section_end: int,
    section_title: str,
    *,
    spans: Sequence[PageSpan],
    source: str,
    source_method: str,
    filename: str,
    batch_id: str,
    created_at: str,
) -> list[Fact]:
    facts: list[Fact] = []
    for item in _section_items(text, section_start, section_end, split_lists=False):
        line = item.text.strip()
        if not line or len(line) > MAX_ITEM_CHARS:
            continue
        if _is_section_title(line, section_title):
            continue
        name, level = _language_parts(line)
        if not name:
            continue
        facts.append(
            _make_fact(
                kind=KIND_LANGUAGE,
                label=name,
                value=level,
                text=text,
                start=item.start,
                end=item.end,
                spans=spans,
                source=source,
                source_method=source_method,
                filename=filename,
                batch_id=batch_id,
                created_at=created_at,
                meta={"level": level} if level else {},
            )
        )
    return facts


def _education_facts(
    text: str,
    section_start: int,
    section_end: int,
    section_title: str,
    *,
    spans: Sequence[PageSpan],
    source: str,
    source_method: str,
    filename: str,
    batch_id: str,
    created_at: str,
) -> list[Fact]:
    facts: list[Fact] = []
    for item in _section_items(text, section_start, section_end, split_lists=False):
        line = item.text.strip()
        if not line or len(line) > MAX_ITEM_CHARS:
            continue
        if _is_section_title(line, section_title):
            continue
        label, meta = _education_parts(line)
        facts.append(
            _make_fact(
                kind=KIND_EDUCATION,
                label=label,
                value="",
                text=text,
                start=item.start,
                end=item.end,
                spans=spans,
                source=source,
                source_method=source_method,
                filename=filename,
                batch_id=batch_id,
                created_at=created_at,
                meta=meta,
            )
        )
        date_value = str(meta.get("date", ""))
        if date_value:
            facts.append(
                _make_fact(
                    kind=KIND_DATE,
                    label=date_value,
                    value="",
                    text=text,
                    start=item.start,
                    end=item.end,
                    spans=spans,
                    source=source,
                    source_method=source_method,
                    filename=filename,
                    batch_id=batch_id,
                    created_at=created_at,
                    meta={"context": "formation"},
                )
            )
    return facts


def _experience_entries(text: str, section_start: int, section_end: int) -> list[_Entry]:
    """Split the Expérience section into entries, one per dated header line.

    The Mission 01 structure engine also parses experiences, but it also
    applies a Canva-specific recovery heuristic.  The fact pipeline needs a
    predictable, offset-exact reading, so the entries are read here.
    """
    entries: list[_Entry] = []
    current: _Entry | None = None
    for item in _section_items(text, section_start, section_end, split_lists=False):
        line = item.text.strip()
        if not line or len(line) > MAX_ITEM_CHARS:
            continue
        if _DATE_RANGE_RE.search(line) or _YEAR_RE.search(line):
            parts = [part.strip() for part in line.split("|") if part.strip()]
            dated = [part for part in parts if _YEAR_RE.search(part)]
            others = [part for part in parts if part not in dated]
            role = others[0] if others else ""
            company = others[1] if len(others) > 1 else ""
            if current is not None:
                entries.append(current)
            current = _Entry(
                role=role,
                company=company,
                dates=_detect_date(line),
                result="",
                start=item.start,
                end=item.end,
            )
            continue
        if current is None:
            continue
        result = current.result or line
        if len(result) > MAX_FACT_DESCRIPTION_CHARS:
            result = result[:MAX_FACT_DESCRIPTION_CHARS].rstrip()
        current = _Entry(
            role=current.role,
            company=current.company,
            dates=current.dates,
            result=result,
            start=current.start,
            end=item.end,
        )
    if current is not None:
        entries.append(current)
    return entries


def _experience_facts(
    text: str,
    section_start: int,
    section_end: int,
    section_title: str,
    *,
    spans: Sequence[PageSpan],
    source: str,
    source_method: str,
    filename: str,
    batch_id: str,
    created_at: str,
) -> list[Fact]:
    facts: list[Fact] = []
    for entry in _experience_entries(text, section_start, section_end):
        if _is_section_title(entry.role, section_title) and not entry.result:
            continue
        if not entry.role and not entry.company and not entry.result:
            continue
        meta = {
            "company": entry.company,
            "role": entry.role,
            "dates": entry.dates,
            "result": entry.result,
        }
        facts.append(
            _make_fact(
                kind=KIND_EXPERIENCE,
                label=entry.role or entry.company or "Expérience",
                value="",
                text=text,
                start=entry.start,
                end=entry.end,
                spans=spans,
                source=source,
                source_method=source_method,
                filename=filename,
                batch_id=batch_id,
                created_at=created_at,
                meta=meta,
            )
        )
        if entry.dates:
            facts.append(
                _make_fact(
                    kind=KIND_DATE,
                    label=entry.dates,
                    value="",
                    text=text,
                    start=entry.start,
                    end=entry.end,
                    spans=spans,
                    source=source,
                    source_method=source_method,
                    filename=filename,
                    batch_id=batch_id,
                    created_at=created_at,
                    meta={"context": "experience"},
                )
            )
    return facts


def _simple_facts(
    text: str,
    kind: str,
    section_start: int,
    section_end: int,
    section_title: str,
    *,
    spans: Sequence[PageSpan],
    source: str,
    source_method: str,
    filename: str,
    batch_id: str,
    created_at: str,
) -> list[Fact]:
    facts: list[Fact] = []
    for item in _section_items(text, section_start, section_end, split_lists=False):
        label = item.text.strip()
        if not label or len(label) > MAX_ITEM_CHARS:
            continue
        if _is_section_title(label, section_title):
            continue
        facts.append(
            _make_fact(
                kind=kind,
                label=label,
                value="",
                text=text,
                start=item.start,
                end=item.end,
                spans=spans,
                source=source,
                source_method=source_method,
                filename=filename,
                batch_id=batch_id,
                created_at=created_at,
            )
        )
    return facts


def _contact_facts(
    text: str,
    *,
    spans: Sequence[PageSpan],
    source: str,
    source_method: str,
    filename: str,
    batch_id: str,
    created_at: str,
) -> list[Fact]:
    """Propose the contact details written in the document, with their source."""
    facts: list[Fact] = []
    email_match = _EMAIL_RE.search(text)
    if email_match:
        email = email_match.group(0).strip(".,;:!?()[]{}").lower()
        facts.append(
            _make_fact(
                kind=KIND_CONTACT,
                label="E-mail",
                value=email,
                text=text,
                start=email_match.start(),
                end=email_match.end(),
                spans=spans,
                source=source,
                source_method=source_method,
                filename=filename,
                batch_id=batch_id,
                created_at=created_at,
                meta={"field": "contact_email"},
            )
        )
    for match in _PHONE_RE.finditer(text):
        candidate = re.sub(r"\s+", " ", match.group(0)).strip(" .-–—")
        digits = re.sub(r"\D", "", candidate)
        if not 9 <= len(digits) <= 15:
            continue
        if _YEAR_RANGE_ONLY.match(candidate):
            continue
        if len(set(digits)) == 1:
            continue
        facts.append(
            _make_fact(
                kind=KIND_CONTACT,
                label="Téléphone",
                value=candidate,
                text=text,
                start=match.start(),
                end=match.end(),
                spans=spans,
                source=source,
                source_method=source_method,
                filename=filename,
                batch_id=batch_id,
                created_at=created_at,
                meta={"field": "contact_phone"},
            )
        )
        break
    return facts


def build_fact_proposals(
    text: str,
    *,
    filename: str = "",
    source_method: str = SOURCE_EMBEDDED_TEXT,
    pages: Sequence[str] | None = None,
    page_count: int | None = None,
    page_confidence: str = "exact",
    batch_id: str = "",
    created_at: str = "",
) -> list[Fact]:
    """Turn one extracted document into the facts it proposes.

    Every returned fact has the ``proposed`` status — including the facts read
    by OCR.  Approval is a separate, explicit action of the person.
    """
    source_text = str(text or "")
    if not source_text.strip():
        return []

    batch = batch_id or f"batch_{uuid.uuid4().hex}"
    spans = page_spans(source_text, pages, page_count, page_confidence=page_confidence)
    analysis = analyze_cv(
        DocumentInput(text=source_text, filename=filename or None, filetype="txt")
    )

    facts: list[Fact] = []
    facts.extend(
        _contact_facts(
            source_text,
            spans=spans,
            source=source_method,
            source_method=source_method,
            filename=filename,
            batch_id=batch,
            created_at=created_at,
        )
    )
    for section in analysis.sections:
        kind = SECTION_KINDS.get(section.title)
        if not kind:
            continue
        start = int(section.start_offset)
        end = int(section.end_offset)
        common = {
            "spans": spans,
            "source": source_method,
            "source_method": source_method,
            "filename": filename,
            "batch_id": batch,
            "created_at": created_at,
        }
        if kind == KIND_SKILL:
            facts.extend(
                _skill_facts(source_text, start, end, section.title, **common)
            )
        elif kind == KIND_LANGUAGE:
            facts.extend(_language_facts(source_text, start, end, section.title, **common))
        elif kind == KIND_EDUCATION:
            facts.extend(_education_facts(source_text, start, end, section.title, **common))
        elif kind == KIND_EXPERIENCE:
            facts.extend(_experience_facts(source_text, start, end, section.title, **common))
        else:
            facts.extend(_simple_facts(source_text, kind, start, end, section.title, **common))

    # Bounded proposals: a very long document never floods the review screen.
    # A kind that reached its own cap is skipped, never fatal: the other
    # sections of the document still deserve their review.
    per_kind: dict[str, int] = {}
    bounded: list[Fact] = []
    for fact in facts:
        count = per_kind.get(fact.kind, 0)
        if count >= MAX_FACTS_PER_KIND:
            continue
        if len(bounded) >= MAX_FACTS_TOTAL:
            break
        per_kind[fact.kind] = count + 1
        bounded.append(fact)

    # Structural guarantee: the builder never approves anything.
    if any(fact.status != STATUS_PROPOSED for fact in bounded):
        raise RuntimeError("Un fait proposé ne peut pas être approuvé automatiquement.")
    return bounded


def source_is_ocr(source_method: str) -> bool:
    """True when the facts come from a local OCR reading."""
    return str(source_method or "") == SOURCE_OCR


def summarize_proposals(facts: Iterable[Fact]) -> dict[str, Any]:
    """Return a small, JSON-safe summary of a proposal batch."""
    materialized = list(facts)
    by_kind: dict[str, int] = {}
    for fact in materialized:
        by_kind[fact.kind] = by_kind.get(fact.kind, 0) + 1
    return {
        "count": len(materialized),
        "by_kind": by_kind,
        "requires_review": len(materialized),
        "ocr_source": any(source_is_ocr(fact.source_method) for fact in materialized),
        "note": (
            "Chaque fait proposé doit être validé, corrigé ou rejeté avant de "
            "pouvoir justifier une correspondance ou une candidature."
        ),
    }
