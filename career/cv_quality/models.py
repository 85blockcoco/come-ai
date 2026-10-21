"""Data models for CV quality analysis.

Pure data structures — no business logic, no network, no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# Status constants for findings
STATUS_OK = "OK"
STATUS_INFO = "INFO"
STATUS_RISK = "RISK"
STATUS_UNKNOWN = "UNKNOWN"

FindingStatus = Literal[STATUS_OK, STATUS_INFO, STATUS_RISK, STATUS_UNKNOWN]


@dataclass(frozen=True, slots=True)
class Finding:
    """A single structural issue detected in the CV.

    Attributes:
        code: Machine-readable code identifying the detector (e.g., "CV_TOO_LONG").
        status: Severity level — OK, INFO, RISK, UNKNOWN.
        message: Human-readable description of the finding.
        source_offset: Character index in the raw source text where the issue was detected.
        source_excerpt: ~50 characters of context around source_offset for verification.
        metadata: Optional extra data specific to the detector (section name, n-gram, page number, etc.).
    """
    code: str
    status: FindingStatus
    message: str
    source_offset: int
    source_excerpt: str
    metadata: dict | None = None


@dataclass(frozen=True, slots=True)
class SectionReading:
    """A detected CV section with its location in the source text.

    Attributes:
        title: Normalized section title (e.g., "Expérience", "Formation").
        start_offset: Character index where the section begins in the raw text.
        end_offset: Character index where the section ends in the raw text.
        content_preview: First ~200 characters of the section content for debugging.
    """
    title: str
    start_offset: int
    end_offset: int
    content_preview: str


@dataclass(frozen=True, slots=True)
class ExperienceEntry:
    """A single work experience entry parsed from the Experience section.

    Attributes:
        company: Company/organization name.
        role: Job title/role.
        start_date: Start date as free text (e.g., "01/2023", "Janvier 2023").
        end_date: End date as free text or "Présent"/"Present"/"Actuel".
        description: Full text of the experience description.
        has_quantified_result: True if description contains at least one number + unit (€, %, k€, M€, k, M, années, mois, xN).
        source_offset: Character index in the raw text where this entry begins.
    """
    company: str
    role: str
    start_date: str | None
    end_date: str | None
    description: str
    has_quantified_result: bool
    source_offset: int


@dataclass(frozen=True, slots=True)
class ReadabilityScore:
    """Approximate French Flesch-Kincaid readability metrics.

    Attributes:
        flesch_kincaid_fr: Approximate Flesch-Kincaid grade level for French (lower = easier).
        avg_sentence_length: Average number of words per sentence.
        complex_word_ratio: Ratio of words with 3+ syllables (French heuristic: 7+ chars) to total words.
    """
    flesch_kincaid_fr: float
    avg_sentence_length: float
    complex_word_ratio: float


@dataclass(frozen=True, slots=True)
class Provenance:
    """Metadata about the analyzed document.

    Attributes:
        filename: Original filename if provided.
        filetype: One of "txt", "pdf", "docx".
        text_length: Total number of characters in the extracted text.
        page_count: Estimated page count (None if unknown).
    """
    filename: str | None
    filetype: str
    text_length: int
    page_count: int | None


@dataclass(frozen=True, slots=True)
class CVAnalysisResult:
    """Complete result of CV structural analysis.

    Attributes:
        findings: All detected issues (RISK and INFO level).
        sections: Detected CV sections with their positions.
        experiences: Parsed experience entries from the Experience section.
        readability: Readability metrics for the full text.
        provenance: Document metadata and extraction info.
    """
    findings: list[Finding]
    sections: list[SectionReading]
    experiences: list[ExperienceEntry]
    readability: ReadabilityScore
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class DocumentInput:
    """Input document for CV analysis.

    Attributes:
        text: Raw extracted text content.
        filename: Original filename (optional).
        filetype: Document type — "txt", "pdf", or "docx".
        page_count: Estimated page count (optional, set by parser).
        raw_bytes: Original file bytes (optional, set by the parser). Kept so
            that the ATS analysis can inspect the real layout of the exported
            file instead of the flattened text.
    """
    text: str
    filename: str | None
    filetype: Literal["txt", "pdf", "docx"]
    page_count: int | None = None
    raw_bytes: bytes | None = None


# ──────────────────────────────────────────────────────────────────────
# ATS models (Mission 04 — contrôle ATS local PDF/DOCX)
# ──────────────────────────────────────────────────────────────────────

ATSRiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass(frozen=True, slots=True)
class ATSFinding:
    """A single ATS risk detected in the analysed document.

    Attributes:
        code: Machine readable code of the detector (e.g. "READING_ORDER").
        risk_level: Severity of the risk — LOW, MEDIUM or HIGH.
        message: Human readable description, phrased as a risk (never a verdict).
        page: 1-based page number (0 when the finding is document-wide).
        bbox: Approximate bounding box in PDF points (x0, y0, x1, y1), None when unknown.
        evidence_excerpt: Short excerpt proving the finding.
        error: Technical error code when the finding comes from a failed
            extraction ("PARSE_ERROR"), None otherwise.
    """

    code: str
    risk_level: ATSRiskLevel
    message: str
    page: int
    bbox: tuple[float, float, float, float] | None
    evidence_excerpt: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ATSCheckResult:
    """Complete result of the local ATS risk analysis.

    Attributes:
        findings: All the detected ATS risks.
        risk_score: Weighted risk score 0-100 (LOW=5, MEDIUM=20, HIGH=50, capped at 100).
        risk_label: Overall label — "LOW", "MEDIUM" or "HIGH".
        pages_analyzed: Number of pages analysed.
        parse_errors: Parsing errors met while reading the file.
        risk_interpretation: User facing interpretation of the label
            ("Faible risque", "Risque modéré — relecture conseillée", ...).
    """

    findings: list[ATSFinding]
    risk_score: int
    risk_label: Literal["LOW", "MEDIUM", "HIGH"]
    pages_analyzed: int
    parse_errors: list[str]
    risk_interpretation: str = ""