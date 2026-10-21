"""CV Quality Analysis — Public API.

100% local, deterministic, offline structural analysis of CVs.
Detects ATS-blocking issues and human readability problems.

Usage:
    from career.cv_quality import analyze_cv, run_ats_check, DocumentInput
    from career.cv_quality.parser import extract_text_from_file

    # From file
    doc = extract_text_from_file("cv.pdf")
    result = analyze_cv(doc)
    ats_result = run_ats_check(doc)

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
    # ATS models (Mission 04)
    ATSFinding,
    ATSCheckResult,
    ATSRiskLevel,
)
from .parser import extract_text_from_bytes, extract_text_from_file
from .structure import analyze_cv
from .ats import run_ats_check, run_ats_check_bytes, run_ats_check_file

__all__ = [
    # Main entry points
    "analyze_cv",
    "run_ats_check",
    "run_ats_check_bytes",
    "run_ats_check_file",
    # Input/Output types
    "DocumentInput",
    "CVAnalysisResult",
    "ATSCheckResult",
    # Data models
    "Finding",
    "SectionReading",
    "ExperienceEntry",
    "ReadabilityScore",
    "Provenance",
    # ATS models
    "ATSFinding",
    "ATSRiskLevel",
    # Status constants
    "STATUS_OK",
    "STATUS_INFO",
    "STATUS_RISK",
    "STATUS_UNKNOWN",
    # Parser helpers
    "extract_text_from_file",
    "extract_text_from_bytes",
]
