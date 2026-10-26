"""Contrôles CI déterministes de gouvernance (SPEC-007).

Ces contrôles sont volontairement statiques et hors ligne : ils s'exécutent
en quelques millisecondes dans la CI et ne dépendent ni du réseau, ni d'une
base de données, ni d'un service externe. Ils sont appelés par les jobs
``privacy-check``, ``no-auto-apply``, ``provenance-check`` et
``migrations-check`` de ``.github/workflows/ci.yml``.

Chaque fonction retourne une liste de problèmes lisibles (vide = OK).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Motifs de secrets à haute confiance. Les détecteurs, les tests et les
# preuves d'audit citent volontairement des clés factices : ils sont exclus.
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}"
    r"|xoxb-[A-Za-z0-9-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
_SECRET_ALLOWLIST = re.compile(
    r"^(devkit/credentials\.py|secret_redaction\.py|scripts/audit_integration\.py"
    r"|tests/|docs/audit_v2/|career/ci_guards\.py|career/privacy\.py)"
)
_SENSITIVE_SUFFIXES = (".db", ".sqlite", ".sqlite2", ".sqlite3", ".pem", ".key")
_MAX_SCANNED_BYTES = 2_000_000


def tracked_files(root: Path = ROOT) -> list[str]:
    """Fichiers suivis par git (repli sur un parcours disque hors dépôt)."""
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        return [item for item in output.decode("utf-8", "replace").split("\0") if item]
    except (OSError, subprocess.SubprocessError):
        ignored = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
        return [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not ignored.intersection(path.parts)
        ]


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_SCANNED_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


# --- privacy -----------------------------------------------------------------


def privacy_problems(root: Path = ROOT) -> list[str]:
    """Aucun fichier sensible ni secret réel dans les fichiers suivis."""
    problems: list[str] = []
    for relative in tracked_files(root):
        name = Path(relative).name
        if name == ".env":
            problems.append(f"fichier d'environnement suivi : {relative}")
        if name.endswith(_SENSITIVE_SUFFIXES):
            problems.append(f"base ou clé privée suivie : {relative}")
        if _SECRET_ALLOWLIST.search(relative):
            continue
        text = _read_text(root / relative)
        match = _SECRET_PATTERN.search(text)
        if match:
            problems.append(f"secret potentiel dans {relative} ({match.group(0)[:12]}…)")
    return problems


# --- no-auto-apply -----------------------------------------------------------

_AUTO_APPLY_FILES = (
    "career/service.py",
    "career/application_dashboard.py",
    "career/application_prep.py",
    "career/application_sprint.py",
    "career/application_studio.py",
    "career/document_export.py",
    "career/router.py",
)
_AUTO_APPLY_PATTERNS = (
    ("envoi SMTP", re.compile(r"\bsmtplib\b")),
    ("client de messagerie", re.compile(r"mailto:", re.IGNORECASE)),
    ("soumission de formulaire", re.compile(r"\.submit\s*\(\s*\)")),
    ("navigation automatique", re.compile(r"webbrowser\.open")),
    ("envoi HTTP direct", re.compile(r"\b(?:requests|httpx)\.post\s*\(")),
    ("soumission déclarée vraie", re.compile(r"automatic_submission[\"']?\s*[:=]\s*True")),
)


def no_auto_apply_problems(root: Path = ROOT) -> list[str]:
    """Le parcours candidature ne peut rien envoyer, poster ni téléverser.

    La règle ne vise que les modules du parcours de candidature : les
    connecteurs d'offres ont le droit de faire des requêtes de lecture.
    """
    problems: list[str] = []
    for relative in _AUTO_APPLY_FILES:
        path = root / relative
        if not path.is_file():
            problems.append(f"module attendu absent : {relative}")
            continue
        text = _read_text(path)
        for label, pattern in _AUTO_APPLY_PATTERNS:
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                problems.append(f"{relative}:{line} — {label}")
    return problems


# --- provenance --------------------------------------------------------------

_PROVENANCE_CONTRACTS = (
    ("career/application_studio.py", "provenance_map"),
    ("career/application_studio.py", "provenance_lines"),
    ("career/service.py", '"provenance_map": generated.provenance_map'),
    ("career/service.py", '"automatic_submission": False'),
)


def provenance_problems(root: Path = ROOT) -> list[str]:
    """Chaque kit expose la carte de provenance de ses affirmations."""
    problems: list[str] = []
    for relative, needle in _PROVENANCE_CONTRACTS:
        text = _read_text(root / relative)
        if needle not in text:
            problems.append(f"contrat de provenance absent de {relative} : {needle}")
    return problems


# --- migrations --------------------------------------------------------------

_MIGRATION_CONTRACTS = (
    ("career/service.py", "schema_version INTEGER NOT NULL"),
    ("career/qualification_persistence.py", "SNAPSHOT_SCHEMA_VERSION = "),
    ("career/service.py", ":schema_version"),
    ("career/service.py", "qualification_schema_version"),
)


def migrations_problems(root: Path = ROOT) -> list[str]:
    """Le schéma de snapshot est versionné et décodable de façon défensive."""
    from career.qualification_persistence import (
        SNAPSHOT_SCHEMA_VERSION,
        decode_qualification_snapshot,
        normalize_qualification_snapshot,
    )

    problems: list[str] = []
    if not isinstance(SNAPSHOT_SCHEMA_VERSION, int) or SNAPSHOT_SCHEMA_VERSION < 1:
        problems.append("SNAPSHOT_SCHEMA_VERSION doit être un entier >= 1")
    for relative, needle in _MIGRATION_CONTRACTS:
        if needle not in _read_text(root / relative):
            problems.append(f"contrat de migration absent de {relative} : {needle}")

    # Un snapshot courant doit se décoder, et un snapshot d'ancienne version
    # sans colonnes doit être ignoré proprement plutôt que planter.
    current = normalize_qualification_snapshot(
        {"qualification": {"status": "conforming", "facts": {}, "provenance": {}}, "source": {}},
        {"source_name": "demo", "source_id": "demo-1", "official_url": "https://example.test/1"},
    )
    if current.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        problems.append("le snapshot normalisé ne porte pas le schéma courant")
    if decode_qualification_snapshot({}) != {}:
        problems.append("un snapshot absent doit se décoder en dictionnaire vide")
    return problems


def report(name: str, problems: list[str]) -> int:
    if problems:
        print(f"{name} : {len(problems)} problème(s)")
        for problem in problems:
            print(f" - {problem}")
        return 1
    print(f"{name} : OK")
    return 0
