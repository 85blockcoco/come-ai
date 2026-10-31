"""Synthetic diagnostics tests: no provider, private data, or real project tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from devkit import diagnostics
from devkit.diagnostics import CommandResult, run_diagnostics
from devkit.exporting import source_fingerprint


@pytest.mark.parametrize("folders", [("tests",), ("evals/tests",), ("tests", "evals/tests")])
def test_real_bootstrap_collects_application_and_evaluation_tests(tmp_path: Path, folders) -> None:
    root = tmp_path / "synthetic-bootstrap"
    root.mkdir()
    for index, folder in enumerate(folders):
        directory = root / folder
        directory.mkdir(parents=True)
        (directory / f"test_fixture_{index}.py").write_text(
            f"def test_fixture_{index}():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    bootstrap = root / "bootstrap.py"
    bootstrap.write_text(diagnostics._BOOTSTRAP, encoding="utf-8")
    receipt = root / "receipt.json"
    result = subprocess.run([sys.executable, str(bootstrap), "pytest", str(receipt)],
                            cwd=root, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
                                           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    counts = json.loads(receipt.read_text(encoding="utf-8"))
    assert counts["completed"] is True
    assert counts["tests_collected"] == counts["tests_passed"] == len(folders)
    assert counts["tests_failed"] == 0


def test_real_bootstrap_runs_only_the_selected_test_file(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-targeted"
    (root / "tests").mkdir(parents=True)
    (root / "tests/test_selected.py").write_text("def test_selected():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    (root / "tests/test_unselected.py").write_text("raise AssertionError('must not be collected')\n", encoding="utf-8")
    bootstrap = root / "bootstrap.py"
    bootstrap.write_text(diagnostics._BOOTSTRAP, encoding="utf-8")
    receipt = root / "receipt.json"
    result = subprocess.run(
        [sys.executable, str(bootstrap), "pytest", str(receipt), json.dumps(["tests/test_selected.py"])],
        cwd=root, env={"PATH": "/usr/bin:/bin", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    counts = json.loads(receipt.read_text(encoding="utf-8"))
    assert counts["tests_collected"] == counts["tests_passed"] == 1


@pytest.mark.parametrize("selection", [[], ["tests/test_example.py"] * 9, ["../test_example.py"],
                                      ["--collect-only.py"], ["tests/test_example.py::test_example"],
                                      ["core.py"], ["tests/../core.py"], ["/tmp/test_example.py"],
                                      ["tests/missing.py"]])
def test_targeted_test_paths_are_validated_before_execution(tmp_path: Path, selection) -> None:
    root, python = project(tmp_path)
    runner = FakeRunner()
    with pytest.raises(ValueError):
        run_diagnostics(root, python_executable=python, runner=runner, targeted_tests=selection)
    assert runner.calls == []


def test_targeted_tests_refuse_symlinked_parent(tmp_path: Path) -> None:
    root, python = project(tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "test_external.py").write_text("raise AssertionError('private')\n", encoding="utf-8")
    (root / "tests/linked").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="liens symboliques"):
        run_diagnostics(root, python_executable=python, targeted_tests=["tests/linked/test_external.py"])


def test_targeted_scope_is_recorded_and_passed_to_the_isolated_runner(tmp_path: Path, monkeypatch) -> None:
    root, python = project(tmp_path)
    sandbox_present(monkeypatch)
    runner = FakeRunner()
    report = run_diagnostics(root, python_executable=python, require_sandbox=True, runner=runner,
                             targeted_tests=["tests/test_example.py"])
    assert report["status"] == "passed"
    assert report["sandbox_used"] is True
    assert report["targeted_tests"] == ["tests/test_example.py"]
    command = next(call["command"] for call in runner.calls if "pytest" in call["command"])
    assert json.loads(command[-1]) == ["tests/test_example.py"]


def project(tmp_path: Path, *, tests: bool = True) -> tuple[Path, Path]:
    root = tmp_path / "fictional-project"
    root.mkdir()
    (root / "example.py").write_text("VALUE = 42\n", encoding="utf-8")
    (root / ".env").write_text("GEMINI_API_KEY=never-read-fixture\n", encoding="utf-8")
    (root / "private.sqlite3").write_bytes(b"private fixture")
    if tests:
        (root / "tests").mkdir()
        (root / "tests/test_example.py").write_text("def test_example():\n    assert True\n", encoding="utf-8")
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("fake executable for injected runner only\n", encoding="utf-8")
    return root, python


class FakeRunner:
    def __init__(self, *, fail: str | None = None, timeout: str | None = None, probe_passes: bool = True):
        self.calls: list[dict] = []
        self.fail = fail
        self.timeout = timeout
        self.probe_passes = probe_passes

    def __call__(self, command: list[str], *, cwd: Path, env: dict[str, str], timeout_seconds: float) -> CommandResult:
        self.calls.append({"command": command, "cwd": cwd, "env": env, "timeout": timeout_seconds})
        assert not (cwd / ".env").exists()
        assert not (cwd / "private.sqlite3").exists()
        if "-c" in command:
            return CommandResult(0 if self.probe_passes else 1, "sandbox-ready")
        action = command[command.index(next(part for part in command if part.endswith("diagnostics_bootstrap.py"))) + 1]
        if action == self.timeout:
            return CommandResult(-9, "fictitious timeout", timed_out=True)
        if action == self.fail:
            if action == "pytest":
                self.write_receipt(command, passed=2, failed=1, skipped=0, exitstatus=1)
            return CommandResult(1, "1 failed, 2 passed in 0.2s" if action == "pytest" else "fictitious failure")
        if action == "metadata":
            return CommandResult(0, '{"python":"3.12.10","platform":"darwin","packages":[{"name":"pytest","version":"9.0"}]}')
        if action == "pytest":
            self.write_receipt(command, passed=3, failed=0, skipped=1, exitstatus=0)
            return CommandResult(0, "3 passed, 1 skipped in 0.2s")
        return CommandResult(0, "OK")

    @staticmethod
    def write_receipt(command: list[str], *, passed: int, failed: int, skipped: int, exitstatus: int) -> None:
        receipt_path = Path(command[command.index("pytest") + 1])
        receipt_path.write_text(json.dumps({
            "schema_version": 1,
            "completed": True,
            "exitstatus": exitstatus,
            "tests_executed": passed + failed,
            "tests_passed": passed,
            "tests_failed": failed,
            "tests_skipped": skipped,
            "tests_collected": passed + failed + skipped,
            "collection_errors": 0,
        }), encoding="utf-8")


def sandbox_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None)


def test_filtered_copy_minimal_environment_report_and_actual_test_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    original = (root / "example.py").read_bytes()
    monkeypatch.setenv("GEMINI_API_KEY", "fictitious-secret-from-parent")
    monkeypatch.setenv("PYTHONPATH", "/private/fictitious-outside-path")
    monkeypatch.setenv("HTTPS_PROXY", "http://fictitious.invalid")
    sandbox_present(monkeypatch)
    runner = FakeRunner()
    reports = tmp_path / "reports"
    report = run_diagnostics(root, report_dir=reports, python_executable=python, require_sandbox=True, runner=runner)

    assert report["status"] == "passed"
    assert report["schema_version"] == 1
    assert report["sandbox_used"] is True
    assert report["source_fingerprint"] == source_fingerprint(root)
    assert report["tests_executed"] == 3
    assert report["tests_passed"] == 3
    assert report["tests_skipped"] == 1
    assert report["pytest_receipt_verified"] is True
    assert report["dependencies"]["packages"] == [{"name": "pytest", "version": "9.0"}]
    assert next(item for item in report["checks"] if item["name"] == "pytest")["status"] == "passed"
    assert next(item for item in report["checks"] if item["name"] == "offline_smoke")["status"] == "skipped"
    assert json.loads((reports / "latest.json").read_text()) == report
    assert len(list(reports.glob("*.json"))) == 2
    assert len(list(reports.glob("*.md"))) == 2
    assert (root / "example.py").read_bytes() == original
    assert not (root / "__pycache__").exists()
    for call in runner.calls:
        assert call["cwd"] != root
        assert call["env"]["HOME"] != str(Path.home())
        assert all(name not in call["env"] for name in ("GEMINI_API_KEY", "PYTHONPATH", "HTTPS_PROXY"))
        assert call["timeout"] > 0
        assert "(deny network*)" in call["command"][2]
    assert "fictitious-secret-from-parent" not in json.dumps(report)


def test_failure_summary_cannot_be_reported_as_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    sandbox_present(monkeypatch)
    report = run_diagnostics(root, python_executable=python, runner=FakeRunner(fail="pytest"))
    assert report["status"] == "failed"
    assert report["tests_executed"] == 3
    assert report["tests_failed"] == 1
    assert report["pytest_receipt_verified"] is True
    assert next(item for item in report["checks"] if item["name"] == "pytest")["returncode"] == 1


def test_command_timeout_is_failed_and_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    sandbox_present(monkeypatch)
    report = run_diagnostics(root, python_executable=python, runner=FakeRunner(timeout="pytest"), timeout_seconds=5)
    assert report["status"] == "failed"
    check = next(item for item in report["checks"] if item["name"] == "pytest")
    assert check["status"] == "failed"
    assert check["returncode"] == -9
    assert report["tests_executed"] == 0
    assert report["pytest_receipt_verified"] is False


def test_candidate_is_blocked_without_os_sandbox_and_no_code_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    runner = FakeRunner()
    report = run_diagnostics(root, python_executable=python, require_sandbox=True, runner=runner)
    assert report["status"] == "blocked"
    assert report["sandbox_used"] is False
    assert report["tests_executed"] == 0
    assert runner.calls == []
    assert report["checks"][0]["name"] == "sandbox"


def test_sandbox_presence_does_not_prove_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    sandbox_present(monkeypatch)
    runner = FakeRunner(probe_passes=False)
    report = run_diagnostics(root, python_executable=python, require_sandbox=True, runner=runner)
    assert report["status"] == "blocked"
    assert report["sandbox_used"] is False
    assert len(runner.calls) == 1  # Only the trusted sandbox probe executes.


def test_trusted_diagnostics_fallback_is_explicit_and_missing_tests_are_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path, tests=False)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    report = run_diagnostics(root, python_executable=python, runner=FakeRunner())
    assert report["status"] == "passed"
    assert report["sandbox_used"] is False
    assert report["tests_executed"] == 0
    assert next(item for item in report["checks"] if item["name"] == "pytest")["status"] == "skipped"
    assert "sources de confiance" in report["isolation_notice"]


def test_report_redacts_credentials_and_personal_paths_and_bounds_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    safe_runner = FakeRunner()

    def sensitive_runner(command: list[str], **kwargs: object) -> CommandResult:
        result = safe_runner(command, **kwargs)
        if "pip_check" in command:
            return CommandResult(1, f"GEMINI_API_KEY=fictitious-secret Bearer fictitious-token {root}/private.txt\n" + "x" * 100_000)
        return result

    report = run_diagnostics(root, python_executable=python, runner=sensitive_runner)
    output = next(item for item in report["checks"] if item["name"] == "pip_check")["output"]
    assert "fictitious-secret" not in output
    assert "fictitious-token" not in output
    assert str(root) not in output
    assert "[masqué]" in output
    assert len(output.encode()) < diagnostics.MAX_OUTPUT_BYTES + 100
    assert "[sortie tronquée]" in output


def test_changed_sources_invalidate_otherwise_successful_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    safe_runner = FakeRunner()

    def changing_runner(command: list[str], **kwargs: object) -> CommandResult:
        result = safe_runner(command, **kwargs)
        if "pytest" in command:
            (root / "example.py").write_text("VALUE = 43\n", encoding="utf-8")
        return result

    report = run_diagnostics(root, python_executable=python, runner=changing_runner)
    assert report["tests_executed"] == 3
    assert report["status"] == "blocked"
    assert report["source_fingerprint"] != source_fingerprint(root)
    assert next(item for item in report["checks"] if item["name"] == "source_consistency")["status"] == "blocked"


def test_forged_pass_stdout_and_early_exit_cannot_validate_zero_tests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    safe_runner = FakeRunner()

    def early_exit_runner(command: list[str], **kwargs: object) -> CommandResult:
        if "pytest" in command:
            # Equivalent to a conftest printing a success line then os._exit(0):
            # bootstrap never returns from pytest.main, and cannot create receipt.
            return CommandResult(0, "1 passed in 0.01s\n")
        return safe_runner(command, **kwargs)

    report = run_diagnostics(root, python_executable=python, runner=early_exit_runner)
    assert report["status"] == "failed"
    assert report["tests_executed"] == 0
    assert report["tests_passed"] == 0
    assert report["pytest_receipt_verified"] is False
    check = next(item for item in report["checks"] if item["name"] == "pytest")
    assert check["returncode"] == 0
    assert check["status"] == "failed"
    assert "Reçu de fin pytest absent" in check["output"]


def test_receipt_counts_must_be_numeric_consistent_and_match_exit_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, python = project(tmp_path)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    safe_runner = FakeRunner()

    def inconsistent_runner(command: list[str], **kwargs: object) -> CommandResult:
        result = safe_runner(command, **kwargs)
        if "pytest" in command:
            receipt_path = Path(command[command.index("pytest") + 1])
            receipt = json.loads(receipt_path.read_text())
            receipt["tests_executed"] = 500
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return result

    report = run_diagnostics(root, python_executable=python, runner=inconsistent_runner)
    assert report["status"] == "failed"
    assert report["tests_executed"] == 0
    assert report["pytest_receipt_verified"] is False
