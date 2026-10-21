"""Local ATS (Applicant Tracking System) risk analysis for CV documents.

Purely local — no network, no LLM, no API key. The module analyses the
*exported* document (PDF / DOCX / TXT) and reports **ATS risks**, never a
binary "pass/fail" verdict and never a "certain rejection" claim.

Nine detectors are implemented (see `run_ats_check`):

1. `READING_ORDER`    — non linear text flow (columns, boxes, mid-page headers)
2. `TEXT_IN_IMAGES`   — text stored as images (scanned document)
3. `NESTED_TABLE`     — tabular structures that break linear extraction
4. `MULTIPLE_COLUMNS` — multi column layout
5. `HEADER_FOOTER`    — repeated header/footer polluting the extraction
6. `DECORATIVE_CHARS` — ligatures / decorative glyphs that may not be mapped
7. `UNREADABLE_LINKS` — raw URLs printed instead of anchor text
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
import unicodedata
from dataclasses import dataclass, field

from .models import ATSCheckResult, ATSFinding, ATSRiskLevel, DocumentInput
from .parser import extract_text_from_bytes, extract_text_from_file

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
    "calculate_risk_score",
    "calculate_risk_label",
    "describe_risk",
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

# Interpretation of the global label (prudent vocabulary, never a verdict).
RISK_INTERPRETATIONS: dict[ATSRiskLevel, str] = {
    "LOW": "Faible risque",
    "MEDIUM": "Risque modéré — relecture conseillée",
    "HIGH": "Risque élevé — restructuration recommandée",
}

# Score boundaries: < 20 low, < 50 moderate, otherwise high.
SCORE_LOW_MAX = 19
SCORE_MEDIUM_MAX = 49

# Sections looked for when the caller does not provide its own list.
DEFAULT_EXPECTED_SECTIONS: tuple[str, ...] = ("Expérience", "Formation", "Compétences")

# Section heading synonyms (FR / EN) — headings are matched on line start.
SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "expérience": (
        "experience", "experiences", "experience professionnelle", "experiences professionnelles",
        "parcours professionnel", "parcours", "emploi", "emplois", "employment",
        "work experience", "career", "carriere",
    ),
    "formation": (
        "formation", "formations", "etudes", "etudes superieures", "diplomes", "diplomes obtertus",
        "education", "academic", "scolarite", "cursus", "degrees",
    ),
    "compétences": (
        "competences", "competences techniques", "competencesistiques", "savoir-faire",
        "savoir faire", "skills", "technical skills", "competencies", "expertise",
        "technologies", "stack", "outils",
    ),
    "langues": (
        "langues", "langue", "languages", "language skills", "maitrise", "niveau",
    ),
    "projets": (
        "projets", "projets personnels", "projects", "personal projects",
        "realisations", "achievements", "portfolio",
    ),
    "certifications": (
        "certifications", "certificats", "certificates", "licences", "licenses",
        "credentials", "badges", "formations et certifications",
    ),
    "contact": ("contact", "coordonnees", "informations", "profil"),
    "resume": ("resume", "summary", "profil", "a propos"),
}

# Glyphs that are frequently not mapped by ATS parsers (ligatures, bullets,
# geometric shapes, arrows). Accented letters and typographic quotes/dashes
# are deliberately NOT part of this list: they are perfectly readable.
DECORATIVE_CHARS: dict[str, str] = {
    "ﬀ": "ﬀ",  # ﬀ
    "ﬁ": "ﬁ",  # ﬁ
    "ﬂ": "ﬂ",  # ﬂ
    "ﬃ": "ﬃ",  # ﬃ
    "ﬄ": "ﬄ",  # ﬄ
    "ﬅ": "ﬅ",  # ﬅ
    "ﬆ": "ﬆ",  # ﬆ
    "•": "•",  # •
    "‣": "‣",  # ‣
    "●": "●",  # ●
    "◦": "◦",  # ◦
    "▪": "▪",  # ▪
    "▫": "▫",  # ▫
    "◆": "◆",  # ◆
    "◇": "◇",  # ◇
    "►": "►",  # ►
    "▶": "▶",  # ▶
    "▸": "▸",  # ▸
    "➤": "➤",  # ➤
    "→": "→",  # →
}

# Raw URL printed in the text (instead of an anchor label).
URL_PATTERN = re.compile(
    r"(?:https?://|ftp://|www\.)[^\s<>\"'()]+"
    r"|\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:com|fr|net|org|io|co|dev|me|eu|info|biz|edu|gov|xyz|app|ai)"
    r"(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)

# Email addresses — removed before the URL scan (an email is not a raw link).
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")

# Markdown-ish / ASCII tables in plain text exports.
TEXT_TABLE_PATTERN = re.compile(
    r"(?:^|\n)\s*\|.*\|\s*(?:\n|$)"          # markdown rows
    r"|(?:^|\n)\s*\+[-=+]{3,}\+\s*(?:\n|$)"   # ascii separators
    r"|(?:^|\n)[^\n\t]*\t[^\n\t]*\t[^\n\t]*",  # tab separated rows
)

# Approximate number of characters per page for text-only documents.
CHARS_PER_PAGE = 3000

# Page zones used for the header / footer detection.
HEADER_ZONE_RATIO = 0.90
FOOTER_ZONE_RATIO = 0.10

# Minimum number of extracted characters for a page that also carries images.
IMAGE_TEXT_MIN_CHARS = 200

# Column detection thresholds (PDF points).
COLUMN_GUTTER_MIN = 40.0
COLUMN_MIN_CHUNKS = 3
COLUMN_MIN_EXTENT_RATIO = 0.30

# Maximum length of an evidence excerpt.
EVIDENCE_MAX_CHARS = 120


# ──────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TextChunk:
    """A positioned piece of text (approximate PDF coordinates)."""

    text: str
    x: float
    y: float
    size: float


@dataclass(frozen=True, slots=True)
class TableInfo:
    """A table detected in the document (native DOCX table or PDF grid)."""

    rows: int
    cols: int
    nested: bool = False
    origin: str = "document"


@dataclass(slots=True)
class PageLayout:
    """Layout of a single page, ready for the detectors."""

    page_num: int
    width: float = 595.0
    height: float = 842.0
    text: str = ""
    chunks: list[TextChunk] = field(default_factory=list)
    image_count: int = 0
    tables: list[TableInfo] = field(default_factory=list)
    column_count: int | None = None
    failed: bool = False


# ──────────────────────────────────────────────────────────────────────
# Text helpers
# ──────────────────────────────────────────────────────────────────────

def _strip_accents(text: str) -> str:
    """Remove diacritics (é -> e) without touching the rest of the text."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _normalize(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace — for comparisons."""
    lowered = _strip_accents(text.lower())
    return re.sub(r"\s+", " ", lowered).strip()


def _clean_line(line: str) -> str:
    """Normalise a single line for heading comparison."""
    return _normalize(line).strip(" \t:-–—•·")


def _lines_of(text: str) -> list[str]:
    """Split a text into non-empty stripped lines."""
    return [line.strip() for line in text.split("\n") if line.strip()]


def _make_finding(
    code: str,
    risk_level: ATSRiskLevel,
    message: str,
    page: int,
    bbox: tuple[float, float, float, float] | None,
    evidence: str,
    error: str | None = None,
) -> ATSFinding:
    """Build an `ATSFinding` with a truncated, single line evidence excerpt."""
    excerpt = evidence[:EVIDENCE_MAX_CHARS].replace("\n", " / ").strip()
    return ATSFinding(
        code=code,
        risk_level=risk_level,
        message=message,
        page=page,
        bbox=bbox,
        evidence_excerpt=excerpt,
        error=error,
    )


def _page_bbox(page: PageLayout) -> tuple[float, float, float, float]:
    """Bounding box covering the whole page."""
    return (0.0, 0.0, round(page.width, 2), round(page.height, 2))


# ──────────────────────────────────────────────────────────────────────
# Layout extraction
# ──────────────────────────────────────────────────────────────────────

def _layout_from_pdf(data: bytes) -> tuple[list[PageLayout], list[str]]:
    """Build the layout of every page of a PDF (pypdf, local only)."""
    errors: list[str] = []

    try:
        import pypdf
    except ImportError:  # pragma: no cover - dependency declared in requirements
        return [], ["pypdf indisponible pour l'extraction PDF"]

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as exc:
        return [], [f"PDF illisible ou corrompu : {exc}"]

    if reader.is_encrypted:
        unlocked = False
        try:
            unlocked = bool(reader.decrypt(""))
        except Exception:
            unlocked = False
        if not unlocked:
            return [], ["PDF chiffré/protégé par mot de passe — extraction impossible"]

    pages: list[PageLayout] = []
    for index, page in enumerate(reader.pages, 1):
        chunks: list[TextChunk] = []

        def visitor(text, cm, tm, font_dict, font_size, _chunks=chunks):
            if text and text.strip():
                _chunks.append(
                    TextChunk(
                        text=text,
                        x=float(tm[4]),
                        y=float(tm[5]),
                        size=float(font_size or 0.0),
                    )
                )

        failed = False
        try:
            text = page.extract_text(visitor_text=visitor) or ""
        except Exception as exc:
            errors.append(f"Page {index} : extraction impossible ({exc})")
            text = ""
            failed = True

        image_count = 0
        try:
            resources = page.get("/Resources")
            xobjects = resources.get("/XObject") if resources else None
            if xobjects:
                for name in xobjects:
                    try:
                        obj = xobjects[name].get_object()
                    except Exception:
                        continue
                    if obj.get("/Subtype") == "/Image":
                        image_count += 1
        except Exception:
            image_count = 0

        width, height = 595.0, 842.0
        try:
            mediabox = page.mediabox
            if mediabox is not None:
                width = float(mediabox.width) or width
                height = float(mediabox.height) or height
        except Exception:
            pass

        pages.append(
            PageLayout(
                page_num=index,
                width=width,
                height=height,
                text=text,
                chunks=chunks,
                image_count=image_count,
                failed=failed,
            )
        )

    return pages, errors


def _docx_column_count(document) -> int | None:
    """Number of text columns declared in the DOCX section properties."""
    try:
        from docx.oxml.ns import qn
    except Exception:  # pragma: no cover - python-docx always available
        return None

    counts: list[int] = []
    for section in document.sections:
        try:
            sect_pr = section._sectPr
            for cols in sect_pr.findall(qn("w:cols")):
                raw = cols.get(qn("w:num"))
                if raw:
                    counts.append(int(raw))
        except Exception:
            continue
    return max(counts) if counts else None


def _docx_tables(document) -> list[TableInfo]:
    """Native DOCX tables, flagging the nested ones (table inside a cell)."""
    tables: list[TableInfo] = []
    try:
        native = list(document.tables)
    except Exception:
        return tables

    for table in native:
        rows = len(table.rows)
        cols = len(table.rows[0].cells) if rows else 0
        nested = False
        try:
            nested = any(cell.tables for row in table.rows for cell in row.cells)
        except Exception:
            nested = False
        tables.append(TableInfo(rows=rows, cols=cols, nested=nested, origin="docx"))
    return tables


def _layout_from_docx(data: bytes) -> tuple[list[PageLayout], list[str]]:
    """Build the layout of a DOCX (python-docx, local only)."""
    errors: list[str] = []

    try:
        import docx
    except ImportError:  # pragma: no cover - dependency declared in requirements
        return [], ["python-docx indisponible pour l'extraction DOCX"]

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        return [], [f"DOCX corrompu ou malformé : {exc}"]

    parts: list[str] = []
    try:
        for paragraph in document.paragraphs:
            if paragraph.text.strip():
                parts.append(paragraph.text)
    except Exception as exc:
        errors.append(f"Lecture des paragraphes impossible : {exc}")

    tables = _docx_tables(document)
    for table in document.tables:
        try:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        except Exception:
            continue

    image_count = 0
    try:
        image_count = len(document.inline_shapes)
    except Exception:
        image_count = 0

    column_count = _docx_column_count(document)
    text = "\n".join(parts)

    page_count = max(1, (len(text) // CHARS_PER_PAGE) + 1)
    pages: list[PageLayout] = []
    for index in range(1, page_count + 1):
        start = (index - 1) * CHARS_PER_PAGE
        end = min(index * CHARS_PER_PAGE, len(text))
        pages.append(
            PageLayout(
                page_num=index,
                text=text[start:end],
                chunks=[],
                image_count=image_count if index == 1 else 0,
                tables=tables if index == 1 else [],
                column_count=column_count,
            )
        )

    return pages, errors


def _layout_from_text(text: str, page_count: int | None) -> list[PageLayout]:
    """Split a plain text document into pseudo pages."""
    total = page_count or max(1, (len(text) // CHARS_PER_PAGE) + 1)
    pages: list[PageLayout] = []
    for index in range(1, max(1, total) + 1):
        start = (index - 1) * CHARS_PER_PAGE
        end = min(index * CHARS_PER_PAGE, len(text))
        pages.append(
            PageLayout(
                page_num=index,
                text=text[start:end],
                chunks=[],
                image_count=0,
                tables=[],
                column_count=None,
            )
        )
    return pages


def build_layouts(
    document: DocumentInput,
    file_bytes: bytes | None = None,
) -> tuple[list[PageLayout], list[str]]:
    """Build the page layouts for a document (bytes first, text otherwise)."""
    data = file_bytes if file_bytes is not None else getattr(document, "raw_bytes", None)

    if data:
        filetype = (document.filetype or "txt").lower()
        if filetype == "pdf":
            return _layout_from_pdf(data)
        if filetype == "docx":
            return _layout_from_docx(data)
        if filetype == "txt":
            try:
                return _layout_from_text(data.decode("utf-8", errors="replace"), document.page_count), []
            except Exception as exc:  # pragma: no cover - defensive
                return [], [f"Texte illisible : {exc}"]
        return [], [f"Type de fichier non pris en charge : {filetype}"]

    return _layout_from_text(document.text, document.page_count), []


# ──────────────────────────────────────────────────────────────────────
# Geometry helpers
# ──────────────────────────────────────────────────────────────────────

def _group_lines(chunks: list[TextChunk], tolerance: float = 3.0) -> list[list[TextChunk]]:
    """Group positioned chunks into visual lines (same y, stream order kept)."""
    lines: list[list[TextChunk]] = []
    for chunk in chunks:
        if lines and abs(chunk.y - lines[-1][0].y) <= tolerance:
            lines[-1].append(chunk)
        else:
            lines.append([chunk])
    return lines


def _chunk_width(chunk: TextChunk) -> float:
    """Approximate the width of a text chunk (average glyph width ~ 0.5 em)."""
    size = chunk.size if chunk.size > 0 else 10.0
    return max(len(chunk.text.strip()) * size * 0.5, 1.0)


def _gutter_candidates(page: PageLayout) -> list[float]:
    """Vertical bands of the page where no text is written (gutter candidates)."""
    intervals = sorted((chunk.x, chunk.x + _chunk_width(chunk)) for chunk in page.chunks)
    if not intervals:
        return []

    merged: list[list[float]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    candidates: list[float] = []
    for left, right in zip(merged, merged[1:]):
        gap = right[0] - left[1]
        if gap >= COLUMN_GUTTER_MIN:
            candidates.append((left[1] + right[0]) / 2.0)
    return candidates


def _detect_column_gutters(page: PageLayout) -> list[float]:
    """Return the gutters that really separate two columns of text.

    A gutter is a vertical band without text, crossed by at most half of the
    lines, and separating two blocks of text each covering a significant
    part of the vertical extent of the page. A centred title or a wide
    headline does not create a gutter.
    """
    if len(page.chunks) < COLUMN_MIN_CHUNKS * 2:
        return []

    ys = [chunk.y for chunk in page.chunks]
    total_extent = max(ys) - min(ys)
    if total_extent <= 0:
        return []

    lines = _group_lines(page.chunks)
    valid: list[float] = []
    for gutter in _gutter_candidates(page):
        crossing = sum(
            1
            for line in lines
            if any(chunk.x < gutter < chunk.x + _chunk_width(chunk) for chunk in line)
        )
        if crossing > len(lines) / 2:
            continue
        left = [chunk for chunk in page.chunks if chunk.x + _chunk_width(chunk) <= gutter]
        right = [chunk for chunk in page.chunks if chunk.x >= gutter]
        if len(left) < COLUMN_MIN_CHUNKS or len(right) < COLUMN_MIN_CHUNKS:
            continue
        left_extent = max(chunk.y for chunk in left) - min(chunk.y for chunk in left)
        right_extent = max(chunk.y for chunk in right) - min(chunk.y for chunk in right)
        if (
            left_extent >= COLUMN_MIN_EXTENT_RATIO * total_extent
            and right_extent >= COLUMN_MIN_EXTENT_RATIO * total_extent
        ):
            valid.append(gutter)
    return valid


def _has_grid(page: PageLayout) -> bool:
    """True when the page holds an aligned grid (table like structure)."""
    return len(_grid_rows(page.chunks)) >= 2


def _grid_rows(chunks: list[TextChunk], tolerance: float = 3.0) -> list[list[TextChunk]]:
    """Lines holding several chunks aligned on distinct x positions (table rows)."""
    rows = []
    for line in _group_lines(chunks, tolerance):
        distinct_x = {round(chunk.x, 1) for chunk in line}
        if len(distinct_x) >= 3:
            rows.append(line)
    return rows


# ──────────────────────────────────────────────────────────────────────
# Detector 1 — reading order
# ──────────────────────────────────────────────────────────────────────

def detect_reading_order(pages: list[PageLayout]) -> list[ATSFinding]:
    """Detect a non linear reading flow (columns, boxes, mid-page headers).

    Heuristic: more than two backward jumps of the y axis on the same page.
    """
    findings: list[ATSFinding] = []

    for page in pages:
        if page.failed:
            continue

        if page.chunks:
            lines = _group_lines(page.chunks)
            jumps = 0
            for previous, current in zip(lines, lines[1:]):
                if current[0].y > previous[0].y + 5:
                    jumps += 1
            if jumps > 2:
                findings.append(
                    _make_finding(
                        code="READING_ORDER",
                        risk_level="MEDIUM",
                        message=(
                            f"Ordre de lecture potentiellement non linéaire "
                            f"({jumps} retours en arrière dans le flux de texte)"
                        ),
                        page=page.page_num,
                        bbox=_page_bbox(page),
                        evidence=f"{jumps} sauts de lecture inversés sur la page",
                    )
                )
            continue

        # Text only fallback: wide gaps inside the lines suggest columns.
        lines_text = _lines_of(page.text)
        if len(lines_text) < 4:
            continue
        spaced = sum(1 for line in lines_text if re.search(r"\S\s{3,}\S", line))
        tabbed = sum(1 for line in lines_text if line.count("\t") >= 1)
        if (spaced + tabbed) >= 3 and (spaced + tabbed) > len(lines_text) * 0.3:
            findings.append(
                _make_finding(
                    code="READING_ORDER",
                    risk_level="MEDIUM",
                    message="Ordre de lecture potentiellement non linéaire (colonnes détectées dans le texte)",
                    page=page.page_num,
                    bbox=None,
                    evidence=f"{spaced} lignes avec colonnes séparées, {tabbed} lignes tabulées",
                )
            )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 2 — text stored as images
# ──────────────────────────────────────────────────────────────────────

def detect_text_in_images(pages: list[PageLayout]) -> list[ATSFinding]:
    """Detect pages whose content is (mostly) an image instead of text."""
    findings: list[ATSFinding] = []

    for page in pages:
        if page.failed:
            continue
        text_chars = len(page.text.strip())

        if page.image_count > 0 and text_chars == 0:
            findings.append(
                _make_finding(
                    code="TEXT_IN_IMAGES",
                    risk_level="HIGH",
                    message=(
                        "Page sans texte extractible alors qu'elle contient des images — "
                        "le contenu reste probablement invisible pour un ATS"
                    ),
                    page=page.page_num,
                    bbox=_page_bbox(page),
                    evidence=f"{page.image_count} image(s) sur la page, 0 caractère extrait",
                )
            )
        elif page.image_count > 0 and text_chars < IMAGE_TEXT_MIN_CHARS:
            findings.append(
                _make_finding(
                    code="TEXT_IN_IMAGES",
                    risk_level="HIGH",
                    message=(
                        f"Texte extractible très faible ({text_chars} caractères) sur une page "
                        "contenant des images — une lecture OCR serait nécessaire"
                    ),
                    page=page.page_num,
                    bbox=_page_bbox(page),
                    evidence=f"{page.image_count} image(s), {text_chars} caractères extraits",
                )
            )
        elif page.image_count == 0 and text_chars == 0:
            findings.append(
                _make_finding(
                    code="TEXT_IN_IMAGES",
                    risk_level="HIGH",
                    message="Page vide : aucun texte extractible pour l'ATS",
                    page=page.page_num,
                    bbox=_page_bbox(page),
                    evidence="Aucun caractère ni image détecté sur la page",
                )
            )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 3 — tabular structures
# ──────────────────────────────────────────────────────────────────────

def detect_nested_tables(pages: list[PageLayout]) -> list[ATSFinding]:
    """Detect table / grid structures that may break linear extraction."""
    findings: list[ATSFinding] = []

    for page in pages:
        if page.failed:
            continue

        for table in page.tables:
            message = (
                "Tableau imbriqué détecté — l'extraction linéaire peut perdre des cellules"
                if table.nested
                else "Structure tabulaire détectée — l'extraction linéaire peut perdre des cellules"
            )
            findings.append(
                _make_finding(
                    code="NESTED_TABLE",
                    risk_level="MEDIUM",
                    message=message,
                    page=page.page_num,
                    bbox=None,
                    evidence=f"Tableau {table.rows} lignes × {table.cols} colonnes ({table.origin})",
                )
            )

        if page.tables:
            continue

        grid = _grid_rows(page.chunks)
        if len(grid) >= 2:
            findings.append(
                _make_finding(
                    code="NESTED_TABLE",
                    risk_level="MEDIUM",
                    message="Grille alignée détectée (structure tabulaire) — l'extraction linéaire peut être perturbée",
                    page=page.page_num,
                    bbox=None,
                    evidence=f"{len(grid)} lignes à au moins 3 cellules alignées",
                )
            )
            continue

        match = TEXT_TABLE_PATTERN.search(page.text)
        if match:
            findings.append(
                _make_finding(
                    code="NESTED_TABLE",
                    risk_level="MEDIUM",
                    message="Structure tabulaire détectée dans le texte — l'extraction linéaire peut être perturbée",
                    page=page.page_num,
                    bbox=None,
                    evidence=match.group(0),
                )
            )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 4 — multiple columns
# ──────────────────────────────────────────────────────────────────────

def detect_multiple_columns(pages: list[PageLayout]) -> list[ATSFinding]:
    """Detect a layout with more than one column of text."""
    findings: list[ATSFinding] = []

    for page in pages:
        if page.failed:
            continue

        if page.column_count and page.column_count > 1:
            findings.append(
                _make_finding(
                    code="MULTIPLE_COLUMNS",
                    risk_level="MEDIUM",
                    message=(
                        f"Mise en page en {page.column_count} colonnes détectée — "
                        "l'ordre de lecture peut être altéré à l'extraction"
                    ),
                    page=page.page_num,
                    bbox=None,
                    evidence=f"{page.column_count} colonnes déclarées dans la mise en page",
                )
            )
            continue

        gutters = [] if (page.tables or _has_grid(page)) else _detect_column_gutters(page)
        if gutters:
            findings.append(
                _make_finding(
                    code="MULTIPLE_COLUMNS",
                    risk_level="MEDIUM",
                    message=(
                        f"Mise en page multi-colonnes détectée ({len(gutters) + 1} colonnes de texte) — "
                        "l'ordre de lecture peut être altéré à l'extraction"
                    ),
                    page=page.page_num,
                    bbox=None,
                    evidence=(
                        f"Gouttière(s) verticale(s) à x≈{', '.join(f'{g:.0f}' for g in gutters)}pt "
                        f"(largeur de page {page.width:.0f}pt)"
                    ),
                )
            )
            continue

        lines_text = _lines_of(page.text)
        tabbed = [line for line in lines_text if line.count("\t") >= 1]
        if len(tabbed) >= 3 and len(tabbed) > len(lines_text) * 0.3:
            findings.append(
                _make_finding(
                    code="MULTIPLE_COLUMNS",
                    risk_level="MEDIUM",
                    message="Mise en page multi-colonnes détectée (colonnes séparées par tabulations)",
                    page=page.page_num,
                    bbox=None,
                    evidence=f"{len(tabbed)} lignes{tabbed[0]}",
                )
            )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 5 — repeated headers / footers
# ──────────────────────────────────────────────────────────────────────

def _zone_signature(page: PageLayout, zone: str) -> str | None:
    """Signature (y bucket + normalised text) of the header or footer zone."""
    chunks = []
    for chunk in page.chunks:
        if not chunk.text.strip():
            continue
        if zone == "header" and chunk.y >= page.height * HEADER_ZONE_RATIO:
            chunks.append(chunk)
        elif zone == "footer" and chunk.y <= page.height * FOOTER_ZONE_RATIO:
            chunks.append(chunk)
    if not chunks:
        return None
    text = _normalize(" ".join(chunk.text for chunk in chunks))
    if not text:
        return None
    y_bucket = round(sum(chunk.y for chunk in chunks) / len(chunks) / 10.0)
    return f"{y_bucket}|{text}"


def detect_headers_footers(pages: list[PageLayout]) -> list[ATSFinding]:
    """Detect a header or a footer repeated on at least two consecutive pages."""
    findings: list[ATSFinding] = []
    usable = [page for page in pages if not page.failed]
    if len(usable) < 2:
        return findings

    positioned = any(page.chunks for page in usable)

    if positioned:
        for zone, label in (("header", "En-tête"), ("footer", "Pied de page")):
            signatures = [_zone_signature(page, zone) for page in usable]
            for index in range(len(signatures) - 1):
                current, following = signatures[index], signatures[index + 1]
                if not current or current != following:
                    continue
                findings.append(
                    _make_finding(
                        code="HEADER_FOOTER",
                        risk_level="LOW",
                        message=(
                            f"{label} répété sur les pages {index + 1} et {index + 2} — "
                            "pollue l'extraction du CV"
                        ),
                        page=usable[index].page_num,
                        bbox=None,
                        evidence=current.split("|", 1)[-1],
                    )
                )
                break
        return findings

    # Text only fallback: the first / last line repeats from one page to the next.
    tops = [_normalize(_lines_of(page.text)[0]) if _lines_of(page.text) else "" for page in usable]
    bottoms = [_normalize(_lines_of(page.text)[-1]) if _lines_of(page.text) else "" for page in usable]

    for series, label in ((tops, "En-tête"), (bottoms, "Pied de page")):
        for index in range(len(series) - 1):
            current, following = series[index], series[index + 1]
            if not current or current != following or len(current) <= 5:
                continue
            findings.append(
                _make_finding(
                    code="HEADER_FOOTER",
                    risk_level="LOW",
                    message=(
                        f"{label} répété sur les pages {index + 1} et {index + 2} — "
                        "pollue l'extraction du CV"
                    ),
                    page=usable[index].page_num,
                    bbox=None,
                    evidence=current,
                )
            )
            break

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 6 — decorative characters / ligatures
# ──────────────────────────────────────────────────────────────────────

def detect_decorative_chars(pages: list[PageLayout]) -> list[ATSFinding]:
    """Detect ligatures and decorative glyphs that may not be mapped."""
    findings: list[ATSFinding] = []

    for page in pages:
        if page.failed:
            continue
        found = sorted({char for char in page.text if char in DECORATIVE_CHARS})
        if not found:
            continue
        labels = ", ".join(DECORATIVE_CHARS[char] for char in found)
        findings.append(
            _make_finding(
                code="DECORATIVE_CHARS",
                risk_level="LOW",
                message=(
                    f"Caractères décoratifs ou ligatures détectés ({labels}) — "
                    "ils peuvent être mal interprétés à l'extraction"
                ),
                page=page.page_num,
                bbox=None,
                evidence="".join(found),
            )
        )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 7 — raw URLs
# ──────────────────────────────────────────────────────────────────────

def _raw_urls(text: str) -> list[str]:
    """Raw URLs printed in the text (emails excluded)."""
    without_emails = EMAIL_PATTERN.sub(" ", text)
    matches: list[str] = []
    last_end = -1
    for match in URL_PATTERN.finditer(without_emails):
        if match.start() < last_end:
            continue
        url = match.group(0).rstrip(".,;:!?")
        if url:
            matches.append(url)
        last_end = match.end()
    return matches


def detect_unreadable_links(pages: list[PageLayout]) -> list[ATSFinding]:
    """Detect full URLs printed in the text instead of an anchor label."""
    findings: list[ATSFinding] = []

    for page in pages:
        if page.failed:
            continue
        urls = _raw_urls(page.text)
        if not urls:
            continue
        findings.append(
            _make_finding(
                code="UNREADABLE_LINKS",
                risk_level="LOW",
                message=(
                    f"{len(urls)} URL(s) complète(s) visible(s) dans le texte — "
                    "un libellé d'ancre est plus lisible pour un ATS"
                ),
                page=page.page_num,
                bbox=None,
                evidence=urls[0],
            )
        )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 8 — missing sections
# ──────────────────────────────────────────────────────────────────────

def _section_found(lines: list[str], section: str) -> bool:
    """True when a heading matching the section is present in the text."""
    key = _normalize(section)
    variants = SECTION_KEYWORDS.get(key)
    if variants:
        for line in lines:
            cleaned = _clean_line(line)
            if any(cleaned.startswith(variant) for variant in variants):
                return True
        return False

    # Unknown section (caller supplied): look for the raw wording anywhere.
    needle = _normalize(section)
    if not needle:
        return True
    return any(needle in _normalize(line) for line in lines)


def detect_missing_sections(
    pages: list[PageLayout],
    expected_sections: list[str] | None = None,
) -> list[ATSFinding]:
    """Detect the expected section headings that are absent from the text."""
    findings: list[ATSFinding] = []
    sections = list(expected_sections) if expected_sections else list(DEFAULT_EXPECTED_SECTIONS)
    if not sections:
        return findings

    lines: list[str] = []
    for page in pages:
        if page.failed:
            continue
        lines.extend(_lines_of(page.text))

    for section in sections:
        if _section_found(lines, section):
            continue
        findings.append(
            _make_finding(
                code="MISSING_SECTION",
                risk_level="HIGH",
                message=(
                    f"Section attendue introuvable : « {section} » — "
                    "la structure reste invisible pour un ATS"
                ),
                page=1,
                bbox=None,
                evidence=f"Aucun titre correspondant à « {section} » dans le texte extrait",
            )
        )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Detector 9 — parse errors
# ──────────────────────────────────────────────────────────────────────

def detect_parse_errors(parse_errors: list[str]) -> list[ATSFinding]:
    """Turn extraction failures into HIGH risk findings."""
    findings: list[ATSFinding] = []

    for error in parse_errors:
        lowered = error.lower()
        if "chiffr" in lowered or "password" in lowered or "mot de passe" in lowered:
            message = "Fichier protégé par mot de passe — l'extraction ATS est impossible"
        elif "non pris en charge" in lowered:
            message = "Type de fichier non pris en charge par le contrôle ATS"
        elif "corrompu" in lowered or "malform" in lowered or "illisible" in lowered:
            message = "Fichier corrompu ou malformé — l'extraction ATS est impossible"
        else:
            message = f"Extraction partielle : {error}"
        findings.append(
            _make_finding(
                code="PARSE_ERROR",
                risk_level="HIGH",
                message=message,
                page=1,
                bbox=None,
                evidence=error,
                error="PARSE_ERROR",
            )
        )

    return findings


# ──────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────

def calculate_risk_score(findings: list[ATSFinding]) -> int:
    """Weighted risk score (LOW=5, MEDIUM=20, HIGH=50) capped at 100."""
    total = sum(RISK_WEIGHTS.get(finding.risk_level, 0) for finding in findings)
    return min(100, total)


def calculate_risk_label(score: int) -> ATSRiskLevel:
    """Global risk label derived from the weighted score."""
    if score <= SCORE_LOW_MAX:
        return "LOW"
    if score <= SCORE_MEDIUM_MAX:
        return "MEDIUM"
    return "HIGH"


def describe_risk(label: ATSRiskLevel) -> str:
    """Human readable interpretation of a risk label."""
    return RISK_INTERPRETATIONS.get(label, RISK_INTERPRETATIONS["MEDIUM"])


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────

def run_ats_check(
    document: DocumentInput,
    *,
    expected_sections: list[str] | None = None,
    file_bytes: bytes | None = None,
) -> ATSCheckResult:
    """Analyse a document and report its ATS risks.

    Args:
        document: The document to analyse (text + metadata).
        expected_sections: Optional list of the section headings the user
            expects in the document. Defaults to Expérience / Formation /
            Compétences.
        file_bytes: Optional raw bytes of the exported file. When omitted the
            bytes attached to `document` are used (see `DocumentInput.raw_bytes`).

    Returns:
        ATSCheckResult with the findings, the weighted score, the risk label,
        the number of pages analysed and the extraction errors.
    """
    pages, parse_errors = build_layouts(document, file_bytes)

    findings: list[ATSFinding] = []
    if pages:
        findings.extend(detect_reading_order(pages))
        findings.extend(detect_text_in_images(pages))
        findings.extend(detect_nested_tables(pages))
        findings.extend(detect_multiple_columns(pages))
        findings.extend(detect_headers_footers(pages))
        findings.extend(detect_decorative_chars(pages))
        findings.extend(detect_unreadable_links(pages))
        if any(page.text.strip() for page in pages):
            # Without any extractable text the section detector would only
            # repeat what the "text in images" finding already says.
            findings.extend(detect_missing_sections(pages, expected_sections))
    findings.extend(detect_parse_errors(parse_errors))

    risk_score = calculate_risk_score(findings)
    risk_label = calculate_risk_label(risk_score)

    return ATSCheckResult(
        findings=findings,
        risk_score=risk_score,
        risk_label=risk_label,
        pages_analyzed=len(pages),
        parse_errors=parse_errors,
        risk_interpretation=describe_risk(risk_label),
    )


def run_ats_check_bytes(
    data: bytes,
    filetype: str,
    *,
    filename: str | None = None,
    expected_sections: list[str] | None = None,
) -> ATSCheckResult:
    """Run the ATS risk analysis on raw file bytes.

    An unreadable file (password protected, corrupted, unsupported type) is
    reported as a `PARSE_ERROR` finding — it never raises.

    Args:
        data: Raw bytes of the document (PDF, DOCX or TXT).
        filetype: One of "pdf", "docx", "txt".
        filename: Optional original file name, kept for the provenance.
        expected_sections: Optional list of the expected section headings.

    Returns:
        ATSCheckResult with the findings, the weighted score and the label.
    """
    if filetype not in ("txt", "pdf", "docx"):
        return _parse_error_result([f"Type de fichier non pris en charge : {filetype}"])

    try:
        document = extract_text_from_bytes(data, filetype, filename=filename)
    except Exception:
        # The text could not be extracted: the byte level analysis reports
        # the precise reason (encrypted file, corrupted file...).
        document = DocumentInput(
            text="",
            filename=filename,
            filetype=filetype,
            page_count=0,
            raw_bytes=data,
        )

    return run_ats_check(document, expected_sections=expected_sections, file_bytes=data)


def run_ats_check_file(
    path: str,
    *,
    expected_sections: list[str] | None = None,
) -> ATSCheckResult:
    """Run the ATS risk analysis on a PDF, DOCX or TXT file.

    Convenience wrapper: reads the file, extracts the text and runs the full
    structural analysis (glyph positions, images, tables, columns). An
    unreadable file is reported as a `PARSE_ERROR` finding — it never raises.

    Args:
        path: Path of the exported file.
        expected_sections: Optional list of the expected section headings.

    Returns:
        ATSCheckResult with the findings, the weighted score and the label.
    """
    from pathlib import Path

    file_path = Path(path)
    data = file_path.read_bytes()
    suffix = file_path.suffix.lower().lstrip(".")
    filetype = {"pdf": "pdf", "docx": "docx", "doc": "docx", "txt": "txt"}.get(suffix, "")

    if not filetype:
        return _parse_error_result([f"Type de fichier non pris en charge : {suffix or path}"])

    try:
        document = extract_text_from_file(file_path)
    except Exception:
        document = DocumentInput(
            text="",
            filename=file_path.name,
            filetype=filetype,
            page_count=0,
            raw_bytes=data,
        )

    return run_ats_check(document, expected_sections=expected_sections, file_bytes=data)


def _parse_error_result(parse_errors: list[str]) -> ATSCheckResult:
    """Build a result made of the parse errors only."""
    findings = detect_parse_errors(parse_errors)
    risk_score = calculate_risk_score(findings)
    risk_label = calculate_risk_label(risk_score)
    return ATSCheckResult(
        findings=findings,
        risk_score=risk_score,
        risk_label=risk_label,
        pages_analyzed=0,
        parse_errors=parse_errors,
        risk_interpretation=describe_risk(risk_label),
    )
