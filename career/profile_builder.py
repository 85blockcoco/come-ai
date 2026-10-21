"""Local pipeline turning one document into reviewable candidate facts.

The pipeline is deterministic and fully local:

    document bytes (PDF / DOCX / TXT) or pasted text
        → local text extraction (Mission 01 parser)
        → local OCR when the document has no usable text layer
        → sections and items detected in the text
        → facts proposed, each one carrying its exact source

Two rules never bend here:

* extraction only *proposes*.  Every fact starts as ``proposed``: nothing is
  approved without an explicit user action;
* a fact always keeps the passage it comes from.  The quote is the exact
  substring of the document text, and the offsets point at it.  A quote that
  does not match the document is a bug, and
  :func:`career.candidate_profile.verify_fact` proves it.

No network, no model, no clock read: the caller injects the timestamp.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from .candidate_profile import (
    EXTRACTION_OCR,
    EXTRACTION_TEXT_LAYER,
    KIND_CONTACT,
    KIND_DATE,
    KIND_EDUCATION,
    KIND_EXPERIENCE,
    KIND_LANGUAGE,
    KIND_SKILL,
    ProfileFact,
    Provenance,
    SourceDocument,
    make_fact_id,
)
from .cv_quality.parser import extract_pages_from_bytes
from .models import clean_text


#: A document whose text layer is shorter than this is considered scanned:
#: the local OCR is used instead of proposing facts from an empty layer.
MIN_TEXT_LAYER_CHARS = 120

#: Upper bound of proposed facts for one document: a CV is not a data dump.
MAX_PROPOSED_FACTS = 400

#: Maximum length of the quoted passage kept with a fact.
MAX_QUOTE_CHARS = 240

#: Maximum length of a fact label.
MAX_LABEL_CHARS = 120


def _normalised(value: str) -> str:
    """Return a comparable form of a heading (no accent, no punctuation)."""
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "skills": (
        "competences",
        "competence",
        "competences techniques",
        "competences cles",
        "savoir faire",
        "expertise",
        "skills",
        "technical skills",
        "core skills",
        "key skills",
        "technologies",
    ),
    "experience": (
        "experience",
        "experiences",
        "experience professionnelle",
        "experiences professionnelles",
        "parcours professionnel",
        "professional experience",
        "work experience",
        "employment history",
        "career history",
    ),
    "education": (
        "formation",
        "formations",
        "education",
        "etudes",
        "parcours academique",
        "diplomes",
        "diploma",
        "diplomas",
        "degrees",
        "academic background",
        "academic qualifications",
    ),
    "languages": (
        "langues",
        "langue",
        "languages",
        "language skills",
    ),
}

_SECTION_BY_ALIAS: dict[str, str] = {
    _normalised(alias): section
    for section, aliases in _SECTION_ALIASES.items()
    for alias in aliases
}

_MONTHS = (
    "janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre"
    "|january|february|march|april|may|june|july|august|september|october|november|december"
)

#: A date written the way people write dates on a CV.
_DATE_RE = re.compile(
    r"(?P<value>"
    r"\b(?:" + _MONTHS + r")\.?\s+\d{4}\b"
    r"|\b\d{1,2}[/.-]\d{4}\b"
    r"|\b\d{4}[/.-]\d{1,2}\b"
    r"|\b(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)?\d{2}\b"
    r"|\b(?:19|20)\d{2}\b"
    r")",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")

_PHONE_RE = re.compile(r"(?<![\w+])(?:\+?\d[\d .\-()]{6,}\d)(?!\w)")

_LINKEDIN_RE = re.compile(
    r"(?i)(?:https?://)?(?:(?:[a-z]{2,3}|www)\.)?linkedin\.com/(?:in|pub)/[^\s,;]+"
)

#: Separators used between two items of the same line.
_ITEM_SEPARATOR_RE = re.compile(r"\s*(?:,|;|\||•|·|\u2022)\s*")

#: Separators used between a role and its company or its dates.
_ROLE_SEPARATOR_RE = re.compile(
    r"\s+(?:-|–|—|\||@|chez |at )\s+|\s*[|:]\s+",
    re.IGNORECASE,
)

#: Bullet markers that start a line of a section.
_BULLET_RE = re.compile(r"^\s*(?:[-*•·‣▪]|\d+[.)])\s+")


@dataclass(frozen=True, slots=True)
class PageSpan:
    """Where a page starts and ends in the full document text."""

    page_number: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class OcrOutcome:
    """The result of the local OCR, when the document had no usable text.

    Attributes:
        text: The text read by the OCR.
        pages: Number of pages read, when the OCR knows it.
        warnings: Bounded warnings shown to the user.
    """

    text: str
    pages: int = 0
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LineSpan:
    """One line of the document, with its exact position."""

    text: str
    start: int
    end: int
    page: int | None


def _page_spans(pages: Sequence[tuple[int, str]]) -> tuple[str, tuple[PageSpan, ...]]:
    """Return the joined text and the span of every page inside it."""
    texts: list[str] = []
    spans: list[PageSpan] = []
    cursor = 0
    for page_number, page_text in pages:
        if texts:
            cursor += 2  # the blank line joining two pages
        spans.append(PageSpan(page_number=page_number, start=cursor, end=cursor + len(page_text)))
        texts.append(page_text)
        cursor += len(page_text)
    return "\n\n".join(texts), tuple(spans)


def document_id_for(sha256: str) -> str:
    """Return the deterministic identifier of a source document."""
    return "doc_" + hashlib.sha256(str(sha256 or "").encode("utf-8")).hexdigest()[:16]


def build_source_document(
    *,
    filename: str,
    filetype: str,
    data: bytes | None = None,
    text: str | None = None,
    ocr_provider: Callable[[], OcrOutcome] | None = None,
    created_at: str = "",
) -> tuple[SourceDocument, tuple[PageSpan, ...]]:
    """Extract a document locally and return it with its page spans.

    The text layer is used first.  When it is missing or too short, the local
    OCR is used instead -- and the document is then marked as ``ocr``, which
    forbids any automatic approval of the facts read from it.

    Args:
        filename: Original filename.
        filetype: ``pdf``, ``docx`` or ``txt``.
        data: Raw bytes of the document.
        text: Text pasted by the user (used instead of ``data``).
        ocr_provider: Called when the document has no usable text layer.
        created_at: Timestamp injected by the caller.

    Returns:
        Tuple of (source document, page spans of its text).
    """
    safe_filename = clean_text(filename, limit=256) or "document-profil"
    pages: list[tuple[int, str]] = []
    page_count: int | None = None
    extraction = EXTRACTION_TEXT_LAYER

    if text is not None:
        raw_text = str(text)
        pages = [(1, raw_text)]
        page_count = max(1, (len(raw_text) // 3000) + 1)
        digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    else:
        payload = bytes(data or b"")
        try:
            extracted_pages, page_count = extract_pages_from_bytes(payload, filetype, safe_filename)
        except ValueError:
            # A document the local parser cannot read may still be readable by
            # the local OCR: the empty text below asks for it.
            extracted_pages, page_count = [], None
        pages = [(page.page_number, page.text) for page in extracted_pages]
        digest = hashlib.sha256(payload).hexdigest()

    joined, spans = _page_spans(pages)

    if len(joined.strip()) < MIN_TEXT_LAYER_CHARS and ocr_provider is not None:
        outcome = ocr_provider()
        ocr_text = str(outcome.text or "")
        if ocr_text.strip():
            joined = ocr_text
            spans = (PageSpan(page_number=1, start=0, end=len(ocr_text)),)
            extraction = EXTRACTION_OCR
            digest = hashlib.sha256(ocr_text.encode("utf-8")).hexdigest()

    if not joined.strip():
        raise ValueError("Le document ne contient aucun texte exploitable.")

    document = SourceDocument(
        document_id=document_id_for(digest),
        filename=safe_filename,
        filetype=filetype,
        page_count=page_count,
        text=joined,
        extraction=extraction,
        sha256=digest,
        created_at=clean_text(created_at, limit=64),
    )
    return document, spans


def _page_of(spans: Sequence[PageSpan], offset: int) -> int | None:
    """Return the page number of an offset, when it is known."""
    for span in spans:
        if span.start <= offset < span.end:
            return span.page_number
    return None


def _lines_with_offsets(text: str, spans: Sequence[PageSpan]) -> list[LineSpan]:
    """Split the document text into lines, keeping the exact offsets."""
    lines: list[LineSpan] = []
    start = 0
    length = len(text)
    while start <= length:
        newline = text.find("\n", start)
        end = length if newline == -1 else newline
        content = text[start:end]
        if content.strip():
            lines.append(
                LineSpan(
                    text=content,
                    start=start,
                    end=end,
                    page=_page_of(spans, start),
                )
            )
        if newline == -1:
            break
        start = newline + 1
    return lines


def _section_of(line: str) -> tuple[str, str] | None:
    """Return the section a line opens, with its inline content if any."""
    candidate = line.strip()
    if not candidate:
        return None
    section = _SECTION_BY_ALIAS.get(_normalised(candidate))
    if section:
        return section, ""
    for separator in (":", "—", "–", "-"):
        if separator not in candidate:
            continue
        head, tail = candidate.split(separator, 1)
        section = _SECTION_BY_ALIAS.get(_normalised(head))
        if section:
            return section, tail.strip()
    return None


def _split_items(text: str, base: int, start: int, end: int) -> list[tuple[str, int, int]]:
    """Split a region of a line into items, keeping the exact offsets.

    ``text`` is the line, ``base`` the absolute offset of that line in the
    document, and ``start``/``end`` the region to split, relative to the line.
    """
    bullet = _BULLET_RE.match(text[start:end])
    if bullet:
        start += bullet.end()
    region = text[start:end]
    items: list[tuple[str, int, int]] = []
    cursor = 0
    for match in _ITEM_SEPARATOR_RE.finditer(region):
        chunk = region[cursor : match.start()]
        stripped = chunk.strip()
        if stripped:
            leading = len(chunk) - len(chunk.lstrip())
            items.append((stripped, base + start + cursor + leading, base + start + cursor + leading + len(stripped)))
        cursor = match.end()
    chunk = region[cursor:]
    stripped = chunk.strip()
    if stripped:
        leading = len(chunk) - len(chunk.lstrip())
        items.append((stripped, base + start + cursor + leading, base + start + cursor + leading + len(stripped)))
    return items


def _label_for(text: str, *, limit: int = MAX_LABEL_CHARS) -> str:
    """Return a short readable label for a passage."""
    return clean_text(text, limit=limit)


def _language_label(item: str) -> tuple[str, dict[str, str]]:
    """Split ``Anglais — C1`` into a language and its level."""
    match = re.match(
        r"^(?P<language>[^(\-–—:|]+?)\s*(?:[-–—:]\s*|\(\s*)(?P<level>[^)]+)\)?$",
        item.strip(),
    )
    if not match:
        return item.strip(), {}
    language = match.group("language").strip()
    level = match.group("level").strip()
    if not language or not level:
        return item.strip(), {}
    return language, {"level": level}


def _date_role(item: str, match: re.Match[str]) -> str:
    """Return whether a date looks like a start or an end date."""
    prefix = item[: match.start()].lower()
    if any(token in prefix for token in ("depuis", "from", "à partir de")):
        return "start"
    if any(token in prefix for token in ("jusqu", "to")):
        return "end"
    return "date"


def _bounded_end(document: SourceDocument, start: int, end: int) -> int:
    """Return the end of a passage, bounded so the quote stays readable."""
    limit = min(end, start + MAX_QUOTE_CHARS, len(document.text))
    return max(start, limit)


def _build_fact(
    *,
    kind: str,
    label: str,
    value: str,
    document: SourceDocument,
    page: int | None,
    start: int,
    end: int,
    attributes: dict[str, str] | None = None,
    created_at: str = "",
) -> ProfileFact:
    """Build one proposed fact with its exact provenance."""
    end = _bounded_end(document, start, end)
    quote = document.text[start:end]
    provenance = Provenance(
        source_id=document.document_id,
        filename=document.filename,
        filetype=document.filetype,
        page=page,
        start_offset=start,
        end_offset=end,
        quote=quote,
        extraction=document.extraction,
        source_sha256=document.sha256,
    )
    fact_id = make_fact_id(kind, label, document.document_id, start)
    return ProfileFact(
        fact_id=fact_id,
        kind=kind,
        label=label,
        value=value,
        status="proposed",
        provenance=provenance,
        attributes=attributes or {},
        created_at=created_at,
        updated_at=created_at,
    )


def _entry_label(text: str) -> str:
    """Return the readable label of an experience or education line.

    A leading date is dropped: the label names the role or the diploma, not
    the period, which is proposed as its own dated fact.
    """
    cleaned = str(text or "").strip()
    leading_date = _DATE_RE.match(cleaned)
    if leading_date:
        cleaned = cleaned[leading_date.end() :].strip(" -–—:|")
    segments = [segment.strip() for segment in _ROLE_SEPARATOR_RE.split(cleaned) if segment.strip()]
    return segments[0] if segments else cleaned


def _facts_from_item(
    *,
    section: str,
    item: str,
    item_start: int,
    item_end: int,
    page: int | None,
    document: SourceDocument,
    created_at: str = "",
) -> list[ProfileFact]:
    """Turn one item of a section into facts."""
    cleaned = clean_text(item, limit=600)
    if not cleaned:
        return []

    if section == "skills":
        return [
            _build_fact(
                kind=KIND_SKILL,
                label=_label_for(cleaned),
                value=cleaned,
                document=document,
                page=page,
                start=item_start,
                end=item_end,
                created_at=created_at,
            )
        ]

    if section == "languages":
        language, attributes = _language_label(cleaned)
        return [
            _build_fact(
                kind=KIND_LANGUAGE,
                label=_label_for(language),
                value=language,
                document=document,
                page=page,
                start=item_start,
                end=item_end,
                attributes=attributes,
                created_at=created_at,
            )
        ]

    kind = KIND_EXPERIENCE if section == "experience" else KIND_EDUCATION
    facts = [
        _build_fact(
            kind=kind,
            label=_label_for(_entry_label(cleaned)),
            value=cleaned,
            document=document,
            page=page,
            start=item_start,
            end=item_end,
            created_at=created_at,
        )
    ]

    for match in _DATE_RE.finditer(cleaned):
        value = clean_text(match.group("value"), limit=60)
        if not value:
            continue
        date_start = item_start + match.start()
        facts.append(
            _build_fact(
                kind=KIND_DATE,
                label=_label_for(value),
                value=value,
                document=document,
                page=page,
                start=date_start,
                end=date_start + len(value),
                attributes={"context": section, "role": _date_role(cleaned, match)},
                created_at=created_at,
            )
        )
    return facts


def _looks_like_year_group(value: str) -> bool:
    """Return whether a number is a group of years rather than a phone number."""
    parts = [part for part in re.split(r"[\s.\-()]+", value) if part]
    if not parts:
        return False
    return all(re.fullmatch(r"(?:19|20)\d{2}", part) for part in parts)


def _facts_from_contacts(
    *,
    line: LineSpan,
    document: SourceDocument,
    created_at: str = "",
) -> list[ProfileFact]:
    """Propose contact facts found outside any section."""
    facts: list[ProfileFact] = []
    text = line.text
    for match in _EMAIL_RE.finditer(text):
        value = clean_text(match.group(0), limit=160)
        facts.append(
            _build_fact(
                kind=KIND_CONTACT,
                label="E-mail",
                value=value,
                document=document,
                page=line.page,
                start=line.start + match.start(),
                end=line.start + match.end(),
                attributes={"channel": "email"},
                created_at=created_at,
            )
        )
    for match in _PHONE_RE.finditer(text):
        candidate = match.group(0)
        if _looks_like_year_group(candidate):
            continue
        digits = re.sub(r"\D", "", candidate)
        if not 7 <= len(digits) <= 15:
            continue
        value = clean_text(candidate, limit=40)
        facts.append(
            _build_fact(
                kind=KIND_CONTACT,
                label="Téléphone",
                value=value,
                document=document,
                page=line.page,
                start=line.start + match.start(),
                end=line.start + match.end(),
                attributes={"channel": "phone"},
                created_at=created_at,
            )
        )
    for match in _LINKEDIN_RE.finditer(text):
        value = clean_text(match.group(0), limit=200)
        facts.append(
            _build_fact(
                kind=KIND_CONTACT,
                label="LinkedIn",
                value=value,
                document=document,
                page=line.page,
                start=line.start + match.start(),
                end=line.start + match.end(),
                attributes={"channel": "linkedin"},
                created_at=created_at,
            )
        )
    return facts


def propose_facts(
    document: SourceDocument,
    spans: Sequence[PageSpan],
    *,
    created_at: str = "",
) -> tuple[ProfileFact, ...]:
    """Propose the facts of one document.

    Every returned fact has the ``proposed`` status: extraction never
    approves anything, and an OCR document is marked as such in the
    provenance of each fact.
    """
    facts: list[ProfileFact] = []
    lines = _lines_with_offsets(document.text, spans)
    section = ""
    seen: set[str] = set()

    for line in lines:
        heading = _section_of(line.text)
        if heading is not None:
            section, inline = heading
            if inline:
                offset = line.text.find(inline)
                if offset != -1:
                    for item, start, end in _split_items(
                        line.text, line.start, offset, offset + len(inline)
                    ):
                        facts.extend(
                            _facts_from_item(
                                section=section,
                                item=item,
                                item_start=start,
                                item_end=end,
                                page=line.page,
                                document=document,
                                created_at=created_at,
                            )
                        )
            continue
        if not section:
            facts.extend(
                _facts_from_contacts(
                    line=line,
                    document=document,
                    created_at=created_at,
                )
            )
            continue
        for item, start, end in _split_items(line.text, line.start, 0, len(line.text)):
            facts.extend(
                _facts_from_item(
                    section=section,
                    item=item,
                    item_start=start,
                    item_end=end,
                    page=line.page,
                    document=document,
                    created_at=created_at,
                )
            )

    unique: list[ProfileFact] = []
    for fact in facts:
        if fact.fact_id in seen:
            continue
        seen.add(fact.fact_id)
        unique.append(fact)
        if len(unique) >= MAX_PROPOSED_FACTS:
            break
    unique.sort(key=lambda fact: (fact.provenance.start_offset, fact.kind))
    return tuple(unique)


def build_profile(
    document: SourceDocument,
    spans: Sequence[PageSpan],
    *,
    created_at: str = "",
) -> tuple[ProfileFact, ...]:
    """Return the facts proposed for one document (never approved)."""
    return propose_facts(document, spans, created_at=created_at)


def summarise_facts(facts: Iterable[ProfileFact]) -> dict[str, Any]:
    """Return a bounded summary of a set of facts."""
    facts = tuple(facts)
    counts: dict[str, int] = {}
    for fact in facts:
        counts[fact.kind] = counts.get(fact.kind, 0) + 1
    return {
        "total": len(facts),
        "by_kind": counts,
        "approvable": sum(1 for fact in facts if fact.status == "proposed"),
        "ocr": sum(1 for fact in facts if fact.provenance.extraction == EXTRACTION_OCR),
    }
