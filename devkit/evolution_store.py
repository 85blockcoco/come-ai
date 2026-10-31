"""Persistent, offline state for the developer evolution workshop.

This store records bounded tasks, execution steps and measured counters. It does
not read project contents or credentials, invoke a model, run code, or apply a
candidate. Interrupted executions are put on hold explicitly, never replayed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from devkit.exporting import KitError, redact_text, source_path_allowed
from devkit.diagnostics import validate_targeted_tests


TASK_STATUSES = frozenset({"queued", "running", "waiting_provider", "needs_review", "failed", "cancelled"})
RUN_STATUSES = TASK_STATUSES | {"completed", "succeeded"}
EVENT_DATA_FIELDS = frozenset({
    "candidate_id", "attempt", "requests", "input_tokens", "output_tokens", "total_tokens",
    "duration_seconds", "tests_passed", "tests_failed", "tests_skipped", "category", "risk", "verification",
})
_COUNTER_FIELDS = frozenset({
    "attempt", "requests", "input_tokens", "output_tokens", "total_tokens",
    "tests_passed", "tests_failed", "tests_skipped",
})
_SUM_FIELDS = _COUNTER_FIELDS - {"attempt"}
_ID = re.compile(r"^[a-f0-9]{32}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,127}$")
_ADDITIONAL_SECRET = re.compile(
    r"(?i)\b(?:api[ _-]?key|access[ _-]?token|authorization|password|client[ _-]?secret)\s*[:=]\s*(?:Bearer\s+)?[^\s,;]{8,}"
)
MAX_RUN_EVENTS = 1000


class EvolutionStoreError(KitError):
    """A safe validation or storage error suitable for the workshop UI."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _safe_text(value: str, label: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise EvolutionStoreError(f"{label} doit être du texte.")
    if len(value) > maximum:
        raise EvolutionStoreError(f"{label} dépasse la longueur autorisée.")
    value = redact_text(value)
    value = _ADDITIONAL_SECRET.sub("[SECRET MASQUÉ]", value)
    value = "".join(character for character in value if character in "\n\t" or ord(character) >= 32)
    value = value.replace("\x7f", "").strip()
    if required and not value:
        raise EvolutionStoreError(f"{label} ne doit pas être vide.")
    return value[:maximum]


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise EvolutionStoreError(f"{label} invalide.")
    return value


def _tag(value: str, label: str) -> str:
    value = _safe_text(value, label, 128, required=True)
    if not _TAG.fullmatch(value):
        raise EvolutionStoreError(f"{label} doit être un identifiant court.")
    return value


def _integer(value: int, label: str, minimum: int = 0, maximum: int = 10**12) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EvolutionStoreError(f"{label} doit être un entier dans les limites autorisées.")
    return value


def _event_data(data: dict | None) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise EvolutionStoreError("Les mesures d’une étape doivent être un objet JSON.")
    result: dict[str, Any] = {}
    for key in EVENT_DATA_FIELDS:
        value = data.get(key)
        if value is None:
            continue
        if key in _COUNTER_FIELDS:
            result[key] = _integer(value, "Une mesure")
        elif key == "duration_seconds":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 86400:
                raise EvolutionStoreError("La durée mesurée est invalide.")
            result[key] = float(value)
        elif key == "candidate_id":
            result[key] = _identifier(value, "Identifiant de candidat")
        else:
            result[key] = _tag(value, "Catégorie de mesure")
    return result


class EvolutionStore:
    """SQLite metadata under ``storage_root/evolution``, with atomic claiming.

    ``storage_root`` is normally the existing ``.devkit`` directory. Counters
    represent measurements supplied by the engine: requests/tokens/durations
    are deltas, while ``attempt`` is the observed attempt number within a run.
    Unknown measurements stay absent. No model response or prompt is accepted
    in event data.
    """

    def __init__(self, storage_root: Path):
        self.storage_root = Path(storage_root).absolute()
        self.directory = self.storage_root / "evolution"
        self.database_path = self.directory / "evolution.sqlite3"
        self._assert_paths()
        try:
            self.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.directory.mkdir(exist_ok=True, mode=0o700)
            os.chmod(self.storage_root, 0o700)
            os.chmod(self.directory, 0o700)
            with self._connection(write=True) as connection:
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS evolution_tasks (
                        task_id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                        selected_files TEXT NOT NULL, acceptance TEXT NOT NULL, priority INTEGER NOT NULL,
                        status TEXT NOT NULL, candidate_id TEXT, reason TEXT, fingerprint TEXT NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS evolution_task_queue ON evolution_tasks(status, priority DESC, created_at);
                    CREATE INDEX IF NOT EXISTS evolution_task_fingerprint ON evolution_tasks(fingerprint, status);
                    CREATE TABLE IF NOT EXISTS evolution_runs (
                        run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES evolution_tasks(task_id),
                        provider TEXT NOT NULL, model TEXT NOT NULL, max_attempts INTEGER NOT NULL,
                        max_requests INTEGER NOT NULL, status TEXT NOT NULL, candidate_id TEXT,
                        reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS evolution_runs_task ON evolution_runs(task_id, created_at DESC);
                    CREATE TABLE IF NOT EXISTS evolution_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL REFERENCES evolution_runs(run_id), phase TEXT NOT NULL,
                        status TEXT NOT NULL, message TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS evolution_events_run ON evolution_events(run_id, event_id);
                """)
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(evolution_tasks)")}
                if "targeted_tests" not in columns:
                    connection.execute("ALTER TABLE evolution_tasks ADD COLUMN targeted_tests TEXT")
                connection.execute("PRAGMA user_version=2")
            # WAL is persistent and set outside the schema transaction.
            with self._connection() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
        except (OSError, sqlite3.Error):
            raise EvolutionStoreError("Le stockage local d’évolution n’a pas pu être initialisé.") from None

    def _assert_paths(self) -> None:
        for path in (self.storage_root, self.directory, self.database_path,
                     Path(str(self.database_path) + "-wal"), Path(str(self.database_path) + "-shm"),
                     Path(str(self.database_path) + "-journal")):
            if path.is_symlink():
                raise EvolutionStoreError("Les liens symboliques sont exclus du stockage d’évolution.")
            if path.exists() and ((path in {self.storage_root, self.directory} and not path.is_dir())
                                  or (path not in {self.storage_root, self.directory} and not path.is_file())):
                raise EvolutionStoreError("Le stockage d’évolution contient un chemin non ordinaire.")

    def _permissions(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            path = Path(str(self.database_path) + suffix)
            if path.exists() and not path.is_symlink():
                os.chmod(path, 0o600)

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self._assert_paths()
        connection = None
        try:
            connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            self._permissions()
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write and connection.in_transaction:
                connection.commit()
            self._permissions()
        except sqlite3.Error:
            if connection and connection.in_transaction:
                connection.rollback()
            raise EvolutionStoreError("Le stockage local d’évolution n’est pas accessible.") from None
        except Exception:
            if connection and connection.in_transaction:
                connection.rollback()
            raise
        finally:
            if connection:
                connection.close()

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        task = dict(row)
        task["selected_files"] = json.loads(task["selected_files"])
        task["targeted_tests"] = json.loads(task["targeted_tests"]) if task.get("targeted_tests") is not None else None
        task.pop("fingerprint", None)
        return task

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, Any]:
        event = dict(row)
        event["data"] = json.loads(event["data"])
        return event

    @staticmethod
    def _limit(value: int) -> int:
        return _integer(value, "La limite de liste", 1, 200)

    def add_task(self, title: str, description: str, selected_files: list[str], acceptance: str = "", priority: int = 50, *, targeted_tests: list[str] | None = None) -> dict:
        title = _safe_text(title, "Le titre", 160, required=True)
        description = _safe_text(description, "La description", 6000, required=True)
        acceptance = _safe_text(acceptance, "Les critères d’acceptation", 4000)
        priority = _integer(priority, "La priorité", 0, 100)
        if not isinstance(selected_files, list) or not 1 <= len(selected_files) <= 64:
            raise EvolutionStoreError("Sélectionnez entre 1 et 64 fichiers source autorisés.")
        if any(not isinstance(item, str) or len(item) > 240 or not source_path_allowed(item) for item in selected_files):
            raise EvolutionStoreError("La tâche contient un chemin hors du périmètre de code autorisé.")
        paths = sorted(set(selected_files))
        targeted_tests = validate_targeted_tests(targeted_tests)
        canonical = json.dumps([" ".join(title.split()), " ".join(description.split()), paths,
                                " ".join(acceptance.split()), *([targeted_tests] if targeted_tests is not None else [])], ensure_ascii=False, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        now = _now()
        with self._connection(write=True) as connection:
            existing = connection.execute(
                "SELECT * FROM evolution_tasks WHERE fingerprint=? AND status IN ('queued','running','waiting_provider') ORDER BY created_at LIMIT 1",
                (fingerprint,),
            ).fetchone()
            if existing:
                return self._task(existing)
            task_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO evolution_tasks (task_id,title,description,selected_files,acceptance,priority,status,candidate_id,reason,fingerprint,created_at,updated_at,targeted_tests) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, title, description, json.dumps(paths), acceptance, priority, "queued", None, None, fingerprint, now, now, json.dumps(targeted_tests) if targeted_tests is not None else None),
            )
            return self._task(connection.execute("SELECT * FROM evolution_tasks WHERE task_id=?", (task_id,)).fetchone())

    def get_task(self, task_id: str) -> dict:
        task_id = _identifier(task_id, "Identifiant de tâche")
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM evolution_tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            raise EvolutionStoreError("Tâche d’évolution introuvable.")
        return self._task(row)

    def list_tasks(self, limit: int = 30) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM evolution_tasks ORDER BY created_at DESC, task_id LIMIT ?", (self._limit(limit),)).fetchall()
        return [self._task(row) for row in rows]

    def next_task(self) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM evolution_tasks WHERE status='queued' ORDER BY priority DESC, created_at, task_id LIMIT 1").fetchone()
        return self._task(row) if row else None

    def _claim(self, connection: sqlite3.Connection, task_id: str | None) -> dict | None:
        if connection.execute("SELECT 1 FROM evolution_tasks WHERE status='running' LIMIT 1").fetchone():
            if task_id:
                raise EvolutionStoreError("Une tâche d’évolution est déjà en cours.")
            return None
        if task_id:
            row = connection.execute("SELECT * FROM evolution_tasks WHERE task_id=? AND status='queued'", (task_id,)).fetchone()
            if not row:
                raise EvolutionStoreError("Cette tâche n’est pas en attente d’exécution.")
        else:
            row = connection.execute("SELECT * FROM evolution_tasks WHERE status='queued' ORDER BY priority DESC, created_at, task_id LIMIT 1").fetchone()
        if row is None:
            return None
        connection.execute("UPDATE evolution_tasks SET status='running', updated_at=? WHERE task_id=?", (_now(), row["task_id"]))
        return self._task(connection.execute("SELECT * FROM evolution_tasks WHERE task_id=?", (row["task_id"],)).fetchone())

    def claim_next_task(self) -> dict | None:
        with self._connection(write=True) as connection:
            return self._claim(connection, None)

    def claim_task(self, task_id: str) -> dict:
        task_id = _identifier(task_id, "Identifiant de tâche")
        with self._connection(write=True) as connection:
            return self._claim(connection, task_id)

    def update_task(self, task_id: str, status: str, *, candidate_id: str | None = None, reason: str | None = None) -> dict:
        task_id = _identifier(task_id, "Identifiant de tâche")
        if status not in TASK_STATUSES:
            raise EvolutionStoreError("État de tâche invalide.")
        if candidate_id is not None:
            candidate_id = _identifier(candidate_id, "Identifiant de candidat")
        if reason is not None:
            reason = _safe_text(reason, "Le motif", 600)
        with self._connection(write=True) as connection:
            if not connection.execute("SELECT 1 FROM evolution_tasks WHERE task_id=?", (task_id,)).fetchone():
                raise EvolutionStoreError("Tâche d’évolution introuvable.")
            if status == "running" and connection.execute("SELECT 1 FROM evolution_tasks WHERE status='running' AND task_id<>?", (task_id,)).fetchone():
                raise EvolutionStoreError("Une tâche d’évolution est déjà en cours.")
            connection.execute("UPDATE evolution_tasks SET status=?, candidate_id=COALESCE(?,candidate_id), reason=?, updated_at=? WHERE task_id=?",
                               (status, candidate_id, reason, _now(), task_id))
            return self._task(connection.execute("SELECT * FROM evolution_tasks WHERE task_id=?", (task_id,)).fetchone())

    def begin_run(self, task_id: str, provider: str, model: str, max_attempts: int, max_requests: int) -> dict:
        task_id = _identifier(task_id, "Identifiant de tâche")
        provider, model = _tag(provider, "Le fournisseur"), _tag(model, "Le modèle")
        max_attempts = _integer(max_attempts, "Le nombre de tentatives", 1, 20)
        max_requests = _integer(max_requests, "Le budget de requêtes", 0, 100)
        with self._connection(write=True) as connection:
            task = connection.execute("SELECT * FROM evolution_tasks WHERE task_id=?", (task_id,)).fetchone()
            if not task or task["status"] != "running":
                raise EvolutionStoreError("La tâche doit être réservée avant son exécution.")
            if connection.execute("SELECT 1 FROM evolution_runs WHERE task_id=? AND status='running'", (task_id,)).fetchone():
                raise EvolutionStoreError("Cette tâche possède déjà une exécution active.")
            run_id, now = uuid.uuid4().hex, _now()
            connection.execute("INSERT INTO evolution_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (run_id, task_id, provider, model, max_attempts, max_requests, "running", None, None, now, now, None))
            return dict(connection.execute("SELECT * FROM evolution_runs WHERE run_id=?", (run_id,)).fetchone())

    def record_event(self, run_id: str, phase: str, status: str, message: str, *, data: dict | None = None) -> dict:
        run_id = _identifier(run_id, "Identifiant d’exécution")
        phase, status = _tag(phase, "L’étape"), _tag(status, "L’état d’étape")
        message = _safe_text(message, "Le résumé d’étape", 600)
        measurements = _event_data(data)
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT status FROM evolution_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise EvolutionStoreError("Exécution d’évolution introuvable.")
            if row["status"] != "running":
                raise EvolutionStoreError("Cette exécution est déjà terminée.")
            if connection.execute("SELECT COUNT(*) FROM evolution_events WHERE run_id=?", (run_id,)).fetchone()[0] >= MAX_RUN_EVENTS:
                raise EvolutionStoreError("Le nombre d’étapes dépasse la limite d’une exécution.")
            cursor = connection.execute("INSERT INTO evolution_events(run_id,phase,status,message,data,created_at) VALUES (?,?,?,?,?,?)",
                                        (run_id, phase, status, message, json.dumps(measurements, sort_keys=True), _now()))
            connection.execute("UPDATE evolution_runs SET updated_at=? WHERE run_id=?", (_now(), run_id))
            return self._event(connection.execute("SELECT * FROM evolution_events WHERE event_id=?", (cursor.lastrowid,)).fetchone())

    def record_route(self, run_id: str, provider: str, model: str) -> None:
        run_id = _identifier(run_id, "Identifiant d’exécution")
        provider, model = _tag(provider, "Le fournisseur"), _tag(model, "Le modèle")
        with self._connection(write=True) as connection:
            connection.execute("UPDATE evolution_runs SET provider=?,model=?,updated_at=? WHERE run_id=? AND status='running'", (provider, model, _now(), run_id))

    def finish_run(self, run_id: str, status: str, *, candidate_id: str | None = None, reason: str | None = None) -> dict:
        run_id = _identifier(run_id, "Identifiant d’exécution")
        if status not in RUN_STATUSES or status in {"queued", "running"}:
            raise EvolutionStoreError("État final d’exécution invalide.")
        if candidate_id is not None:
            candidate_id = _identifier(candidate_id, "Identifiant de candidat")
        if reason is not None:
            reason = _safe_text(reason, "Le motif", 600)
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT * FROM evolution_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise EvolutionStoreError("Exécution d’évolution introuvable.")
            if row["status"] != "running":
                raise EvolutionStoreError("Cette exécution est déjà terminée.")
            now = _now()
            connection.execute("UPDATE evolution_runs SET status=?,candidate_id=?,reason=?,updated_at=?,finished_at=? WHERE run_id=?",
                               (status, candidate_id, reason, now, now, run_id))
            task_status = status if status in TASK_STATUSES else ("needs_review" if candidate_id else "failed")
            # A user's cancellation persists even if the worker finishes later.
            connection.execute("UPDATE evolution_tasks SET status=CASE WHEN status='cancelled' THEN status ELSE ? END,candidate_id=COALESCE(?,candidate_id),reason=?,updated_at=? WHERE task_id=?",
                               (task_status, candidate_id, reason, now, row["task_id"]))
        return self.get_run(run_id)

    @staticmethod
    def _metrics(events: list[dict]) -> dict:
        metrics: dict[str, Any] = {key: 0 for key in _SUM_FIELDS}
        metrics.update(attempts=0, duration_seconds=0.0, measured_usage_events=0)
        for event in events:
            data = event["data"]
            for key in _SUM_FIELDS:
                metrics[key] += data.get(key, 0)
            metrics["attempts"] = max(metrics["attempts"], data.get("attempt", 0))
            metrics["duration_seconds"] += data.get("duration_seconds", 0.0)
            if any(key in data for key in {"input_tokens", "output_tokens", "total_tokens"}):
                metrics["measured_usage_events"] += 1
        return metrics

    def get_run(self, run_id: str) -> dict:
        run_id = _identifier(run_id, "Identifiant d’exécution")
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM evolution_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise EvolutionStoreError("Exécution d’évolution introuvable.")
            events = [self._event(event) for event in connection.execute("SELECT * FROM evolution_events WHERE run_id=? ORDER BY event_id", (run_id,)).fetchall()]
        return {**dict(row), "events": events, "metrics": self._metrics(events)}

    def list_runs(self, limit: int = 30) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM evolution_runs ORDER BY created_at DESC,run_id LIMIT ?", (self._limit(limit),)).fetchall()
        return [dict(row) for row in rows]

    def recover_interrupted(self) -> dict:
        """Explicit startup recovery: put unfinished work on hold, without I/O replay."""
        reason = "Exécution interrompue : reprise explicite nécessaire, aucun appel fournisseur relancé."
        with self._connection(write=True) as connection:
            now = _now()
            runs = connection.execute("UPDATE evolution_runs SET status='waiting_provider',reason=?,updated_at=?,finished_at=? WHERE status='running'", (reason, now, now)).rowcount
            tasks = connection.execute("UPDATE evolution_tasks SET status='waiting_provider',reason=?,updated_at=? WHERE status='running'", (reason, now)).rowcount
        return {"recovered_runs": runs, "recovered_tasks": tasks, "remote_requests_replayed": 0}

    def dashboard(self) -> dict:
        with self._connection() as connection:
            task_counts = {row["status"]: row["count"] for row in connection.execute("SELECT status,COUNT(*) AS count FROM evolution_tasks GROUP BY status")}
            run_counts = {row["status"]: row["count"] for row in connection.execute("SELECT status,COUNT(*) AS count FROM evolution_runs GROUP BY status")}
            events = [self._event(row) for row in connection.execute("SELECT * FROM evolution_events ORDER BY event_id")]
        metrics = self._metrics(events)
        attempts_by_run: Counter = Counter()
        for event in events:
            attempts_by_run[event["run_id"]] = max(attempts_by_run[event["run_id"]], event["data"].get("attempt", 0))
        metrics["attempts"] = sum(attempts_by_run.values())
        return {
            "available": True, "automatic_application": False,
            "task_count": sum(task_counts.values()), "run_count": sum(run_counts.values()),
            "event_count": len(events), "tasks_by_status": {key: task_counts.get(key, 0) for key in sorted(TASK_STATUSES)},
            "runs_by_status": run_counts, "metrics": metrics,
            "usage_measurements": "reported_only", "unknown_usage_is_not_estimated": True,
        }


__all__ = ["EvolutionStore", "EvolutionStoreError", "TASK_STATUSES", "RUN_STATUSES", "EVENT_DATA_FIELDS"]
