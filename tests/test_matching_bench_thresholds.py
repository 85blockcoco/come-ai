"""Tests of the regression thresholds of the bench (CVBOOST-08).

The thresholds must fail a run that introduces a defect, must not fail a run
that fixes one, and must never compare two runs that do not measure the same
thing.
"""

from __future__ import annotations

import json

import pytest

from career.matching_bench import contracts, thresholds
from career.matching_bench.runner import run_bench


def _run_payload() -> dict:
    run = run_bench()
    return run.to_dict()


def test_default_limits_keep_only_structural_gates() -> None:
    limits = thresholds.default_limits()
    assert limits["cases_min"] == contracts.MIN_CASES
    assert limits["unstable_cases_max"] == 0
    assert limits["oracle_unresolved_max"] == 0


def test_evaluation_reports_the_measured_numbers() -> None:
    run = run_bench()
    evaluation = thresholds.evaluate(run)
    assert evaluation.measured["cases"] == len(run.outcomes)
    assert evaluation.measured["unstable_cases"] == 0
    assert evaluation.measured["oracle_unresolved"] == 0


def test_a_new_hard_defect_breaks_the_gate() -> None:
    run = run_bench()
    strict = dict(thresholds.default_limits())
    strict["hard_failures_max"] = 0
    evaluation = thresholds.evaluate(run, strict)
    assert not evaluation.ok
    assert any(violation["limit"] == "hard_failures_max" for violation in evaluation.violations)


def test_a_new_semantic_defect_breaks_the_gate() -> None:
    run = run_bench()
    strict = dict(thresholds.default_limits())
    strict["semantic_failures_max"] = 0
    evaluation = thresholds.evaluate(run, strict)
    assert not evaluation.ok
    assert any(violation["limit"] == "semantic_failures_max" for violation in evaluation.violations)


def test_a_too_small_suite_breaks_the_gate() -> None:
    run = run_bench()
    strict = dict(thresholds.default_limits())
    strict["cases_min"] = 10_000
    evaluation = thresholds.evaluate(run, strict)
    assert not evaluation.ok
    assert any(violation["limit"] == "cases_min" for violation in evaluation.violations)


def test_the_stored_thresholds_are_the_measured_baseline() -> None:
    stored = thresholds.load_thresholds()
    assert stored["schema_version"] == contracts.THRESHOLDS_SCHEMA_VERSION
    run = run_bench()
    measured = thresholds.measure_run(run)
    assert stored["baseline"]["hard_failures"] == measured["hard_failures"]
    assert stored["baseline"]["semantic_failures"] == measured["semantic_failures"]
    assert stored["limits"]["hard_failures_max"] == measured["hard_failures"]
    assert stored["limits"]["semantic_failures_max"] == measured["semantic_failures"]


def test_compare_detects_a_regression() -> None:
    baseline = _run_payload()
    candidate = json.loads(json.dumps(baseline))
    healthy = next(
        case for case in candidate["cases"] if not case["hard_failed"] and not case["semantic_failed"]
    )
    healthy["hard_failed"] = ["evidence_verbatim"]
    healthy["semantic_failed"] = ["support_decision"]
    comparison = thresholds.compare_runs(baseline, candidate)
    assert not comparison["ok"]
    assert comparison["regressions"]
    assert comparison["regressions"][0]["case_id"] == healthy["case_id"]


def test_compare_detects_an_improvement() -> None:
    baseline = _run_payload()
    candidate = json.loads(json.dumps(baseline))
    broken = next(case for case in candidate["cases"] if case["hard_failed"] or case["semantic_failed"])
    broken["hard_failed"] = []
    broken["semantic_failed"] = []
    comparison = thresholds.compare_runs(baseline, candidate)
    assert comparison["improvements"]
    assert comparison["improvements"][0]["case_id"] == broken["case_id"]


def test_compare_detects_a_changed_suite() -> None:
    baseline = _run_payload()
    candidate = json.loads(json.dumps(baseline))
    candidate["cases"] = candidate["cases"][:-1]
    comparison = thresholds.compare_runs(baseline, candidate)
    assert not comparison["ok"]
    assert comparison["removed_cases"]


def test_thresholds_file_is_written_and_read_back(tmp_path) -> None:
    run = run_bench()
    payload = thresholds.build_thresholds(run)
    path = thresholds.save_thresholds(payload, tmp_path / "thresholds.json")
    reloaded = thresholds.load_thresholds(path)
    assert reloaded["limits"] == payload["limits"]
    assert reloaded["baseline"] == payload["baseline"]


def test_a_threshold_file_with_a_wrong_schema_is_refused(tmp_path) -> None:
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({"schema_version": "autre/1"}), encoding="utf-8")
    with pytest.raises(ValueError):
        thresholds.load_thresholds(path)


def test_a_missing_threshold_file_is_refused(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        thresholds.load_thresholds(tmp_path / "absent.json")
