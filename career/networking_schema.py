"""Local SQLite schema and storage for the networking directory (SPEC-040).

Everything lives in a local SQLite file owned by the user.  Nothing here talks
to the network: contacts come from the user's own LinkedIn export, from
traceable public facts entered by the user, or from manual entries.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import clean_text

NETWORKING_SCHEMA_VERSION = 1

SOURCE_LINKEDIN_EXPORT = "linkedin_export"
SOURCE_WEB_RESEARCHER = "web_researcher"
SOURCE_MANUAL = "manual"
ALLOWED_SOURCES = (SOURCE_LINKEDIN_EXPORT, SOURCE_WEB_RESEARCHER, SOURCE_MANUAL)

RELATION_FIRST = "first"
RELATION_SECOND = "second"
RELATION_ALUMNI = "alumni"
RELATION_UNKNOWN = "unknown"
ALLOWED_RELATIONS = (RELATION_FIRST, RELATION_SECOND, RELATION_ALUMNI, RELATION_UNKNOWN)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS networking_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    headline TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    school TEXT NOT NULL DEFAULT '',
    relation TEXT NOT NULL DEFAULT 'unknown',
    email TEXT NOT NULL DEFAULT '',
    profile_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    last_contact_at TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    provenance TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (full_name, company, source)
);
CREATE TABLE IF NOT EXISTS networking_profile_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (kind, value, source)
);
CREATE TABLE IF NOT EXISTS networking_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    rows_total INTEGER NOT NULL DEFAULT 0,
    rows_imported INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_relation(value: Any) -> str:
    """Map French labels ("1er", "2nd") and loose spellings onto the closed relation list."""
    text = clean_text(value, limit=40).lower()
    if not text:
        return RELATION_UNKNOWN
    if text in ("1er", "premier", "1st", "first", "1"):
        return RELATION_FIRST
    if text in ("2nd", "second", "2", "deuxième", "deuxieme"):
        return RELATION_SECOND
    if "alumn" in text or text in ("école", "ecole", "school"):
        return RELATION_ALUMNI
    return RELATION_UNKNOWN


def _normalize_source(value: Any) -> str:
    text = clean_text(value, limit=40) or SOURCE_MANUAL
    return text if text in ALLOWED_SOURCES else SOURCE_MANUAL


@dataclass(frozen=True)
class Contact:
    """A local networking contact.  ``provenance`` cites who says what, and where."""

    id: int
    full_name: str
    headline: str = ""
    company: str = ""
    school: str = ""
    relation: str = RELATION_UNKNOWN
    email: str = ""
    profile_url: str = ""
    notes: str = ""
    last_contact_at: str = ""
    next_action: str = ""
    source: str = SOURCE_MANUAL
    provenance: list[dict[str, str]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ProfileFact:
    """A fact about the user themself (school, role...) with its provenance."""

    id: int
    kind: str
    value: str
    source: str
    origin: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ImportRecord:
    id: int
    filename: str
    kind: str
    source: str
    rows_total: int
    rows_imported: int
    imported_at: str


class NetworkingStore:
    """Small, self-contained SQLite store for contacts, profile facts and imports."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            # Removes residual bytes from deleted rows; the directory stays purgable.
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(_SCHEMA)

    # ------------------------------------------------------------------ contacts
    def upsert_contact(
        self,
        *,
        full_name: str,
        headline: str = "",
        company: str = "",
        school: str = "",
        relation: Any = RELATION_UNKNOWN,
        email: str = "",
        profile_url: str = "",
        source: str = SOURCE_MANUAL,
        provenance: list[dict[str, str]] | None = None,
    ) -> Contact:
        """Insert a contact, or refresh imported fields without touching user fields.

        ``notes``, ``last_contact_at`` and ``next_action`` belong to the user and are
        never overwritten by a re-import.
        """
        name = clean_text(full_name, limit=200)
        if not name:
            raise ValueError("un contact doit au moins avoir un nom")
        stored_source = _normalize_source(source)
        now = _now_iso()
        provenance_json = json.dumps(provenance or [], ensure_ascii=False)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO networking_contacts
                    (full_name, headline, company, school, relation, email, profile_url,
                     source, provenance, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (full_name, company, source) DO UPDATE SET
                    headline = CASE WHEN excluded.headline != '' THEN excluded.headline ELSE networking_contacts.headline END,
                    school = CASE WHEN excluded.school != '' THEN excluded.school ELSE networking_contacts.school END,
                    email = CASE WHEN excluded.email != '' THEN excluded.email ELSE networking_contacts.email END,
                    profile_url = CASE WHEN excluded.profile_url != '' THEN excluded.profile_url ELSE networking_contacts.profile_url END,
                    relation = CASE WHEN excluded.relation != 'unknown' THEN excluded.relation ELSE networking_contacts.relation END,
                    provenance = CASE WHEN excluded.provenance != '[]' THEN excluded.provenance ELSE networking_contacts.provenance END,
                    updated_at = excluded.updated_at
                """,
                (
                    name,
                    clean_text(headline, limit=300),
                    clean_text(company, limit=200),
                    clean_text(school, limit=200),
                    normalize_relation(relation),
                    clean_text(email, limit=200),
                    clean_text(profile_url, limit=500),
                    stored_source,
                    provenance_json,
                    now,
                    now,
                ),
            )
            # lastrowid is unreliable on the UPDATE branch of the upsert: fetch the row by its key.
            row = connection.execute(
                "SELECT * FROM networking_contacts WHERE full_name = ? AND company = ? AND source = ?",
                (name, clean_text(company, limit=200), stored_source),
            ).fetchone()
            if row is None:
                raise ValueError(f"impossible de relire le contact {name!r}")
            return self._contact_from_row(row)

    def get_contact(self, contact_id: int) -> Contact | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM networking_contacts WHERE id = ?", (contact_id,)
            ).fetchone()
            return self._contact_from_row(row) if row else None

    def list_contacts(self, source: str | None = None) -> list[Contact]:
        query = "SELECT * FROM networking_contacts"
        params: tuple[Any, ...] = ()
        if source:
            query += " WHERE source = ?"
            params = (_normalize_source(source),)
        query += " ORDER BY full_name COLLATE NOCASE, id"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
            return [self._contact_from_row(row) for row in rows]

    def update_contact_fields(
        self,
        contact_id: int,
        *,
        notes: str | None = None,
        last_contact_at: str | None = None,
        next_action: str | None = None,
        school: str | None = None,
        relation: Any = None,
    ) -> Contact:
        """Update user-owned fields (notes, follow-up) on an existing contact."""
        assignments: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("notes", notes),
            ("last_contact_at", last_contact_at),
            ("next_action", next_action),
            ("school", school),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                params.append(clean_text(value, limit=2_000))
        if relation is not None:
            assignments.append("relation = ?")
            params.append(normalize_relation(relation))
        if not assignments:
            return self.get_contact(contact_id)  # type: ignore[return-value]
        assignments.append("updated_at = ?")
        params.append(_now_iso())
        params.append(contact_id)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE networking_contacts SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
        updated = self.get_contact(contact_id)
        if updated is None:
            raise ValueError(f"contact {contact_id} introuvable")
        return updated

    @staticmethod
    def _contact_from_row(row: sqlite3.Row) -> Contact:
        try:
            provenance = json.loads(row["provenance"] or "[]")
        except (TypeError, ValueError):
            provenance = []
        if not isinstance(provenance, list):
            provenance = []
        return Contact(
            id=int(row["id"]),
            full_name=row["full_name"],
            headline=row["headline"],
            company=row["company"],
            school=row["school"],
            relation=row["relation"],
            email=row["email"],
            profile_url=row["profile_url"],
            notes=row["notes"],
            last_contact_at=row["last_contact_at"],
            next_action=row["next_action"],
            source=row["source"],
            provenance=[item for item in provenance if isinstance(item, dict)],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------- profile facts
    def add_profile_fact(self, *, kind: str, value: str, source: str, origin: str = "") -> ProfileFact:
        fact_kind = clean_text(kind, limit=60).lower()
        fact_value = clean_text(value, limit=300)
        if not fact_kind or not fact_value:
            raise ValueError("un fait de profil requiert un type et une valeur")
        stored_source = _normalize_source(source)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO networking_profile_facts (kind, value, source, origin, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (kind, value, source) DO NOTHING
                """,
                (fact_kind, fact_value, stored_source, clean_text(origin, limit=300), _now_iso()),
            )
            row_id = cursor.lastrowid
            if row_id is None:
                row = connection.execute(
                    "SELECT * FROM networking_profile_facts WHERE kind = ? AND value = ? AND source = ?",
                    (fact_kind, fact_value, stored_source),
                ).fetchone()
                row_id = int(row["id"])
            return ProfileFact(
                id=int(row_id),
                kind=fact_kind,
                value=fact_value,
                source=stored_source,
                origin=clean_text(origin, limit=300),
                created_at=_now_iso(),
            )

    def list_profile_facts(self, kind: str | None = None) -> list[ProfileFact]:
        query = "SELECT * FROM networking_profile_facts"
        params: tuple[Any, ...] = ()
        if kind:
            query += " WHERE kind = ?"
            params = (clean_text(kind, limit=60).lower(),)
        query += " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
            return [
                ProfileFact(
                    id=int(row["id"]),
                    kind=row["kind"],
                    value=row["value"],
                    source=row["source"],
                    origin=row["origin"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    # -------------------------------------------------------------------- imports
    def record_import(self, *, filename: str, kind: str, source: str, rows_total: int, rows_imported: int) -> ImportRecord:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO networking_imports (filename, kind, source, rows_total, rows_imported, imported_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_text(filename, limit=300),
                    clean_text(kind, limit=60),
                    _normalize_source(source),
                    max(0, int(rows_total)),
                    max(0, int(rows_imported)),
                    _now_iso(),
                ),
            )
            return ImportRecord(
                id=int(cursor.lastrowid),
                filename=clean_text(filename, limit=300),
                kind=clean_text(kind, limit=60),
                source=_normalize_source(source),
                rows_total=max(0, int(rows_total)),
                rows_imported=max(0, int(rows_imported)),
                imported_at=_now_iso(),
            )

    def list_imports(self) -> list[ImportRecord]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM networking_imports ORDER BY id").fetchall()
            return [
                ImportRecord(
                    id=int(row["id"]),
                    filename=row["filename"],
                    kind=row["kind"],
                    source=row["source"],
                    rows_total=int(row["rows_total"]),
                    rows_imported=int(row["rows_imported"]),
                    imported_at=row["imported_at"],
                )
                for row in rows
            ]

    # ---------------------------------------------------------------------- purge
    def purge(self, *, older_than_days: int | None = None, force: bool = False) -> int:
        """Delete contacts locally.

        Without ``older_than_days`` this is a full wipe and requires ``force=True``
        so nothing is destroyed by accident.  With a retention window, only
        contacts whose last contact (or last update) is older are removed.
        Returns the number of contacts deleted.
        """
        if older_than_days is None:
            if not force:
                raise ValueError("purge totale refusée sans force=True (confirmation explicite)")
            with self._connection() as connection:
                deleted = connection.execute("DELETE FROM networking_contacts").rowcount
                connection.execute("DELETE FROM networking_profile_facts")
                connection.execute("DELETE FROM networking_imports")
                return int(deleted or 0)
        retention = int(older_than_days)
        if retention < 0:
            raise ValueError("older_than_days doit être positif")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention)).isoformat(timespec="seconds")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM networking_contacts
                WHERE MAX(last_contact_at, updated_at) != '' AND MAX(last_contact_at, updated_at) < ?
                """,
                (cutoff,),
            )
            return int(cursor.rowcount or 0)

    # --------------------------------------------------------------------- misc
    def counts(self) -> dict[str, int]:
        with self._connection() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "networking_contacts",
                    "networking_profile_facts",
                    "networking_imports",
                )
            }


def contact_with_changes(contact: Contact, **changes: Any) -> Contact:
    """Return a copy of ``contact`` with the given fields replaced (helper for callers)."""
    return replace(contact, **changes)
