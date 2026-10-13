"""Offline tests for the V5 read-only Memory & Storage diagnostics service."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from memory_storage import MemoryStorageError, MemoryStorageService, redact_location_path


def _make_memory_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE projects (id TEXT PRIMARY KEY);
            CREATE TABLE sources (id TEXT PRIMARY KEY);
            CREATE TABLE memory_chunks (id TEXT PRIMARY KEY);
            INSERT INTO projects VALUES ('project-1');
            INSERT INTO sources VALUES ('source-1');
            INSERT INTO sources VALUES ('source-2');
            INSERT INTO memory_chunks VALUES ('chunk-1');
            INSERT INTO memory_chunks VALUES ('chunk-2');
            INSERT INTO memory_chunks VALUES ('chunk-3');
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_snapshot_reports_local_files_database_counts_disk_and_backup(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    database = memory_dir / "personal_memory.sqlite3"
    _make_memory_database(database)
    (memory_dir / "cache.bin").write_bytes(b"x" * 100_000)
    backup = memory_dir / "backup"
    backup.mkdir()
    (backup / "memory-2026-01-01.sqlite3").write_bytes(b"b" * 300)

    snapshot = MemoryStorageService(memory_dir, home_dir=tmp_path).snapshot()

    assert snapshot["status"] == "ready"
    assert snapshot["location"] == {
        "display_path": "~/memory",
        "is_external": False,
        "exists": True,
    }
    assert snapshot["storage"]["file_count"] == 3
    assert snapshot["storage"]["total_bytes"] >= 100_300
    assert snapshot["storage"]["largest_files"][0]["relative_path"] == "cache.bin"
    assert snapshot["storage"]["scan"]["complete"] is True
    assert snapshot["disk"]["status"] == "ready"
    assert snapshot["disk"]["free_bytes"] > 0
    assert snapshot["database"] == {
        "status": "ready",
        "relative_path": "personal_memory.sqlite3",
        "bytes": database.stat().st_size,
        "sidecar_bytes": 0,
        "records": {"projects": 1, "sources": 2, "memory_chunks": 3},
    }
    assert snapshot["backups"]["status"] == "ready"
    assert snapshot["backups"]["exists"] is True
    assert snapshot["backups"]["file_count"] == 1
    assert snapshot["backups"]["total_bytes"] == 300
    assert snapshot["backups"]["scan_complete"] is True


def test_missing_directory_is_non_mutating_and_still_has_safe_disk_status(tmp_path: Path) -> None:
    missing = tmp_path / "external-ssd" / "come-memory"
    snapshot = MemoryStorageService(missing, home_dir=tmp_path).snapshot()

    assert not missing.exists()
    assert snapshot["status"] == "missing"
    assert snapshot["location"]["display_path"] == "~/external-ssd/come-memory"
    assert snapshot["storage"]["file_count"] == 0
    assert snapshot["storage"]["total_bytes"] == 0
    assert snapshot["database"]["status"] == "missing"
    assert snapshot["backups"]["status"] == "missing"
    assert snapshot["disk"]["status"] == "ready"


def test_scan_limits_and_symlinks_are_reported_without_following_external_content(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    for number in range(5):
        (memory_dir / f"file-{number}.txt").write_text("local", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside" * 500)
    link = memory_dir / "000-outside-link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Les liens symboliques ne sont pas disponibles dans cet environnement.")

    snapshot = MemoryStorageService(memory_dir, max_scan_entries=3, home_dir=tmp_path).snapshot()

    assert snapshot["storage"]["scan"]["limit_reached"] is True
    assert snapshot["storage"]["scan"]["complete"] is False
    assert snapshot["storage"]["file_count"] <= 3
    assert snapshot["storage"]["scan"]["skipped_symlinks"] == 1
    assert all(item["relative_path"] != "000-outside-link.txt" for item in snapshot["storage"]["largest_files"])
    assert snapshot["storage"]["total_bytes"] < outside.stat().st_size


def test_depth_limit_and_unrecognised_sqlite_database_are_honest(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    nested = memory_dir / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("not reached", encoding="utf-8")
    (memory_dir / "personal_memory.sqlite3").write_bytes(b"not a sqlite database")

    snapshot = MemoryStorageService(memory_dir, max_scan_depth=1, home_dir=tmp_path).snapshot()

    assert snapshot["storage"]["scan"]["skipped_depths"] == 1
    assert snapshot["storage"]["scan"]["complete"] is False
    assert snapshot["database"]["status"] == "unavailable"
    assert snapshot["database"]["records"] == {
        "projects": None,
        "sources": None,
        "memory_chunks": None,
    }


def test_active_sqlite_journal_is_reported_without_reading_transactional_counts(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    database = memory_dir / "personal_memory.sqlite3"
    _make_memory_database(database)
    (memory_dir / "personal_memory.sqlite3-wal").write_bytes(b"active transaction")

    snapshot = MemoryStorageService(memory_dir, home_dir=tmp_path).snapshot()

    assert snapshot["database"] == {
        "status": "active_journal",
        "relative_path": "personal_memory.sqlite3",
        "bytes": database.stat().st_size,
        "sidecar_bytes": len(b"active transaction"),
        "records": {"projects": None, "sources": None, "memory_chunks": None},
    }


def test_redacted_paths_and_constructor_validation_are_safe(tmp_path: Path) -> None:
    home = tmp_path / "private-home"
    nested = home / "Documents" / "Côme AI"
    assert redact_location_path(nested, home_dir=home) == "~/Documents/Côme AI"
    assert redact_location_path(Path("/Users/another-person/Secret"), home_dir=home) == "~/Secret"

    with pytest.raises(MemoryStorageError, match="nom local simple"):
        MemoryStorageService(tmp_path, database_filename="../outside.sqlite3")
    with pytest.raises(MemoryStorageError, match="entier positif"):
        MemoryStorageService(tmp_path, max_scan_entries=0)
    with pytest.raises(MemoryStorageError, match="positif ou nul"):
        MemoryStorageService(tmp_path, max_scan_depth=-1)
    with pytest.raises(MemoryStorageError, match="nom local simple"):
        MemoryStorageService(tmp_path, backup_dir_name="backup\nunsafe")


def test_snapshot_does_not_read_environment_or_create_a_missing_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-be-read")
    missing = tmp_path / "not-created"

    service = MemoryStorageService(missing, home_dir=tmp_path)
    result = service.snapshot()

    assert os.environ["GEMINI_API_KEY"] == "must-not-be-read"
    assert not missing.exists()
    assert result["status"] == "missing"
