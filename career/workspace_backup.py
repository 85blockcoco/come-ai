"""Versioned, local-only backup and restore for the Career workspace (SPEC-034).

The Career workspace is a private directory tree owned by the local service
(SQLite database plus documents, exports, proofs and application drafts).  This
module exports that tree as a ZIP archive with a JSON manifest and SHA-256
checksums, then restores it with an explicit, non-destructive plan.

Design rules enforced here:

* everything stays local: no network, no model, no secret;
* the manifest records the archive format version (``BACKUP_SCHEMA_VERSION``),
  independently from the SQLite migration version of ``career.service``;
* a restore never writes anything without ``confirm=True``;
* a restore never overwrites a locally modified file unless the caller also
  passes ``accept_conflicts=True`` (conflicts are therefore never resolved
  silently);
* a restore never deletes local files that are absent from the archive;
* archive members are validated before extraction (no absolute paths, no
  ``..`` traversal, no backslashes, no symlinks, no duplicate names, no
  unlisted payload files, no encrypted entries);
* every payload checksum is verified before the first byte is written.

The public contract (``BackupManifest``, ``RestorePlan``, ``create_backup``,
``restore_backup`` and ``diff_state``) is intentionally small so the router can
stay a thin adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKUP_SCHEMA_VERSION = 7
"""Version of the backup manifest handled by this module.

It is deliberately decoupled from ``career.service.SCHEMA_VERSION`` (the
SQLite migration counter): restoring a ZIP is a file operation, not a database
migration.  ``upgrade=True`` is the explicit escape hatch when a caller wants
to accept a manifest produced by another backup format version.
"""

MANIFEST_NAME = "manifest.json"
BACKUP_KIND = "career_workspace_backup"
BACKUP_SUFFIX = ".zip"
DEFAULT_BACKUP_DIRNAME = "backups"
DEFAULT_EXCLUDED_TOP_LEVEL = ("backups",)
"""A backup stored inside the workspace must not include previous backups."""

_SQLITE_MAGIC = b"SQLite format 3\x00"
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_CHUNK_SIZE = 1024 * 1024
_MAX_FILES = 5_000
_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_MAX_PATH_LENGTH = 512
_MAX_PATH_DEPTH = 32
_MAX_SEGMENT_LENGTH = 255
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class WorkspaceBackupError(RuntimeError):
    """Base class for predictable, user-facing backup errors."""


class BackupNotFoundError(WorkspaceBackupError):
    """The requested archive does not exist or is not a regular file."""


class BackupIntegrityError(WorkspaceBackupError):
    """The archive content does not match its manifest."""


class BackupSchemaMismatch(WorkspaceBackupError):
    """The archive format version differs from the local one."""


class BackupConfirmationRequired(WorkspaceBackupError):
    """A restore was requested without the explicit ``confirm=True`` flag."""

    def __init__(self, plan: RestorePlan):
        super().__init__("La restauration exige une confirmation explicite (confirm=True).")
        self.plan = plan


class BackupConflictError(WorkspaceBackupError):
    """Locally modified files would be overwritten without explicit consent."""

    def __init__(self, plan: RestorePlan):
        super().__init__(
            "Des fichiers ont été modifiés localement ; aucune écriture n'a été faite. "
            "Passez accept_conflicts=True pour les remplacer explicitement."
        )
        self.plan = plan


class UnsafeBackupEntry(WorkspaceBackupError):
    """An archive member is not a safe relative regular file."""


@dataclass
class BackupManifest:
    """Description stored inside every archive under ``manifest.json``."""

    created_at: str
    schema_version: int
    files: list[str]
    checksums: dict[str, str]


@dataclass
class RestorePlan:
    """What a restore would do, computed before any write.

    ``to_overwrite`` lists payload files that already exist locally (they are
    the candidates for replacement).  ``conflicts`` is the subset whose local
    SHA-256 differs from the archived one: those are never replaced without
    ``accept_conflicts=True``.  ``to_add`` lists files absent locally.
    """

    to_overwrite: list[str]
    to_add: list[str]
    conflicts: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


_DATABASE_SUFFIXES = (".sqlite3", ".sqlite", ".db")


def _is_database_name(name: str) -> bool:
    return name.lower().endswith(_DATABASE_SUFFIXES)


def _logical_sqlite_digest(path: Path) -> str | None:
    """Digest the logical content of a database, ignoring page layout noise.

    A live SQLite file can change bytes (checkpoint, PRAGMA, journal mode)
    without any user data changing.  Comparing raw bytes would therefore
    report false conflicts on every restore; ``iterdump`` compares the actual
    schema and rows instead.  ``None`` means "cannot inspect", which callers
    must treat as a conflict (fail closed).
    """
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
        try:
            lines = sorted(connection.iterdump())
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return None
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _archive_sqlite_digest(backup_path: Path, name: str) -> str | None:
    """Extract one archived database to a private temp file and digest it."""
    try:
        with zipfile.ZipFile(backup_path, "r") as archive:
            info = next((item for item in archive.infolist() if item.filename == name), None)
            if info is None:
                return None
            with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as handle:
                temporary = Path(handle.name)
                with archive.open(info, "r") as reader:
                    while chunk := reader.read(_CHUNK_SIZE):
                        handle.write(chunk)
    except (zipfile.BadZipFile, OSError):
        return None
    try:
        return _logical_sqlite_digest(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_stream(stream: Any, expected_size: int) -> str:
    digest = hashlib.sha256()
    read_total = 0
    while chunk := stream.read(_CHUNK_SIZE):
        read_total += len(chunk)
        if read_total > expected_size:
            raise BackupIntegrityError("La taille décompressée d'une entrée dépasse sa taille déclarée.")
        digest.update(chunk)
    if read_total != expected_size:
        raise BackupIntegrityError("La taille décompressée d'une entrée ne correspond pas au manifeste.")
    return digest.hexdigest()


def _is_sqlite_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(_SQLITE_MAGIC)) == _SQLITE_MAGIC
    except OSError:
        return False


def _normalize_entry_name(name: str) -> str:
    """Return a safe POSIX relative member name or raise ``UnsafeBackupEntry``."""
    if not name or "\x00" in name:
        raise UnsafeBackupEntry("Nom d'entrée d'archive vide ou invalide.")
    if name.startswith(("/", "\\")) or _DRIVE_PREFIX.match(name):
        raise UnsafeBackupEntry("L'archive contient un chemin absolu interdit.")
    if "\\" in name:
        raise UnsafeBackupEntry("L'archive contient un chemin avec anti-slash interdit.")
    if len(name) > _MAX_PATH_LENGTH:
        raise UnsafeBackupEntry("L'archive contient un chemin trop long.")
    parts = name.split("/")
    if len(parts) > _MAX_PATH_DEPTH:
        raise UnsafeBackupEntry("L'archive contient un chemin trop profond.")
    for part in parts:
        if part in ("", ".", ".."):
            raise UnsafeBackupEntry("L'archive contient un chemin relatif interdit.")
        if len(part) > _MAX_SEGMENT_LENGTH:
            raise UnsafeBackupEntry("L'archive contient un segment de chemin trop long.")
    return "/".join(parts)


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_member(info: zipfile.ZipInfo) -> str:
    """Validate one ZIP member and return its normalized payload name.

    Directory members return an empty string; they are not payload files and
    are never extracted directly (parents are created from file paths).
    """
    if info.flag_bits & 0x1:
        raise UnsafeBackupEntry("Les archives chiffrées ne sont pas prises en charge.")
    name = info.filename
    mode = (info.external_attr >> 16) & 0o170000
    if mode == stat.S_IFLNK:
        raise UnsafeBackupEntry("Les liens symboliques sont interdits dans une sauvegarde.")
    if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise UnsafeBackupEntry("Type de fichier non pris en charge dans la sauvegarde.")
    if info.is_dir() or name.endswith("/"):
        _normalize_entry_name(name.rstrip("/"))
        return ""
    return _normalize_entry_name(name)


def _iter_payload_files(root: Path, excluded_top_level: Iterable[str]) -> list[Path]:
    excluded = frozenset(excluded_top_level)
    collected: list[Path] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        # Never descend into excluded top-level directories (typically the
        # workspace's own ``backups`` folder) or symbolic directories.
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not (current_path == root and name in excluded)
            and not name.startswith(".workspace-backup-tmp-")
            and not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            if current_path == root and filename == MANIFEST_NAME:
                raise WorkspaceBackupError(
                    f"Le nom de fichier {MANIFEST_NAME!r} est réservé à la racine du workspace."
                )
            if filename.startswith(".workspace-backup-tmp-"):
                continue
            source = current_path / filename
            if source.is_symlink():
                continue
            if any(filename.endswith(suffix) for suffix in _SQLITE_SIDECAR_SUFFIXES):
                # A consistent SQLite snapshot is taken through the backup API,
                # so WAL/journal sidecars must not be archived separately.
                continue
            if not source.is_file():
                continue
            if len(collected) >= _MAX_FILES:
                raise WorkspaceBackupError("Le workspace contient trop de fichiers pour une sauvegarde.")
            collected.append(source)
    return sorted(collected, key=lambda path: path.relative_to(root).as_posix())


def _stage_source(source: Path, staging_dir: Path, index: int) -> Path:
    """Return a stable file to archive; snapshot SQLite databases first."""
    if not _is_sqlite_file(source):
        return source
    snapshot = staging_dir / f"sqlite-{index:06d}.db"
    try:
        with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=5.0) as source_conn:
            with sqlite3.connect(snapshot, timeout=5.0) as destination_conn:
                source_conn.backup(destination_conn)
    except sqlite3.Error as error:  # pragma: no cover - defensive
        raise WorkspaceBackupError("Impossible de produire un instantané cohérent de la base locale.") from error
    return snapshot


def _safe_destination_candidate(workspace: Path, name: str) -> Path:
    """Return the destination path and refuse any symlinked parent."""
    candidate = workspace / name
    parent = candidate.parent.resolve()
    if not _is_within(workspace, parent):
        raise UnsafeBackupEntry("La destination d'un fichier sort du workspace.")
    return candidate


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def default_backup_path(workspace_dir: Path | str, *, now: datetime | None = None) -> Path:
    """Return the conventional destination for a new workspace archive."""
    workspace = Path(workspace_dir).resolve()
    moment = now or datetime.now(UTC)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    return workspace / DEFAULT_BACKUP_DIRNAME / "workspace" / f"workspace-backup-{stamp}-{os.urandom(4).hex()}.zip"


def create_backup(
    workspace_dir: Path | str,
    destination: Path | str | None = None,
    *,
    schema_version: int = BACKUP_SCHEMA_VERSION,
    excluded_top_level: Iterable[str] = DEFAULT_EXCLUDED_TOP_LEVEL,
    now: datetime | None = None,
) -> tuple[Path, BackupManifest]:
    """Create a versioned ZIP backup of ``workspace_dir``.

    Returns the archive path and its in-memory manifest.  The archive is
    written to a sibling temporary file and atomically renamed, so a crash
    cannot leave a truncated ``.zip`` under the requested name.
    """
    workspace = Path(workspace_dir).resolve()
    if not workspace.is_dir():
        raise BackupNotFoundError("Le workspace à sauvegarder est introuvable.")
    if not isinstance(schema_version, int) or schema_version <= 0:
        raise WorkspaceBackupError("schema_version doit être un entier strictement positif.")

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    created_at = moment.astimezone(UTC).isoformat().replace("+00:00", "Z")

    target = Path(destination) if destination is not None else default_backup_path(workspace, now=moment)
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    sources = _iter_payload_files(workspace, excluded_top_level)
    temporary = target.with_name(f".workspace-backup-tmp-{target.name}-{os.urandom(4).hex()}")
    staging_dir = target.parent / f".workspace-backup-tmp-{os.urandom(8).hex()}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    checksums: dict[str, str] = {}
    files: list[str] = []
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            total_bytes = 0
            for index, source in enumerate(sources):
                name = source.relative_to(workspace).as_posix()
                _normalize_entry_name(name)
                staged = _stage_source(source, staging_dir, index)
                size = staged.stat().st_size
                total_bytes += size
                if total_bytes > _MAX_UNCOMPRESSED_BYTES:
                    raise WorkspaceBackupError("Le workspace dépasse la taille maximale d'une sauvegarde.")
                digest = hashlib.sha256()
                with staged.open("rb") as reader, archive.open(name, "w") as writer:
                    while chunk := reader.read(_CHUNK_SIZE):
                        digest.update(chunk)
                        writer.write(chunk)
                checksums[name] = digest.hexdigest()
                files.append(name)

            manifest = BackupManifest(
                created_at=created_at,
                schema_version=schema_version,
                files=sorted(files),
                checksums=dict(sorted(checksums.items())),
            )
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(
                    {
                        "kind": BACKUP_KIND,
                        "created_at": manifest.created_at,
                        "schema_version": manifest.schema_version,
                        "files": manifest.files,
                        "checksums": manifest.checksums,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8"),
            )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        for leftover in staging_dir.glob("*"):
            leftover.unlink(missing_ok=True)
        staging_dir.rmdir()
    return target, manifest


# ---------------------------------------------------------------------------
# Reading / planning
# ---------------------------------------------------------------------------


def read_manifest(backup_path: Path | str) -> BackupManifest:
    """Read and validate the manifest of an existing archive."""
    path = Path(backup_path)
    if not path.is_file():
        raise BackupNotFoundError("Sauvegarde introuvable.")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            entries = [info for info in archive.infolist() if info.filename == MANIFEST_NAME]
            if len(entries) != 1:
                raise BackupIntegrityError("Le manifeste de la sauvegarde est absent ou dupliqué.")
            entry = entries[0]
            _validate_member_for_manifest(entry)
            with archive.open(entry, "r") as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise BackupIntegrityError("Le manifeste de la sauvegarde est trop volumineux.")
    except zipfile.BadZipFile as error:
        raise BackupIntegrityError("Le fichier de sauvegarde n'est pas une archive ZIP valide.") from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackupIntegrityError("Le manifeste de la sauvegarde est illisible.") from error
    return _manifest_from_payload(payload)


def _validate_member_for_manifest(info: zipfile.ZipInfo) -> None:
    if info.flag_bits & 0x1:
        raise UnsafeBackupEntry("Les archives chiffrées ne sont pas prises en charge.")
    if info.filename != MANIFEST_NAME:
        raise BackupIntegrityError("Entrée de manifeste inattendue.")


def _manifest_from_payload(payload: Any) -> BackupManifest:
    if not isinstance(payload, dict):
        raise BackupIntegrityError("Le manifeste doit être un objet JSON.")
    kind = payload.get("kind", BACKUP_KIND)
    if kind != BACKUP_KIND:
        raise BackupIntegrityError("Ce fichier n'est pas une sauvegarde de workspace Career.")
    created_at = payload.get("created_at")
    schema_version = payload.get("schema_version")
    files = payload.get("files")
    checksums = payload.get("checksums")
    if not isinstance(created_at, str) or not created_at.strip():
        raise BackupIntegrityError("Le manifeste ne contient pas de date de création valide.")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version <= 0:
        raise BackupIntegrityError("Le manifeste ne contient pas de version de schéma valide.")
    if not isinstance(files, list) or not all(isinstance(name, str) for name in files):
        raise BackupIntegrityError("Le manifeste ne contient pas une liste de fichiers valide.")
    if not isinstance(checksums, dict):
        raise BackupIntegrityError("Le manifeste ne contient pas de sommes de contrôle valides.")

    normalized: list[str] = []
    seen: set[str] = set()
    for name in files:
        safe_name = _normalize_entry_name(name)
        if safe_name == MANIFEST_NAME:
            raise BackupIntegrityError("Le manifeste ne peut pas se décrire lui-même comme contenu.")
        if safe_name in seen:
            raise BackupIntegrityError("Le manifeste contient des chemins dupliqués.")
        seen.add(safe_name)
        normalized.append(safe_name)
    if len(normalized) > _MAX_FILES:
        raise BackupIntegrityError("Le manifeste contient trop de fichiers.")

    clean_checksums: dict[str, str] = {}
    for name, digest in checksums.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise BackupIntegrityError("Le manifeste contient une somme de contrôle invalide.")
        safe_name = _normalize_entry_name(name)
        if safe_name not in seen:
            raise BackupIntegrityError("Une somme de contrôle référence un fichier absent du manifeste.")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupIntegrityError("Une somme de contrôle n'est pas un SHA-256 hexadécimal.")
        clean_checksums[safe_name] = digest
    if set(clean_checksums) != seen:
        raise BackupIntegrityError("Chaque fichier du manifeste doit avoir une somme de contrôle.")

    return BackupManifest(
        created_at=created_at,
        schema_version=schema_version,
        files=sorted(normalized),
        checksums=dict(sorted(clean_checksums.items())),
    )


def _check_schema(manifest: BackupManifest, local_schema_version: int | None, upgrade: bool) -> None:
    expected = BACKUP_SCHEMA_VERSION if local_schema_version is None else local_schema_version
    if not isinstance(expected, int) or expected <= 0:
        raise WorkspaceBackupError("local_schema_version doit être un entier strictement positif.")
    if manifest.schema_version != expected and not upgrade:
        raise BackupSchemaMismatch(
            f"Version de sauvegarde {manifest.schema_version} incompatible avec la version locale "
            f"{expected}. Passez upgrade=True pour accepter explicitement cette mise à niveau."
        )


def _plan_for_manifest(
    manifest: BackupManifest,
    workspace_dir: Path | str,
    *,
    backup_path: Path | None = None,
) -> RestorePlan:
    workspace = Path(workspace_dir).resolve()
    if not workspace.is_dir():
        raise BackupNotFoundError("Le workspace de destination est introuvable.")
    to_add: list[str] = []
    to_overwrite: list[str] = []
    conflicts: list[str] = []
    for name in manifest.files:
        candidate = workspace / name
        if not candidate.exists() or candidate.is_dir():
            to_add.append(name)
            continue
        to_overwrite.append(name)
        same_bytes = candidate.is_file() and not candidate.is_symlink() and _sha256_file(candidate) == manifest.checksums[name]
        if same_bytes:
            continue
        if _is_database_name(name) and backup_path is not None and candidate.is_file() and not candidate.is_symlink():
            local_digest = _logical_sqlite_digest(candidate)
            archived_digest = _archive_sqlite_digest(backup_path, name)
            if local_digest is not None and archived_digest is not None and local_digest == archived_digest:
                # Same schema and rows: only the on-disk page layout changed.
                continue
        conflicts.append(name)
    return RestorePlan(
        to_overwrite=sorted(to_overwrite),
        to_add=sorted(to_add),
        conflicts=sorted(conflicts),
    )


def diff_state(
    backup_path: Path | str,
    workspace_dir: Path | str,
    *,
    local_schema_version: int | None = None,
    upgrade: bool = False,
) -> RestorePlan:
    """Compute what a restore would change, without writing anything."""
    manifest = read_manifest(backup_path)
    _check_schema(manifest, local_schema_version, upgrade)
    return _plan_for_manifest(manifest, workspace_dir, backup_path=Path(backup_path))


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def _verify_archive(archive: zipfile.ZipFile, manifest: BackupManifest) -> dict[str, zipfile.ZipInfo]:
    """Validate every member and checksum before any extraction."""
    payload_infos: dict[str, zipfile.ZipInfo] = {}
    total_bytes = 0
    for info in archive.infolist():
        if info.filename == MANIFEST_NAME:
            continue
        name = _validate_member(info)
        if not name:
            continue
        if name in payload_infos:
            raise BackupIntegrityError("L'archive contient des entrées dupliquées.")
        if name not in manifest.checksums:
            raise BackupIntegrityError("L'archive contient un fichier absent du manifeste.")
        if info.file_size > _MAX_UNCOMPRESSED_BYTES:
            raise BackupIntegrityError("Une entrée de l'archive dépasse la taille maximale autorisée.")
        total_bytes += info.file_size
        if total_bytes > _MAX_UNCOMPRESSED_BYTES:
            raise BackupIntegrityError("Le contenu de l'archive dépasse la taille maximale autorisée.")
        payload_infos[name] = info
    missing = sorted(set(manifest.checksums) - set(payload_infos))
    if missing:
        raise BackupIntegrityError("Des fichiers annoncés par le manifeste sont absents de l'archive.")
    for name, info in payload_infos.items():
        with archive.open(info, "r") as stream:
            digest = _sha256_stream(stream, info.file_size)
        if digest != manifest.checksums[name]:
            raise BackupIntegrityError(f"Somme de contrôle invalide pour {name!r}.")
    return payload_infos


def _atomic_write(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path, workspace: Path) -> None:
    destination = _safe_destination_candidate(workspace, destination.relative_to(workspace).as_posix())
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent = destination.parent.resolve()
    if not _is_within(workspace, parent):
        raise UnsafeBackupEntry("La destination d'un fichier sort du workspace.")
    temporary = destination.with_name(f".workspace-backup-tmp-{destination.name}-{os.urandom(4).hex()}")
    try:
        with archive.open(info, "r") as reader, temporary.open("xb") as writer:
            while chunk := reader.read(_CHUNK_SIZE):
                writer.write(chunk)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def restore_backup(
    backup_path: Path | str,
    workspace_dir: Path | str,
    *,
    confirm: bool = False,
    upgrade: bool = False,
    accept_conflicts: bool = False,
    local_schema_version: int | None = None,
) -> RestorePlan:
    """Restore an archive into ``workspace_dir``.

    ``confirm`` is mandatory.  ``upgrade`` accepts a different manifest schema
    version.  ``accept_conflicts`` is mandatory when locally modified files
    would be replaced; without it the restore aborts before any write.
    """
    path = Path(backup_path)
    workspace = Path(workspace_dir).resolve()
    if not workspace.is_dir():
        raise BackupNotFoundError("Le workspace de destination est introuvable.")
    manifest = read_manifest(path)
    _check_schema(manifest, local_schema_version, upgrade)
    plan = _plan_for_manifest(manifest, workspace, backup_path=path)
    if not confirm:
        raise BackupConfirmationRequired(plan)
    if plan.conflicts and not accept_conflicts:
        raise BackupConflictError(plan)

    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = _verify_archive(archive, manifest)
            # Preflight every destination before the first write, so a local
            # symlink escaping the workspace cannot cause a partial restore.
            write_names = sorted(set(plan.to_add) | set(plan.to_overwrite))
            for name in write_names:
                destination = _safe_destination_candidate(workspace, name)
                if destination.is_symlink():
                    raise UnsafeBackupEntry("La cible de restauration est un lien symbolique.")
                if destination.exists() and (not destination.is_file() or destination.is_dir()):
                    raise UnsafeBackupEntry("Une cible de restauration n'est pas un fichier régulier.")
            # All validation succeeded: the archive is trustworthy.  Write only
            # files whose local copy differs or is absent, using an atomic
            # sibling rename so an interrupted restore cannot truncate a file.
            for name in write_names:
                destination = _safe_destination_candidate(workspace, name)
                if destination.exists() and destination.is_file():
                    if _sha256_file(destination) == manifest.checksums[name]:
                        continue
                _atomic_write(archive, infos[name], destination, workspace)
                if _is_database_name(name):
                    for sidecar_suffix in _SQLITE_SIDECAR_SUFFIXES:
                        Path(f"{destination}{sidecar_suffix}").unlink(missing_ok=True)
    except zipfile.BadZipFile as error:
        raise BackupIntegrityError("Le fichier de sauvegarde n'est pas une archive ZIP valide.") from error
    return plan


# ---------------------------------------------------------------------------
# Serialization helpers for the REST layer
# ---------------------------------------------------------------------------


def manifest_to_dict(manifest: BackupManifest) -> dict[str, Any]:
    return {
        "created_at": manifest.created_at,
        "schema_version": manifest.schema_version,
        "files": list(manifest.files),
        "checksums": dict(manifest.checksums),
    }


def plan_to_dict(plan: RestorePlan) -> dict[str, list[str]]:
    return {
        "to_overwrite": list(plan.to_overwrite),
        "to_add": list(plan.to_add),
        "conflicts": list(plan.conflicts),
    }


__all__ = [
    "BACKUP_SCHEMA_VERSION",
    "MANIFEST_NAME",
    "BackupConfirmationRequired",
    "BackupConflictError",
    "BackupIntegrityError",
    "BackupManifest",
    "BackupNotFoundError",
    "BackupSchemaMismatch",
    "RestorePlan",
    "UnsafeBackupEntry",
    "WorkspaceBackupError",
    "create_backup",
    "default_backup_path",
    "diff_state",
    "manifest_to_dict",
    "plan_to_dict",
    "read_manifest",
    "restore_backup",
]
