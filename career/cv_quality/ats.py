"""Local ATS (Applicant Tracking System) risk analysis for CV documents.

Purely local — no network, no LLM, no API key. The module analyses the
*exported* document (PDF / DOCX / TXT) and reports **ATS risks**, never a
binary "pass/fail" verdict and never a "certain rejection" claim.

Nine detectors are implemented (see `run_ats_check`):

1. `READING_ORDER`    — non linear text flow (columns, boxes, mid-page headers)
2. `TEXT_IN_IMAGES`   — text stored as images (scanned / flattened document)
3. `NESTED_TABLE`     — tabular structures that break linear extraction
4. `MULTIPLE_COLUMNS` — multi column layout
5. `HEADER_FOOTER`    — repeated header/footer polluting the extraction
6. `DECORATIVE_CHARS` — ligatures / decorative glyphs that may not be mapped
7. `UNREADABLE_LINKS` — raw URLs printed instead of an anchor text
8. `MISSING_SECTION`  — expected section headings invisible to the ATS
9. `PARSE_ERROR`      — encrypted / malformed file (extraction impossible)

Each detector returns `ATSFinding` objects carrying a `risk_level`
(LOW / MEDIUM / HIGH), a `page`, an approximate `bbox` and a verifiable
`evidence_excerpt`. The global score is the weighted sum of the findings
(LOW=5, MEDIUM=20, HIGH=50) capped at 100.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ATSCheckResult, ATSFinding, ATSRiskLevel, DocumentInput

__all__ = [
    "run_ats_check",
    "run_ats_check_bytes",
    "run_ats_check_file",
    "detect_reading_order",
    "detect_text_in_images",
    "detect_nested_tables",
    "detect_multiple_columns",
    "detect_headers_footers",
    "detect_decorative_chars",
    "detect_unreadable_links",
    "detect_missing_sections",
    "detect_parse_errors",
    "risk_interpretation",
    "PageLayout",
    "TextChunk",
    "TableInfo",
]


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Weighted scoring — LOW=5, MEDIUM=20, HIGH=50 (sum capped at 100).
RISK_WEIGHTS: dict[ATSRiskLevel, int] = {
    "LOW": 5,
    "MEDIUM": 20,
    "HIGH": 50,
}

# Score thresholds used to derive the global label.
SCORE_MEDIUM_THRESHOLD = 25
SCORE_HIGH_THRESHOLD = 60

# User facing interpretation of each label (prudent wording).
RISK_INTERPRETATIONS: dict[str, str] = {
    "LOW": "Faible risque",
    "MEDIUM": "Risque modéré — relecture conseillée",
    "HIGH": "Risque élevé — restructuration recommandée",
}

# Expected section keywords (FR/EN) — aligned with cv_quality.structure.
SECTION_KEYWORDS: dict[str, list[str]] = {
    "Expérience": [
        "experience", "experiences", "experience professionnelle",
        "work experience", "professional experience", "employment",
        "emploi", "emplois", "parcours professionnel", "career",
        "carriere", "experiencia",
    ],
    "Formation": [
        "formation", "formations", "education", "etudes", "diplomes",
        "degrees", "academic", "scolarite", "cursus", "formacion",
    ],
    "Compétences": [
        "competences", "skills", "competencies", "technical skills",
        "savoir-faire", "savoir faire", "expertise", "technologies",
        "stack", "hard skills",
    ],
    "Langues": [
        "langues", "languages", "language skills", "langue", "maitrise",
        "idiomas",
    ],
    "Projets": [
        "projets", "projects", "realisations", "achievements", "portfolio",
        "personal projects", "side projects", "proyectos",
    ],
    "Certifications": [
        "certifications", "certificates", "licenses", "licences",
        "credentials", "badges", "certificaciones",
    ],
    "Contact": [
        "contact", "coordonnees", "informations", "personal information",
    ],
}

# Sections checked when the caller does not provide any.
DEFAULT_EXPECTED_SECTIONS: list[str] = ["Expérience", "Formation", "Compétences"]

# Decorative glyphs / ligatures that some ATS parsers cannot map.
# Typographic punctuation (curly quotes, en/em dashes) is deliberately
# excluded: Word produces it on every export and it is not an ATS risk.
DECORATIVE_CHARS: dict[str, str] = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "•": "•",   # bullet
    "‣": "‣",   # triangular bullet
    "●": "●",   # black circle
    "◆": "◆",   # black diamond
    "■": "■",   # black square
    "▪": "▪",   # black small square
    "◦": "◦",   # white bullet
    "►": "►",   # right triangle
    "▸": "▸",   # small right triangle
    "➤": "➤",   # heavy right arrow
    "→": "→",   # right arrow
    "★": "★",   # black star
    "☆": "☆",   # white star
    "❖": "❖",   # black diamond minus white x
    "✦": "✦",   # black four pointed star
    "✧": "✧",   # white four pointed star
    "❯": "❯",   # heavy right angle quotation
    "‹": "‹",   # single left angle quote
    "›": "›",   # single right angle quote
}

# Raw URL printed in the visible text (instead of an anchor text).
URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>\"{}|\\^`\[\]]+", re.IGNORECASE)

# Geometry (PDF points, origin bottom-left).
HEADER_BAND_PT = 72.0       # top band considered as a running header
FOOTER_BAND_PT = 72.0       # bottom band considered as a running footer
COLUMN_GAP_PT = 24.0        # horizontal gap above which two columns are distinct
LATERAL_JUMP_PT = 120.0     # horizontal move considered as a jump between columns
READING_JUMP_PT = 15.0      # vertical jump considered as a backward jump
TEXT_WIDTH_FACTOR = 0.5     # average glyph width factor (font_size * factor)

# Table detection.
MIN_TABLE_ROWS = 3          # aligned rows needed to conclude "tabular layout"
MIN_TABLE_COLS = 2          # separated blocks per row needed to conclude "tabular"

# Text-only fallbacks.
CHARS_PER_PAGE = 3000


# ──────────────────────────────────────────────────────────────────────
# Layout model
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TextChunk:
    """A positioned run of text.

    Attributes:
        text: The extracted text of the run.
        x: Horizontal position of the run (PDF points, origin left).
        y: Vertical position of the baseline (PDF points, origin bottom).
        size: Font size in points.
    """

    text: str
    x: float
    y: float
    size: float

    @property
    def width(self) -> float:
        """Estimated rendered width of the run."""
        return max(1.0, len(self.text) * self.size * TEXT_WIDTH_FACTOR)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Approximate bounding box of the run."""
        return (round(self.x, 2), round(self.y, 2), round(self.x + self.width, 2), round(self.y + self.size, 2))


@dataclass(frozen=True, slots=True)
class TableInfo:
    """A tabular structure detected on a page.

    Attributes:
        kind: "grid" (PDF aligned rows) or "native" (DOCX table object).
        bbox: Approximate bounding box when known.
        nested: True when the table is nested inside another table.
        detail: Short human readable detail used as evidence.
    """

    kind: str
    bbox: tuple[float, float, float, float] | None = None
    nested: bool = False
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PageContent:
    """Structured content of a single page.

    Attributes:
        page_num: 1-based page number.
        text: Flattened text of the page.
        chunks: Positioned text runs (empty for TXT / DOCX without layout).
        images: Bounding boxes of the images of the page.
        tables: Tabular structures detected on the page.
        width: Page width in points.
        height: Page height in points.
        header_texts: Running headers declared in the layout (DOCX).
        footer_texts: Running footers declared in the layout (DOCX).
        declared_columns: Number of columns declared in the layout (DOCX).
    """

    page_num: int
    text: str
    chunks: tuple[TextChunk, ...] = ()
    images: tuple[tuple[float, float, float, float], ...] = ()
    tables: tuple[TableInfo, ...] = ()
    width: float = 595.0
    height: float = 842.0
    header_texts: tuple[str, ...] = ()
    footer_texts: tuple[str, ...] = ()
    declared_columns: int = 1


# The public alias used by the detectors.
PageLayout = PageContent


# ──────────────────────────────────────────────────────────────────────
# PDF extraction (pypdf)
# ──────────────────────────────────────────────────────────────────────

def _pdf_chunks(page: Any) -> list[TextChunk]:
    """Collect the positioned text runs of a PDF page.

    pypdf exposes the text matrix through the `visitor_text` hook: the
    translation part of the matrix gives the position of the run on the page.
    """
    chunks: list[TextChunk] = []

    def visitor(text: str, cm: Any, tm: Any, font_dict: Any, font_size: Any) -> None:
        stripped = text.strip()
        if not stripped:
            return
        try:
            x = float(tm[4])
            y = float(tm[5])
            size = float(font_size or 0.0) or 10.0
        except (TypeError, ValueError, IndexError):
            return
        chunks.append(TextChunk(text=stripped, x=x, y=y, size=size))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return chunks
    return chunks


def _pdf_images(page: Any, width: float, height: float) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of the image XObjects of a PDF page.

    The exact position of an image inside the content stream is not exposed by
    pypdf: the page box is returned instead, which is enough to know that the
    page carries an image.
    """
    boxes: list[tuple[float, float, float, float]] = []
    try:
        resources = page.get("/Resources")
        xobjects = resources.get("/XObject") if resources else None
        if not xobjects:
            return boxes
        for name in xobjects:
            try:
                obj = xobjects[name].get_object()
            except Exception:
                continue
            if obj.get("/Subtype") == "/Image":
                boxes.append((0.0, 0.0, round(width, 2), round(height, 2)))
    except Exception:
        return boxes
    return boxes


def _extract_pdf_pages(data: bytes) -> tuple[list[PageContent], list[str]]:
    """Extract the layout of every page of a PDF (local only)."""
    errors: list[str] = []

    try:
        import pypdf
    except ImportError:  # pragma: no cover - dependency declared in requirements
        return [], ["PARSE_ERROR: pypdf indisponible pour l'extraction PDF"]

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as exc:
        return [], [f"PARSE_ERROR: PDF illisible ou corrompu : {exc}"]

    if getattr(reader, "is_encrypted", False):
        unlocked = False
        try:
            unlocked = bool(reader.decrypt(""))
        except Exception:
            unlocked = False
        if not unlocked:
            return [], ["PARSE_ERROR: PDF chiffré/protégé par mot de passe — extraction impossible"]

    pages: list[PageContent] = []
    for index, page in enumerate(reader.pages, 1):
        width, height = 595.0, 842.0
        try:
            mediabox = page.mediabox
            width = float(mediabox.width)
            height = float(mediabox.height)
        except Exception:
            pass

        chunks = _pdf_chunks(page)
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            errors.append(f"PARSE_ERROR: page {index} illisible : {exc}")
            text = "\n".join(chunk.text for chunk in chunks)

        tables = _pdf_tables(chunks)

        pages.append(
            PageContent(
                page_num=index,
                text=text,
                chunks=tuple(chunks),
                images=tuple(_pdf_images(page, width, height)),
                tables=tuple(tables),
                width=width,
                height=height,
            )
        )

    return pages, errors


def _pdf_tables(chunks: list[TextChunk]) -> list[TableInfo]:
    """Detect tabular layouts in a PDF page from the alignment of the runs."""
    if len(chunks) < MIN_TABLE_COLS * MIN_TABLE_ROWS:
        return []
    rows = _aligned_rows(chunks)
    tabular = [row for row in rows if len(row) >= MIN_TABLE_COLS]
    if len(tabular) < MIN_TABLE_ROWS:
        return []
    xs = [chunk.x for chunk in chunks]
    ys = [chunk.y for chunk in chunks]
    bbox = (round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2))
    return [
        TableInfo(
            kind="grid",
            bbox=bbox,
            nested=False,
            detail=f"{len(tabular)} lignes alignées sur {len(tabular[0])} colonnes",
        )
    ]


# ──────────────────────────────────────────────────────────────────────
# DOCX extraction (python-docx)
# ──────────────────────────────────────────────────────────────────────

def _docx_section_columns(doc: Any) -> int:
    """Number of text columns declared in the section properties."""
    from docx.oxml.ns import qn

    columns = 1
    for section in doc.sections:
        try:
            cols = section._sectPr.findall(qn("w:cols"))  # noqa: SLF001 - no public accessor
        except Exception:
            continue
        for col in cols:
            try:
                number = int(col.get(qn("w:num")) or 1)
            except (TypeError, ValueError):
                number = 1
            if number > 1:
                columns = max(columns, number)
    return columns


def _docx_header_footer_text(doc: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Header and footer texts declared in the sections of the document."""
    headers: list[str] = []
    footers: list[str] = []
    for section in doc.sections:
        try:
            header = " ".join(p.text.strip() for p in section.header.paragraphs if p.text.strip())
            footer = " ".join(p.text.strip() for p in section.footer.paragraphs if p.text.strip())
        except Exception:
            continue
        if header:
            headers.append(header)
        if footer:
            footers.append(footer)
    return tuple(headers), tuple(footers)


def _docx_table_info(table: Any) -> tuple[bool, int]:
    """Return (nested, row_count) for a python-docx table."""
    nested = False
    rows = 0
    try:
        rows = len(table.rows)
    except Exception:
        rows = 0
    try:
        for row in table.rows:
            for cell in row.cells:
                if getattr(cell, "tables", None):
                    nested = True
                    break
            if nested:
                break
    except Exception:
        pass
    return nested, rows


def _docx_page_break(paragraph: Any) -> bool:
    """Detect an explicit page break inside a DOCX paragraph."""
    try:
        xml = paragraph._p.xml  # noqa: SLF001 - no public accessor
    except Exception:
        return False
    return 'w:type="page"' in xml or "lastRenderedPageBreak" in xml


def _iter_docx_blocks(doc: Any) -> list[tuple[str, Any]]:
    """Return the paragraphs and the tables of a DOCX body, in document order."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    items: list[tuple[str, Any]] = []
    try:
        body = doc.element.body
    except Exception:
        return items
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            items.append(("p", Paragraph(child, doc)))
        elif child.tag == qn("w:tbl"):
            items.append(("tbl", Table(child, doc)))
    return items


def _extract_docx_pages(data: bytes) -> tuple[list[PageContent], list[str]]:
    """Extract the layout of a DOCX (local only).

    DOCX has no native page boundaries: explicit page breaks are honoured,
    otherwise the document is treated as a single page.
    """
    try:
        import docx
    except ImportError:  # pragma: no cover - dependency declared in requirements
        return [], ["PARSE_ERROR: python-docx indisponible pour l'extraction DOCX"]

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as exc:
        return [], [f"PARSE_ERROR: DOCX illisible ou corrompu : {exc}"]

    headers, footers = _docx_header_footer_text(doc)
    columns = _docx_section_columns(doc)

    page_texts: list[str] = []
    page_tables: list[list[TableInfo]] = []
    current_text: list[str] = []
    current_tables: list[TableInfo] = []

    for kind, element in _iter_docx_blocks(doc):
        if kind == "p":
            text = element.text.strip()
            if text:
                current_text.append(text)
            if _docx_page_break(element):
                page_texts.append("\n".join(current_text))
                page_tables.append(current_tables)
                current_text = []
                current_tables = []
        else:
            nested, row_count = _docx_table_info(element)
            rows_text: list[str] = []
            try:
                for row in element.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        rows_text.append(" | ".join(cells))
            except Exception:
                pass
            if rows_text:
                current_text.append("\n".join(rows_text))
            current_tables.append(
                TableInfo(
                    kind="native",
                    bbox=None,
                    nested=nested,
                    detail=f"{row_count} ligne(s)" + (" — tableau imbriqué" if nested else ""),
                )
            )

    page_texts.append("\n".join(current_text))
    page_tables.append(current_tables)

    images: list[tuple[float, float, float, float]] = []
    try:
        for shape in doc.inline_shapes:
            width_pt = float(shape.width) / 12700.0
            height_pt = float(shape.height) / 12700.0
            images.append((0.0, 0.0, round(width_pt, 2), round(height_pt, 2)))
    except Exception:
        images = []

    pages: list[PageContent] = []
    for index, (text, tables) in enumerate(zip(page_texts, page_tables), 1):
        pages.append(
            PageContent(
                page_num=index,
                text=text,
                images=tuple(images) if index == 1 else (),
                tables=tuple(tables),
                header_texts=headers,
                footer_texts=footers,
                declared_columns=columns,
            )
        )

    return pages, []


# ──────────────────────────────────────────────────────────────────────
# TXT extraction
# ──────────────────────────────────────────────────────────────────────

def _split_text_pages(text: str) -> list[str]:
    """Split a plain text into pseudo pages of ~3000 characters."""
    if not text:
        return [""]
    pages = []
    for start in range(0, len(text), CHARS_PER_PAGE):
        pages.append(text[start:start + CHARS_PER_PAGE])
    return pages


def _extract_txt_pages(data: bytes) -> tuple[list[PageContent], list[str]]:
    """Extract the pseudo layout of a plain text file."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")
    pages = [
        PageContent(page_num=index, text=page_text)
        for index, page_text in enumerate(_split_text_pages(text), 1)
    ]
    return pages, []


def extract_pages_from_bytes(data: bytes, filetype: str) -> tuple[list[PageContent], list[str]]:
    """Extract the layout of a document from its raw bytes."""
    if filetype == "pdf":
        return _extract_pdf_pages(data)
    if filetype == "docx":
        return _extract_docx_pages(data)
    if filetype == "txt":
        return _extract_txt_pages(data)
    return [], [f"PARSE_ERROR: type de fichier non pris en charge ({filetype})"]


def extract_pages(document: DocumentInput) -> tuple[list[PageContent], list[str]]:
    """Extract the layout from a DocumentInput (text fallback).

    Used when the raw bytes of the file are not available: the analysis then
    relies on the flattened text only, which is less precise (no position, no
    image, no native table).
    """
    text = document.text or ""
    page_count = document.page_count or len(_split_text_pages(text))
    pages = [
        PageContent(page_num=index, text=page_text)
        for index, page_text in enumerate(_split_text_pages(text)[:page_count], 1)
    ]
    return pages, []


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, de-accent and collapse whitespace — used for comparisons."""
    text = text.lower()
    accents = {
        "à": "a", "â": "a", "ä": "a", "é": "e", "è": "e", "ê": "e", "ë": "e",
        "î": "i", "ï": "i", "ô": "o", "ö": "o", "ù": "u", "û": "u", "ü": "u",
        "ç": "c", "ñ": "n", "œ": "oe", "æ": "ae",
    }
    for accented, plain in accents.items():
        text = text.replace(accented, plain)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _contains_keyword(text: str, keyword: str) -> bool:
    """Word-boundary aware keyword search.

    Avoids the classic false positive where "information" matches "formation".
    """
    normalized = _normalize(text)
    pattern = re.escape(_normalize(keyword))
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", normalized) is not None


def _make_ats_finding(
    code: str,
    risk_level: ATSRiskLevel,
    message: str,
    page: int,
    bbox: tuple[float, float, float, float] | None,
    evidence: str,
    error: str | None = None,
) -> ATSFinding:
    """Build an ATSFinding with a bounded, single line evidence excerpt."""
    excerpt = " ".join(evidence.split())[:160].strip()
    return ATSFinding(
        code=code,
        risk_level=risk_level,
        message=message,
        page=page,
        bbox=bbox,
        evidence_excerpt=excerpt,
        error=error,
    )


def _calculate_risk_score(findings: list[ATSFinding]) -> int:
    """Weighted risk score (LOW=5, MEDIUM=20, HIGH=50), capped at 100."""
    total = sum(RISK_WEIGHTS.get(finding.risk_level, 0) for finding in findings)
    return min(100, total)


def _calculate_risk_label(score: int, findings: list[ATSFinding] | None = None) -> ATSRiskLevel:
    """Global label derived from the score and from the worst finding."""
    findings = findings or []
    if score >= SCORE_HIGH_THRESHOLD or any(f.risk_level == "HIGH" for f in findings):
        return "HIGH"
    if score >= SCORE_MEDIUM_THRESHOLD or any(f.risk_level == "MEDIUM" for f in findings):
        return "MEDIUM"
    return "LOW"


def risk_interpretation(label: str) -> str:
    """User facing interpretation of a risk label."""
    return RISK_INTERPRETATIONS.get(label, RISK_INTERPRETATIONS["MEDIUM"])


def _aligned_rows(chunks: list[TextChunk]) -> list[list[TextChunk]]:
    """Group the runs that share (approximately) the same vertical position."""
    if not chunks:
        return []
    ordered = sorted(chunks, key=lambda c: (-c.y, c.x))
    rows: list[list[TextChunk]] = []
    for chunk in ordered:
        if rows and abs(rows[-1][0].y - chunk.y) <= 3.0:
            rows[-1].append(chunk)
        else:
            rows.append([chunk])
    return rows


def _column_clusters(chunks: list[TextChunk]) -> list[list[TextChunk]]:
    """Group the runs into horizontal clusters (columns)."""
    if not chunks:
        return []
    ordered = sorted(chunks, key=lambda c: c.x)
    clusters: list[list[TextChunk]] = [[ordered[0]]]
    for chunk in ordered[1:]:
        current = clusters[-1]
        left = min(c.x for c in current)
        if chunk.x - left <= COLUMN_GAP_PT:
            current.append(chunk)
        else:
            clusters.append([chunk])
    return clusters


def _text_coverage(page: PageContent) -> float:
    """Ratio of the page surface covered by the text (0.0 - 1.0)."""
    area = page.width * page.height
    if area <= 0:
        return 0.0
    covered = 0.0
    for chunk in page.chunks:
        covered += chunk.width * max(1.0, chunk.size)
    return min(1.0, covered / area)


def _page_bbox(page: PageContent) -> tuple[float, float, float, float]:
    """Bounding box covering the whole page."""
    return (0.0, 0.0, round(page.width, 2), round(page.height, 2))


def _band_text(page: PageContent, band: str) -> str:
    """Text of the top or bottom band of a page (empty string when absent)."""
    if not page.chunks:
        lines = [line.strip() for line in page.text.split("\n") if line.strip()]
        if not lines:
            return ""
        return _normalize(lines[0] if band == "top" else lines[-1])

    if band == "top":
        candidates = [c for c in page.chunks if c.y >= page.height - HEADER_BAND_PT]
        if not candidates:
            return ""
        top_y = max(c.y for c in candidates)
        candidates = [c for c in candidates if abs(c.y - top_y) <= 3.0]
    else:
        candidates = [c for c in page.chunks if c.y <= FOOTER_BAND_PT]
        if not candidates:
            return ""
        bottom_y = min(c.y for c in candidates)
        candidates = [c for c in candidates if abs(c.y - bottom_y) <= 3.0]

    return _normalize(" ".join(c.text for c in sorted(candidates, key=lambda c: c.x)))


# ──────────────────────────────────────────────────────────────────────
# Detector 1 — reading order
# ──────────────────────────────────────────────────────────────────────

def detect_reading_order(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect a non linear reading flow (columns, boxes, headers read mid-flow).

    Two signals are combined, both counted per page:

    * *backward jumps* — the text goes back up the page (y grows again in PDF
      coordinates): a sidebar or a running header read in the middle of the
      content;
    * *lateral jumps* — on the same line, the text moves from one column to
      another: the content is read row by row instead of column by column
      (the classic table / multi-column extraction problem).

    A page is flagged when the total exceeds two jumps. Text-only documents
    fall back on a column-like line heuristic.
    """
    findings: list[ATSFinding] = []

    for page in pages:
        if page.chunks:
            chunks = list(page.chunks)
            backward_jumps = 0
            lateral_jumps = 0
            samples: list[str] = []

            clusters = _column_clusters(chunks)
            substantial = [c for c in clusters if len(c) >= 3]
            multi_column = len(substantial) >= 2

            previous = chunks[0]
            for chunk in chunks[1:]:
                if chunk.y - previous.y > READING_JUMP_PT:
                    backward_jumps += 1
                    if len(samples) < 3:
                        samples.append(chunk.text[:40])
                elif multi_column and abs(chunk.y - previous.y) <= 3.0 and abs(chunk.x - previous.x) >= LATERAL_JUMP_PT:
                    lateral_jumps += 1
                    if len(samples) < 3:
                        samples.append(chunk.text[:40])
                previous = chunk

            jumps = backward_jumps + lateral_jumps
            if jumps > 2:
                detail = []
                if backward_jumps:
                    detail.append(f"{backward_jumps} saut(s) vertical/verticaux inversé(s)")
                if lateral_jumps:
                    detail.append(f"{lateral_jumps} saut(s) latéral/latéraux entre colonnes")
                findings.append(
                    _make_ats_finding(
                        "READING_ORDER",
                        "MEDIUM",
                        "Ordre de lecture potentiellement non linéaire (" + ", ".join(detail) + ")",
                        page.page_num,
                        None,
                        " / ".join(samples) or "sauts de lecture détectés",
                    )
                )
            continue

        lines = [line.rstrip() for line in page.text.split("\n") if line.strip()]
        if len(lines) < 4:
            continue
        spaced = sum(1 for line in lines if re.search(r"\S\s{3,}\S", line))
        tabbed = sum(1 for line in lines if line.count("\t") >= 2)
        columns_like = spaced + tabbed
        if columns_like >= 3 and columns_like > len(lines) * 0.3:
            findings.append(
                _make_ats_finding(
                    "READING_ORDER",
                    "MEDIUM",
                    "Ordre de lecture potentiellement non linéaire (colonnes détectées dans le texte extrait)",
                    page.page_num,
                    None,
                    f"{columns_like} ligne(s) sur {len(lines)} présentent une structure multi-colonnes",
                )
            )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 2 — text stored in images
# ──────────────────────────────────────────────────────────────────────

def detect_text_in_images(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect pages whose content is mainly images (scanned / flattened CV).

    Heuristic: the page holds images and the extractable text covers less than
    half of the page surface (or is almost absent).
    """
    findings: list[ATSFinding] = []

    for page in pages:
        if not page.images:
            continue

        text_chars = len(page.text.strip())
        coverage = _text_coverage(page)
        image_area = sum(
            max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
            for box in page.images
        )
        page_area = page.width * page.height
        image_share = (image_area / page_area) if page_area > 0 else 0.0

        if text_chars < 50 or coverage < 0.5 or image_share >= 0.5:
            findings.append(
                _make_ats_finding(
                    "TEXT_IN_IMAGES",
                    "HIGH",
                    "Contenu majoritairement sous forme d'image — le texte risque de ne pas être extrait par l'ATS",
                    page.page_num,
                    _page_bbox(page),
                    f"{len(page.images)} image(s), {text_chars} caractère(s) extractibles, texte sur {coverage:.0%} de la page",
                )
            )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 3 — tabular structures
# ──────────────────────────────────────────────────────────────────────

def detect_nested_tables(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect tabular structures (grid or native table) that may break extraction."""
    findings: list[ATSFinding] = []

    text_patterns = (
        re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE),                  # markdown table
        re.compile(r"^\s*\+[-+]{2,}\+\s*$", re.MULTILINE),             # ascii table
        re.compile(r"(?:^|\n)[^\n]*\t[^\n]*\t[^\n]*", re.MULTILINE),   # tab separated columns
    )

    for page in pages:
        if page.tables:
            for table in page.tables:
                message = (
                    "Tableau imbriqué détecté — structure tabulaire à risque pour l'extraction ATS"
                    if table.nested
                    else "Structure tabulaire détectée — les tableaux peuvent casser l'extraction ATS"
                )
                findings.append(
                    _make_ats_finding(
                        "NESTED_TABLE",
                        "MEDIUM",
                        message,
                        page.page_num,
                        table.bbox,
                        table.detail or "structure tabulaire",
                    )
                )
            continue

        if page.chunks:
            continue

        for pattern in text_patterns:
            match = pattern.search(page.text)
            if match:
                findings.append(
                    _make_ats_finding(
                        "NESTED_TABLE",
                        "MEDIUM",
                        "Structure tabulaire détectée dans le texte — les tableaux peuvent casser l'extraction ATS",
                        page.page_num,
                        None,
                        match.group(),
                    )
                )
                break

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 4 — multiple columns
# ──────────────────────────────────────────────────────────────────────

def detect_multiple_columns(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect multi column layouts (each column narrower than 60% of the page)."""
    findings: list[ATSFinding] = []

    for page in pages:
        if page.declared_columns > 1:
            findings.append(
                _make_ats_finding(
                    "MULTIPLE_COLUMNS",
                    "MEDIUM",
                    f"Mise en page sur {page.declared_columns} colonnes — l'ordre de lecture peut être altéré",
                    page.page_num,
                    None,
                    f"{page.declared_columns} colonnes déclarées dans la mise en page",
                )
            )
            continue

        if page.chunks:
            clusters = _column_clusters(list(page.chunks))
            substantial = [c for c in clusters if len(c) >= 3]
            if len(substantial) < 2:
                continue
            narrow = [
                c for c in substantial
                if (max(c.x + c.width for c in c) - min(c.x for c in c)) < page.width * 0.6
            ]
            if len(narrow) < 2:
                continue

            # A table also produces several x-clusters: it is detected by the
            # table detector instead, so it is skipped here.
            rows = _aligned_rows(list(page.chunks))
            shared_rows = sum(1 for row in rows if len(row) >= MIN_TABLE_COLS)
            if shared_rows >= MIN_TABLE_ROWS:
                continue

            findings.append(
                _make_ats_finding(
                    "MULTIPLE_COLUMNS",
                    "MEDIUM",
                    f"Mise en page multi-colonnes détectée ({len(narrow)} colonnes étroites) — ordre de lecture à vérifier",
                    page.page_num,
                    None,
                    "colonnes à x≈" + ", ".join(f"{min(c.x for c in c):.0f}" for c in narrow),
                )
            )
            continue

        lines = [line.strip() for line in page.text.split("\n") if line.strip()]
        if len(lines) < 8:
            continue
        short_lines = [(i, line) for i, line in enumerate(lines) if 0 < len(line) < 50]
        long_lines = [line for line in lines if len(line) >= 50]
        non_bullet = [(i, line) for i, line in short_lines if not line.startswith(("-", "•", "·", "*", "○"))]
        paired = sum(
            1
            for (idx1, line1), (idx2, line2) in zip(non_bullet, non_bullet[1:])
            if idx2 == idx1 + 1 and abs(len(line1) - len(line2)) < 15
        )
        if paired >= 3 and len(non_bullet) > len(long_lines):
            findings.append(
                _make_ats_finding(
                    "MULTIPLE_COLUMNS",
                    "MEDIUM",
                    "Mise en page multi-colonnes détectée (lignes courtes alignées) — ordre de lecture à vérifier",
                    page.page_num,
                    None,
                    " / ".join(line for _, line in non_bullet[:4]),
                )
            )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 5 — running headers and footers
# ──────────────────────────────────────────────────────────────────────

def detect_headers_footers(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect running headers/footers repeated on consecutive pages."""
    findings: list[ATSFinding] = []
    if not pages:
        return findings

    # DOCX: the header/footer of a section is repeated on every page of it.
    for page in pages:
        reported = False
        for header in page.header_texts:
            if len(header.strip()) > 3:
                findings.append(
                    _make_ats_finding(
                        "HEADER_FOOTER",
                        "LOW",
                        "En-tête défini dans la mise en page — il sera répété sur chaque page",
                        page.page_num,
                        None,
                        header,
                    )
                )
                reported = True
                break
        for footer in page.footer_texts:
            if len(footer.strip()) > 3:
                findings.append(
                    _make_ats_finding(
                        "HEADER_FOOTER",
                        "LOW",
                        "Pied de page défini dans la mise en page — il sera répété sur chaque page",
                        page.page_num,
                        None,
                        footer,
                    )
                )
                reported = True
                break
        if reported:
            # The layout declares its own header/footer: no need to look for
            # repeated bands in the extracted text.
            return findings

    if len(pages) < 2:
        return findings

    tops = [_band_text(page, "top") for page in pages]
    bottoms = [_band_text(page, "bottom") for page in pages]

    for index in range(len(tops) - 1):
        if tops[index] and tops[index] == tops[index + 1]:
            findings.append(
                _make_ats_finding(
                    "HEADER_FOOTER",
                    "LOW",
                    f"En-tête répété sur les pages {index + 1} et {index + 2} — pollution de l'extraction",
                    index + 1,
                    None,
                    tops[index],
                )
            )
            break

    for index in range(len(bottoms) - 1):
        if bottoms[index] and bottoms[index] == bottoms[index + 1]:
            findings.append(
                _make_ats_finding(
                    "HEADER_FOOTER",
                    "LOW",
                    f"Pied de page répété sur les pages {index + 1} et {index + 2} — pollution de l'extraction",
                    index + 1,
                    None,
                    bottoms[index],
                )
            )
            break

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 6 — decorative characters and ligatures
# ──────────────────────────────────────────────────────────────────────

def detect_decorative_chars(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect decorative glyphs/ligatures that some ATS parsers cannot map."""
    findings: list[ATSFinding] = []

    for page in pages:
        found = sorted({char for char in page.text if char in DECORATIVE_CHARS})
        if not found:
            continue
        names = ", ".join(DECORATIVE_CHARS[char] for char in found)
        findings.append(
            _make_ats_finding(
                "DECORATIVE_CHARS",
                "LOW",
                f"Caractères décoratifs ou ligatures détectés ({names}) — ils peuvent être mal interprétés",
                page.page_num,
                None,
                " ".join(found),
            )
        )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 7 — raw URLs instead of anchor texts
# ──────────────────────────────────────────────────────────────────────

def detect_unreadable_links(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect raw URLs printed in the text instead of readable anchor texts."""
    findings: list[ATSFinding] = []

    for page in pages:
        matches = URL_PATTERN.findall(page.text)
        if not matches:
            continue
        findings.append(
            _make_ats_finding(
                "UNREADABLE_LINKS",
                "LOW",
                f"{len(matches)} URL(s) brute(s) visible(s) dans le texte — un libellé lisible serait préférable",
                page.page_num,
                None,
                matches[0],
            )
        )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 8 — missing expected sections
# ──────────────────────────────────────────────────────────────────────

def detect_missing_sections(
    pages: list[PageContent],
    expected_sections: list[str] | None = None,
) -> list[ATSFinding]:
    """Detect the expected sections whose keyword is absent from the text."""
    findings: list[ATSFinding] = []
    sections = expected_sections if expected_sections is not None else DEFAULT_EXPECTED_SECTIONS
    if not sections:
        return findings

    full_text = "\n".join(page.text for page in pages)

    for section in sections:
        keywords = SECTION_KEYWORDS.get(section, [section])
        if not any(_contains_keyword(full_text, keyword) for keyword in keywords):
            findings.append(
                _make_ats_finding(
                    "MISSING_SECTION",
                    "HIGH",
                    f"Section attendue introuvable dans le texte extrait : « {section} » — la structure reste invisible pour l'ATS",
                    1,
                    None,
                    "aucun mot-clé parmi : " + ", ".join(keywords[:5]),
                )
            )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 9 — parse errors (encrypted / malformed files)
# ──────────────────────────────────────────────────────────────────────

def detect_parse_errors(parse_errors: list[str]) -> list[ATSFinding]:
    """Convert the parsing errors into HIGH risk findings."""
    findings: list[ATSFinding] = []

    for error in parse_errors:
        lowered = error.lower()
        if "chiffr" in lowered or "mot de passe" in lowered or "password" in lowered:
            message = "Fichier protégé par mot de passe — le contenu ne peut pas être analysé par l'ATS"
        elif "corrompu" in lowered or "illisible" in lowered:
            message = "Fichier corrompu ou malformé — l'analyse ATS ne peut pas aboutir"
        else:
            message = "Erreur d'extraction du document — l'analyse ATS est incomplète"
        findings.append(
            _make_ats_finding(
                "PARSE_ERROR",
                "HIGH",
                message,
                0,
                None,
                error,
                error="PARSE_ERROR",
            )
        )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Public entry points
# ──────────────────────────────────────────────────────────────────────

def run_ats_check(
    document: DocumentInput,
    *,
    expected_sections: list[str] | None = None,
    file_bytes: bytes | None = None,
) -> ATSCheckResult:
    """Run the complete ATS risk analysis on a document.

    Args:
        document: DocumentInput carrying the extracted text and the metadata.
        expected_sections: Sections the user expects to find. Defaults to
            Expérience, Formation, Compétences.
        file_bytes: Optional raw bytes of the original file. When provided the
            real PDF/DOCX structure is analysed (positions, images, tables,
            columns); otherwise the analysis falls back on the plain text.

    Returns:
        ATSCheckResult with the findings, the weighted score, the label and
        its interpretation.
    """
    if file_bytes:
        pages, parse_errors = extract_pages_from_bytes(file_bytes, document.filetype)
    else:
        raw = getattr(document, "raw_bytes", None)
        if raw is not None:
            # The parser keeps the original bytes: the real layout can be used.
            pages, parse_errors = extract_pages_from_bytes(raw, document.filetype)
        else:
            pages, parse_errors = extract_pages(document)

    findings: list[ATSFinding] = []
    findings.extend(detect_reading_order(pages))
    findings.extend(detect_text_in_images(pages))
    findings.extend(detect_nested_tables(pages))
    findings.extend(detect_multiple_columns(pages))
    findings.extend(detect_headers_footers(pages))
    findings.extend(detect_decorative_chars(pages))
    findings.extend(detect_unreadable_links(pages))
    # A missing section only makes sense when the text could actually be read.
    if any(page.text.strip() for page in pages):
        findings.extend(detect_missing_sections(pages, expected_sections))
    findings.extend(detect_parse_errors(parse_errors))

    risk_score = _calculate_risk_score(findings)
    risk_label = _calculate_risk_label(risk_score, findings)

    return ATSCheckResult(
        findings=findings,
        risk_score=risk_score,
        risk_label=risk_label,
        pages_analyzed=len(pages),
        parse_errors=parse_errors,
        risk_interpretation=risk_interpretation(risk_label),
    )


def run_ats_check_bytes(
    data: bytes,
    filetype: str,
    *,
    expected_sections: list[str] | None = None,
    filename: str | None = None,
) -> ATSCheckResult:
    """Run the ATS analysis directly on raw bytes (full structural analysis)."""
    document = DocumentInput(text="", filename=filename, filetype=filetype)  # type: ignore[arg-type]
    try:
        from .parser import extract_text_from_bytes

        document = extract_text_from_bytes(data, filetype, filename=filename)
    except Exception:
        # The text extraction failed (encrypted / corrupted file): the layout
        # extraction reports the PARSE_ERROR finding.
        document = DocumentInput(text="", filename=filename, filetype=filetype)  # type: ignore[arg-type]

    return run_ats_check(document, expected_sections=expected_sections, file_bytes=data)


def run_ats_check_file(
    path: Path | str,
    *,
    expected_sections: list[str] | None = None,
) -> ATSCheckResult:
    """Run the ATS analysis on a PDF/DOCX/TXT file (full structural analysis)."""
    file_path = Path(path)
    data = file_path.read_bytes()
    suffix = file_path.suffix.lower()
    filetype = {".pdf": "pdf", ".docx": "docx", ".txt": "txt"}.get(suffix)
    if filetype is None:
        raise ValueError(f"Extension non prise en charge pour l'analyse ATS : {suffix}")
    return run_ats_check_bytes(
        data,
        filetype,
        expected_sections=expected_sections,
        filename=file_path.name,
    )
