"""Real sandbox validation of a synthetic correction, never user code/data."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from devkit.diagnostics import run_diagnostics
from devkit.patching import PatchWorkspace


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("sandbox-exec"), reason="Validation OS réservée au Mac avec sandbox-exec")
@pytest.mark.skipif(os.environ.get("COME_AI_DIAGNOSTICS_OFFLINE") == "1", reason="macOS refuse les sandbox imbriquées ; ce scénario est vérifié séparément hors du runner déjà isolé")
def test_real_sandbox_patch_validation_apply_and_rollback(tmp_path: Path) -> None:
    root = tmp_path / "fixture-project"
    root.mkdir()
    (root / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "tests").mkdir()
    sentinel = root / "private-sentinel.txt"
    sentinel.write_text("fixture-private", encoding="utf-8")
    test_source = (
        "import os, pathlib, socket\nfrom calculator import add\n"
        "def test_sum_and_isolation():\n"
        "    assert add(2, 3) == 5\n"
        "    assert not os.environ.get('GEMINI_API_KEY')\n"
        f"    sentinel = pathlib.Path({str(sentinel)!r})\n"
        "    try:\n        sentinel.read_text()\n"
        "    except PermissionError:\n        pass\n"
        "    else:\n        raise AssertionError('Original source is readable')\n"
        "    try:\n        socket.create_connection(('127.0.0.1', 9), timeout=0.1)\n"
        "    except (RuntimeError, PermissionError):\n        pass\n"
        "    else:\n        raise AssertionError('Network is enabled')\n"
    )
    (root / "tests" / "test_calculator.py").write_text(test_source, encoding="utf-8")
    workspace = PatchWorkspace(root, root / ".devkit")
    staged = workspace.stage_files({"calculator.py": "def add(a, b):\n    return a + b\n"})
    candidate = staged["candidate_id"]
    report = run_diagnostics(workspace.candidate_path(candidate), python_executable=Path(sys.executable),
                             report_dir=root / ".devkit" / "test-report", require_sandbox=True, timeout_seconds=60)
    assert report["status"] == "passed", report
    assert report["sandbox_used"] is True
    assert report["tests_executed"] == 1
    assert "return a - b" in (root / "calculator.py").read_text()
    workspace.mark_validation(candidate, report)
    applied = workspace.apply(candidate)
    assert "return a + b" in (root / "calculator.py").read_text()
    restored = PatchWorkspace(root, root / ".devkit")
    assert restored.list_transactions()[0]["transaction_id"] == applied["transaction_id"]
    restored.rollback(applied["transaction_id"])
    assert "return a - b" in (root / "calculator.py").read_text()
    assert sentinel.read_text() == "fixture-private"
