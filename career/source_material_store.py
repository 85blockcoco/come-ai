"""Bounded, versioned local storage for fields copied from public sources.

Source material is kept separate from qualification facts and derived offer
intelligence. It preserves what a connector received without asserting that a
published value is correct.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Mapping

from .models import clean_text
from .source_fields import collect_source_fields

TABLE_NAME = "job_source_material_snapshots"
MAX_MATERIAL_BYTES = 32_000
MAX_CONFLICTS = 25

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    material_json TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, version)
);
CREATE INDEX IF NOT EXISTS idx_source_material_current
    ON {TABLE_NAME}(job_id, is_current);
"""


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)


def _bounded_material(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_fields = payload.get("source_fields")
    fields: dict[str, dict[str, Any]] = {}
    if isinstance(raw_fields, Mapping):
        for provider, values in list(raw_fields.items())[:8]:
            if not isinstance(values, Mapping):
                continue
            key = clean_text(provider, limit=40).lower()
            if not key:
                continue
            try:
                fields.update(collect_source_fields(key, values))
            except (TypeError, ValueError):
                continue
    raw_conflicts = payload.get("source_conflicts")
    conflicts: list[dict[str, Any]] = []
    if isinstance(raw_conflicts, list):
        for item in raw_conflicts[:MAX_CONFLICTS]:
            if not isinstance(item, Mapping):
                continue
            bounded: dict[str, Any] = {}
            for key in ("kind", "field", "source_field", "source_value", "description_value", "quote"):
                value = item.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    bounded[key] = value
                elif isinstance(value, (str, float, bool)):
                    bounded[key] = clean_text(value, limit=500) if isinstance(value, str) else value
            if bounded:
                conflicts.append(bounded)
    if not fields and not conflicts:
        return {}
    material = {"source_fields": fields, "source_conflicts": conflicts}
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_MATERIAL_BYTES:
        raise ValueError("Le matériau publié dépasse la taille locale autorisée.")
    return material


def store_current(connection: sqlite3.Connection, job_id: str, payload: Mapping[str, Any], *, now: str) -> dict[str, Any] | None:
    """Store one bounded snapshot; identical imports are idempotent."""
    material = _bounded_material(payload)
    if not material:
        return None
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    current = connection.execute(
        f"SELECT version, source_hash FROM {TABLE_NAME} WHERE job_id = ? AND is_current = 1",
        (job_id,),
    ).fetchone()
    if current is not None and current["source_hash"] == source_hash:
        connection.execute(f"UPDATE {TABLE_NAME} SET updated_at = ? WHERE job_id = ? AND version = ?",
                           (now, job_id, current["version"]))
        return {"version": int(current["version"]), "source_hash": source_hash, "changed": False}
    version = int(current["version"]) + 1 if current is not None else 1
    connection.execute(f"UPDATE {TABLE_NAME} SET is_current = 0 WHERE job_id = ? AND is_current = 1", (job_id,))
    connection.execute(
        f"INSERT INTO {TABLE_NAME} (job_id, version, source_hash, material_json, is_current, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 1, ?, ?)",
        (job_id, version, source_hash, encoded, now, now),
    )
    return {"version": version, "source_hash": source_hash, "changed": True}


def load_current(connection: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        f"SELECT version, source_hash, material_json, created_at, updated_at FROM {TABLE_NAME} "
        "WHERE job_id = ? AND is_current = 1",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        material = json.loads(row["material_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        material = {}
    if not isinstance(material, dict):
        material = {}
    return {
        "version": int(row["version"]),
        "source_hash": str(row["source_hash"]),
        "material": material,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def load_current_all(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Load all current snapshots in one query for offer-list views."""
    rows = connection.execute(
        f"SELECT job_id, version, source_hash, material_json, created_at, updated_at "
        f"FROM {TABLE_NAME} WHERE is_current = 1"
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            material = json.loads(row["material_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            material = {}
        result[str(row["job_id"])] = {
            "version": int(row["version"]),
            "source_hash": str(row["source_hash"]),
            "material": material if isinstance(material, dict) else {},
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
    return result


__all__ = ["MAX_MATERIAL_BYTES", "TABLE_NAME", "ensure_schema", "load_current", "load_current_all", "store_current"]
