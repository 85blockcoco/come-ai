from career.cv_fit import derive_pipeline_stage
from career.models import PipelineStage


def test_pipeline_stage_priority_is_deterministic() -> None:
    context = {
        "jobs": {"job-1": {"qualification_facts_json": "{}"}},
        "sprint_queue": [{"job_id": "job-1"}],
        "prep_cache": {"job-1"},
        "selected_variant": {"job-1": "m_a"},
        "application_drafts": [{"job_id": "job-1"}],
        "applications": [{"job_id": "job-1"}],
    }

    assert derive_pipeline_stage("job-1", context) is PipelineStage.TRACKING_CREATED
    context["applications"] = []
    assert derive_pipeline_stage("job-1", context) is PipelineStage.KIT_GENERATED
    context["application_drafts"] = []
    assert derive_pipeline_stage("job-1", context) is PipelineStage.VARIANT_SELECTED
    context["selected_variant"] = {}
    assert derive_pipeline_stage("job-1", context) is PipelineStage.PREP_ANALYZED
    context["prep_cache"] = set()
    assert derive_pipeline_stage("job-1", context) is PipelineStage.SPRINT_QUEUED
    context["sprint_queue"] = []
    assert derive_pipeline_stage("job-1", context) is PipelineStage.QUALIFIED
    context["jobs"]["job-1"]["qualification_facts_json"] = ""
    assert derive_pipeline_stage("job-1", context) is PipelineStage.DISCOVERED


def test_tracking_created_before_a_kit_does_not_claim_the_cycle_is_complete() -> None:
    context = {
        "jobs": {"job-1": {"qualification_facts_json": "1"}},
        "sprint_queue": [{"job_id": "job-1"}],
        "prep_cache": set(),
        "selected_variant": {},
        "application_drafts": [],
        "applications": [{"job_id": "job-1", "stage": "to_review"}],
    }

    assert derive_pipeline_stage("job-1", context) is PipelineStage.SPRINT_QUEUED
