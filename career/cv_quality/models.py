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
        text: The analysed text itself.  Consumers that must quote the CV
            verbatim (mission 08 matching) need the exact characters: the
            offsets of ``findings``, ``sections`` and ``experiences`` are
            positions inside this text.
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
    """
    text: str
    filename: str | None
    filetype: Literal["txt", "pdf", "docx"]
    page_count: int | None = None


# ──────────────────────────────────────────────────────────────────────
# Matching models (Mission 08)
# ──────────────────────────────────────────────────────────────────────

MatchActionCode = Literal["HIGHLIGHT", "REPHRASE", "DO_NOT_ADD", "QUANTIFY", "CONFIRM_LANGUAGE"]


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    """A verbatim excerpt of the CV that supports a matching decision.

    Attributes:
        text: The excerpt, byte-for-byte identical to a slice of the CV text.
        offset: Character index of ``text`` inside the CV text.
        kind: What the excerpt proves — "skill", "language", …
        field: Optional label of the concept or language proven.
    """
    text: str
    offset: int
    kind: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class MatchAction:
    """A single action resulting from matching one offer requirement against the CV.

    Attributes:
        code: Action type — HIGHLIGHT (direct evidence), REPHRASE (evidence exists but needs rewording),
              DO_NOT_ADD (no evidence in CV), QUANTIFY (evidence exists but lacks numbers),
              CONFIRM_LANGUAGE (language requirement confirmed).
        requirement_text: Exact excerpt of the requirement from the offer.
        cv_evidence_text: Exact verbatim substring from the CV that supports this action,
                          or None if DO_NOT_ADD.
        cv_evidence_offset: Character index in the raw CV text where cv_evidence_text starts,
                            or None if DO_NOT_ADD or evidence not found.
        reason: Human-readable explanation of why this action was chosen.
        confidence: Deterministic confidence score 0.0–1.0 for this action.
        evidence: Structured form of the same proof (never more than the text).
    """
    code: MatchActionCode
    requirement_text: str
    cv_evidence_text: str | None
    cv_evidence_offset: int | None
    reason: str
    confidence: float
    evidence: MatchEvidence | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Complete result of matching a CV against one offer.

    Attributes:
        overall_score: Global matching score 0.0–1.0.  It is the weighted
            average of the coverage of each requirement — HIGHLIGHT 1.0,
            QUANTIFY 0.9, CONFIRM_LANGUAGE 0.8, REPHRASE 0.6, DO_NOT_ADD 0.0 —
            the weight being the importance of the requirement (obligatory 1.0,
            preferred 0.5, other 0.3).
        matched_requirements: Number of requirements covered by a proof of the
            CV (HIGHLIGHT, QUANTIFY, CONFIRM_LANGUAGE).  A REPHRASE shows a
            related competence, not the required one: it is not a cover.
        total_requirements: Number of requirements the engine acted on.  A
            negated statement is not a requirement: it produces a warning, not
            an action, and it never weighs on the score.
        actions: List of actions for each requirement, in the same order as extracted.
        missing_critical: List of requirement texts that are mandatory (modality=required) but have DO_NOT_ADD.
        warnings: Non-blocking warnings (e.g., "Alternance détectée", "Négation détectée", "Langue programme vs exigence").
    """
    overall_score: float
    matched_requirements: int
    total_requirements: int
    actions: list[MatchAction]
    missing_critical: list[str]
    warnings: list[str]