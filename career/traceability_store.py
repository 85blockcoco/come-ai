"""SQLite persistence for the requirement traceability registry (SPEC-011).

The store is deliberately thin: it owns the schema, the indexes and the
queries, while every business rule stays in ``career.traceability``.

TWO TABLES
- ``requirement_traces`` holds the **current state** of every requirement.
- ``trace_events`` holds the **append-only** audit trail.

The history is never rewritten: the store only ever inserts events (with
``INSERT OR IGNORE`` on the event id), so a restart of the application cannot
change what happened.  The current state of a trace is rebuilt by applying
its events, which keeps the database and the in-memory registry consistent.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Sequence

from .traceability import RequirementTrace, TraceEvent


TRACEABILITY_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requirement_traces (
    trace_id TEXT PRIMARY KEY,
    requirement_id TEXT NOT NULL DEFAULT '',
    requirement_text TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    offer_id TEXT NOT NULL DEFAULT '',
    cv_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other',
    criticality TEXT NOT NULL DEFAULT 'contextual',
    status TEXT NOT NULL DEFAULT 'uncovered',
    evidence_id TEXT NOT NULL DEFAULT '',
    evidence_quote TEXT NOT NULL DEFAULT '',
    source_field TEXT NOT NULL DEFAULT '',
    locator TEXT NOT NULL DEFAULT '',
    confidence REAL,
    auto_linked INTEGER NOT NULL DEFAULT 0,
    validated INTEGER,
    waiver_reason TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS requirement_traces_status_idx ON requirement_traces(status);
CREATE INDEX IF NOT EXISTS requirement_traces_category_idx ON requirement_traces(category);
CREATE INDEX IF NOT EXISTS requirement_traces_criticality_idx ON requirement_traces(criticality);
CREATE INDEX IF NOT EXISTS requirement_traces_offer_idx ON requirement_traces(offer_id);
CREATE INDEX IF NOT EXISTS requirement_traces_cv_idx ON requirement_traces(cv_id);
CREATE INDEX IF NOT EXISTS requirement_traces_updated_idx ON requirement_traces(updated_at DESC);

CREATE TABLE IF NOT EXISTS trace_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL DEFAULT 'system',
    comment TEXT
);

CREATE INDEX IF NOT EXISTS trace_events_trace_idx ON trace_events(trace_id, timestamp);
CREATE INDEX IF NOT EXISTS trace_events_type_idx ON trace_events(event_type, timestamp);
CREATE INDEX IF NOT EXISTS trace_events_actor_idx ON trace_events(actor, timestamp);
"""


class TraceabilityStore:
    """Read/write access to the traceability tables of the local database."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    # -- schema ------------------------------------------------------------

    @staticmethod
    def ensure_schema(connection: sqlite3.Connection) -> None:
        """Create the traceability tables when they are missing.

        The statement is idempotent: a fresh database and a migrated one end
        up with exactly the same tables.
        """
        connection.executescript(_SCHEMA)

    # -- writing -----------------------------------------------------------

    def save_trace(self, trace: RequirementTrace) -> None:
        """Upsert the current state of one trace."""
        self.connection.execute(
            """
            INSERT INTO requirement_traces (
                trace_id, requirement_id, requirement_text, source, offer_id, cv_id,
                category, criticality, status, evidence_id, evidence_quote,
                source_field, locator, confidence, auto_linked, validated,
                waiver_reason, tags_json, deleted, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trace_id) DO UPDATE SET
                requirement_id = excluded.requirement_id,
                requirement_text = excluded.requirement_text,
                source = excluded.source,
                offer_id = excluded.offer_id,
                cv_id = excluded.cv_id,
                category = excluded.category,
                criticality = excluded.criticality,
                status = excluded.status,
                evidence_id = excluded.evidence_id,
                evidence_quote = excluded.evidence_quote,
                source_field = excluded.source_field,
                locator = excluded.locator,
                confidence = excluded.confidence,
                auto_linked = excluded.auto_linked,
                validated = excluded.validated,
                waiver_reason = excluded.waiver_reason,
                tags_json = excluded.tags_json,
                deleted = excluded.deleted,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                trace.trace_id,
                trace.requirement_id,
                trace.requirement_text,
                trace.source,
                trace.offer_id,
                trace.cv_id,
                trace.category,
                trace.criticality,
                trace.status,
                trace.evidence_id or "",
                trace.evidence_quote or "",
                trace.source_field,
                trace.locator,
                trace.confidence,
                1 if trace.auto_linked else 0,
                None if trace.validated is None else (1 if trace.validated else 0),
                trace.waiver_reason or "",
                json.dumps(list(trace.tags), ensure_ascii=False),
                1 if trace.deleted else 0,
                trace.created_at,
                trace.updated_at,
            ),
        )

    def save_traces(self, traces: Iterable[RequirementTrace]) -> None:
        for trace in traces:
            self.save_trace(trace)

    def append_events(self, trace_id: str, events: Sequence[TraceEvent]) -> int:
        """Append events to the immutable audit trail.

        Events are inserted with ``INSERT OR IGNORE``: re-saving the same
        event (for instance after a restart) never duplicates nor rewrites
        history.
        """
        written = 0
        for event in events:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO trace_events
                    (event_id, trace_id, timestamp, event_type, old_value, new_value, actor, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    trace_id,
                    event.timestamp,
                    event.event_type,
                    event.old_value,
                    event.new_value,
                    event.actor,
                    event.comment,
                ),
            )
            written += cursor.rowcount if cursor.rowcount > 0 else 0
        return written

    # -- reading -----------------------------------------------------------

    def load_trace(self, trace_id: str) -> RequirementTrace | None:
        row = self.connection.execute(
            "SELECT * FROM requirement_traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if row is None:
            return None
        trace = _row_to_trace(row)
        trace.history = self.load_events(trace_id=trace_id)
        return trace

    def load_traces(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        criticality: str | None = None,
        offer_id: str | None = None,
        cv_id: str | None = None,
        source: str | None = None,
        tag: str | None = None,
        include_deleted: bool = False,
    ) -> list[RequirementTrace]:
        """Return the traces matching every provided filter."""
        clauses: list[str] = []
        params: list[Any] = []
        if not include_deleted:
            clauses.append("deleted = 0")
        for column, value in (
            ("status", status),
            ("category", category),
            ("criticality", criticality),
            ("offer_id", offer_id),
            ("cv_id", cv_id),
            ("source", source),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM requirement_traces{where} ORDER BY created_at ASC, trace_id ASC", params
        ).fetchall()
        traces = [_row_to_trace(row) for row in rows]
        if tag:
            traces = [trace for trace in traces if tag in trace.tags]
        return traces

    def load_events(
        self,
        *,
        trace_id: str | None = None,
        event_type: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[TraceEvent]:
        """Return the audit trail, optionally filtered."""
        clauses: list[str] = []
        params: list[Any] = []
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM trace_events{where} ORDER BY timestamp ASC, event_id ASC", params
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def load_events_grouped(
        self,
        *,
        event_type: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, list[TraceEvent]]:
        """Return the audit trail grouped by requirement.

        The grouping is done by the store so the ``TraceEvent`` entity keeps
        exactly the fields of the SPEC-011 contract.
        """
        grouped: dict[str, list[TraceEvent]] = {}
        clauses: list[str] = []
        params: list[Any] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM trace_events{where} ORDER BY timestamp ASC, event_id ASC", params
        ).fetchall()
        for row in rows:
            grouped.setdefault(str(row["trace_id"]), []).append(_row_to_event(row))
        return grouped

    def counts_by_status(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) AS total FROM requirement_traces WHERE deleted = 0 GROUP BY status"
        ).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}


def _row_to_trace(row: sqlite3.Row) -> RequirementTrace:
    validated = row["validated"]
    confidence = row["confidence"]
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        tags = []
    return RequirementTrace(
        trace_id=str(row["trace_id"]),
        requirement_id=str(row["requirement_id"]),
        requirement_text=str(row["requirement_text"]),
        source=str(row["source"]),
        category=str(row["category"]),
        criticality=str(row["criticality"]),
        evidence_id=str(row["evidence_id"]) or None,
        evidence_quote=str(row["evidence_quote"]) or None,
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        history=[],
        tags=[str(tag) for tag in tags] if isinstance(tags, list) else [],
        offer_id=str(row["offer_id"]),
        cv_id=str(row["cv_id"]),
        source_field=str(row["source_field"]),
        locator=str(row["locator"]),
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        auto_linked=bool(row["auto_linked"]),
        validated=bool(validated) if validated is not None else None,
        waiver_reason=str(row["waiver_reason"]) or None,
        deleted=bool(row["deleted"]),
    )


def _row_to_event(row: sqlite3.Row) -> TraceEvent:
    return TraceEvent(
        event_id=str(row["event_id"]),
        timestamp=str(row["timestamp"]),
        event_type=str(row["event_type"]),
        old_value=str(row["old_value"]) if row["old_value"] is not None else None,
        new_value=str(row["new_value"]) if row["new_value"] is not None else None,
        actor=str(row["actor"]),
        comment=str(row["comment"]) if row["comment"] is not None else None,
    )
