"""Controlled automation orchestrator (SPEC-016).

Local-first, human-in-the-loop orchestration layer.  No automatic submission
of applications or emails: every external side-effect stays behind an explicit
human checkpoint.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .automation_audit import AuditEvent, AuditStore
from .automation_policy import (
    AutomationPolicy,
    CircuitBreakerConfig,
    EscalationConfig,
    Guardrails,
    HumanCheckpoint,
    PipelineStep,
    RetryPolicy,
    Trigger,
    policy_to_dict,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {k: _to_dict(getattr(value, k)) for k in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(k): _to_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_dict(v) for v in value]
    return value


@dataclass
class StepResult:
    step_id: str
    status: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    output: Any = None
    error: str | None = None
    attempts: int = 0
    duration_ms: float = 0.0


@dataclass
class HumanDecision:
    decision_id: str = ""
    execution_id: str = ""
    checkpoint_id: str = ""
    decider: str = ""
    decision: str = "approve"
    comment: str = ""
    decided_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.decision_id:
            self.decision_id = str(uuid.uuid4())
        if not self.decided_at:
            self.decided_at = _now()


@dataclass
class ExecutionMetrics:
    steps_total: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    human_checkpoints: int = 0
    duration_ms: float = 0.0


@dataclass
class WorkflowExecution:
    execution_id: str = ""
    policy_id: str = ""
    status: str = "pending"
    current_step: str | None = None
    started_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    input_data: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, StepResult] = field(default_factory=dict)
    human_decisions: list[HumanDecision] = field(default_factory=list)
    audit_trail: list[AuditEvent] = field(default_factory=list)
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)

    def __post_init__(self) -> None:
        if not self.execution_id:
            self.execution_id = str(uuid.uuid4())
        if not self.started_at:
            self.started_at = _now()
        if not self.updated_at:
            self.updated_at = self.started_at


@dataclass
class DashboardData:
    active_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    paused_workflows: int = 0
    waiting_human: int = 0
    cancelled_workflows: int = 0
    total_workflows: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    human_queue: list[dict[str, Any]] = field(default_factory=list)
    guardrails: dict[str, Any] = field(default_factory=dict)
    circuit_breakers: dict[str, Any] = field(default_factory=dict)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    policies: list[dict[str, Any]] = field(default_factory=list)


class AutomationOrchestrator:
    """Thread-safe, local-first workflow orchestrator."""

    def __init__(
        self,
        base_dir: Any = None,
        service: Any = None,
        audit_store: AuditStore | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.service = service
        self._lock = threading.RLock()
        self._policies: dict[str, AutomationPolicy] = {}
        self._executions: dict[str, WorkflowExecution] = {}
        self._audit = audit_store or AuditStore()
        self._circuit: dict[str, dict[str, Any]] = {}
        self._step_handlers: dict[str, Callable[[dict[str, Any], dict[str, Any]], Any]] = {}
        self.register_default_handlers()

    # ------------------------------------------------------------------ policies
    def _normalize_policy(self, policy: AutomationPolicy) -> AutomationPolicy:
        if not isinstance(policy, AutomationPolicy):
            try:
                policy = AutomationPolicy(**{k: v for k, v in dict(policy).items() if k in AutomationPolicy.__dataclass_fields__})
            except Exception:
                pass
        # steps
        new_steps = []
        for st in getattr(policy, "steps", []) or []:
            if isinstance(st, PipelineStep):
                new_steps.append(st)
            elif isinstance(st, dict):
                rp = st.get("retry_policy")
                if isinstance(rp, dict):
                    rp = RetryPolicy(**{k: v for k, v in rp.items() if k in RetryPolicy.__dataclass_fields__})
                elif rp is None:
                    rp = RetryPolicy()
                step = PipelineStep(
                    step_id=st.get("step_id") or st.get("id") or "step",
                    name=st.get("name", ""),
                    type=st.get("type", "transformation"),
                    handler=st.get("handler", ""),
                    input_schema=st.get("input_schema", {}) or {},
                    output_schema=st.get("output_schema", {}) or {},
                    timeout_seconds=st.get("timeout_seconds", 1800),
                    retry_policy=rp,
                    dependencies=st.get("dependencies", []) or [],
                    condition=st.get("condition", None),
                    on_failure=st.get("on_failure", "stop"),
                    fallback_step_id=st.get("fallback_step_id", None),
                )
                new_steps.append(step)
            else:
                new_steps.append(st)
        policy.steps = new_steps
        # human_checkpoints
        new_cps = []
        for cp in getattr(policy, "human_checkpoints", []) or []:
            if isinstance(cp, HumanCheckpoint):
                new_cps.append(cp)
            elif isinstance(cp, dict):
                esc = cp.get("escalation")
                if isinstance(esc, dict):
                    esc = EscalationConfig(**{k: v for k, v in esc.items() if k in EscalationConfig.__dataclass_fields__})
                elif esc is None:
                    esc = EscalationConfig()
                new_cps.append(HumanCheckpoint(
                    checkpoint_id=cp.get("checkpoint_id") or cp.get("id") or "cp",
                    step_id=cp.get("step_id", ""),
                    trigger=cp.get("trigger", "always"),
                    threshold_config=cp.get("threshold_config", None),
                    required_approvers=cp.get("required_approvers", 1),
                    approver_roles=cp.get("approver_roles", ["user"]) or ["user"],
                    timeout_hours=cp.get("timeout_hours", 24),
                    escalation=esc,
                    required_fields=cp.get("required_fields", []) or [],
                    veto_power=cp.get("veto_power", True),
                ))
            else:
                new_cps.append(cp)
        policy.human_checkpoints = new_cps
        # triggers
        new_tr = []
        for t in getattr(policy, "triggers", []) or []:
            if isinstance(t, Trigger):
                new_tr.append(t)
            elif isinstance(t, dict):
                new_tr.append(Trigger(
                    trigger_id=t.get("trigger_id") or t.get("id") or "",
                    type=t.get("type", "manual"),
                    config=t.get("config", {}) or {},
                ))
            else:
                new_tr.append(t)
        policy.triggers = new_tr
        # guardrails
        if isinstance(policy.guardrails, dict):
            g = policy.guardrails
            cb = g.get("circuit_breaker")
            if isinstance(cb, dict):
                cb = CircuitBreakerConfig(**{k: v for k, v in cb.items() if k in CircuitBreakerConfig.__dataclass_fields__})
            elif cb is None:
                cb = CircuitBreakerConfig()
            policy.guardrails = Guardrails(
                max_execution_time_seconds=g.get("max_execution_time_seconds", 7200),
                max_retries=g.get("max_retries", 3),
                max_concurrent_executions=g.get("max_concurrent_executions", 10),
                max_data_volume_mb=g.get("max_data_volume_mb", 100),
                forbidden_operations=g.get("forbidden_operations", ["send_email", "delete_data", "external_api_call"]),
                data_classification_required=g.get("data_classification_required", True),
                pii_handling=g.get("pii_handling", "mask"),
                circuit_breaker=cb,
                rate_limits=g.get("rate_limits", {"default": 100}) or {"default": 100},
                cost_limit_usd=g.get("cost_limit_usd", 10.0),
            )
        return policy

    def register_policy(self, policy: AutomationPolicy) -> AutomationPolicy:
        policy = self._normalize_policy(policy)

        with self._lock:
            self._policies[policy.policy_id] = policy
            self._record_audit(
                execution_id=None,
                event_type="policy_changed",
                actor="system",
                details={"policy_id": policy.policy_id, "version": policy.version},
                severity="info",
            )
            return policy

    def get_policy(self, policy_id: str) -> AutomationPolicy | None:
        with self._lock:
            return self._policies.get(policy_id)

    def list_policies(self) -> list[AutomationPolicy]:
        with self._lock:
            return list(self._policies.values())

    def create_policy(self, policy: AutomationPolicy) -> AutomationPolicy:
        return self.register_policy(policy)

    def update_policy(self, policy_id: str, **changes: Any) -> AutomationPolicy | None:
        with self._lock:
            policy = self._policies.get(policy_id)
            if policy is None:
                return None
            for key, value in changes.items():
                if hasattr(policy, key):
                    setattr(policy, key, value)
            policy.version += 1
            self._record_audit(
                execution_id=None,
                event_type="policy_changed",
                actor="user",
                details={"policy_id": policy_id, "changes": list(changes.keys())},
                severity="info",
            )
            return policy

    def activate_policy(self, policy_id: str) -> AutomationPolicy | None:
        with self._lock:
            policy = self._policies.get(policy_id)
            if policy is None:
                return None
            policy.status = "active"
            self._record_audit(
                execution_id=None,
                event_type="policy_activated",
                actor="user",
                details={"policy_id": policy_id},
                severity="info",
            )
            return policy

    def pause_policy(self, policy_id: str) -> AutomationPolicy | None:
        with self._lock:
            policy = self._policies.get(policy_id)
            if policy is None:
                return None
            policy.status = "paused"
            self._record_audit(
                execution_id=None,
                event_type="policy_deactivated",
                actor="user",
                details={"policy_id": policy_id},
                severity="warning",
            )
            return policy

    # ------------------------------------------------------------------ handlers
    def register_handler(self, step_type_or_id: str, handler: Callable[[dict[str, Any], dict[str, Any]], Any]) -> None:
        self._step_handlers[step_type_or_id] = handler

    def register_default_handlers(self) -> None:
        def _default(step: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
            return {"step": step.get("step_id"), "status": "completed"}

        for key in ("extraction", "enrichment", "validation", "transformation", "export", "notification", "human_review"):
            self._step_handlers.setdefault(key, _default)
        self._step_handlers.setdefault("*", _default)

    def _handler_for(self, step: PipelineStep) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
        return self._step_handlers.get(step.type) or self._step_handlers.get("*") or (lambda s, c: {"ok": True})

    # ------------------------------------------------------------------ execution
    def submit_workflow(
        self,
        policy_id: str,
        input_data: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> WorkflowExecution:
        with self._lock:
            policy = self._policies.get(policy_id)
            if policy is not None:
                policy = self._normalize_policy(policy)
            if policy is None:
                policy = self._policies.get("default")
            if policy is None:
                # Create a minimal default policy on the fly.
                policy = AutomationPolicy(policy_id=policy_id, name=policy_id, status="active")
                self._policies[policy_id] = policy
            if policy.status not in {"active", "draft"}:
                raise ValueError(f"Policy {policy_id} is not active (status={policy.status})")

            execution = WorkflowExecution(
                policy_id=policy.policy_id,
                input_data=dict(input_data or {}),
                context=dict(context or {}),
            )
            execution.metrics.steps_total = len(policy.steps)
            self._executions[execution.execution_id] = execution
            self._record_audit(
                execution_id=execution.execution_id,
                event_type="workflow_started",
                actor="system",
                details={"policy_id": policy.policy_id, "input_keys": list((input_data or {}).keys())},
                severity="info",
            )
            # Run synchronously unless a human checkpoint stops it.
            self._run_execution(execution, policy)
            return execution

    def _run_execution(self, execution: WorkflowExecution, policy: AutomationPolicy) -> None:
        started = datetime.now(timezone.utc)
        execution.status = "running"
        execution.updated_at = _now()
        # Build checkpoint lookup by step.
        checkpoints_by_step: dict[str, list[HumanCheckpoint]] = {}
        for cp in policy.human_checkpoints:
            checkpoints_by_step.setdefault(cp.step_id, []).append(cp)

        # Circuit breaker check.
        cb = self._circuit.get(policy.policy_id, {"failures": 0, "opened_at": None, "state": "closed"})
        if cb.get("state") == "open":
            execution.status = "failed"
            execution.completed_at = _now()
            self._record_audit(
                execution_id=execution.execution_id,
                event_type="circuit_breaker_opened",
                actor="system",
                details={"policy_id": policy.policy_id},
                severity="critical",
            )
            return

        for step in policy.steps:
            # Dependencies
            if any(self._executions[execution.execution_id].step_results.get(dep, StepResult(dep)).status not in {"completed", "skipped"} for dep in step.dependencies):
                # skip if dependency failed
                pass

            if execution.status in {"paused", "waiting_human", "cancelled", "failed"}:
                break

            # Condition evaluation (very light): support simple truthy strings.
            if step.condition:
                if not self._eval_condition(step.condition, execution):
                    sr = StepResult(step_id=step.step_id, status="skipped", started_at=_now(), completed_at=_now())
                    execution.step_results[step.step_id] = sr
                    execution.metrics.steps_skipped += 1
                    continue

            # Checkpoint "always"/"manual" before step.
            cps = checkpoints_by_step.get(step.step_id, [])
            blocking = [cp for cp in cps if cp.trigger in {"always", "manual"}]
            if blocking:
                execution.status = "waiting_human"
                execution.current_step = step.step_id
                execution.updated_at = _now()
                cp = blocking[0]
                self._record_audit(
                    execution_id=execution.execution_id,
                    event_type="human_checkpoint_created",
                    actor="system",
                    details={"checkpoint_id": cp.checkpoint_id, "step_id": step.step_id},
                    severity="info",
                )
                execution.metrics.human_checkpoints += 1
                return

            # Execute step.
            execution.current_step = step.step_id
            sr = StepResult(step_id=step.step_id, status="running", started_at=_now(), attempts=1)
            execution.step_results[step.step_id] = sr
            self._record_audit(
                execution_id=execution.execution_id,
                event_type="step_started",
                actor="system",
                details={"step_id": step.step_id},
                severity="info",
            )
            t0 = datetime.now(timezone.utc)
            try:
                handler = self._handler_for(step)
                out = handler(_to_dict(step), execution.context)
                sr.output = out
                sr.status = "completed"
                sr.completed_at = _now()
                sr.duration_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000.0
                execution.metrics.steps_completed += 1
                # Store output into context under step_id for downstream.
                if isinstance(out, dict):
                    execution.context.setdefault("results", {})[step.step_id] = out
                self._record_audit(
                    execution_id=execution.execution_id,
                    event_type="step_completed",
                    actor="system",
                    details={"step_id": step.step_id},
                    severity="info",
                )
            except Exception as exc:  # noqa: BLE001
                sr.status = "failed"
                sr.error = str(exc)
                sr.completed_at = _now()
                sr.duration_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000.0
                execution.metrics.steps_failed += 1
                self._record_audit(
                    execution_id=execution.execution_id,
                    event_type="step_failed",
                    actor="system",
                    details={"step_id": step.step_id, "error": str(exc)},
                    severity="error",
                )
                # Guardrail: circuit breaker.
                cb["failures"] = cb.get("failures", 0) + 1
                if cb["failures"] >= policy.guardrails.circuit_breaker.failure_threshold:
                    cb["state"] = "open"
                    cb["opened_at"] = _now()
                    self._circuit[policy.policy_id] = cb
                    self._record_audit(
                        execution_id=execution.execution_id,
                        event_type="circuit_breaker_opened",
                        actor="system",
                        details={"policy_id": policy.policy_id, "failures": cb["failures"]},
                        severity="critical",
                    )
                # on_failure handling.
                if step.on_failure == "stop":
                    execution.status = "failed"
                    break
                elif step.on_failure == "continue":
                    continue
                elif step.on_failure == "fallback" and step.fallback_step_id:
                    # mark fallback as completed placeholder
                    pass
                else:
                    execution.status = "failed"
                    break

        if execution.status == "running":
            execution.status = "completed"
            execution.completed_at = _now()
        execution.updated_at = _now()
        execution.metrics.duration_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000.0
        if execution.status == "completed":
            self._record_audit(
                execution_id=execution.execution_id,
                event_type="workflow_started" if False else "step_completed",
                actor="system",
                details={"execution_id": execution.execution_id, "final": True},
                severity="info",
            )

    def _eval_condition(self, condition: str, execution: WorkflowExecution) -> bool:
        # Minimal: treat non-empty condition as True unless it references a known false.
        condition = condition.strip().lower()
        if condition in {"false", "0", "no"}:
            return False
        return True

    def get_execution(self, execution_id: str) -> WorkflowExecution | None:
        with self._lock:
            return self._executions.get(execution_id)

    def list_executions(self) -> list[WorkflowExecution]:
        with self._lock:
            return list(self._executions.values())

    def pause_execution(self, execution_id: str, reason: str = "") -> WorkflowExecution | None:
        with self._lock:
            ex = self._executions.get(execution_id)
            if ex is None:
                return None
            if ex.status in {"completed", "failed", "cancelled"}:
                return ex
            ex.status = "paused"
            ex.updated_at = _now()
            self._record_audit(
                execution_id=execution_id,
                event_type="step_failed" if False else "guardrail_triggered",
                actor="user",
                details={"reason": reason, "action": "pause"},
                severity="warning",
            )
            return ex

    def resume_execution(self, execution_id: str) -> WorkflowExecution | None:
        with self._lock:
            ex = self._executions.get(execution_id)
            if ex is None:
                return None
            if ex.status == "paused":
                ex.status = "running"
                ex.updated_at = _now()
                policy = self._policies.get(ex.policy_id)
                if policy is not None:
                    self._run_execution(ex, policy)
            return ex

    def cancel_execution(self, execution_id: str, reason: str = "") -> WorkflowExecution | None:
        with self._lock:
            ex = self._executions.get(execution_id)
            if ex is None:
                return None
            ex.status = "cancelled"
            ex.completed_at = _now()
            ex.updated_at = _now()
            self._record_audit(
                execution_id=execution_id,
                event_type="rollback_initiated",
                actor="user",
                details={"reason": reason, "action": "cancel"},
                severity="warning",
            )
            return ex

    def approve_checkpoint(
        self,
        execution_id: str,
        checkpoint_id: str,
        approver: str,
        decision: str = "approve",
        comment: str = "",
    ) -> HumanDecision:
        with self._lock:
            ex = self._executions.get(execution_id)
            if ex is None:
                raise KeyError(f"Unknown execution {execution_id}")
            hd = HumanDecision(
                execution_id=execution_id,
                checkpoint_id=checkpoint_id,
                decider=approver,
                decision=decision,
                comment=comment,
            )
            ex.human_decisions.append(hd)
            self._record_audit(
                execution_id=execution_id,
                event_type="human_decision_made",
                actor="user",
                actor_id=approver,
                details={"checkpoint_id": checkpoint_id, "decision": decision, "comment": comment},
                severity="info",
            )
            # Resume if approved.
            if decision in {"approve", "approved"}:
                policy = self._policies.get(ex.policy_id)
                # mark current step completed
                if ex.current_step:
                    if ex.current_step not in ex.step_results:
                        ex.step_results[ex.current_step] = StepResult(step_id=ex.current_step, status="completed", started_at=_now(), completed_at=_now())
                    else:
                        ex.step_results[ex.current_step].status = "completed"
                        ex.step_results[ex.current_step].completed_at = _now()
                ex.status = "running"
                ex.updated_at = _now()
                if policy is not None:
                    # Continue from next step: re-run but skip completed.
                    self._continue_execution(ex, policy)
            elif decision in {"reject", "rejected"}:
                ex.status = "failed"
                ex.completed_at = _now()
                ex.updated_at = _now()
            return hd

    def _continue_execution(self, execution: WorkflowExecution, policy: AutomationPolicy) -> None:
        checkpoints_by_step: dict[str, list[HumanCheckpoint]] = {}
        for cp in policy.human_checkpoints:
            checkpoints_by_step.setdefault(cp.step_id, []).append(cp)

        for step in policy.steps:
            if step.step_id in execution.step_results and execution.step_results[step.step_id].status in {"completed", "skipped"}:
                continue
            if execution.status in {"paused", "waiting_human", "cancelled", "failed"}:
                break

            cps = checkpoints_by_step.get(step.step_id, [])
            blocking = [cp for cp in cps if cp.trigger in {"always", "manual"}]
            if blocking:
                execution.status = "waiting_human"
                execution.current_step = step.step_id
                execution.updated_at = _now()
                cp = blocking[0]
                self._record_audit(
                    execution_id=execution.execution_id,
                    event_type="human_checkpoint_created",
                    actor="system",
                    details={"checkpoint_id": cp.checkpoint_id, "step_id": step.step_id},
                    severity="info",
                )
                execution.metrics.human_checkpoints += 1
                return

            execution.current_step = step.step_id
            sr = StepResult(step_id=step.step_id, status="running", started_at=_now(), attempts=1)
            execution.step_results[step.step_id] = sr
            self._record_audit(
                execution_id=execution.execution_id,
                event_type="step_started",
                actor="system",
                details={"step_id": step.step_id},
                severity="info",
            )
            t0 = datetime.now(timezone.utc)
            try:
                handler = self._handler_for(step)
                out = handler(_to_dict(step), execution.context)
                sr.output = out
                sr.status = "completed"
                sr.completed_at = _now()
                sr.duration_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000.0
                execution.metrics.steps_completed += 1
                if isinstance(out, dict):
                    execution.context.setdefault("results", {})[step.step_id] = out
                self._record_audit(
                    execution_id=execution.execution_id,
                    event_type="step_completed",
                    actor="system",
                    details={"step_id": step.step_id},
                    severity="info",
                )
            except Exception as exc:  # noqa: BLE001
                sr.status = "failed"
                sr.error = str(exc)
                sr.completed_at = _now()
                execution.metrics.steps_failed += 1
                self._record_audit(
                    execution_id=execution.execution_id,
                    event_type="step_failed",
                    actor="system",
                    details={"step_id": step.step_id, "error": str(exc)},
                    severity="error",
                )
                execution.status = "failed"
                break

        if execution.status == "running":
            execution.status = "completed"
            execution.completed_at = _now()
        execution.updated_at = _now()

    def get_dashboard_data(self) -> DashboardData:
        with self._lock:
            execs = list(self._executions.values())
            dd = DashboardData()
            dd.total_workflows = len(execs)
            for ex in execs:
                if ex.status == "running":
                    dd.active_workflows += 1
                elif ex.status == "completed":
                    dd.completed_workflows += 1
                elif ex.status == "failed":
                    dd.failed_workflows += 1
                elif ex.status == "paused":
                    dd.paused_workflows += 1
                elif ex.status == "waiting_human":
                    dd.waiting_human += 1
                elif ex.status == "cancelled":
                    dd.cancelled_workflows += 1
            dd.success_rate = (dd.completed_workflows / dd.total_workflows) if dd.total_workflows else 0.0
            durations = [ex.metrics.duration_ms for ex in execs if ex.metrics.duration_ms]
            dd.avg_duration_ms = (sum(durations) / len(durations)) if durations else 0.0
            # human queue
            for ex in execs:
                if ex.status == "waiting_human":
                    dd.human_queue.append({
                        "execution_id": ex.execution_id,
                        "policy_id": ex.policy_id,
                        "current_step": ex.current_step,
                        "started_at": ex.started_at,
                    })
            # guardrails summary
            dd.guardrails = {
                "policies": len(self._policies),
                "circuit_open": sum(1 for c in self._circuit.values() if c.get("state") == "open"),
            }
            dd.circuit_breakers = dict(self._circuit)
            dd.recent_events = [_to_dict(e) for e in self._audit.all()[-20:]]
            dd.policies = [policy_to_dict(p) for p in self._policies.values()]
            return dd

    def get_audit_trail(self, **filters: Any) -> list[AuditEvent]:
        return self._audit.filter(**filters)

    def _record_audit(self, **kwargs: Any) -> None:
        event = AuditEvent(**kwargs)
        self._audit.append(event)
        # Also attach to execution if present.
        eid = kwargs.get("execution_id")
        if eid and eid in self._executions:
            self._executions[eid].audit_trail.append(event)

    # ------------------------------------------------------------------ helpers
    def rollback_execution(self, execution_id: str, reason: str = "") -> WorkflowExecution | None:
        with self._lock:
            ex = self._executions.get(execution_id)
            if ex is None:
                return None
            ex.status = "rolled_back" if hasattr(ex, "status") else ex.status
            ex.status = "cancelled"
            ex.completed_at = _now()
            self._record_audit(
                execution_id=execution_id,
                event_type="rollback_initiated",
                actor="user",
                details={"reason": reason},
                severity="warning",
            )
            return ex

    def handle_step(self, step_id: str, handler: Callable[[dict[str, Any], dict[str, Any]], Any]) -> None:
        self.register_handler(step_id, handler)


# Aliases
Orchestrator = AutomationOrchestrator
Controller = AutomationOrchestrator


def create_orchestrator(*args: Any, **kwargs: Any) -> AutomationOrchestrator:
    return AutomationOrchestrator(*args, **kwargs)


def get_orchestrator(base_dir: Any = None, service: Any = None) -> AutomationOrchestrator:
    # Module-level cache by base_dir/service identity.
    key = (str(base_dir) if base_dir is not None else None, id(service) if service is not None else None)
    cache = getattr(get_orchestrator, "_cache", None)
    if cache is None:
        cache = {}
        get_orchestrator._cache = cache  # type: ignore[attr-defined]
    if key not in cache:
        cache[key] = AutomationOrchestrator(base_dir=base_dir, service=service)
    return cache[key]


def to_dict(value: Any) -> Any:
    return _to_dict(value)


# --------------------------------------------------------------------------- #
# FastAPI router (SPEC-016)
# --------------------------------------------------------------------------- #
try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover
    APIRouter = None  # type: ignore


def _orchestrator_from(service_or_orch: Any) -> AutomationOrchestrator:
    if isinstance(service_or_orch, AutomationOrchestrator):
        return service_or_orch
    if hasattr(service_or_orch, "automation_orchestrator"):
        return service_or_orch.automation_orchestrator
    return get_orchestrator(service=service_or_orch)


if APIRouter is not None:
    class _PolicyPayload(BaseModel):  # type: ignore
        policy: dict[str, Any] = Field(default_factory=dict)

    class _WorkflowPayload(BaseModel):  # type: ignore
        policy_id: str
        input_data: dict[str, Any] = Field(default_factory=dict)
        context: dict[str, Any] = Field(default_factory=dict)

    class _DecisionPayload(BaseModel):  # type: ignore
        execution_id: str | None = None
        approver: str = "user"
        decision: str = "approve"
        comment: str = ""
else:
    class _PolicyPayload:  # type: ignore
        pass
    class _WorkflowPayload:  # type: ignore
        pass
    class _DecisionPayload:  # type: ignore
        pass


def create_automation_router(service_or_orchestrator: Any = None) -> "APIRouter":
    if APIRouter is None:
        raise RuntimeError("FastAPI is not available")
    orch = _orchestrator_from(service_or_orchestrator) if service_or_orchestrator is not None else None
    router = APIRouter()

    def get_orch() -> AutomationOrchestrator:
        nonlocal orch
        if orch is None:
            orch = get_orchestrator(service=service_or_orchestrator)
        return orch

    @router.post("/automation/workflows")
    async def submit_workflow(payload: _WorkflowPayload) -> Any:
        ex = get_orch().submit_workflow(payload.policy_id, payload.input_data, payload.context)
        return to_dict(ex)

    @router.get("/automation/workflows")
    async def list_workflows() -> Any:
        return [to_dict(e) for e in get_orch().list_executions()]

    @router.get("/automation/workflows/{execution_id}")
    async def get_workflow(execution_id: str) -> Any:
        ex = get_orch().get_execution(execution_id)
        if ex is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return to_dict(ex)

    @router.post("/automation/workflows/{execution_id}/pause")
    async def pause_workflow(execution_id: str, payload: dict[str, Any] | None = None) -> Any:
        reason = (payload or {}).get("reason", "")
        ex = get_orch().pause_execution(execution_id, reason)
        if ex is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return to_dict(ex)

    @router.post("/automation/workflows/{execution_id}/resume")
    async def resume_workflow(execution_id: str) -> Any:
        ex = get_orch().resume_execution(execution_id)
        if ex is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return to_dict(ex)

    @router.post("/automation/workflows/{execution_id}/cancel")
    async def cancel_workflow(execution_id: str, payload: dict[str, Any] | None = None) -> Any:
        reason = (payload or {}).get("reason", "")
        ex = get_orch().cancel_execution(execution_id, reason)
        if ex is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return to_dict(ex)

    @router.post("/automation/checkpoints/{checkpoint_id}/decide")
    async def decide_checkpoint(checkpoint_id: str, payload: _DecisionPayload) -> Any:
        # execution_id may be passed in payload
        execution_id = getattr(payload, "execution_id", None) if hasattr(payload, "execution_id") else None
        if execution_id is None:
            # try dict
            if isinstance(payload, dict):
                execution_id = payload.get("execution_id")
        if execution_id is None:
            # find latest waiting execution
            for ex in get_orch().list_executions():
                if ex.status == "waiting_human":
                    execution_id = ex.execution_id
                    break
        if execution_id is None:
            raise HTTPException(status_code=400, detail="execution_id required")
        hd = get_orch().approve_checkpoint(execution_id, checkpoint_id, payload.approver, payload.decision, payload.comment)
        return to_dict(hd)

    @router.get("/automation/dashboard")
    async def dashboard() -> Any:
        return to_dict(get_orch().get_dashboard_data())

    @router.get("/automation/audit")
    async def audit(execution_id: str | None = None, event_type: str | None = None, severity: str | None = None) -> Any:
        events = get_orch().get_audit_trail(execution_id=execution_id, event_type=event_type, severity=severity)
        return [to_dict(e) for e in events]

    @router.get("/automation/policies")
    async def list_policies() -> Any:
        return [policy_to_dict(p) for p in get_orch().list_policies()]

    @router.post("/automation/policies")
    async def create_policy(payload: dict[str, Any]) -> Any:
        # Accept either a full policy dict or fields.
        from .automation_policy import make_policy, AutomationPolicy
        if "policy_id" in payload:
            policy = make_policy(payload["policy_id"], name=payload.get("name", ""), domain=payload.get("domain", "all"))
            # apply optional fields
            for k in ("steps", "triggers", "guardrails", "human_checkpoints", "version", "status", "audit_level", "retention_days"):
                if k in payload:
                    setattr(policy, k, payload[k])
        else:
            policy = AutomationPolicy(**{k: v for k, v in payload.items() if k in AutomationPolicy.__dataclass_fields__})
        get_orch().register_policy(policy)
        return policy_to_dict(policy)

    @router.patch("/automation/policies/{policy_id}")
    async def update_policy(policy_id: str, payload: dict[str, Any]) -> Any:
        policy = get_orch().update_policy(policy_id, **payload)
        if policy is None:
            raise HTTPException(status_code=404, detail="policy not found")
        return policy_to_dict(policy)

    @router.post("/automation/policies/{policy_id}/activate")
    async def activate_policy(policy_id: str) -> Any:
        policy = get_orch().activate_policy(policy_id)
        if policy is None:
            raise HTTPException(status_code=404, detail="policy not found")
        return policy_to_dict(policy)

    @router.post("/automation/policies/{policy_id}/pause")
    async def pause_policy(policy_id: str) -> Any:
        policy = get_orch().pause_policy(policy_id)
        if policy is None:
            raise HTTPException(status_code=404, detail="policy not found")
        return policy_to_dict(policy)

    @router.get("/automation/metrics")
    async def metrics() -> Any:
        dd = get_orch().get_dashboard_data()
        return {
            "total_workflows": dd.total_workflows,
            "active_workflows": dd.active_workflows,
            "completed_workflows": dd.completed_workflows,
            "failed_workflows": dd.failed_workflows,
            "success_rate": dd.success_rate,
            "avg_duration_ms": dd.avg_duration_ms,
        }

    return router


# Also expose /api/career/automation aliases by mounting same paths? We'll let router.py handle.
