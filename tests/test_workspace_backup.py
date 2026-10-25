"""Tests SPEC-034 — sauvegarde / restauration locale du workspace Career.

Toutes les données sont synthétiques (``tests/fixtures/backup_synthetic.json``).
Aucun accès réseau, aucune donnée réelle, aucun secret.  Les cas couvrent le
contrat public, les refus explicites (confirmation, conflits, schéma) et des
archives adversariales (zip-slip, chemins absolus, liens symboliques,
checksums falsifiés, entrées non listées, doublons, chiffrement).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import struct
import warnings
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from career.router import create_career_router
from career.service import CareerService
from career.workspace_backup import (
    BACKUP_SCHEMA_VERSION,
    BackupConflictError,
    BackupConfirmationRequired,
    BackupIntegrityError,
    BackupManifest,
    BackupNotFoundError,
    BackupSchemaMismatch,
    RestorePlan,
    UnsafeBackupEntry,
    WorkspaceBackupError,
    create_backup,
    diff_state,
    read_manifest,
    restore_backup,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "backup_synthetic.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _file_bytes(value: object) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def seed_workspace(root: Path, *, payload: dict[str, object] | None = None) -> dict[str, bytes]:
    """Materialise the synthetic fixture as a workspace tree."""
    data = payload or _fixture_payload()
    written: dict[str, bytes] = {}
    for name, value in data["files"].items():  # type: ignore[index]
        content = _file_bytes(value)
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        written[name] = content
    return written


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(
    entries: dict[str, bytes],
    *,
    schema_version: int = BACKUP_SCHEMA_VERSION,
    checksums: dict[str, str] | None = None,
    files: list[str] | None = None,
) -> dict[str, object]:
    return {
        "kind": "career_workspace_backup",
        "created_at": "2026-10-20T10:00:00Z",
        "schema_version": schema_version,
        "files": files if files is not None else sorted(entries),
        "checksums": checksums if checksums is not None else {name: _sha256(data) for name, data in entries.items()},
    }


def _write_zip(
    path: Path,
    entries: dict[str, bytes],
    manifest: dict[str, object],
    *,
    include_manifest: bool = True,
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        if include_manifest:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def _write_special_zip(path: Path, info: zipfile.ZipInfo, data: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(_manifest({info.filename: data})))
        archive.writestr(info, data)
    return path


def _mark_entry_encrypted(path: Path, entry_name: str) -> None:
    """Set the ZIP "encrypted" general-purpose bit, which ``zipfile`` refuses to write itself."""
    data = path.read_bytes()
    central_start = data.find(b"PK\x01\x02")
    position = central_start
    while position >= 0 and data[position : position + 4] == b"PK\x01\x02":
        name_length = struct.unpack("<H", data[position + 28 : position + 30])[0]
        extra_length = struct.unpack("<H", data[position + 30 : position + 32])[0]
        comment_length = struct.unpack("<H", data[position + 32 : position + 34])[0]
        name = data[position + 46 : position + 46 + name_length]
        if name == entry_name.encode("utf-8"):
            local_offset = struct.unpack("<I", data[position + 42 : position + 46])[0]
            data = data[: position + 8] + b"\x01\x00" + data[position + 10 :]
            data = data[: local_offset + 6] + b"\x01\x00" + data[local_offset + 8 :]
            path.write_bytes(data)
            return
        position += 46 + name_length + extra_length + comment_length
    raise AssertionError(f"entrée {entry_name!r} introuvable")


def _client(service: CareerService) -> TestClient:
    app = FastAPI()
    app.include_router(create_career_router(service))
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Round-trip and manifest contract
# ---------------------------------------------------------------------------


def test_round_trip_preserves_nested_files_and_unicode(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    files = seed_workspace(workspace)
    files["documents/cv-été-démo.txt"] = "Été synthétique — accents éàü\n".encode("utf-8")
    (workspace / "documents/cv-été-démo.txt").write_bytes(files["documents/cv-été-démo.txt"])

    backup_path, manifest = create_backup(workspace)
    assert backup_path.is_file()
    assert manifest.schema_version == BACKUP_SCHEMA_VERSION == 7
    assert manifest.files == sorted(files)
    assert set(manifest.checksums) == set(files)

    target = tmp_path / "restored"
    target.mkdir()
    plan = restore_backup(backup_path, target, confirm=True)
    assert isinstance(plan, RestorePlan)
    assert plan.to_add == sorted(files)
    assert plan.to_overwrite == []
    assert plan.conflicts == []
    for name, content in files.items():
        assert (target / name).read_bytes() == content


def test_read_manifest_round_trips_the_dataclass(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seed_workspace(workspace)
    backup_path, manifest = create_backup(workspace)

    reread = read_manifest(backup_path)
    assert isinstance(reread, BackupManifest)
    assert reread.created_at == manifest.created_at
    assert reread.schema_version == manifest.schema_version
    assert reread.files == manifest.files
    assert reread.checksums == manifest.checksums


def test_default_destination_lives_under_backups_and_is_not_nested(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seed_workspace(workspace)

    first, _ = create_backup(workspace)
    assert first.parent == workspace / "backups" / "workspace"
    assert first.parent == (workspace / "backups" / "workspace").resolve()
    first_bytes = first.read_bytes()

    second, second_manifest = create_backup(workspace)
    assert second.exists()
    # The second archive must not contain the first one (no recursion).
    assert not any(name.startswith("backups/") for name in second_manifest.files)
    assert first.read_bytes() == first_bytes


def test_invalid_schema_version_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(WorkspaceBackupError):
        create_backup(workspace, schema_version=0)


def test_missing_workspace_is_reported(tmp_path: Path) -> None:
    with pytest.raises(BackupNotFoundError):
        create_backup(tmp_path / "absent")


# ---------------------------------------------------------------------------
# 2. SQLite consistency and sidecars
# ---------------------------------------------------------------------------


def test_sqlite_database_is_snapshotted_without_sidecars(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = workspace / "career.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE demo (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO demo (value) VALUES (42)")
        connection.commit()
    (workspace / "career.sqlite3-wal").write_bytes(b"")
    (workspace / "career.sqlite3-shm").write_bytes(b"")

    backup_path, manifest = create_backup(workspace)
    assert "career.sqlite3" in manifest.files
    assert not any(name.endswith(("-wal", "-shm", "-journal")) for name in manifest.files)

    target = tmp_path / "restored"
    target.mkdir()
    restore_backup(backup_path, target, confirm=True)
    with sqlite3.connect(target / "career.sqlite3") as connection:
        assert connection.execute("SELECT value FROM demo").fetchone() == (42,)


# ---------------------------------------------------------------------------
# 3. diff_state — no write, explicit conflicts
# ---------------------------------------------------------------------------


def test_diff_state_on_empty_workspace_only_adds(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    files = seed_workspace(workspace)
    backup_path, _ = create_backup(workspace)

    target = tmp_path / "empty"
    target.mkdir()
    plan = diff_state(backup_path, target)
    assert plan.to_add == sorted(files)
    assert plan.to_overwrite == []
    assert plan.conflicts == []
    assert not any(target.iterdir())


def test_diff_state_detects_locally_modified_files_as_conflicts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    files = seed_workspace(workspace)
    backup_path, _ = create_backup(workspace)

    target = tmp_path / "copy"
    target.mkdir()
    for name, content in files.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    unchanged = diff_state(backup_path, target)
    assert unchanged.conflicts == []
    assert unchanged.to_overwrite == sorted(files)

    (target / "documents/cover-letter-demo.txt").write_text("modifié localement", encoding="utf-8")
    plan = diff_state(backup_path, target)
    assert plan.conflicts == ["documents/cover-letter-demo.txt"]
    assert "documents/cover-letter-demo.txt" in plan.to_overwrite


# ---------------------------------------------------------------------------
# 4. Consent and conflicts
# ---------------------------------------------------------------------------


def test_restore_without_confirmation_writes_nothing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    files = seed_workspace(workspace)
    backup_path, _ = create_backup(workspace)

    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(BackupConfirmationRequired) as captured:
        restore_backup(backup_path, target)
    assert captured.value.plan.to_add == sorted(files)
    assert list(target.iterdir()) == []


def test_conflicts_are_not_overwritten_without_explicit_consent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    files = seed_workspace(workspace)
    backup_path, _ = create_backup(workspace)

    target = tmp_path / "target"
    target.mkdir()
    restore_backup(backup_path, target, confirm=True)
    (target / "documents/cover-letter-demo.txt").write_text("version locale importante", encoding="utf-8")

    with pytest.raises(BackupConflictError) as captured:
        restore_backup(backup_path, target, confirm=True)
    assert captured.value.plan.conflicts == ["documents/cover-letter-demo.txt"]
    assert (target / "documents/cover-letter-demo.txt").read_text(encoding="utf-8") == "version locale importante"

    restore_backup(backup_path, target, confirm=True, accept_conflicts=True)
    assert (target / "documents/cover-letter-demo.txt").read_bytes() == files["documents/cover-letter-demo.txt"]


def test_restore_never_deletes_unrelated_local_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seed_workspace(workspace)
    backup_path, _ = create_backup(workspace)

    target = tmp_path / "target"
    target.mkdir()
    (target / "notes-locales.txt").write_text("à conserver", encoding="utf-8")
    restore_backup(backup_path, target, confirm=True)
    assert (target / "notes-locales.txt").read_text(encoding="utf-8") == "à conserver"


# ---------------------------------------------------------------------------
# 5. Schema version gate
# ---------------------------------------------------------------------------


def test_restore_refuses_a_different_schema_without_upgrade(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seed_workspace(workspace)
    backup_path, _ = create_backup(workspace, schema_version=6)

    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(BackupSchemaMismatch):
        diff_state(backup_path, target)
    with pytest.raises(BackupSchemaMismatch):
        restore_backup(backup_path, target, confirm=True)
    assert list(target.iterdir()) == []

    plan = restore_backup(backup_path, target, confirm=True, upgrade=True)
    assert plan.to_add
    assert (target / "applications/demo-application.json").is_file()


# ---------------------------------------------------------------------------
# 6. Adversarial archives
# ---------------------------------------------------------------------------


def test_zip_slip_relative_path_is_rejected_before_any_write(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    _write_zip(
        archive,
        {},
        _manifest({}, files=["../escape.txt"], checksums={"../escape.txt": _sha256(b"owned")}),
        include_manifest=True,
    )
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(UnsafeBackupEntry):
        restore_backup(archive, target, confirm=True)
    assert not (tmp_path / "escape.txt").exists()
    assert list(target.iterdir()) == []


def test_absolute_path_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    absolute = (tmp_path / "escape.txt").resolve()
    _write_zip(
        archive,
        {},
        _manifest({}, files=[str(absolute)], checksums={str(absolute): _sha256(b"owned")}),
    )
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(UnsafeBackupEntry):
        restore_backup(archive, target, confirm=True)
    assert not absolute.exists()


def test_backslash_and_drive_paths_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    for bad_name in ("documents\\..\\escape.txt", "C:/Windows/escape.txt"):
        archive = tmp_path / f"{abs(hash(bad_name))}.zip"
        _write_zip(
            archive,
            {},
            _manifest({}, files=[bad_name], checksums={bad_name: _sha256(b"owned")}),
        )
        with pytest.raises(UnsafeBackupEntry):
            restore_backup(archive, target, confirm=True)


def test_checksum_mismatch_aborts_before_writing(tmp_path: Path) -> None:
    entries = {"documents/demo.txt": b"contenu"}
    archive = tmp_path / "evil.zip"
    _write_zip(archive, entries, _manifest(entries, checksums={"documents/demo.txt": "0" * 64}))
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(BackupIntegrityError):
        restore_backup(archive, target, confirm=True)
    assert list(target.iterdir()) == []


def test_unlisted_payload_file_is_rejected(tmp_path: Path) -> None:
    entries = {"documents/demo.txt": b"contenu"}
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("manifest.json", json.dumps(_manifest(entries)))
        handle.writestr("documents/demo.txt", entries["documents/demo.txt"])
        handle.writestr("smuggled.txt", "non listé".encode("utf-8"))
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(BackupIntegrityError):
        restore_backup(archive, target, confirm=True)
    assert list(target.iterdir()) == []


def test_symlink_archive_entry_is_rejected(tmp_path: Path) -> None:
    info = zipfile.ZipInfo("lien.txt")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = _write_special_zip(tmp_path / "symlink.zip", info, b"../../etc/passwd")
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(UnsafeBackupEntry):
        restore_backup(archive, target, confirm=True)
    assert not (target / "lien.txt").exists()


def test_encrypted_entry_flag_is_rejected(tmp_path: Path) -> None:
    info = zipfile.ZipInfo("secret.txt")
    archive = _write_special_zip(tmp_path / "encrypted.zip", info, b"data")
    _mark_entry_encrypted(archive, "secret.txt")
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(UnsafeBackupEntry):
        restore_backup(archive, target, confirm=True)


def test_duplicate_payload_entries_are_rejected(tmp_path: Path) -> None:
    entries = {"documents/demo.txt": b"contenu"}
    archive = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("manifest.json", json.dumps(_manifest(entries)))
            handle.writestr("documents/demo.txt", entries["documents/demo.txt"])
            handle.writestr("documents/demo.txt", "deuxième".encode("utf-8"))
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(BackupIntegrityError):
        restore_backup(archive, target, confirm=True)


def test_corrupt_zip_is_reported_as_integrity_error(tmp_path: Path) -> None:
    archive = tmp_path / "corrupt.zip"
    archive.write_bytes(b"pas une archive zip")
    with pytest.raises(BackupIntegrityError):
        read_manifest(archive)


def test_missing_manifest_is_reported(tmp_path: Path) -> None:
    archive = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("documents/demo.txt", b"contenu")
    with pytest.raises(BackupIntegrityError):
        read_manifest(archive)


def test_manifest_checksum_for_absent_file_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "inconsistent.zip"
    _write_zip(
        archive,
        {},
        _manifest({}, files=[], checksums={"ghost.txt": _sha256(b"x")}),
    )
    with pytest.raises(BackupIntegrityError):
        read_manifest(archive)


def test_symlinked_local_parent_cannot_escape_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seed_workspace(workspace)
    backup_path, _ = create_backup(workspace)

    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "documents").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafeBackupEntry):
        restore_backup(backup_path, target, confirm=True)
    assert list(outside.iterdir()) == []


# ---------------------------------------------------------------------------
# 7. REST endpoints (smoke test through create_career_router)
# ---------------------------------------------------------------------------


def test_rest_api_round_trip_with_explicit_consent(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    (service.data_dir / "documents" / "demo-note.txt").write_text("note synthétique", encoding="utf-8")
    client = _client(service)

    created = client.post("/api/career/workspace/backups")
    assert created.status_code == 201, created.text
    payload = created.json()
    filename = payload["filename"]
    assert filename.endswith(".zip")
    assert payload["manifest"]["schema_version"] == BACKUP_SCHEMA_VERSION
    assert "career.sqlite3" in payload["manifest"]["files"]

    listed = client.get("/api/career/workspace/backups")
    assert listed.status_code == 200
    assert listed.json()["schema_version"] == BACKUP_SCHEMA_VERSION
    assert [item["filename"] for item in listed.json()["backups"]] == [filename]

    downloaded = client.get(f"/api/career/workspace/backups/{filename}")
    assert downloaded.status_code == 200
    assert downloaded.content[:2] == b"PK"

    planned = client.post(f"/api/career/workspace/backups/{filename}/plan")
    assert planned.status_code == 200
    assert planned.json()["plan"]["conflicts"] == []

    (service.data_dir / "documents" / "demo-note.txt").write_text("note locale modifiée", encoding="utf-8")
    conflicted = client.post(f"/api/career/workspace/backups/{filename}/plan")
    assert conflicted.json()["plan"]["conflicts"] == ["documents/demo-note.txt"]

    refused = client.post(f"/api/career/workspace/backups/{filename}/restore", json={})
    assert refused.status_code == 409
    assert (service.data_dir / "documents" / "demo-note.txt").read_text(encoding="utf-8") == "note locale modifiée"

    unconfirmed_conflict = client.post(
        f"/api/career/workspace/backups/{filename}/restore",
        json={"confirm": True},
    )
    assert unconfirmed_conflict.status_code == 409
    assert unconfirmed_conflict.json()["detail"]["plan"]["conflicts"] == ["documents/demo-note.txt"]

    restored = client.post(
        f"/api/career/workspace/backups/{filename}/restore",
        json={"confirm": True, "accept_conflicts": True},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"] is True
    assert (service.data_dir / "documents" / "demo-note.txt").read_text(encoding="utf-8") == "note synthétique"


def test_rest_api_rejects_path_traversal_and_unknown_backup(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = _client(service)

    for filename in ("..%2F..%2Fescape.zip", "inconnu.zip", ".cache.zip"):
        response = client.get(f"/api/career/workspace/backups/{filename}")
        assert response.status_code in (400, 404)


def test_rest_api_is_mounted_by_create_app(tmp_path: Path) -> None:
    """The mission requires a smoke test through the real app factory."""
    from come_ai_web import create_app

    service = CareerService(tmp_path)
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=service))

    created = client.post("/api/career/workspace/backups")
    assert created.status_code == 201, created.text
    listed = client.get("/api/career/workspace/backups")
    assert listed.status_code == 200
    assert listed.json()["schema_version"] == BACKUP_SCHEMA_VERSION
    assert [item["filename"] for item in listed.json()["backups"]] == [created.json()["filename"]]


def test_rest_api_schema_mismatch_requires_upgrade_flag(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    backup_path, _ = create_backup(service.data_dir, schema_version=6)
    client = _client(service)

    refused = client.post(f"/api/career/workspace/backups/{backup_path.name}/restore", json={"confirm": True})
    assert refused.status_code == 409

    accepted = client.post(
        f"/api/career/workspace/backups/{backup_path.name}/restore",
        json={"confirm": True, "upgrade": True},
    )
    assert accepted.status_code == 200, accepted.text
