"""Audit trail and compliance helpers for controlled automation (SPEC-016).

Events are immutable once recorded: the store keeps deep copies so a caller can
never rewrite history through a returned reference (audit immutability is a
SPEC-016 success criterion), and retention can be enforced per policy.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
        # Defensive copy: history is immutable, whatever the caller keeps.
        stored = copy.deepcopy(event)
        self.events.append(stored)
        return stored

    def record(self, **kwargs: Any) -> AuditEvent:
        event = AuditEvent(**kwargs)
        return self.append(event)

    def prune_before(self, cutoff_iso: str) -> int:
        """Drop events strictly older than ``cutoff_iso`` (ISO8601). Returns count."""
        keep, removed = [], 0
        for event in self.events:
            if event.timestamp < cutoff_iso:
                removed += 1
            else:
                keep.append(event)
        self.events = keep
        return removed

    def prune_older_than(self, retention_days: int, *, now: datetime | None = None) -> int:
        if retention_days <= 0:
            return 0
        moment = now or datetime.now(timezone.utc)
        cutoff = (moment - timedelta(days=retention_days)).isoformat()
        return self.prune_before(cutoff)

    def filter(
        self,
        *,
        execution_id: str | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        actor: str | None = None,
        correlation_id: str | None = None,
        query: str | None = None,
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
        if correlation_id is not None:
            result = [e for e in result if e.correlation_id == correlation_id]
        if query:
            needle = query.lower()
            result = [
                e
                for e in result
                if needle in json.dumps(_to_dict(e), ensure_ascii=False).lower()
            ]
        # Defensive copies: history stays immutable for every consumer.
        return [copy.deepcopy(e) for e in result]

    def export_json(self) -> str:
        return json.dumps([_to_dict(e) for e in self.events], ensure_ascii=False, indent=2)

    def export_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["event_id", "timestamp", "execution_id", "event_type", "actor", "actor_id", "severity", "correlation_id", "details"])
        for event in self.events:
            writer.writerow([
                event.event_id,
                event.timestamp,
                event.execution_id or "",
                event.event_type,
                event.actor,
                event.actor_id,
                event.severity,
                event.correlation_id,
                json.dumps(event.details, ensure_ascii=False),
            ])
        return buffer.getvalue()

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
        return [copy.deepcopy(e) for e in self._trail.events]

    def filter(self, **kwargs: Any) -> list[AuditEvent]:
        return self._trail.filter(**kwargs)

    def prune_older_than(self, retention_days: int, *, now: datetime | None = None) -> int:
        return self._trail.prune_older_than(retention_days, now=now)

    def prune_before(self, cutoff_iso: str) -> int:
        return self._trail.prune_before(cutoff_iso)

    def __len__(self) -> int:
        return len(self._trail.events)

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
