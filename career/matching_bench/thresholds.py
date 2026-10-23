"""Regression thresholds of the adversarial bench (CVBOOST-08).

A bench that only prints numbers is a snapshot.  This module turns the
measured baseline into gates: a run that introduces a *new* defect fails, a
run that fixes one is reported as an improvement.

Two things are kept apart on purpose:

* the **limits** (what a run must satisfy) — hard invariants, determinism,
  suite size, oracle resolution;
* the **baseline** (what the current code does) — the number of defects
  already known, so that a fix lowers the bar instead of breaking the gate.

The thresholds are versioned next to the fixtures: a change of business rule
that breaks the bench must be a deliberate act, visible in the history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import contracts

THRESHOLDS_PATH = Path(__file__).resolve().parent / "fixtures" / "thresholds.json"

#: The gates every run must satisfy.
LIMIT_KEYS = (
    "cases_min",
    "hard_failures_max",
    "semantic_failures_max",
    "unstable_cases_max",
    "oracle_unresolved_max",
)

LIMIT_LABELS = {
    "cases_min": "Nombre minimal de couples synthétiques",
    "hard_failures_max": "Nombre maximal de défauts durs",
    "semantic_failures_max": "Nombre maximal d'écarts sémantiques",
    "unstable_cases_max": "Nombre maximal de cas non déterministes",
    "oracle_unresolved_max": "Nombre maximal de références d'oracle non résolues",
}


@dataclass(frozen=True)
class Evaluation:
    """The verdict of a run against the thresholds."""

    ok: bool
    measured: dict[str, Any]
    limits: dict[str, Any]
    violations: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "measured": self.measured,
            "limits": self.limits,
            "violations": self.violations,
        }


def measure_run(run: Any) -> dict[str, Any]:
    """The comparable numbers of a run."""
    outcomes = run.outcomes
    hard_failures = sum(len(outcome.hard_failures) for outcome in outcomes)
    semantic_failures = sum(len(outcome.semantic_failures) for outcome in outcomes)
    unstable = sum(
        1
        for outcome in outcomes
        if any(not check["ok"] for check in outcome.hard_checks if check["check"] == "determinism")
    )
    unresolved = sum(
        1
        for outcome in outcomes
        for check in outcome.semantic_checks
        if check["check"] == "requirement_detection"
        and any("référence ambiguë" in failure for failure in check["failures"])
    )
    return {
        "cases": len(outcomes),
        "hard_failures": hard_failures,
        "semantic_failures": semantic_failures,
        "unstable_cases": unstable,
        "oracle_unresolved": unresolved,
        "cases_passed": sum(1 for outcome in outcomes if outcome.passed),
    }


def default_limits() -> dict[str, Any]:
    """The limits of a fresh suite: only the structural ones are fixed."""
    return {
        "cases_min": contracts.MIN_CASES,
        "hard_failures_max": 0,
        "semantic_failures_max": 0,
        "unstable_cases_max": 0,
        "oracle_unresolved_max": 0,
    }


def evaluate(run: Any, limits: dict[str, Any] | None = None) -> Evaluation:
    """Check a run against the thresholds."""
    active = dict(default_limits())
    if limits:
        active.update({key: value for key, value in limits.items() if key in LIMIT_KEYS})
    measured = measure_run(run)
    violations: list[dict[str, Any]] = []

    if measured["cases"] < int(active["cases_min"]):
        violations.append(
            {
                "limit": "cases_min",
                "label": LIMIT_LABELS["cases_min"],
                "measured": measured["cases"],
                "allowed": int(active["cases_min"]),
                "direction": "min",
            }
        )
    if measured["hard_failures"] > int(active["hard_failures_max"]):
        violations.append(
            {
                "limit": "hard_failures_max",
                "label": LIMIT_LABELS["hard_failures_max"],
                "measured": measured["hard_failures"],
                "allowed": int(active["hard_failures_max"]),
                "direction": "max",
            }
        )
    if measured["semantic_failures"] > int(active["semantic_failures_max"]):
        violations.append(
            {
                "limit": "semantic_failures_max",
                "label": LIMIT_LABELS["semantic_failures_max"],
                "measured": measured["semantic_failures"],
                "allowed": int(active["semantic_failures_max"]),
                "direction": "max",
            }
        )
    if measured["unstable_cases"] > int(active["unstable_cases_max"]):
        violations.append(
            {
                "limit": "unstable_cases_max",
                "label": LIMIT_LABELS["unstable_cases_max"],
                "measured": measured["unstable_cases"],
                "allowed": int(active["unstable_cases_max"]),
                "direction": "max",
            }
        )
    if measured["oracle_unresolved"] > int(active["oracle_unresolved_max"]):
        violations.append(
            {
                "limit": "oracle_unresolved_max",
                "label": LIMIT_LABELS["oracle_unresolved_max"],
                "measured": measured["oracle_unresolved"],
                "allowed": int(active["oracle_unresolved_max"]),
                "direction": "max",
            }
        )
    return Evaluation(ok=not violations, measured=measured, limits=active, violations=violations)


def load_thresholds(path: Path | str | None = None) -> dict[str, Any]:
    """Read the versioned thresholds file."""
    target = Path(path) if path else THRESHOLDS_PATH
    if not target.is_file():
        raise FileNotFoundError(f"fichier de seuils introuvable : {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema_version") != contracts.THRESHOLDS_SCHEMA_VERSION:
        raise ValueError(
            f"{target.name} : version de schéma inattendue {payload.get('schema_version')!r}"
        )
    return payload


def save_thresholds(payload: dict[str, Any], path: Path | str | None = None) -> Path:
    """Write the versioned thresholds file."""
    target = Path(path) if path else THRESHOLDS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def build_thresholds(run: Any) -> dict[str, Any]:
    """Build the thresholds payload from a measured run."""
    measured = measure_run(run)
    return {
        "schema_version": contracts.THRESHOLDS_SCHEMA_VERSION,
        "suite_version": contracts.SUITE_VERSION,
        "as_of": contracts.BENCH_AS_OF,
        "note": (
            "Les limites correspondent a l'etat mesure actuel du code : un nouveau defaut "
            "fait echouer la porte, une correction la fait passer."
        ),
        "baseline": measured,
        "limits": {
            "cases_min": contracts.MIN_CASES,
            "hard_failures_max": measured["hard_failures"],
            "semantic_failures_max": measured["semantic_failures"],
            "unstable_cases_max": 0,
            "oracle_unresolved_max": 0,
        },
    }


def compare_runs(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare two serialized runs: regressions, improvements, status changes."""
    base_cases = {case["case_id"]: case for case in baseline.get("cases", [])}
    candidate_cases = {case["case_id"]: case for case in candidate.get("cases", [])}
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    added: list[str] = []
    removed: list[str] = []
    for case_id, case in candidate_cases.items():
        if case_id not in base_cases:
            added.append(case_id)
            continue
        was_ok = not base_cases[case_id]["hard_failed"] and not base_cases[case_id]["semantic_failed"]
        is_ok = not case["hard_failed"] and not case["semantic_failed"]
        if was_ok and not is_ok:
            regressions.append(
                {
                    "case_id": case_id,
                    "hard_failed": case["hard_failed"],
                    "semantic_failed": case["semantic_failed"],
                }
            )
        elif is_ok and not was_ok:
            improvements.append(
                {
                    "case_id": case_id,
                    "previously_failed": (
                        base_cases[case_id]["hard_failed"] + base_cases[case_id]["semantic_failed"]
                    ),
                }
            )
    for case_id in base_cases:
        if case_id not in candidate_cases:
            removed.append(case_id)
    return {
        "regressions": regressions,
        "improvements": improvements,
        "added_cases": added,
        "removed_cases": removed,
        "ok": not regressions and not added and not removed,
    }
