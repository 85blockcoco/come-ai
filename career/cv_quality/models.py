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
    """
    text: str
    filename: str | None
    filetype: Literal["txt", "pdf", "docx"]
    page_count: int | None = None


# ───────────────────────────────────────────────────────────────────────
# Rémunération (CVBOOST-16)
# ───────────────────────────────────────────────────────────────────────

Currency = Literal[
    "EUR",
    "USD",
    "GBP",
    "JPY",
    "CHF",
    "CAD",
    "AUD",
    "SEK",
    "NOK",
    "DKK",
    "PLN",
    "INR",
    "CNY",
    "",
]
"""Devise d'une evidence de rémunération.

La chaîne vide signifie « aucune devise lue dans le texte » (montant sans
symbole, composant en pourcentage, nombre d'actions…). Aucune devise n'est
jamais déduite ni inventée.
"""

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
"""Nature de la rémunération détectée.

``unknown`` = le texte ne dit pas de quelle composante il s'agit (ni
« base », ni « variable », ni « bonus »…). Rien n'est deviné.
"""

Periodicity = Literal["annual", "monthly", "hourly", "unknown"]
"""Périodicité *explicitement* lue dans le texte.

``unknown`` = le texte n'indique aucune périodicité ; le montant est alors
annualisé comme un montant annuel (convention de ``to_annual``), mais le
champ continue de dire la vérité sur ce qui a été trouvé.
"""


@dataclass(frozen=True, slots=True)
class SalaryEvidence:
    """A remuneration figure extracted from an offer description.

    Attributes:
        raw_text: Exact source excerpt of the remuneration expression
            (e.g. "45 000 € brut annuel").
        source_offset: Character index of the expression in the source text.
        source_excerpt: ~50 characters of context around source_offset.
        min_annual_eur: Lower bound annualized, in the currency of the
            evidence (see note below), or None when the figure is not a
            monetary amount (percentage, number of units).
        max_annual_eur: Upper bound annualized, same unit as
            ``min_annual_eur`` (equal to it for a single amount).
        currency: ISO code of the currency found in the text ("", when the
            text carries no currency at all).
        salary_type: Nature of the remuneration (see :data:`SalaryType`).
        periodicity: Periodicity read in the text (see :data:`Periodicity`).
        raw_amount_text: Exact amount text as written (e.g. "45 000 €",
            "45-55k€", "$60,000", "20%").
        raw_period_text: Exact periodicity text as written (e.g. "brut
            annuel", "par an", "mensuel", "per year"), "" when absent.
        confidence: Deterministic 0–1 score describing how sure the
            extraction is (never a quality promise about the offer).

    NOTE — ``min_annual_eur`` / ``max_annual_eur``: the historical field
    names mention EUR but the values are expressed in ``currency``. No
    foreign-exchange conversion is performed: this package has no rate
    table, no network and never invents a converted amount. For a EUR offer
    (the usual case) the two readings coincide.
    """

    raw_text: str
    source_offset: int
    source_excerpt: str
    min_annual_eur: float | None
    max_annual_eur: float | None
    currency: Currency
    salary_type: SalaryType
    periodicity: Periodicity
    raw_amount_text: str
    raw_period_text: str
    confidence: float