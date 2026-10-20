"""Offline tests for the fail-closed integration auditor."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.audit_integration import audit_candidate, report_payload, static_findings, write_report


def command(repo: Path, *args: str) -> str:
    result = subprocess.run(args, cwd=repo, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit_all(repo: Path, message: str) -> str:
    command(repo, "git", "add", ".")
    command(repo, "git", "commit", "-m", message)
    return command(repo, "git", "rev-parse", "HEAD")


def synthetic_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "synthetic-integration-repo"
    repo.mkdir()
    command(repo, "git", "init", "-b", "main")
    command(repo, "git", "config", "user.name", "Côme AI Synthetic Test")
    command(repo, "git", "config", "user.email", "synthetic@example.test")
    write(repo / "README.md", "# Synthetic repository\n")
    base = commit_all(repo, "synthetic base")
    return repo, base


def test_clean_candidate_is_authorized_after_real_dynamic_checks(tmp_path: Path) -> None:
    repo, base = synthetic_repo(tmp_path)
    command(repo, "git", "switch", "-c", "agent/clean")
    write(repo / "feature.py", '"""Synthetic candidate module."""\n\nANSWER = 42\n')
    write(repo / "test_sample.py", "from feature import ANSWER\n\n\ndef test_answer():\n    assert ANSWER == 42\n")
    commit_all(repo, "clean synthetic feature")
    command(repo, "git", "switch", "main")

    report = audit_candidate(
        repo,
        branch="agent/clean",
        base=base,
        allowed_paths=["feature.py", "test_sample.py"],
        python=sys.executable,
        pytest_args=("-q", "test_sample.py"),
        ruff_args=("feature.py", "test_sample.py"),
    )

    assert report.verdict == "MERGE AUTORISÉ"
    assert all(check.passed for check in report.checks)
    assert {"pytest", "ruff", "diff_check"} <= {check.name for check in report.checks}


def test_candidate_with_forbidden_code_is_refused_without_leaking_secret(tmp_path: Path) -> None:
    repo, base = synthetic_repo(tmp_path)
    command(repo, "git", "switch", "-c", "agent/unsafe")
    fake_secret = "s" + "k-syntheticSecretValue123456789"
    write(
        repo / "unsafe.py",
        'import requests\n\nDIALOG = "window.prompt("\nTOKEN = "' + fake_secret + '"\n',
    )
    commit_all(repo, "unsafe synthetic feature")
    command(repo, "git", "switch", "main")

    report = audit_candidate(
        repo,
        branch="agent/unsafe",
        base=base,
        allowed_paths=["unsafe.py"],
        python=sys.executable,
    )

    assert report.verdict == "MERGE REFUSÉ"
    assert {"network_call", "window_prompt", "secret_openai"} <= {item.rule for item in report.findings}
    serialized = json.dumps(report_payload(report), ensure_ascii=False)
    assert fake_secret not in serialized
    assert any(check.name == "candidate_validation" and not check.passed for check in report.checks)


def test_shared_file_requires_a_separate_explicit_permission(tmp_path: Path) -> None:
    repo, base = synthetic_repo(tmp_path)
    command(repo, "git", "switch", "-c", "agent/shared")
    write(repo / "career" / "service.py", '"""Synthetic shared file."""\n')
    commit_all(repo, "touch shared file")
    command(repo, "git", "switch", "main")

    refused = audit_candidate(repo, branch="agent/shared", base=base, allowed_paths=["career"])
    assert refused.verdict == "MERGE REFUSÉ"
    assert any(check.name == "shared_files" and not check.passed for check in refused.checks)


def test_real_named_fixture_must_be_explicitly_synthetic(tmp_path: Path) -> None:
    repo, base = synthetic_repo(tmp_path)
    command(repo, "git", "switch", "-c", "agent/real-fixture")
    write(repo / "tests" / "PROFILE_REAL.json", '{"name": "Jean Dupont"}\n')
    commit_all(repo, "unlabelled real fixture")
    command(repo, "git", "switch", "main")

    report = audit_candidate(repo, branch="agent/real-fixture", base=base, allowed_paths=["tests"])
    assert report.verdict == "MERGE REFUSÉ"
    assert "real_fixture_unlabelled" in {item.rule for item in report.findings}


def test_json_report_is_written_without_source_lines(tmp_path: Path) -> None:
    repo, base = synthetic_repo(tmp_path)
    command(repo, "git", "switch", "-c", "agent/report")
    fake_google_secret = "AI" + "zaSyntheticCredentialValue000000"
    write(repo / "bad.py", f'TOKEN = "{fake_google_secret}"\n')
    commit_all(repo, "synthetic blocked report")
    command(repo, "git", "switch", "main")
    report = audit_candidate(repo, branch="agent/report", base=base, allowed_paths=["bad.py"])
    output = tmp_path / "audit.json"

    write_report(report, output)
    payload = output.read_text(encoding="utf-8")
    assert report.verdict == "MERGE REFUSÉ"
    assert "secret_google" in payload
    assert fake_google_secret not in payload


def test_guard_tests_may_name_forbidden_behaviour_without_adding_it_to_production() -> None:
    findings = static_findings(
        [
            ("tests/test_ui_guard.py", 10, 'assert "window.prompt" not in source'),
            ("tests/test_schema_guard.py", 11, 'assert "SCHEMA_VERSION = 7" in source'),
        ],
        network_allowed_paths=[],
    )
    assert findings == []
