"""Local persistence of the candidate profile: documents, facts and decisions.

The store keeps three things apart:

* the **source document** and its text, so every quote can be checked again;
* the **facts** proposed from that document, each one with its provenance;
* the **decisions** of the user: proposed, approved, rejected, modified or
  suspended.

The user always wins: re-reading the same document proposes the same facts
(it never duplicates them) and never overwrites a decision already taken.

The store is local SQLite, created on demand with ``CREATE TABLE IF NOT
EXISTS`` so it can live beside the other Career data without any migration
of the application schema.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

from .candidate_profile import (
    ACTOR_SYSTEM,
    ACTOR_USER,
    FACT_STATUSES,
    STATUS_APPROVED,
    STATUS_MODIFIED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_SUSPENDED,
    AutoApprovalError,
    CandidateProfile,
    FactTransitionError,
    ProfileFact,
    ProfileError,
    Provenance,
    SourceDocument,
    transition_fact,
)
from .models import clean_text, utc_now


DOCUMENTS_TABLE = "candidate_profile_documents"
FACTS_TABLE = "candidate_profile_facts"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {DOCUMENTS_TABLE} (
    document_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL DEFAULT '',
    filetype TEXT NOT NULL DEFAULT '',
    page_count INTEGER,
    extraction TEXT NOT NULL DEFAULT 'text_layer',
    sha256 TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS {FACTS_TABLE} (
    fact_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed',
    source_id TEXT NOT NULL DEFAULT '',
    source_filename TEXT NOT NULL DEFAULT '',
    source_filetype TEXT NOT NULL DEFAULT '',
    source_page INTEGER,
    source_start INTEGER NOT NULL DEFAULT 0,
    source_end INTEGER NOT NULL DEFAULT 0,
    source_quote TEXT NOT NULL DEFAULT '',
    extraction TEXT NOT NULL DEFAULT 'text_layer',
    source_sha256 TEXT NOT NULL DEFAULT '',
    attributes_json TEXT NOT NULL DEFAULT '{{}}',
    previous_value TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS candidate_profile_facts_document
    ON {FACTS_TABLE} (document_id);
"""


class ProfileStoreError(ProfileError):
    """The local profile store could not be used."""


class ProfileStore:
    """Read and write the candidate profile in the local Career database."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._ready = False

    # -- plumbing ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def ensure_schema(self) -> None:
        """Create the two tables of the profile when they do not exist yet."""
        with self._lock:
            if self._ready:
                return
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                with self._connect() as connection:
                    connection.executescript(_SCHEMA)
                    connection.commit()
            except sqlite3.Error as error:
                raise ProfileStoreError(
                    "Le profil candidat local n’a pas pu être initialisé."
                ) from error
            self._ready = True

    # -- documents --------------------------------------------------------

    def save_document(self, document: SourceDocument) -> None:
        """Store the source document and its text."""
        self.ensure_schema()
        with self._lock, self._connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {DOCUMENTS_TABLE}
                    (document_id, filename, filetype, page_count, extraction, sha256, text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    filename = excluded.filename,
                    filetype = excluded.filetype,
                    page_count = excluded.page_count,
                    extraction = excluded.extraction,
                    sha256 = excluded.sha256,
                    text = excluded.text
                """,
                (
                    document.document_id,
                    document.filename,
                    document.filetype,
                    document.page_count,
                    document.extraction,
                    document.sha256,
                    document.text,
                    document.created_at,
                ),
            )
            connection.commit()

    def get_document(self, document_id: str) -> SourceDocument | None:
        """Return one stored document."""
        self.ensure_schema()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {DOCUMENTS_TABLE} WHERE document_id = ?",
                (clean_text(document_id, limit=120),),
            ).fetchone()
        if row is None:
            return None
        return SourceDocument(
            document_id=row["document_id"],
            filename=row["filename"],
            filetype=row["filetype"],
            page_count=row["page_count"],
            text=row["text"],
            extraction=row["extraction"],
            sha256=row["sha256"],
            created_at=row["created_at"],
        )

    def list_documents(self) -> list[dict[str, Any]]:
        """Return the stored documents, newest first, without their text."""
        self.ensure_schema()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT d.*, (
                    SELECT COUNT(*) FROM {FACTS_TABLE} f WHERE f.document_id = d.document_id
                ) AS fact_count
                FROM {DOCUMENTS_TABLE} d
                ORDER BY d.created_at DESC, d.document_id
                """
            ).fetchall()
        return [
            {
                "document_id": row["document_id"],
                "filename": row["filename"],
                "filetype": row["filetype"],
                "page_count": row["page_count"],
                "extraction": row["extraction"],
                "sha256": row["sha256"],
                "created_at": row["created_at"],
                "text_chars": len(row["text"] or ""),
                "fact_count": row["fact_count"],
            }
            for row in rows
        ]

    def delete_document(self, document_id: str) -> int:
        """Delete one document and every fact read from it."""
        self.ensure_schema()
        identifier = clean_text(document_id, limit=120)
        with self._lock, self._connect() as connection:
            deleted = connection.execute(
                f"DELETE FROM {FACTS_TABLE} WHERE document_id = ?", (identifier,)
            ).rowcount
            connection.execute(
                f"DELETE FROM {DOCUMENTS_TABLE} WHERE document_id = ?", (identifier,)
            )
            connection.commit()
        return int(deleted)

    # -- facts ------------------------------------------------------------

    def save_facts(self, facts: Iterable[ProfileFact], *, now: str = "") -> int:
        """Store the facts proposed for a document.

        A fact already decided by the user keeps its status and its value:
        a new extraction proposes, it never decides.
        """
        self.ensure_schema()
        stamp = clean_text(now, limit=64) or utc_now()
        stored = 0
        with self._lock, self._connect() as connection:
            for fact in facts:
                existing = connection.execute(
                    f"SELECT status, value FROM {FACTS_TABLE} WHERE fact_id = ?",
                    (fact.fact_id,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        f"""
                        INSERT INTO {FACTS_TABLE} (
                            fact_id, document_id, kind, label, value, status,
                            source_id, source_filename, source_filetype, source_page,
                            source_start, source_end, source_quote, extraction,
                            source_sha256, attributes_json, previous_value,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        self._fact_row(fact, status=fact.status, stamp=stamp),
                    )
                    stored += 1
                    continue
                if existing["status"] in (STATUS_APPROVED, STATUS_MODIFIED):
                    # The user already decided: only the evidence is refreshed.
                    connection.execute(
                        f"""
                        UPDATE {FACTS_TABLE}
                        SET source_page = ?, source_start = ?, source_end = ?,
                            source_quote = ?, extraction = ?, source_sha256 = ?,
                            updated_at = ?
                        WHERE fact_id = ?
                        """,
                        (
                            fact.provenance.page,
                            fact.provenance.start_offset,
                            fact.provenance.end_offset,
                            fact.provenance.quote,
                            fact.provenance.extraction,
                            fact.provenance.source_sha256,
                            stamp,
                            fact.fact_id,
                        ),
                    )
                    continue
                connection.execute(
                    f"""
                    UPDATE {FACTS_TABLE}
                    SET document_id = ?, kind = ?, label = ?, value = ?, status = ?,
                        source_id = ?, source_filename = ?, source_filetype = ?,
                        source_page = ?, source_start = ?, source_end = ?,
                        source_quote = ?, extraction = ?, source_sha256 = ?,
                        attributes_json = ?, updated_at = ?
                    WHERE fact_id = ?
                    """,
                    (
                        fact.provenance.source_id,
                        fact.kind,
                        fact.label,
                        fact.value,
                        STATUS_PROPOSED,
                        fact.provenance.source_id,
                        fact.provenance.filename,
                        fact.provenance.filetype,
                        fact.provenance.page,
                        fact.provenance.start_offset,
                        fact.provenance.end_offset,
                        fact.provenance.quote,
                        fact.provenance.extraction,
                        fact.provenance.source_sha256,
                        json.dumps(fact.attributes, ensure_ascii=False, sort_keys=True),
                        stamp,
                        fact.fact_id,
                    ),
                )
                stored += 1
            connection.commit()
        return stored

    def _fact_row(self, fact: ProfileFact, *, status: str, stamp: str) -> tuple[Any, ...]:
        return (
            fact.fact_id,
            fact.provenance.source_id,
            fact.kind,
            fact.label,
            fact.value,
            status,
            fact.provenance.source_id,
            fact.provenance.filename,
            fact.provenance.filetype,
            fact.provenance.page,
            fact.provenance.start_offset,
            fact.provenance.end_offset,
            fact.provenance.quote,
            fact.provenance.extraction,
            fact.provenance.source_sha256,
            json.dumps(fact.attributes, ensure_ascii=False, sort_keys=True),
            fact.previous_value,
            fact.created_at or stamp,
            stamp,
        )

    def list_facts(self, *, document_id: str = "") -> list[ProfileFact]:
        """Return the stored facts, ordered by their position in the source."""
        self.ensure_schema()
        query = f"SELECT * FROM {FACTS_TABLE}"
        parameters: tuple[Any, ...] = ()
        if document_id:
            query += " WHERE document_id = ?"
            parameters = (clean_text(document_id, limit=120),)
        query += " ORDER BY source_start, fact_id"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_fact_from_row(row) for row in rows]

    def get_fact(self, fact_id: str) -> ProfileFact | None:
        """Return one stored fact."""
        self.ensure_schema()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {FACTS_TABLE} WHERE fact_id = ?",
                (clean_text(fact_id, limit=120),),
            ).fetchone()
        if row is None:
            return None
        return _fact_from_row(row)

    def set_status(
        self,
        fact_id: str,
        status: str,
        *,
        actor: str = ACTOR_USER,
        value: str | None = None,
        now: str = "",
    ) -> ProfileFact:
        """Apply the decision of the user to one fact.

        The transition rules of the model are enforced, and an OCR fact can
        only be approved by a user.
        """
        self.ensure_schema()
        if status not in FACT_STATUSES:
            raise FactTransitionError(f"Statut inconnu : {status}")
        fact = self.get_fact(fact_id)
        if fact is None:
            raise ProfileStoreError("Ce fait de profil n’existe pas.")
        updated = transition_fact(fact, status, actor=actor, value=value, now=now or utc_now())
        with self._lock, self._connect() as connection:
            connection.execute(
                f"""
                UPDATE {FACTS_TABLE}
                SET value = ?, status = ?, previous_value = ?, updated_at = ?
                WHERE fact_id = ?
                """,
                (updated.value, updated.status, updated.previous_value, updated.updated_at, updated.fact_id),
            )
            connection.commit()
        return updated

    def approve(self, fact_id: str, *, actor: str = ACTOR_USER, now: str = "") -> ProfileFact:
        """Approve one fact (a user action)."""
        return self.set_status(fact_id, STATUS_APPROVED, actor=actor, now=now)

    def reject(self, fact_id: str, *, actor: str = ACTOR_USER, now: str = "") -> ProfileFact:
        """Reject one fact."""
        return self.set_status(fact_id, STATUS_REJECTED, actor=actor, now=now)

    def suspend(self, fact_id: str, *, actor: str = ACTOR_USER, now: str = "") -> ProfileFact:
        """Set one fact aside for now."""
        return self.set_status(fact_id, STATUS_SUSPENDED, actor=actor, now=now)

    def modify(self, fact_id: str, value: str, *, actor: str = ACTOR_USER, now: str = "") -> ProfileFact:
        """Correct the value of one fact."""
        return self.set_status(fact_id, STATUS_MODIFIED, actor=actor, value=value, now=now)

    def delete_fact(self, fact_id: str) -> bool:
        """Delete one fact.  Returns whether something was deleted."""
        self.ensure_schema()
        with self._lock, self._connect() as connection:
            deleted = connection.execute(
                f"DELETE FROM {FACTS_TABLE} WHERE fact_id = ?",
                (clean_text(fact_id, limit=120),),
            ).rowcount
            connection.commit()
        return bool(deleted)

    def clear(self) -> dict[str, int]:
        """Delete every document and every fact of the profile."""
        self.ensure_schema()
        with self._lock, self._connect() as connection:
            facts = connection.execute(f"DELETE FROM {FACTS_TABLE}").rowcount
            documents = connection.execute(f"DELETE FROM {DOCUMENTS_TABLE}").rowcount
            connection.commit()
        return {"facts": int(facts), "documents": int(documents)}

    # -- reading ----------------------------------------------------------

    def counts(self, facts: Sequence[ProfileFact] | None = None) -> dict[str, int]:
        """Return the number of facts per status."""
        facts = self.list_facts() if facts is None else facts
        counts = {status: 0 for status in FACT_STATUSES}
        for fact in facts:
            counts[fact.status] = counts.get(fact.status, 0) + 1
        return counts

    def active_facts(self) -> tuple[ProfileFact, ...]:
        """Return the facts that may justify a matching or an application."""
        return tuple(fact for fact in self.list_facts() if fact.is_justifiable)

    def export_profile(self, *, include_source: bool = True) -> dict[str, Any]:
        """Return the portable profile: facts, decisions and provenance."""
        facts = self.list_facts()
        documents = self.list_documents()
        exported_documents: list[dict[str, Any]] = []
        for document in documents:
            stored = self.get_document(document["document_id"])
            payload = dict(document)
            if include_source and stored is not None:
                payload["text"] = stored.text
            exported_documents.append(payload)
        return {
            "schema": "come-candidate-profile/1",
            "documents": exported_documents,
            "facts": [fact.to_dict() for fact in facts],
            "counts": self.counts(facts),
            "active_facts": [fact.fact_id for fact in facts if fact.is_justifiable],
        }

    def profile(self, *, document_id: str = "") -> CandidateProfile:
        """Return the profile as a model object."""
        facts = self.list_facts(document_id=document_id)
        documents = self.list_documents()
        document = None
        if documents:
            identifier = document_id or documents[0]["document_id"]
            document = self.get_document(identifier)
        if document is None:
            document = SourceDocument(document_id="", filename="", filetype="", page_count=None, text="")
        return CandidateProfile(document=document, facts=tuple(facts))


def _fact_from_row(row: sqlite3.Row) -> ProfileFact:
    """Rebuild a fact from a stored row."""
    try:
        attributes = json.loads(row["attributes_json"] or "{}")
    except (TypeError, ValueError):
        attributes = {}
    if not isinstance(attributes, dict):
        attributes = {}
    provenance = Provenance(
        source_id=row["source_id"],
        filename=row["source_filename"],
        filetype=row["source_filetype"],
        page=row["source_page"],
        start_offset=row["source_start"],
        end_offset=row["source_end"],
        quote=row["source_quote"],
        extraction=row["extraction"],
        source_sha256=row["source_sha256"],
    )
    return ProfileFact(
        fact_id=row["fact_id"],
        kind=row["kind"],
        label=row["label"],
        value=row["value"],
        status=row["status"],
        provenance=provenance,
        attributes={str(key): str(value) for key, value in attributes.items()},
        previous_value=row["previous_value"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = [
    "ACTOR_SYSTEM",
    "ACTOR_USER",
    "AutoApprovalError",
    "ProfileStore",
    "ProfileStoreError",
    "STATUS_APPROVED",
    "STATUS_MODIFIED",
    "STATUS_PROPOSED",
    "STATUS_REJECTED",
    "STATUS_SUSPENDED",
]
