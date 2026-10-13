"""Fictional projects exercise staging, test gates and conflict-safe recovery."""
from pathlib import Path

import pytest

from devkit.patching import PatchError, PatchWorkspace, source_fingerprint


@pytest.fixture
def workshop(tmp_path):
    root = tmp_path / "fictional-project"
    root.mkdir()
    (root / "core.py").write_text("def answer():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("Fictional project\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_core.py").write_text("def test_example():\n    assert True\n", encoding="utf-8")
    (root / ".env").write_text("PRIVATE_VALUE=fictitious\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "private.txt").write_text("fictional private document", encoding="utf-8")
    return PatchWorkspace(root, tmp_path / "private-workshop")


def proof(workshop, candidate_id):
    return {"status": "passed", "checks": [{"name": "pytest", "status": "passed"}],
            "tests_executed": 1, "sandbox_used": True, "pytest_receipt_verified": True,
            "source_fingerprint": source_fingerprint(workshop.candidate_path(candidate_id))}


def proposal(workshop):
    return workshop.stage_patch("--- a/core.py\n+++ b/core.py\n@@ -1,2 +1,2 @@\n def answer():\n-    return 1\n+    return 2\n")


def test_patch_stage_validate_apply_and_rollback_preserves_private_files(workshop):
    staged = proposal(workshop)
    identifier = staged["candidate_id"]
    candidate = workshop.candidate_path(identifier)
    assert not (candidate / ".env").exists()
    assert not (candidate / "data").exists()
    assert (workshop.project_root / "core.py").read_text() == "def answer():\n    return 1\n"
    assert staged["changed_files"] == [{"path": "core.py", "operation": "modify"}]
    assert "-    return 1\n+    return 2\n" in staged["diff"]
    assert "fictional-project" not in str(staged)
    workshop.mark_validation(identifier, proof(workshop, identifier))
    result = workshop.apply(identifier)
    assert (workshop.project_root / "core.py").read_text() == "def answer():\n    return 2\n"
    rollback = workshop.rollback(result["transaction_id"])
    assert rollback["status"] == "rolled_back"
    assert (workshop.project_root / "core.py").read_text() == "def answer():\n    return 1\n"
    assert (workshop.project_root / ".env").read_text() == "PRIVATE_VALUE=fictitious\n"
    assert (workshop.project_root / "data" / "private.txt").read_text() == "fictional private document"
    with pytest.raises(PatchError):
        workshop.rollback(result["transaction_id"])


def test_application_requires_actual_successful_sandbox_tests(workshop):
    identifier = proposal(workshop)["candidate_id"]
    with pytest.raises(PatchError, match="validation"):
        workshop.apply(identifier)
    for changed in ({"status": "failed"}, {"checks": [{"name": "pytest", "status": "skipped"}]},
                    {"tests_executed": 0}, {"sandbox_used": False}, {"pytest_receipt_verified": False}, {"source_fingerprint": "bad"}):
        report = {**proof(workshop, identifier), **changed}
        with pytest.raises(PatchError, match="Tests réussis"):
            workshop.mark_validation(identifier, report)
        with pytest.raises(PatchError):
            workshop.apply(identifier)


def test_candidate_edits_invalidate_test_proof(workshop):
    identifier = proposal(workshop)["candidate_id"]
    workshop.mark_validation(identifier, proof(workshop, identifier))
    (workshop.candidate_path(identifier) / "core.py").write_text("other = 3\n", encoding="utf-8")
    with pytest.raises(PatchError, match="validation"):
        workshop.apply(identifier)
    assert "return 1" in (workshop.project_root / "core.py").read_text()


def test_original_edits_refused_and_preview_remains_stable(workshop):
    staged = proposal(workshop)
    identifier = staged["candidate_id"]
    workshop.mark_validation(identifier, proof(workshop, identifier))
    (workshop.project_root / "README.md").write_text("User just edited this\n", encoding="utf-8")
    assert workshop.preview(identifier)["diff"] == staged["diff"]
    with pytest.raises(PatchError, match="code principal a changé"):
        workshop.apply(identifier)
    assert (workshop.project_root / "README.md").read_text() == "User just edited this\n"


def test_rollback_never_overwrites_new_user_edit(workshop):
    identifier = proposal(workshop)["candidate_id"]
    workshop.mark_validation(identifier, proof(workshop, identifier))
    result = workshop.apply(identifier)
    (workshop.project_root / "core.py").write_text("user_change = True\n", encoding="utf-8")
    with pytest.raises(PatchError, match="édition plus récente"):
        workshop.rollback(result["transaction_id"])
    assert (workshop.project_root / "core.py").read_text() == "user_change = True\n"


def test_files_can_add_delete_and_restore_empty_text(workshop):
    staged = workshop.stage_files({"new.py": "", "README.md": None, "core.py": "changed = True\n"})
    identifier = staged["candidate_id"]
    assert {item["operation"] for item in staged["changed_files"]} == {"add", "delete", "modify"}
    assert "+++ b/new.py" in staged["diff"]
    workshop.mark_validation(identifier, proof(workshop, identifier))
    result = workshop.apply(identifier)
    assert (workshop.project_root / "new.py").read_bytes() == b""
    assert not (workshop.project_root / "README.md").exists()
    workshop.rollback(result["transaction_id"])
    assert not (workshop.project_root / "new.py").exists()
    assert (workshop.project_root / "README.md").read_text() == "Fictional project\n"


def test_git_addition_and_unified_deletion(workshop):
    staged = workshop.stage_patch("diff --git a/added.py b/added.py\nnew file mode 100644\nindex 0000000..1234567\n--- /dev/null\n+++ b/added.py\n@@ -0,0 +1 @@\n+value = 3\n--- a/README.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-Fictional project\n")
    candidate = workshop.candidate_path(staged["candidate_id"])
    assert (candidate / "added.py").read_text() == "value = 3\n"
    assert not (candidate / "README.md").exists()


def test_missing_final_newline_preserved_in_exact_diff(workshop):
    (workshop.project_root / "core.py").write_text("value = 1", encoding="utf-8")
    staged = workshop.stage_patch("--- a/core.py\n+++ b/core.py\n@@ -1 +1 @@\n-value = 1\n\\ No newline at end of file\n+value = 2\n\\ No newline at end of file\n")
    assert (workshop.candidate_path(staged["candidate_id"]) / "core.py").read_bytes() == b"value = 2"
    assert staged["diff"].count("\\ No newline at end of file") == 2


@pytest.mark.parametrize("relative", ["../outside.py", "/tmp/outside.py", "tests/../../outside.py", ".env", "data/private.txt", "tests\\outside.py"])
def test_sensitive_paths_and_traversal_refused(workshop, relative):
    with pytest.raises(PatchError):
        workshop.stage_files({relative: "value = 1\n"})
    with pytest.raises(PatchError):
        workshop.stage_patch(f"--- /dev/null\n+++ b/{relative}\n@@ -0,0 +1 @@\n+value = 1\n")


@pytest.mark.parametrize("patch", [
    "--- a/core.py\n+++ b/core.py\n@@ -1,2 +1,2 @@\n def wrong():\n-    return 1\n+    return 2\n",
    "--- a/core.py\n+++ b/core.py\n@@ -1,2 +1,2 @@\n def answer():\n",
    "--- a/core.py\n+++ b/core.py\n@@ -99 +1 @@\n-nothing\n+changed\n",
    "--- a/core.py\n+++ b/other.py\n@@ -1,2 +1,2 @@\n def answer():\n-    return 1\n+    return 2\n",
    "diff --git a/core.py b/core.py\nold mode 100644\nnew mode 100755\n",
    "GIT binary patch\nencoded\n",
])
def test_corrupt_hunks_renames_modes_and_binary_refused(workshop, patch):
    with pytest.raises(PatchError):
        workshop.stage_patch(patch)
    assert "return 1" in (workshop.project_root / "core.py").read_text()


def test_symlinks_and_embedded_credential_rejected(workshop):
    outside = workshop.project_root.parent / "outside.py"
    outside.write_text("private = True\n", encoding="utf-8")
    (workshop.project_root / "linked.py").symlink_to(outside)
    with pytest.raises(PatchError, match="liens symboliques"):
        workshop.stage_files({"linked.py": "replace = True\n"})
    fake_token = "AIza" + "x" * 34
    with pytest.raises(PatchError, match="source non autorisé"):
        workshop.stage_files({"new.py": f"value = '{fake_token}'\n"})
    assert outside.read_text() == "private = True\n"
    assert not list(workshop.storage_root.rglob("new.py"))


def test_mid_application_error_restores_all_previous_sources(workshop, monkeypatch):
    from devkit import patching
    (workshop.project_root / "second.py").write_text("original = 1\n", encoding="utf-8")
    staged = workshop.stage_files({"core.py": "changed = 2\n", "second.py": "changed = 3\n"})
    identifier = staged["candidate_id"]
    workshop.mark_validation(identifier, proof(workshop, identifier))
    real_write = patching._atomic_write
    failed = False

    def fail_once(path, content, mode=0o600):
        nonlocal failed
        if path == workshop.project_root / "second.py" and not failed:
            failed = True
            raise OSError("fictional disk failure")
        return real_write(path, content, mode)

    monkeypatch.setattr(patching, "_atomic_write", fail_once)
    with pytest.raises(PatchError, match="restaurés"):
        workshop.apply(identifier)
    assert (workshop.project_root / "core.py").read_text() == "def answer():\n    return 1\n"
    assert (workshop.project_root / "second.py").read_text() == "original = 1\n"


def test_persistent_history_uses_opaque_ids_and_restores_after_restart(workshop):
    staged = proposal(workshop)
    identifier = staged["candidate_id"]
    workshop.mark_validation(identifier, proof(workshop, identifier))
    result = workshop.apply(identifier)
    restarted = PatchWorkspace(workshop.project_root, workshop.storage_root)
    candidates = restarted.list_candidates()
    transactions = restarted.list_transactions()
    assert candidates[0]["candidate_id"] == identifier
    assert candidates[0]["status"] == "applied"
    assert candidates[0]["created_at"]
    assert "diff" not in candidates[0]
    assert transactions[0]["transaction_id"] == result["transaction_id"]
    assert transactions[0]["rollback_available"]
    assert "fictional-project" not in str(transactions)
    restarted.rollback(result["transaction_id"])
    assert restarted.list_transactions()[0]["status"] == "rolled_back"


def test_history_ignores_corrupt_and_symlinked_records(workshop):
    staged = proposal(workshop)
    folder = workshop.storage_root / "transactions"
    folder.mkdir()
    (folder / ("a" * 32)).symlink_to(workshop.storage_root / "candidates" / staged["candidate_id"])
    corrupt = folder / ("b" * 32)
    corrupt.mkdir()
    (corrupt / "metadata.json").write_text("invalid", encoding="utf-8")
    assert workshop.list_transactions() == []
    with pytest.raises(PatchError):
        workshop.list_candidates(limit=1000)


def test_failed_rollback_restores_complete_post_patch_state(workshop, monkeypatch):
    from devkit import patching
    (workshop.project_root / "second.py").write_text("original = 1\n", encoding="utf-8")
    staged = workshop.stage_files({"core.py": "changed = 2\n", "second.py": "changed = 3\n"})
    identifier = staged["candidate_id"]
    workshop.mark_validation(identifier, proof(workshop, identifier))
    result = workshop.apply(identifier)
    real_write = patching._atomic_write
    failed = False

    def fail_once(path, content, mode=0o600):
        nonlocal failed
        if path == workshop.project_root / "core.py" and not failed:
            failed = True
            raise OSError("fictional rollback disk failure")
        return real_write(path, content, mode)

    monkeypatch.setattr(patching, "_atomic_write", fail_once)
    with pytest.raises(PatchError, match="état après correctif est conservé"):
        workshop.rollback(result["transaction_id"])
    assert (workshop.project_root / "core.py").read_text() == "changed = 2\n"
    assert (workshop.project_root / "second.py").read_text() == "changed = 3\n"
    assert workshop.list_transactions()[0]["rollback_available"]


def test_storage_never_recursively_copies_itself_or_follows_group_link(workshop):
    with pytest.raises(PatchError, match="hors des dossiers de code"):
        PatchWorkspace(workshop.project_root, workshop.project_root / "devkit" / "private")
    outside = workshop.project_root.parent / "outside-storage"
    outside.mkdir()
    (workshop.storage_root / "candidates").symlink_to(outside)
    with pytest.raises(PatchError, match="liens symboliques de stockage"):
        proposal(workshop)
    assert list(outside.iterdir()) == []
