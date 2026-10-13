"""Small, offline source snapshots and portable AI repair requests.

The allowlist is intentionally shared by exports and patch staging. Credentials,
documents and application databases are never discovered or opened by this module.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import math
import os
import platform
import re
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 15 * 1024 * 1024
MAX_FILES = 1000
MAX_REPORT_BYTES = 1024 * 1024
SOURCE_DIRECTORIES = frozenset(
    {"career", "tests", "devkit", "evals", "web_static", "career_static", "v5_static"}
)
SOURCE_SUFFIXES = frozenset({".py", ".html", ".css", ".js", ".md", ".txt", ".ini", ".toml"})
EXCLUDED_DIRECTORIES = frozenset(
    {"data", "output", "logs", "state", "career_data", "memory_data", "cache",
     "__pycache__", "node_modules", "backup", "backups", "exports"}
)
EXCLUDED_ROOT_FILES = frozenset({"agent.py", "agent_v2.py", "test_gemini.py"})

_SECRET_PATTERNS = (
    re.compile(r"\bAQ\.[0-9A-Za-z_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"sk-or-v1-[0-9A-Za-z_-]{24,}"),
    re.compile(r"\bsk-(?:proj-)?[0-9A-Za-z_-]{24,}"),
    re.compile(r"(?i)\bbearer\s+[0-9A-Za-z_.+/=-]{24,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:https?|ssh)://[^\s/:@]+:[^\s/@]+@"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[=:]\s*['\"]([0-9A-Za-z_.+/=-]{24,})['\"]"),
)
_PRIVATE_FIELDS = frozenset(
    {"api_key", "apikey", "access_token", "authorization", "client_secret", "password",
     "environment", "env", "profile", "personal_data", "credentials"}
)
_LOCAL_PATH = re.compile(
    r"(?<![\w:/])(?:/(?:Users|home|private|tmp|var|Volumes)/[^\s\"'<>]*|[A-Za-z]:[\\/][^\s\"'<>]*)"
)


class KitError(ValueError):
    """A safe, user-facing maintenance validation error."""


def validate_source_text(content: str) -> None:
    """Reject binary/oversized source and credential-shaped literals before staging."""
    if not isinstance(content, str):
        raise KitError("Le correctif source doit être du texte UTF-8.")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError:
        raise KitError("Le correctif source doit être du texte UTF-8.") from None
    if len(encoded) > MAX_FILE_BYTES:
        raise KitError("Un fichier source dépasse la limite de taille du kit.")
    if "\x00" in content:
        raise KitError("Un fichier source contient des données binaires.")
    if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
        raise KitError("Export bloqué : un secret potentiel est présent dans le code autorisé. Aucun fragment n'a été affiché.")


def source_path_allowed(relative_path: str) -> bool:
    """Return whether a portable relative path belongs to the source allowlist."""
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in relative_path):
        return False
    if "\x00" in relative_path or ":" in relative_path or relative_path.startswith("/"):
        return False
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    if len(parts) == 1:
        name = parts[0]
        if name in EXCLUDED_ROOT_FILES:
            return False
        return (
            (not name.startswith(".") and name.endswith(".py"))
            or (name.startswith("README") and name.endswith(".md"))
            or (name.startswith("requirements") and name.endswith(".txt"))
            or name in {"pytest.ini", ".gitignore"}
        )
    if parts[0] not in SOURCE_DIRECTORIES:
        return False
    if any(part.startswith(".") or part.lower() in EXCLUDED_DIRECTORIES for part in parts):
        return False
    if parts[0] == "evals":
        # Evaluation code and synthetic cases belong to diagnostics. Persisted
        # observations are not source: they may contain future private inputs.
        if parts[1] == "runs":
            return False
        if PurePosixPath(relative_path).suffix.lower() == ".json":
            return len(parts) == 3 and parts[1] == "cases"
    return PurePosixPath(relative_path).suffix.lower() in SOURCE_SUFFIXES


def _project_root(project_root: Path) -> Path:
    root = Path(project_root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise KitError("Le dossier du projet doit être un dossier local existant sans lien symbolique.")
    return root.resolve()


def _read_source(root: Path, relative_path: str) -> bytes:
    if not source_path_allowed(relative_path):
        raise KitError("Un chemin demandé est hors du périmètre de code autorisé.")
    path = root.joinpath(*relative_path.split("/"))
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            raise KitError("Les liens symboliques sont exclus des échanges de code.")
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            attributes = os.fstat(handle.fileno())
            if not stat.S_ISREG(attributes.st_mode):
                raise KitError("Seuls les fichiers source ordinaires sont autorisés.")
            if attributes.st_size > MAX_FILE_BYTES:
                raise KitError("Un fichier source dépasse la limite de taille du kit.")
            content = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise KitError("Un fichier source n'est pas accessible.") from None
    if len(content) > MAX_FILE_BYTES:
        raise KitError("Un fichier source dépasse la limite de taille du kit.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise KitError("Un fichier source n'est pas du texte UTF-8 exportable.") from None
    validate_source_text(text)
    return content


def _sources(project_root: Path, selected_files: list[str] | None = None) -> tuple[Path, list[tuple[str, bytes]]]:
    root = _project_root(project_root)
    if selected_files is not None:
        if not isinstance(selected_files, list) or not all(isinstance(item, str) for item in selected_files):
            raise KitError("La sélection doit être une liste de chemins source relatifs.")
        candidates = sorted(set(selected_files))
        if not candidates:
            raise KitError("Sélectionnez au moins un fichier source pour la demande de correction.")
    else:
        candidates = []
        for child in root.iterdir():
            if child.is_symlink():
                continue
            if child.is_file() and source_path_allowed(child.name):
                candidates.append(child.name)
            elif child.is_dir() and child.name in SOURCE_DIRECTORIES:
                for current_dir, directories, filenames in os.walk(child, followlinks=False):
                    current_path = Path(current_dir)
                    directories[:] = sorted(
                        name for name in directories
                        if not name.startswith(".")
                        and name.lower() not in EXCLUDED_DIRECTORIES
                        and not (current_path == root / "evals" and name == "runs")
                        and not (current_path / name).is_symlink()
                    )
                    for name in filenames:
                        path = current_path / name
                        relative_path = path.relative_to(root).as_posix()
                        if not path.is_symlink() and source_path_allowed(relative_path):
                            candidates.append(relative_path)
        candidates.sort()
    if len(candidates) > MAX_FILES:
        raise KitError("Le nombre de fichiers source dépasse la limite du kit.")
    contents = []
    total_bytes = 0
    for relative_path in candidates:
        content = _read_source(root, relative_path)
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_BYTES:
            raise KitError("Le volume source total dépasse la limite du kit.")
        contents.append((relative_path, content))
    return root, contents


def _inventory(contents: list[tuple[str, bytes]]) -> list[dict]:
    return [
        {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
        for path, content in contents
    ]


def source_inventory(project_root: Path) -> list[dict]:
    """Read and validate source only; return content hashes without source text."""
    _, contents = _sources(project_root)
    return _inventory(contents)


def source_fingerprint(project_root: Path) -> str:
    """Hash the canonical path/content identities used by diagnostics and patches."""
    return _inventory_fingerprint(source_inventory(project_root))


def _inventory_fingerprint(inventory: list[dict]) -> str:
    identities = sorted(({"path": item["path"], "sha256": item["sha256"]} for item in inventory), key=lambda item: item["path"])
    canonical = json.dumps(identities, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def materialize_source(project_root: Path, destination: Path) -> list[dict]:
    """Create a new isolated source tree; never overwrite an existing directory."""
    root, contents = _sources(project_root)
    destination = Path(destination).absolute()
    if destination == root or destination.is_symlink() or destination.exists():
        raise KitError("La copie isolée nécessite un dossier de destination neuf.")
    try:
        destination.mkdir(parents=True, exist_ok=False)
        for relative_path, content in contents:
            target = destination.joinpath(*relative_path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(content)
    except OSError:
        raise KitError("La copie isolée n'a pas pu être créée. Le projet principal est inchangé.") from None
    return _inventory(contents)


def redact_text(text: str, project_root: Path | None = None) -> str:
    """Mask credentials and local paths in diagnostics supplied by the caller."""
    value = str(text)
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[SECRET MASQUÉ]", value)
    if project_root is not None:
        root_text = str(Path(project_root).absolute())
        value = value.replace(root_text + os.sep, "<projet>/").replace(root_text, "<projet>")
    return _LOCAL_PATH.sub("<chemin local>", value)


def _safe_report(value: Any, root: Path, depth: int = 0) -> Any:
    if depth > 12:
        return "[structure tronquée]"
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:500]:
            safe_key = redact_text(str(key), root)[:200]
            result[safe_key] = (
                "[DONNÉE PRIVÉE MASQUÉE]"
                if str(key).lower().replace("-", "_") in _PRIVATE_FIELDS
                else _safe_report(item, root, depth + 1)
            )
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_report(item, root, depth + 1) for item in value[:500]]
    if isinstance(value, str):
        return redact_text(value, root)[:100_000]
    if isinstance(value, float) and not math.isfinite(value):
        return "[valeur numérique non finie]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[valeur non portable]"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _dependencies(contents: list[tuple[str, bytes]]) -> dict:
    names = set()
    for path, content in contents:
        if "/" not in path and path.startswith("requirements") and path.endswith(".txt"):
            for line in content.decode("utf-8").splitlines():
                # Only package names are exported, never URL/VCS/private-index lines.
                match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?\s*(?:[<>=!~;]|$)", line)
                if match:
                    names.add(match.group(1))
    packages = []
    for name in sorted(names, key=str.lower):
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = None
        packages.append({"name": name, "installed_version": version})
    return {
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "packages": packages,
        "note": "Versions du runtime qui produit l'archive ; aucun environnement, jeton ni URL d'installation exporté.",
    }


def _architecture(inventory: list[dict]) -> str:
    paths = {entry["path"] for entry in inventory}
    roles = {
        "come_ai_web.py": "Serveur web local, API et orchestration de l'interface.",
        "workspace_core.py": "Configuration, espaces de fichiers et outils Python contrôlés.",
        "v5_orchestrator.py": "Plans d'action et orchestration locale.",
        "personal_memory.py": "Indexation et recherche dans la mémoire documentaire locale.",
        "memory_storage.py": "Diagnostics en lecture seule du stockage.",
        "task_queue.py": "File de tâches persistante et suivi de progression.",
        "free_ai_router.py": "Politique de choix de modèles gratuits et locaux.",
        "usage_ledger.py": "Journal local de consommation des modèles.",
        "run_come_ai_v3.py": "Lancement de l'application locale.",
    }
    lines = [
        "# Architecture du snapshot", "",
        "Les repères ci-dessous décrivent les couches habituelles de Côme AI. Leur présence",
        "dans cette archive est signalée ; un fichier non fourni n'a pas été joint.",
        "L'inventaire final décrit uniquement les fichiers inclus. Les données personnelles,",
        "bases privées, clés, documents, journaux et environnements virtuels sont exclus.", "",
    ]
    for name, role in roles.items():
        availability = "inclus" if name in paths else "non fourni"
        lines.append(f"- `{name}` : {role} ({availability}).")
    group_roles = {
        "career": "outils de profil, candidatures et carrière",
        "web_static": "interface locale historique",
        "career_static": "interface carrière",
        "v5_static": "interface du workspace personnel",
        "devkit": "diagnostics, export et correctifs isolés",
        "tests": "tests reproductibles hors ligne",
    }
    for directory, role in group_roles.items():
        count = sum(path.startswith(directory + "/") for path in paths)
        lines.append(f"- `{directory}/` : {role} ({count} fichiers inclus).")
    lines.extend(["", "## Périmètre", "", *[f"- `{entry['path']}`" for entry in inventory], ""])
    return "\n".join(lines)


def _write_archive(destination: Path, entries: dict[str, bytes]) -> Path:
    destination = Path(destination).absolute()
    if destination.suffix.lower() != ".zip":
        raise KitError("La destination doit être une nouvelle archive .zip.")
    if destination.exists() or destination.is_symlink():
        raise KitError("Une archive existe déjà à cette destination ; aucun écrasement n'est autorisé.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(buffer.getvalue())
    except FileExistsError:
        raise KitError("Une archive existe déjà à cette destination ; aucun écrasement n'est autorisé.") from None
    except OSError:
        raise KitError("L'archive n'a pas pu être écrite.") from None
    return destination


def _snapshot_entries(root: Path, contents: list[tuple[str, bytes]], diagnostic_report: dict | None, *, entire_project: bool = False) -> tuple[dict[str, bytes], dict]:
    inventory = _inventory(contents)
    manifest = {
        "schema_version": 1,
        "kind": "come_ai_source_snapshot",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": inventory,
        "file_count": len(inventory),
        "total_source_bytes": sum(entry["size_bytes"] for entry in inventory),
        "excluded_categories": ["credentials", "personal_documents", "private_databases", "logs", "virtual_environments", "binary_assets", "historical_agents"],
        "limits": {"max_file_bytes": MAX_FILE_BYTES, "max_total_bytes": MAX_TOTAL_BYTES, "max_files": MAX_FILES},
    }
    manifest["diagnostic_matches_project"] = (
        diagnostic_report.get("source_fingerprint") == _inventory_fingerprint(inventory)
        if entire_project and isinstance(diagnostic_report, dict) else None
    )
    manifest["source_fingerprint"] = _inventory_fingerprint(inventory)
    report = _safe_report(diagnostic_report, root) if diagnostic_report is not None else {
        "status": "not_provided", "note": "Aucun test n'est lancé automatiquement pendant un export."
    }
    report_bytes = _json_bytes(report)
    if len(report_bytes) > MAX_REPORT_BYTES:
        raise KitError("Le rapport de diagnostic dépasse la limite exportable.")
    entries = {"source/" + path: content for path, content in contents}
    entries.update({
        "MANIFEST.json": _json_bytes(manifest),
        "ARCHITECTURE.md": _architecture(inventory).encode("utf-8"),
        "DEPENDENCIES.json": _json_bytes(_dependencies(contents)),
        "DIAGNOSTICS.json": report_bytes,
    })
    return entries, manifest


def export_snapshot(project_root: Path, destination: Path, *, diagnostic_report: dict | None = None) -> dict:
    """Export an offline, allowlisted project snapshot to a new ZIP archive."""
    root, contents = _sources(project_root)
    entries, manifest = _snapshot_entries(root, contents, diagnostic_report, entire_project=True)
    archive_path = _write_archive(destination, entries)
    return {"archive_path": str(archive_path), "file_count": manifest["file_count"],
            "total_bytes": manifest["total_source_bytes"], "manifest": manifest}


def build_issue_bundle(
    project_root: Path,
    destination: Path,
    *,
    title: str,
    description: str,
    errors: str = "",
    selected_files: list[str] | None = None,
    diagnostic_report: dict | None = None,
) -> dict:
    """Create a portable repair request containing only explicitly selected code."""
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise KitError("Le titre doit contenir entre 1 et 200 caractères.")
    if not isinstance(description, str) or not description.strip() or len(description) > 20_000:
        raise KitError("La description doit contenir entre 1 et 20 000 caractères.")
    if not isinstance(errors, str) or len(errors) > 200_000:
        raise KitError("Les erreurs doivent être un texte de moins de 200 000 caractères.")
    if selected_files is None:
        raise KitError("La demande de correction nécessite une sélection explicite des fichiers concernés.")
    root, contents = _sources(project_root, selected_files)
    entries, manifest = _snapshot_entries(root, contents, diagnostic_report)
    # A targeted issue still needs dependency context, but no unrelated code or
    # personal data is copied. Only allowlisted root requirements are read here.
    requirement_contents = [
        (path.name, _read_source(root, path.name))
        for path in sorted(root.iterdir())
        if path.name.startswith("requirements") and path.name.endswith(".txt")
        and source_path_allowed(path.name) and not path.is_symlink() and path.is_file()
    ]
    entries["DEPENDENCIES.json"] = _json_bytes(_dependencies(requirement_contents))
    instructions = [
        "Inspecter ISSUE.json, DIAGNOSTICS.json et les fichiers source/ sélectionnés.",
        "Retourner un correctif au format unified diff avec chemins relatifs au projet, ou des fichiers UTF-8 complets accompagnés de leurs chemins relatifs.",
        "Limiter les modifications aux fichiers du périmètre explicite ; expliquer tout fichier supplémentaire nécessaire.",
        "Ne pas demander de clé API ni de donnée personnelle ; utiliser des fixtures fictives pour les tests.",
        "Ne pas produire de script de téléchargement ou d'exécution automatique ; indiquer les tests hors ligne pertinents.",
        "La réimportation se fera dans une copie isolée, avec aperçu et tests avant toute application au projet principal.",
    ]
    issue = {
        "schema_version": 1,
        "kind": "come_ai_technical_issue",
        "title": redact_text(title.strip(), root),
        "description": redact_text(description.strip(), root),
        "errors": redact_text(errors, root),
        "selected_files": [path for path, _ in contents],
        "source_manifest": manifest["files"],
        "target_assistants": ["ChatGPT Chat", "ChatGPT Work", "Gemini", "Codex"],
        "expected_response": "unified_diff_or_complete_utf8_files",
        "instructions": instructions,
    }
    markdown = ["# Demande de correction", "", issue["title"], "", "## Problème", "", issue["description"], "",
                "## Fichiers concernés", "", *["- `" + path + "`" for path in issue["selected_files"]], "",
                "## Erreurs fournies", "", issue["errors"] or "Aucune erreur fournie.", "",
                "## Résultat attendu", "", *["- " + item for item in instructions], ""]
    entries["ISSUE.json"] = _json_bytes(issue)
    entries["ISSUE.md"] = "\n".join(markdown).encode("utf-8")
    archive_path = _write_archive(destination, entries)
    return {"archive_path": str(archive_path), "file_count": manifest["file_count"],
            "total_bytes": manifest["total_source_bytes"], "manifest": manifest, "issue": issue}


__all__ = ["KitError", "source_path_allowed", "validate_source_text", "source_inventory", "source_fingerprint", "materialize_source",
           "redact_text", "export_snapshot", "build_issue_bundle"]
