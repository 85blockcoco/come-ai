"""Text extraction from PDF, DOCX, and TXT files.

Pure local extraction — no network, no LLM, no external APIs.
Reuses pypdf (PDF) and python-docx (DOCX) if available.
"""

from __future__ import annotations

import io
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
    if not HAS_PYPDF:
        raise ValueError("PDF extraction requires 'pypdf' package. Install with: pip install pypdf")

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
        texts = []
        for page in reader.pages:
            try:
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)
            except Exception:
                # Skip pages that fail to extract
                continue
        return "\n\n".join(texts), page_count
    except Exception as e:
        raise ValueError(f"Failed to parse PDF: {e}") from e


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