"""Persistance locale des accords de consentement.

Le dépôt est une base SQLite unique, créée dans un dossier privé fourni par
l'appelant.  Il suit les conventions déjà employées par ``personal_profile`` :
dossier en ``0700``, base et journaux en ``0600``, mode WAL, transactions
``BEGIN IMMEDIATE`` et erreurs en français sans détail d'implémentation.

Ce qui est stocké, et rien d'autre : l'identifiant de l'accord, la cible liée
(fournisseur, modèle, objectif), l'empreinte et la taille du contenu, les
instants d'émission, d'expiration et de consommation, l'état, le compteur
d'usage, l'acteur et une note libre courte.  **Aucun contenu personnel n'est
écrit**, pas plus dans la table des accords que dans le journal des refus :
celui-ci ne garde que des codes, des champs divergents et des horodatages.

La consommation est atomique au niveau de la base : deux threads ou deux
processus ne peuvent pas consommer le même accord, le second reçoit
``consent_exhausted``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from .envelope import SINGLE_USE, ConsentEnvelope, format_instant
from .errors import StoreError

STORE_SCHEMA_VERSION = 1
DEFAULT_DB_NAME = "consent_guard.sqlite3"

STATE_GRANTED = "granted"
STATE_USED = "used"
STATE_REVOKED = "revoked"
STATES = (STATE_GRANTED, STATE_USED, STATE_REVOKED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS consents (
    consent_id     TEXT PRIMARY KEY,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    purpose        TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    payload_bytes  INTEGER NOT NULL,
    issued_at      TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    state          TEXT NOT NULL,
    uses_allowed   INTEGER NOT NULL,
    uses_consumed  INTEGER NOT NULL,
    consumed_at    TEXT NOT NULL DEFAULT '',
    actor          TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    binding_digest TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS consents_state_idx ON consents (state, expires_at);
CREATE TABLE IF NOT EXISTS refusals (
    refusal_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    code        TEXT NOT NULL,
    consent_id  TEXT NOT NULL DEFAULT '',
    fields      TEXT NOT NULL DEFAULT '[]'
);
"""


@dataclass(frozen=True)
class RefusalRecord:
    """Entrée du journal des refus : codes et champs, jamais de contenu."""

    at: str
    code: str
    consent_id: str = ""
    fields: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "code": self.code,
            "consent_id": self.consent_id,
            "fields": list(self.fields),
        }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_envelope(row: sqlite3.Row) -> ConsentEnvelope:
    return ConsentEnvelope(
        consent_id=row["consent_id"],
        provider=row["provider"],
        model=row["model"],
        purpose=row["purpose"],
        payload_digest=row["payload_digest"],
        payload_bytes=int(row["payload_bytes"]),
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        state=row["state"],
        uses_allowed=int(row["uses_allowed"]),
        uses_consumed=int(row["uses_consumed"]),
        consumed_at=row["consumed_at"] or "",
        actor=row["actor"] or "",
        note=row["note"] or "",
    )


class ConsentStore:
    """Base locale des accords, thread-safe et sans contenu personnel."""

    def __init__(self, base_dir: Path | str, *, db_name: str = DEFAULT_DB_NAME) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.base_dir, 0o700)
        except OSError:
            pass
        self.db_path = self.base_dir / db_name
        self._lock = RLock()
        self._initialise()

    # --- cycle de vie -----------------------------------------------------

    def _initialise(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(_SCHEMA)

    def close(self) -> None:
        """Rien à garder ouvert : chaque opération ouvre et ferme sa connexion."""

        return None

    def __enter__(self) -> "ConsentStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA synchronous = FULL")
            yield connection
            self._tighten_permissions()
        except sqlite3.Error as error:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise StoreError("Le dépôt local des consentements est indisponible.") from error
        finally:
            if connection is not None:
                connection.close()

    def _tighten_permissions(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.db_path) + suffix)
            if candidate.exists():
                try:
                    os.chmod(candidate, 0o600)
                except OSError:
                    pass

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """Transaction d'écriture immédiate : la concurrence est sérialisée."""

        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
                raise
            connection.commit()

    # --- accords ----------------------------------------------------------

    def insert(self, envelope: ConsentEnvelope) -> None:
        """Mémorise un accord neuf.  Un identifiant déjà pris est refusé."""

        payload = (
            envelope.consent_id,
            envelope.provider,
            envelope.model,
            envelope.purpose,
            envelope.payload_digest,
            envelope.payload_bytes,
            envelope.issued_at,
            envelope.expires_at,
            envelope.state,
            envelope.uses_allowed or SINGLE_USE,
            envelope.uses_consumed,
            envelope.consumed_at,
            envelope.actor,
            envelope.note,
            envelope.binding_digest,
        )
        with self._write() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO consents (
                        consent_id, provider, model, purpose, payload_digest, payload_bytes,
                        issued_at, expires_at, state, uses_allowed, uses_consumed, consumed_at,
                        actor, note, binding_digest
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
            except sqlite3.IntegrityError as error:
                raise StoreError("Un accord avec cet identifiant existe déjà localement.") from error

    def get(self, consent_id: str) -> ConsentEnvelope | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM consents WHERE consent_id = ?", (consent_id,)
            ).fetchone()
        return _row_to_envelope(row) if row is not None else None

    def mark_consumed(self, consent_id: str, *, at: str) -> bool:
        """Consomme l'accord de façon atomique.

        Renvoie ``True`` seulement si cette appel est celui qui a basculé le
        compteur.  Une deuxième consommation renvoie ``False`` : c'est le
        verrou qui rend le rejeu impossible.
        """

        with self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE consents
                   SET uses_consumed = uses_consumed + 1, state = ?, consumed_at = ?
                 WHERE consent_id = ? AND uses_consumed < uses_allowed AND state = ?
                """,
                (STATE_USED, at, consent_id, STATE_GRANTED),
            )
        return cursor.rowcount == 1

    def mark_revoked(self, consent_id: str) -> bool:
        with self._write() as connection:
            cursor = connection.execute(
                "UPDATE consents SET state = ? WHERE consent_id = ? AND state = ?",
                (STATE_REVOKED, consent_id, STATE_GRANTED),
            )
        return cursor.rowcount == 1

    def mark_expired(self, *, now: datetime | None = None) -> int:
        """Bascule en « révoqué » les accordés dont l'expiration est dépassée."""

        moment = now or datetime.now(timezone.utc)
        limit = format_instant(moment)
        with self._write() as connection:
            cursor = connection.execute(
                "UPDATE consents SET state = ? WHERE state = ? AND expires_at <= ?",
                (STATE_REVOKED, STATE_GRANTED, limit),
            )
        return int(cursor.rowcount or 0)

    def list_consents(self, *, state: str | None = None) -> tuple[ConsentEnvelope, ...]:
        query = "SELECT * FROM consents"
        params: tuple[Any, ...] = ()
        if state:
            query += " WHERE state = ?"
            params = (state,)
        query += " ORDER BY issued_at DESC, consent_id ASC"
        with self._lock, self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_row_to_envelope(row) for row in rows)

    # --- journal des refus -------------------------------------------------

    def record_refusal(self, at: str, code: str, consent_id: str = "", fields: tuple[str, ...] = ()) -> None:
        """Journalise un refus.  Aucun contenu, aucun extrait, aucun chemin."""

        with self._write() as connection:
            connection.execute(
                "INSERT INTO refusals (at, code, consent_id, fields) VALUES (?, ?, ?, ?)",
                (at, code, consent_id, "[]" if not fields else json.dumps(list(fields))),
            )

    def journal(self, *, limit: int = 200) -> tuple[RefusalRecord, ...]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT at, code, consent_id, fields FROM refusals ORDER BY refusal_id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        records: list[RefusalRecord] = []
        for row in rows:
            try:
                fields = tuple(json.loads(row["fields"] or "[]"))
            except ValueError:
                fields = ()
            records.append(
                RefusalRecord(at=row["at"], code=row["code"], consent_id=row["consent_id"] or "", fields=fields)
            )
        return tuple(records)

    # --- effacement --------------------------------------------------------

    def forget_everything(self) -> bool:
        """Efface tous les accords et tout le journal, puis compacte la base."""

        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM refusals")
            connection.execute("DELETE FROM consents")
            connection.commit()
        return self._compact()

    def _compact(self) -> bool:
        try:
            connection = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("VACUUM")
            finally:
                connection.close()
            self._tighten_permissions()
            return True
        except sqlite3.Error:
            return False

    def stats(self) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            counts = connection.execute(
                "SELECT state, COUNT(*) AS total FROM consents GROUP BY state"
            ).fetchall()
            refusals = connection.execute("SELECT COUNT(*) AS total FROM refusals").fetchone()
        return {
            "consents": {row["state"]: int(row["total"]) for row in counts},
            "refusals": int(refusals["total"]) if refusals is not None else 0,
            "db_name": self.db_path.name,
            "schema_version": STORE_SCHEMA_VERSION,
        }


__all__ = [
    "ConsentStore",
    "RefusalRecord",
    "DEFAULT_DB_NAME",
    "STORE_SCHEMA_VERSION",
    "STATES",
    "STATE_GRANTED",
    "STATE_USED",
    "STATE_REVOKED",
    "_now",
]
