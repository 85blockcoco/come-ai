"""Audit trail and compliance helpers for controlled automation (SPEC-016)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

AUDIT_EVENT_TYPES = (
    "workflow_started", "step_started", "step_completed", "step_failed",
    "human_checkpoint_created", "human_decision_made", "guardrail_triggered",
    "circuit_breaker_opened", "circuit_breaker_closed", "rollback_initiated",
    "policy_changed", "policy_activated", "policy_deactivated",
)


@dataclass
class AuditEvent:
    event_id: str = ""
    timestamp: str = ""
    execution_id: str | None = None
    event_type: str = "workflow_started"
    actor: str = "system"
    actor_id: str = "system"
    details: dict[str, Any] = field(default_factory=dict)
    severity: str = "info"
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.correlation_id:
            self.correlation_id = self.execution_id or self.event_id


@dataclass
class AuditTrail:
    events: list[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> AuditEvent:
        self.events.append(event)
        return event

    def record(self, **kwargs: Any) -> AuditEvent:
        event = AuditEvent(**kwargs)
        return self.append(event)

    def filter(
        self,
        *,
        execution_id: str | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        actor: str | None = None,
    ) -> list[AuditEvent]:
        result = list(self.events)
        if execution_id is not None:
            result = [e for e in result if e.execution_id == execution_id]
        if event_type is not None:
            result = [e for e in result if e.event_type == event_type]
        if severity is not None:
            result = [e for e in result if e.severity == severity]
        if actor is not None:
            result = [e for e in result if e.actor == actor]
        return result

    def export_json(self) -> str:
        return json.dumps([_to_dict(e) for e in self.events], ensure_ascii=False, indent=2)

    def export_csv(self) -> str:
        lines = ["event_id,timestamp,execution_id,event_type,actor,severity"]
        for e in self.events:
            lines.append(f"{e.event_id},{e.timestamp},{e.execution_id or ''},{e.event_type},{e.actor},{e.severity}")
        return "\n".join(lines)

    def clear(self) -> None:
        self.events.clear()


class AuditStore:
    """Simple in-memory audit store with filtering and export."""

    def __init__(self) -> None:
        self._trail = AuditTrail()

    @property
    def trail(self) -> AuditTrail:
        return self._trail

    def append(self, event: AuditEvent) -> AuditEvent:
        return self._trail.append(event)

    def record(self, **kwargs: Any) -> AuditEvent:
        return self._trail.record(**kwargs)

    def all(self) -> list[AuditEvent]:
        return list(self._trail.events)

    def filter(self, **kwargs: Any) -> list[AuditEvent]:
        return self._trail.filter(**kwargs)

    def export(self, format: str = "json") -> str:
        if format == "csv":
            return self._trail.export_csv()
        return self._trail.export_json()

    def clear(self) -> None:
        self._trail.clear()


def _to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {k: _to_dict(getattr(value, k)) for k in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(k): _to_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_dict(v) for v in value]
    return value


def make_event(**kwargs: Any) -> AuditEvent:
    return AuditEvent(**kwargs)
