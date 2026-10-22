"""Persistance et requêtes du registre de traçabilité (SPEC-011).

Ce module apporte deux choses :

1. :class:`TraceabilityStore` — la persistance SQLite du registre (une base
   dédiée, locale, chiffrable par le filesystem comme le reste des données
   Career) ;
2. :class:`TraceabilityService` — la façade qui relie le registre en
   mémoire (:class:`~career.traceability.TraceabilityRegistry`) au stockage,
   et qui expose les opérations utilisées par l'API HTTP.

PRINCIPES DE PERSISTANCE
------------------------
* **Base dédiée** — ``career_data/traceability.sqlite3`` : la base Career
  principale n'est pas touchée, donc aucune migration de ``career.sqlite3``
  n'est nécessaire et le registre peut être réinitialisé seul.
* **Schéma additif** — ``CREATE TABLE IF NOT EXISTS`` : la table et ses
  index sont créés une fois, jamais réécrits.
* **Écriture idempotente** — une trace est écrite par ``INSERT OR REPLACE``
  (clé primaire ``trace_id``) et un événement par ``INSERT OR IGNORE``
  (clé primaire ``event_id``) : réimporter le même registre ne duplique
  rien.
* **Journal immuable** — la table ``traceability_events`` conserve tous les
  événements, y compris ceux des traces supprimées : l'historique ne
  disparaît jamais.
* **Confidentialité** — fichier en ``0600``, répertoire en ``0700``,
  ``secure_delete`` activé : le registre contient des extraits de CV.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from .models import clean_text, utc_now
from .traceability import (
    RequirementTrace,
    TraceabilityError,
    TraceabilityRegistry,
    auto_link_evidence,
)


__all__ = [
    "TraceabilityService",
    "TraceabilityStore",
]


SCHEMA_VERSION = 1

CSV_COLUMNS: tuple[str, ...] = (
    "trace_id",
    "requirement_id",
    "requirement_text",
    "source",
    "offer_id",
    "cv_id",
    "category",
    "criticality",
    "status",
    "evidence_id",
    "evidence_quote",
    "link_origin",
    "review_state",
    "match_kind",
    "locator",
    "source_field",
    "tags",
    "created_at",
    "updated_at",
    "history_count",
)


class TraceabilityStore:
    """SQLite persistence of the traceability registry."""

    def __init__(self, db_path: Path | str, *, clock: Callable[[], str] = utc_now) -> None:
        self.db_path = Path(db_path)
        self._clock = clock
        self._ensure_storage()
        self._initialize()

    # -- storage ------------------------------------------------------------
    def _ensure_storage(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise TraceabilityError(
                "Le registre de traçabilité a rencontré un problème local. Réessaie."
            ) from error
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS traceability_traces (
                    trace_id TEXT PRIMARY KEY,
                    requirement_id TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    offer_id TEXT NOT NULL DEFAULT '',
                    cv_id TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'other',
                    criticality TEXT NOT NULL DEFAULT 'contextual',
                    status TEXT NOT NULL DEFAULT 'uncovered',
                    evidence_id TEXT,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS traceability_events (
                    event_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    payload TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            for statement in (
                "CREATE INDEX IF NOT EXISTS idx_traces_status ON traceability_traces(status)",
                "CREATE INDEX IF NOT EXISTS idx_traces_category ON traceability_traces(category)",
                "CREATE INDEX IF NOT EXISTS idx_traces_criticality ON traceability_traces(criticality)",
                "CREATE INDEX IF NOT EXISTS idx_traces_offer ON traceability_traces(offer_id)",
                "CREATE INDEX IF NOT EXISTS idx_traces_cv ON traceability_traces(cv_id)",
                "CREATE INDEX IF NOT EXISTS idx_traces_deleted ON traceability_traces(deleted)",
                "CREATE INDEX IF NOT EXISTS idx_events_trace ON traceability_events(trace_id)",
                "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON traceability_events(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_events_type ON traceability_events(event_type)",
            ):
                connection.execute(statement)
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    # -- writes -------------------------------------------------------------
    def save_trace(self, trace: RequirementTrace) -> None:
        """Persist one trace and its events (idempotent)."""
        payload = json.dumps(trace.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO traceability_traces (
                    trace_id, requirement_id, source, offer_id, cv_id, category,
                    criticality, status, evidence_id, deleted, created_at, updated_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.trace_id,
                    trace.requirement_id,
                    trace.source,
                    trace.offer_id,
                    trace.cv_id,
                    trace.category,
                    trace.criticality,
                    trace.status,
                    trace.evidence_id or "",
                    1 if trace.deleted else 0,
                    trace.created_at,
                    trace.updated_at,
                    payload,
                ),
            )
            for event in trace.history:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO traceability_events (
                        event_id, trace_id, timestamp, event_type, actor, payload
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        trace.trace_id,
                        event.timestamp,
                        event.event_type,
                        event.actor,
                        json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True),
                    ),
                )

    def save_traces(self, traces: Iterable[RequirementTrace]) -> int:
        count = 0
        for trace in traces:
            self.save_trace(trace)
            count += 1
        return count

    def delete_trace(self, trace_id: str) -> None:
        """Hard-delete a trace and its events (used by the reset only)."""
        identifier = clean_text(trace_id, limit=120)
        with self._connection() as connection:
            connection.execute("DELETE FROM traceability_events WHERE trace_id = ?", (identifier,))
            connection.execute("DELETE FROM traceability_traces WHERE trace_id = ?", (identifier,))

    def clear(self) -> None:
        """Remove every trace and event (used by the personal-data reset)."""
        with self._connection() as connection:
            connection.execute("DELETE FROM traceability_events")
            connection.execute("DELETE FROM traceability_traces")

    # -- reads --------------------------------------------------------------
    def load_traces(self) -> list[RequirementTrace]:
        """Return every persisted trace (deleted ones included)."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM traceability_traces ORDER BY created_at ASC, trace_id ASC"
            ).fetchall()
        traces: list[RequirementTrace] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            traces.append(RequirementTrace.from_dict(payload))
        return traces

    def get_trace(self, trace_id: str) -> RequirementTrace | None:
        identifier = clean_text(trace_id, limit=120)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM traceability_traces WHERE trace_id = ?", (identifier,)
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return RequirementTrace.from_dict(payload)

    def list_events(self, *, trace_id: str | None = None, limit: int = 1_000) -> list[dict[str, Any]]:
        """Return the persisted events, newest last."""
        query = "SELECT payload FROM traceability_events"
        parameters: list[Any] = []
        if trace_id:
            query += " WHERE trace_id = ?"
            parameters.append(clean_text(trace_id, limit=120))
        query += " ORDER BY timestamp ASC, event_id ASC"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                events.append(payload)
        bounded = max(0, int(limit or 0))
        return events[:bounded] if bounded else events

    # -- export / import ----------------------------------------------------
    def export_json(self, traces: Sequence[RequirementTrace] | None = None) -> dict[str, Any]:
        """Return the portable export of the registry (deterministic)."""
        items = list(traces) if traces is not None else self.load_traces()
        return {
            "schema_version": SCHEMA_VERSION,
            "trace_count": len(items),
            "traces": [trace.to_dict() for trace in items],
        }

    def export_csv(self, traces: Sequence[RequirementTrace] | None = None) -> str:
        """Return the CSV export of the registry (deterministic)."""
        items = list(traces) if traces is not None else self.load_traces()
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for trace in items:
            payload = trace.to_dict()
            payload["tags"] = "|".join(trace.tags)
            payload["history_count"] = len(trace.history)
            writer.writerow({column: payload.get(column, "") for column in CSV_COLUMNS})
        return buffer.getvalue()

    def import_json(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Import a portable export — idempotent, history preserved.

        A trace already known is **not** overwritten by a stale export: the
        local (newer) version wins, and only the missing events are added.
        """
        if not isinstance(payload, Mapping):
            raise TraceabilityError("Le contenu d’import du registre est invalide.")
        records = payload.get("traces")
        if not isinstance(records, list):
            raise TraceabilityError("Le contenu d’import du registre est invalide : liste de traces attendue.")
        imported = 0
        skipped = 0
        events_added = 0
        for record in records:
            if not isinstance(record, Mapping):
                skipped += 1
                continue
            trace = RequirementTrace.from_dict(record)
            if not trace.trace_id:
                skipped += 1
                continue
            existing = self.get_trace(trace.trace_id)
            if existing is None:
                self.save_trace(trace)
                imported += 1
                continue
            known = {event.event_id for event in existing.history}
            merged = list(existing.history)
            for event in trace.history:
                if event.event_id not in known:
                    merged.append(event)
                    events_added += 1
            existing.history = merged
            if trace.updated_at > existing.updated_at:
                existing.category = trace.category
                existing.criticality = trace.criticality
                existing.status = trace.status
                existing.evidence_id = trace.evidence_id
                existing.evidence_quote = trace.evidence_quote
                existing.tags = trace.tags
                existing.updated_at = trace.updated_at
            self.save_trace(existing)
            skipped += 1
        return {
            "imported": imported,
            "skipped": skipped,
            "events_added": events_added,
        }


class TraceabilityService:
    """Facade combining the in-memory registry and its SQLite persistence."""

    def __init__(self, db_path: Path | str, *, clock: Callable[[], str] = utc_now) -> None:
        self._clock = clock
        self.store = TraceabilityStore(db_path, clock=clock)
        self.registry = TraceabilityRegistry(clock=clock)
        self._lock = threading.RLock()
        self._load()

    # -- internals ----------------------------------------------------------
    def _load(self) -> None:
        self.registry.restore_all(self.store.load_traces())

    def _persist(self, *traces: RequirementTrace) -> RequirementTrace:
        for trace in traces:
            self.store.save_trace(trace)
        return traces[0]

    # -- creation -----------------------------------------------------------
    def create_requirement(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Create one traceability record from an API payload."""
        with self._lock:
            trace = self.registry.register(
                clean_text(payload.get("requirement_id"), limit=200),
                clean_text(payload.get("requirement_text"), limit=4_000),
                clean_text(payload.get("source"), limit=200) or "manual",
                category=clean_text(payload.get("category"), limit=60) or "other",
                criticality=clean_text(payload.get("criticality"), limit=60) or "contextual",
                tags=payload.get("tags") or [],
                actor=clean_text(payload.get("actor"), limit=40) or "user",
                comment=clean_text(payload.get("comment"), limit=2_000) or None,
                offer_id=clean_text(payload.get("offer_id"), limit=120),
                cv_id=clean_text(payload.get("cv_id"), limit=120),
                locator=clean_text(payload.get("locator"), limit=200),
                source_field=clean_text(payload.get("source_field"), limit=120),
            )
            self._persist(trace)
            return trace.to_dict()

    def register_offer_analysis(self, analysis: Mapping[str, Any], *, actor: str = "system") -> dict[str, Any]:
        """Register every requirement of a SK-02 analysis."""
        with self._lock:
            traces = self.registry.register_offer_analysis(analysis, actor=actor)
            self.store.save_traces(traces)
            return {
                "registered": len(traces),
                "offer_id": clean_text((analysis or {}).get("offer_id"), limit=120),
                "trace_ids": [trace.trace_id for trace in traces],
            }

    def register_facts(self, facts: Iterable[Mapping[str, Any]], *, cv_id: str, actor: str = "system") -> dict[str, Any]:
        """Register the facts of a candidate profile (SK-10)."""
        with self._lock:
            traces = self.registry.register_facts(facts, cv_id=cv_id, actor=actor)
            self.store.save_traces(traces)
            return {"registered": len(traces), "cv_id": clean_text(cv_id, limit=120)}

    # -- reads --------------------------------------------------------------
    def list_requirements(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return the traces matching the filters."""
        payload = filters or {}
        traces = self.registry.list_traces(
            status=clean_text(payload.get("status"), limit=40) or None,
            category=clean_text(payload.get("category"), limit=40) or None,
            criticality=clean_text(payload.get("criticality"), limit=40) or None,
            offer_id=clean_text(payload.get("offer_id"), limit=120) or None,
            cv_id=clean_text(payload.get("cv_id"), limit=120) or None,
            source=clean_text(payload.get("source"), limit=200) or None,
            tag=clean_text(payload.get("tag"), limit=60) or None,
            query=clean_text(payload.get("query"), limit=200) or None,
            review_state=clean_text(payload.get("review_state"), limit=40) or None,
            include_deleted=bool(payload.get("include_deleted")),
        )
        return {
            "count": len(traces),
            "requirements": [trace.to_dict() for trace in traces],
        }

    def get_requirement(self, trace_id: str) -> dict[str, Any] | None:
        trace = self.registry.get(trace_id)
        return trace.to_dict() if trace else None

    # -- mutations ----------------------------------------------------------
    def update_requirement(self, trace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Update the mutable fields of a requirement (status, tags, …)."""
        with self._lock:
            trace = self.registry.get(trace_id)
            if trace is None:
                raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
            actor = clean_text(payload.get("actor"), limit=40) or "user"
            comment = clean_text(payload.get("comment"), limit=2_000) or None
            if payload.get("category"):
                self.registry.set_category(trace.trace_id, payload["category"], actor=actor, comment=comment)
            if payload.get("criticality"):
                self.registry.set_criticality(trace.trace_id, payload["criticality"], actor=actor, comment=comment)
            if "tags" in payload:
                self.registry.set_tags(trace.trace_id, payload.get("tags") or [], actor=actor, comment=comment)
            if payload.get("status"):
                self.registry.set_status(trace.trace_id, payload["status"], actor=actor, comment=comment)
            self._persist(trace)
            return trace.to_dict()

    def link_evidence(self, trace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            trace = self.registry.get(trace_id)
            if trace is None:
                raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
            updated = self.registry.link_evidence(
                trace.trace_id,
                evidence_id=clean_text(payload.get("evidence_id"), limit=200),
                evidence_quote=clean_text(payload.get("evidence_quote"), limit=4_000) or None,
                actor=clean_text(payload.get("actor"), limit=40) or "user",
                comment=clean_text(payload.get("comment"), limit=2_000) or None,
                origin=clean_text(payload.get("origin"), limit=20) or "manual",
                status=clean_text(payload.get("status"), limit=40) or None,
                match_kind=clean_text(payload.get("match_kind"), limit=60),
            )
            self._persist(updated)
            return updated.to_dict()

    def unlink_evidence(self, trace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            trace = self.registry.get(trace_id)
            if trace is None:
                raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
            updated = self.registry.unlink_evidence(
                trace.trace_id,
                actor=clean_text(payload.get("actor"), limit=40) or "user",
                comment=clean_text(payload.get("comment"), limit=2_000) or None,
            )
            self._persist(updated)
            return updated.to_dict()

    def waive(self, trace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            trace = self.registry.get(trace_id)
            if trace is None:
                raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
            updated = self.registry.waive(
                trace.trace_id,
                clean_text(payload.get("justification"), limit=2_000),
                actor=clean_text(payload.get("actor"), limit=40) or "user",
            )
            self._persist(updated)
            return updated.to_dict()

    def reopen(self, trace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            trace = self.registry.get(trace_id)
            if trace is None:
                raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
            updated = self.registry.reopen(
                trace.trace_id,
                actor=clean_text(payload.get("actor"), limit=40) or "user",
                comment=clean_text(payload.get("comment"), limit=2_000) or None,
            )
            self._persist(updated)
            return updated.to_dict()

    def confirm_link(self, trace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            trace = self.registry.get(trace_id)
            if trace is None:
                raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
            updated = self.registry.confirm_link(
                trace.trace_id,
                actor=clean_text(payload.get("actor"), limit=40) or "user",
                comment=clean_text(payload.get("comment"), limit=2_000) or None,
            )
            self._persist(updated)
            return updated.to_dict()

    def reject_link(self, trace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            trace = self.registry.get(trace_id)
            if trace is None:
                raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
            updated = self.registry.reject_link(
                trace.trace_id,
                actor=clean_text(payload.get("actor"), limit=40) or "user",
                reason=clean_text(payload.get("reason") or payload.get("comment"), limit=2_000) or None,
            )
            self._persist(updated)
            return updated.to_dict()

    def delete_requirement(self, trace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            trace = self.registry.get(trace_id)
            if trace is None:
                raise TraceabilityError("Cette exigence n’existe pas dans le registre.")
            updated = self.registry.delete(
                trace.trace_id,
                actor=clean_text(payload.get("actor"), limit=40) or "user",
                comment=clean_text(payload.get("comment"), limit=2_000) or None,
            )
            self._persist(updated)
            return updated.to_dict()

    def auto_link(self, evidences: Iterable[Any], *, actor: str = "system") -> dict[str, Any]:
        """Propose automatic links between the registry and the evidences."""
        with self._lock:
            summary = auto_link_evidence(self.registry, evidences, actor=actor)
            self.store.save_traces(self.registry.all())
            return summary

    def batch_apply(
        self,
        trace_ids: Sequence[str],
        action: str,
        *,
        justification: str = "",
        actor: str = "user",
    ) -> dict[str, Any]:
        """Apply one action to several requirements (batch mode).

        The batch never stops at the first failure: each requirement is
        applied independently and the errors are reported per requirement, so
        a refusal (missing justification, unknown trace) never hides the
        other results.
        """
        kind = clean_text(action, limit=40).lower()
        if kind not in {"confirm", "reject", "unlink", "waive"}:
            raise TraceabilityError(
                "Action de lot inconnue : utilise « confirm », « reject », « unlink » ou « waive »."
            )
        applied: list[str] = []
        failed: list[dict[str, str]] = []
        for trace_id in trace_ids or []:
            identifier = clean_text(trace_id, limit=120)
            try:
                if kind == "confirm":
                    self.confirm_link(identifier, {"actor": actor})
                elif kind == "reject":
                    self.reject_link(identifier, {"actor": actor, "reason": "Liaison rejetée (lot)"})
                elif kind == "unlink":
                    self.unlink_evidence(identifier, {"actor": actor, "comment": "Preuve retirée (lot)"})
                else:
                    self.waive(identifier, {"justification": justification, "actor": actor})
                applied.append(identifier)
            except TraceabilityError as error:
                failed.append({"trace_id": identifier, "error": str(error)})
        return {
            "action": kind,
            "applied_count": len(applied),
            "failed_count": len(failed),
            "applied": applied,
            "failed": failed,
        }

    # -- export / import ----------------------------------------------------
    def export(self, export_format: str = "json") -> tuple[str, str]:
        """Return ``(content, media_type)`` for the requested export format."""
        kind = clean_text(export_format, limit=10).lower() or "json"
        traces = self.registry.all()
        if kind == "csv":
            return self.store.export_csv(traces), "text/csv; charset=utf-8"
        if kind != "json":
            raise TraceabilityError("Format d’export inconnu : utilise « json » ou « csv ».")
        return json.dumps(self.store.export_json(traces), ensure_ascii=False, indent=2), "application/json; charset=utf-8"

    def import_traces(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Import a portable export and reload the registry."""
        with self._lock:
            summary = self.store.import_json(payload)
            self._load()
            return summary

    def reset(self) -> None:
        """Erase the registry (used by the personal-data reset)."""
        with self._lock:
            self.store.clear()
            self.registry.restore_all([])
