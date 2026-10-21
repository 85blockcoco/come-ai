from career.cv_fit import compute_coverage, generate_diff
from career.cv_quality.models import (
    CVAnalysisResult,
    ExperienceEntry,
    Finding,
    Provenance,
    ReadabilityScore,
    SectionReading,
)
from career.cv_variants import MA_VARIANT


def _analysis() -> CVAnalysisResult:
    return CVAnalysisResult(
        findings=[
            Finding(
                code="MISSING_SECTION",
                status="RISK",
                message="Projects section missing",
                source_offset=0,
                source_excerpt="",
                metadata={"section": "Projects"},
            ),
            Finding(
                code="UNQUANTIFIED_EXPERIENCE",
                status="RISK",
                message="Experience has no metric",
                source_offset=42,
                source_excerpt="SMBC Analyst",
                metadata=None,
            ),
        ],
        sections=[
            SectionReading("Education", 0, 20, "EDHEC"),
            SectionReading("Experience", 21, 100, "SMBC Analyst"),
        ],
        experiences=[
            ExperienceEntry(
                company="SMBC",
                role="Analyst",
                start_date="2026-01",
                end_date="2026-06",
                description="Automated files with Python",
                has_quantified_result=False,
                source_offset=42,
            )
        ],
        readability=ReadabilityScore(8.0, 12.0, 0.2),
        provenance=Provenance("current-cv.pdf", "pdf", 100, 1),
    )


def _job() -> dict:
    return {
        "qualification": {
            "missing_fields": ["start_date"],
            "provenance": {
                "start_date": {
                    "source": "offer.requirements",
                    "quote": "Starting January 2027",
                    "offset": 10,
                }
            },
        },
        "cv_action_plan": [{"requirement": "financial modeling", "status": "needs_evidence"}],
        "matched_elements": [
            {
                "requirement": "valuation",
                "profile_field": "experience",
                "evidence": "Valued two companies using DCF",
            }
        ],
    }


def test_coverage_splits_mandatory_and_preferred_requirements() -> None:
    result = compute_coverage(
        _job(),
        _analysis(),
        {
            "experience": "Valued two companies using DCF; financial modeling",
            "skills": "Excel",
            "projects": "",
        },
        MA_VARIANT,
    )

    assert result.mandatory_total == 5
    assert result.mandatory_covered == 2
    assert result.mandatory_pct == 40.0
    assert result.preferred_total == 9
    assert result.preferred_covered == 4
    assert result.preferred_pct == 44.4
    assert result.recommended_variant is MA_VARIANT


def test_diff_is_actionable_bounded_and_cited() -> None:
    analysis = _analysis()
    coverage = compute_coverage(
        _job(),
        analysis,
        {
            "experience": "Valued two companies using DCF; financial modeling",
            "skills": "Excel",
            "projects": "",
        },
        MA_VARIANT,
    )

    gaps = generate_diff(coverage, analysis, {}, MA_VARIANT, max_gaps=5)

    assert len(gaps) <= 5
    assert all(gap.adapted_state for gap in gaps)
    assert all(gap.provenance or gap.current_state == "missing" for gap in gaps)
    assert any(gap.current_state == "unquantified" for gap in gaps)
    assert any(gap.current_state == "wrong_order" for gap in gaps)
    assert any(gap.requirement == "Projects" for gap in gaps)
