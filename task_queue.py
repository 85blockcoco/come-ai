"""File d'attente locale, persistante et bornée pour Côme AI.

Cette fondation ne sait pas exécuter de commandes, de code arbitraire, ni
appeler un modèle. Elle mémorise seulement des tâches *typées* et confie leur
exécution à des gestionnaires explicitement enregistrés par l'application.
Cela permet aux futurs outils contrôlés (documents, mémoire, Excel…) de
travailler en arrière-plan sans donner au texte d'un utilisateur le pouvoir
de choisir une fonction Python ou un chemin disque.

Les données de tâche restent locales dans SQLite. Les payloads, résultats,
erreurs et messages sont volontairement limités, et les secrets courants sont
redactés avant toute écriture en base.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeAlias

from secret_redaction import (
    DEFAULT_REPLACEMENT as _SECRET_REPLACEMENT,
    is_sensitive_key as _shared_is_sensitive_key,
    normalise_key as _shared_normalise_key,
    redact_payload as _shared_redact_payload,
    redact_text as _shared_redact_text,
)


# These limits are deliberately small enough for a local SQLite task ledger.
# Large input or output belongs in the controlled workspace and should be
# referenced by an opaque file/document identifier in the payload or result.
MAX_PAYLOAD_BYTES = 32 * 1024
MAX_RESULT_BYTES = 128 * 1024
MAX_ERROR_CHARS = 2_000
MAX_MESSAGE_CHARS = 1_000
MAX_MESSAGES_PER_TASK = 100
MAX_JSON_DEPTH = 8
MAX_JSON_CONTAINER_ITEMS = 256
MAX_JSON_STRING_CHARS = 16_000
MAX_LIST_LIMIT = 100

JsonValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)


class TaskQueueError(RuntimeError):
    """A safe error suitable for displaying in the local application."""


class TaskNotFoundError(TaskQueueError):
    """Raised when a task identifier does not exist in this queue."""


class InvalidTaskStateError(TaskQueueError):
    """Raised when a lifecycle operation is not valid for a task state."""


class TaskCancelled(TaskQueueError):
    """Raised by a handler at a cooperative cancellation checkpoint."""


class TaskKind(StrEnum):
    """The finite, application-owned set of permitted background task types."""

    ORCHESTRATOR_PLAN = "orchestrator_plan"
    DOCUMENT_IMPORT = "document_import"
    DOCUMENT_INDEX = "document_index"
    PDF_OCR = "pdf_ocr"
    MEMORY_INDEX = "memory_index"
    SPREADSHEET_ANALYSIS = "spreadsheet_analysis"
    FINANCE_ANALYSIS = "finance_analysis"
    REPORT_GENERATION = "report_generation"
    CAREER_ACTION = "career_action"
    STUDY_PLAN = "study_plan"


class TaskStatus(StrEnum):
    """Lifecycle states stored in SQLite."""

    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MessageLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


TERMINAL_STATUSES = frozenset(
    {TaskStatus.CANCELLED, TaskStatus.SUCCEEDED, TaskStatus.FAILED}
)
ACTIVE_STATUSES = frozenset({TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCELLING})


@dataclass(frozen=True, slots=True)
class TaskMessage:
    """A bounded, user-safe progress entry associated with a task."""

    created_at: str
    level: MessageLevel
    text: str


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """A task snapshot. Mutating it never changes the SQLite record."""

    id: str
    kind: TaskKind
    status: TaskStatus
    payload: dict[str, JsonValue]
    progress: int
    cancellation_requested: bool
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    result: JsonValue | None
    error: str | None
    messages: tuple[TaskMessage, ...] = ()

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_key(key: str) -> str:
    return _shared_normalise_key(key)


def _is_sensitive_key(key: str) -> bool:
    return _shared_is_sensitive_key(key)


def redact_text(value: object, *, limit: int | None = None) -> str:
    """Redact likely credentials, then cap text without keeping a traceback."""

    return _shared_redact_text(value, limit=limit, replacement=_SECRET_REPLACEMENT)


def redact_payload(value: Any) -> Any:
    """Redact nested tool data using the shared credential policy.

    Tool results can be dictionaries/lists rather than a single error string.
    This traversal delegates to ``secret_redaction`` : la liste des motifs est
    figée en un seul endroit et testée d'un bloc.
    """
    return _shared_redact_payload(value)


def _coerce_enum(enum_type: type[StrEnum], value: StrEnum | str, label: str) -> StrEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(item.value for item in enum_type)
        raise TaskQueueError(f"{label} invalide. Valeurs autorisées : {choices}.") from error


def _normalise_json(
    value: Any,
    *,
    label: str,
    depth: int = 0,
    string_limit: int = MAX_JSON_STRING_CHARS,
) -> JsonValue:
    """Return a JSON-safe, redacted value or reject unsupported/huge values."""

    if depth > MAX_JSON_DEPTH:
        raise TaskQueueError(f"{label} est trop profondément imbriqué.")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise TaskQueueError(f"{label} contient un nombre non valide.")
        return value
    if isinstance(value, str):
        safe = redact_text(value)
        if len(safe) > string_limit:
            raise TaskQueueError(f"{label} contient un texte trop long.")
        return safe
    if isinstance(value, Mapping):
        if len(value) > MAX_JSON_CONTAINER_ITEMS:
            raise TaskQueueError(f"{label} contient trop d’éléments.")
        normalised: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TaskQueueError(f"{label} contient une clé qui n’est pas du texte.")
            if _is_sensitive_key(key):
                normalised[key] = "[secret redacted]"
            else:
                normalised[key] = _normalise_json(
                    item,
                    label=label,
                    depth=depth + 1,
                    string_limit=string_limit,
                )
        return normalised
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_JSON_CONTAINER_ITEMS:
            raise TaskQueueError(f"{label} contient trop d’éléments.")
        return [
            _normalise_json(item, label=label, depth=depth + 1, string_limit=string_limit)
            for item in value
        ]
    raise TaskQueueError(f"{label} contient un type non pris en charge.")


def _prepare_json(
    value: Any,
    *,
    label: str,
    max_bytes: int,
    root_must_be_mapping: bool = False,
) -> tuple[JsonValue, str]:
    normalised = _normalise_json(value, label=label)
    if root_must_be_mapping and not isinstance(normalised, dict):
        raise TaskQueueError(f"{label} doit être un objet JSON.")
    encoded = json.dumps(normalised, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > max_bytes:
        raise TaskQueueError(
            f"{label} est trop volumineux pour la file locale. "
            "Enregistre le contenu dans l’espace de travail contrôlé et passe un identifiant opaque."
        )
    return normalised, encoded


def _safe_error(error: object) -> str:
    """Keep a compact explanation, never a traceback or an unredacted secret."""

    message = redact_text(error, limit=MAX_ERROR_CHARS)
    return message or "La tâche locale a échoué sans détail exploitable."


class TaskQueue:
    """SQLite-backed task ledger with explicit lifecycle methods only.

    Each public operation creates its own short-lived SQLite connection. This
    makes queue snapshots safe to read from a web request thread while a single
    ``TaskRunner`` writes progress from its worker thread.
    """

    def __init__(self, database_path: str | Path):
        path = Path(database_path).expanduser()
        if path.exists() and path.is_dir():
            raise TaskQueueError("Le chemin de la file locale désigne un dossier.")
        self.database_path = path.resolve()
        parent_existed = self.database_path.parent.exists()
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Never chmod an existing parent: it may be a user-owned project folder.
        if not parent_existed:
            try:
                os.chmod(self.database_path.parent, 0o700)
            except OSError:
                pass

        existed = self.database_path.exists()
        self._initialise()
        if not existed:
            try:
                os.chmod(self.database_path, 0o600)
            except OSError:
                pass
        self.recover_interrupted_tasks()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path), timeout=5.0, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialise(self) -> None:
        kinds = ", ".join(repr(kind.value) for kind in TaskKind)
        statuses = ", ".join(repr(status.value) for status in TaskStatus)
        levels = ", ".join(repr(level.value) for level in MessageLevel)
        connection = self._connect()
        try:
            # WAL permits responsive reads while a worker records progress.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS task_queue_tasks (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ({kinds})),
                    status TEXT NOT NULL CHECK (status IN ({statuses})),
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    error_text TEXT,
                    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
                    cancellation_requested INTEGER NOT NULL DEFAULT 0
                        CHECK (cancellation_requested IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS task_queue_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES task_queue_tasks(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL CHECK (level IN ({levels})),
                    text TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS task_queue_next_idx
                    ON task_queue_tasks(status, created_at, id);
                CREATE INDEX IF NOT EXISTS task_queue_messages_task_idx
                    ON task_queue_messages(task_id, id);
                """
            )
        finally:
            connection.close()

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a read connection and always close it after the snapshot."""

        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _validate_task_id(task_id: str) -> str:
        if not isinstance(task_id, str):
            raise TaskQueueError("Identifiant de tâche invalide.")
        try:
            return uuid.UUID(task_id).hex
        except (TypeError, ValueError, AttributeError) as error:
            raise TaskQueueError("Identifiant de tâche invalide.") from error

    @staticmethod
    def _decode_json(raw: str | None, *, field: str) -> JsonValue | None:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise TaskQueueError(f"La base locale contient un {field} illisible.") from error

    def _messages_for(self, connection: sqlite3.Connection, task_id: str) -> tuple[TaskMessage, ...]:
        rows = connection.execute(
            """
            SELECT created_at, level, text
            FROM task_queue_messages
            WHERE task_id = ?
            ORDER BY id ASC
            """,
            (task_id,),
        ).fetchall()
        return tuple(
            TaskMessage(
                created_at=row["created_at"],
                level=MessageLevel(row["level"]),
                text=row["text"],
            )
            for row in rows
        )

    def _record_from_row(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        include_messages: bool,
    ) -> TaskRecord:
        payload = self._decode_json(row["payload_json"], field="payload")
        if not isinstance(payload, dict):
            raise TaskQueueError("La base locale contient un payload invalide.")
        return TaskRecord(
            id=row["id"],
            kind=TaskKind(row["kind"]),
            status=TaskStatus(row["status"]),
            payload=payload,
            progress=int(row["progress"]),
            cancellation_requested=bool(row["cancellation_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            result=self._decode_json(row["result_json"], field="résultat"),
            error=row["error_text"],
            messages=self._messages_for(connection, row["id"]) if include_messages else (),
        )

    def _get_task_in_connection(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        *,
        include_messages: bool,
    ) -> TaskRecord:
        row = connection.execute(
            "SELECT * FROM task_queue_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFoundError("Tâche introuvable.")
        return self._record_from_row(connection, row, include_messages=include_messages)

    def _append_message_in_connection(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        text: object,
        level: MessageLevel,
    ) -> None:
        safe_text = redact_text(text, limit=MAX_MESSAGE_CHARS)
        connection.execute(
            """
            INSERT INTO task_queue_messages(task_id, created_at, level, text)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, _utc_now(), level.value, safe_text or "Mise à jour locale."),
        )
        # Keep only the newest bounded history for each task.
        connection.execute(
            """
            DELETE FROM task_queue_messages
            WHERE task_id = ? AND id IN (
                SELECT id FROM task_queue_messages
                WHERE task_id = ?
                ORDER BY id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (task_id, task_id, MAX_MESSAGES_PER_TASK),
        )

    def create_task(
        self, kind: TaskKind | str, payload: Mapping[str, Any]
    ) -> TaskRecord:
        """Persist a queued task. Only a typed kind and JSON object are accepted."""

        task_kind = _coerce_enum(TaskKind, kind, "Type de tâche")
        if not isinstance(payload, Mapping):
            raise TaskQueueError("Le payload de tâche doit être un objet JSON.")
        normalised_payload, payload_json = _prepare_json(
            dict(payload),
            label="Le payload de tâche",
            max_bytes=MAX_PAYLOAD_BYTES,
            root_must_be_mapping=True,
        )
        # ``normalised_payload`` is deliberately computed before the transaction:
        # bad user content never creates a partially persisted task.
        assert isinstance(normalised_payload, dict)
        task_id = uuid.uuid4().hex
        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO task_queue_tasks(
                    id, kind, status, payload_json, progress,
                    cancellation_requested, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    task_id,
                    task_kind.value,
                    TaskStatus.QUEUED.value,
                    payload_json,
                    now,
                    now,
                ),
            )
            self._append_message_in_connection(
                connection,
                task_id,
                "Tâche ajoutée à la file locale.",
                MessageLevel.INFO,
            )
            return self._get_task_in_connection(connection, task_id, include_messages=True)

    def get_task(self, task_id: str, *, include_messages: bool = True) -> TaskRecord:
        safe_id = self._validate_task_id(task_id)
        with self._read_connection() as connection:
            return self._get_task_in_connection(
                connection, safe_id, include_messages=include_messages
            )

    def list_tasks(
        self,
        *,
        status: TaskStatus | str | None = None,
        kind: TaskKind | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskRecord]:
        """List compact task snapshots; use ``get_task`` for their full messages."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_LIMIT:
            raise TaskQueueError(f"La limite doit être comprise entre 1 et {MAX_LIST_LIMIT}.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise TaskQueueError("Le décalage doit être un entier positif.")
        clauses: list[str] = []
        values: list[str | int] = []
        if status is not None:
            task_status = _coerce_enum(TaskStatus, status, "Statut")
            clauses.append("status = ?")
            values.append(task_status.value)
        if kind is not None:
            task_kind = _coerce_enum(TaskKind, kind, "Type de tâche")
            clauses.append("kind = ?")
            values.append(task_kind.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.extend((limit, offset))
        with self._read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM task_queue_tasks
                {where}
                ORDER BY rowid DESC
                LIMIT ? OFFSET ?
                """,
                values,
            ).fetchall()
            return [
                self._record_from_row(connection, row, include_messages=False)
                for row in rows
            ]

    def recover_interrupted_tasks(self) -> int:
        """Make tasks interrupted by a process restart eligible to run again.

        A queued job is already durable. A job which was running is requeued;
        one that had received a cancellation request is finalized as cancelled.
        Handlers must still be idempotent or use their own controlled resume
        markers before performing a non-idempotent file operation.
        """

        recovered = 0
        with self._transaction(immediate=True) as connection:
            rows = connection.execute(
                """
                SELECT id, status, cancellation_requested
                FROM task_queue_tasks
                WHERE status IN (?, ?)
                ORDER BY rowid ASC
                """,
                (TaskStatus.RUNNING.value, TaskStatus.CANCELLING.value),
            ).fetchall()
            for row in rows:
                now = _utc_now()
                if row["cancellation_requested"] or row["status"] == TaskStatus.CANCELLING.value:
                    connection.execute(
                        """
                        UPDATE task_queue_tasks
                        SET status = ?, cancellation_requested = 1,
                            updated_at = ?, finished_at = ?
                        WHERE id = ?
                        """,
                        (TaskStatus.CANCELLED.value, now, now, row["id"]),
                    )
                    self._append_message_in_connection(
                        connection,
                        row["id"],
                        "Annulation finalisée après le redémarrage de l’application.",
                        MessageLevel.WARNING,
                    )
                else:
                    connection.execute(
                        """
                        UPDATE task_queue_tasks
                        SET status = ?, started_at = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (TaskStatus.QUEUED.value, now, row["id"]),
                    )
                    self._append_message_in_connection(
                        connection,
                        row["id"],
                        "Exécution interrompue : tâche remise en attente après redémarrage.",
                        MessageLevel.WARNING,
                    )
                recovered += 1
        return recovered

    def claim_next(self) -> TaskRecord | None:
        """Atomically claim the oldest queued task for one registered worker."""

        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                """
                SELECT id FROM task_queue_tasks
                WHERE status = ?
                ORDER BY rowid ASC
                LIMIT 1
                """,
                (TaskStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None
            now = _utc_now()
            connection.execute(
                """
                UPDATE task_queue_tasks
                SET status = ?, started_at = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    now,
                    now,
                    row["id"],
                    TaskStatus.QUEUED.value,
                ),
            )
            self._append_message_in_connection(
                connection,
                row["id"],
                "Exécution locale démarrée.",
                MessageLevel.INFO,
            )
            return self._get_task_in_connection(connection, row["id"], include_messages=True)

    def request_cancel(self, task_id: str) -> TaskRecord:
        """Request cooperative cancellation; queued work is cancelled immediately."""

        safe_id = self._validate_task_id(task_id)
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status in TERMINAL_STATUSES:
                return current
            now = _utc_now()
            if current.status is TaskStatus.QUEUED:
                connection.execute(
                    """
                    UPDATE task_queue_tasks
                    SET status = ?, cancellation_requested = 1,
                        updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.CANCELLED.value, now, now, safe_id),
                )
                message = "Tâche annulée avant son démarrage."
            else:
                connection.execute(
                    """
                    UPDATE task_queue_tasks
                    SET status = ?, cancellation_requested = 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.CANCELLING.value, now, safe_id),
                )
                message = "Annulation demandée : l’outil local va s’arrêter à son prochain point de contrôle."
            self._append_message_in_connection(connection, safe_id, message, MessageLevel.WARNING)
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def is_cancellation_requested(self, task_id: str) -> bool:
        safe_id = self._validate_task_id(task_id)
        with self._read_connection() as connection:
            record = self._get_task_in_connection(connection, safe_id, include_messages=False)
            return record.cancellation_requested or record.status in {
                TaskStatus.CANCELLING,
                TaskStatus.CANCELLED,
            }

    def append_message(
        self,
        task_id: str,
        text: object,
        *,
        level: MessageLevel | str = MessageLevel.INFO,
    ) -> TaskRecord:
        safe_id = self._validate_task_id(task_id)
        message_level = _coerce_enum(MessageLevel, level, "Niveau de message")
        with self._transaction(immediate=True) as connection:
            self._get_task_in_connection(connection, safe_id, include_messages=False)
            self._append_message_in_connection(connection, safe_id, text, message_level)
            connection.execute(
                "UPDATE task_queue_tasks SET updated_at = ? WHERE id = ?",
                (_utc_now(), safe_id),
            )
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def update_progress(
        self,
        task_id: str,
        progress: int,
        *,
        message: object | None = None,
        level: MessageLevel | str = MessageLevel.INFO,
    ) -> TaskRecord:
        """Store monotonic progress for a running task and an optional message."""

        safe_id = self._validate_task_id(task_id)
        if isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= 100:
            raise TaskQueueError("La progression doit être un entier compris entre 0 et 100.")
        message_level = _coerce_enum(MessageLevel, level, "Niveau de message")
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status not in {TaskStatus.RUNNING, TaskStatus.CANCELLING}:
                raise InvalidTaskStateError("La progression ne peut être mise à jour que pendant l’exécution.")
            now = _utc_now()
            connection.execute(
                "UPDATE task_queue_tasks SET progress = ?, updated_at = ? WHERE id = ?",
                (max(current.progress, progress), now, safe_id),
            )
            if message is not None:
                self._append_message_in_connection(connection, safe_id, message, message_level)
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def finish_success(self, task_id: str, result: Any = None) -> TaskRecord:
        """Finish a running task, unless cancellation won the race."""

        safe_id = self._validate_task_id(task_id)
        _normalised_result, result_json = _prepare_json(
            result,
            label="Le résultat de tâche",
            max_bytes=MAX_RESULT_BYTES,
        )
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status not in {TaskStatus.RUNNING, TaskStatus.CANCELLING}:
                raise InvalidTaskStateError("Seule une tâche en cours peut être terminée.")
            now = _utc_now()
            if current.cancellation_requested or current.status is TaskStatus.CANCELLING:
                connection.execute(
                    """
                    UPDATE task_queue_tasks
                    SET status = ?, cancellation_requested = 1,
                        updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.CANCELLED.value, now, now, safe_id),
                )
                self._append_message_in_connection(
                    connection,
                    safe_id,
                    "Résultat ignoré : l’annulation a été demandée avant la fin de la tâche.",
                    MessageLevel.WARNING,
                )
            else:
                connection.execute(
                    """
                    UPDATE task_queue_tasks
                    SET status = ?, progress = 100, result_json = ?, error_text = NULL,
                        updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.SUCCEEDED.value, result_json, now, now, safe_id),
                )
                self._append_message_in_connection(
                    connection,
                    safe_id,
                    "Tâche locale terminée.",
                    MessageLevel.INFO,
                )
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def finish_failed(self, task_id: str, error: object) -> TaskRecord:
        """Finish a running task with a bounded, redacted error explanation."""

        safe_id = self._validate_task_id(task_id)
        safe_error = _safe_error(error)
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status not in {TaskStatus.RUNNING, TaskStatus.CANCELLING}:
                raise InvalidTaskStateError("Seule une tâche en cours peut échouer.")
            now = _utc_now()
            if current.cancellation_requested or current.status is TaskStatus.CANCELLING:
                connection.execute(
                    """
                    UPDATE task_queue_tasks
                    SET status = ?, cancellation_requested = 1,
                        updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.CANCELLED.value, now, now, safe_id),
                )
                self._append_message_in_connection(
                    connection,
                    safe_id,
                    "Annulation finalisée pendant l’arrêt de l’outil local.",
                    MessageLevel.WARNING,
                )
            else:
                connection.execute(
                    """
                    UPDATE task_queue_tasks
                    SET status = ?, error_text = ?, updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.FAILED.value, safe_error, now, now, safe_id),
                )
                self._append_message_in_connection(connection, safe_id, safe_error, MessageLevel.ERROR)
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def finish_cancelled(self, task_id: str, *, message: object | None = None) -> TaskRecord:
        """Finalize cooperative cancellation for a queued/running task."""

        safe_id = self._validate_task_id(task_id)
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
                raise InvalidTaskStateError("Une tâche déjà terminée ne peut plus être annulée.")
            if current.status is TaskStatus.CANCELLED:
                return current
            now = _utc_now()
            connection.execute(
                """
                UPDATE task_queue_tasks
                SET status = ?, cancellation_requested = 1,
                    updated_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (TaskStatus.CANCELLED.value, now, now, safe_id),
            )
            self._append_message_in_connection(
                connection,
                safe_id,
                message or "Tâche annulée de manière coopérative.",
                MessageLevel.WARNING,
            )
            return self._get_task_in_connection(connection, safe_id, include_messages=True)


class TaskExecutionContext:
    """Minimal capability passed to a registered background task handler."""

    def __init__(self, queue: TaskQueue, task_id: str):
        self._queue = queue
        self.task_id = task_id

    def is_cancellation_requested(self) -> bool:
        return self._queue.is_cancellation_requested(self.task_id)

    def checkpoint(self) -> None:
        """Stop safely if the user has requested cancellation."""

        if self.is_cancellation_requested():
            raise TaskCancelled("Annulation demandée.")

    def set_progress(
        self,
        progress: int,
        message: object | None = None,
        *,
        level: MessageLevel | str = MessageLevel.INFO,
    ) -> TaskRecord:
        self.checkpoint()
        return self._queue.update_progress(
            self.task_id, progress, message=message, level=level
        )

    def message(
        self, text: object, *, level: MessageLevel | str = MessageLevel.INFO
    ) -> TaskRecord:
        self.checkpoint()
        return self._queue.append_message(self.task_id, text, level=level)


TaskHandler: TypeAlias = Callable[[TaskExecutionContext, Mapping[str, JsonValue]], Any]


class TaskRunner:
    """Single local worker dispatching only handlers registered in application code.

    The runner deliberately has no facility for dynamic imports, shell commands,
    Python snippets, URLs, or provider calls. A future module can register a
    narrow handler for one ``TaskKind`` and retain validation of its opaque IDs.
    """

    def __init__(
        self,
        queue: TaskQueue,
        handlers: Mapping[TaskKind | str, TaskHandler],
        *,
        poll_interval_seconds: float = 0.25,
    ):
        if not 0.05 <= poll_interval_seconds <= 5.0:
            raise TaskQueueError("L’intervalle de surveillance doit être compris entre 0,05 et 5 secondes.")
        registered: dict[TaskKind, TaskHandler] = {}
        for raw_kind, handler in handlers.items():
            kind = _coerce_enum(TaskKind, raw_kind, "Type de gestionnaire")
            if not callable(handler):
                raise TaskQueueError("Chaque gestionnaire de tâche doit être appelable.")
            registered[kind] = handler
        self.queue = queue
        self._handlers = registered
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._active_task_id: str | None = None
        self._last_worker_error: str | None = None

    @property
    def active_task_id(self) -> str | None:
        with self._state_lock:
            return self._active_task_id

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def last_worker_error(self) -> str | None:
        """A redacted scheduler-level error, if the worker itself could not run."""

        with self._state_lock:
            return self._last_worker_error

    def start(self) -> None:
        """Start one daemon worker. Calling this twice is harmless."""

        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="come-ai-task-runner",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, wait: bool = True, timeout: float = 5.0, cancel_active: bool = False) -> None:
        """Ask the worker to stop polling; optional cancellation remains cooperative."""

        if timeout < 0:
            raise TaskQueueError("Le délai d’arrêt ne peut pas être négatif.")
        if cancel_active:
            active_id = self.active_task_id
            if active_id is not None:
                self.queue.request_cancel(active_id)
        self._stop_event.set()
        self._wake_event.set()
        with self._state_lock:
            thread = self._thread
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def submit(self, kind: TaskKind | str, payload: Mapping[str, Any]) -> TaskRecord:
        """Create a task and wake the worker; execution still needs registered code."""

        task = self.queue.create_task(kind, payload)
        self._wake_event.set()
        return task

    def cancel(self, task_id: str) -> TaskRecord:
        task = self.queue.request_cancel(task_id)
        self._wake_event.set()
        return task

    def run_once(self) -> TaskRecord | None:
        """Synchronously execute at most one queued job (useful for deterministic tests)."""

        task = self.queue.claim_next()
        if task is None:
            return None
        with self._state_lock:
            self._active_task_id = task.id
        try:
            handler = self._handlers.get(task.kind)
            if handler is None:
                return self.queue.finish_failed(
                    task.id,
                    f"Aucun gestionnaire local autorisé pour « {task.kind.value} ».",
                )
            context = TaskExecutionContext(self.queue, task.id)
            try:
                context.checkpoint()
                result = handler(context, task.payload)
                context.checkpoint()
                return self.queue.finish_success(task.id, result)
            except TaskCancelled:
                return self.queue.finish_cancelled(task.id)
            except Exception as error:  # handlers are application-owned but can still fail.
                if self.queue.is_cancellation_requested(task.id):
                    return self.queue.finish_cancelled(
                        task.id,
                        message="Tâche arrêtée après une demande d’annulation.",
                    )
                return self.queue.finish_failed(task.id, error)
        finally:
            with self._state_lock:
                self._active_task_id = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                completed = self.run_once()
            except Exception as error:
                # A database-level failure must not spin a CPU. Individual
                # handler failures are persisted by ``run_once`` above.
                with self._state_lock:
                    self._last_worker_error = _safe_error(error)
                completed = None
            if completed is None:
                self._wake_event.wait(self._poll_interval_seconds)
                self._wake_event.clear()

