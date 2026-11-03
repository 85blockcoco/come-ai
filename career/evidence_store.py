"""Persistance locale du centre de preuves.

Le stockage est volontairement bête : il écrit et relit des documents.  Il
n'analyse rien, ne décide rien et n'appelle jamais un réseau.

Choix structurants :

* **un fichier SQLite privé** — ``career_data/evidence/evidence.sqlite3``,
  lisible et inscriptible par la seule personne (``0600``), dans un
  répertoire ``0700``.  La base Career principale n'est pas touchée : le
  centre de preuves ne force aucune migration du schéma existant.
* **des colonnes JSON bornées** — étiquettes, pièces jointes, usages,
  sources additionnelles et historique de fusion sont des listes courtes et
  déterministes ; une table relationnelle n'apporterait rien ici.
* **des index explicites** — ``claim_key`` (regroupement par affirmation),
  ``evidence_type`` et ``created_at`` (tri), pour que la recherche et les
  statistiques restent locales et rapides.
* **rien de secret** — ni chemin d'origine, ni contenu de document : seules
  des métadonnées (nom de fichier, empreinte SHA-256, taille) sont indexées.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from workspace_core import UserFacingError

from .evidence import EvidenceItem, EvidenceUsage, claim_key
from .models import utc_now


TABLE_ITEMS = "evidence_items"
TABLE_MERGES = "evidence_merges"

#: Version du schéma de stockage local (le format d'export a sa propre version).
STORE_SCHEMA_VERSION = 1

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_ITEMS} (
    id TEXT PRIMARY KEY,
    claim TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    source_document TEXT NOT NULL DEFAULT '',
    source_location TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL DEFAULT '',
    evidence_type TEXT NOT NULL,
    confidence TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0, 1)),
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    attachments_json TEXT NOT NULL DEFAULT '[]',
    usage_json TEXT NOT NULL DEFAULT '[]',
    additional_sources_json TEXT NOT NULL DEFAULT '[]',
    merged_from_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS evidence_items_claim_idx ON {TABLE_ITEMS}(claim_key);
CREATE INDEX IF NOT EXISTS evidence_items_type_idx ON {TABLE_ITEMS}(evidence_type, created_at DESC);
CREATE INDEX IF NOT EXISTS evidence_items_created_idx ON {TABLE_ITEMS}(created_at DESC);

CREATE TABLE IF NOT EXISTS {TABLE_MERGES} (
    id TEXT PRIMARY KEY,
    keep_id TEXT NOT NULL,
    merged_ids_json TEXT NOT NULL DEFAULT '[]',
    snapshots_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS evidence_merges_created_idx ON {TABLE_MERGES}(created_at DESC);
"""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: Any, fallback: Any) -> Any:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed is not None else fallback


class EvidenceStore:
    """Interface de stockage du centre de preuves."""

    def save(self, item: EvidenceItem) -> None:
        raise NotImplementedError

    def get(self, evidence_id: str) -> EvidenceItem | None:
        raise NotImplementedError

    def delete(self, evidence_id: str) -> bool:
        raise NotImplementedError

    def all(self) -> list[EvidenceItem]:
        raise NotImplementedError

    def merge_items(self, keeper: EvidenceItem, merged_ids: list[str], snapshots: list[dict[str, Any]]) -> None:
        """Write the kept proof, erase the merged ones and record the history.

        The three writes must happen in **one** transaction : a merge that
        fails half-way would destroy a provenance without keeping its
        snapshot.
        """
        raise NotImplementedError

    def record_merge(self, keep_id: str, merged_ids: list[str], snapshots: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    def merges(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class SqliteEvidenceStore(EvidenceStore):
    """Store backed by one private SQLite file."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            pass
        try:
            self.ensure_schema()
        except sqlite3.DatabaseError:
            # Un fichier illisible ne doit pas empêcher l'espace Career de
            # démarrer : le fichier est mis de côté et le centre repart vide.
            self.quarantine_damaged_file()
            self.ensure_schema()

    def quarantine_damaged_file(self) -> Path | None:
        """Move a damaged database aside and return its new location."""
        if not self.db_path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = self.db_path.with_name(f"{self.db_path.name}.corrupt-{stamp}")
        try:
            os.replace(self.db_path, target)
        except OSError:
            return None
        for suffix in ("-wal", "-shm"):
            Path(f"{self.db_path}{suffix}").unlink(missing_ok=True)
        return target

    # -- schéma -------------------------------------------------------------
    @contextmanager
    def _raw_connection(self) -> Iterator[sqlite3.Connection]:
        """Open a connection without translating the driver errors."""
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise
        finally:
            connection.close()

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
                "Le centre de preuves a rencontré un problème. Réessaie."
            ) from error
        finally:
            connection.close()

    def ensure_schema(self) -> None:
        """Create the tables and the indexes when they are missing."""
        with self._raw_connection() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(f"PRAGMA user_version = {STORE_SCHEMA_VERSION}")
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    # -- lecture / écriture -------------------------------------------------
    def save(self, item: EvidenceItem) -> None:
        with self._connection() as connection:
            connection.execute(
                f"""
                INSERT INTO {TABLE_ITEMS} (
                    id, claim, claim_key, source_document, source_location, quote,
                    evidence_type, confidence, approved, blocked, created_at, updated_at,
                    expires_at, tags_json, attachments_json, usage_json,
                    additional_sources_json, merged_from_json
                ) VALUES (
                    :id, :claim, :claim_key, :source_document, :source_location, :quote,
                    :evidence_type, :confidence, :approved, :blocked, :created_at, :updated_at,
                    :expires_at, :tags_json, :attachments_json, :usage_json,
                    :additional_sources_json, :merged_from_json
                )
                ON CONFLICT(id) DO UPDATE SET
                    claim = excluded.claim,
                    claim_key = excluded.claim_key,
                    source_document = excluded.source_document,
                    source_location = excluded.source_location,
                    quote = excluded.quote,
                    evidence_type = excluded.evidence_type,
                    confidence = excluded.confidence,
                    approved = excluded.approved,
                    blocked = excluded.blocked,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    tags_json = excluded.tags_json,
                    attachments_json = excluded.attachments_json,
                    usage_json = excluded.usage_json,
                    additional_sources_json = excluded.additional_sources_json,
                    merged_from_json = excluded.merged_from_json
                """,
                self._row(item),
            )

    def get(self, evidence_id: str) -> EvidenceItem | None:
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT * FROM {TABLE_ITEMS} WHERE id = ?", (evidence_id,)
            ).fetchone()
        return self._item(row) if row else None

    def delete(self, evidence_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(f"DELETE FROM {TABLE_ITEMS} WHERE id = ?", (evidence_id,))
        return cursor.rowcount > 0

    def all(self) -> list[EvidenceItem]:
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM {TABLE_ITEMS} ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [self._item(row) for row in rows]

    def merge_items(self, keeper: EvidenceItem, merged_ids: list[str], snapshots: list[dict[str, Any]]) -> None:
        """Write the kept proof, erase the merged ones and record the history.

        The three writes happen in **one** transaction : a merge that fails
        half-way would destroy a provenance without keeping its snapshot.
        """
        with self._connection() as connection:
            connection.execute(
                f"""
                INSERT INTO {TABLE_ITEMS} (
                    id, claim, claim_key, source_document, source_location, quote,
                    evidence_type, confidence, approved, blocked, created_at, updated_at,
                    expires_at, tags_json, attachments_json, usage_json,
                    additional_sources_json, merged_from_json
                ) VALUES (
                    :id, :claim, :claim_key, :source_document, :source_location, :quote,
                    :evidence_type, :confidence, :approved, :blocked, :created_at, :updated_at,
                    :expires_at, :tags_json, :attachments_json, :usage_json,
                    :additional_sources_json, :merged_from_json
                )
                ON CONFLICT(id) DO UPDATE SET
                    claim = excluded.claim,
                    claim_key = excluded.claim_key,
                    source_document = excluded.source_document,
                    source_location = excluded.source_location,
                    quote = excluded.quote,
                    evidence_type = excluded.evidence_type,
                    confidence = excluded.confidence,
                    approved = excluded.approved,
                    blocked = excluded.blocked,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    tags_json = excluded.tags_json,
                    attachments_json = excluded.attachments_json,
                    usage_json = excluded.usage_json,
                    additional_sources_json = excluded.additional_sources_json,
                    merged_from_json = excluded.merged_from_json
                """,
                self._row(keeper),
            )
            for merged_id in merged_ids:
                connection.execute(f"DELETE FROM {TABLE_ITEMS} WHERE id = ?", (merged_id,))
            connection.execute(
                f"""
                INSERT INTO {TABLE_MERGES} (id, keep_id, merged_ids_json, snapshots_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"merge_{uuid.uuid4().hex[:12]}",
                    keeper.id,
                    _dump(list(merged_ids)),
                    _dump(list(snapshots)),
                    _timestamp(),
                ),
            )

    def record_merge(self, keep_id: str, merged_ids: list[str], snapshots: list[dict[str, Any]]) -> None:
        with self._connection() as connection:
            connection.execute(
                f"""
                INSERT INTO {TABLE_MERGES} (id, keep_id, merged_ids_json, snapshots_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"merge_{uuid.uuid4().hex[:12]}",
                    keep_id,
                    _dump(list(merged_ids)),
                    _dump(list(snapshots)),
                    _timestamp(),
                ),
            )

    def merges(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM {TABLE_MERGES} ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "keep_id": str(row["keep_id"]),
                "merged_ids": _load(row["merged_ids_json"], []),
                "snapshots": _load(row["snapshots_json"], []),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    # -- conversion ---------------------------------------------------------
    @staticmethod
    def _row(item: EvidenceItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "claim": item.claim,
            "claim_key": claim_key(item.claim),
            "source_document": item.source_document,
            "source_location": item.source_location,
            "quote": item.quote,
            "evidence_type": item.evidence_type,
            "confidence": item.confidence,
            "approved": 1 if item.approved else 0,
            "blocked": 1 if item.blocked else 0,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "expires_at": item.expires_at,
            "tags_json": _dump(list(item.tags)),
            "attachments_json": _dump([dict(entry) for entry in item.attachments]),
            "usage_json": _dump([usage.to_dict() for usage in item.usage]),
            "additional_sources_json": _dump([dict(source) for source in item.additional_sources]),
            "merged_from_json": _dump(list(item.merged_from)),
        }

    @staticmethod
    def _item(row: sqlite3.Row) -> EvidenceItem:
        usage = [EvidenceUsage.from_dict(entry) for entry in _load(row["usage_json"], [])]
        attachments = [dict(entry) for entry in _load(row["attachments_json"], []) if isinstance(entry, dict)]
        sources = [dict(entry) for entry in _load(row["additional_sources_json"], []) if isinstance(entry, dict)]
        return EvidenceItem(
            id=str(row["id"]),
            claim=str(row["claim"]),
            source_document=str(row["source_document"]),
            source_location=str(row["source_location"]),
            quote=str(row["quote"]),
            evidence_type=str(row["evidence_type"]),
            confidence=str(row["confidence"]),
            approved=bool(row["approved"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            tags=[str(tag) for tag in _load(row["tags_json"], [])],
            attachments=attachments,
            usage=usage,
            blocked=bool(row["blocked"]),
            expires_at=str(row["expires_at"]),
            merged_from=[str(entry) for entry in _load(row["merged_from_json"], [])],
            additional_sources=sources,
        )


class InMemoryEvidenceStore(EvidenceStore):
    """Volatile store used by the unit tests of the center.

    It follows exactly the same rules as the SQLite store — including the
    copy semantics : a stored proof cannot be modified by the caller without
    going through ``save``.
    """

    def __init__(self) -> None:
        self._items: dict[str, EvidenceItem] = {}
        self._merges: list[dict[str, Any]] = []

    @staticmethod
    def _copy(item: EvidenceItem) -> EvidenceItem:
        return EvidenceItem.from_dict(item.to_dict())

    def save(self, item: EvidenceItem) -> None:
        self._items[item.id] = self._copy(item)

    def get(self, evidence_id: str) -> EvidenceItem | None:
        item = self._items.get(evidence_id)
        return self._copy(item) if item is not None else None

    def delete(self, evidence_id: str) -> bool:
        return self._items.pop(evidence_id, None) is not None

    def all(self) -> list[EvidenceItem]:
        return [self._copy(item) for item in sorted(self._items.values(), key=lambda entry: (entry.created_at, entry.id))]

    def merge_items(self, keeper: EvidenceItem, merged_ids: list[str], snapshots: list[dict[str, Any]]) -> None:
        self._items[keeper.id] = self._copy(keeper)
        for merged_id in merged_ids:
            self._items.pop(merged_id, None)
        self.record_merge(keeper.id, list(merged_ids), list(snapshots))

    def record_merge(self, keep_id: str, merged_ids: list[str], snapshots: list[dict[str, Any]]) -> None:
        self._merges.append(
            {
                "id": f"merge_{uuid.uuid4().hex[:12]}",
                "keep_id": keep_id,
                "merged_ids": list(merged_ids),
                "snapshots": list(snapshots),
                "created_at": _timestamp(),
            }
        )

    def merges(self) -> list[dict[str, Any]]:
        return list(reversed(self._merges))


def _timestamp() -> str:
    return utc_now()
