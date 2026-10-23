"""Deterministic CV variant definitions for the local application pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VariantId = Literal["m_a", "markets", "corporate_finance"]
VariantLocale = Literal["en-GB", "en-US"]


@dataclass(frozen=True, slots=True)
class CVVariant:
    """Immutable configuration used to target CV content to a job family."""

    id: VariantId
    label: str
    locale: VariantLocale
    section_order: tuple[str, ...]
    keyword_priorities: dict[str, float]
    section_headers: dict[str, str]
    cover_letter_tone: str
    mandatory_keywords: tuple[str, ...]


MA_VARIANT = CVVariant(
    id="m_a",
    label="M&A / Investment Banking",
    locale="en-GB",
    section_order=(
        "Professional Experience",
        "Transaction Experience",
        "Education",
        "Technical Skills",
        "Projects",
        "Languages",
        "Certifications",
    ),
    keyword_priorities={
        "financial modeling": 1.0,
        "valuation": 0.9,
        "LBO": 0.9,
        "M&A": 0.8,
        "deal rationale": 0.8,
        "Excel": 0.7,
        "PowerPoint": 0.6,
    },
    section_headers={
        "Experience": "Transaction Experience",
        "Skills": "Technical & Transaction Skills",
    },
    cover_letter_tone="transaction-focused",
    mandatory_keywords=("financial modeling", "valuation", "M&A", "deal"),
)

MARKETS_VARIANT = CVVariant(
    id="markets",
    label="Markets / Quant",
    locale="en-US",
    section_order=(
        "Technical Skills",
        "Quantitative Projects",
        "Professional Experience",
        "Education",
        "Projects",
        "Languages",
        "Certifications",
    ),
    keyword_priorities={
        "Python": 1.0,
        "statistics": 0.9,
        "Bloomberg": 0.9,
        "time series": 0.8,
        "quantitative research": 0.8,
        "SQL": 0.7,
        "pandas": 0.7,
    },
    section_headers={
        "Experience": "Quantitative Projects",
        "Skills": "Technical Skills",
    },
    cover_letter_tone="data-driven",
    mandatory_keywords=("Python", "statistics", "Bloomberg", "quantitative"),
)

CORPFIN_VARIANT = CVVariant(
    id="corporate_finance",
    label="Corporate Finance / FP&A",
    locale="en-US",
    section_order=(
        "Finance Experience",
        "Reporting & Analysis",
        "Professional Experience",
        "Education",
        "Technical Skills",
        "Projects",
        "Languages",
    ),
    keyword_priorities={
        "financial reporting": 1.0,
        "variance analysis": 0.9,
        "budgeting": 0.9,
        "FP&A": 0.8,
        "Excel": 0.9,
        "PowerBI": 0.7,
        "SAP": 0.6,
    },
    section_headers={
        "Experience": "Finance Experience",
        "Skills": "Financial Analysis Skills",
    },
    cover_letter_tone="reporting-focused",
    mandatory_keywords=(
        "financial reporting",
        "variance analysis",
        "budgeting",
        "FP&A",
    ),
)

ALL_VARIANTS = (MA_VARIANT, MARKETS_VARIANT, CORPFIN_VARIANT)

VARIANT_LABELS = {
    "m_a": "M&A / Investment Banking",
    "markets": "Markets / Quant",
    "corporate_finance": "Corporate Finance / FP&A",
}

JOB_FAMILY_TO_VARIANT = {
    "M&A / Investment Banking": ["m_a"],
    "Investment Banking": ["m_a"],
    "M&A": ["m_a"],
    "Markets / Quant": ["markets"],
    "Sales & Trading": ["markets"],
    "Quantitative Research": ["markets"],
    "Corporate Finance / FP&A": ["corporate_finance"],
    "FP&A": ["corporate_finance"],
    "Financial Planning": ["corporate_finance"],
    "Treasury": ["corporate_finance"],
}
