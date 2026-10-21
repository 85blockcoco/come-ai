"""ATS (Applicant Tracking System) risk analysis for CV documents.

Pure local analysis — no network, no LLM, no external APIs, no API key.
Detects 9 categories of ATS parsing risks on PDF/DOCX/TXT documents with a
weighted risk score and a prudent interpretation label.

Design notes
------------
* The analysis is **position aware**: for PDF the module reads real glyph
  coordinates through ``pypdf``'s ``visitor_text`` hook and real image
  placements through the page content stream.  Those coordinates feed the
  reading-order, multi-column, table and text-in-image detectors.
* For DOCX (which has no fixed layout) the module reads the OOXML section
  properties (``w:cols``), the native tables and their nesting, and the
  header/footer parts.
* When only raw text is available (``DocumentInput`` without bytes) the
  detectors fall back to conservative textual heuristics.
* Every detector is pure and deterministic: same input, same output.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Literal

from .models import (
    ATSCheckResult,
    ATSFinding,
    ATSRiskLevel,
    DocumentInput,
)

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Expected section keywords (FR/EN) — matching structure.py
SECTION_KEYWORDS: dict[str, list[str]] = {
    "Expérience": [
        "experience", "experience professionnelle", "experiences",
        "work experience", "employment", "emploi", "emplois",
        "parcours professionnel", "career", "carrière",
    ],
    "Formation": [
        "formation", "education", "etudes", "études",
        "diplomes", "diplômes", "degrees", "academic",
        "scolarite", "scolarité", "cursus",
    ],
    "Compétences": [
        "competences", "compétences", "skills", "competencies",
        "technical skills", "compétences techniques", "savoir-faire",
        "expertise", "technologies", "stack",
    ],
    "Langues": [
        "langues", "languages", "language skills",
        "langue", "maîtrise", "maitrise",
    ],
    "Projets": [
        "projets", "projects", "realisations", "réalisations",
        "achievements", "portfolio", "personal projects",
        "projets personnels", "side projects",
    ],
    "Certifications": [
        "certifications", "certificates", "certifications & licenses",
        "licenses", "licences", "credentials", "badges",
    ],
}

# Default expected sections if the user does not provide a custom list
DEFAULT_EXPECTED_SECTIONS = ["Expérience", "Formation", "Compétences"]

# Decorative characters / ligatures that may not map correctly in ATS
DECORATIVE_CHARS = {
    "ﬁ": "fi",   # ﬁ
    "ﬂ": "fl",   # ﬂ
    "•": "•",    # • bullet
    "●": "●",    # ● black circle
    "►": "►",    # ► right triangle
    "◆": "◆",    # ◆ black diamond
    "‣": "‣",    # ‣ triangular bullet
    "▪": "▪",    # ▪ black small square
    "◦": "◦",    # ◦ white bullet
    "➤": "➤",    # ➤ heavy right arrow
    "→": "→",    # → right arrow
    "·": "·",    # · middle dot
    "–": "-",    # – en dash
    "—": "-",    # — em dash
    "‘": "'",    # ‘ left single quote
    "’": "'",    # ’ right single quote
    "“": '"',    # “ left double quote
    "”": '"',    # ” right double quote
}

# URL pattern for detecting raw URLs
URL_PATTERN = re.compile(
    r"\b(?:https?://|www\.)[^\s<>{}|\\^`\[\]]+",
    re.IGNORECASE,
)

# Weighted scoring (mission 04 — §4)
RISK_WEIGHTS: dict[ATSRiskLevel, int] = {
    "LOW": 5,
    "MEDIUM": 20,
    "HIGH": 50,
}

# Score thresholds for the risk label.
# Calibrated on the weights themselves so that the label never contradicts
# the findings: one MEDIUM finding (20 pts) is already "MEDIUM", one HIGH
# finding (50 pts) is already "HIGH".
SCORE_LOW_MAX = 19
SCORE_MEDIUM_MAX = 49

# Prudent interpretation attached to each label (mission 04 — §4)
RISK_INTERPRETATIONS: dict[str, str] = {
    "LOW": "Faible risque",
    "MEDIUM": "Risque modéré — relecture conseillée",
    "HIGH": "Risque élevé — restructuration recommandée",
}

# Technical code carried by the findings raised from a failed extraction.
PARSE_ERROR_CODE = "PARSE_ERROR"

# Page geometry defaults (A4 in PDF points)
DEFAULT_PAGE_WIDTH = 595.0
DEFAULT_PAGE_HEIGHT = 842.0

# A page holding less than this many extractable characters is considered
# "without usable text" (image-only / scanned document).
MIN_TEXT_CHARS_FOR_TEXT_PAGE = 50

# An image covering at least this share of the page is considered dominant.
DOMINANT_IMAGE_AREA_RATIO = 0.25

# Reading-order: a backward jump (the extraction order goes up the page)
# counts when the vertical delta exceeds this many points.
READING_ORDER_JUMP_PT = 10.0

# Reading-order: more than this many backward jumps on a page => finding.
READING_ORDER_MAX_JUMPS = 2

# Column clustering: two chunks belong to the same column when their left
# edges are closer than this many points.
COLUMN_CLUSTER_TOLERANCE_PT = 20.0

# A column must hold at least this share of the page chunks to be a column.
COLUMN_MIN_SHARE = 0.20

# Two columns must be separated by at least this many points.
COLUMN_MIN_SEPARATION_PT = 40.0

# A column is "narrow" when it spans less than this share of the page width.
COLUMN_MAX_WIDTH_RATIO = 0.60

# Rows of a PDF table need at least this many aligned cells.
TABLE_MIN_CELLS = 3

# A PDF table needs at least this many aligned rows.
TABLE_MIN_ROWS = 2

# Number of drawn straight segments (rules) that indicates a table grid.
TABLE_MIN_RULES = 4


# ──────────────────────────────────────────────────────────────────────
# Data structures for page-level analysis
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TextChunk:
    """A run of text with its position on the page.

    Coordinates are PDF points in the page user space (origin bottom-left).

    Attributes:
        text: The text content of the run.
        x0: Left edge.
        y0: Baseline (bottom) of the run.
        x1: Right edge (approximate).
        y1: Top of the run (approximate).
    """

    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(slots=True)
class PageContent:
    """Extracted content for a single page.

    Attributes:
        page_num: 1-based page number.
        text: Page text, in visual reading order when positions are known.
        chunks: Positioned text runs (empty when only raw text is available).
        images: Bounding boxes (x0, y0, x1, y1) of the images on the page.
        tables: Bounding boxes (x0, y0, x1, y1) of the detected tables.
        width: Page width in points.
        height: Page height in points.
        header_text: Repeated header content (DOCX header part).
        footer_text: Repeated footer content (DOCX footer part).
        columns: Number of text columns declared by the layout (DOCX).
        table_count: Number of native tables on the page (DOCX).
        nested_table_count: Number of tables nested inside another table.
    """

    page_num: int
    text: str
    chunks: list[TextChunk] = field(default_factory=list)
    images: list[tuple[float, float, float, float]] = field(default_factory=list)
    tables: list[tuple[float, float, float, float]] = field(default_factory=list)
    width: float = DEFAULT_PAGE_WIDTH
    height: float = DEFAULT_PAGE_HEIGHT
    header_text: str = ""
    footer_text: str = ""
    columns: int = 1
    table_count: int = 0
    nested_table_count: int = 0


# ──────────────────────────────────────────────────────────────────────
# Low-level PDF helpers
# ──────────────────────────────────────────────────────────────────────

def _mat_mul(m1: tuple[float, ...], m2: tuple[float, ...]) -> tuple[float, ...]:
    """Multiply two PDF transformation matrices (PDF row-vector convention)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _pdf_chunks(page) -> list[TextChunk]:
    """Extract positioned text runs from a pypdf page.

    Uses the ``visitor_text`` hook, which is called for every text-showing
    operator with the current transformation matrix.

    Args:
        page: A ``pypdf`` page object.

    Returns:
        List of ``TextChunk`` in extraction order.
    """
    chunks: list[TextChunk] = []

    def visitor(text, cm, tm, font_dict, font_size):  # noqa: ANN001 - pypdf callback
        if not text or not text.strip():
            return
        try:
            tx, ty = float(tm[4]), float(tm[5])
            if cm is not None:
                x = float(cm[0]) * tx + float(cm[2]) * ty + float(cm[4])
                y = float(cm[1]) * tx + float(cm[3]) * ty + float(cm[5])
                scale_x = abs(float(cm[0])) or 1.0
                scale_y = abs(float(cm[3])) or 1.0
            else:
                x, y = tx, ty
                scale_x = scale_y = 1.0
            size = float(font_size) * scale_y
            width = 0.5 * size * scale_x * len(text)
        except (TypeError, ValueError, IndexError):
            return
        chunks.append(TextChunk(
            text=text,
            x0=x,
            y0=y,
            x1=x + width,
            y1=y + size,
        ))

    page.extract_text(visitor_text=visitor)
    return chunks


def _pdf_page_graphics(page) -> tuple[list[tuple[float, float, float, float]], int]:
    """Extract image placements and count drawn rules on a PDF page.

    Walks the page content stream: ``cm`` sets the current transformation
    matrix, ``Do`` paints an XObject.  An image XObject paints the unit
    square, so its placement rectangle is the current matrix.

    Args:
        page: A ``pypdf`` page object.

    Returns:
        Tuple of (image bounding boxes, number of drawn straight segments).
    """
    images: list[tuple[float, float, float, float]] = []
    rules = 0

    try:
        from pypdf.generic import ContentStream

        contents = page.get_contents()
        if contents is None:
            return images, rules
        reader = getattr(page, "pdf", None) or getattr(page, "_pdf", None)
        stream = ContentStream(contents, reader)
    except Exception:
        return images, rules

    ctm: tuple[float, ...] | None = None
    stack: list[tuple[float, ...] | None] = []

    try:
        operations = stream.operations
    except Exception:
        return images, rules

    for operands, operator in operations:
        try:
            if operator == b"q":
                stack.append(ctm)
            elif operator == b"Q":
                ctm = stack.pop() if stack else None
            elif operator == b"cm":
                m = tuple(float(v) for v in operands)
                ctm = _mat_mul(m, ctm) if ctm is not None else m
            elif operator == b"l":
                rules += 1
            elif operator == b"re":
                rules += 1
            elif operator == b"Do":
                name = operands[0]
                resources = page.get("/Resources")
                if resources is None or "/XObject" not in resources:
                    continue
                xobjects = resources["/XObject"]
                if name not in xobjects:
                    continue
                xobj = xobjects[name].get_object()
                if xobj.get("/Subtype") != "/Image":
                    continue
                if ctm is None:
                    images.append((0.0, 0.0, DEFAULT_PAGE_WIDTH, DEFAULT_PAGE_HEIGHT))
                    continue
                a, b, c, d, e, f = ctm
                images.append((e, f, e + a, f + d))
        except Exception:
            # A malformed operator must not abort the whole analysis.
            continue

    return images, rules


def _pdf_table_bboxes(chunks: list[TextChunk], rules: int) -> list[tuple[float, float, float, float]]:
    """Detect tabular grids in a PDF page from aligned text runs.

    A grid is detected when several lines share the same vertical position
    and each of them splits into at least ``TABLE_MIN_CELLS`` aligned cells.

    Args:
        chunks: Positioned text runs of the page.
        rules: Number of drawn straight segments on the page.

    Returns:
        List of approximate table bounding boxes.
    """
    if not chunks:
        return []

    rows: list[list[TextChunk]] = []
    for chunk in sorted(chunks, key=lambda c: (-c.y0, c.x0)):
        for row in rows:
            if abs(row[0].y0 - chunk.y0) <= 2.0:
                row.append(chunk)
                break
        else:
            rows.append([chunk])

    grid_rows = 0
    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")

    for row in rows:
        row.sort(key=lambda c: c.x0)
        cells = 1
        for previous, current in zip(row, row[1:]):
            if current.x0 - previous.x0 > COLUMN_CLUSTER_TOLERANCE_PT:
                cells += 1
        if cells >= TABLE_MIN_CELLS:
            grid_rows += 1
            for chunk in row:
                min_x = min(min_x, chunk.x0)
                max_x = max(max_x, chunk.x1)
                min_y = min(min_y, chunk.y0)
                max_y = max(max_y, chunk.y1)

    if grid_rows >= TABLE_MIN_ROWS:
        return [(min_x, min_y, max_x, max_y)]

    # No aligned grid, but an explicit drawn grid (borders) is a strong hint.
    if rules >= TABLE_MIN_RULES and chunks:
        min_x = min(c.x0 for c in chunks)
        max_x = max(c.x1 for c in chunks)
        min_y = min(c.y0 for c in chunks)
        max_y = max(c.y1 for c in chunks)
        return [(min_x, min_y, max_x, max_y)]

    return []


def _chunks_to_text(chunks: list[TextChunk]) -> str:
    """Rebuild the page text from positioned runs, in visual reading order."""
    if not chunks:
        return ""

    lines: list[list[TextChunk]] = []
    current: list[TextChunk] = []
    current_y: float | None = None

    for chunk in chunks:
        if current_y is None or abs(chunk.y0 - current_y) <= 2.0:
            current.append(chunk)
            if current_y is None:
                current_y = chunk.y0
        else:
            lines.append(current)
            current = [chunk]
            current_y = chunk.y0
    if current:
        lines.append(current)

    rendered: list[str] = []
    for line in lines:
        line.sort(key=lambda c: c.x0)
        rendered.append(" ".join(c.text.strip() for c in line if c.text.strip()))
    return "\n".join(rendered)


# ──────────────────────────────────────────────────────────────────────
# PDF / DOCX / TXT extraction with structure preservation
# ──────────────────────────────────────────────────────────────────────

def _extract_pdf_pages(data: bytes) -> tuple[list[PageContent], list[str]]:
    """Extract page-by-page content from PDF bytes using pypdf.

    Args:
        data: Raw PDF bytes.

    Returns:
        Tuple of (pages, parse_errors).
    """
    pages: list[PageContent] = []
    parse_errors: list[str] = []

    try:
        import pypdf
    except ImportError:
        parse_errors.append("pypdf not available for PDF extraction")
        return pages, parse_errors

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as e:
        parse_errors.append(f"PDF parsing failed: {e}")
        return pages, parse_errors

    if reader.is_encrypted:
        decrypted = False
        try:
            # 0 = failure, 1 = user password, 2 = owner password
            decrypted = bool(reader.decrypt(""))
        except Exception:
            decrypted = False
        if not decrypted:
            parse_errors.append("PDF is encrypted/password-protected")
            return pages, parse_errors

    try:
        pdf_pages = reader.pages
    except Exception as e:
        parse_errors.append(f"PDF parsing failed: {e}")
        return pages, parse_errors

    for page_num, page in enumerate(pdf_pages, 1):
        try:
            mediabox = page.mediabox
            width = float(mediabox.width) if mediabox else DEFAULT_PAGE_WIDTH
            height = float(mediabox.height) if mediabox else DEFAULT_PAGE_HEIGHT

            chunks = _pdf_chunks(page)
            images, rules = _pdf_page_graphics(page)
            tables = _pdf_table_bboxes(chunks, rules)
            text = _chunks_to_text(chunks)

            pages.append(PageContent(
                page_num=page_num,
                text=text,
                chunks=chunks,
                images=images,
                tables=tables,
                width=width,
                height=height,
            ))
        except Exception as e:
            parse_errors.append(f"Page {page_num}: {e}")
            pages.append(PageContent(
                page_num=page_num,
                text="",
                width=DEFAULT_PAGE_WIDTH,
                height=DEFAULT_PAGE_HEIGHT,
            ))

    return pages, parse_errors


def _docx_section_columns(doc) -> int:
    """Read the number of text columns declared by the DOCX section properties."""
    try:
        from docx.oxml.ns import qn
    except ImportError:  # pragma: no cover
        return 1

    columns = 1
    try:
        sections = list(doc.sections)
    except Exception:
        return 1

    for section in sections:
        try:
            cols = section._sectPr.find(qn("w:cols"))
        except Exception:
            continue
        if cols is None:
            continue
        raw = cols.get(qn("w:num"))
        if raw:
            try:
                columns = max(columns, int(raw))
            except ValueError:
                continue
    return columns


def _docx_header_footer_text(doc) -> tuple[str, str]:
    """Read the header and footer text of the first DOCX section."""
    header_text = ""
    footer_text = ""
    try:
        section = doc.sections[0]
    except Exception:
        return header_text, footer_text

    for part, attribute in ((section.header, "header"), (section.footer, "footer")):
        try:
            if part is None:
                continue
            paragraphs = [p.text.strip() for p in part.paragraphs if p.text.strip()]
        except Exception:
            continue
        text = "\n".join(paragraphs)
        if attribute == "header":
            header_text = text
        else:
            footer_text = text

    return header_text, footer_text


def _docx_table_info(doc) -> tuple[int, int]:
    """Count the native tables of a DOCX and the tables nested inside them."""
    table_count = 0
    nested_count = 0
    try:
        tables = list(doc.tables)
    except Exception:
        return table_count, nested_count

    table_count = len(tables)
    for table in tables:
        try:
            for row in table.rows:
                for cell in row.cells:
                    nested_count += len(cell.tables)
        except Exception:
            continue
    return table_count, nested_count


def _docx_has_page_break(paragraph) -> bool:
    """Tell whether a DOCX paragraph contains an explicit page break."""
    try:
        xml = paragraph._p.xml
    except Exception:
        return False
    return 'w:type="page"' in xml or "lastRenderedPageBreak" in xml


def _extract_docx_pages(data: bytes) -> tuple[list[PageContent], list[str]]:
    """Extract page-by-page content from DOCX bytes using python-docx.

    DOCX has no fixed layout: page boundaries are approximated from the
    explicit page breaks, then from a ~3000 characters per page heuristic.

    Args:
        data: Raw DOCX bytes.

    Returns:
        Tuple of (pages, parse_errors).
    """
    pages: list[PageContent] = []
    parse_errors: list[str] = []

    try:
        import docx
    except ImportError:
        parse_errors.append("python-docx not available for DOCX extraction")
        return pages, parse_errors

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        parse_errors.append(f"DOCX parsing failed: {e}")
        return pages, parse_errors

    columns = _docx_section_columns(doc)
    header_text, footer_text = _docx_header_footer_text(doc)
    table_count, nested_table_count = _docx_table_info(doc)

    # Body blocks in document order (paragraphs + tables).
    blocks: list[tuple[str, object]] = []
    try:
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        body = doc.element.body
        for child in body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                blocks.append(("p", Paragraph(child, doc)))
            elif tag == "tbl":
                blocks.append(("t", Table(child, doc)))
    except Exception as e:
        parse_errors.append(f"DOCX structure extraction failed: {e}")

    if not blocks:
        # Fallback: plain paragraphs only.
        try:
            blocks = [("p", p) for p in doc.paragraphs]
        except Exception:
            blocks = []

    page_blocks: list[list[tuple[str, object]]] = [[]]
    chars_in_page = 0
    for kind, block in blocks:
        if kind == "p":
            text = getattr(block, "text", "") or ""
            if _docx_has_page_break(block) and page_blocks[-1]:
                page_blocks.append([])
                chars_in_page = 0
            page_blocks[-1].append((kind, block))
            chars_in_page += len(text)
        else:
            page_blocks[-1].append((kind, block))
            chars_in_page += 200
        if chars_in_page > 3000:
            page_blocks.append([])
            chars_in_page = 0

    if not page_blocks or not page_blocks[-1]:
        page_blocks = [[]]

    for page_num, page_content_blocks in enumerate(page_blocks, 1):
        lines: list[str] = []
        tables: list[tuple[float, float, float, float]] = []
        y = DEFAULT_PAGE_HEIGHT - 72.0
        for kind, block in page_content_blocks:
            if kind == "p":
                text = getattr(block, "text", "") or ""
                if text.strip():
                    lines.append(text.strip())
                y -= 14
            else:
                rows = 0
                try:
                    for row in block.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        line = " | ".join(c for c in cells if c)
                        if line.strip():
                            lines.append(line)
                        rows += 1
                except Exception:
                    pass
                height = max(20.0, rows * 14.0)
                tables.append((54.0, y - height, 541.0, y))
                y -= height

        text = "\n".join(lines)
        pages.append(PageContent(
            page_num=page_num,
            text=text,
            chunks=[],
            images=[],
            tables=tables,
            width=DEFAULT_PAGE_WIDTH,
            height=DEFAULT_PAGE_HEIGHT,
            header_text=header_text,
            footer_text=footer_text,
            columns=columns,
            table_count=table_count if page_num == 1 else 0,
            nested_table_count=nested_table_count if page_num == 1 else 0,
        ))

    return pages, parse_errors


def _extract_txt_pages(data: bytes) -> tuple[list[PageContent], list[str]]:
    """Extract page content from plain text.

    Args:
        data: Raw bytes.

    Returns:
        Tuple of (pages, parse_errors).
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")

    pages = _split_text_pages(text)
    return pages, []


def _split_text_pages(text: str) -> list[PageContent]:
    """Split raw text into pseudo pages (~3000 characters per page)."""
    chars_per_page = 3000
    page_count = max(1, (len(text) // chars_per_page) + 1)

    pages: list[PageContent] = []
    for page_num in range(1, page_count + 1):
        start = (page_num - 1) * chars_per_page
        end = min(page_num * chars_per_page, len(text))
        pages.append(PageContent(
            page_num=page_num,
            text=text[start:end],
            width=DEFAULT_PAGE_WIDTH,
            height=DEFAULT_PAGE_HEIGHT,
        ))
    return pages


def extract_pages(document: DocumentInput) -> tuple[list[PageContent], list[str]]:
    """Extract page-structured content from a ``DocumentInput``.

    Without raw bytes only the extracted text is available, so the pages are
    rebuilt from the text with the usual ~3000 characters per page heuristic.

    Args:
        document: The document to analyse.

    Returns:
        Tuple of (pages, parse_errors).
    """
    return _split_text_pages(document.text), []


def extract_pages_from_bytes(data: bytes, filetype: str) -> tuple[list[PageContent], list[str]]:
    """Extract page-structured content from raw bytes.

    Args:
        data: Raw file bytes.
        filetype: One of "pdf", "docx", "txt".

    Returns:
        Tuple of (pages, parse_errors).
    """
    if filetype == "pdf":
        return _extract_pdf_pages(data)
    if filetype == "docx":
        return _extract_docx_pages(data)
    if filetype == "txt":
        return _extract_txt_pages(data)
    return [], [f"Unsupported filetype: {filetype}"]


# ──────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Normalize text for comparison (lowercase, no accents, single spaces)."""
    text = text.lower()
    accents = {
        "à": "a", "â": "a", "ä": "a", "é": "e", "è": "e", "ê": "e", "ë": "e",
        "î": "i", "ï": "i", "ô": "o", "ö": "o", "ù": "u", "û": "u", "ü": "u",
        "ç": "c", "ñ": "n",
    }
    for a, b in accents.items():
        text = text.replace(a, b)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _make_ats_finding(
    code: str,
    risk_level: ATSRiskLevel,
    message: str,
    page: int,
    bbox: tuple[float, float, float, float] | None,
    evidence: str,
    error: str | None = None,
) -> ATSFinding:
    """Create an ATSFinding with a truncated evidence excerpt."""
    excerpt = evidence[:120].replace("\n", "⏎")
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
    """Calculate the weighted risk score (capped at 100)."""
    total = sum(RISK_WEIGHTS.get(f.risk_level, 0) for f in findings)
    return min(100, total)


def _calculate_risk_label(score: int) -> Literal["LOW", "MEDIUM", "HIGH"]:
    """Determine the risk label from the score."""
    if score <= SCORE_LOW_MAX:
        return "LOW"
    if score <= SCORE_MEDIUM_MAX:
        return "MEDIUM"
    return "HIGH"


def risk_interpretation(label: str) -> str:
    """Return the prudent interpretation of a risk label.

    Args:
        label: One of "LOW", "MEDIUM", "HIGH".

    Returns:
        The human readable interpretation (e.g. "Risque modéré — relecture conseillée").
    """
    return RISK_INTERPRETATIONS.get(label, RISK_INTERPRETATIONS["LOW"])


# ──────────────────────────────────────────────────────────────────────
# Detector 1: Reading Order Problems (non-linear text flow)
# ──────────────────────────────────────────────────────────────────────

def detect_reading_order(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect a non-linear reading order (columns, boxes, headers read mid-flow).

    With real coordinates the detector counts the "backward jumps" of the
    extraction order: the text goes back up the page instead of continuing
    downwards.  More than ``READING_ORDER_MAX_JUMPS`` jumps on a page is a
    finding.  Without coordinates the detector falls back to a textual
    multi-column heuristic.

    Args:
        pages: Pages of the document.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    for page in pages:
        if not page.chunks:
            # Text-only fallback: look for explicit multi-column lines
            lines = [l.strip() for l in page.text.split("\n") if l.strip()]
            if len(lines) < 4:
                continue

            multi_col_lines = 0
            for line in lines:
                if re.search(r"\S\s{3,}\S", line):
                    multi_col_lines += 1

            tab_col_lines = sum(1 for line in lines if line.count("\t") >= 2)

            if (multi_col_lines + tab_col_lines) >= 3 and (multi_col_lines + tab_col_lines) > len(lines) * 0.3:
                findings.append(_make_ats_finding(
                    code="READING_ORDER",
                    risk_level="MEDIUM",
                    message="Ordre de lecture potentiellement non-linéaire (colonnes détectées dans les lignes)",
                    page=page.page_num,
                    bbox=None,
                    evidence=f"Multi-col lines: {multi_col_lines}, Tab-col lines: {tab_col_lines}",
                ))
            continue

        # With character positions: detect Y jumps backwards.
        # PDF coordinates: Y increases upward. Reading order goes top-to-bottom.
        y_positions = [c.y0 for c in page.chunks]
        if len(y_positions) < 4:
            continue

        backward_jumps = 0
        for i in range(1, len(y_positions)):
            if y_positions[i] > y_positions[i - 1] + READING_ORDER_JUMP_PT:
                backward_jumps += 1

        if backward_jumps > READING_ORDER_MAX_JUMPS:
            findings.append(_make_ats_finding(
                code="READING_ORDER",
                risk_level="MEDIUM",
                message=f"Ordre de lecture non-linéaire détecté ({backward_jumps} sauts de lecture inversés)",
                page=page.page_num,
                bbox=(0, 0, page.width, page.height),
                evidence=f"Backward Y jumps: {backward_jumps}",
            ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 2: Text in Images (low extractable text ratio)
# ──────────────────────────────────────────────────────────────────────

def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    """Area of a bounding box (never negative)."""
    width = max(0.0, bbox[2] - bbox[0])
    height = max(0.0, bbox[3] - bbox[1])
    return width * height


def _chunks_overlap_bbox(chunks: list[TextChunk], bbox: tuple[float, float, float, float]) -> bool:
    """Tell whether a text run overlaps the given bounding box."""
    bx0, by0, bx1, by1 = bbox
    for chunk in chunks:
        if chunk.x1 > bx0 and chunk.x0 < bx1 and chunk.y1 > by0 and chunk.y0 < by1:
            return True
    return False


def detect_text_in_images(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect pages whose content is carried by an image instead of text.

    Two situations are reported as HIGH risk:

    * the page holds an image but almost no extractable text (scanned
      document, the ATS sees a blank page);
    * a dominant image (> 25 % of the page) carries no overlapping text,
      which means the text is baked into the picture (OCR required).

    A small picture next to a normal text (a photo in a CV header) is not
    reported: it does not hide any text from the ATS.

    Args:
        pages: Pages of the document.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    for page in pages:
        if page.width <= 0 or page.height <= 0:
            continue

        page_area = page.width * page.height
        text_length = len(page.text.strip())

        if not page.images:
            continue

        # Case 1: image present, no usable text at all.
        if text_length < MIN_TEXT_CHARS_FOR_TEXT_PAGE:
            findings.append(_make_ats_finding(
                code="TEXT_IN_IMAGES",
                risk_level="HIGH",
                message=(
                    f"Page {page.page_num} : texte extractible négligeable "
                    f"({text_length} caractères) alors que la page contient "
                    f"{len(page.images)} image(s) — document scanné probable, "
                    "OCR requis pour être lu par un ATS"
                ),
                page=page.page_num,
                bbox=(0, 0, page.width, page.height),
                evidence=f"Text chars: {text_length}, images: {len(page.images)}",
            ))
            continue

        # Case 2: a dominant image without any adjacent text.
        for image_bbox in page.images:
            ratio = _bbox_area(image_bbox) / page_area if page_area > 0 else 0.0
            if ratio < DOMINANT_IMAGE_AREA_RATIO:
                continue
            if _chunks_overlap_bbox(page.chunks, image_bbox):
                continue
            findings.append(_make_ats_finding(
                code="TEXT_IN_IMAGES",
                risk_level="HIGH",
                message=(
                    f"Page {page.page_num} : image occupant {ratio:.0%} de la page "
                    "sans texte adjacent — le contenu textuel est probablement "
                    "incorporé dans l'image (OCR requis)"
                ),
                page=page.page_num,
                bbox=image_bbox,
                evidence=f"Image area ratio: {ratio:.1%}",
            ))
            break

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 3: Tabular structures
# ──────────────────────────────────────────────────────────────────────

def detect_nested_tables(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect table / grid structures that may break the ATS extraction.

    Three sources are used:

    * native tables of the document (DOCX ``w:tbl``, PDF drawn grids);
    * grids aligned by position in the PDF (several lines sharing the same
      cells);
    * textual table patterns (markdown, ASCII art, tab separated) as a
      fallback when only text is available.

    Args:
        pages: Pages of the document.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    table_patterns = [
        re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE),  # Markdown tables
        re.compile(r"^\s*\+[-+]+\+\s*$", re.MULTILINE),  # ASCII tables
        re.compile(r"(?:^|\n)\s{2,}[^\n]{10,}\s{2,}[^\n]{10,}\s*$", re.MULTILINE),
        re.compile(r"(?:^|\n)[^\n]*\t[^\n]*\t[^\n]*", re.MULTILINE),  # Tab separated
    ]

    for page in pages:
        # Native tables (PDF grid or DOCX table).
        if page.tables:
            for table_bbox in page.tables:
                findings.append(_make_ats_finding(
                    code="NESTED_TABLE",
                    risk_level="MEDIUM",
                    message="Structure tabulaire détectée — l'extraction ATS peut être incomplète (préférer une liste linéaire)",
                    page=page.page_num,
                    bbox=table_bbox,
                    evidence="Native table object detected",
                ))

        if page.nested_table_count:
            findings.append(_make_ats_finding(
                code="NESTED_TABLE",
                risk_level="MEDIUM",
                message=(
                    f"{page.nested_table_count} tableau(x) imbriqué(s) détecté(s) — "
                    "l'extraction ATS peut perdre l'ordre des cellules"
                ),
                page=page.page_num,
                bbox=None,
                evidence=f"Nested tables: {page.nested_table_count}",
            ))

        if page.chunks:
            # Positioned content: the grid detection already ran at extraction
            # time, nothing more to do here.
            continue

        text = page.text
        if not text.strip():
            continue

        for pattern in table_patterns:
            match = pattern.search(text)
            if match:
                findings.append(_make_ats_finding(
                    code="NESTED_TABLE",
                    risk_level="MEDIUM",
                    message="Structure tabulaire détectée — l'extraction ATS peut être incomplète (préférer une liste linéaire)",
                    page=page.page_num,
                    bbox=None,
                    evidence=match.group()[:100],
                ))
                break

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 4: Multiple Columns
# ──────────────────────────────────────────────────────────────────────

def _column_clusters(chunks: list[TextChunk]) -> list[list[TextChunk]]:
    """Group positioned text runs into columns, by their left edge."""
    if not chunks:
        return []

    ordered = sorted(chunks, key=lambda c: c.x0)
    clusters: list[list[TextChunk]] = [[ordered[0]]]
    for chunk in ordered[1:]:
        last = clusters[-1]
        if chunk.x0 - last[-1].x0 <= COLUMN_CLUSTER_TOLERANCE_PT:
            last.append(chunk)
        else:
            clusters.append([chunk])
    return clusters


def _aligned_column_separators(lines: list[str]) -> list[int]:
    """Return the offsets of the internal column separators of a text page.

    A two-column layout shows up as several lines sharing a separator at the
    same offset (several spaces or a tab between two aligned fields).
    """
    offsets: list[int] = []
    for line in lines:
        match = re.search(r"\S(\s{3,})\S", line)
        if match:
            offsets.append(match.start(1))
            continue
        if line.count("\t") >= 1:
            offsets.append(line.index("\t"))
    return offsets


def detect_multiple_columns(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect multi-column layouts (> 1 column of text per page).

    With real coordinates the detector clusters the left edges of the text
    runs: a column is a cluster holding a significant share of the page text
    and spanning less than 60 % of the page width.  Two such clusters mean
    the document is laid out on several columns.  Without coordinates the
    detector looks for several lines sharing the same internal separator,
    which is the textual signature of a two-column layout.

    Args:
        pages: Pages of the document.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    for page in pages:
        # DOCX declares its columns in the section properties.
        if page.columns > 1:
            findings.append(_make_ats_finding(
                code="MULTIPLE_COLUMNS",
                risk_level="MEDIUM",
                message=f"Mise en page sur {page.columns} colonnes déclarée — l'ordre de lecture ATS peut être altéré",
                page=page.page_num,
                bbox=(0, 0, page.width, page.height),
                evidence=f"Declared columns: {page.columns}",
            ))
            continue

        if not page.chunks:
            # Text-only heuristic: several lines sharing the same internal
            # separator (the textual signature of aligned columns).
            lines = [l.strip() for l in page.text.split("\n") if l.strip()]
            if len(lines) < 4:
                continue

            offsets = _aligned_column_separators(lines)
            if len(offsets) < 3:
                continue
            offsets.sort()
            median = offsets[len(offsets) // 2]
            aligned = [offset for offset in offsets if abs(offset - median) <= 3]
            if len(aligned) < 3:
                continue

            findings.append(_make_ats_finding(
                code="MULTIPLE_COLUMNS",
                risk_level="MEDIUM",
                message=(
                    f"Mise en page multi-colonnes détectée (séparateur de colonnes commun "
                    f"à la position {median}) — l'ordre de lecture ATS peut être altéré"
                ),
                page=page.page_num,
                bbox=None,
                evidence="\n".join(
                    line for line in lines if re.search(r"\S\s{3,}\S", line)
                )[:120],
            ))
            continue

        clusters = _column_clusters(page.chunks)
        if len(clusters) < 2:
            continue

        total = len(page.chunks)
        qualified: list[list[TextChunk]] = []
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            if len(cluster) / total < COLUMN_MIN_SHARE:
                continue
            span = max(c.x1 for c in cluster) - min(c.x0 for c in cluster)
            if span >= page.width * COLUMN_MAX_WIDTH_RATIO:
                continue
            qualified.append(cluster)

        if len(qualified) < 2:
            continue

        lefts = sorted(min(c.x0 for c in cluster) for cluster in qualified)
        if lefts[-1] - lefts[0] < COLUMN_MIN_SEPARATION_PT:
            continue

        findings.append(_make_ats_finding(
            code="MULTIPLE_COLUMNS",
            risk_level="MEDIUM",
            message=(
                f"Mise en page multi-colonnes détectée ({len(qualified)} colonnes étroites) — "
                "l'ordre de lecture ATS peut être altéré"
            ),
            page=page.page_num,
            bbox=(0, 0, page.width, page.height),
            evidence=f"Column left edges: {', '.join(f'{x:.0f}' for x in lefts)}",
        ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 5: Headers/Footers (repeated text at top/bottom)
# ──────────────────────────────────────────────────────────────────────

def detect_headers_footers(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect headers and footers repeated across consecutive pages.

    A text repeated at the top or at the bottom of two consecutive pages
    pollutes the extraction: it is read as part of the body content.

    Args:
        pages: Pages of the document.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    if not pages:
        return findings

    # DOCX: the header/footer parts are repeated on every page by design.
    for label, attribute in (("En-tête", "header_text"), ("Pied de page", "footer_text")):
        values = [getattr(page, attribute, "") for page in pages]
        normalized = [_normalize(v) for v in values]
        repeated = any(
            normalized[i] and normalized[i] == normalized[i + 1] and len(normalized[i]) > 5
            for i in range(len(normalized) - 1)
        )
        if repeated:
            first = next(v for v in values if v.strip())
            findings.append(_make_ats_finding(
                code="HEADER_FOOTER",
                risk_level="LOW",
                message=f"{label} répété sur chaque page — pollution de l'extraction ATS",
                page=1,
                bbox=None,
                evidence=first[:100],
            ))

    if len(pages) < 2:
        return findings

    top_texts: list[str] = []
    bottom_texts: list[str] = []

    for page in pages:
        lines = [l.strip() for l in page.text.split("\n") if l.strip()]
        if lines:
            top_texts.append(_normalize(lines[0]))
            bottom_texts.append(_normalize(lines[-1]))
        else:
            top_texts.append("")
            bottom_texts.append("")

    for i in range(len(top_texts) - 1):
        if top_texts[i] and top_texts[i] == top_texts[i + 1] and len(top_texts[i]) > 5:
            findings.append(_make_ats_finding(
                code="HEADER_FOOTER",
                risk_level="LOW",
                message=f"En-tête répété pages {i + 1}-{i + 2} — pollution de l'extraction ATS",
                page=i + 1,
                bbox=None,
                evidence=top_texts[i][:100],
            ))
            break

    for i in range(len(bottom_texts) - 1):
        if bottom_texts[i] and bottom_texts[i] == bottom_texts[i + 1] and len(bottom_texts[i]) > 5:
            findings.append(_make_ats_finding(
                code="HEADER_FOOTER",
                risk_level="LOW",
                message=f"Pied de page répété pages {i + 1}-{i + 2} — pollution de l'extraction ATS",
                page=i + 1,
                bbox=None,
                evidence=bottom_texts[i][:100],
            ))
            break

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 6: Decorative Characters / Ligatures
# ──────────────────────────────────────────────────────────────────────

def detect_decorative_chars(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect non-ASCII decorative characters and ligatures.

    Args:
        pages: Pages of the document.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    for page in pages:
        found_chars: set[str] = set()
        for char in DECORATIVE_CHARS:
            if char in page.text:
                found_chars.add(char)

        if found_chars:
            char_names = [DECORATIVE_CHARS[c] for c in sorted(found_chars)]
            findings.append(_make_ats_finding(
                code="DECORATIVE_CHARS",
                risk_level="LOW",
                message=(
                    f"Caractères décoratifs/ligatures détectés : {', '.join(char_names)} — "
                    "ils peuvent être mal mappés par un ATS"
                ),
                page=page.page_num,
                bbox=None,
                evidence="".join(sorted(found_chars))[:50],
            ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 7: Unreadable Links (raw URLs instead of anchors)
# ──────────────────────────────────────────────────────────────────────

def detect_unreadable_links(pages: list[PageContent]) -> list[ATSFinding]:
    """Detect raw URLs displayed in the text instead of an anchor label.

    Args:
        pages: Pages of the document.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    for page in pages:
        matches = list(URL_PATTERN.finditer(page.text))
        if not matches:
            continue

        long_urls = [m for m in matches if len(m.group()) > 60]
        if len(matches) > 2 or long_urls:
            findings.append(_make_ats_finding(
                code="UNREADABLE_LINKS",
                risk_level="LOW",
                message=(
                    f"{len(matches)} URL(s) brute(s) visible(s) dans le texte — "
                    "préférer un texte d'ancrage lisible"
                ),
                page=page.page_num,
                bbox=None,
                evidence=matches[0].group()[:100],
            ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 8: Missing Expected Sections
# ──────────────────────────────────────────────────────────────────────

def detect_missing_sections(
    pages: list[PageContent],
    expected_sections: list[str] | None,
) -> list[ATSFinding]:
    """Detect the expected sections that are absent from the extracted text.

    Args:
        pages: Pages of the document.
        expected_sections: Sections the user expects; defaults to
            ``DEFAULT_EXPECTED_SECTIONS``.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    sections_to_check = expected_sections or DEFAULT_EXPECTED_SECTIONS
    full_text = "\n".join(p.text for p in pages)
    normalized_text = _normalize(full_text)

    for section in sections_to_check:
        keywords = SECTION_KEYWORDS.get(section, [section.lower()])
        found = any(_normalize(kw) in normalized_text for kw in keywords)

        if not found:
            findings.append(_make_ats_finding(
                code="MISSING_SECTION",
                risk_level="HIGH",
                message=(
                    f"Section attendue introuvable : « {section} » — "
                    "la structure reste invisible pour un ATS"
                ),
                page=1,
                bbox=None,
                evidence=f"Section '{section}' not found in extracted text",
            ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 9: Parse Errors (encrypted/malformed files)
# ──────────────────────────────────────────────────────────────────────

def detect_parse_errors(parse_errors: list[str]) -> list[ATSFinding]:
    """Convert the extraction errors into HIGH risk findings.

    Args:
        parse_errors: The error messages collected during the extraction.

    Returns:
        List of findings.
    """
    findings: list[ATSFinding] = []

    for error in parse_errors:
        lowered = error.lower()
        if "encrypted" in lowered or "password" in lowered or "chiffr" in lowered:
            message = "Fichier PDF chiffré/protégé par mot de passe — extraction impossible pour un ATS"
        elif "corrupt" in lowered or "invalid" in lowered or "malform" in lowered:
            message = f"Fichier corrompu/malformé — extraction ATS impossible : {error}"
        elif "failed" in lowered or "error" in lowered or "échec" in lowered:
            message = f"Erreur d'extraction : {error}"
        else:
            message = f"Erreur d'extraction : {error}"

        findings.append(_make_ats_finding(
            code="PARSE_ERROR",
            risk_level="HIGH",
            message=message,
            page=0,
            bbox=None,
            evidence=error,
            error=PARSE_ERROR_CODE,
        ))

    return findings


# ──────────────────────────────────────────────────────────────────────
# Main entry points
# ──────────────────────────────────────────────────────────────────────

def run_ats_check(
    document: DocumentInput,
    *,
    expected_sections: list[str] | None = None,
    file_bytes: bytes | None = None,
) -> ATSCheckResult:
    """Run the complete ATS risk analysis on a document.

    The analysis is pure and deterministic: no network call, no LLM, no API
    key.  When the raw bytes are available — passed explicitly or carried by
    ``document.raw_bytes`` — the real structure of the PDF or of the DOCX is
    inspected (glyph positions, images, tables, columns); otherwise the
    detectors work on the extracted text only.

    Args:
        document: DocumentInput with the extracted text and metadata.
        expected_sections: Optional list of the section names the user
            expects (defaults to Expérience / Formation / Compétences).
        file_bytes: Optional raw file bytes enabling the structural analysis.

    Returns:
        ATSCheckResult with the findings, the weighted score, the label and
        the extraction errors.
    """
    all_findings: list[ATSFinding] = []
    parse_errors: list[str] = []

    raw = file_bytes if file_bytes is not None else getattr(document, "raw_bytes", None)
    if raw is not None:
        pages, parse_errors = extract_pages_from_bytes(raw, document.filetype)
    else:
        pages, parse_errors = extract_pages(document)

    pages_analyzed = len(pages)

    # A document that could not be read at all only deserves the parse error:
    # every other detector would produce a meaningless finding.
    if parse_errors and not pages:
        all_findings.extend(detect_parse_errors(parse_errors))
        risk_score = _calculate_risk_score(all_findings)
        risk_label = _calculate_risk_label(risk_score)
        return ATSCheckResult(
            findings=all_findings,
            risk_score=risk_score,
            risk_label=risk_label,
            pages_analyzed=pages_analyzed,
            parse_errors=parse_errors,
            risk_interpretation=RISK_INTERPRETATIONS[risk_label],
        )

    all_findings.extend(detect_reading_order(pages))
    image_findings = detect_text_in_images(pages)
    all_findings.extend(image_findings)
    all_findings.extend(detect_nested_tables(pages))
    all_findings.extend(detect_multiple_columns(pages))
    all_findings.extend(detect_headers_footers(pages))
    all_findings.extend(detect_decorative_chars(pages))
    all_findings.extend(detect_unreadable_links(pages))
    # When the text is missing because it is baked into an image, the missing
    # sections are only a consequence: reporting them too would be noise.
    if not image_findings:
        all_findings.extend(detect_missing_sections(pages, expected_sections))
    all_findings.extend(detect_parse_errors(parse_errors))

    risk_score = _calculate_risk_score(all_findings)
    risk_label = _calculate_risk_label(risk_score)

    return ATSCheckResult(
        findings=all_findings,
        risk_score=risk_score,
        risk_label=risk_label,
        pages_analyzed=pages_analyzed,
        parse_errors=parse_errors,
        risk_interpretation=RISK_INTERPRETATIONS[risk_label],
    )


def run_ats_check_bytes(
    data: bytes,
    filetype: str,
    *,
    filename: str | None = None,
    expected_sections: list[str] | None = None,
) -> ATSCheckResult:
    """Run the ATS risk analysis on raw file bytes.

    Args:
        data: Raw bytes of the document (PDF, DOCX or TXT).
        filetype: One of "pdf", "docx", "txt".
        filename: Optional original file name, kept for the provenance.
        expected_sections: Optional list of the expected section names.

    Returns:
        ATSCheckResult with the findings, the weighted score and the label.
    """
    from .parser import extract_text_from_bytes

    try:
        document = extract_text_from_bytes(data, filetype, filename=filename)
    except Exception:
        # An unreadable document (encrypted, corrupted, truncated) is not a
        # crash: the structural analysis below reports the error as a
        # HIGH risk finding.
        document = DocumentInput(
            text="",
            filename=filename,
            filetype=filetype,  # type: ignore[arg-type]
            page_count=0,
        )

    return run_ats_check(
        document,
        expected_sections=expected_sections,
        file_bytes=data,
    )


def run_ats_check_file(
    path: str,
    *,
    expected_sections: list[str] | None = None,
) -> ATSCheckResult:
    """Run the ATS risk analysis on a PDF, DOCX or TXT file.

    Convenience wrapper reading the file and running the full structural
    analysis (glyph positions, images, tables, columns).

    Args:
        path: Path of the document to analyse.
        expected_sections: Optional list of the expected section names.

    Returns:
        ATSCheckResult with the findings, the weighted score and the label.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file extension is not supported.
    """
    from pathlib import Path

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        filetype = "pdf"
    elif suffix in (".docx", ".doc"):
        filetype = "docx"
    elif suffix == ".txt":
        filetype = "txt"
    else:
        raise ValueError(f"Unsupported file extension: {suffix}")

    data = file_path.read_bytes()

    return run_ats_check_bytes(
        data,
        filetype,
        filename=file_path.name,
        expected_sections=expected_sections,
    )
