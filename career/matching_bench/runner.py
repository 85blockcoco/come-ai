"""Execution of the adversarial matching bench (CVBOOST-08).

The runner is a harness, not a new business rule: it calls the *existing*
Career code paths — the application preparation, the requirement provenance
contract, the brief matching, the education access and the offer
qualification — and then confronts what they produced with the hand-written
ground truth of each synthetic case.

Nothing here is simulated: every observation comes from the application
itself.  What *is* simulated is the source data (synthetic offers and
profiles) and what is *not* measured is the network (no call is ever made).
The report keeps those three statements apart.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from career.application_prep import prepare_application
from career.education_access import assess_education_access
from career.offer_qualification import qualify_offer
from career.offer_requirements import analyze_offer
from career.stage_search import score_brief_match

from . import contracts, validators
from .fixtures import Case, load_cases


def observation_hash(observation: dict[str, Any]) -> str:
    """Stable fingerprint of an observation (byte-for-byte comparable)."""
    payload = json.dumps(observation, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_observation(case: Case) -> dict[str, Any]:
    """Run the real application code paths for one synthetic couple."""
    profile = case.profile_fields
    offer = case.offer_fields
    criteria = case.criteria
    as_of = date.fromisoformat(contracts.BENCH_AS_OF)
    qualification = qualify_offer(
        offer,
        minimum_duration_months=int(criteria.get("minimum_stage_duration_months") or 6),
        allowed_contract_types=criteria.get("allowed_contract_types"),
        allowed_start_months=criteria.get("allowed_start_months"),
        minimum_stage_duration_months=int(criteria.get("minimum_stage_duration_months") or 6),
        as_of=as_of,
    )
    return {
        "prep": prepare_application(profile, {}, offer),
        "requirements": analyze_offer(offer),
        "match": score_brief_match(case.brief or {}, offer),
        "education": assess_education_access(offer),
        "eligibility": qualification.to_dict(),
    }


@dataclass
class CaseOutcome:
    """What the bench observed for one synthetic couple."""

    case_id: str
    family: str
    axis: str
    severity: str
    title: str
    hard_checks: list[dict[str, Any]] = field(default_factory=list)
    semantic_checks: list[dict[str, Any]] = field(default_factory=list)
    observation: dict[str, Any] = field(default_factory=dict)
    observation_digest: str = ""
    duration_ms: float = 0.0

    @property
    def hard_failures(self) -> list[dict[str, Any]]:
        return [check for check in self.hard_checks if not check["ok"]]

    @property
    def semantic_failures(self) -> list[dict[str, Any]]:
        return [check for check in self.semantic_checks if not check["ok"]]

    @property
    def passed(self) -> bool:
        return not self.hard_failures and not self.semantic_failures

    def to_dict(self, *, include_observation: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "case_id": self.case_id,
            "family": self.family,
            "axis": self.axis,
            "severity": self.severity,
            "title": self.title,
            "hard_checks": self.hard_checks,
            "semantic_checks": self.semantic_checks,
            "hard_failed": [check["check"] for check in self.hard_failures],
            "semantic_failed": [check["check"] for check in self.semantic_failures],
            "observation_digest": self.observation_digest,
            "duration_ms": round(self.duration_ms, 3),
        }
        if include_observation:
            payload["observation"] = self.observation
        return payload


def run_case(case: Case) -> CaseOutcome:
    """Execute one case: observation, then every validator."""
    started = time.perf_counter()
    observation = build_observation(case)
    replay = build_observation(case)
    digest = observation_hash(observation)

    hard_checks = [
        validator(case, observation)
        for validator in validators.HARD_VALIDATORS
    ]
    hard_checks.append(validators.check_determinism(case, observation, observation_hash(replay)))
    semantic_checks = [
        validator(case, observation)
        for validator in validators.SEMANTIC_VALIDATORS
    ]
    return CaseOutcome(
        case_id=case.id,
        family=case.family,
        axis=case.axis,
        severity=case.severity,
        title=case.title,
        hard_checks=hard_checks,
        semantic_checks=semantic_checks,
        observation=observation,
        observation_digest=digest,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


@dataclass
class BenchRun:
    """The result of a full bench execution."""

    suite_version: str
    schema_version: str
    as_of: str
    outcomes: list[CaseOutcome] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    axes: dict[str, Any] = field(default_factory=dict)
    defects: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, *, include_observations: bool = False) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "suite_version": self.suite_version,
            "as_of": self.as_of,
            "network_policy": contracts.NETWORK_POLICY,
            "metrics": self.metrics,
            "axes": self.axes,
            "defects": self.defects,
            "cases": [outcome.to_dict(include_observation=include_observations) for outcome in self.outcomes],
        }


def _check_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check for check in checks if not check["ok"]]
    return {
        "total": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "failed_checks": sorted({str(check["check"]) for check in failed}),
    }


def _family_metrics(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    families: dict[str, Any] = {}
    for outcome in outcomes:
        entry = families.setdefault(
            outcome.family,
            {"cases": 0, "hard_failures": 0, "semantic_failures": 0, "cases_with_defect": 0},
        )
        entry["cases"] += 1
        entry["hard_failures"] += len(outcome.hard_failures)
        entry["semantic_failures"] += len(outcome.semantic_failures)
        if outcome.hard_failures or outcome.semantic_failures:
            entry["cases_with_defect"] += 1
    for entry in families.values():
        entry["agreement_rate"] = round(
            (entry["cases"] - entry["cases_with_defect"]) / entry["cases"], 4
        ) if entry["cases"] else 0.0
    return families


def _axis_metrics(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    admissibility: dict[str, int] = {"eligible": 0, "ineligible": 0, "unknown": 0}
    education: dict[str, int] = {}
    coverage_total = 0
    coverage_sum = 0
    relevance_scores: list[int] = []
    unknown_relevance = 0
    for outcome in outcomes:
        observation = outcome.observation
        eligibility = observation.get("eligibility") or {}
        status = str(eligibility.get("target_status") or "to_verify")
        verdict = contracts.ELIGIBILITY_BY_TARGET_STATUS.get(status, "unknown")
        admissibility[verdict] = admissibility.get(verdict, 0) + 1
        level = str((observation.get("education") or {}).get("status") or "unknown")
        education[level] = education.get(level, 0) + 1
        coverage = (observation.get("prep") or {}).get("cv_coverage") or {}
        coverage_total += int(coverage.get("requirements_total") or 0)
        coverage_sum += int(coverage.get("coverage_percent") or 0)
        match = observation.get("match") or {}
        score = match.get("score")
        if isinstance(score, int):
            relevance_scores.append(score)
        else:
            unknown_relevance += 1
    return {
        "admissibilite": {
            "description": "Verdict de compatibilité avec les critères déclarés (offre + critères).",
            "counts": admissibility,
        },
        "pertinence": {
            "description": "Score de correspondance avec le brief de recherche (comparaison lexicale).",
            "scores": len(relevance_scores),
            "score_mean": round(sum(relevance_scores) / len(relevance_scores), 2) if relevance_scores else None,
            "score_min": min(relevance_scores) if relevance_scores else None,
            "score_max": max(relevance_scores) if relevance_scores else None,
            "not_scored": unknown_relevance,
        },
        "couverture": {
            "description": "Couverture documentaire du CV (exigences étayées / exigences détectées).",
            "requirements_detected": coverage_total,
            "coverage_percent_mean": round(coverage_sum / len(outcomes), 2) if outcomes else None,
        },
        "education_levels": education,
        "note": (
            "Ces trois axes sont mesurés séparément et ne sont jamais additionnés : "
            "une forte couverture documentaire ne dit rien de l'admissibilité, "
            "et un score de pertinence ne dit rien de la couverture."
        ),
    }


def _collect_defects(outcomes: list[CaseOutcome]) -> list[dict[str, Any]]:
    defects: list[dict[str, Any]] = []
    for outcome in outcomes:
        for check in outcome.hard_failures:
            defects.append(
                {
                    "case_id": outcome.case_id,
                    "family": outcome.family,
                    "severity": outcome.severity,
                    "kind": "invariant_dur",
                    "check": check["check"],
                    "detail": check["detail"],
                    "failures": check["failures"],
                }
            )
        for check in outcome.semantic_failures:
            defects.append(
                {
                    "case_id": outcome.case_id,
                    "family": outcome.family,
                    "severity": outcome.severity,
                    "kind": "ecart_semantique",
                    "check": check["check"],
                    "detail": check["detail"],
                    "failures": check["failures"],
                }
            )
    return defects


def run_bench(cases: list[Case] | None = None) -> BenchRun:
    """Execute the whole suite and compute the separated metrics."""
    suite = cases if cases is not None else load_cases()
    outcomes = [run_case(case) for case in suite]
    hard_checks = [check for outcome in outcomes for check in outcome.hard_checks]
    semantic_checks = [check for outcome in outcomes for check in outcome.semantic_checks]
    defects = _collect_defects(outcomes)
    run = BenchRun(
        suite_version=contracts.SUITE_VERSION,
        schema_version=contracts.SCHEMA_VERSION,
        as_of=contracts.BENCH_AS_OF,
        outcomes=outcomes,
        axes=_axis_metrics(outcomes),
        defects=defects,
    )
    run.metrics = {
        "simulated": {
            "description": (
                "Métriques calculées sur des couples synthétiques, exécution locale et déterministe."
            ),
            "cases": len(outcomes),
            "hard_checks": _check_summary(hard_checks),
            "semantic_checks": _check_summary(semantic_checks),
            "cases_passed": sum(1 for outcome in outcomes if outcome.passed),
            "cases_with_defect": sum(1 for outcome in outcomes if not outcome.passed),
            "by_family": _family_metrics(outcomes),
        },
        "application_verified": {
            "description": (
                "Comportement produit par le code applicatif réel (préparation, provenance des exigences, "
                "matching du brief, accès académique, qualification de l'offre)."
            ),
            "cases": len(outcomes),
            "cases_with_full_observation": sum(1 for outcome in outcomes if outcome.observation),
            "determinism": {
                "stable_cases": sum(
                    1 for outcome in outcomes
                    if all(check["ok"] for check in outcome.hard_checks if check["check"] == "determinism")
                ),
                "unstable_cases": sum(
                    1 for outcome in outcomes
                    if any(not check["ok"] for check in outcome.hard_checks if check["check"] == "determinism")
                ),
            },
        },
        "network_real": {
            "description": "Exécution sur une source réelle ou le réseau public.",
            "status": "not_measured",
            "cases": 0,
            "reason": contracts.NETWORK_POLICY,
        },
    }
    return run
