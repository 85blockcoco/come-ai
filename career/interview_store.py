"""Local persistence for the targeted interview-preparation sessions (SPEC-010).

The store keeps two things: the preparation itself (questions, factsheet,
recruiter questions) and the rehearsal history (one row per simulated answer).
It lives in its own SQLite file inside the private ``career_data`` directory
so that adding the feature never rewrites the main Career schema and never
mixes rehearsal data with the offer tracker.

Nothing here performs a network call and nothing is written outside the
private Career directory: the file is created with owner-only permissions and
every read is bounded.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import clean_text, utc_now
from workspace_core import UserFacingError


SCHEMA_VERSION = 1
MAX_SESSIONS = 100
MAX_SIMULATIONS_PER_SESSION = 200
MAX_PAYLOAD_CHARS = 400_000


class InterviewPrepStore:
    """A small, private SQLite store for preparation sessions and rehearsals."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "interview_prep.sqlite3"
        self._lock = threading.RLock()
        self._ensure_storage()
        self._initialize()

    def _ensure_storage(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass

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
                "La base locale des préparations d’entretien a rencontré un problème. Réessaie."
            ) from error
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise UserFacingError(
                    "Les préparations d’entretien ont été créées par une version plus récente de l’application."
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS interview_prep_sessions (
                    id TEXT PRIMARY KEY,
                    offer_id TEXT NOT NULL DEFAULT '',
                    profile_id TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'standard',
                    company TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS interview_prep_simulations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    question_id TEXT NOT NULL DEFAULT '',
                    score TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS interview_prep_sessions_updated_idx
                    ON interview_prep_sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS interview_prep_simulations_session_idx
                    ON interview_prep_simulations(session_id, created_at DESC);
                """
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    # -- sessions ---------------------------------------------------------

    def save_session(
        self,
        *,
        session_id: str,
        offer_id: str,
        profile_id: str,
        mode: str,
        payload: dict[str, Any],
        company: str = "",
        title: str = "",
    ) -> None:
        """Create or replace one preparation session."""
        identifier = clean_text(session_id, limit=80)
        if not identifier:
            raise UserFacingError("La préparation d’entretien n’a pas d’identifiant.")
        serialized = json.dumps(payload, ensure_ascii=False)[:MAX_PAYLOAD_CHARS]
        now = utc_now()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO interview_prep_sessions (
                    id, offer_id, profile_id, mode, company, title,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    offer_id = excluded.offer_id,
                    profile_id = excluded.profile_id,
                    mode = excluded.mode,
                    company = excluded.company,
                    title = excluded.title,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    identifier,
                    clean_text(offer_id, limit=80),
                    clean_text(profile_id, limit=80),
                    clean_text(mode, limit=40) or "standard",
                    clean_text(company, limit=240),
                    clean_text(title, limit=300),
                    serialized,
                    now,
                    now,
                ),
            )

    def get_payload(self, session_id: str) -> dict[str, Any] | None:
        """Return the stored preparation payload, or ``None`` when unknown."""
        identifier = clean_text(session_id, limit=80)
        if not identifier:
            return None
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM interview_prep_sessions WHERE id = ?", (identifier,)
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return the session metadata (without the full payload)."""
        identifier = clean_text(session_id, limit=80)
        if not identifier:
            return None
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, offer_id, profile_id, mode, company, title, created_at, updated_at
                FROM interview_prep_sessions WHERE id = ?
                """,
                (identifier,),
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_sessions(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """List the most recent preparations."""
        bounded = max(1, min(int(limit or 30), MAX_SESSIONS))
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, offer_id, profile_id, mode, company, title, created_at, updated_at
                FROM interview_prep_sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        sessions = [dict(row) for row in rows]
        for session in sessions:
            session["simulation_count"] = self.count_simulations(str(session["id"]))
        return sessions

    def delete_session(self, session_id: str) -> None:
        """Remove one preparation and its rehearsal history."""
        identifier = clean_text(session_id, limit=80)
        if not identifier:
            return
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM interview_prep_simulations WHERE session_id = ?", (identifier,))
            connection.execute("DELETE FROM interview_prep_sessions WHERE id = ?", (identifier,))

    # -- rehearsals --------------------------------------------------------

    def append_simulation(
        self,
        *,
        session_id: str,
        question_id: str,
        score: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Append one rehearsal answer to the session history."""
        identifier = clean_text(session_id, limit=80)
        if not identifier:
            raise UserFacingError("Cette préparation d’entretien n’existe pas.")
        serialized = json.dumps(payload, ensure_ascii=False)[:MAX_PAYLOAD_CHARS]
        now = utc_now()
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                "SELECT COUNT(*) FROM interview_prep_simulations WHERE session_id = ?", (identifier,)
            ).fetchone()[0]
            if int(existing) >= MAX_SIMULATIONS_PER_SESSION:
                raise UserFacingError(
                    "Cette préparation a atteint 200 réponses enregistrées. "
                    "Exporte la fiche puis démarre une nouvelle préparation."
                )
            record_id = f"prep_sim_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO interview_prep_simulations (
                    id, session_id, question_id, score, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    identifier,
                    clean_text(question_id, limit=120),
                    clean_text(score, limit=40),
                    serialized,
                    now,
                ),
            )
        return {
            "id": record_id,
            "session_id": identifier,
            "question_id": clean_text(question_id, limit=120),
            "score": clean_text(score, limit=40),
            "created_at": now,
        }

    def list_simulations(self, session_id: str) -> list[dict[str, Any]]:
        """Return the rehearsal history of one preparation, oldest first."""
        identifier = clean_text(session_id, limit=80)
        if not identifier:
            return []
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, session_id, question_id, score, payload_json, created_at
                FROM interview_prep_simulations
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (identifier, MAX_SIMULATIONS_PER_SESSION),
            ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
            except json.JSONDecodeError:
                payload = {}
            history.append(
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "question_id": row["question_id"],
                    "score": row["score"],
                    "created_at": row["created_at"],
                    "feedback": payload if isinstance(payload, dict) else {},
                }
            )
        return history

    def count_simulations(self, session_id: str) -> int:
        """Return how many rehearsals a preparation already holds."""
        identifier = clean_text(session_id, limit=80)
        if not identifier:
            return 0
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM interview_prep_simulations WHERE session_id = ?", (identifier,)
            ).fetchone()
        return int(row[0]) if row else 0

    # -- housekeeping ------------------------------------------------------

    def clear(self) -> None:
        """Remove every preparation and rehearsal (used by the data reset)."""
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM interview_prep_simulations")
            connection.execute("DELETE FROM interview_prep_sessions")


__all__ = ["InterviewPrepStore", "MAX_SIMULATIONS_PER_SESSION", "SCHEMA_VERSION"]
