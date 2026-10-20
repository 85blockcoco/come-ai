#!/usr/bin/env python3
"""Audit a candidate branch before a supervised Côme AI integration.

The audit is deliberately fail-closed.  It never merges or pushes.  A candidate
is checked from a temporary detached worktree, then removed in a ``finally``
block.  Detected sensitive lines are never copied to the JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence


DEFAULT_BASE = "e3c77f4a81b0e3c48a86d27b08f48ed539c1d26d"
SHARED_FILES = frozenset({"career/service.py", "career_static/career.js"})
SAFE_AUXILIARY_PREFIXES = ("tests/", "docs/agent-reports/")

FORBIDDEN_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("schema_version", re.compile(r"\bSCHEMA" + r"_VERSION\b")),
    ("window_prompt", re.compile(r"\bwindow\.prompt\s*\(")),
    ("secret_openai", re.compile(r"\bs" + r"k-[A-Za-z0-9_-]{12,}")),
    ("secret_google", re.compile(r"\bAI" + r"za[0-9A-Za-z_-]{20,}")),
    ("private_key", re.compile(r"BEGIN " + r"(?:RSA |EC |OPENSSH )?" + r"PRIVATE KEY")),
    ("automatic_submission", re.compile(r"automated" + r"_submission\s*[:=]\s*(?:True|true|1)")),
    (
        "email_send",
        re.compile(r"\b(?:smtp" + r"lib|SM" + r"TP|send" + r"mail|send_" + r"message)\b"),
    ),
)
PRODUCTION_ONLY_RULES = frozenset({"schema_version", "window_prompt", "automatic_submission", "email_send"})
NETWORK_RULE = re.compile(
    r"(?:\bimport\s+(?:requests|httpx|urllib|socket)\b|"
    r"\bfrom\s+(?:requests|httpx|urllib|socket)\b|"
    r"\b(?:requests|httpx|urllib\.request)\.(?:get|post|put|delete|request)\s*\(|"
    r"\bsocket\.socket\s*\()"
)
PERSONAL_DATA_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:test|com)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone", re.compile(r"(?<!\d)(?:\+33|0)[1-9](?:[ .-]?\d{2}){4}(?!\d)")),
)


@dataclass(slots=True)
class Check:
    name: str
    passed: bool
    detail: str
    command: list[str] | None = None
    exit_code: int | None = None
    output_tail: str = ""


@dataclass(slots=True)
class Finding:
    rule: str
    path: str
    added_line: int | None
    detail: str


@dataclass(slots=True)
class AuditReport:
    branch: str
    base: str
    head: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    allowed_paths: list[str] = field(default_factory=list)
    allowed_shared_paths: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    verdict: str = "MERGE REFUSÉ"
    reasons: list[str] = field(default_factory=list)


class AuditError(RuntimeError):
    """A safe, user-facing audit failure."""


def run(command: Sequence[str], *, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def git(repo: Path, *arguments: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return run(["git", *arguments], cwd=repo, timeout=timeout)


def require_git(repo: Path, *arguments: str) -> str:
    result = git(repo, *arguments)
    if result.returncode:
        raise AuditError(result.stderr.strip() or result.stdout.strip() or "Commande Git en échec.")
    return result.stdout.strip()


def normalize_prefix(value: str) -> str:
    cleaned = value.strip().replace("\\", "/").lstrip("./")
    if not cleaned or cleaned.startswith("../") or "/../" in f"/{cleaned}/":
        raise AuditError(f"Périmètre invalide : {value!r}")
    return cleaned.rstrip("/")


def within(path: str, prefixes: Sequence[str]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def changed_files(repo: Path, base: str, branch: str) -> list[str]:
    output = require_git(repo, "diff", "--name-only", "--diff-filter=ACMRT", f"{base}...{branch}", "--")
    return sorted(line for line in output.splitlines() if line)


def added_lines(repo: Path, base: str, branch: str) -> list[tuple[str, int | None, str]]:
    diff = require_git(repo, "diff", "--no-ext-diff", "--unified=0", f"{base}...{branch}", "--")
    current_path = ""
    new_line: int | None = None
    result: list[tuple[str, int | None, str]] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            new_line = int(match.group(1)) if match else None
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.append((current_path, new_line, line[1:]))
            if new_line is not None:
                new_line += 1
        elif not line.startswith("-") and new_line is not None:
            new_line += 1
    return result


def static_findings(
    lines: Sequence[tuple[str, int | None, str]], *, network_allowed_paths: Sequence[str]
) -> list[Finding]:
    findings: list[Finding] = []
    real_file_contents: dict[str, list[str]] = {}
    route_changed = False
    testclient_added = False
    for path, line_number, text in lines:
        if "_REAL" in Path(path).name.upper():
            real_file_contents.setdefault(path, []).append(text)
        if path.startswith("career/") and ("router" in Path(path).stem or "@router." in text):
            route_changed = True
        if path.startswith("tests/") and "TestClient" in text:
            testclient_added = True
        for rule, pattern in FORBIDDEN_RULES:
            if rule in PRODUCTION_ONLY_RULES and path.startswith(("tests/", "docs/")):
                continue
            if pattern.search(text):
                findings.append(Finding(rule, path, line_number, "Motif interdit détecté dans une ligne ajoutée."))
        if (
            not path.startswith(("tests/", "docs/"))
            and not within(path, network_allowed_paths)
            and NETWORK_RULE.search(text)
        ):
            findings.append(Finding("network_call", path, line_number, "Appel réseau ajouté hors périmètre explicitement autorisé."))
        if path.startswith(("tests/", "evals/")):
            for rule, pattern in PERSONAL_DATA_RULES:
                if pattern.search(text):
                    findings.append(Finding(f"personal_data_{rule}", path, line_number, "Donnée ressemblant à une donnée personnelle dans une fixture."))
    for path, content_lines in real_file_contents.items():
        content = "\n".join(content_lines).casefold()
        if "synthetic" not in content and "synthétique" not in content:
            findings.append(Finding("real_fixture_unlabelled", path, None, "Fichier *_REAL* non marqué comme synthétique."))
    if route_changed and not testclient_added:
        findings.append(Finding("route_without_testclient", "career/", None, "Route modifiée sans test TestClient ajouté dans le lot."))
    return findings


def command_check(name: str, command: list[str], *, cwd: Path, timeout: int) -> Check:
    try:
        result = run(command, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Check(name, False, f"Délai dépassé après {timeout} s.", command=command)
    combined = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    tail = "\n".join(combined.splitlines()[-30:])
    return Check(name, result.returncode == 0, "Commande réussie." if result.returncode == 0 else "Commande en échec.", command, result.returncode, tail)


def validate_in_temporary_worktree(
    repo: Path,
    branch: str,
    *,
    python: str,
    pytest_args: Sequence[str],
    ruff_args: Sequence[str],
) -> list[Check]:
    temporary_parent = Path(tempfile.mkdtemp(prefix="come-ai-integration-audit-"))
    checkout = temporary_parent / "candidate"
    checks: list[Check] = []
    added = False
    try:
        add = git(repo, "worktree", "add", "--detach", str(checkout), branch, timeout=180)
        checks.append(Check("temporary_worktree", add.returncode == 0, "Worktree jetable créé." if add.returncode == 0 else "Création du worktree jetable impossible.", ["git", "worktree", "add", "--detach", "<temp>", branch], add.returncode, "\n".join((add.stdout + add.stderr).splitlines()[-10:])))
        if add.returncode:
            return checks
        added = True
        checks.append(command_check("pytest", [python, "-m", "pytest", *pytest_args], cwd=checkout, timeout=900))
        checks.append(command_check("ruff", [python, "-m", "ruff", "check", *ruff_args], cwd=checkout, timeout=300))
        checks.append(command_check("diff_check", ["git", "diff", "--check"], cwd=checkout, timeout=120))
        return checks
    finally:
        if added:
            git(repo, "worktree", "remove", "--force", str(checkout), timeout=180)
        shutil.rmtree(temporary_parent, ignore_errors=True)


def audit_candidate(
    repo: Path,
    *,
    branch: str,
    base: str,
    allowed_paths: Sequence[str],
    allowed_shared_paths: Sequence[str] = (),
    network_allowed_paths: Sequence[str] = (),
    python: str = sys.executable,
    pytest_args: Sequence[str] = ("-q",),
    ruff_args: Sequence[str] = (".",),
) -> AuditReport:
    repo = Path(require_git(repo, "rev-parse", "--show-toplevel"))
    report = AuditReport(branch=branch, base=base)
    require_git(repo, "check-ref-format", "--branch", branch)
    report.head = require_git(repo, "rev-parse", f"{branch}^{{commit}}")
    base_sha = require_git(repo, "rev-parse", f"{base}^{{commit}}")
    report.base = base_sha
    ancestry = git(repo, "merge-base", "--is-ancestor", base_sha, report.head)
    report.checks.append(Check("base_is_ancestor", ancestry.returncode == 0, "La branche descend de la base." if ancestry.returncode == 0 else "La branche ne descend pas de la base annoncée."))

    normalized_allowed = [normalize_prefix(item) for item in allowed_paths]
    normalized_shared = [normalize_prefix(item) for item in allowed_shared_paths]
    normalized_network = [normalize_prefix(item) for item in network_allowed_paths]
    report.allowed_paths = normalized_allowed
    report.allowed_shared_paths = normalized_shared
    report.changed_files = changed_files(repo, base_sha, branch)

    out_of_scope = [
        path for path in report.changed_files
        if not within(path, normalized_allowed) and not path.startswith(SAFE_AUXILIARY_PREFIXES)
    ]
    report.checks.append(Check("declared_scope", not out_of_scope and bool(normalized_allowed), "Tous les fichiers sont dans le périmètre déclaré." if not out_of_scope and normalized_allowed else "Périmètre absent ou fichiers hors périmètre : " + ", ".join(out_of_scope or ["aucun --allow-path"])))

    shared_without_permission = [
        path for path in report.changed_files if path in SHARED_FILES and path not in normalized_shared
    ]
    report.checks.append(Check("shared_files", not shared_without_permission, "Aucun fichier partagé sensible non autorisé." if not shared_without_permission else "Fichier partagé sans autorisation explicite : " + ", ".join(shared_without_permission)))

    lines = added_lines(repo, base_sha, branch)
    report.findings.extend(static_findings(lines, network_allowed_paths=normalized_network))
    report.checks.append(Check("forbidden_patterns", not report.findings, "Aucun motif interdit détecté." if not report.findings else f"{len(report.findings)} constat(s) bloquant(s)."))

    static_green = all(check.passed for check in report.checks)
    if static_green:
        report.checks.extend(
            validate_in_temporary_worktree(
                repo,
                branch,
                python=python,
                pytest_args=pytest_args,
                ruff_args=ruff_args,
            )
        )
    else:
        report.checks.append(Check("candidate_validation", False, "Validation dynamique non exécutée car un contrôle statique bloque le lot."))

    failed = [check.name for check in report.checks if not check.passed]
    if failed:
        report.verdict = "MERGE REFUSÉ"
        report.reasons = [f"Contrôle en échec : {name}" for name in failed]
    else:
        report.verdict = "MERGE AUTORISÉ"
        report.reasons = ["Tous les contrôles configurés ont réussi."]
    return report


def report_payload(report: AuditReport) -> dict[str, object]:
    return asdict(report)


def safe_report_name(branch: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", branch).strip("-") or "candidate"


def write_report(report: AuditReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report_payload(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_report(report: AuditReport, output: Path) -> None:
    print(f"Branche : {report.branch}")
    print(f"Base : {report.base}")
    print(f"HEAD : {report.head}")
    print(f"Fichiers modifiés : {len(report.changed_files)}")
    for check in report.checks:
        print(f"[{'OK' if check.passed else 'REFUS'}] {check.name} — {check.detail}")
    for finding in report.findings:
        location = f"{finding.path}:{finding.added_line}" if finding.added_line else finding.path
        print(f"[BLOQUANT] {finding.rule} — {location} — {finding.detail}")
    print(f"VERDICT : {report.verdict}")
    print(f"Journal JSON : {output}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auditer une branche candidate Côme AI sans la fusionner.")
    parser.add_argument("--branch", required=True, help="Branche candidate à auditer.")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Commit de base attendu.")
    parser.add_argument("--allow-path", action="append", default=[], help="Préfixe de fichier autorisé, répétable.")
    parser.add_argument("--allow-shared-path", action="append", default=[], help="Autorisation explicite pour career/service.py ou career_static/career.js.")
    parser.add_argument("--allow-network-path", action="append", default=[], help="Préfixe où le réseau est explicitement admis, par exemple un connecteur revu.")
    parser.add_argument("--pytest-arg", action="append", default=[], help="Argument pytest supplémentaire, répétable.")
    parser.add_argument("--ruff-arg", action="append", default=[], help="Cible ruff supplémentaire, répétable.")
    parser.add_argument("--output", type=Path, help="Chemin du journal JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo = Path.cwd()
    output = args.output or repo / ".devkit" / "integration-audits" / f"{safe_report_name(args.branch)}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    try:
        report = audit_candidate(
            repo,
            branch=args.branch,
            base=args.base,
            allowed_paths=args.allow_path,
            allowed_shared_paths=args.allow_shared_path,
            network_allowed_paths=args.allow_network_path,
            python=sys.executable,
            pytest_args=("-q", *args.pytest_arg),
            ruff_args=tuple(args.ruff_arg or ["."]),
        )
    except (AuditError, subprocess.TimeoutExpired) as error:
        report = AuditReport(branch=args.branch, base=args.base)
        report.checks.append(Check("audit_execution", False, str(error)))
        report.reasons = [str(error)]
    write_report(report, output)
    print_report(report, output)
    return 0 if report.verdict == "MERGE AUTORISÉ" else 2


if __name__ == "__main__":
    raise SystemExit(main())
