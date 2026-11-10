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

import hashlib
import json
import os
import sqlite3
import stat
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeAlias
from zoneinfo import ZoneInfo

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
MAX_TASK_ATTEMPTS = 3
MAX_IDEMPOTENCY_KEY_BYTES = 128
MAX_JSON_DEPTH = 8
MAX_JSON_CONTAINER_ITEMS = 256
MAX_JSON_STRING_CHARS = 16_000
MAX_LIST_LIMIT = 100
MIN_SCHEDULE_INTERVAL_SECONDS = 60
MAX_SCHEDULE_INTERVAL_SECONDS = 90 * 24 * 60 * 60

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


class TaskIdempotencyConflictError(TaskQueueError):
    """Raised when a request key is reused with different task content."""


class InvalidTaskStateError(TaskQueueError):
    """Raised when a lifecycle operation is not valid for a task state."""


class TaskCancelled(TaskQueueError):
    """Raised by a handler at a cooperative cancellation checkpoint."""


class TaskExecutionFailure(TaskQueueError):
    """A handler failure that can retain a bounded, user-visible partial result."""

    def __init__(self, message: str, *, partial_result: Any = None) -> None:
        super().__init__(message)
        self.partial_result = partial_result


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


class TaskScheduleStatus(StrEnum):
    """Lifecycle for a recurring local schedule."""

    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


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
    scheduled_for: str | None
    attempt_count: int
    started_at: str | None
    finished_at: str | None
    result: JsonValue | None
    error: str | None
    schedule_id: str | None = None
    schedule_occurrence: int | None = None
    messages: tuple[TaskMessage, ...] = ()

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass(frozen=True, slots=True)
class TaskScheduleRecord:
    """Persistent recurring schedule metadata; payload remains server-side."""

    id: str
    status: TaskScheduleStatus
    interval_seconds: int
    next_run_at: str
    created_at: str
    updated_at: str
    occurrence_count: int
    last_task_id: str | None
    payload: dict[str, JsonValue]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_scheduled_for(value: datetime | str | None) -> str | None:
    """Return a timezone-aware instant as a stable UTC ISO timestamp."""

    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise TaskQueueError("L’heure programmée doit être une date ISO valide avec fuseau horaire.") from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TaskQueueError("L’heure programmée doit inclure un fuseau horaire.")
    instant = value.astimezone(timezone.utc)
    if isinstance(value.tzinfo, ZoneInfo):
        local_round_trip = instant.astimezone(value.tzinfo)
        if local_round_trip.replace(fold=value.fold) != value:
            raise TaskQueueError(
                "L’heure programmée correspond à une heure locale inexistante."
            )
    return instant.isoformat(timespec="microseconds")


def _next_future_interval(
    scheduled_for: datetime | str,
    interval_seconds: int,
    now: datetime | str,
) -> str:
    """Coalesce missed occurrences and return the first strictly future tick."""

    scheduled_at = datetime.fromisoformat(_normalise_scheduled_for(scheduled_for) or "")
    current_time = datetime.fromisoformat(_normalise_scheduled_for(now) or "")
    if scheduled_at > current_time:
        return scheduled_at.isoformat(timespec="microseconds")
    elapsed = (current_time - scheduled_at).total_seconds()
    periods = int(elapsed // interval_seconds) + 1
    return (scheduled_at + timedelta(seconds=periods * interval_seconds)).isoformat(
        timespec="microseconds"
    )


def _hash_idempotency_key(value: str | None) -> str | None:
    """Hash an opaque request key without persisting the caller's raw token."""

    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_IDEMPOTENCY_KEY_BYTES
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise TaskQueueError(
            f"La clé d’idempotence doit contenir de 1 à {MAX_IDEMPOTENCY_KEY_BYTES} caractères ASCII visibles."
        )
    return hashlib.sha256(value.encode("ascii")).hexdigest()


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
        requested_path = Path(database_path).expanduser()
        if not requested_path.name:
            raise TaskQueueError("Le chemin de la file locale doit désigner un fichier.")
        parent_existed = requested_path.parent.exists()
        parent = requested_path.parent.resolve()
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Never chmod an existing parent: it may be a user-owned project folder.
        if not parent_existed:
            try:
                os.chmod(parent, 0o700)
            except OSError:
                pass
        # Resolve parent symlinks deliberately, but keep the final filename
        # unresolved so validation and open can reject a swapped symlink.
        self.database_path = parent / requested_path.name

        try:
            metadata = self.database_path.lstat()
        except FileNotFoundError:
            metadata = None
        expected_metadata = metadata
        if metadata is not None:
            if not stat.S_ISREG(metadata.st_mode):
                raise TaskQueueError(
                    "Le chemin de la file locale doit désigner un fichier ordinaire, pas un lien symbolique."
                )
            if metadata.st_nlink != 1:
                raise TaskQueueError(
                    "La base de la file locale ne peut pas être un lien physique vers un autre nom."
                )
            self._protect_existing_database(metadata)
        else:
            # Create atomically with private permissions before SQLite opens
            # the path. O_EXCL also avoids clobbering an entry created by a
            # concurrent initializer.
            try:
                descriptor = os.open(
                    self.database_path,
                    os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                try:
                    concurrent_metadata = self.database_path.lstat()
                except OSError as error:
                    raise TaskQueueError(
                        "Le chemin de la file locale a changé pendant son initialisation."
                    ) from error
                if not stat.S_ISREG(concurrent_metadata.st_mode):
                    raise TaskQueueError(
                        "Le chemin de la file locale doit désigner un fichier ordinaire, pas un lien symbolique."
                    )
                self._protect_existing_database(concurrent_metadata)
                expected_metadata = concurrent_metadata
            else:
                try:
                    os.fchmod(descriptor, 0o600)
                    expected_metadata = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
        if expected_metadata is None:
            raise TaskQueueError("Le fichier de la file locale n’a pas pu être initialisé.")
        self._database_identity = (expected_metadata.st_dev, expected_metadata.st_ino)
        self._initialise()
        self.recover_interrupted_tasks()

    def _verify_database_identity(self) -> None:
        """Reject a database path replaced after queue initialization."""

        try:
            descriptor = os.open(
                self.database_path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as error:
            raise TaskQueueError(
                "Le chemin de la file locale a changé depuis son initialisation."
            ) from error
        try:
            opened = os.fstat(descriptor)
            try:
                current = self.database_path.lstat()
            except OSError as error:
                raise TaskQueueError(
                    "Le chemin de la file locale a changé pendant sa vérification."
                ) from error
            identity_matches = (opened.st_dev, opened.st_ino) == self._database_identity
            path_matches = (current.st_dev, current.st_ino) == self._database_identity
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or opened.st_nlink != 1
                or current.st_nlink != 1
                or not identity_matches
                or not path_matches
            ):
                raise TaskQueueError(
                    "Le chemin de la file locale a changé depuis son initialisation."
                )
        finally:
            os.close(descriptor)

    def _protect_existing_database(self, expected: os.stat_result) -> None:
        """Protect an existing regular file without following a path swap."""

        try:
            descriptor = os.open(
                self.database_path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as error:
            raise TaskQueueError(
                "Le chemin de la file locale a changé ou n’est pas accessible."
            ) from error
        try:
            opened = os.fstat(descriptor)
            try:
                current = self.database_path.lstat()
            except OSError as error:
                raise TaskQueueError(
                    "Le chemin de la file locale a changé pendant sa vérification."
                ) from error
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or opened.st_nlink != 1
                or current.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise TaskQueueError(
                    "Le chemin de la file locale a changé pendant sa vérification."
                )
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            else:
                os.chmod(self.database_path, 0o600)
        finally:
            os.close(descriptor)

    def _connect(self) -> sqlite3.Connection:
        self._verify_database_identity()
        connection = sqlite3.connect(
            str(self.database_path), timeout=5.0, isolation_level=None
        )
        try:
            self._verify_database_identity()
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            return connection
        except BaseException:
            connection.close()
            raise

    def _initialise(self) -> None:
        kinds = ", ".join(repr(kind.value) for kind in TaskKind)
        statuses = ", ".join(repr(status.value) for status in TaskStatus)
        schedule_statuses = ", ".join(repr(status.value) for status in TaskScheduleStatus)
        levels = ", ".join(repr(level.value) for level in MessageLevel)
        connection = self._connect()
        try:
            # WAL permits responsive reads while a worker records progress.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS task_queue_schedules (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK (status IN ({schedule_statuses})),
                    payload_json TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL
                        CHECK (interval_seconds BETWEEN {MIN_SCHEDULE_INTERVAL_SECONDS} AND {MAX_SCHEDULE_INTERVAL_SECONDS}),
                    first_run_at TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    idempotency_key_hash TEXT
                );

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
                    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    requested_scheduled_for TEXT,
                    scheduled_for TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    idempotency_key_hash TEXT,
                    schedule_id TEXT REFERENCES task_queue_schedules(id),
                    schedule_occurrence INTEGER CHECK (schedule_occurrence IS NULL OR schedule_occurrence >= 1)
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
            # Existing local databases are upgraded additively. Keep this
            # after table creation so old databases do not fail while creating
            # an index that references a column they do not have yet.
            connection.execute("BEGIN IMMEDIATE")
            try:
                schedule_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(task_queue_schedules)"
                    )
                }
                if "idempotency_key_hash" not in schedule_columns:
                    connection.execute(
                        "ALTER TABLE task_queue_schedules ADD COLUMN idempotency_key_hash TEXT"
                    )
                if "first_run_at" not in schedule_columns:
                    connection.execute(
                        "ALTER TABLE task_queue_schedules ADD COLUMN first_run_at TEXT"
                    )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(task_queue_tasks)")
                }
                if "scheduled_for" not in columns:
                    connection.execute(
                        "ALTER TABLE task_queue_tasks ADD COLUMN scheduled_for TEXT"
                    )
                if "requested_scheduled_for" not in columns:
                    connection.execute(
                        "ALTER TABLE task_queue_tasks ADD COLUMN requested_scheduled_for TEXT"
                    )
                if "attempt_count" not in columns:
                    connection.execute(
                        "ALTER TABLE task_queue_tasks ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0)"
                    )
                if "idempotency_key_hash" not in columns:
                    connection.execute(
                        "ALTER TABLE task_queue_tasks ADD COLUMN idempotency_key_hash TEXT"
                    )
                if "schedule_id" not in columns:
                    connection.execute(
                        "ALTER TABLE task_queue_tasks ADD COLUMN schedule_id TEXT REFERENCES task_queue_schedules(id)"
                    )
                if "schedule_occurrence" not in columns:
                    connection.execute(
                        "ALTER TABLE task_queue_tasks ADD COLUMN schedule_occurrence INTEGER"
                    )
                connection.execute(
                    """UPDATE task_queue_tasks
                       SET requested_scheduled_for = scheduled_for
                       WHERE requested_scheduled_for IS NULL"""
                )
                connection.execute(
                    """UPDATE task_queue_schedules
                       SET first_run_at = COALESCE(
                           (SELECT scheduled_for FROM task_queue_tasks
                            WHERE task_queue_tasks.schedule_id = task_queue_schedules.id
                              AND task_queue_tasks.schedule_occurrence = 1
                            ORDER BY task_queue_tasks.rowid ASC LIMIT 1),
                           next_run_at
                       )
                       WHERE first_run_at IS NULL"""
                )
                connection.execute(
                    """CREATE INDEX IF NOT EXISTS task_queue_schedule_idx
                       ON task_queue_tasks(status, scheduled_for, created_at)"""
                )
                connection.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS task_queue_idempotency_idx
                       ON task_queue_tasks(idempotency_key_hash)
                       WHERE idempotency_key_hash IS NOT NULL"""
                )
                connection.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS task_queue_schedule_idempotency_idx
                       ON task_queue_schedules(idempotency_key_hash)
                       WHERE idempotency_key_hash IS NOT NULL"""
                )
                connection.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS task_queue_schedule_occurrence_idx
                       ON task_queue_tasks(schedule_id, schedule_occurrence)
                       WHERE schedule_id IS NOT NULL"""
                )
                active_statuses = ", ".join(repr(status.value) for status in ACTIVE_STATUSES)
                connection.execute(
                    f"""CREATE UNIQUE INDEX IF NOT EXISTS task_queue_schedule_active_idx
                       ON task_queue_tasks(schedule_id)
                       WHERE schedule_id IS NOT NULL AND status IN ({active_statuses})"""
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
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
        status = TaskStatus(row["status"])
        try:
            payload = self._decode_json(row["payload_json"], field="payload")
            if not isinstance(payload, dict):
                raise TaskQueueError("La base locale contient un payload invalide.")
        except TaskQueueError:
            if status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
                raise
            # A malformed interrupted task must remain visible for review; it
            # has already been marked terminal and cannot be dispatched again.
            payload = {}
        return TaskRecord(
            id=row["id"],
            kind=TaskKind(row["kind"]),
            status=status,
            payload=payload,
            progress=int(row["progress"]),
            cancellation_requested=bool(row["cancellation_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            scheduled_for=row["scheduled_for"],
            attempt_count=int(row["attempt_count"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            result=self._decode_json(row["result_json"], field="résultat"),
            error=row["error_text"],
            schedule_id=row["schedule_id"],
            schedule_occurrence=row["schedule_occurrence"],
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

    def _schedule_from_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> TaskScheduleRecord:
        payload = self._decode_json(row["payload_json"], field="plan récurrent")
        if not isinstance(payload, dict):
            raise TaskQueueError("La base locale contient un plan récurrent invalide.")
        counts = connection.execute(
            """SELECT COUNT(*) AS occurrence_count,
                      (SELECT id FROM task_queue_tasks WHERE schedule_id = ?
                       ORDER BY schedule_occurrence DESC LIMIT 1) AS last_task_id
               FROM task_queue_tasks WHERE schedule_id = ?""",
            (row["id"], row["id"]),
        ).fetchone()
        return TaskScheduleRecord(
            id=row["id"],
            status=TaskScheduleStatus(row["status"]),
            interval_seconds=int(row["interval_seconds"]),
            next_run_at=row["next_run_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            occurrence_count=int(counts["occurrence_count"]),
            last_task_id=counts["last_task_id"],
            payload=payload,
        )

    def _get_schedule_in_connection(
        self, connection: sqlite3.Connection, schedule_id: str
    ) -> TaskScheduleRecord:
        row = connection.execute(
            "SELECT * FROM task_queue_schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFoundError("Planning récurrent introuvable.")
        return self._schedule_from_row(connection, row)

    def create_schedule(
        self,
        kind: TaskKind | str,
        payload: Mapping[str, Any],
        *,
        first_run_at: datetime | str,
        interval_seconds: int,
        now: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> TaskScheduleRecord:
        """Create a recurring schedule for a validated, read-only V5 plan."""

        task_kind = _coerce_enum(TaskKind, kind, "Type de tâche")
        if task_kind is not TaskKind.ORCHESTRATOR_PLAN:
            raise TaskQueueError("La récurrence est réservée aux plans V5 en lecture seule.")
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int):
            raise TaskQueueError("L’intervalle doit être un nombre entier de secondes.")
        if not MIN_SCHEDULE_INTERVAL_SECONDS <= interval_seconds <= MAX_SCHEDULE_INTERVAL_SECONDS:
            raise TaskQueueError(
                f"L’intervalle doit être compris entre {MIN_SCHEDULE_INTERVAL_SECONDS} secondes et 90 jours."
            )
        if not isinstance(payload, Mapping):
            raise TaskQueueError("Le payload de tâche doit être un objet JSON.")
        source = dict(payload)
        if source.get("allow_write") is not False:
            raise TaskQueueError("Un planning récurrent ne peut pas autoriser une écriture.")
        if not isinstance(source.get("message"), str) or not source["message"].strip():
            raise TaskQueueError("Un objectif V5 non vide est requis.")
        source.setdefault("selected_file_ids", [])
        selected_file_ids = source.get("selected_file_ids", [])
        if (
            not isinstance(selected_file_ids, list)
            or len(selected_file_ids) > 4
            or any(
                not isinstance(file_id, str)
                or not file_id.strip()
                or len(file_id) > 128
                for file_id in selected_file_ids
            )
        ):
            raise TaskQueueError("La sélection de fichiers V5 est invalide.")
        memory_project_id = source.get("memory_project_id")
        if memory_project_id is not None and (
            not isinstance(memory_project_id, str) or len(memory_project_id) > 48
        ):
            raise TaskQueueError("Le projet de mémoire V5 est invalide.")
        first_due = _normalise_scheduled_for(first_run_at)
        assert first_due is not None
        current_time = _normalise_scheduled_for(now or datetime.now(timezone.utc))
        assert current_time is not None
        _normalised_payload, payload_json = _prepare_json(
            source,
            label="Le payload du planning",
            max_bytes=MAX_PAYLOAD_BYTES,
            root_must_be_mapping=True,
        )
        assert isinstance(_normalised_payload, dict)
        key_hash = _hash_idempotency_key(idempotency_key)
        comparable_payload_json = json.dumps(
            _normalised_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        now_text = _utc_now()
        with self._transaction(immediate=True) as connection:
            if key_hash is not None:
                existing = connection.execute(
                    """SELECT id, payload_json, interval_seconds, first_run_at
                       FROM task_queue_schedules
                       WHERE idempotency_key_hash = ?""",
                    (key_hash,),
                ).fetchone()
                if existing is not None:
                    existing_payload_json = json.dumps(
                        json.loads(existing["payload_json"]),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                        allow_nan=False,
                    )
                    if (
                        existing_payload_json != comparable_payload_json
                        or int(existing["interval_seconds"]) != interval_seconds
                        or existing["first_run_at"] != first_due
                    ):
                        raise TaskIdempotencyConflictError(
                            "La clé d’idempotence a déjà servi pour un autre planning."
                        )
                    return self._get_schedule_in_connection(
                        connection, existing["id"]
                    )

            if first_due <= current_time:
                raise TaskQueueError("Le premier lancement doit rester dans le futur.")

            schedule_id = uuid.uuid4().hex
            connection.execute(
                """INSERT INTO task_queue_schedules(
                       id, status, payload_json, interval_seconds, first_run_at,
                       next_run_at, created_at, updated_at, idempotency_key_hash
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    schedule_id,
                    TaskScheduleStatus.ACTIVE.value,
                    payload_json,
                    interval_seconds,
                    first_due,
                    first_due,
                    now_text,
                    now_text,
                    key_hash,
                ),
            )
            return self._get_schedule_in_connection(connection, schedule_id)

    def get_schedule(self, schedule_id: str) -> TaskScheduleRecord:
        safe_id = self._validate_task_id(schedule_id)
        with self._read_connection() as connection:
            return self._get_schedule_in_connection(connection, safe_id)

    def list_schedules(
        self,
        *,
        status: TaskScheduleStatus | str | None = None,
        limit: int = 50,
    ) -> list[TaskScheduleRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_LIMIT:
            raise TaskQueueError(f"La limite doit être comprise entre 1 et {MAX_LIST_LIMIT}.")
        clauses: list[str] = []
        values: list[str | int] = []
        if status is not None:
            schedule_status = _coerce_enum(TaskScheduleStatus, status, "Statut de planning")
            clauses.append("status = ?")
            values.append(schedule_status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self._read_connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM task_queue_schedules {where} ORDER BY created_at DESC LIMIT ?",
                values,
            ).fetchall()
            return [self._schedule_from_row(connection, row) for row in rows]

    def pause_schedule(self, schedule_id: str) -> TaskScheduleRecord:
        safe_id = self._validate_task_id(schedule_id)
        with self._transaction(immediate=True) as connection:
            current = self._get_schedule_in_connection(connection, safe_id)
            if current.status is TaskScheduleStatus.CANCELLED:
                raise InvalidTaskStateError("Un planning annulé ne peut pas être mis en pause.")
            if current.status is TaskScheduleStatus.PAUSED:
                return current
            connection.execute(
                "UPDATE task_queue_schedules SET status = ?, updated_at = ? WHERE id = ?",
                (TaskScheduleStatus.PAUSED.value, _utc_now(), safe_id),
            )
            return self._get_schedule_in_connection(connection, safe_id)

    def resume_schedule(
        self, schedule_id: str, *, now: datetime | None = None
    ) -> TaskScheduleRecord:
        safe_id = self._validate_task_id(schedule_id)
        now_text = _normalise_scheduled_for(now or datetime.now(timezone.utc))
        assert now_text is not None
        with self._transaction(immediate=True) as connection:
            current = self._get_schedule_in_connection(connection, safe_id)
            if current.status is TaskScheduleStatus.CANCELLED:
                raise InvalidTaskStateError("Un planning annulé ne peut pas être repris.")
            if current.status is TaskScheduleStatus.ACTIVE:
                return current
            next_due = _next_future_interval(
                current.next_run_at, current.interval_seconds, now_text
            )
            connection.execute(
                """UPDATE task_queue_schedules
                   SET status = ?, next_run_at = ?, updated_at = ? WHERE id = ?""",
                (TaskScheduleStatus.ACTIVE.value, next_due, _utc_now(), safe_id),
            )
            return self._get_schedule_in_connection(connection, safe_id)

    def cancel_schedule(self, schedule_id: str) -> TaskScheduleRecord:
        safe_id = self._validate_task_id(schedule_id)
        with self._transaction(immediate=True) as connection:
            current = self._get_schedule_in_connection(connection, safe_id)
            if current.status is TaskScheduleStatus.CANCELLED:
                return current
            now_text = _utc_now()
            connection.execute(
                "UPDATE task_queue_schedules SET status = ?, updated_at = ? WHERE id = ?",
                (TaskScheduleStatus.CANCELLED.value, now_text, safe_id),
            )
            active_task = connection.execute(
                """SELECT id, status FROM task_queue_tasks
                   WHERE schedule_id = ? AND status IN (?, ?, ?)
                   ORDER BY schedule_occurrence DESC LIMIT 1""",
                (
                    safe_id,
                    TaskStatus.QUEUED.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.CANCELLING.value,
                ),
            ).fetchone()
            if active_task is not None:
                self._request_cancel_in_connection(connection, active_task["id"])
            return self._get_schedule_in_connection(connection, safe_id)

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

    def _request_cancel_in_connection(
        self, connection: sqlite3.Connection, task_id: str
    ) -> None:
        row = connection.execute(
            "SELECT status, schedule_id FROM task_queue_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None or row["status"] not in {status.value for status in ACTIVE_STATUSES}:
            return
        now = _utc_now()
        if row["status"] == TaskStatus.QUEUED.value:
            connection.execute(
                """UPDATE task_queue_tasks SET status = ?, cancellation_requested = 1,
                   updated_at = ?, finished_at = ? WHERE id = ?""",
                (TaskStatus.CANCELLED.value, now, now, task_id),
            )
            message = "Tâche annulée avant son démarrage."
        else:
            connection.execute(
                """UPDATE task_queue_tasks SET status = ?, cancellation_requested = 1,
                   updated_at = ? WHERE id = ?""",
                (TaskStatus.CANCELLING.value, now, task_id),
            )
            message = "Annulation demandée : l’outil local va s’arrêter à son prochain point de contrôle."
        self._append_message_in_connection(
            connection, task_id, message, MessageLevel.WARNING
        )
        if row["schedule_id"] is not None:
            connection.execute(
                """UPDATE task_queue_schedules SET status = ?, updated_at = ?
                   WHERE id = ? AND status = ?""",
                (
                    TaskScheduleStatus.PAUSED.value,
                    now,
                    row["schedule_id"],
                    TaskScheduleStatus.ACTIVE.value,
                ),
            )

    def _pause_schedule_for_task_in_connection(
        self, connection: sqlite3.Connection, task_id: str, now: str
    ) -> None:
        row = connection.execute(
            "SELECT schedule_id FROM task_queue_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is not None and row["schedule_id"] is not None:
            connection.execute(
                """UPDATE task_queue_schedules SET status = ?, updated_at = ?
                   WHERE id = ? AND status = ?""",
                (
                    TaskScheduleStatus.PAUSED.value,
                    now,
                    row["schedule_id"],
                    TaskScheduleStatus.ACTIVE.value,
                ),
            )

    def _advance_schedule_after_success_in_connection(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        finished_at: str,
    ) -> None:
        task = connection.execute(
            "SELECT schedule_id, scheduled_for FROM task_queue_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if task is None or task["schedule_id"] is None or task["scheduled_for"] is None:
            return
        schedule = connection.execute(
            "SELECT status, interval_seconds FROM task_queue_schedules WHERE id = ?",
            (task["schedule_id"],),
        ).fetchone()
        if schedule is None or schedule["status"] != TaskScheduleStatus.ACTIVE.value:
            return
        next_due = _next_future_interval(
            task["scheduled_for"], int(schedule["interval_seconds"]), finished_at
        )
        connection.execute(
            """UPDATE task_queue_schedules SET next_run_at = ?, updated_at = ?
               WHERE id = ? AND status = ?""",
            (
                next_due,
                _utc_now(),
                task["schedule_id"],
                TaskScheduleStatus.ACTIVE.value,
            ),
        )

    def _materialize_due_schedules_in_connection(
        self, connection: sqlite3.Connection, due_before: str
    ) -> None:
        schedules = connection.execute(
            """SELECT id, payload_json, next_run_at FROM task_queue_schedules
               WHERE status = ? AND next_run_at <= ? ORDER BY next_run_at, id""",
            (TaskScheduleStatus.ACTIVE.value, due_before),
        ).fetchall()
        for schedule in schedules:
            active = connection.execute(
                """SELECT 1 FROM task_queue_tasks
                   WHERE schedule_id = ? AND status IN (?, ?, ?) LIMIT 1""",
                (
                    schedule["id"],
                    TaskStatus.QUEUED.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.CANCELLING.value,
                ),
            ).fetchone()
            if active is not None:
                continue
            occurrence = int(
                connection.execute(
                    """SELECT COALESCE(MAX(schedule_occurrence), 0) + 1
                       FROM task_queue_tasks WHERE schedule_id = ?""",
                    (schedule["id"],),
                ).fetchone()[0]
            )
            payload = json.loads(schedule["payload_json"])
            task_id = uuid.uuid4().hex
            created_at = _utc_now()
            connection.execute(
                """INSERT INTO task_queue_tasks(
                       id, kind, status, payload_json, progress,
                       cancellation_requested, created_at, updated_at, scheduled_for,
                       schedule_id, schedule_occurrence
                   ) VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    TaskKind.ORCHESTRATOR_PLAN.value,
                    TaskStatus.QUEUED.value,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    created_at,
                    created_at,
                    schedule["next_run_at"],
                    schedule["id"],
                    occurrence,
                ),
            )
            self._append_message_in_connection(
                connection,
                task_id,
                f"Occurrence récurrente {occurrence} ajoutée à la file locale.",
                MessageLevel.INFO,
            )

    def create_task(
        self,
        kind: TaskKind | str,
        payload: Mapping[str, Any],
        *,
        scheduled_for: datetime | str | None = None,
        idempotency_key: str | None = None,
    ) -> TaskRecord:
        """Persist a queued task. Only a typed kind and JSON object are accepted."""

        task_kind = _coerce_enum(TaskKind, kind, "Type de tâche")
        scheduled_at = _normalise_scheduled_for(scheduled_for)
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
        key_hash = _hash_idempotency_key(idempotency_key)
        comparable_payload_json = json.dumps(
            normalised_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        task_id = uuid.uuid4().hex
        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            if key_hash is not None:
                existing = connection.execute(
                    """SELECT id, kind, payload_json, requested_scheduled_for
                       FROM task_queue_tasks
                       WHERE idempotency_key_hash = ?""",
                    (key_hash,),
                ).fetchone()
                if existing is not None:
                    existing_payload_json = json.dumps(
                        json.loads(existing["payload_json"]),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                        allow_nan=False,
                    )
                    if (
                        existing["kind"] != task_kind.value
                        or existing_payload_json != comparable_payload_json
                        or existing["requested_scheduled_for"] != scheduled_at
                    ):
                        raise TaskIdempotencyConflictError(
                            "La clé d’idempotence a déjà servi pour une autre demande."
                        )
                    return self._get_task_in_connection(
                        connection, existing["id"], include_messages=True
                    )
            connection.execute(
                """
                INSERT INTO task_queue_tasks(
                    id, kind, status, payload_json, progress,
                    cancellation_requested, created_at, updated_at,
                    requested_scheduled_for, scheduled_for, idempotency_key_hash
                ) VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task_kind.value,
                    TaskStatus.QUEUED.value,
                    payload_json,
                    now,
                    now,
                    scheduled_at,
                    scheduled_at,
                    key_hash,
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

    @staticmethod
    def _can_resume_interrupted_row(row: sqlite3.Row) -> bool:
        """Resume only handlers whose persisted payload is safe to replay."""

        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        if row["kind"] == TaskKind.MEMORY_INDEX.value:
            file_id = payload.get("file_id")
            source_id = payload.get("source_id")
            project_id = payload.get("project_id")
            # Accept task if it has file_id or source_id (for backwards compatibility)
            has_identifier = (isinstance(file_id, str) and bool(file_id.strip())) or                              (isinstance(source_id, str) and bool(source_id.strip()))
            return has_identifier and (project_id is None or isinstance(project_id, str))  # Content-hash import is idempotent.
        if row["kind"] != TaskKind.ORCHESTRATOR_PLAN.value:
            return False
        message = payload.get("message")
        selected_file_ids = payload.get("selected_file_ids")
        project_id = payload.get("memory_project_id")
        return (
            payload.get("allow_write") is False
            and isinstance(message, str)
            and bool(message.strip())
            and isinstance(selected_file_ids, list)
            and all(isinstance(file_id, str) for file_id in selected_file_ids)
            and (project_id is None or isinstance(project_id, str))
        )

    def recover_interrupted_tasks(self) -> int:
        """Make tasks interrupted by a process restart eligible to run again.

        Only explicitly safe-to-replay handlers are requeued. A write-enabled,
        malformed, or unknown task is failed for review rather than replayed
        after an uncertain side effect. Cancellation always takes precedence.
        """

        recovered = 0
        with self._transaction(immediate=True) as connection:
            rows = connection.execute(
                """
                SELECT id, kind, payload_json, status,
                       cancellation_requested, attempt_count
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
                    self._pause_schedule_for_task_in_connection(connection, row["id"], now)
                elif int(row["attempt_count"]) >= MAX_TASK_ATTEMPTS:
                    error = f"Tâche interrompue : limite de {MAX_TASK_ATTEMPTS} tentatives atteinte."
                    connection.execute(
                        """
                        UPDATE task_queue_tasks
                        SET status = ?, error_text = ?, updated_at = ?, finished_at = ?
                        WHERE id = ?
                        """,
                        (TaskStatus.FAILED.value, error, now, now, row["id"]),
                    )
                    self._append_message_in_connection(
                        connection,
                        row["id"],
                        error,
                        MessageLevel.ERROR,
                    )
                    self._pause_schedule_for_task_in_connection(connection, row["id"], now)
                elif not self._can_resume_interrupted_row(row):
                    error = (
                        "Tâche interrompue : reprise automatique refusée pour éviter de répéter une action. "
                        "Vérifie les fichiers produits avant toute nouvelle exécution."
                    )
                    connection.execute(
                        """
                        UPDATE task_queue_tasks
                        SET status = ?, error_text = ?, updated_at = ?, finished_at = ?
                        WHERE id = ?
                        """,
                        (TaskStatus.FAILED.value, error, now, now, row["id"]),
                    )
                    self._append_message_in_connection(
                        connection,
                        row["id"],
                        error,
                        MessageLevel.ERROR,
                    )
                    self._pause_schedule_for_task_in_connection(connection, row["id"], now)
                else:
                    connection.execute(
                        """
                        UPDATE task_queue_tasks
                        SET status = ?, progress = 0, started_at = NULL, updated_at = ?
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

    def claim_next(self, *, now: datetime | None = None) -> TaskRecord | None:
        """Atomically claim the oldest queued task for one registered worker."""

        due_before = _normalise_scheduled_for(now or datetime.now(timezone.utc))
        assert due_before is not None
        with self._transaction(immediate=True) as connection:
            self._materialize_due_schedules_in_connection(connection, due_before)
            row = connection.execute(
                """
                SELECT id, attempt_count FROM task_queue_tasks
                WHERE status = ?
                  AND attempt_count < ?
                  AND (scheduled_for IS NULL OR scheduled_for <= ?)
                ORDER BY rowid ASC
                LIMIT 1
                """,
                (TaskStatus.QUEUED.value, MAX_TASK_ATTEMPTS, due_before),
            ).fetchone()
            if row is None:
                return None
            now = _utc_now()
            attempt_number = int(row["attempt_count"]) + 1
            connection.execute(
                """
                UPDATE task_queue_tasks
                SET status = ?, started_at = ?, updated_at = ?,
                    attempt_count = attempt_count + 1
                WHERE id = ? AND status = ? AND attempt_count < ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    now,
                    now,
                    row["id"],
                    TaskStatus.QUEUED.value,
                    MAX_TASK_ATTEMPTS,
                ),
            )
            self._append_message_in_connection(
                connection,
                row["id"],
                f"Exécution locale démarrée (tentative {attempt_number}/{MAX_TASK_ATTEMPTS}).",
                MessageLevel.INFO,
            )
            return self._get_task_in_connection(connection, row["id"], include_messages=True)

    def retry_failed_task(self, task_id: str) -> TaskRecord:
        """Requeue only a failed scheduled read-only V5 orchestration task."""

        safe_id = self._validate_task_id(task_id)
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status is not TaskStatus.FAILED:
                raise InvalidTaskStateError("Seule une tâche échouée peut être relancée.")
            if (
                current.kind is not TaskKind.ORCHESTRATOR_PLAN
                or current.scheduled_for is None
                or current.schedule_id is not None
                or current.payload.get("allow_write") is not False
            ):
                raise InvalidTaskStateError(
                    "La reprise est réservée aux tâches programmées en lecture seule."
                )
            if current.attempt_count >= MAX_TASK_ATTEMPTS:
                raise InvalidTaskStateError(
                    f"La limite de {MAX_TASK_ATTEMPTS} tentatives est atteinte."
                )
            now = _utc_now()
            connection.execute(
                """
                UPDATE task_queue_tasks
                SET status = ?, progress = 0, cancellation_requested = 0,
                    result_json = NULL, error_text = NULL, started_at = NULL,
                    finished_at = NULL, updated_at = ?
                WHERE id = ? AND status = ? AND attempt_count < ?
                """,
                (
                    TaskStatus.QUEUED.value,
                    now,
                    safe_id,
                    TaskStatus.FAILED.value,
                    MAX_TASK_ATTEMPTS,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise InvalidTaskStateError("La tâche ne peut plus être relancée.")
            self._append_message_in_connection(
                connection,
                safe_id,
                f"Nouvel essai manuel demandé (tentative {current.attempt_count + 1}/{MAX_TASK_ATTEMPTS}).",
                MessageLevel.WARNING,
            )
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def reschedule_task(
        self,
        task_id: str,
        scheduled_for: datetime | str,
    ) -> TaskRecord:
        """Move only an unclaimed, queued, scheduled read-only V5 plan."""

        safe_id = self._validate_task_id(task_id)
        scheduled_at = _normalise_scheduled_for(scheduled_for)
        if scheduled_at is None:
            raise TaskQueueError("Une nouvelle heure programmée est requise.")
        with self._transaction(immediate=True) as connection:
            if datetime.fromisoformat(scheduled_at) <= datetime.now(timezone.utc):
                raise TaskQueueError("La nouvelle heure programmée doit rester dans le futur.")
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status is not TaskStatus.QUEUED:
                raise InvalidTaskStateError(
                    "Seule une tâche encore en attente peut être reprogrammée."
                )
            if (
                current.kind is not TaskKind.ORCHESTRATOR_PLAN
                or current.scheduled_for is None
                or current.schedule_id is not None
            ):
                raise InvalidTaskStateError(
                    "La reprogrammation est réservée aux tâches V5 déjà programmées."
                )
            if current.payload.get("allow_write") is not False:
                raise InvalidTaskStateError(
                    "Seule une tâche programmée en lecture seule peut être reprogrammée."
                )
            if current.attempt_count != 0:
                raise InvalidTaskStateError(
                    "Une tâche déjà prise en charge ne peut plus être reprogrammée."
                )
            old_schedule = current.scheduled_for
            connection.execute(
                """
                UPDATE task_queue_tasks
                SET scheduled_for = ?, updated_at = ?
                WHERE id = ? AND status = ? AND scheduled_for IS NOT NULL
                  AND attempt_count = 0
                """,
                (scheduled_at, _utc_now(), safe_id, TaskStatus.QUEUED.value),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise InvalidTaskStateError(
                    "La tâche a changé d'état avant la reprogrammation."
                )
            self._append_message_in_connection(
                connection,
                safe_id,
                f"Horaire reprogrammé : {old_schedule} → {scheduled_at}.",
                MessageLevel.INFO,
            )
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def request_cancel(self, task_id: str) -> TaskRecord:
        """Request cooperative cancellation; queued work is cancelled immediately."""

        safe_id = self._validate_task_id(task_id)
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status in TERMINAL_STATUSES:
                return current
            self._request_cancel_in_connection(connection, safe_id)
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

    def finish_success(
        self,
        task_id: str,
        result: Any = None,
        *,
        now: datetime | None = None,
    ) -> TaskRecord:
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
            finished_at = _normalise_scheduled_for(now or datetime.now(timezone.utc))
            assert finished_at is not None
            if current.cancellation_requested or current.status is TaskStatus.CANCELLING:
                connection.execute(
                    """
                    UPDATE task_queue_tasks
                    SET status = ?, cancellation_requested = 1,
                        updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.CANCELLED.value, finished_at, finished_at, safe_id),
                )
                self._pause_schedule_for_task_in_connection(connection, safe_id, finished_at)
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
                    (TaskStatus.SUCCEEDED.value, result_json, finished_at, finished_at, safe_id),
                )
                self._advance_schedule_after_success_in_connection(
                    connection, safe_id, finished_at
                )
                self._append_message_in_connection(
                    connection,
                    safe_id,
                    "Tâche locale terminée.",
                    MessageLevel.INFO,
                )
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def finish_failed(
        self,
        task_id: str,
        error: object,
        *,
        partial_result: Any = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        """Finish a task with a safe error and optional bounded partial result."""

        safe_id = self._validate_task_id(task_id)
        safe_error = _safe_error(error)
        partial_result_json: str | None = None
        partial_result_rejected = False
        if partial_result is not None:
            try:
                _, partial_result_json = _prepare_json(
                    partial_result,
                    label="Le résultat partiel de tâche",
                    max_bytes=MAX_RESULT_BYTES,
                )
            except Exception:
                # A malformed or oversized diagnostic must never strand the
                # task in RUNNING. The bounded error remains the source of truth.
                partial_result_rejected = True
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status not in {TaskStatus.RUNNING, TaskStatus.CANCELLING}:
                raise InvalidTaskStateError("Seule une tâche en cours peut échouer.")
            finished_at = _normalise_scheduled_for(now or datetime.now(timezone.utc))
            assert finished_at is not None
            if current.cancellation_requested or current.status is TaskStatus.CANCELLING:
                connection.execute(
                    """
                    UPDATE task_queue_tasks
                    SET status = ?, cancellation_requested = 1,
                        updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (TaskStatus.CANCELLED.value, finished_at, finished_at, safe_id),
                )
                self._pause_schedule_for_task_in_connection(connection, safe_id, finished_at)
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
                    SET status = ?, result_json = ?, error_text = ?, updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (
                        TaskStatus.FAILED.value,
                        partial_result_json,
                        safe_error,
                        finished_at,
                        finished_at,
                        safe_id,
                    ),
                )
                self._pause_schedule_for_task_in_connection(
                    connection, safe_id, finished_at
                )
                if partial_result_rejected:
                    self._append_message_in_connection(
                        connection,
                        safe_id,
                        "Les détails partiels ont été écartés car ils dépassaient les limites de stockage sécurisé.",
                        MessageLevel.WARNING,
                    )
                self._append_message_in_connection(connection, safe_id, safe_error, MessageLevel.ERROR)
            return self._get_task_in_connection(connection, safe_id, include_messages=True)

    def finish_cancelled(
        self,
        task_id: str,
        *,
        message: object | None = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        """Finalize cooperative cancellation for a queued/running task."""

        safe_id = self._validate_task_id(task_id)
        with self._transaction(immediate=True) as connection:
            current = self._get_task_in_connection(connection, safe_id, include_messages=False)
            if current.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
                raise InvalidTaskStateError("Une tâche déjà terminée ne peut plus être annulée.")
            if current.status is TaskStatus.CANCELLED:
                return current
            finished_at = _normalise_scheduled_for(now or datetime.now(timezone.utc))
            assert finished_at is not None
            connection.execute(
                """
                UPDATE task_queue_tasks
                SET status = ?, cancellation_requested = 1,
                    updated_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (TaskStatus.CANCELLED.value, finished_at, finished_at, safe_id),
            )
            self._pause_schedule_for_task_in_connection(
                connection, safe_id, finished_at
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
        clock: Callable[[], datetime] | None = None,
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
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._state_lock = threading.Lock()
        self._execution_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._restart_requested = False
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
                if self._stop_event.is_set():
                    self._restart_requested = True
                return
            self._stop_event.clear()
            self._restart_requested = False
            self._thread = threading.Thread(
                target=self._run_loop,
                name="come-ai-task-runner",
                daemon=True,
            )
            self._thread.start()

    def stop(
        self, *, wait: bool = True, timeout: float = 5.0, cancel_active: bool = False
    ) -> bool:
        """Ask the worker to stop and report whether its thread has exited.

        Cancelling active work remains cooperative. ``False`` means the worker
        is still alive, usually because a handler has not reached a checkpoint
        or the join timeout expired.
        """

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
        with self._state_lock:
            current_thread = self._thread
        return current_thread is None or not current_thread.is_alive()

    def submit(
        self,
        kind: TaskKind | str,
        payload: Mapping[str, Any],
        *,
        scheduled_for: datetime | str | None = None,
        idempotency_key: str | None = None,
    ) -> TaskRecord:
        """Create a task and wake the worker; execution still needs registered code."""

        task = self.queue.create_task(
            kind,
            payload,
            scheduled_for=scheduled_for,
            idempotency_key=idempotency_key,
        )
        self._wake_event.set()
        return task

    def cancel(self, task_id: str) -> TaskRecord:
        task = self.queue.request_cancel(task_id)
        self._wake_event.set()
        return task

    def retry(self, task_id: str) -> TaskRecord:
        task = self.queue.retry_failed_task(task_id)
        self._wake_event.set()
        return task

    def reschedule(self, task_id: str, scheduled_for: datetime | str) -> TaskRecord:
        task = self.queue.reschedule_task(task_id, scheduled_for)
        self._wake_event.set()
        return task

    def run_once(self) -> TaskRecord | None:
        """Synchronously execute at most one queued job (useful for deterministic tests)."""

        if not self._execution_lock.acquire(blocking=False):
            return None
        try:
            with self._state_lock:
                # Publish the claimed id atomically with claiming work. Otherwise
                # stop(cancel_active=True) can observe no active task after SQLite
                # has marked it RUNNING and miss the cancellation window.
                task = self.queue.claim_next(now=self._clock())
                if task is None:
                    return None
                self._active_task_id = task.id
            try:
                handler = self._handlers.get(task.kind)
                if handler is None:
                    return self.queue.finish_failed(
                        task.id,
                        f"Aucun gestionnaire local autorisé pour « {task.kind.value} ».",
                        now=self._clock(),
                    )
                context = TaskExecutionContext(self.queue, task.id)
                try:
                    context.checkpoint()
                    result = handler(context, task.payload)
                    context.checkpoint()
                    return self.queue.finish_success(task.id, result, now=self._clock())
                except TaskCancelled:
                    return self.queue.finish_cancelled(task.id, now=self._clock())
                except TaskExecutionFailure as error:
                    if self.queue.is_cancellation_requested(task.id):
                        return self.queue.finish_cancelled(
                            task.id,
                            message="Tâche arrêtée après une demande d’annulation.",
                            now=self._clock(),
                        )
                    return self.queue.finish_failed(
                        task.id,
                        error,
                        partial_result=error.partial_result,
                        now=self._clock(),
                    )
                except Exception as error:  # handlers are application-owned but can still fail.
                    if self.queue.is_cancellation_requested(task.id):
                        return self.queue.finish_cancelled(
                            task.id,
                            message="Tâche arrêtée après une demande d’annulation.",
                            now=self._clock(),
                        )
                    return self.queue.finish_failed(task.id, error, now=self._clock())
            finally:
                with self._state_lock:
                    self._active_task_id = None
        finally:
            self._execution_lock.release()

    def _run_loop(self) -> None:
        current_thread = threading.current_thread()
        try:
            while not self._stop_event.is_set():
                try:
                    completed = self.run_once()
                except Exception as error:
                    # A database-level failure must not spin a CPU. Individual
                    # handler failures are persisted by ``run_once`` above.
                    with self._state_lock:
                        self._last_worker_error = _safe_error(error)
                    completed = None
                else:
                    # The diagnostic describes the current worker health, not a
                    # permanent historical error. A successful poll/claim proves
                    # that the worker and queue have recovered.
                    with self._state_lock:
                        self._last_worker_error = None
                if completed is None:
                    self._wake_event.wait(self._poll_interval_seconds)
                    self._wake_event.clear()
        finally:
            with self._state_lock:
                if self._thread is current_thread:
                    self._thread = None
                if self._restart_requested:
                    self._restart_requested = False
                    self._stop_event.clear()
                    self._wake_event.set()
                    next_thread = threading.Thread(
                        target=self._run_loop,
                        name="come-ai-task-runner",
                        daemon=True,
                    )
                    self._thread = next_thread
                    next_thread.start()

