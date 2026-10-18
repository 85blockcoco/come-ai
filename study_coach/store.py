"""Local SQLite persistence for the Study Coach engine.

The store is intentionally standalone: it does **not** touch the personal-memory
database, the workspace or the task queue.  It lives in a directory chosen by
the caller (the web integration will point it at the same folder as the other
Côme AI local stores) and it can export or delete everything it holds.

Layout::

    <base_dir>/study_coach.sqlite3

    meta      schema marker
    syllabi   one JSON payload per revision programme
    sessions  one JSON payload per review session
    answers   one row per learner answer (columns kept for fast statistics)
    schedule  one row per spaced-repetition item
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .errors import StoreError
from .models import (
    SCHEMA_VERSION,
    AnswerRecord,
    ReviewSession,
    ScheduleEntry,
    Syllabus,
    clean_text,
    utc_now,
)

DB_FILENAME = "study_coach.sqlite3"
EXPORT_SCHEMA = "come-study-coach-export/1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS syllabi (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    syllabus_id TEXT NOT NULL,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_syllabus_idx ON sessions (syllabus_id, created_at);
CREATE TABLE IF NOT EXISTS answers (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    notion_id TEXT NOT NULL,
    syllabus_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    score REAL,
    validation TEXT NOT NULL,
    answered_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS answers_session_idx ON answers (session_id, answered_at);
CREATE INDEX IF NOT EXISTS answers_notion_idx ON answers (notion_id, answered_at);
CREATE TABLE IF NOT EXISTS schedule (
    item_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    due_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS schedule_due_idx ON schedule (due_at);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: str) -> Any:
    return json.loads(value)


class StudyCoachStore:
    """Thread-safe, local-only storage for syllabi, sessions, answers, schedule."""

    def __init__(self, base_dir: str | Path | None = None, *, db_path: str | Path | None = None) -> None:
        if db_path is not None:
            self.db_path = Path(db_path)
        elif base_dir is not None:
            self.db_path = Path(base_dir).expanduser() / DB_FILENAME
        else:
            raise StoreError("Un dossier de stockage (base_dir) ou un chemin de base (db_path) est requis.")

        self._lock = threading.RLock()
        self._closed = False
        self._in_memory = str(self.db_path) == ":memory:"
        if not self._in_memory:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._tighten_permissions()
        self._connection = sqlite3.connect(
            str(self.db_path), check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            if not self._in_memory:
                self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.executescript(_SCHEMA)
            self._connection.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            # The database file is only created by SQLite: tighten it afterwards.
            if not self._in_memory:
                self._tighten_permissions()

    # ------------------------------------------------------------------ #
    # Infrastructure
    # ------------------------------------------------------------------ #

    def _tighten_permissions(self) -> None:
        """Keep the study data readable by its owner only."""

        for path in (self.db_path.parent, self.db_path):
            try:
                if path.is_dir():
                    os.chmod(path, 0o700)
                elif path.exists():
                    os.chmod(path, 0o600)
            except OSError:
                # A read-only or exotic filesystem must not block the engine.
                pass

    @property
    def schema_version(self) -> int:
        row = self._connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "StudyCoachStore":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def _execute(self, sql: str, parameters: Iterable[Any] = ()) -> sqlite3.Cursor:
        if self._closed:
            raise StoreError("Le stockage Study Coach est fermé.")
        with self._lock:
            return self._connection.execute(sql, tuple(parameters))

    # ------------------------------------------------------------------ #
    # Syllabi
    # ------------------------------------------------------------------ #

    def save_syllabus(self, syllabus: Syllabus) -> Syllabus:
        if not syllabus.id:
            raise StoreError("Le programme de révision doit avoir un identifiant.")
        self._execute(
            "INSERT INTO syllabi (id, title, created_at, payload) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, payload=excluded.payload",
            (syllabus.id, syllabus.title, syllabus.created_at or utc_now(), _dumps(syllabus.to_dict())),
        )
        return syllabus

    def get_syllabus(self, syllabus_id: str) -> Syllabus | None:
        row = self._execute("SELECT payload FROM syllabi WHERE id=?", (syllabus_id,)).fetchone()
        return Syllabus.from_dict(_loads(row["payload"])) if row else None

    def list_syllabi(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT id, title, created_at FROM syllabi ORDER BY created_at DESC LIMIT ?",
            (max(1, int(limit or 50)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_syllabus(self, syllabus_id: str) -> dict[str, Any]:
        with self._lock:
            sessions = [
                str(row["id"])
                for row in self._execute(
                    "SELECT id FROM sessions WHERE syllabus_id=?", (syllabus_id,)
                ).fetchall()
            ]
            for session_id in sessions:
                self._execute("DELETE FROM answers WHERE session_id=?", (session_id,))
            self._execute("DELETE FROM sessions WHERE syllabus_id=?", (syllabus_id,))
            self._execute("DELETE FROM syllabi WHERE id=?", (syllabus_id,))
            return {"syllabus_id": syllabus_id, "sessions_deleted": len(sessions)}

    # ------------------------------------------------------------------ #
    # Sessions
    # ------------------------------------------------------------------ #

    def save_session(self, session: ReviewSession) -> ReviewSession:
        if not session.id:
            raise StoreError("La séance doit avoir un identifiant.")
        self._execute(
            "INSERT INTO sessions (id, syllabus_id, title, mode, status, created_at, updated_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, status=excluded.status, "
            "updated_at=excluded.updated_at, payload=excluded.payload",
            (
                session.id,
                session.syllabus_id,
                session.title,
                session.mode,
                session.status,
                session.created_at or utc_now(),
                session.updated_at or utc_now(),
                _dumps(session.to_dict()),
            ),
        )
        return session

    def get_session(self, session_id: str) -> ReviewSession | None:
        row = self._execute("SELECT payload FROM sessions WHERE id=?", (session_id,)).fetchone()
        return ReviewSession.from_dict(_loads(row["payload"])) if row else None

    def list_sessions(self, *, syllabus_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if syllabus_id:
            rows = self._execute(
                "SELECT id, syllabus_id, title, mode, status, created_at, updated_at FROM sessions "
                "WHERE syllabus_id=? ORDER BY created_at DESC LIMIT ?",
                (syllabus_id, max(1, int(limit or 50))),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT id, syllabus_id, title, mode, status, created_at, updated_at FROM sessions "
                "ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit or 50)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            self._execute("DELETE FROM answers WHERE session_id=?", (session_id,))
            self._execute("DELETE FROM sessions WHERE id=?", (session_id,))
            return {"session_id": session_id}

    # ------------------------------------------------------------------ #
    # Answers
    # ------------------------------------------------------------------ #

    def record_answer(self, answer: AnswerRecord) -> AnswerRecord:
        if not answer.id:
            raise StoreError("La réponse doit avoir un identifiant.")
        self._execute(
            "INSERT INTO answers (id, session_id, question_id, notion_id, syllabus_id, status, score, "
            "validation, answered_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, score=excluded.score, "
            "validation=excluded.validation, payload=excluded.payload",
            (
                answer.id,
                answer.session_id,
                answer.question_id,
                answer.notion_id,
                answer.syllabus_id,
                answer.status,
                answer.score,
                answer.validation,
                answer.answered_at or utc_now(),
                _dumps(answer.to_dict()),
            ),
        )
        return answer

    def get_answer(self, answer_id: str) -> AnswerRecord | None:
        row = self._execute("SELECT payload FROM answers WHERE id=?", (answer_id,)).fetchone()
        return AnswerRecord.from_dict(_loads(row["payload"])) if row else None

    def find_answer(self, session_id: str, question_id: str) -> AnswerRecord | None:
        row = self._execute(
            "SELECT payload FROM answers WHERE session_id=? AND question_id=? LIMIT 1",
            (session_id, question_id),
        ).fetchone()
        return AnswerRecord.from_dict(_loads(row["payload"])) if row else None

    def list_answers(
        self,
        *,
        session_id: str = "",
        notion_id: str = "",
        syllabus_id: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if session_id:
            clauses.append("session_id=?")
            parameters.append(session_id)
        if notion_id:
            clauses.append("notion_id=?")
            parameters.append(notion_id)
        if syllabus_id:
            clauses.append("syllabus_id=?")
            parameters.append(syllabus_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(max(1, int(limit or 500)))
        rows = self._execute(
            f"SELECT notion_id, question_id, syllabus_id, status, score, validation, answered_at, session_id "
            f"FROM answers{where} ORDER BY answered_at ASC LIMIT ?",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_answers(self, *, session_id: str = "") -> int:
        if session_id:
            cursor = self._execute("DELETE FROM answers WHERE session_id=?", (session_id,))
        else:
            cursor = self._execute("DELETE FROM answers")
        return int(cursor.rowcount or 0)

    # ------------------------------------------------------------------ #
    # Spaced repetition
    # ------------------------------------------------------------------ #

    def upsert_schedule(self, entry: ScheduleEntry) -> ScheduleEntry:
        if not entry.item_key:
            raise StoreError("Une entrée de révision doit avoir une clé.")
        self._execute(
            "INSERT INTO schedule (item_key, kind, due_at, updated_at, payload) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(item_key) DO UPDATE SET kind=excluded.kind, due_at=excluded.due_at, "
            "updated_at=excluded.updated_at, payload=excluded.payload",
            (entry.item_key, entry.kind, entry.due_at, entry.updated_at or utc_now(), _dumps(entry.to_dict())),
        )
        return entry

    def get_schedule(self, item_key: str) -> ScheduleEntry | None:
        row = self._execute("SELECT payload FROM schedule WHERE item_key=?", (item_key,)).fetchone()
        return ScheduleEntry.from_dict(_loads(row["payload"])) if row else None

    def list_schedule(self) -> list[ScheduleEntry]:
        rows = self._execute("SELECT payload FROM schedule ORDER BY due_at ASC").fetchall()
        return [ScheduleEntry.from_dict(_loads(row["payload"])) for row in rows]

    # ------------------------------------------------------------------ #
    # Statistics, export, deletion
    # ------------------------------------------------------------------ #

    def stats(self) -> dict[str, Any]:
        answers = self.list_answers(limit=100_000)
        by_status: dict[str, int] = {}
        for answer in answers:
            by_status[str(answer.get("status") or "inconnu")] = by_status.get(str(answer.get("status") or "inconnu"), 0) + 1
        sessions = self.list_sessions(limit=100_000)
        return {
            "schema_version": self.schema_version,
            "syllabi": len(self.list_syllabi(limit=100_000)),
            "sessions_total": len(sessions),
            "sessions_completed": len([row for row in sessions if row.get("status") == "terminee"]),
            "questions_seen": len(answers),
            "answers_by_status": by_status,
            "schedule_items": len(self.list_schedule()),
            "database": DB_FILENAME,
        }

    @property
    def database_path(self) -> str:
        """Absolute path of the database (never exported, for diagnostics only)."""

        return str(self.db_path)

    def export_data(self) -> dict[str, Any]:
        """Full, portable export: no absolute path of the learner's documents."""

        syllabi = [
            Syllabus.from_dict(_loads(row["payload"]))
            for row in self._execute("SELECT payload FROM syllabi ORDER BY created_at ASC").fetchall()
        ]
        sessions = [
            ReviewSession.from_dict(_loads(row["payload"]))
            for row in self._execute("SELECT payload FROM sessions ORDER BY created_at ASC").fetchall()
        ]
        return {
            "schema": EXPORT_SCHEMA,
            "exported_at": utc_now(),
            "storage_schema_version": self.schema_version,
            "syllabi": [item.to_dict() for item in syllabi],
            "sessions": [item.to_dict() for item in sessions],
            "answers": self.list_answers(limit=1_000_000),
            "schedule": [entry.to_dict() for entry in self.list_schedule()],
            "stats": self.stats(),
        }

    def delete_data(self, *, scope: str = "all", syllabus_id: str = "") -> dict[str, Any]:
        """Delete stored data.

        ``scope`` is ``all`` (default), ``progress`` (answers + schedule) or
        ``sessions``.  When ``syllabus_id`` is given, only that course (its
        sessions and its answers) is deleted and ``scope`` is ignored.
        """

        scope = clean_text(scope, limit=32) or "all"
        if scope not in {"all", "progress", "sessions"}:
            raise StoreError(f"Périmètre de suppression inconnu : {scope}.")
        with self._lock:
            deleted: dict[str, Any] = {"answers": 0, "sessions": 0, "syllabi": 0, "schedule": 0}
            if syllabus_id:
                session_ids = [
                    str(row["id"])
                    for row in self._execute(
                        "SELECT id FROM sessions WHERE syllabus_id=?", (syllabus_id,)
                    ).fetchall()
                ]
                for session_id in session_ids:
                    deleted["answers"] += self._execute(
                        "DELETE FROM answers WHERE session_id=?", (session_id,)
                    ).rowcount or 0
                deleted["sessions"] = self._execute(
                    "DELETE FROM sessions WHERE syllabus_id=?", (syllabus_id,)
                ).rowcount or 0
                deleted["syllabi"] = self._execute(
                    "DELETE FROM syllabi WHERE id=?", (syllabus_id,)
                ).rowcount or 0
                deleted["scope"] = f"syllabus:{syllabus_id}"
                return deleted
            if scope == "all":
                deleted["answers"] = self._execute("DELETE FROM answers").rowcount or 0
                deleted["sessions"] = self._execute("DELETE FROM sessions").rowcount or 0
                deleted["syllabi"] += self._execute("DELETE FROM syllabi").rowcount or 0
                deleted["schedule"] = self._execute("DELETE FROM schedule").rowcount or 0
            elif scope == "progress":
                deleted["answers"] = self._execute("DELETE FROM answers").rowcount or 0
                deleted["schedule"] = self._execute("DELETE FROM schedule").rowcount or 0
            else:
                deleted["answers"] = self._execute("DELETE FROM answers").rowcount or 0
                deleted["sessions"] = self._execute("DELETE FROM sessions").rowcount or 0
            deleted["scope"] = scope
            return deleted
