from career.cv_fit import classify_variant
from career.cv_variants import ALL_VARIANTS


def test_classification_ma_exact_match() -> None:
    result = classify_variant(
        {
            "job_family": "M&A / Investment Banking",
            "requirements": "Financial modeling, valuation, LBO and M&A deal rationale.",
            "qualification": {"provenance": {}},
        },
        {"experience": "Built financial modeling and valuation work for an M&A deal."},
        ALL_VARIANTS,
    )

    assert result.primary_variant.id == "m_a"
    assert result.scores["m_a"] > 0.8
    assert "job_family" in result.rationale


def test_classification_markets_from_keywords_without_family_match() -> None:
    result = classify_variant(
        {
            "job_family": "Other",
            "requirements": "Python statistics Bloomberg quantitative research",
            "qualification": {"provenance": {}},
        },
        {"experience": "Python and statistics for quantitative analysis"},
        ALL_VARIANTS,
    )

    assert result.primary_variant.id == "markets"
    assert result.scores["markets"] == 0.55


def test_classification_corporate_finance_family_selects_corporate_finance_variant() -> None:
    result = classify_variant(
        {
            "job_family": "Corporate Finance",
            "requirements": "Financial reporting, budgeting and Excel.",
            "qualification": {"provenance": {}},
        },
        {"experience": ""},
        ALL_VARIANTS,
    )

    assert result.primary_variant.id == "corporate_finance"
    assert result.scores["corporate_finance"] == 0.7
    assert "job_family" in result.rationale


def test_classification_tie_break_is_deterministic() -> None:
    result = classify_variant({}, {}, ALL_VARIANTS)

    assert result.primary_variant.id == "m_a"
    assert result.scores == {
        "m_a": 0.0,
        "markets": 0.0,
        "corporate_finance": 0.0,
    }
    assert result.rationale == "Aucun signal fort ; défaut M&A"
