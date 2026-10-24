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
        source_text: Exact text that was analyzed, kept so that downstream
            modules can quote it verbatim (CVBOOST-21 needs exact substring
            provenance to prove that a CV really contains a skill).
            ``None`` when the result was built without its source text.
    """
    filename: str | None
    filetype: str
    text_length: int
    page_count: int | None
    source_text: str | None = None


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


# ──────────────────────────────────────────────────────────────────────
# CV ↔ Offer matching (CVBOOST-21)
# ──────────────────────────────────────────────────────────────────────

#: The exhaustive set of actions a matching can recommend.
MatchActionCode = Literal[
    "HIGHLIGHT",
    "REPHRASE",
    "DO_NOT_ADD",
    "QUANTIFY",
    "CONFIRM_LANGUAGE",
]


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    """A verbatim excerpt of the CV backing one offer requirement.

    Attributes:
        text: Verbatim excerpt — always an exact substring of the CV source.
        offset: Character index of ``text`` inside the CV source text.
        field: CV field the excerpt comes from ("skills", "experience",
            "education", "languages", "projects", "certifications" or
            "document" when the proof sits outside any detected section).
        confidence: Deterministic 0.0-1.0 score of the match quality.
        coverage: Share of the requirement the excerpt proves (1.0 when
            every significant term of the requirement was found).
    """
    text: str
    offset: int
    field: str
    confidence: float
    coverage: float = 1.0


@dataclass(frozen=True, slots=True)
class MatchAction:
    """One concrete action for exactly one offer requirement.

    Attributes:
        code: Action code (see :data:`MatchActionCode`).
        requirement_text: Verbatim requirement text taken from the offer.
        cv_evidence_text: Verbatim CV excerpt proving the requirement
            (``None`` when nothing in the CV proves it).
        cv_evidence_offset: Character index of ``cv_evidence_text`` in the CV.
        cv_evidence_field: CV field the excerpt comes from (``None`` without
            evidence).
        reason: Human readable explanation of the action.
        confidence: Deterministic 0.0-1.0 score of the recommendation.
    """
    code: MatchActionCode
    requirement_text: str
    cv_evidence_text: str | None
    cv_evidence_offset: int | None
    cv_evidence_field: str | None
    reason: str
    confidence: float


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Result of matching one CV against one offer.

    Attributes:
        overall_score: Match ratio between 0.0 and 1.0
            (``matched_requirements / total_requirements``).
        matched_requirements: Number of requirements backed by CV evidence.
        total_requirements: Number of requirements taken into account.
        actions: One action per requirement, in requirement order.
        missing_critical: Mandatory requirements without any evidence.
        warnings: Cross-cutting warnings (contract, education, languages).
    """
    overall_score: float
    matched_requirements: int
    total_requirements: int
    actions: list[MatchAction]
    missing_critical: list[str]
    warnings: list[str]
