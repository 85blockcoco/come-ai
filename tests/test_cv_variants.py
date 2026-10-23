from dataclasses import FrozenInstanceError

import pytest

from career.cv_variants import (
    ALL_VARIANTS,
    CORPFIN_VARIANT,
    JOB_FAMILY_TO_VARIANT,
    MARKETS_VARIANT,
    MA_VARIANT,
    VARIANT_LABELS,
)


def test_ma_variant_has_exact_configuration() -> None:
    assert MA_VARIANT.id == "m_a"
    assert MA_VARIANT.label == "M&A / Investment Banking"
    assert MA_VARIANT.locale == "en-GB"
    assert MA_VARIANT.section_order == (
        "Professional Experience",
        "Transaction Experience",
        "Education",
        "Technical Skills",
        "Projects",
        "Languages",
        "Certifications",
    )
    assert MA_VARIANT.keyword_priorities == {
        "financial modeling": 1.0,
        "valuation": 0.9,
        "LBO": 0.9,
        "M&A": 0.8,
        "deal rationale": 0.8,
        "Excel": 0.7,
        "PowerPoint": 0.6,
    }
    assert MA_VARIANT.section_headers == {
        "Experience": "Transaction Experience",
        "Skills": "Technical & Transaction Skills",
    }
    assert MA_VARIANT.cover_letter_tone == "transaction-focused"
    assert MA_VARIANT.mandatory_keywords == (
        "financial modeling",
        "valuation",
        "M&A",
        "deal",
    )


def test_markets_variant_has_exact_configuration() -> None:
    assert MARKETS_VARIANT.id == "markets"
    assert MARKETS_VARIANT.label == "Markets / Quant"
    assert MARKETS_VARIANT.locale == "en-US"
    assert MARKETS_VARIANT.section_order == (
        "Technical Skills",
        "Quantitative Projects",
        "Professional Experience",
        "Education",
        "Projects",
        "Languages",
        "Certifications",
    )
    assert MARKETS_VARIANT.keyword_priorities == {
        "Python": 1.0,
        "statistics": 0.9,
        "Bloomberg": 0.9,
        "time series": 0.8,
        "quantitative research": 0.8,
        "SQL": 0.7,
        "pandas": 0.7,
    }
    assert MARKETS_VARIANT.section_headers == {
        "Experience": "Quantitative Projects",
        "Skills": "Technical Skills",
    }
    assert MARKETS_VARIANT.cover_letter_tone == "data-driven"
    assert MARKETS_VARIANT.mandatory_keywords == (
        "Python",
        "statistics",
        "Bloomberg",
        "quantitative",
    )


def test_corpfin_variant_has_exact_configuration() -> None:
    assert CORPFIN_VARIANT.id == "corporate_finance"
    assert CORPFIN_VARIANT.label == "Corporate Finance / FP&A"
    assert CORPFIN_VARIANT.locale == "en-US"
    assert CORPFIN_VARIANT.section_order == (
        "Finance Experience",
        "Reporting & Analysis",
        "Professional Experience",
        "Education",
        "Technical Skills",
        "Projects",
        "Languages",
    )
    assert CORPFIN_VARIANT.keyword_priorities == {
        "financial reporting": 1.0,
        "variance analysis": 0.9,
        "budgeting": 0.9,
        "FP&A": 0.8,
        "Excel": 0.9,
        "PowerBI": 0.7,
        "SAP": 0.6,
    }
    assert CORPFIN_VARIANT.section_headers == {
        "Experience": "Finance Experience",
        "Skills": "Financial Analysis Skills",
    }
    assert CORPFIN_VARIANT.cover_letter_tone == "reporting-focused"
    assert CORPFIN_VARIANT.mandatory_keywords == (
        "financial reporting",
        "variance analysis",
        "budgeting",
        "FP&A",
    )


def test_variant_exports_preserve_deterministic_order_and_labels() -> None:
    assert ALL_VARIANTS == (MA_VARIANT, MARKETS_VARIANT, CORPFIN_VARIANT)
    assert VARIANT_LABELS == {
        "m_a": "M&A / Investment Banking",
        "markets": "Markets / Quant",
        "corporate_finance": "Corporate Finance / FP&A",
    }


def test_job_family_mapping_matches_classification_contract() -> None:
    assert JOB_FAMILY_TO_VARIANT == {
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


def test_variants_are_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        MA_VARIANT.label = "Changed"  # type: ignore[misc]
