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


# Salary extraction vocabulary
SALARY_TYPE_BASE = "base"
SALARY_TYPE_VARIABLE = "variable"
SALARY_TYPE_BONUS = "bonus"
SALARY_TYPE_STOCK = "stock"
SALARY_TYPE_EQUITY = "equity"
SALARY_TYPE_RSU = "rsu"
SALARY_TYPE_PACKAGE = "package"
SALARY_TYPE_TOTAL = "total"
SALARY_TYPE_UNKNOWN = "unknown"

SalaryType = Literal[
    "base",
    "variable",
    "bonus",
    "stock",
    "equity",
    "rsu",
    "package",
    "total",
    "unknown",
]

SALARY_PERIOD_ANNUAL = "annual"
SALARY_PERIOD_MONTHLY = "monthly"
SALARY_PERIOD_HOURLY = "hourly"
SALARY_PERIOD_UNKNOWN = "unknown"

SalaryPeriodicity = Literal["annual", "monthly", "hourly", "unknown"]

# ISO 4217 codes recognised by the salary extractor. The empty string means
# "no currency written in the source" — the amount is then left as it is
# written, without any invented conversion.
Currency = Literal[
    "EUR",
    "USD",
    "GBP",
    "JPY",
    "CHF",
    "CAD",
    "AUD",
    "NOK",
    "SEK",
    "DKK",
    "PLN",
    "INR",
    "BRL",
    "ZAR",
    "SGD",
    "",
]


@dataclass(frozen=True, slots=True)
class SalaryEvidence:
    """A single salary/compensation mention extracted from a job offer.

    Attributes:
        raw_text: Exact excerpt of the source text covered by this evidence
            (e.g. "45 000 € brut annuel").
        source_offset: Character index in the raw source text where the mention starts.
        source_excerpt: ~50 characters of context around source_offset for verification.
        min_annual_eur: Lower bound of the amount, annualised (monthly x12, hourly x2080).
            The value stays expressed in `currency` — no FX rate is ever applied, so the
            field never invents a converted figure. None when the mention is not a monetary
            amount (percentage, share/unit count) or when no amount could be read.
        max_annual_eur: Upper bound of the amount (equal to min_annual_eur for a fixed amount,
            strictly greater for a range).
        currency: ISO 4217 code of the source currency ("EUR", "USD", "GBP", "JPY", ...).
            Empty string when the text carries no currency token.
        salary_type: Nature of the compensation (base, variable, bonus, stock, equity, rsu,
            package, total) or "unknown".
        periodicity: Periodicity of the amount (annual, monthly, hourly) or "unknown".
        raw_amount_text: The amount as written in the source (e.g. "45 000 €", "55k€", "$80,000").
        raw_period_text: The period/qualifier as written (e.g. "brut annuel", "par an",
            "mensuel"). Empty string when absent.
        confidence: Heuristic score in [0.0, 1.0] — high when currency, type and periodicity
            are all explicit, low when the mention is ambiguous.
    """

    raw_text: str
    source_offset: int
    source_excerpt: str
    min_annual_eur: float | None
    max_annual_eur: float | None
    currency: str
    salary_type: SalaryType
    periodicity: SalaryPeriodicity
    raw_amount_text: str
    raw_period_text: str
    confidence: float


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
    text: str = ""


@dataclass(frozen=True, slots=True)
class DocumentInput:
    """Input document for CV analysis.

    Attributes:
        text: Raw extracted text content.
        filename: Original filename (optional).
        filetype: Document type — "txt", "pdf", or "docx".
        page_count: Estimated page count (optional, set by parser).
        raw_bytes: Original file bytes (optional, set by the parser). Kept so
            that a layout level analysis (columns, tables, images) can run on
            the exported file instead of the flattened text only.
    """
    text: str
    filename: str | None
    filetype: Literal["txt", "pdf", "docx"]
    page_count: int | None = None
    raw_bytes: bytes | None = None


# ──────────────────────────────────────────────────────────────────────
# ATS specific models (Mission 04 — contrôle ATS local)
# ──────────────────────────────────────────────────────────────────────

ATSRiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass(frozen=True, slots=True)
class ATSFinding:
    """A single ATS risk detected in the exported document.

    Attributes:
        code: Machine readable code identifying the detector
            ("READING_ORDER", "TEXT_IN_IMAGES", "NESTED_TABLE",
            "MULTIPLE_COLUMNS", "HEADER_FOOTER", "DECORATIVE_CHARS",
            "UNREADABLE_LINKS", "MISSING_SECTION", "PARSE_ERROR").
        risk_level: Severity of the risk — LOW, MEDIUM or HIGH.
        message: Human readable description of the risk (prudent wording:
            a risk is reported, never a certain rejection).
        page: 1-based page number the risk was detected on.
        bbox: Approximate bounding box in PDF points (x0, y0, x1, y1),
            None when the position is unknown.
        evidence_excerpt: Verifiable excerpt (≤ 120 chars) showing the reason.
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
    """Result of the local ATS risk analysis.

    Attributes:
        findings: Every risk detected in the document.
        risk_score: Weighted score 0–100 (LOW=5, MEDIUM=20, HIGH=50, capped).
        risk_label: Global risk label — "LOW", "MEDIUM" or "HIGH".
        pages_analyzed: Number of pages analysed.
        parse_errors: Extraction errors (encrypted file, corrupted file...).
        risk_interpretation: Human readable interpretation of the label
            ("Faible risque", "Risque modéré — relecture conseillée",
            "Risque élevé — restructuration recommandée").
    """
    findings: list[ATSFinding]
    risk_score: int
    risk_label: Literal["LOW", "MEDIUM", "HIGH"]
    pages_analyzed: int
    parse_errors: list[str]
    risk_interpretation: str = ""


# Matching models (Mission 08)
MatchActionCode = Literal["HIGHLIGHT", "REPHRASE", "DO_NOT_ADD", "QUANTIFY", "CONFIRM_LANGUAGE"]


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    text: str
    offset: int
    kind: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class MatchAction:
    code: MatchActionCode
    requirement_text: str
    cv_evidence_text: str | None
    cv_evidence_offset: int | None
    reason: str
    confidence: float
    evidence: MatchEvidence | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    overall_score: float
    matched_requirements: int
    total_requirements: int
    actions: list[MatchAction]
    missing_critical: list[str]
    warnings: list[str]
