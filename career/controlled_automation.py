"""Controlled automation orchestration layer (SPEC-016).

Coordinates existing automatismes (pipelines, workflows, scheduled tasks) with
human validation points, guardrails (thresholds, timeouts, circuit breakers),
rollback and a unified audit trail.  Deterministic, local, no network.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable


class AutomationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_VALIDATION = "awaiting_validation"
    DONE = "done"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class AutomationPolicy:
    name: str
    threshold: float = 0.5          # min confidence to auto-approve
    timeout_sec: float = 300.0     # max duration
    require_human_validation: bool = True
    max_retries: int = 3
    circuit_breaker_threshold: int = 5  # consecutive failures before opening


@dataclass
class AutomationStep:
    name: str
    action: Callable[[], Any] | None = None
    status: AutomationStatus = AutomationStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: float | None = None
    ended_at: float | None = None


@dataclass
class AutomationRun:
    run_id: str
    policy: AutomationPolicy
    steps: list[AutomationStep] = field(default_factory=list)
    status: AutomationStatus = AutomationStatus.PENDING
    audit: list[dict[str, Any]] = field(default_factory=list)
    _consecutive_failures: int = 0


class ControlledAutomation:
    """Orchestrator with human validation points, guardrails, audit trail."""

    def __init__(self) -> None:
        self._runs: dict[str, AutomationRun] = {}
        self._counter = 0

    def create_run(self, policy: AutomationPolicy, steps: Iterable[str] | None = None) -> AutomationRun:
        self._counter += 1
        run = AutomationRun(run_id=f"run_{self._counter}", policy=policy)
        for s in (steps or []):
            run.steps.append(AutomationStep(name=s))
        self._runs[run.run_id] = run
        self._audit(run, "created", {"steps": [s.name for s in run.steps]})
        return run

    def get_run(self, run_id: str) -> AutomationRun | None:
        return self._runs.get(run_id)

    def run_step(self, run_id: str, step_name: str) -> AutomationStep:
        run = self._runs[run_id]
        step = next((s for s in run.steps if s.name == step_name), None)
        if step is None:
            raise KeyError(f"step {step_name} not found")
        if run.status == AutomationStatus.CIRCUIT_OPEN:
            step.status = AutomationStatus.CIRCUIT_OPEN
            self._audit(run, "step_skipped_circuit_open", {"step": step_name})
            return step
        step.status = AutomationStatus.RUNNING
        step.started_at = time.time()
        self._audit(run, "step_started", {"step": step_name})
        try:
            if step.action is not None:
                step.result = step.action()
            step.status = AutomationStatus.DONE
            run._consecutive_failures = 0
            self._audit(run, "step_done", {"step": step_name, "result": step.result})
        except Exception as exc:
            step.status = AutomationStatus.FAILED
            step.error = str(exc)
            run._consecutive_failures += 1
            self._audit(run, "step_failed", {"step": step_name, "error": str(exc)})
            if run._consecutive_failures >= run.policy.circuit_breaker_threshold:
                run.status = AutomationStatus.CIRCUIT_OPEN
                self._audit(run, "circuit_opened", {"failures": run._consecutive_failures})
        step.ended_at = time.time()
        if step.ended_at - (step.started_at or step.ended_at) > run.policy.timeout_sec:
            step.status = AutomationStatus.FAILED
            step.error = "timeout"
            self._audit(run, "step_timeout", {"step": step_name})
        return step

    def request_validation(self, run_id: str, step_name: str) -> None:
        run = self._runs[run_id]
        step = next((s for s in run.steps if s.name == step_name), None)
        if step is None:
            raise KeyError(f"step {step_name} not found")
        if run.policy.require_human_validation:
            step.status = AutomationStatus.AWAITING_VALIDATION
            run.status = AutomationStatus.AWAITING_VALIDATION
            self._audit(run, "validation_requested", {"step": step_name})

    def validate(self, run_id: str, step_name: str, approved: bool) -> None:
        run = self._runs[run_id]
        step = next((s for s in run.steps if s.name == step_name), None)
        if step is None:
            raise KeyError(f"step {step_name} not found")
        if approved:
            step.status = AutomationStatus.DONE
            self._audit(run, "validated", {"step": step_name, "approved": True})
        else:
            step.status = AutomationStatus.ROLLED_BACK
            self._audit(run, "rejected", {"step": step_name, "approved": False})
        self._update_run_status(run)

    def _update_run_status(self, run: AutomationRun) -> None:
        statuses = {s.status for s in run.steps}
        if AutomationStatus.FAILED in statuses:
            run.status = AutomationStatus.FAILED
        elif AutomationStatus.AWAITING_VALIDATION in statuses:
            run.status = AutomationStatus.AWAITING_VALIDATION
        elif all(s.status in (AutomationStatus.DONE, AutomationStatus.ROLLED_BACK) for s in run.steps):
            run.status = AutomationStatus.DONE
        else:
            run.status = AutomationStatus.RUNNING

    def _audit(self, run: AutomationRun, event: str, payload: dict[str, Any]) -> None:
        run.audit.append({"at": time.time(), "event": event, "payload": payload})

    def rollback(self, run_id: str) -> None:
        run = self._runs[run_id]
        for s in run.steps:
            s.status = AutomationStatus.ROLLED_BACK
        run.status = AutomationStatus.ROLLED_BACK
        self._audit(run, "rolled_back", {})

    def dashboard(self) -> dict[str, Any]:
        return {
            "runs": len(self._runs),
            "statuses": {r.run_id: r.status.value for r in self._runs.values()},
        }

    def to_dict(self, run_id: str) -> dict[str, Any]:
        run = self._runs[run_id]
        return {
            "run_id": run.run_id,
            "status": run.status.value,
            "policy": asdict(run.policy),
            "steps": [asdict(s) for s in run.steps],
            "audit": run.audit,
        }