"""End-to-end tests of the adversarial bench (CVBOOST-08).

The bench must stay reproducible, must separate the three axes, and must
keep the recorded baseline honest: a new defect fails the suite, a fixed
defect updates the baseline on purpose.
"""

from __future__ import annotations

import json

from career.matching_bench import contracts, thresholds
from career.matching_bench.fixtures import load_cases
from career.matching_bench.report import build_report, cross_axis_flags, render_markdown
from career.matching_bench.runner import build_observation, observation_hash, run_bench, run_case

CASES = {case.id: case for case in load_cases()}


def test_two_executions_produce_identical_observations() -> None:
    case = CASES["CVB08-FP-001"]
    first = build_observation(case)
    second = build_observation(case)
    assert observation_hash(first) == observation_hash(second)


def test_the_whole_bench_is_reproducible() -> None:
    first = run_bench()
    second = run_bench()
    assert [outcome.observation_digest for outcome in first.outcomes] == [
        outcome.observation_digest for outcome in second.outcomes
    ]
    assert first.metrics == second.metrics


def test_metrics_separate_simulated_application_and_network() -> None:
    run = run_bench()
    metrics = run.metrics
    assert set(metrics) == {"simulated", "application_verified", "network_real"}
    assert metrics["simulated"]["cases"] == len(run.outcomes)
    assert metrics["application_verified"]["cases"] == len(run.outcomes)
    assert metrics["network_real"]["cases"] == 0
    assert metrics["network_real"]["status"] == "not_measured"
    assert "réseau" in metrics["network_real"]["reason"].lower()


def test_application_verified_claims_are_honest() -> None:
    run = run_bench()
    verified = run.metrics["application_verified"]
    assert verified["determinism"]["unstable_cases"] == 0
    assert verified["determinism"]["stable_cases"] == len(run.outcomes)
    assert verified["cases_with_full_observation"] == len(run.outcomes)


def test_three_axes_are_reported_separately() -> None:
    run = run_bench()
    axes = run.axes
    assert set(axes) >= {"admissibilite", "pertinence", "couverture"}
    assert axes["admissibilite"]["counts"]
    assert axes["pertinence"]["scores"] == len(run.outcomes)
    assert axes["couverture"]["requirements_detected"] > 0
    # Les axes ne sont jamais fusionnés en un score unique.
    assert "score_global" not in axes


def test_every_case_is_measured_on_the_three_axes() -> None:
    run = run_bench()
    for outcome in run.outcomes:
        observation = outcome.observation
        assert observation["prep"]["requirements"] is not None
        assert observation["requirements"]["requirements"] is not None
        assert observation["match"]["components"] is not None
        assert observation["education"]["status"] in contracts.EDUCATION_STATUSES
        assert observation["eligibility"]["target_status"] in {
            "conforming", "non_conforming", "to_verify"
        }


def test_the_current_code_respects_the_recorded_thresholds() -> None:
    run = run_bench()
    stored = thresholds.load_thresholds()
    evaluation = thresholds.evaluate(run, stored["limits"])
    assert evaluation.ok, evaluation.violations


def test_the_baseline_matches_the_recorded_defects() -> None:
    """Une correction doit être visible : la ligne de base est révisée à la main."""
    run = run_bench()
    stored = thresholds.load_thresholds()
    measured = thresholds.measure_run(run)
    assert measured["hard_failures"] == stored["baseline"]["hard_failures"]
    assert measured["semantic_failures"] == stored["baseline"]["semantic_failures"]
    assert measured["cases"] == stored["baseline"]["cases"]


def test_known_hard_defects_are_the_contact_leaks() -> None:
    """Les trois défauts durs connus sont des fuites de contact."""
    run = run_bench()
    hard = [defect for defect in run.defects if defect["kind"] == "invariant_dur"]
    assert {defect["case_id"] for defect in hard} == {
        "CVB08-CN-002",
        "CVB08-CN-003",
        "CVB08-CN-004",
    }
    assert {defect["check"] for defect in hard} == {"no_contact_leak"}


def test_detected_defects_are_classified_by_family() -> None:
    run = run_bench()
    families = {defect["family"] for defect in run.defects}
    assert "faux_positif_lexical" in families
    assert "negation" in families
    assert "avantages" in families


def test_cross_axis_flags_are_reported_without_being_arbitrated() -> None:
    run = run_bench()
    flags = cross_axis_flags(run)
    assert isinstance(flags, list)
    for flag in flags:
        assert flag["niveau_academique"] == "outside_preference"
        assert flag["admissibilite"] == "eligible"


def test_the_markdown_report_mentions_the_three_provenances() -> None:
    run = run_bench()
    evaluation = thresholds.evaluate(run, thresholds.load_thresholds()["limits"])
    markdown = render_markdown(run, evaluation)
    assert "Simulée" in markdown
    assert "Application vérifiée" in markdown
    assert "Réseau réel" in markdown
    assert "not_measured" in markdown or "réseau" in markdown.lower()


def test_the_json_report_is_serialisable() -> None:
    run = run_bench()
    evaluation = thresholds.evaluate(run, thresholds.load_thresholds()["limits"])
    payload = build_report(run, evaluation)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert json.loads(encoded)["metrics"]["simulated"]["cases"] == len(run.outcomes)


def test_a_single_case_can_be_run_in_isolation() -> None:
    outcome = run_case(CASES["CVB08-FP-001"])
    assert outcome.case_id == "CVB08-FP-001"
    assert outcome.hard_checks
    assert outcome.semantic_checks
    assert outcome.observation_digest


def test_reports_are_written_to_disk(tmp_path) -> None:
    from career.matching_bench.report import write_reports

    run = run_bench()
    written = write_reports(run, tmp_path)
    assert written["json"].is_file()
    assert written["markdown"].is_file()
    assert json.loads(written["json"].read_text(encoding="utf-8"))["cases"]
