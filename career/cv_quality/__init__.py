"""CV Quality Analysis — Public API.

100% local, deterministic, offline structural analysis of CVs.
Detects ATS-blocking issues and human readability problems.

Usage:
    from career.cv_quality import analyze_cv, DocumentInput
    from career.cv_quality.parser import extract_text_from_file

    # From file
    doc = extract_text_from_file("cv.pdf")
    result = analyze_cv(doc)

    # From raw text
    doc = DocumentInput(text="...", filename="cv.txt", filetype="txt")
    result = analyze_cv(doc)
"""

from __future__ import annotations

from .models import (
    CVAnalysisResult,
    DocumentInput,
    ExperienceEntry,
    Finding,
    Provenance,
    ReadabilityScore,
    SectionReading,
    STATUS_INFO,
    STATUS_OK,
    STATUS_RISK,
    STATUS_UNKNOWN,
)
from .parser import (
    PageText,
    PagedDocument,
    extract_paged_text_from_bytes,
    extract_text_from_bytes,
    extract_text_from_file,
)
from .structure import analyze_cv

__all__ = [
    # Main entry point
    "analyze_cv",
    # Input/Output types
    "DocumentInput",
    "CVAnalysisResult",
    # Data models
    "Finding",
    "SectionReading",
    "ExperienceEntry",
    "ReadabilityScore",
    "Provenance",
    # Status constants
    "STATUS_OK",
    "STATUS_INFO",
    "STATUS_RISK",
    "STATUS_UNKNOWN",
    # Parser helpers
    "extract_text_from_file",
    "extract_text_from_bytes",
    # Page-aware extraction (provenance)
    "PageText",
    "PagedDocument",
    "extract_paged_text_from_bytes",
]