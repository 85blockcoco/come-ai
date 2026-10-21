"""Text extraction from PDF, DOCX, and TXT files.

Pure local extraction — no network, no LLM, no external APIs.
Reuses pypdf (PDF) and python-docx (DOCX) if available.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from .models import DocumentInput, Finding, STATUS_RISK


# Optional dependencies — handled gracefully
try:
    import pypdf
    HAS_PYPDF = True
except ImportError:  # pragma: no cover
    HAS_PYPDF = False

try:
    import docx
    HAS_DOCX = True
except ImportError:  # pragma: no cover
    HAS_DOCX = False


@dataclass(frozen=True, slots=True)
class VisualBlock:
    """One positioned text fragment extracted from a visually laid-out page."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    page: int = 0


@dataclass(frozen=True, slots=True)
class PageText:
    """One extracted page and its offsets inside the joined document text.

    The offsets are relative to the text returned by
    :func:`extract_text_from_bytes`, so a page span always points at the exact
    passage it holds.
    """

    page: int
    text: str
    start_offset: int
    end_offset: int


def reconstruct_reading_order(
    blocks: list[VisualBlock], *, line_tolerance: float = 6.0
) -> str:
    """Rebuild logical lines top-to-bottom and left-to-right within a band."""

    pages: list[str] = []
    for page_number in sorted({block.page for block in blocks}):
        page_blocks = sorted(
            (block for block in blocks if block.page == page_number),
            key=lambda block: (block.top, block.x0),
        )
        bands: list[list[VisualBlock]] = []
        for block in page_blocks:
            if not block.text.strip():
                continue
            if bands and abs(bands[-1][0].top - block.top) <= line_tolerance:
                bands[-1].append(block)
            else:
                bands.append([block])
        lines: list[str] = []
        for band in bands:
            ordered = sorted(band, key=lambda block: block.x0)
            first_text = ordered[0].text.strip()
            if (
                len(ordered) > 1
                and first_text.upper() == first_text
                and first_text.casefold()
                in {
                    "experience",
                    "education",
                    "skills",
                    "languages",
                    "projects",
                    "certifications",
                    "expérience",
                    "formation",
                    "compétences",
                    "langues",
                    "projets",
                }
            ):
                lines.append(first_text)
                lines.append(" ".join(block.text.strip() for block in ordered[1:]))
                continue
            parts: list[str] = []
            previous: VisualBlock | None = None
            for block in ordered:
                if previous is not None and block.x0 - previous.x1 > 45:
                    parts.append("|")
                parts.append(block.text.strip())
                previous = block
            lines.append(" ".join(parts))
        pages.append("\n".join(lines))
    return "\n\n".join(pages)


def _extract_positioned_page(page: object, page_number: int) -> str:
    blocks: list[VisualBlock] = []
    page_height = float(getattr(page, "mediabox").height)

    def visitor(text: str, _cm: object, tm: list[float], _font: object, size: float) -> None:
        x0 = float(tm[4])
        base_top = page_height - float(tm[5])
        for line_index, raw_line in enumerate(text.splitlines()):
            cleaned = raw_line.strip()
            if not cleaned:
                continue
            top = base_top + line_index * float(size)
            width = max(float(size) * 0.45 * len(cleaned), 1.0)
            blocks.append(
                VisualBlock(
                    text=cleaned,
                    x0=x0,
                    top=top,
                    x1=x0 + width,
                    bottom=top + float(size),
                    page=page_number,
                )
            )

    try:
        page.extract_text(visitor_text=visitor)
    except TypeError:
        return ""
    return reconstruct_reading_order(blocks)


def extract_text_from_bytes(data: bytes, filetype: str, filename: str | None = None) -> DocumentInput:
    """Extract text from raw bytes based on filetype.

    Args:
        data: Raw file bytes.
        filetype: One of "txt", "pdf", "docx".
        filename: Original filename for provenance.

    Returns:
        DocumentInput with extracted text and metadata.

    Raises:
        ValueError: If filetype is unsupported or extraction fails.
    """
    if filetype == "txt":
        text = _extract_txt(data)
        page_count = _estimate_pages_txt(text)
    elif filetype == "pdf":
        text, page_count = _extract_pdf(data)
    elif filetype == "docx":
        text, page_count = _extract_docx(data)
    else:
        raise ValueError(f"Unsupported filetype: {filetype}")

    return DocumentInput(
        text=text,
        filename=filename,
        filetype=filetype,
        page_count=page_count,
    )


def extract_text_from_file(path: Path | str) -> DocumentInput:
    """Extract text from a file path, inferring type from extension.

    Args:
        path: Path to the file.

    Returns:
        DocumentInput with extracted text and metadata.

    Raises:
        ValueError: If file extension is unsupported or file not found.
        FileNotFoundError: If the file doesn't exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".txt":
        filetype = "txt"
    elif suffix == ".pdf":
        filetype = "pdf"
    elif suffix in (".docx", ".doc"):
        filetype = "docx"
    else:
        raise ValueError(f"Unsupported file extension: {suffix}")

    data = path.read_bytes()
    return extract_text_from_bytes(data, filetype, filename=path.name)


def _extract_txt(data: bytes) -> str:
    """Extract text from plain text bytes (UTF-8, fallback to latin-1)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _estimate_pages_txt(text: str) -> int | None:
    """Estimate page count for plain text (approx 3000 chars/page)."""
    if not text:
        return 1
    # Rough estimate: ~3000 characters per A4 page
    return max(1, (len(text) // 3000) + 1)


def _extract_pdf(data: bytes) -> tuple[str, int]:
    """Extract text from PDF bytes using pypdf.

    Returns:
        Tuple of (extracted_text, page_count).

    Raises:
        ValueError: If pypdf is not available or PDF is invalid.
    """
    page_count, pages = _extract_pdf_pages(data)
    return "\n\n".join(page_text for _page_number, page_text in pages), page_count


def _extract_pdf_pages(data: bytes) -> tuple[int, list[tuple[int, str]]]:
    """Extract the pages of a PDF, keeping the page number of each text.

    Returns:
        Tuple of (total_page_count, [(page_index, page_text)]).  Pages whose
        text cannot be read are skipped, exactly like the joined text does.
    """
    if not HAS_PYPDF:
        raise ValueError("PDF extraction requires 'pypdf' package. Install with: pip install pypdf")

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
        pages: list[tuple[int, str]] = []
        for page_number, page in enumerate(reader.pages):
            try:
                page_text = _extract_positioned_page(page, page_number)
                legacy_text = page.extract_text() or ""
                if not page_text or (
                    len(page_text.splitlines()) < 0.4 * len(legacy_text.splitlines())
                ):
                    page_text = legacy_text
            except Exception:
                # Skip pages that fail to extract
                continue
            if page_text:
                pages.append((page_number, page_text))
        return page_count, pages
    except Exception as e:
        raise ValueError(f"Failed to parse PDF: {e}") from e


def extract_pages_from_bytes(data: bytes, filetype: str) -> list[PageText]:
    """Extract the pages of a document with their offsets in the joined text.

    The offsets match the text returned by :func:`extract_text_from_bytes`, so
    a caller can attach a page number to any passage it reads.

    Args:
        data: Raw file bytes.
        filetype: One of "txt", "pdf", "docx".

    Returns:
        The list of pages, in reading order.

    Raises:
        ValueError: If filetype is unsupported or extraction fails.
    """
    if filetype == "txt":
        text = _extract_txt(data)
        return [PageText(page=1, text=text, start_offset=0, end_offset=len(text))]
    if filetype == "docx":
        text, _page_count = _extract_docx(data)
        return [PageText(page=1, text=text, start_offset=0, end_offset=len(text))]
    if filetype != "pdf":
        raise ValueError(f"Unsupported filetype: {filetype}")

    _page_count, pages = _extract_pdf_pages(data)
    page_texts: list[PageText] = []
    offset = 0
    for page_number, page_text in pages:
        end_offset = offset + len(page_text)
        page_texts.append(
            PageText(
                page=page_number + 1,
                text=page_text,
                start_offset=offset,
                end_offset=end_offset,
            )
        )
        # The pages are joined with a blank line, exactly like the text.
        offset = end_offset + 2
    return page_texts


def _extract_docx(data: bytes) -> tuple[str, int]:
    """Extract text from DOCX bytes using python-docx.

    Returns:
        Tuple of (extracted_text, page_count_estimate).

    Raises:
        ValueError: If python-docx is not available or DOCX is invalid.
    """
    if not HAS_DOCX:
        raise ValueError("DOCX extraction requires 'python-docx' package. Install with: pip install python-docx")

    try:
        doc = docx.Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also extract text from tables
        table_texts = []
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text for cell in row.cells)
                if row_text.strip():
                    table_texts.append(row_text)

        all_text = "\n".join(paragraphs + table_texts)
        # Rough page estimate for DOCX: ~3000 chars per page
        page_count = max(1, (len(all_text) // 3000) + 1)
        return all_text, page_count
    except Exception as e:
        raise ValueError(f"Failed to parse DOCX: {e}") from e


def create_parse_error_finding(error: Exception, filetype: str, filename: str | None = None) -> Finding:
    """Create a Finding for a parsing error."""
    msg = str(error)
    excerpt = msg[:50] if msg else "Unknown parsing error"
    return Finding(
        code="PARSE_ERROR",
        status=STATUS_RISK,
        message=f"Failed to extract text from {filetype.upper()}: {msg}",
        source_offset=0,
        source_excerpt=excerpt,
        metadata={"filetype": filetype, "filename": filename, "error_type": type(error).__name__},
    )
