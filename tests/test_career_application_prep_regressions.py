"""Regression tests for deterministic application-preparation matching."""

from career.application_prep import prepare_application


def test_short_finance_skill_is_verified_from_profile() -> None:
    """Acronyms such as SQL are valid evidence, despite being shorter than 4 chars."""
    result = prepare_application(
        {"skills": "SQL and financial modelling"},
        {},
        {
            "title": "Risk Intern",
            "company": "Synthetic Bank",
            "requirements": "SQL is required.",
        },
    )

    assert result["matched_elements"] == [
        {
            "requirement": "SQL is required.",
            "profile_field": "skills",
            "evidence": "SQL and financial modelling",
            "matched_on": ["sql"],
        }
    ]
    assert result["unverified_elements"] == []
