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

from .conditions_extractor import (
    CONDITION_GROUPS,
    ConditionFact,
    ConditionType,
    Confidence,
    detect_language,
    extract_conditions,
    extract_conditions_from_offer,
    summarize_conditions,
)
from .missions_extractor import (
    MissionFact,
    classify_mission_type,
    detect_implied_skills,
    detect_language as detect_mission_language,
    extract_missions,
    missions_as_dicts,
    normalize_offer_text,
)
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
from .parser import extract_pages_from_bytes, extract_salary, extract_text_from_bytes, extract_text_from_file
from .structure import analyze_cv
from .ats import describe_risk, run_ats_check, run_ats_check_bytes, run_ats_check_file
from .matching import find_evidence_in_cv, match_cv_to_offer

__all__ = [
    # Main entry points
    "analyze_cv",
    "match_cv_to_offer",
    "find_evidence_in_cv",
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
    # Work conditions (SK-17)
    "ConditionFact",
    "ConditionType",
    "Confidence",
    "CONDITION_GROUPS",
    "detect_language",
    "extract_conditions",
    "extract_conditions_from_offer",
    "summarize_conditions",
    # Mission extraction (SK-18)
    "MissionFact",
    "classify_mission_type",
    "detect_implied_skills",
    "detect_mission_language",
    "extract_missions",
    "missions_as_dicts",
    "normalize_offer_text",
    # Status constants
    "STATUS_OK",
    "STATUS_INFO",
    "STATUS_RISK",
    "STATUS_UNKNOWN",
    # Parser helpers
    "extract_text_from_file",
    "extract_text_from_bytes",
    "extract_pages_from_bytes",
]
