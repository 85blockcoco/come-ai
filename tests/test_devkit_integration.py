"""Synthetic end-to-end workshop routes and inert AI proposals."""

from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from come_ai_web import create_app
from devkit.exporting import KitError, source_fingerprint, build_issue_bundle, export_snapshot
from devkit.proposals import CodeProposal, propose_in_isolation
from devkit.patching import PatchError, PatchWorkspace


def fixture_project(path: Path) -> Path:
    path.mkdir(exist_ok=True)
    (path / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (path / "requirements-fixture.txt").write_text("pytest>=8\n", encoding="utf-8")
    tests = path / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_calculator.py").write_text("from calculator import add\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    return path


def test_http_export_issue_and_test_gated_patch_preserve_private_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_project(tmp_path)
    (root / ".env").write_text("GEMINI_API_KEY=synthetic-private-value\n", encoding="utf-8")
    app = create_app(root)
    try:
        with TestClient(app) as client:
            response = client.get("/api/devkit/status", headers={"Origin": "http://testserver"})
            assert response.status_code == 200
            token = response.json()["workshop_token"]
            assert token, "l'atelier doit libérer son jeton pour son propre navigateur"
            # Un navigateur étranger ne doit ni recevoir le jeton ni le déduire.
            foreign = client.get("/api/devkit/status", headers={"Origin": "https://example.invalid"})
            assert foreign.status_code == 403
            anonymous = client.get("/api/devkit/status")
            assert anonymous.status_code == 200
            assert anonymous.json()["workshop_token"] == ""
            assert "source_files" not in anonymous.json()
            assert "latest_report" not in anonymous.json()
            headers = {"X-Workshop-Token": token}
            assert client.post("/api/devkit/exports", json={}).status_code == 403
            assert client.post("/api/devkit/exports", json={}, headers={**headers, "Origin": "https://example.invalid"}).status_code == 403
            exported = client.post("/api/devkit/exports", json={}, headers=headers)
            assert exported.status_code == 200, exported.text
            assert client.get(exported.json()["download_url"]).status_code == 403
            download = client.get(exported.json()["download_url"], headers=headers)
            from io import BytesIO
            with zipfile.ZipFile(BytesIO(download.content)) as archive:
                assert "source/calculator.py" in archive.namelist()
                assert not any(".env" in name or "career_data" in name for name in archive.namelist())
                assert b"synthetic-private-value" not in b"".join(archive.read(name) for name in archive.namelist())

            issue = client.post("/api/devkit/issues", json={"title": "Somme incorrecte", "description": "2 + 3 devrait retourner 5", "selected_files": ["calculator.py"]}, headers=headers)
            assert issue.status_code == 200, issue.text
            staged = client.post("/api/devkit/candidates/files", json={"files": {"calculator.py": "def add(a, b):\n    return a + b\n"}}, headers=headers)
            assert staged.status_code == 200, staged.text
            candidate = staged.json()["candidate_id"]
            assert "+    return a + b" in staged.json()["diff"]
            assert client.get(f"/api/devkit/candidates/{candidate}").status_code == 403
            assert client.get(f"/api/devkit/candidates/{candidate}", headers=headers).status_code == 200
            assert client.get("/api/devkit/evolution").status_code == 403
            assert client.get("/api/devkit/evolution", headers=headers).status_code == 200
            assert "return a - b" in (root / "calculator.py").read_text()
            apply_url = f"/api/devkit/candidates/{candidate}/apply"
            assert client.post(apply_url, json={"confirmed": True}, headers=headers).status_code == 400

            def fake_diagnostics(project_root: Path, **kwargs):
                # Simulated runner metadata; this test checks transport and
                # gating, while diagnostics tests exercise the real sandbox.
                assert kwargs["require_sandbox"] is True
                assert kwargs["python_executable"] == Path(sys.executable)
                return {"schema_version": 1, "status": "passed", "sandbox_used": True, "tests_executed": 1, "pytest_receipt_verified": True,
                        "source_fingerprint": source_fingerprint(project_root), "checks": [{"name": "pytest", "status": "passed", "output": "1 passed"}]}

            monkeypatch.setattr("devkit.service.run_diagnostics", fake_diagnostics)
            job = client.post("/api/devkit/diagnostics", json={"candidate_id": candidate}, headers=headers)
            assert job.status_code == 200
            assert client.get(f"/api/devkit/jobs/{job.json()['job_id']}").status_code == 403
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                status = client.get(f"/api/devkit/jobs/{job.json()['job_id']}", headers=headers).json()
                if status["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.01)
            assert status["status"] == "completed", status
            assert client.post(apply_url, json={"confirmed": False}, headers=headers).status_code == 400
            applied = client.post(apply_url, json={"confirmed": True}, headers=headers)
            assert applied.status_code == 200, applied.text
            assert "return a + b" in (root / "calculator.py").read_text()
            transaction = applied.json()["transaction_id"]
            rolled = client.post(f"/api/devkit/transactions/{transaction}/rollback", json={"confirmed": True}, headers=headers)
            assert rolled.status_code == 200, rolled.text
            assert "return a - b" in (root / "calculator.py").read_text()
            assert (root / ".env").read_text() == "GEMINI_API_KEY=synthetic-private-value\n"
    finally:
        app.state.runtime.task_runner.stop(wait=True, timeout=1)


def test_inert_local_reviewer_only_stages_selected_source(tmp_path: Path) -> None:
    root = fixture_project(tmp_path)

    class FakeLocalReviewer:
        is_remote = False
        def propose(self, context):
            assert list(context.sources) == ["calculator.py"]
            assert "2 + 3" in context.issue["description"]
            return CodeProposal(files={"calculator.py": "def add(a, b):\n    return a + b\n"})

    result = propose_in_isolation(root, root / ".devkit", FakeLocalReviewer(), title="Somme", description="2 + 3 devrait valoir 5", selected_files=["calculator.py"])
    assert result["status"] == "staged"
    assert "return a - b" in (root / "calculator.py").read_text()
    class FakeRemoteReviewer(FakeLocalReviewer):
        is_remote = True
        def propose(self, context):
            raise AssertionError("Remote calls must be blocked before generation")
    with pytest.raises(KitError):
        propose_in_isolation(root, root / ".devkit", FakeRemoteReviewer(), title="Somme", description="Reproduire", selected_files=["calculator.py"])


def test_out_of_scope_proposal_is_refused_before_staging(tmp_path: Path) -> None:
    root = fixture_project(tmp_path)
    class OutOfScopeReviewer:
        is_remote = False
        def propose(self, context):
            return CodeProposal(files={"other.py": "value = 42\n"})
    with pytest.raises(PatchError, match="périmètre"):
        propose_in_isolation(root, root / ".devkit", OutOfScopeReviewer(), title="Somme", description="Corriger addition", selected_files=["calculator.py"])
    assert PatchWorkspace(root, root / ".devkit").list_candidates() == []
    assert not (root / "other.py").exists()


def test_devkit_report_reads_reject_cross_site_and_invalid_tokens(tmp_path: Path) -> None:
    root = fixture_project(tmp_path)
    app = create_app(root)
    try:
        with TestClient(app) as client:
            status = client.get("/api/devkit/status", headers={"Origin": "http://testserver"}).json()
            headers = {"X-Workshop-Token": status["workshop_token"]}
            assert client.get("/api/devkit/evolution", headers={**headers, "Origin": "https://example.invalid"}).status_code == 403
            assert client.get("/api/devkit/evolution", headers={"X-Workshop-Token": "wrong"}).status_code == 403
            assert client.get("/api/devkit/jobs/unknown").status_code == 403
            assert client.get("/api/devkit/evolution/runs/unknown").status_code == 403
            assert client.get("/api/devkit/artifacts/unknown").status_code == 403
    finally:
        app.state.runtime.task_runner.stop(wait=True, timeout=1)


def test_cli_refuses_symbolic_storage_and_tolerates_corrupt_previous_report(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from devkit.__main__ import main
    root = fixture_project(tmp_path / "project")
    target = tmp_path / "private-folder"
    target.mkdir(mode=0o755)
    old_mode = target.stat().st_mode
    (root / ".devkit").symlink_to(target, target_is_directory=True)
    assert main(["--project", str(root), "export"]) == 1
    assert target.stat().st_mode == old_mode
    assert list(target.iterdir()) == []
    # Removing a fictitious fixture link only; its target stays intact.
    (root / ".devkit").unlink()
    reports = root / ".devkit" / "diagnostics"
    reports.mkdir(parents=True)
    (reports / "latest.json").write_text("not-json", encoding="utf-8")
    corrected = tmp_path / "correction.py"
    corrected.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    assert main(["--project", str(root), "stage", "--file", f"calculator.py={corrected}"]) == 0
    assert main(["--project", str(root), "export"]) == 0


def test_issue_does_not_inspect_unselected_source_and_snapshot_marks_stale_report(tmp_path: Path) -> None:
    root = fixture_project(tmp_path / "project")
    original_fingerprint = source_fingerprint(root)
    (root / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    snapshot = export_snapshot(root, tmp_path / "snapshot.zip", diagnostic_report={"status": "passed", "source_fingerprint": original_fingerprint})
    assert snapshot["manifest"]["diagnostic_matches_project"] is False
    # Synthetic credential-shaped literal in an unrelated source. A targeted
    # request must not open or include this file; a full snapshot blocks it.
    token = "AIza" + "x" * 35
    (root / "unrelated.py").write_text(f"value = {token!r}\n", encoding="utf-8")
    issue = build_issue_bundle(root, tmp_path / "issue.zip", title="Somme", description="Vérifier addition", selected_files=["calculator.py"], diagnostic_report={"status": "passed", "source_fingerprint": original_fingerprint})
    assert issue["issue"]["selected_files"] == ["calculator.py"]
    assert issue["manifest"]["diagnostic_matches_project"] is None
    with pytest.raises(KitError):
        export_snapshot(root, tmp_path / "refused.zip")
