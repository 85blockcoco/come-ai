"""Reviewable source changes in isolated copies, with test-gated application.

This module never executes proposed code. Candidate validation is performed by
the diagnostics runner in its operating-system sandbox. Applying and rolling
back are separate, explicit actions; concurrent edits are treated as conflicts.
"""
from __future__ import annotations

import difflib
import fcntl
from functools import wraps
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import tempfile
import threading
import uuid

from .exporting import (materialize_source, source_inventory, source_path_allowed,
                        source_fingerprint, validate_source_text)


MAX_PATCH_BYTES = 2 * 1024 * 1024
MAX_CHANGED_FILES = 100
MAX_FILE_BYTES = 1024 * 1024
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)\n?$")
_ID = re.compile(r"^[0-9a-f]{32}$")


class PatchError(ValueError):
    """Invalid proposal, missing validation, or conflict with user edits."""


def _serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            descriptor = os.open(self.storage_root / ".operation.lock",
                                 os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                return method(self, *args, **kwargs)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
    return wrapped


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PatchError("Chemin de fichier invalide.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise PatchError("Les chemins absolus et les traversées de dossiers sont refusés.")
    if not source_path_allowed(value):
        raise PatchError("Ce fichier ne fait pas partie du code source autorisé.")
    return value


def _target(root: Path, relative: str) -> Path:
    relative = _safe_relative(relative)
    target = root.joinpath(*PurePosixPath(relative).parts)
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PatchError("Les liens symboliques sont refusés.")
        if cursor.exists() and cursor != target and not cursor.is_dir():
            raise PatchError("Un dossier de destination est remplacé par un fichier.")
    if target.exists() and not target.is_file():
        raise PatchError("La destination n'est pas un fichier source.")
    return target


def _read(root: Path, relative: str) -> bytes | None:
    path = _target(root, relative)
    if not path.exists():
        return None
    if path.stat().st_size > MAX_FILE_BYTES:
        raise PatchError("Fichier source trop volumineux.")
    content = path.read_bytes()
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchError("Seuls les fichiers texte UTF-8 sont acceptés.") from exc
    if b"\x00" in content:
        raise PatchError("Les fichiers binaires sont refusés.")
    return content


def _atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".devkit-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save_json(path: Path, value: dict) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))


def _load_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * MAX_PATCH_BYTES:
        raise PatchError("Métadonnées de correctif introuvables ou invalides.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PatchError("Métadonnées de correctif invalides.") from exc
    if not isinstance(value, dict):
        raise PatchError("Métadonnées de correctif invalides.")
    return value


def _diff(relative: str, before: bytes | None, after: bytes | None) -> str:
    old = (before or b"").decode("utf-8").splitlines(keepends=True)
    new = (after or b"").decode("utf-8").splitlines(keepends=True)
    lines = difflib.unified_diff(old, new, fromfile=f"a/{relative}" if before is not None else "/dev/null",
                                 tofile=f"b/{relative}" if after is not None else "/dev/null")
    result = []
    for line in lines:
        result.append(line)
        if not line.endswith("\n"):
            result.append("\n\\ No newline at end of file\n")
    # An empty new/deleted file still needs a reviewable file operation.
    if before != after and not result:
        result = [f"--- {'a/' + relative if before is not None else '/dev/null'}\n",
                  f"+++ {'b/' + relative if after is not None else '/dev/null'}\n", "@@ -0,0 +0,0 @@\n"]
    return "".join(result)


def _header_path(line: str, prefix: str) -> str | None:
    value = line[len(prefix):].rstrip("\r\n").split("\t", 1)[0]
    if value == "/dev/null":
        return None
    if value.startswith(('"', "'")):
        raise PatchError("Les chemins cités ou échappés ne sont pas acceptés.")
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return _safe_relative(value)


def _parse_patch(patch: str, root: Path) -> tuple[dict[str, bytes | None], dict[str, str | None]]:
    if not isinstance(patch, str) or len(patch.encode("utf-8")) > MAX_PATCH_BYTES or "\x00" in patch:
        raise PatchError("Correctif vide, binaire ou trop volumineux.")
    lines = patch.splitlines(keepends=True)
    changes: dict[str, bytes | None] = {}
    expected_before = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            try:
                parts = shlex.split(line.strip())
            except ValueError as exc:
                raise PatchError("Entête Git invalide.") from exc
            if len(parts) != 4 or _header_path("--- " + parts[2], "--- ") != _header_path("+++ " + parts[3], "+++ "):
                raise PatchError("Les renommages ne sont pas acceptés.")
            index += 1
            continue
        if line.startswith("index ") or not line.strip():
            index += 1
            continue
        if line.strip() in ("new file mode 100644", "deleted file mode 100644"):
            index += 1
            continue
        if not line.startswith("--- ") or index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise PatchError("Format unified diff invalide ou modification de permissions refusée.")
        old_path = _header_path(line, "--- ")
        new_path = _header_path(lines[index + 1], "+++ ")
        if old_path is None and new_path is None or old_path is not None and new_path is not None and old_path != new_path:
            raise PatchError("Les renommages ou chemins incohérents sont refusés.")
        relative = old_path or new_path
        assert relative is not None
        if relative in changes or len(changes) >= MAX_CHANGED_FILES:
            raise PatchError("Fichier dupliqué ou trop de fichiers dans le correctif.")
        before = _read(root, relative)
        if old_path is None and before is not None or old_path is not None and before is None:
            raise PatchError("Le fichier source ne correspond pas au correctif.")
        original = (before or b"").decode("utf-8").splitlines(keepends=True)
        output: list[str] = []
        cursor = 0
        index += 2
        hunks = 0
        while index < len(lines) and lines[index].startswith("@@ "):
            match = _HUNK.fullmatch(lines[index])
            if not match:
                raise PatchError("Entête de bloc invalide.")
            old_start = int(match[1])
            old_count = int(match[2] or "1")
            new_start = int(match[3])
            new_count = int(match[4] or "1")
            old_offset = old_start if old_count == 0 else old_start - 1
            new_offset = new_start if new_count == 0 else new_start - 1
            if old_offset < cursor or old_offset > len(original):
                raise PatchError("Position de bloc invalide.")
            output.extend(original[cursor:old_offset])
            cursor = old_offset
            if new_offset != len(output):
                raise PatchError("Position de destination incohérente.")
            index += 1
            entries: list[tuple[str, str]] = []
            consumed = produced = 0
            while index < len(lines):
                item = lines[index]
                if item.startswith("\\ No newline at end of file"):
                    if not entries or not entries[-1][1].endswith("\n"):
                        raise PatchError("Marqueur de fin de ligne invalide.")
                    kind, body = entries[-1]
                    entries[-1] = (kind, body[:-1])
                    index += 1
                    continue
                if consumed == old_count and produced == new_count:
                    break
                if not item or item[0] not in " +-":
                    raise PatchError("Contenu de bloc incomplet.")
                kind, body = item[0], item[1:]
                entries.append((kind, body))
                consumed += kind in " -"
                produced += kind in " +"
                if consumed > old_count or produced > new_count:
                    raise PatchError("Longueur de bloc incohérente.")
                index += 1
            if consumed != old_count or produced != new_count:
                raise PatchError("Bloc tronqué.")
            for kind, body in entries:
                if kind in " -":
                    if cursor >= len(original) or original[cursor] != body:
                        raise PatchError("Le contexte du correctif ne correspond pas au source.")
                    cursor += 1
                if kind in " +":
                    output.append(body)
            hunks += 1
        if not hunks:
            raise PatchError("Un fichier doit contenir au moins un bloc unified diff.")
        output.extend(original[cursor:])
        after = "".join(output).encode("utf-8") if new_path is not None else None
        if new_path is None and output:
            raise PatchError("La suppression doit supprimer tout le contenu du fichier.")
        if after is not None and len(after) > MAX_FILE_BYTES:
            raise PatchError("Fichier proposé trop volumineux.")
        changes[relative] = after
        expected_before[relative] = _digest(before)
    if not changes:
        raise PatchError("Le correctif ne contient aucun fichier.")
    return changes, expected_before


class PatchWorkspace:
    def __init__(self, project_root: Path, storage_root: Path):
        self.project_root = Path(project_root).resolve(strict=True)
        unresolved_storage = Path(storage_root).absolute()
        if any(path.is_symlink() for path in (unresolved_storage, *unresolved_storage.parents)):
            raise PatchError("Les liens symboliques de stockage sont refusés.")
        self.storage_root = unresolved_storage.resolve()
        if not self.project_root.is_dir() or self.storage_root == self.project_root:
            raise PatchError("Dossiers du projet et de l'atelier invalides.")
        if self.storage_root.is_relative_to(self.project_root):
            relative = self.storage_root.relative_to(self.project_root).as_posix()
            if source_path_allowed(relative + "/probe.py"):
                raise PatchError("Le stockage de l'atelier doit rester hors des dossiers de code exportés.")
        self.storage_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.storage_root, 0o700)
        self._lock = threading.RLock()

    def _directory(self, group: str, identifier: str) -> Path:
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise PatchError("Identifiant de correctif invalide.")
        directory = self.storage_root / group / identifier
        if (self.storage_root / group).is_symlink() or directory.is_symlink() or not directory.is_dir():
            raise PatchError("Correctif introuvable.")
        return directory

    def _new_directory(self, group: str, identifier: str) -> Path:
        parent = self.storage_root / group
        if parent.is_symlink():
            raise PatchError("Les liens symboliques de stockage sont refusés.")
        parent.mkdir(parents=True, exist_ok=True)
        directory = parent / identifier
        directory.mkdir(mode=0o700)
        return directory

    def candidate_path(self, candidate_id: str) -> Path:
        directory = self._directory("candidates", candidate_id)
        path = directory / "source"
        if path.is_symlink() or not path.is_dir():
            raise PatchError("Copie de travail introuvable.")
        return path

    @_serialized
    def stage_patch(self, patch_text: str, *, allowed_paths: list[str] | None = None) -> dict:
        changes, expected_before = _parse_patch(patch_text, self.project_root)
        if allowed_paths is not None and not set(changes).issubset(allowed_paths):
            raise PatchError("La proposition touche un fichier hors du périmètre demandé.")
        return self._stage(changes, expected_before)

    @_serialized
    def stage_files(self, files: dict[str, str | None], *, allowed_paths: list[str] | None = None) -> dict:
        if not isinstance(files, dict) or not files or len(files) > MAX_CHANGED_FILES:
            raise PatchError("Liste de fichiers vide ou trop volumineuse.")
        if allowed_paths is not None and not set(files).issubset(allowed_paths):
            raise PatchError("La proposition touche un fichier hors du périmètre demandé.")
        changes = {}
        for relative, content in files.items():
            _target(self.project_root, relative)
            if content is not None and (not isinstance(content, str) or "\x00" in content):
                raise PatchError("Seuls les fichiers texte UTF-8 sont acceptés.")
            encoded = content.encode("utf-8") if content is not None else None
            if encoded is not None and len(encoded) > MAX_FILE_BYTES:
                raise PatchError("Fichier proposé trop volumineux.")
            changes[relative] = encoded
        if sum(len(content or b"") for content in changes.values()) > MAX_PATCH_BYTES:
            raise PatchError("Correctif trop volumineux.")
        return self._stage(changes)

    def _stage(self, changes: dict[str, bytes | None], expected_before: dict | None = None) -> dict:
        try:
            for content in changes.values():
                if content is not None:
                    validate_source_text(content.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise PatchError("La proposition contient un fichier source non autorisé.") from exc
        identifier = uuid.uuid4().hex
        directory = self._new_directory("candidates", identifier)
        candidate = directory / "source"
        base_inventory = materialize_source(self.project_root, candidate)
        actual = []
        try:
            for relative, after in sorted(changes.items()):
                before = _read(self.project_root, relative)
                if expected_before is not None and _digest(before) != expected_before[relative]:
                    raise PatchError("Le source a changé pendant la préparation.")
                if before == after:
                    continue
                if before is not None:
                    _atomic_write(directory / "base" / relative, before)
                path = _target(candidate, relative)
                if after is None:
                    if path.exists():
                        path.unlink()
                else:
                    _atomic_write(path, after, 0o644)
                actual.append({"path": relative, "before_sha256": _digest(before), "after_sha256": _digest(after),
                               "operation": "delete" if after is None else "add" if before is None else "modify"})
            if not actual:
                raise PatchError("Le correctif ne modifie aucun fichier.")
            # Export policy also rejects embedded tokens and invalid source data.
            source_inventory(candidate)
            metadata = {"candidate_id": identifier, "status": "staged", "base_inventory": base_inventory,
                        "changes": actual, "validation": None, "created_at": _now()}
            _save_json(directory / "metadata.json", metadata)
        except (ValueError, OSError) as exc:
            _save_json(directory / "metadata.json", {"candidate_id": identifier, "status": "rejected", "changes": [], "created_at": _now()})
            raise PatchError("La proposition est refusée par la politique du code source.") from exc
        return self.preview(identifier)

    def preview(self, candidate_id: str) -> dict:
        directory = self._directory("candidates", candidate_id)
        metadata = _load_json(directory / "metadata.json")
        candidate = self.candidate_path(candidate_id)
        changes = metadata.get("changes", [])
        diff = "".join(_diff(item["path"], _read(directory / "base", item["path"]), _read(candidate, item["path"]))
                       for item in changes)
        return {"candidate_id": candidate_id, "status": metadata["status"], "diff": diff,
                "changed_files": [{"path": item["path"], "operation": item["operation"]} for item in changes],
                "validated": bool(metadata.get("validation")), "requires_explicit_apply": True,
                "validation_status": "passed" if metadata.get("validation") else "not_validated",
                "created_at": metadata.get("created_at")}

    def _list_metadata(self, group: str, limit: int) -> list[tuple[str, dict]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise PatchError("La limite d'historique doit être comprise entre 1 et 100.")
        parent = self.storage_root / group
        if parent.is_symlink():
            raise PatchError("Un dossier d'historique est remplacé par un lien symbolique.")
        if not parent.exists():
            return []
        results = []
        # IDs are random; use timestamps recorded in atomically persisted metadata.
        for scanned, directory in enumerate(parent.iterdir()):
            if scanned >= 1000:
                break
            if directory.is_symlink() or not directory.is_dir() or not _ID.fullmatch(directory.name):
                continue
            try:
                value = _load_json(directory / "metadata.json")
                changes = value.get("changes", [])
                if not isinstance(changes, list) or len(changes) > MAX_CHANGED_FILES:
                    continue
                for item in changes:
                    _safe_relative(item["path"])
                    if item.get("operation") not in {"modify", "add", "delete"}:
                        raise PatchError("Opération d'historique invalide.")
                if group == "transactions" and not _ID.fullmatch(str(value.get("candidate_id", ""))):
                    continue
                if value.get("status") not in {"staged", "rejected", "validated", "applied", "preparing", "rolled_back", "restored_after_error", "recovery_required"}:
                    continue
                results.append((directory.name, value))
            except (ValueError, OSError, KeyError, TypeError):
                continue
        results.sort(key=lambda item: str(item[1].get("created_at", "")), reverse=True)
        return results[:limit]

    def list_candidates(self, limit: int = 20) -> list[dict]:
        return [{"candidate_id": identifier, "status": value["status"],
                 "created_at": value.get("created_at"),
                 "changed_files": [{"path": item["path"], "operation": item["operation"]} for item in value["changes"]],
                 "validated": bool(value.get("validation")), "requires_explicit_apply": True,
                 "validation_status": "passed" if value.get("validation") else "not_validated"}
                for identifier, value in self._list_metadata("candidates", limit)]

    def list_transactions(self, limit: int = 20) -> list[dict]:
        return [{"transaction_id": identifier, "status": value["status"],
                 "candidate_id": value.get("candidate_id"), "created_at": value.get("created_at"),
                 "changed_files": [item["path"] for item in value["changes"]],
                 "rollback_available": value["status"] == "applied"}
                for identifier, value in self._list_metadata("transactions", limit)]

    @_serialized
    def mark_validation(self, candidate_id: str, report: dict) -> dict:
        directory = self._directory("candidates", candidate_id)
        metadata = _load_json(directory / "metadata.json")
        if metadata.get("status") not in ("staged", "validated"):
            raise PatchError("Ce correctif ne peut pas être validé.")
        fingerprint = source_fingerprint(self.candidate_path(candidate_id))
        checks = report.get("checks", []) if isinstance(report, dict) else []
        if isinstance(checks, dict):
            pytest_passed = isinstance(checks.get("pytest"), dict) and checks["pytest"].get("status") == "passed"
        else:
            pytest_passed = any(isinstance(item, dict) and item.get("name") == "pytest" and item.get("status") == "passed" for item in checks)
        count = report.get("tests_executed", 0) if isinstance(report, dict) else 0
        if (not isinstance(report, dict) or report.get("status") != "passed" or not pytest_passed
                or not isinstance(count, int) or isinstance(count, bool) or count < 1
                or report.get("sandbox_used") is not True or report.get("pytest_receipt_verified") is not True
                or report.get("source_fingerprint") != fingerprint):
            metadata["validation"] = None
            metadata["status"] = "staged"
            _save_json(directory / "metadata.json", metadata)
            raise PatchError("Tests réussis dans la copie isolée et empreinte correspondante requis.")
        metadata["validation"] = {"status": "passed", "pytest": "passed", "tests_executed": count,
                                  "sandbox_used": True, "pytest_receipt_verified": True, "source_fingerprint": fingerprint}
        metadata["status"] = "validated"
        _save_json(directory / "metadata.json", metadata)
        return self.preview(candidate_id)

    @_serialized
    def apply(self, candidate_id: str) -> dict:
        directory = self._directory("candidates", candidate_id)
        metadata = _load_json(directory / "metadata.json")
        candidate = self.candidate_path(candidate_id)
        validation = metadata.get("validation")
        if metadata.get("status") != "validated" or not validation or validation.get("source_fingerprint") != source_fingerprint(candidate):
            raise PatchError("Le correctif nécessite une validation actuelle des tests.")
        if source_inventory(self.project_root) != metadata.get("base_inventory"):
            raise PatchError("Conflit : le code principal a changé depuis la préparation.")
        identifier = uuid.uuid4().hex
        transaction = self._new_directory("transactions", identifier)
        prepared = []
        for item in metadata["changes"]:
            relative = item["path"]
            before = _read(self.project_root, relative)
            after = _read(candidate, relative)
            if _digest(before) != item["before_sha256"] or _digest(after) != item["after_sha256"]:
                raise PatchError("Conflit : contenu du correctif modifié.")
            path = _target(self.project_root, relative)
            mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
            if before is not None:
                _atomic_write(transaction / "before" / relative, before)
            if after is not None:
                _atomic_write(transaction / "after" / relative, after)
            prepared.append({**item, "mode": mode})
        record = {"transaction_id": identifier, "candidate_id": candidate_id, "status": "preparing",
                  "changes": prepared, "created_at": _now()}
        _save_json(transaction / "metadata.json", record)
        applied = []
        try:
            for item in prepared:
                path = _target(self.project_root, item["path"])
                if _digest(_read(self.project_root, item["path"])) != item["before_sha256"]:
                    raise PatchError("Une édition est survenue pendant l'application.")
                applied.append(item)
                after = _read(candidate, item["path"])
                if after is None:
                    path.unlink()
                else:
                    _atomic_write(path, after, item["mode"])
        except (OSError, PatchError) as exc:
            recovered = True
            for item in reversed(applied):
                current = _digest(_read(self.project_root, item["path"]))
                if current == item["before_sha256"]:
                    continue
                if current != item["after_sha256"]:
                    # Preserve a user edit even when recovering an earlier I/O error.
                    recovered = False
                    continue
                try:
                    self._restore_before(transaction, item)
                except (OSError, PatchError):
                    recovered = False
            record["status"] = "restored_after_error" if recovered else "recovery_required"
            _save_json(transaction / "metadata.json", record)
            if not recovered:
                raise PatchError("Application interrompue ; une récupération manuelle est nécessaire. Les éditions concurrentes sont préservées.") from exc
            raise PatchError("Application interrompue ; fichiers précédents restaurés.") from exc
        record["status"] = "applied"
        _save_json(transaction / "metadata.json", record)
        metadata["status"] = "applied"
        metadata["transaction_id"] = identifier
        _save_json(directory / "metadata.json", metadata)
        return {"transaction_id": identifier, "candidate_id": candidate_id, "status": "applied",
                "changed_files": [item["path"] for item in prepared], "rollback_available": True}

    def _restore_before(self, transaction: Path, item: dict) -> None:
        self._restore_snapshot(transaction, item, "before")

    def _restore_snapshot(self, transaction: Path, item: dict, version: str) -> None:
        path = _target(self.project_root, item["path"])
        expected_hash = item[version + "_sha256"]
        if expected_hash is None:
            if path.exists():
                path.unlink()
        else:
            backup = transaction / version / item["path"]
            if backup.is_symlink() or _digest(backup.read_bytes()) != expected_hash:
                raise PatchError("Sauvegarde de retour arrière invalide.")
            _atomic_write(path, backup.read_bytes(), item["mode"])

    @_serialized
    def rollback(self, transaction_id: str) -> dict:
        transaction = self._directory("transactions", transaction_id)
        record = _load_json(transaction / "metadata.json")
        if record.get("status") != "applied":
            raise PatchError("Ce retour arrière n'est plus disponible.")
        for item in record["changes"]:
            if _digest(_read(self.project_root, item["path"])) != item["after_sha256"]:
                raise PatchError("Conflit : une édition plus récente empêche le retour arrière.")
            if item["before_sha256"] is not None:
                backup = transaction / "before" / item["path"]
                if backup.is_symlink() or _digest(backup.read_bytes()) != item["before_sha256"]:
                    raise PatchError("Sauvegarde de retour arrière invalide.")
        restored = []
        try:
            for item in reversed(record["changes"]):
                if _digest(_read(self.project_root, item["path"])) != item["after_sha256"]:
                    raise PatchError("Une édition est survenue pendant le retour arrière.")
                restored.append(item)
                self._restore_before(transaction, item)
        except (OSError, PatchError) as exc:
            recovered = True
            for item in reversed(restored):
                current = _digest(_read(self.project_root, item["path"]))
                if current == item["after_sha256"]:
                    continue
                if current != item["before_sha256"]:
                    recovered = False
                    continue
                try:
                    self._restore_snapshot(transaction, item, "after")
                except (OSError, PatchError):
                    recovered = False
            if not recovered:
                record["status"] = "recovery_required"
                _save_json(transaction / "metadata.json", record)
                raise PatchError("Retour arrière interrompu ; récupération manuelle nécessaire, éditions concurrentes préservées.") from exc
            raise PatchError("Retour arrière interrompu ; l'état après correctif est conservé.") from exc
        record["status"] = "rolled_back"
        _save_json(transaction / "metadata.json", record)
        return {"transaction_id": transaction_id, "status": "rolled_back",
                "restored_files": [item["path"] for item in record["changes"]]}


__all__ = ["PatchError", "PatchWorkspace", "source_fingerprint"]
