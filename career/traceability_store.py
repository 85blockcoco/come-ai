"""Persistance locale du registre de traçabilité — SPEC-011 (CVBOOST-46).

Le registre (voir :mod:`career.traceability`) ne sait rien du disque.  Ce
module lui fournit un magasin **local** : une base SQLite dédiée, placée
dans le répertoire privé ``career_data/``, jamais dans l'espace de travail
général, jamais synchronisée, jamais envoyée ailleurs.

CHOIX DE PERSISTANCE
--------------------
* **Une base dédiée** (``career_data/traceability.sqlite3``) et non la base
  Career principale : le registre peut évoluer (nouvelles colonnes, nouveaux
  index) sans toucher au schéma versionné de l'application, et les autres
  modules SPEC peuvent être fusionnés en parallèle.
* **Deux tables** : ``traceability_requirements`` (l'état courant) et
  ``traceability_events`` (l'historique, append-only).  Les événements ne
  sont **pas** supprimés quand une exigence l'est : le journal d'audit
  survit à la suppression de l'exigence qu'il décrit.
* **Aucune horloge ni aucun réseau** dans le magasin : les horodatages
  viennent du registre.

PRIVACITÉ
---------
``reset()`` efface toutes les lignes : c'est le point d'entrée utilisé par la
suppression des données Career, pour qu'aucune trace personnelle ne survive à
une demande d'effacement.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from workspace_core import UserFacingError

from .traceability import (
    RequirementTrace,
    TraceEvent,
    TraceabilityError,
    TraceabilityRegistry,
    auto_link_from_matching,
    event_to_dict,
    trace_from_dict,
    trace_to_dict,
    traces_from_offer_analysis,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS traceability_requirements (
    trace_id TEXT PRIMARY KEY,
    requirement_id TEXT NOT NULL DEFAULT '',
    requirement_text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other',
    criticality TEXT NOT NULL DEFAULT 'contextual',
    evidence_id TEXT,
    evidence_quote TEXT,
    status TEXT NOT NULL DEFAULT 'uncovered',
    offer_id TEXT NOT NULL DEFAULT '',
    cv_id TEXT NOT NULL DEFAULT '',
    locator TEXT NOT NULL DEFAULT '',
    source_field TEXT NOT NULL DEFAULT '',
    evidence_field TEXT NOT NULL DEFAULT '',
    evidence_offset INTEGER,
    link_origin TEXT NOT NULL DEFAULT 'manual',
    confirmed INTEGER NOT NULL DEFAULT 1,
    waiver_reason TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS traceability_status_idx
    ON traceability_requirements(status);
CREATE INDEX IF NOT EXISTS traceability_category_idx
    ON traceability_requirements(category);
CREATE INDEX IF NOT EXISTS traceability_criticality_idx
    ON traceability_requirements(criticality);
CREATE INDEX IF NOT EXISTS traceability_offer_idx
    ON traceability_requirements(offer_id);
CREATE INDEX IF NOT EXISTS traceability_cv_idx
    ON traceability_requirements(cv_id);
CREATE INDEX IF NOT EXISTS traceability_source_idx
    ON traceability_requirements(source);

CREATE TABLE IF NOT EXISTS traceability_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    trace_id TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL DEFAULT 'system',
    comment TEXT,
    origin TEXT NOT NULL DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS traceability_events_trace_idx
    ON traceability_events(trace_id, seq);
CREATE INDEX IF NOT EXISTS traceability_events_time_idx
    ON traceability_events(timestamp);
"""

_REQUIREMENT_COLUMNS = (
    "trace_id",
    "requirement_id",
    "requirement_text",
    "source",
    "category",
    "criticality",
    "evidence_id",
    "evidence_quote",
    "status",
    "offer_id",
    "cv_id",
    "locator",
    "source_field",
    "evidence_field",
    "evidence_offset",
    "link_origin",
    "confirmed",
    "waiver_reason",
    "tags_json",
    "created_at",
    "updated_at",
)


class TraceabilityStore:
    """Magasin SQLite local du registre de traçabilité."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    # -- connexion ---------------------------------------------------------

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise UserFacingError(
                "Le registre de traçabilité a rencontré un problème. Réessaie."
            ) from error
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(SCHEMA)
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    # -- écriture ----------------------------------------------------------

    def save_trace(self, trace: RequirementTrace, events: Sequence[TraceEvent] = ()) -> None:
        """Enregistre l'état courant d'une exigence et ses nouveaux événements."""
        payload = {
            "trace_id": trace.trace_id,
            "requirement_id": trace.requirement_id,
            "requirement_text": trace.requirement_text,
            "source": trace.source,
            "category": trace.category,
            "criticality": trace.criticality,
            "evidence_id": trace.evidence_id,
            "evidence_quote": trace.evidence_quote,
            "status": trace.status,
            "offer_id": trace.offer_id,
            "cv_id": trace.cv_id,
            "locator": trace.locator,
            "source_field": trace.source_field,
            "evidence_field": trace.evidence_field,
            "evidence_offset": trace.evidence_offset,
            "link_origin": trace.link_origin,
            "confirmed": 1 if trace.confirmed else 0,
            "waiver_reason": trace.waiver_reason,
            "tags_json": json.dumps(list(trace.tags), ensure_ascii=False),
            "created_at": trace.created_at,
            "updated_at": trace.updated_at,
        }
        placeholders = ", ".join(f":{column}" for column in _REQUIREMENT_COLUMNS)
        columns = ", ".join(_REQUIREMENT_COLUMNS)
        with self._lock, self._connection() as connection:
            connection.execute(
                f"INSERT OR REPLACE INTO traceability_requirements ({columns}) VALUES ({placeholders})",
                payload,
            )
            self._insert_events(connection, events or trace.history)

    def save_events(self, events: Sequence[TraceEvent]) -> None:
        """Ajoute des événements au journal (append-only)."""
        with self._lock, self._connection() as connection:
            self._insert_events(connection, events)

    @staticmethod
    def _insert_events(connection: sqlite3.Connection, events: Sequence[TraceEvent]) -> None:
        for event in events:
            connection.execute(
                """
                INSERT OR IGNORE INTO traceability_events
                    (event_id, trace_id, timestamp, event_type, old_value, new_value, actor, comment, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.trace_id,
                    event.timestamp,
                    event.event_type,
                    event.old_value,
                    event.new_value,
                    event.actor,
                    event.comment,
                    event.origin,
                ),
            )

    def delete_trace(self, trace_id: str) -> None:
        """Supprime l'exigence courante.  Son journal d'audit est conservé."""
        with self._lock, self._connection() as connection:
            connection.execute(
                "DELETE FROM traceability_requirements WHERE trace_id = ?", (trace_id,)
            )

    def reset(self) -> None:
        """Efface toutes les traces et tout l'historique (données personnelles)."""
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM traceability_events")
            connection.execute("DELETE FROM traceability_requirements")

    # -- lecture -----------------------------------------------------------

    def _row_to_trace(self, row: sqlite3.Row, history: Sequence[TraceEvent] = ()) -> RequirementTrace:
        data = dict(row)
        try:
            tags = json.loads(data.get("tags_json") or "[]")
        except (TypeError, ValueError):
            tags = []
        data["tags"] = tags if isinstance(tags, list) else []
        data["confirmed"] = bool(data.get("confirmed", 1))
        data["history"] = [event_to_dict(event) for event in history]
        return trace_from_dict(data)

    def get(self, trace_id: str) -> RequirementTrace | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM traceability_requirements WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            if row is None:
                return None
            events = self._events_of(connection, trace_id)
        return self._row_to_trace(row, events)

    @staticmethod
    def _events_of(connection: sqlite3.Connection, trace_id: str) -> list[TraceEvent]:
        rows = connection.execute(
            "SELECT * FROM traceability_events WHERE trace_id = ? ORDER BY seq ASC", (trace_id,)
        ).fetchall()
        return [
            TraceEvent(
                event_id=str(row["event_id"]),
                timestamp=str(row["timestamp"]),
                event_type=str(row["event_type"]),
                old_value=row["old_value"],
                new_value=row["new_value"],
                actor=str(row["actor"]),
                comment=row["comment"],
                origin=str(row["origin"]),
                trace_id=str(row["trace_id"]),
            )
            for row in rows
        ]

    def list_traces(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        criticality: str | None = None,
        offer_id: str | None = None,
        cv_id: str | None = None,
        source: str | None = None,
        tag: str | None = None,
        query: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[RequirementTrace]:
        """Liste filtrée des exigences, avec leur historique."""
        clauses: list[str] = []
        params: list[Any] = []
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
        if tag:
            clauses.append("tags_json LIKE ?")
            params.append(f'%"{tag}"%')
        if query:
            clauses.append("(requirement_text LIKE ? OR requirement_id LIKE ? OR evidence_quote LIKE ?)")
            needle = f"%{query}%"
            params.extend([needle, needle, needle])
        sql = "SELECT * FROM traceability_requirements"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, trace_id ASC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        with self._lock, self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
            events = self._all_events(connection)
        grouped: dict[str, list[TraceEvent]] = {}
        for event in events:
            grouped.setdefault(event.trace_id, []).append(event)
        return [self._row_to_trace(row, grouped.get(str(row["trace_id"]), ())) for row in rows]

    @staticmethod
    def _all_events(connection: sqlite3.Connection) -> list[TraceEvent]:
        rows = connection.execute(
            "SELECT * FROM traceability_events ORDER BY seq ASC"
        ).fetchall()
        return [
            TraceEvent(
                event_id=str(row["event_id"]),
                timestamp=str(row["timestamp"]),
                event_type=str(row["event_type"]),
                old_value=row["old_value"],
                new_value=row["new_value"],
                actor=str(row["actor"]),
                comment=row["comment"],
                origin=str(row["origin"]),
                trace_id=str(row["trace_id"]),
            )
            for row in rows
        ]

    def events(
        self,
        *,
        trace_id: str | None = None,
        event_type: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[TraceEvent]:
        """Historique global filtré."""
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
        sql = "SELECT * FROM traceability_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY seq ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._lock, self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            TraceEvent(
                event_id=str(row["event_id"]),
                timestamp=str(row["timestamp"]),
                event_type=str(row["event_type"]),
                old_value=row["old_value"],
                new_value=row["new_value"],
                actor=str(row["actor"]),
                comment=row["comment"],
                origin=str(row["origin"]),
                trace_id=str(row["trace_id"]),
            )
            for row in rows
        ]

    def counts(self) -> dict[str, int]:
        """Compteurs bruts du registre (recalculables à tout moment)."""
        with self._lock, self._connection() as connection:
            requirements = connection.execute(
                "SELECT COUNT(*) FROM traceability_requirements"
            ).fetchone()[0]
            events = connection.execute("SELECT COUNT(*) FROM traceability_events").fetchone()[0]
        return {"requirements": int(requirements), "events": int(events)}

    def export_snapshot(self) -> dict[str, Any]:
        """Export complet du registre (JSON) pour l'export de données perso."""
        traces = self.list_traces()
        return {
            "traces": [trace_to_dict(trace) for trace in traces],
            "events": [
                {
                    "event_id": event.event_id,
                    "trace_id": event.trace_id,
                    "timestamp": event.timestamp,
                    "event_type": event.event_type,
                    "old_value": event.old_value,
                    "new_value": event.new_value,
                    "actor": event.actor,
                    "comment": event.comment,
                    "origin": event.origin,
                }
                for event in self.events()
            ],
            "counts": self.counts(),
        }

    def import_snapshot(self, payload: Mapping[str, Any], *, replace: bool = False) -> dict[str, int]:
        """Restaure un export.  Les traces déjà connues ne sont pas dupliquées."""
        data = payload or {}
        imported = 0
        skipped = 0
        with self._lock, self._connection() as connection:
            if replace:
                connection.execute("DELETE FROM traceability_events")
                connection.execute("DELETE FROM traceability_requirements")
            for raw in data.get("traces") or []:
                if not isinstance(raw, Mapping):
                    continue
                trace = trace_from_dict(raw)
                if not trace.trace_id or not trace.requirement_text:
                    skipped += 1
                    continue
                existing = connection.execute(
                    "SELECT 1 FROM traceability_requirements WHERE trace_id = ?",
                    (trace.trace_id,),
                ).fetchone()
                if existing is not None:
                    skipped += 1
                    continue
                payload_row = {
                    "trace_id": trace.trace_id,
                    "requirement_id": trace.requirement_id,
                    "requirement_text": trace.requirement_text,
                    "source": trace.source,
                    "category": trace.category,
                    "criticality": trace.criticality,
                    "evidence_id": trace.evidence_id,
                    "evidence_quote": trace.evidence_quote,
                    "status": trace.status,
                    "offer_id": trace.offer_id,
                    "cv_id": trace.cv_id,
                    "locator": trace.locator,
                    "source_field": trace.source_field,
                    "evidence_field": trace.evidence_field,
                    "evidence_offset": trace.evidence_offset,
                    "link_origin": trace.link_origin,
                    "confirmed": 1 if trace.confirmed else 0,
                    "waiver_reason": trace.waiver_reason,
                    "tags_json": json.dumps(list(trace.tags), ensure_ascii=False),
                    "created_at": trace.created_at,
                    "updated_at": trace.updated_at,
                }
                columns = ", ".join(_REQUIREMENT_COLUMNS)
                placeholders = ", ".join(f":{column}" for column in _REQUIREMENT_COLUMNS)
                connection.execute(
                    f"INSERT INTO traceability_requirements ({columns}) VALUES ({placeholders})",
                    payload_row,
                )
                self._insert_events(connection, trace.history)
                imported += 1
            for raw in data.get("events") or []:
                if not isinstance(raw, Mapping):
                    continue
                self._insert_events(
                    connection,
                    [
                        TraceEvent(
                            event_id=str(raw.get("event_id") or ""),
                            timestamp=str(raw.get("timestamp") or ""),
                            event_type=str(raw.get("event_type") or ""),
                            old_value=raw.get("old_value"),
                            new_value=raw.get("new_value"),
                            actor=str(raw.get("actor") or "system"),
                            comment=raw.get("comment"),
                            origin=str(raw.get("origin") or "manual"),
                            trace_id=str(raw.get("trace_id") or ""),
                        )
                    ],
                )
        return {"imported": imported, "skipped": skipped}


class TraceabilityLedger:
    """Facade applicative : registre pur + magasin local.

    Chaque opération recharge le registre depuis le magasin, applique la
    règle métier, puis persiste le résultat.  Le registre n'a donc jamais
    d'état en mémoire divergent du disque.
    """

    def __init__(self, store: TraceabilityStore, *, clock=None) -> None:
        self.store = store
        self._clock = clock

    # -- chargement --------------------------------------------------------

    def registry(self) -> TraceabilityRegistry:
        traces = self.store.list_traces()
        events = self.store.events()
        return TraceabilityRegistry.from_traces(traces, events=events, clock=self._clock)

    # -- lecture -----------------------------------------------------------

    def list_traces(self, **filters: Any) -> list[RequirementTrace]:
        return self.store.list_traces(**filters)

    def get(self, trace_id: str) -> RequirementTrace:
        trace = self.store.get(trace_id)
        if trace is None:
            raise TraceabilityError("Cette exigence n'existe pas dans le registre.")
        return trace

    def history(self, **filters: Any) -> list[TraceEvent]:
        return self.store.events(**filters)

    # -- écriture ----------------------------------------------------------

    def _persist(self, registry: TraceabilityRegistry, trace: RequirementTrace) -> RequirementTrace:
        self.store.save_trace(trace)
        return trace

    def create(self, **payload: Any) -> RequirementTrace:
        registry = self.registry()
        trace = registry.register(**payload)
        return self._persist(registry, trace)

    def update(self, trace_id: str, **payload: Any) -> RequirementTrace:
        registry = self.registry()
        trace = registry.get(trace_id)
        if "status" in payload and payload["status"]:
            trace = registry.set_status(
                trace_id,
                payload["status"],
                actor=payload.get("actor", "user"),
                comment=payload.get("comment"),
            )
        if payload.get("evidence_id") and payload.get("evidence_quote"):
            trace = registry.link_evidence(
                trace_id,
                evidence_id=payload["evidence_id"],
                evidence_quote=payload["evidence_quote"],
                status=payload.get("evidence_status") or "covered",
                actor=payload.get("actor", "user"),
                comment=payload.get("comment"),
                origin=payload.get("origin", "manual"),
                evidence_field=payload.get("evidence_field", ""),
                evidence_offset=payload.get("evidence_offset"),
            )
        if "tags" in payload:
            trace = registry.update_tags(
                trace_id,
                payload.get("tags"),
                actor=payload.get("actor", "user"),
                comment=payload.get("comment"),
            )
        if payload.get("category"):
            trace = registry.set_category(
                trace_id,
                payload["category"],
                actor=payload.get("actor", "user"),
                comment=payload.get("comment"),
            )
        if payload.get("criticality"):
            trace = registry.set_criticality(
                trace_id,
                payload["criticality"],
                actor=payload.get("actor", "user"),
                comment=payload.get("comment"),
            )
        return self._persist(registry, trace)

    def link_evidence(self, trace_id: str, **payload: Any) -> RequirementTrace:
        registry = self.registry()
        trace = registry.link_evidence(
            trace_id,
            evidence_id=payload.get("evidence_id", ""),
            evidence_quote=payload.get("evidence_quote", ""),
            status=payload.get("status") or "covered",
            actor=payload.get("actor", "user"),
            comment=payload.get("comment"),
            origin=payload.get("origin", "manual"),
            evidence_field=payload.get("evidence_field", ""),
            evidence_offset=payload.get("evidence_offset"),
            confirmed=payload.get("confirmed"),
        )
        return self._persist(registry, trace)

    def unlink_evidence(self, trace_id: str, **payload: Any) -> RequirementTrace:
        registry = self.registry()
        trace = registry.unlink_evidence(
            trace_id,
            actor=payload.get("actor", "user"),
            comment=payload.get("comment"),
        )
        return self._persist(registry, trace)

    def confirm_link(self, trace_id: str, *, confirmed: bool, **payload: Any) -> RequirementTrace:
        registry = self.registry()
        trace = registry.confirm_link(
            trace_id,
            confirmed=confirmed,
            actor=payload.get("actor", "user"),
            comment=payload.get("comment"),
        )
        return self._persist(registry, trace)

    def waive(self, trace_id: str, **payload: Any) -> RequirementTrace:
        registry = self.registry()
        trace = registry.waive(
            trace_id,
            justification=payload.get("justification") or payload.get("comment", ""),
            actor=payload.get("actor", "user"),
            comment=payload.get("comment"),
        )
        return self._persist(registry, trace)

    def reopen(self, trace_id: str, **payload: Any) -> RequirementTrace:
        registry = self.registry()
        trace = registry.reopen(
            trace_id,
            actor=payload.get("actor", "user"),
            comment=payload.get("comment"),
        )
        return self._persist(registry, trace)

    def delete(self, trace_id: str, **payload: Any) -> TraceEvent:
        registry = self.registry()
        event = registry.delete(
            trace_id,
            actor=payload.get("actor", "user"),
            comment=payload.get("comment"),
        )
        self.store.save_events([event])
        self.store.delete_trace(trace_id)
        return event

    # -- intégrations ------------------------------------------------------

    def sync_offer(self, analysis: Mapping[str, Any], **payload: Any) -> list[RequirementTrace]:
        """Crée (ou complète) les traces d'une offre à partir du contrat SK-02."""
        registry = self.registry()
        traces = traces_from_offer_analysis(
            registry,
            analysis,
            source=payload.get("source"),
            actor=payload.get("actor", "system"),
            comment=payload.get("comment"),
        )
        for trace in traces:
            self.store.save_trace(trace)
        return traces

    def auto_link(self, matches: Sequence[Mapping[str, Any]], **payload: Any) -> list[RequirementTrace]:
        """Applique les liaisons proposées par le matching SK-21."""
        registry = self.registry()
        traces = auto_link_from_matching(
            registry,
            matches,
            actor=payload.get("actor", "system"),
            comment=payload.get("comment"),
        )
        for trace in traces:
            self.store.save_trace(trace)
        return traces


__all__ = [
    "TraceabilityLedger",
    "TraceabilityStore",
]
