"""Tests des contrôles CI de gouvernance (SPEC-007)."""

from __future__ import annotations

from pathlib import Path

from career.ci_guards import (
    _AUTO_APPLY_PATTERNS,
    migrations_problems,
    no_auto_apply_problems,
    privacy_problems,
    provenance_problems,
)
from career.docx import docx_sha256


def test_repository_passes_privacy_check() -> None:
    assert privacy_problems() == []


def test_repository_passes_no_auto_apply_check() -> None:
    assert no_auto_apply_problems() == []


def test_repository_passes_provenance_check() -> None:
    assert provenance_problems() == []


def test_repository_passes_migrations_check() -> None:
    assert migrations_problems() == []


def test_privacy_check_detects_sensitive_files_and_secrets(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DEMO=1", encoding="utf-8")
    (tmp_path / "leak.py").write_text(
        "KEY = 'ghp_" + "A" * 24 + "'\n", encoding="utf-8"
    )
    problems = privacy_problems(tmp_path)
    assert any("fichier d'environnement" in problem for problem in problems)
    assert any("secret potentiel" in problem for problem in problems)


def test_no_auto_apply_patterns_cover_forbidden_actions() -> None:
    samples = [
        "import smtplib",
        'href = "mailto:recruiter@example.test"',
        "form.submit()",
        'payload = {"automatic_submission": True}',
    ]
    for sample in samples:
        assert any(pattern.search(sample) for _, pattern in _AUTO_APPLY_PATTERNS), sample


def test_docx_export_is_byte_for_byte_deterministic() -> None:
    assert docx_sha256() == docx_sha256()
