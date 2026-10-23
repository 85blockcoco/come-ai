"""Versioned persistence of the offer-intelligence snapshots (SPEC SK-07).

WHERE THE SNAPSHOT LIVES
The derived analysis of an offer is stored **beside** the offer, in its own
table.  The ``jobs`` table is not extended with dozens of columns: the
snapshot is one bounded JSON document, versioned by the fingerprint of the
source text.

HOW THE VERSIONS WORK
- The first analysis of an offer creates version 1.
- A re-import whose source content is **identical** keeps the same version and
  the same derived identifiers: nothing is recomputed behind the user's back.
- A re-import whose source content **changed** creates a new version.  The
  previous version stays in the history (it remains auditable) but it is never
  presented as the current analysis, so a stale citation can never be shown as
  the present truth.
- User state (personal note, shortlist, application stage, approved profile)
  lives in its own tables and is never rewritten by a snapshot write.

The module is deliberately dumb: it stores and reads documents.  It performs no
analysis of its own.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from .offer_intelligence import OfferIntelligenceSnapshot, snapshot_summary

TABLE_NAME = "job_offer_intelligence_snapshots"

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{{}}',
    snapshot_json TEXT NOT NULL DEFAULT '{{}}',
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, version)
);
CREATE INDEX IF NOT EXISTS idx_offer_intelligence_current
    ON {TABLE_NAME}(job_id, is_current);
CREATE INDEX IF NOT EXISTS idx_offer_intelligence_hash
    ON {TABLE_NAME}(job_id, source_hash);
"""


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the snapshot table when it does not exist yet."""
    connection.executescript(SCHEMA_SQL)


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def store_snapshot(
    connection: sqlite3.Connection,
    snapshot: OfferIntelligenceSnapshot | Mapping[str, Any],
    *,
    now: str,
) -> dict[str, Any]:
    """Store one snapshot and return its version state.

    The function returns ``{"version": int, "created": bool, "source_hash":
    str, "changed": bool}``.  ``created`` is false when the very same source
    content was already the current analysis: the version and the identifiers
    are then preserved untouched.
    """
    if isinstance(snapshot, OfferIntelligenceSnapshot):
        payload = snapshot.to_dict()
    else:
        payload = dict(snapshot or {})
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("un snapshot d’offre intelligence doit porter un job_id")
    source_hash = str(payload.get("source_hash") or "").strip()
    if not source_hash:
        raise ValueError("un snapshot d’offre intelligence doit porter un source_hash")
    schema_version = int(payload.get("schema_version") or 1)
    summary = snapshot_summary(payload)

    current = connection.execute(
        f"SELECT version, source_hash FROM {TABLE_NAME} "
        "WHERE job_id = ? AND is_current = 1",
        (job_id,),
    ).fetchone()

    if current is not None and str(current["source_hash"]) == source_hash:
        # Identical source content: the analysis and its identifiers stay.
        # The document keeps its first derivation date and only refreshes its
        # last update: the audit trail of a version never rewrites itself.
        previous = connection.execute(
            f"SELECT snapshot_json FROM {TABLE_NAME} WHERE job_id = ? AND version = ?",
            (job_id, int(current["version"])),
        ).fetchone()
        payload = _with_audit_dates(payload, previous, now)
        summary = snapshot_summary(payload)
        connection.execute(
            f"UPDATE {TABLE_NAME} SET summary_json = ?, snapshot_json = ?, updated_at = ? "
            "WHERE job_id = ? AND version = ?",
            (_json(summary), _json(payload), now, job_id, int(current["version"])),
        )
        return {
            "version": int(current["version"]),
            "created": False,
            "changed": False,
            "source_hash": source_hash,
        }

    highest = connection.execute(
        f"SELECT MAX(version) AS version FROM {TABLE_NAME} WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    version = int(highest["version"] or 0) + 1
    connection.execute(
        f"UPDATE {TABLE_NAME} SET is_current = 0 WHERE job_id = ?", (job_id,)
    )
    payload = _with_audit_dates(payload, None, now)
    summary = snapshot_summary(payload)
    connection.execute(
        f"""
        INSERT INTO {TABLE_NAME} (
            job_id, version, schema_version, source_hash,
            summary_json, snapshot_json, is_current, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            job_id,
            version,
            schema_version,
            source_hash,
            _json(summary),
            _json(payload),
            now,
            now,
        ),
    )
    return {
        "version": version,
        "created": True,
        "changed": current is not None,
        "source_hash": source_hash,
    }


def load_current(
    connection: sqlite3.Connection, job_id: str
) -> dict[str, Any] | None:
    """Return the current snapshot of one offer, or ``None``."""
    row = connection.execute(
        f"SELECT version, schema_version, source_hash, snapshot_json, created_at, updated_at "
        f"FROM {TABLE_NAME} WHERE job_id = ? AND is_current = 1",
        (job_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "version": int(row["version"]),
        "schema_version": int(row["schema_version"]),
        "source_hash": str(row["source_hash"]),
        "snapshot": _decode(row["snapshot_json"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def load_snapshot(
    connection: sqlite3.Connection, job_id: str
) -> dict[str, Any] | None:
    """Return the current snapshot document of one offer, or ``None``."""
    current = load_current(connection, job_id)
    return current["snapshot"] if current else None


def load_history(connection: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    """Return the version history of one offer, newest first.

    Only the metadata is returned: the history proves which analysis was
    replaced, it never re-presents an outdated citation as the current one.
    """
    rows = connection.execute(
        f"""
        SELECT version, schema_version, source_hash, summary_json, is_current, created_at, updated_at
        FROM {TABLE_NAME}
        WHERE job_id = ?
        ORDER BY version DESC
        """,
        (job_id,),
    ).fetchall()
    history: list[dict[str, Any]] = []
    for row in rows:
        try:
            summary = json.loads(row["summary_json"] or "{}")
        except (TypeError, ValueError):
            summary = {}
        history.append(
            {
                "version": int(row["version"]),
                "schema_version": int(row["schema_version"]),
                "source_hash": str(row["source_hash"]),
                "is_current": bool(row["is_current"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "summary": summary if isinstance(summary, dict) else {},
            }
        )
    return history


def load_summary(
    connection: sqlite3.Connection, job_id: str
) -> dict[str, Any] | None:
    """Return the compact summary of the current snapshot, or ``None``."""
    row = connection.execute(
        f"SELECT summary_json FROM {TABLE_NAME} WHERE job_id = ? AND is_current = 1",
        (job_id,),
    ).fetchone()
    if not row:
        return None
    try:
        summary = json.loads(row["summary_json"] or "{}")
    except (TypeError, ValueError):
        return None
    return summary if isinstance(summary, dict) else None


def delete_snapshots(connection: sqlite3.Connection, job_id: str) -> int:
    """Remove every snapshot of one offer (used when the offer is deleted)."""
    cursor = connection.execute(f"DELETE FROM {TABLE_NAME} WHERE job_id = ?", (job_id,))
    return int(cursor.rowcount or 0)


def _decode(raw: Any) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _with_audit_dates(
    payload: dict[str, Any],
    previous: Any,
    now: str,
) -> dict[str, Any]:
    """Stamp a snapshot document with its first and last derivation date.

    The first derivation date of a version is never rewritten: re-importing an
    unchanged offer refreshes the analysis, not its history.
    """
    document = dict(payload)
    created_at = None
    if previous is not None:
        try:
            stored = json.loads(previous["snapshot_json"] or "{}")
        except (TypeError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            created_at = stored.get("created_at")
    document["created_at"] = created_at or document.get("created_at") or now
    document["updated_at"] = now
    return document


__all__ = [
    "SCHEMA_SQL",
    "TABLE_NAME",
    "delete_snapshots",
    "ensure_schema",
    "load_current",
    "load_history",
    "load_snapshot",
    "load_summary",
    "store_snapshot",
]
