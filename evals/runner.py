"""Exécution des cas d'évaluation, métriques et comparaison de runs.

Le runner est volontairement découplé du système sous test : toute cible
implémentant ``run(case) -> observation`` peut être mesurée. Deux cibles sont
fournies :

* :class:`SimulatedTarget` — observation parfaite reconstruite depuis
  ``case.expected``. Elle sert **uniquement** à valider le runner lui-même
  (détection, métriques, comparaison). Elle ne prouve rien sur un modèle IA.
* :class:`FaultInjectionTarget` — la même cible avec une faute déterministe
  injectée, pour démontrer que chaque famille de défaut est détectée.

Aucun appel réseau, aucun secret, aucune donnée personnelle n'entre en jeu.
"""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import resource
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .checks import run_checks
from .schema import Case, load_cases, summarize_suite

RUNS_DIR = Path(__file__).resolve().parents[1] / ".devkit" / "evals" / "runs"
EXECUTION_KINDS = {"real", "simulated", "unknown"}


@dataclass
class TargetResult:
    """Explicit adapter result; unsupported and crashes never become successes."""

    observation: dict[str, Any] | None = None
    status: str = "real"  # real | simulated | unsupported | execution_error
    reason: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)


class Target(Protocol):
    """Contrat minimal d'une cible d'évaluation."""

    name: str
    execution_kind: str
    supported_features: set[str]

    def run(self, case: Case) -> dict[str, Any] | TargetResult:
        """Produit une observation pour le cas donné."""
        ...


# --------------------------------------------------------------- cibles simulées

class SimulatedTarget:
    """Cible simulée : renvoie l'observation idéale du cas.

    Strictement outil de test du runner. Les taux de réussite produits par
    cette cible ne sont **jamais** une mesure de la qualité d'un modèle IA.
    """

    name = "simulated"
    execution_kind = "simulated"

    def run(self, case: Case) -> dict[str, Any]:
        return copy.deepcopy(case.expected)


# Familles de fautes injectables. Chaque mode démontre qu'une famille de
# défauts réels (réponse incorrecte, fait inventé, citation fausse, etc.)
# est effectivement captée par les validateurs.
FAULT_MODES = (
    "wrong_answer",       # valeur numérique fausse
    "invented_fact",      # fait hors contexte
    "bad_citation",       # citation vers source inexistante
    "lost_fact",          # fait attendu absent (perte d'information)
    "wrong_structure",    # champ structuré manquant
    "wrong_tool",         # mauvais choix d'outil
    "invalid_plan",       # plan avec outil inconnu
    "quota_overrun",      # consommation au-dessus du plafond
    "silent_failure",     # échec non signalé (réponse vide, pas d'erreur)
    "fabricated_error",   # erreur signalée à tort sur un cas valide
)


class FaultInjectionTarget:
    """Cible simulée corrompue de façon déterministe selon ``mode``."""

    execution_kind = "simulated"

    def __init__(self, mode: str):
        if mode not in FAULT_MODES:
            raise ValueError(f"mode de faute inconnu : {mode!r} (choix : {FAULT_MODES})")
        self.mode = mode
        self.name = f"simulated+fault:{mode}"

    def run(self, case: Case) -> dict[str, Any]:
        observation = copy.deepcopy(case.expected)
        checks = [c["check"] for c in case.acceptance]
        if self.mode == "wrong_answer":
            for crit in case.acceptance:
                if crit["check"] == "numeric_close":
                    path = crit["path"]
                    _mutate_number(observation, path, crit["value"] + max(1.0, abs(crit["value"]) * 0.1))
                    break
            else:
                _mutate_first_exact(observation, case)
        elif self.mode == "invented_fact" and "no_hallucinated_facts" in checks:
            observation.setdefault("facts", []).append("Fait complètement hors contexte (inventé).")
        elif self.mode == "bad_citation" and "citations_valid" in checks:
            observation.setdefault("citations", []).append(
                {"source_id": "SOURCE_INCONNUE_404", "quote": "extrait inventé"}
            )
        elif self.mode == "lost_fact" and "facts_present" in checks:
            facts = observation.get("facts") or []
            if facts:
                facts.pop()
        elif self.mode == "wrong_structure" and "structure_valid" in checks:
            structured = observation.get("structured") or {}
            if structured:
                structured.pop(next(iter(structured)))
            else:
                observation["structured"] = None
        elif self.mode == "wrong_tool" and "tools_called" in checks:
            observation["tools_called"] = ["outil_inexistant"]
        elif self.mode == "invalid_plan" and "plan_valid" in checks:
            observation.setdefault("plan", []).append(
                {"step_id": "etape-corrompue", "tool": "outil_inconnu",
                 "arguments": {"x": 1}, "depends_on": []}
            )
        elif self.mode == "quota_overrun" and "budget_respected" in checks:
            usage = observation.get("usage") or {}
            observation["usage"] = {k: (v * 100 if isinstance(v, (int, float)) else v)
                                    for k, v in usage.items()} or {"api_calls": 999}
        elif self.mode == "silent_failure" and "error_signaled" in checks:
            observation["error"] = None
            observation["answer"] = None
            observation["structured"] = None
        elif self.mode == "fabricated_error" and "no_error" in checks:
            observation["error"] = "Panne interne simulée (fausse alerte)."
            observation["answer"] = None
        return observation


def _mutate_number(observation: dict, path: str, value: float) -> None:
    parts = path.split(".")
    node = observation
    for part in parts[:-1]:
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return
    if isinstance(node, dict):
        node[parts[-1]] = value


def _mutate_first_exact(observation: dict, case: Case) -> None:
    for crit in case.acceptance:
        if crit["check"] == "exact_value":
            _mutate_number(observation, crit["path"], "valeur incorrecte (injetée)")
            return


# ------------------------------------------------------------------ exécution

@dataclass
class CaseResult:
    case_id: str
    category: str
    severity: str
    status: str                    # "executed" | "unsupported"
    passed: bool | None
    duration_ms: float
    checks: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    execution_kind: str = "unknown"
    outcome: str = "unknown"
    trace: list[dict[str, Any]] = field(default_factory=list)
    observation: dict[str, Any] | None = None
    contract_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 3),
            "checks": self.checks,
            "reason": self.reason,
            "execution_kind": self.execution_kind,
            "outcome": self.outcome,
            "trace": self.trace,
            "observation": self.observation,
            "contract_hash": self.contract_hash,
        }


def _contract_hash(case: Case) -> str:
    """Fingerprint the contract actually used by both adapter and validators."""
    contract = {"id": case.id, "category": case.category, "severity": case.severity,
                "status": case.status, "required_features": case.required_features,
                "input": case.input, "expected": case.expected, "acceptance": case.acceptance}
    canonical = json.dumps(contract, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def execute_case(case: Case, target: Target) -> CaseResult:
    """Execute supported contracts only when the selected adapter supports them."""
    kind = getattr(target, "execution_kind", "unknown")
    if kind not in EXECUTION_KINDS:
        kind = "unknown"
    contract_hash = _contract_hash(case)
    start = time.perf_counter()

    def unsupported(reason: str, trace: list[dict] | None = None) -> CaseResult:
        return CaseResult(
            case_id=case.id, category=case.category, severity=case.severity,
            status="unsupported", passed=None, duration_ms=0.0,
            reason=reason, execution_kind=kind, outcome="unsupported", trace=trace or [],
            contract_hash=contract_hash,
        )

    def execution_error(reason: str, trace: list[dict] | None = None) -> CaseResult:
        failed_checks = [{"check": "target_execution", "ok": False, "detail": reason}]
        failed_checks.extend({"check": criterion.get("check", "acceptance_valid"), "ok": False,
                              "detail": "contrôle non exécuté : erreur de cible"}
                             for criterion in case.acceptance if isinstance(criterion, dict))
        return CaseResult(
            case_id=case.id, category=case.category, severity=case.severity,
            status="executed", passed=False,
            duration_ms=(time.perf_counter() - start) * 1000,
            reason=reason, checks=failed_checks, execution_kind=kind,
            outcome="execution_error", trace=trace or [],
            contract_hash=contract_hash,
        )

    if case.status != "supported":
        return unsupported(f"fonctionnalité non prise en charge (status={case.status}) : "
                           f"{', '.join(case.required_features)}")
    if kind == "real":
        features = getattr(target, "supported_features", None)
        if not isinstance(features, (set, frozenset)) or any(not isinstance(f, str) for f in features):
            return unsupported("la cible réelle ne déclare pas ses capacités")
        missing = sorted(set(case.required_features) - features)
        if missing:
            return unsupported(f"capacités absentes de la cible : {', '.join(missing)}")
        supports_case = getattr(target, "supports_case", None)
        if not callable(supports_case):
            return unsupported("la cible réelle ne déclare pas de handler pour ce cas")
        try:
            support = supports_case(case)
        except Exception as exc:
            return execution_error(f"contrôle de capacité en erreur : {type(exc).__name__}")
        if isinstance(support, tuple) and len(support) == 2:
            supported, reason = support
        else:
            supported, reason = support, "cas sans handler dans cette cible"
        if supported is not True:
            return unsupported(reason if isinstance(reason, str) else "cas sans handler dans cette cible")
    try:
        result = target.run(case)
    except Exception as exc:
        return execution_error(f"la cible a levé une exception : {type(exc).__name__}")
    trace: list[dict[str, Any]] = []
    if isinstance(result, TargetResult):
        if not isinstance(result.trace, list) or any(not isinstance(t, dict) for t in result.trace):
            return execution_error("trace de cible mal formée")
        try:
            json.dumps(result.trace, allow_nan=False)
        except (TypeError, ValueError, OverflowError):
            return execution_error("trace de cible non sérialisable")
        trace = result.trace
        if result.status == "unsupported":
            return unsupported(result.reason or "cas non pris en charge par la cible", trace)
        if result.status == "execution_error":
            return execution_error(result.reason or "erreur d'exécution signalée par la cible", trace)
        if result.status not in {"real", "simulated"} or result.status != kind:
            return execution_error("provenance incohérente entre la cible et son résultat", trace)
        observation = result.observation
    else:
        observation = result
    problem = _observation_error(observation)
    if problem:
        return execution_error(problem, trace)
    duration = (time.perf_counter() - start) * 1000
    checks = run_checks({**case.raw, "input": case.input, "expected": case.expected,
                         "acceptance": case.acceptance}, observation)
    if observation["error"] and not any(c.get("check") == "error_signaled" for c in case.acceptance):
        checks.append({"check": "target_no_error", "ok": False,
                       "detail": "la cible a signalé une erreur sur un cas censé réussir"})
    passed = all(c["ok"] for c in checks)
    return CaseResult(
        case_id=case.id, category=case.category, severity=case.severity,
        status="executed", passed=passed, duration_ms=duration, checks=checks,
        execution_kind=kind, outcome=kind if passed else "incorrect",
        trace=trace, observation=observation,
        contract_hash=contract_hash,
    )


def _observation_error(observation: Any) -> str | None:
    if not isinstance(observation, dict):
        return "l'observation doit être un objet"
    required = {"answer", "structured", "citations", "facts", "tools_called", "usage", "error"}
    if required - observation.keys():
        return "observation incomplète : " + ", ".join(sorted(required - observation.keys()))
    for key in ("answer", "error"):
        if observation[key] is not None and not isinstance(observation[key], str):
            return f"bloc {key} de type invalide"
    if observation["error"] is not None and not observation["error"].strip():
        return "bloc error vide"
    for key in ("structured", "usage"):
        if observation[key] is not None and not isinstance(observation[key], dict):
            return f"bloc {key} de type invalide"
    for key in ("facts", "tools_called"):
        if not isinstance(observation[key], list) or any(not isinstance(v, str) for v in observation[key]):
            return f"bloc {key} de type invalide"
    for key in ("citations", "plan"):
        value = observation.get(key, [])
        if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
            return f"bloc {key} de type invalide"
    try:
        json.dumps(observation, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return "observation non sérialisable ou nombre non fini"
    return None


# ------------------------------------------------------------------- métriques

def _check_metric(results: list[CaseResult], families: tuple[str, ...]) -> dict[str, Any]:
    total = passed = 0
    for result in results:
        for chk in result.checks:
            if chk["check"] in families:
                total += 1
                if chk["ok"]:
                    passed += 1
    return {
        "checks_total": total,
        "checks_passed": passed,
        "rate": round(passed / total, 4) if total else None,
        "measured": True,
    }


def compute_metrics(results: list[CaseResult], suite_summary: dict[str, Any]) -> dict[str, Any]:
    executed = [r for r in results if r.status == "executed"]
    unsupported = [r for r in results if r.status == "unsupported"]
    passed = [r for r in executed if r.passed]
    failed = [r for r in executed if r.passed is False]
    critical_failures = [r for r in failed if r.severity == "critical"]
    return {
        "cases_total": len(results),
        "cases_executed": len(executed),
        "cases_passed": len(passed),
        "cases_failed": len(failed),
        "cases_unsupported": len(unsupported),
        "cases_real": sum(r.execution_kind == "real" for r in executed),
        "cases_simulated": sum(r.execution_kind == "simulated" for r in executed),
        "cases_execution_error": sum(r.outcome == "execution_error" for r in executed),
        "real_pass_rate": (
            round(sum(r.passed is True for r in executed if r.execution_kind == "real") /
                  sum(r.execution_kind == "real" for r in executed), 4)
            if any(r.execution_kind == "real" for r in executed) else None
        ),
        "unsupported_ids": sorted(r.case_id for r in unsupported),
        "pass_rate_executable": (
            round(len(passed) / len(executed), 4) if executed else None
        ),
        "critical_failures": [
            {"case_id": r.case_id, "failed_checks": [c["check"] for c in r.checks if not c["ok"]]}
            for r in critical_failures
        ],
        "calculation_accuracy": _check_metric(executed, ("numeric_close",)),
        "structure_validity": _check_metric(executed, ("structure_valid", "plan_valid")),
        "source_traceability": _check_metric(executed, ("citations_valid",)),
        "hallucination_guard": _check_metric(executed, ("no_hallucinated_facts", "facts_present")),
        "suite": suite_summary,
    }


# ------------------------------------------------------------------ run global

def run_suite(
    target: Target,
    cases: list[Case] | None = None,
    *,
    label: str = "",
    persist: bool = True,
    runs_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Exécute la suite complète et retourne (et optionnellement persiste) le run."""
    if cases is None:
        cases = load_cases()
    if not cases:
        raise ValueError("une exécution exige au moins un cas")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("identifiants de cas dupliqués dans l'exécution")
    start = time.perf_counter()
    results = [execute_case(case, target) for case in cases]
    suite_contracts = sorted([{"case_id": r.case_id, "contract_hash": r.contract_hash}
                             for r in results], key=lambda r: r["case_id"])
    suite_hash = hashlib.sha256(json.dumps(suite_contracts, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
    total_seconds = time.perf_counter() - start
    peak_rss_native = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_kb = peak_rss_native / 1024 if sys.platform == "darwin" else peak_rss_native
    kind = getattr(target, "execution_kind", "unknown")
    if kind not in EXECUTION_KINDS:
        kind = "unknown"
    usages = [r.observation.get("usage") if r.observation else None
              for r in results if r.status == "executed"]
    declared_usage: dict[str, Any] = {}
    for key in ("api_calls", "tokens", "cost_usd"):
        values = [u.get(key) if isinstance(u, dict) else None for u in usages]
        valid = all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in values)
        declared_usage[key] = sum(values) if values and valid else None
    run = {
        "schema": "come-evals-run/1",
        "run_id": uuid.uuid4().hex[:12],
        "suite_hash": suite_hash,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label,
        "target": target.name,
        "execution_kind": kind,
        "quality_measurement": kind == "real" and any(r.status == "executed" for r in results),
        "measured_not_estimated": True,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "resources": {
            "total_seconds": round(total_seconds, 4),
            "peak_rss_kb": peak_rss_kb,
            "note": "durée du run et mémoire pic du processus mesurées localement ; consommation déclarée par la cible, non mesurée par le runner.",
            "declared_usage": declared_usage,
        },
        "metrics": compute_metrics(results, summarize_suite(cases)),
        "results": [r.to_dict() for r in results],
    }
    if persist:
        directory = Path(runs_dir) if runs_dir else RUNS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{run['run_id']}.json"
        path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        run["_path"] = str(path)
    return run


# ------------------------------------------------------------------ comparaison

def compare_runs(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Détecte régressions et améliorations entre deux runs."""
    baseline_kind = baseline.get("execution_kind", "unknown")
    candidate_kind = candidate.get("execution_kind", "unknown")
    if baseline_kind not in {"real", "simulated"} or candidate_kind != baseline_kind:
        raise ValueError("comparaison refusée : provenances réelle/simulée différentes ou inconnues")
    for run in (baseline, candidate):
        if not isinstance(run.get("suite_hash"), str) or not run["suite_hash"]:
            raise ValueError("comparaison refusée : empreinte de suite absente")
        ids = [r["case_id"] for r in run["results"]]
        if len(ids) != len(set(ids)):
            raise ValueError("comparaison refusée : identifiants de cas dupliqués")
        if any(r.get("execution_kind", run["execution_kind"]) != run["execution_kind"] for r in run["results"]):
            raise ValueError("comparaison refusée : provenance mixte dans un run")
    base = {r["case_id"]: r for r in baseline["results"]}
    cand = {r["case_id"]: r for r in candidate["results"]}
    for case_id in sorted(set(base) & set(cand)):
        b_hash, c_hash = base[case_id].get("contract_hash"), cand[case_id].get("contract_hash")
        if not b_hash or not c_hash or b_hash != c_hash:
            raise ValueError(f"comparaison refusée : contrat modifié ou sans empreinte pour {case_id}")
    regressions, improvements, changed_unsupported, coverage_losses = [], [], [], []
    for case_id in sorted(set(base) & set(cand)):
        b, c = base[case_id], cand[case_id]
        if b["status"] == "executed" and c["status"] == "executed":
            if b["passed"] and not c["passed"]:
                failed_checks = [x["check"] for x in c["checks"] if not x["ok"]]
                regressions.append({"case_id": case_id, "failed_checks": failed_checks})
            elif not b["passed"] and c["passed"]:
                improvements.append(case_id)
        elif b["status"] == "unsupported" and c["status"] == "executed":
            changed_unsupported.append({"case_id": case_id, "change": "unsupported -> executed"})
        elif b["status"] == "executed" and c["status"] == "unsupported":
            changed_unsupported.append({"case_id": case_id, "change": "executed -> unsupported"})
            coverage_losses.append(case_id)
    coverage_losses.extend(r["case_id"] for r in baseline["results"]
                           if r["case_id"] not in cand and r["status"] == "executed")
    return {
        "schema": "come-evals-compare/1",
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "baseline_target": baseline["target"],
        "candidate_target": candidate["target"],
        "execution_kind": baseline_kind,
        "baseline_suite_hash": baseline["suite_hash"],
        "candidate_suite_hash": candidate["suite_hash"],
        "regressions": regressions,
        "improvements": improvements,
        "status_changes": changed_unsupported,
        "new_cases": sorted(set(cand) - set(base)),
        "removed_cases": sorted(set(base) - set(cand)),
        "has_regressions": bool(regressions),
        "coverage_losses": sorted(coverage_losses),
        "has_coverage_loss": bool(coverage_losses),
    }
