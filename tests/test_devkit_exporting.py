"""Fictitious source exports: confidential files are never opened or packaged."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from devkit import exporting
from devkit.exporting import (
    KitError,
    build_issue_bundle,
    export_snapshot,
    materialize_source,
    source_fingerprint,
    source_inventory,
    source_path_allowed,
    validate_source_text,
)


def _project(root: Path) -> Path:
    root.mkdir()
    (root / "workspace_core.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    (root / "README_TEST.md").write_text("# Fictitious project\n", encoding="utf-8")
    (root / "requirements-test.txt").write_text("pytest>=8\nnonexistent-fictitious-package>=1\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_example.py").write_text("def test_example():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    return root


def test_snapshot_contains_source_manifest_and_versions_without_private_files(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    secret = "AIza" + "A" * 35
    for name in (".env", "agent.py", "agent_v2.py", "test_gemini.py"):
        (root / name).write_text(secret, encoding="utf-8")
    for directory in ("data", "output", "state", "memory_data", "career_data", "logs", ".venv"):
        folder = root / directory
        folder.mkdir()
        (folder / "private.py").write_text(secret, encoding="utf-8")
        (folder / "private.sqlite3").write_bytes(b"private")
    (root / "tests" / ".private.txt").write_text(secret, encoding="utf-8")
    (root / "tests" / "cv.pdf").write_bytes(b"private CV")
    report = {"status": "passed", "error": str(root / "workspace_core.py") + "\nAuthorization: Bearer " + "Z" * 32,
              "api_key": "very private", "profile": {"email": "private@example.test"}}
    result = export_snapshot(root, tmp_path / "snapshot.zip", diagnostic_report=report)

    with ZipFile(result["archive_path"]) as archive:
        names = archive.namelist()
        assert names == ["source/README_TEST.md", "source/pytest.ini", "source/requirements-test.txt",
                         "source/tests/test_example.py", "source/workspace_core.py", "MANIFEST.json",
                         "ARCHITECTURE.md", "DEPENDENCIES.json", "DIAGNOSTICS.json"]
        joined = b"".join(archive.read(name) for name in names).decode("utf-8")
        assert secret not in joined
        assert "private@example.test" not in joined
        assert "Z" * 32 not in joined
        assert str(root) not in joined
        inventory = json.loads(archive.read("MANIFEST.json"))["files"]
        assert inventory[0]["sha256"] == hashlib.sha256(archive.read("source/README_TEST.md")).hexdigest()
        dependencies = json.loads(archive.read("DEPENDENCIES.json"))
        assert dependencies["packages"] == [
            {"name": "nonexistent-fictitious-package", "installed_version": None},
            {"name": "pytest", "installed_version": dependencies["packages"][1]["installed_version"]},
        ]
        assert dependencies["packages"][1]["installed_version"] is not None
        assert "workspace_core.py" in archive.read("ARCHITECTURE.md").decode("utf-8")
    assert result["file_count"] == 5
    assert (root / ".env").read_text(encoding="utf-8") == secret


def test_source_snapshot_and_materialization_match_with_no_overwrite(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    original_inventory = source_inventory(root)
    candidate = tmp_path / "candidate"
    assert materialize_source(root, candidate) == original_inventory
    assert source_inventory(candidate) == original_inventory
    assert source_fingerprint(candidate) == source_fingerprint(root)
    (candidate / "workspace_core.py").write_text("return_value = 10\n", encoding="utf-8")
    assert source_fingerprint(candidate) != source_fingerprint(root)
    with pytest.raises(KitError, match="neuf"):
        materialize_source(root, candidate)
    destination = tmp_path / "snapshot.zip"
    export_snapshot(root, destination)
    original = destination.read_bytes()
    with pytest.raises(KitError, match="écrasement"):
        export_snapshot(root, destination)
    assert destination.read_bytes() == original


@pytest.mark.parametrize("path", ["../workspace_core.py", "/workspace_core.py", "tests/../.env",
                                  "tests//example.py", "tests/./example.py", "tests\\example.py",
                                  "C:/example.py", ".env", "agent.py", "unknown/example.py",
                                  "tests/data/profile.txt", "tests/private.pem", "tests/.keys/key.txt"])
def test_disallowed_paths_never_enter_issue_bundle(tmp_path: Path, path: str) -> None:
    root = _project(tmp_path / "project")
    assert not source_path_allowed(path)
    with pytest.raises(KitError):
        build_issue_bundle(root, tmp_path / "issue.zip", title="Test", description="Fixture", selected_files=[path])
    assert not (tmp_path / "issue.zip").exists()


def test_symlinks_are_skipped_in_inventory_and_refused_when_selected(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    outside = tmp_path / "outside.py"
    outside.write_text("private = True\n", encoding="utf-8")
    (root / "linked.py").symlink_to(outside)
    (root / "tests" / "linked").symlink_to(tmp_path, target_is_directory=True)
    assert all("linked" not in item["path"] for item in source_inventory(root))
    with pytest.raises(KitError, match="symboliques"):
        build_issue_bundle(root, tmp_path / "issue.zip", title="Test", description="Fixture", selected_files=["linked.py"])
    with pytest.raises(KitError, match="symboliques"):
        build_issue_bundle(root, tmp_path / "issue.zip", title="Test", description="Fixture", selected_files=["tests/linked/outside.py"])


@pytest.mark.parametrize("secret", ["AIza" + "A" * 35, "sk-or-v1-" + "f" * 50,
                                    "sk-" + "A" * 40, "Bearer " + "A" * 40,
                                    "api_key = '" + "B" * 40 + "'",
                                    "-----BEGIN " + "PRIVATE KEY-----",
                                    "https://" + "privateuser:privatepass@example.test/pkg"])
def test_secret_blocks_export_without_echoing_fragment(tmp_path: Path, secret: str) -> None:
    root = _project(tmp_path / "project")
    (root / "workspace_core.py").write_text(secret, encoding="utf-8")
    with pytest.raises(KitError) as caught:
        export_snapshot(root, tmp_path / "snapshot.zip")
    assert secret not in str(caught.value)
    assert "secret potentiel" in str(caught.value)
    assert not (tmp_path / "snapshot.zip").exists()


def test_source_size_count_and_aggregate_limits_fail_before_creating_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path / "project")
    monkeypatch.setattr(exporting, "MAX_FILES", 2)
    with pytest.raises(KitError, match="nombre"):
        export_snapshot(root, tmp_path / "too-many.zip")
    monkeypatch.setattr(exporting, "MAX_FILES", 1000)
    monkeypatch.setattr(exporting, "MAX_FILE_BYTES", 10)
    with pytest.raises(KitError, match="fichier source dépasse"):
        export_snapshot(root, tmp_path / "too-big.zip")
    monkeypatch.setattr(exporting, "MAX_FILE_BYTES", 1024)
    monkeypatch.setattr(exporting, "MAX_TOTAL_BYTES", 50)
    with pytest.raises(KitError, match="volume source total"):
        export_snapshot(root, tmp_path / "too-large.zip")
    assert not list(tmp_path.glob("*.zip"))


def test_issue_bundle_is_explicit_portable_and_redacts_errors(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    error = "Traceback at " + str(root / "workspace_core.py") + " and /Users/fictitious/private/cv.pdf\n" + "sk-or-v1-" + "f" * 50
    result = build_issue_bundle(root, tmp_path / "issue.zip", title="Wrong answer", description="Expected 43; got 42.",
                                errors=error, selected_files=["workspace_core.py"])
    with ZipFile(result["archive_path"]) as archive:
        issue = json.loads(archive.read("ISSUE.json"))
        assert issue["schema_version"] == 1
        assert issue["selected_files"] == ["workspace_core.py"]
        assert issue["target_assistants"] == ["ChatGPT Chat", "ChatGPT Work", "Gemini", "Codex"]
        assert issue["expected_response"] == "unified_diff_or_complete_utf8_files"
        assert str(root) not in issue["errors"]
        assert "/Users/fictitious" not in issue["errors"]
        assert "f" * 50 not in issue["errors"]
        assert "<projet>/workspace_core.py" in issue["errors"]
        assert b"unified diff" in archive.read("ISSUE.md")
        assert "source/tests/test_example.py" not in archive.namelist()
        dependencies = json.loads(archive.read("DEPENDENCIES.json"))
        assert any(package["name"] == "pytest" for package in dependencies["packages"])
        assert "non fourni" in archive.read("ARCHITECTURE.md").decode("utf-8")
        assert json.loads(archive.read("DIAGNOSTICS.json"))["status"] == "not_provided"
    with pytest.raises(KitError, match="explicite"):
        build_issue_bundle(root, tmp_path / "implicit.zip", title="Test", description="Fixture")


def test_binary_and_fifo_sources_are_rejected_without_blocking(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    (root / "binary.py").write_bytes(b"\xff\x00")
    with pytest.raises(KitError, match="UTF-8"):
        source_inventory(root)
    with pytest.raises(KitError, match="binaires"):
        validate_source_text("binary\x00data")
    if hasattr(os, "mkfifo"):
        os.mkfifo(root / "pipe.py")
        with pytest.raises(KitError, match="ordinaires"):
            build_issue_bundle(root, tmp_path / "fifo.zip", title="FIFO", description="Fixture", selected_files=["pipe.py"])
