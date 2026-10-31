"""Policies, guardrails and step definitions for controlled automation (SPEC-016)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PolicyStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    DEPRECATED = "deprecated"


class StepType(str, Enum):
    EXTRACTION = "extraction"
    ENRICHMENT = "enrichment"
    VALIDATION = "validation"
    TRANSFORMATION = "transformation"
    EXPORT = "export"
    NOTIFICATION = "notification"
    HUMAN_REVIEW = "human_review"


class TriggerType(str, Enum):
    SCHEDULE = "schedule"
    EVENT = "event"
    MANUAL = "manual"
    WEBHOOK = "webhook"


class OnFailure(str, Enum):
    STOP = "stop"
    CONTINUE = "continue"
    RETRY = "retry"
    FALLBACK = "fallback"
    ALERT = "alert"


class PiiHandling(str, Enum):
    STRIP = "strip"
    MASK = "mask"
    ENCRYPT = "encrypt"
    BLOCK = "block"


class CheckpointTrigger(str, Enum):
    ALWAYS = "always"
    ON_FAILURE = "on_failure"
    ON_WARNING = "on_warning"
    ON_THRESHOLD = "on_threshold"
    MANUAL = "manual"


class HumanDecisionValue(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    DEFER = "defer"


@dataclass
class Trigger:
    trigger_id: str = ""
    type: str = "manual"
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trigger_id:
            self.trigger_id = f"trigger-{self.type or 'manual'}"


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    exponential: bool = True


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    window_seconds: int = 60
    open_seconds: int = 300
    state: str = "closed"


@dataclass
class EscalationConfig:
    enabled: bool = False
    after_hours: int = 2
    to_roles: list[str] = field(default_factory=list)


@dataclass
class Guardrails:
    max_execution_time_seconds: int = 7200
    max_retries: int = 3
    max_concurrent_executions: int = 10
    max_data_volume_mb: int = 100
    forbidden_operations: list[str] = field(default_factory=lambda: ["send_email", "delete_data", "external_api_call"])
    data_classification_required: bool = True
    pii_handling: str = "mask"
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    rate_limits: dict[str, int] = field(default_factory=lambda: {"default": 100})
    cost_limit_usd: float | None = 10.0


@dataclass
class PipelineStep:
    step_id: str
    name: str = ""
    type: str = "transformation"
    handler: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 1800
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    dependencies: list[str] = field(default_factory=list)
    condition: str | None = None
    on_failure: str = "stop"
    fallback_step_id: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.step_id


@dataclass
class HumanCheckpoint:
    checkpoint_id: str
    step_id: str = ""
    trigger: str = "always"
    threshold_config: dict[str, Any] | None = None
    required_approvers: int = 1
    approver_roles: list[str] = field(default_factory=lambda: ["user"])
    timeout_hours: int = 24
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    required_fields: list[str] = field(default_factory=list)
    veto_power: bool = True

    def __post_init__(self) -> None:
        if not self.step_id:
            self.step_id = self.checkpoint_id


@dataclass
class AutomationPolicy:
    policy_id: str
    name: str = ""
    domain: str = "all"
    version: int = 1
    status: str = "draft"
    triggers: list[Trigger] = field(default_factory=list)
    steps: list[PipelineStep] = field(default_factory=list)
    guardrails: Guardrails = field(default_factory=Guardrails)
    human_checkpoints: list[HumanCheckpoint] = field(default_factory=list)
    audit_level: str = "standard"
    retention_days: int = 30

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.policy_id
        if self.status not in {"draft", "active", "paused", "deprecated"}:
            self.status = "draft"


def _dataclass_to_dict(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _dataclass_to_dict(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(k): _dataclass_to_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_dataclass_to_dict(v) for v in value]
    return value


def policy_to_dict(policy: AutomationPolicy) -> dict[str, Any]:
    return _dataclass_to_dict(policy)


AutomationPolicyDict = dict
TriggerConfig = Trigger
Policy = AutomationPolicy
Step = PipelineStep
Checkpoint = HumanCheckpoint


def default_guardrails() -> Guardrails:
    return Guardrails()


def make_policy(policy_id: str, *, name: str = "", domain: str = "all", steps=None, **kwargs: Any) -> AutomationPolicy:
    return AutomationPolicy(policy_id=policy_id, name=name or policy_id, domain=domain, steps=steps or [], **kwargs)
