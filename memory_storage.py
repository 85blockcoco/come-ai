"""Safe, local storage diagnostics for the Côme AI memory workspace.

This module is intentionally read-only.  It helps the V5 interface describe
the local memory folder without importing documents, opening ``.env``,
contacting a provider, or deleting/repairing anything.  It is therefore safe
to call from a dashboard or a health endpoint.

The service does not follow child symlinks and bounds its filesystem walk.  A
result explicitly says when the scan is partial, so the UI never presents a
limited inventory as a complete one.  Absolute paths are represented through
``redact_location_path``: paths under the current home directory use ``~``
instead of exposing the account name, while an external volume remains
recognisable to its owner.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from shutil import disk_usage
from typing import Any, Iterable


DEFAULT_MAX_SCAN_ENTRIES = 10_000
DEFAULT_MAX_SCAN_DEPTH = 12
DEFAULT_LARGEST_FILES_LIMIT = 12
DEFAULT_DATABASE_FILENAME = "personal_memory.sqlite3"
DEFAULT_BACKUP_DIR_NAME = "backup"
_DATABASE_SIDECAR_SUFFIXES = ("", "-wal", "-shm", "-journal")
_MEMORY_TABLES = ("projects", "sources", "memory_chunks")


class MemoryStorageError(ValueError):
    """Raised for an invalid local diagnostics configuration.

    Operational filesystem/database failures are returned as a safe status in
    :meth:`MemoryStorageService.snapshot` instead of exposing host details.
    """


@dataclass(frozen=True)
class _FileRecord:
    """One regular non-symlink file found below the configured root."""

    relative_path: str
    size_bytes: int
    modified_at: str | None
    is_backup: bool


@dataclass(frozen=True)
class _ScanResult:
    """Internal bounded inventory used to build JSON-ready dashboard data."""

    files: tuple[_FileRecord, ...]
    entries_seen: int
    unreadable_entries: int
    skipped_symlinks: int
    skipped_depths: int
    skipped_non_regular: int
    limit_reached: bool

    @property
    def complete(self) -> bool:
        """Whether a size/depth limit did not omit any potential file."""
        return not self.limit_reached and self.skipped_depths == 0


def redact_location_path(path: Path | str, *, home_dir: Path | str | None = None) -> str:
    """Return a display-safe local path without a macOS account name.

    A path below the supplied/current home directory is displayed as ``~``.
    The additional ``/Users/<account>`` fallback protects a home-like path in
    tests or after a home-directory migration.  This is presentation only; it
    does not perform access checks or read any configuration file.
    """

    target = _normalise_path(path)
    home = _normalise_path(home_dir) if home_dir is not None else _normalise_path(Path.home())
    try:
        relative = target.relative_to(home)
    except ValueError:
        relative = None
    if relative is not None:
        return "~" if not relative.parts else f"~/{_safe_display_relative(relative)}"

    parts = target.parts
    # macOS homes are normally /Users/<account>.  Avoid leaking an old or
    # alternate account name if callers pass a path from such a location.
    if len(parts) >= 3 and parts[0] == os.sep and parts[1] == "Users":
        remaining = Path(*parts[3:])
        return "~" if not remaining.parts else f"~/{_safe_display_relative(remaining)}"
    return _safe_display_absolute(target)


class MemoryStorageService:
    """Build bounded, read-only diagnostics for one local memory directory.

    Parameters are deliberately explicit instead of being read from the
    environment.  ``memory_dir`` may live on an external SSD.  The class
    never creates that directory, which lets callers distinguish a not-yet
    initialised memory library from a ready one.

    ``max_scan_entries`` counts every directory entry considered, not just
    regular files.  This bounds work even for a tree containing many empty
    directories.  ``max_scan_depth`` and ``largest_files_limit`` are likewise
    surfaced in the returned scan metadata.
    """

    def __init__(
        self,
        memory_dir: Path | str,
        *,
        database_filename: str = DEFAULT_DATABASE_FILENAME,
        backup_dir_name: str = DEFAULT_BACKUP_DIR_NAME,
        max_scan_entries: int = DEFAULT_MAX_SCAN_ENTRIES,
        max_scan_depth: int = DEFAULT_MAX_SCAN_DEPTH,
        largest_files_limit: int = DEFAULT_LARGEST_FILES_LIMIT,
        home_dir: Path | str | None = None,
    ) -> None:
        self.memory_dir = _normalise_path(memory_dir)
        self.database_filename = _safe_child_name(database_filename, "Le nom de la base mémoire")
        self.backup_dir_name = _safe_child_name(backup_dir_name, "Le nom du dossier de sauvegarde")
        self.max_scan_entries = _positive_int(max_scan_entries, "La limite de scan")
        self.max_scan_depth = _non_negative_int(max_scan_depth, "La profondeur de scan")
        self.largest_files_limit = _positive_int(largest_files_limit, "La limite des fichiers volumineux")
        self.home_dir = _normalise_path(home_dir) if home_dir is not None else _normalise_path(Path.home())

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-ready, safe view of memory files and disk capacity.

        The method has no side effect.  It only reads file metadata and, when
        a settled primary SQLite database is present, runs fixed immutable
        ``COUNT`` queries against the known V5 table names.
        """

        root_status = self._root_status()
        location = {
            "display_path": redact_location_path(self.memory_dir, home_dir=self.home_dir),
            "is_external": not _is_relative_to(self.memory_dir, self.home_dir),
            "exists": root_status == "ready",
        }
        disk = self._disk_snapshot()
        if root_status != "ready":
            return {
                "status": root_status,
                "location": location,
                "storage": self._empty_storage_snapshot(complete=root_status == "missing"),
                "disk": disk,
                "database": self._database_snapshot(root_ready=False),
                "backups": self._backup_snapshot((), complete=root_status == "missing"),
            }

        scan = self._scan_files()
        return {
            "status": "ready",
            "location": location,
            "storage": self._storage_snapshot(scan),
            "disk": disk,
            "database": self._database_snapshot(root_ready=True),
            "backups": self._backup_snapshot(scan.files, complete=scan.complete),
        }

    # ------------------------------------------------------------------
    # Root, disk, and bounded filesystem inventory
    # ------------------------------------------------------------------
    def _root_status(self) -> str:
        try:
            info = self.memory_dir.lstat()
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unavailable"
        if stat.S_ISDIR(info.st_mode):
            return "ready"
        return "not_directory"

    def _disk_snapshot(self) -> dict[str, Any]:
        target = _nearest_existing_directory(self.memory_dir)
        if target is None:
            return {
                "status": "unavailable",
                "total_bytes": None,
                "used_bytes": None,
                "free_bytes": None,
            }
        try:
            usage = disk_usage(target)
        except OSError:
            return {
                "status": "unavailable",
                "total_bytes": None,
                "used_bytes": None,
                "free_bytes": None,
            }
        return {
            "status": "ready",
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
        }

    def _scan_files(self) -> _ScanResult:
        files: list[_FileRecord] = []
        stack: list[tuple[Path, int]] = [(self.memory_dir, 0)]
        entries_seen = 0
        unreadable_entries = 0
        skipped_symlinks = 0
        skipped_depths = 0
        skipped_non_regular = 0
        limit_reached = False

        while stack:
            directory, depth = stack.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda child: (child.name.casefold(), child.name))
            except OSError:
                unreadable_entries += 1
                continue

            for child in children:
                if entries_seen >= self.max_scan_entries:
                    limit_reached = True
                    break
                entries_seen += 1
                try:
                    info = child.lstat()
                except OSError:
                    unreadable_entries += 1
                    continue

                if stat.S_ISLNK(info.st_mode):
                    skipped_symlinks += 1
                    continue
                if stat.S_ISDIR(info.st_mode):
                    if depth >= self.max_scan_depth:
                        skipped_depths += 1
                    else:
                        stack.append((child, depth + 1))
                    continue
                if not stat.S_ISREG(info.st_mode):
                    skipped_non_regular += 1
                    continue

                relative = _safe_relative_path(self.memory_dir, child)
                files.append(
                    _FileRecord(
                        relative_path=relative,
                        size_bytes=max(0, int(info.st_size)),
                        modified_at=_format_timestamp(info.st_mtime),
                        is_backup=_is_backup_relative_path(relative, self.backup_dir_name),
                    )
                )
            if limit_reached:
                break

        return _ScanResult(
            files=tuple(files),
            entries_seen=entries_seen,
            unreadable_entries=unreadable_entries,
            skipped_symlinks=skipped_symlinks,
            skipped_depths=skipped_depths,
            skipped_non_regular=skipped_non_regular,
            limit_reached=limit_reached,
        )

    def _empty_storage_snapshot(self, *, complete: bool) -> dict[str, Any]:
        return {
            "file_count": 0,
            "total_bytes": 0,
            "largest_files": [],
            "scan": {
                "complete": complete,
                "entries_seen": 0,
                "files_seen": 0,
                "max_entries": self.max_scan_entries,
                "max_depth": self.max_scan_depth,
                "limit_reached": False,
                "unreadable_entries": 0,
                "skipped_symlinks": 0,
                "skipped_depths": 0,
                "skipped_non_regular": 0,
            },
        }

    def _storage_snapshot(self, scan: _ScanResult) -> dict[str, Any]:
        largest = sorted(scan.files, key=lambda item: (-item.size_bytes, item.relative_path.casefold()))[
            : self.largest_files_limit
        ]
        return {
            "file_count": len(scan.files),
            "total_bytes": sum(item.size_bytes for item in scan.files),
            "largest_files": [self._file_dict(item) for item in largest],
            "scan": {
                "complete": scan.complete,
                "entries_seen": scan.entries_seen,
                "files_seen": len(scan.files),
                "max_entries": self.max_scan_entries,
                "max_depth": self.max_scan_depth,
                "limit_reached": scan.limit_reached,
                "unreadable_entries": scan.unreadable_entries,
                "skipped_symlinks": scan.skipped_symlinks,
                "skipped_depths": scan.skipped_depths,
                "skipped_non_regular": scan.skipped_non_regular,
            },
        }

    @staticmethod
    def _file_dict(record: _FileRecord) -> dict[str, Any]:
        return {
            "relative_path": record.relative_path,
            "size_bytes": record.size_bytes,
            "modified_at": record.modified_at,
        }

    # ------------------------------------------------------------------
    # Primary SQLite metadata and backup summary
    # ------------------------------------------------------------------
    def _database_snapshot(self, *, root_ready: bool) -> dict[str, Any]:
        empty_records: dict[str, int | None] = {name: None for name in _MEMORY_TABLES}
        if not root_ready:
            return {
                "status": "missing",
                "relative_path": self.database_filename,
                "bytes": 0,
                "sidecar_bytes": 0,
                "records": empty_records,
            }

        database_path = self.memory_dir / self.database_filename
        primary_size = _regular_file_size(database_path)
        sidecar_sizes = {
            suffix: _regular_file_size(database_path.with_name(database_path.name + suffix))
            for suffix in _DATABASE_SIDECAR_SUFFIXES[1:]
        }
        sidecar_bytes = sum(size for size in sidecar_sizes.values() if size is not None)
        if primary_size is None:
            return {
                "status": "missing",
                "relative_path": self.database_filename,
                "bytes": 0,
                "sidecar_bytes": sidecar_bytes,
                "records": empty_records,
            }

        # A live SQLite WAL/journal can require auxiliary files even for a
        # read-only connection.  Avoid that entire code path: storage bytes
        # remain accurate and the dashboard can refresh record counts once the
        # writer has settled, without this diagnostics module ever creating a
        # lock/shm file or triggering recovery work.
        if any(size not in (None, 0) for size in sidecar_sizes.values()):
            return {
                "status": "active_journal",
                "relative_path": self.database_filename,
                "bytes": primary_size,
                "sidecar_bytes": sidecar_bytes,
                "records": empty_records,
            }

        status, records = self._read_database_counts(database_path)
        return {
            "status": status,
            "relative_path": self.database_filename,
            "bytes": primary_size,
            "sidecar_bytes": sidecar_bytes,
            "records": records,
        }

    @staticmethod
    def _read_database_counts(database_path: Path) -> tuple[str, dict[str, int | None]]:
        records: dict[str, int | None] = {name: None for name in _MEMORY_TABLES}
        connection: sqlite3.Connection | None = None
        try:
            # ``immutable=1`` prevents lock/journal writes from this optional
            # dashboard read.  Active WAL/journal files are handled before
            # this method, so an immutable snapshot is not presented as a
            # live transactional count.  All SQL below is fixed by this code.
            connection = sqlite3.connect(
                f"{database_path.as_uri()}?mode=ro&immutable=1", uri=True, timeout=1.0
            )
            connection.execute("PRAGMA query_only = ON")
            table_names = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            for table in _MEMORY_TABLES:
                if table in table_names:
                    records[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except (OSError, sqlite3.Error, ValueError):
            return "unavailable", records
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass

        if any(value is not None for value in records.values()):
            return "ready", records
        return "unknown_schema", records

    def _backup_snapshot(self, files: Iterable[_FileRecord], *, complete: bool) -> dict[str, Any]:
        backup_path = self.memory_dir / self.backup_dir_name
        backup_status = _child_directory_status(backup_path)
        backup_files = [record for record in files if record.is_backup]
        latest = max((record.modified_at for record in backup_files if record.modified_at is not None), default=None)
        return {
            "status": backup_status,
            "exists": backup_status == "ready",
            "relative_path": self.backup_dir_name,
            "file_count": len(backup_files),
            "total_bytes": sum(record.size_bytes for record in backup_files),
            "latest_modified_at": latest,
            "scan_complete": complete,
        }


def _normalise_path(path: Path | str) -> Path:
    """Make a stable absolute local path without requiring it to exist."""

    try:
        candidate = Path(path).expanduser()
    except (TypeError, ValueError) as error:
        raise MemoryStorageError("Le chemin de mémoire locale est invalide.") from error
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        # A malformed/unavailable path is still reported safely by snapshot.
        try:
            return candidate.absolute()
        except (OSError, RuntimeError) as error:
            raise MemoryStorageError("Le chemin de mémoire locale est indisponible.") from error


def _safe_child_name(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryStorageError(f"{label} est obligatoire.")
    if any(character < " " or character == "\x7f" for character in value):
        raise MemoryStorageError(f"{label} doit être un nom local simple.")
    candidate = Path(value)
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name in {"", ".", ".."}:
        raise MemoryStorageError(f"{label} doit être un nom local simple.")
    return candidate.name


def _positive_int(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryStorageError(f"{label} doit être un entier positif.")
    return value


def _non_negative_int(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MemoryStorageError(f"{label} doit être un entier positif ou nul.")
    return value


def _nearest_existing_directory(path: Path) -> Path | None:
    """Find a local mountable directory without resolving or creating it."""

    candidate = path
    while True:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            parent = candidate.parent
            if parent == candidate:
                return None
            candidate = parent
            continue
        except OSError:
            return None
        return candidate if stat.S_ISDIR(info.st_mode) else candidate.parent


def _regular_file_size(path: Path) -> int | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    if stat.S_ISREG(info.st_mode):
        return max(0, int(info.st_size))
    return None


def _child_directory_status(path: Path) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unavailable"
    if stat.S_ISLNK(info.st_mode):
        return "skipped_link"
    return "ready" if stat.S_ISDIR(info.st_mode) else "not_directory"


def _safe_relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return _safe_display_absolute(path)
    return _safe_display_relative(relative)


def _safe_display_relative(path: Path) -> str:
    return "/".join(_clean_display_component(component) for component in path.parts)


def _safe_display_absolute(path: Path) -> str:
    prefix = path.anchor or os.sep
    parts = [part for part in path.parts if part not in {path.anchor, os.sep}]
    clean = "/".join(_clean_display_component(part) for part in parts)
    if not clean:
        return prefix
    if prefix == os.sep:
        return f"{os.sep}{clean}"
    return f"{prefix.rstrip(os.sep)}/{clean}"


def _clean_display_component(value: str) -> str:
    # Prevent a malicious filename from injecting a line break/control character
    # into a web dashboard or terminal log.  The UI receives text, not HTML.
    cleaned = "".join(character if character >= " " and character != "\x7f" else "�" for character in value)
    return cleaned[:240] or "�"


def _format_timestamp(value: float) -> str | None:
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _is_backup_relative_path(relative_path: str, backup_dir_name: str) -> bool:
    return relative_path == backup_dir_name or relative_path.startswith(f"{backup_dir_name}/")


def _is_relative_to(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
    except ValueError:
        return False
    return True
