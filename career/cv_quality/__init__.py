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
    Currency,
    DocumentInput,
    ExperienceEntry,
    Finding,
    MatchAction,
    MatchActionCode,
    MatchEvidence,
    MatchResult,
    Provenance,
    ReadabilityScore,
    SalaryEvidence,
    SalaryPeriodicity,
    SalaryType,
    SectionReading,
    STATUS_INFO,
    STATUS_OK,
    STATUS_RISK,
    STATUS_UNKNOWN,
    # ATS models (Mission 04)
    ATSCheckResult,
    ATSFinding,
    ATSRiskLevel,
)
from .parser import extract_salary, extract_text_from_bytes, extract_text_from_file
from .structure import analyze_cv
from .ats import describe_risk, run_ats_check, run_ats_check_bytes, run_ats_check_file
from .matching import match_cv_to_offer

__all__ = [
    # Main entry points
    "analyze_cv",
    "match_cv_to_offer",
    "run_ats_check",
    "run_ats_check_bytes",
    "run_ats_check_file",
    "describe_risk",
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
    "MatchAction",
    "MatchActionCode",
    "MatchEvidence",
    "MatchResult",
    # ATS models
    "ATSFinding",
    "ATSRiskLevel",
    # Salary extraction
    "SalaryEvidence",
    "SalaryType",
    "SalaryPeriodicity",
    "Currency",
    "extract_salary",
    # Status constants
    "STATUS_OK",
    "STATUS_INFO",
    "STATUS_RISK",
    "STATUS_UNKNOWN",
    # Parser helpers
    "extract_text_from_file",
    "extract_text_from_bytes",
]
