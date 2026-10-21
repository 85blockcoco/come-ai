from dataclasses import FrozenInstanceError, asdict

import pytest

from career.cv_fit import CoverageResult, FitGap, PipelineItem
from career.cv_quality.models import Provenance
from career.cv_variants import MA_VARIANT
from career.models import PipelineStage


def _provenance() -> Provenance:
    return Provenance(
        filename="approved-cv.pdf",
        filetype="pdf",
        text_length=4_200,
        page_count=2,
    )


def test_fit_gap_instantiation_serialization_and_provenance() -> None:
    provenance = _provenance()
    gap = FitGap(
        requirement="financial modeling",
        requirement_type="mandatory",
        current_state="unquantified",
        adapted_state="Add a quantified modeling result.",
        provenance=provenance,
        variant_specific=True,
    )

    assert gap.provenance is provenance
    assert asdict(gap) == {
        "requirement": "financial modeling",
        "requirement_type": "mandatory",
        "current_state": "unquantified",
        "adapted_state": "Add a quantified modeling result.",
        "provenance": {
            "filename": "approved-cv.pdf",
            "filetype": "pdf",
            "text_length": 4_200,
            "page_count": 2,
        },
        "variant_specific": True,
    }
    with pytest.raises(FrozenInstanceError):
        gap.current_state = "weak"  # type: ignore[misc]


def test_coverage_result_instantiation_and_recursive_serialization() -> None:
    gap = FitGap(
        requirement="valuation",
        requirement_type="mandatory",
        current_state="missing",
        adapted_state="Add evidence or retain the explicit placeholder.",
        provenance=None,
        variant_specific=True,
    )
    result = CoverageResult(
        mandatory_total=4,
        mandatory_covered=2,
        preferred_total=3,
        preferred_covered=1,
        mandatory_pct=50.0,
        preferred_pct=33.3,
        gaps=[gap],
        recommended_variant=MA_VARIANT,
        variant_rationale="Exact job-family match with cited profile evidence.",
    )

    serialized = asdict(result)
    assert serialized["gaps"][0]["provenance"] is None
    assert serialized["recommended_variant"]["id"] == "m_a"
    assert serialized["variant_rationale"] == ("Exact job-family match with cited profile evidence.")
    with pytest.raises(FrozenInstanceError):
        result.mandatory_pct = 0.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("stage", "value"),
    [
        (PipelineStage.DISCOVERED, "discovered"),
        (PipelineStage.QUALIFIED, "qualified"),
        (PipelineStage.SPRINT_QUEUED, "sprint_queued"),
        (PipelineStage.PREP_ANALYZED, "prep_analyzed"),
        (PipelineStage.VARIANT_SELECTED, "variant_selected"),
        (PipelineStage.KIT_GENERATED, "kit_generated"),
        (PipelineStage.TRACKING_CREATED, "tracking_created"),
    ],
)
def test_pipeline_stage_values(stage: PipelineStage, value: str) -> None:
    assert stage.value == value
    assert str(stage) == value


def test_pipeline_item_instantiation_and_serialization() -> None:
    item = PipelineItem(
        job_id="jpm-2027-iba",
        company="JPMorgan",
        title="Investment Banking Analyst Intern",
        stage=PipelineStage.KIT_GENERATED,
        variant=MA_VARIANT,
        variant_label=MA_VARIANT.label,
        kit_generated_at="2026-10-21T14:30:00Z",
        tracking_stage=None,
        readiness="prepare_now",
        match_score=87,
    )

    serialized = asdict(item)
    assert serialized["stage"] is PipelineStage.KIT_GENERATED
    assert serialized["variant"]["id"] == "m_a"
    assert serialized["variant_label"] == "M&A / Investment Banking"
    assert serialized["tracking_stage"] is None
    with pytest.raises(FrozenInstanceError):
        item.match_score = 0  # type: ignore[misc]
