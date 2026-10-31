"""Offline metadata tests; no model, project credentials or private data involved."""

import json

import pytest

from devkit.evolution_store import EvolutionStore, EvolutionStoreError


@pytest.fixture
def store(tmp_path):
    return EvolutionStore(tmp_path / "workshop")


def task(store, title="Repair fictional core", priority=50):
    return store.add_task(title, "Correct the fictional return value.", ["core.py"], "Keep all existing tests.", priority)


def run(store, item=None):
    item = item or task(store)
    store.claim_task(item["task_id"])
    return store.begin_run(item["task_id"], "ollama", "fixture-local", 2, 2)


def test_tasks_persist_deduplicate_and_use_priority_order(store):
    normal = task(store)
    duplicate = store.add_task("  Repair fictional core  ", "Correct the fictional return value.",
                               ["core.py", "core.py"], "Keep all existing tests.", 99)
    urgent = task(store, "Repair urgent fictional bug", 90)
    assert duplicate["task_id"] == normal["task_id"]
    assert len(store.list_tasks()) == 2
    restarted = EvolutionStore(store.storage_root)
    assert restarted.next_task()["task_id"] == urgent["task_id"]
    assert restarted.get_task(normal["task_id"])["selected_files"] == ["core.py"]
    assert "fingerprint" not in restarted.get_task(normal["task_id"])


def test_claim_is_exclusive_and_never_replays_a_running_task(store):
    first = task(store)
    second = task(store, "Second fictional task")
    assert store.claim_next_task()["task_id"] == first["task_id"]
    assert store.claim_next_task() is None
    with pytest.raises(EvolutionStoreError, match="déjà en cours"):
        store.claim_task(second["task_id"])
    assert store.get_task(second["task_id"])["status"] == "queued"
    with pytest.raises(EvolutionStoreError):
        store.begin_run(second["task_id"], "ollama", "fixture-local", 2, 2)


def test_interruption_recovery_is_explicit_and_requires_requeue(store):
    execution = run(store)
    restarted = EvolutionStore(store.storage_root)
    assert restarted.get_run(execution["run_id"])["status"] == "running"
    assert restarted.recover_interrupted() == {"recovered_runs": 1, "recovered_tasks": 1, "remote_requests_replayed": 0}
    assert restarted.next_task() is None
    assert restarted.get_run(execution["run_id"])["status"] == "waiting_provider"
    assert restarted.recover_interrupted()["recovered_runs"] == 0
    restarted.update_task(execution["task_id"], "queued")
    assert restarted.claim_next_task()["task_id"] == execution["task_id"]


def test_metrics_count_only_reported_values_and_survive_restart(store):
    execution = run(store)
    identifier = execution["run_id"]
    store.record_event(identifier, "generation", "running", "Attempt one", data={"attempt": 1, "requests": 1})
    store.record_event(identifier, "usage", "measured", "Reported usage", data={"input_tokens": 31, "output_tokens": 7,
                                                                               "total_tokens": 38, "duration_seconds": 0.25})
    store.record_event(identifier, "generation", "running", "Attempt two", data={"attempt": 2, "requests": 1})
    store.record_event(identifier, "validation", "failed", "Actual diagnostic counters", data={"tests_passed": 2, "tests_failed": 1})
    result = store.finish_run(identifier, "failed", reason="Tests failed.")
    assert result["metrics"]["attempts"] == 2
    assert result["metrics"]["requests"] == 2
    assert result["metrics"]["total_tokens"] == 38
    assert result["metrics"]["measured_usage_events"] == 1
    assert result["metrics"]["duration_seconds"] == 0.25
    restarted = EvolutionStore(store.storage_root)
    assert restarted.get_run(identifier)["metrics"] == result["metrics"]
    dashboard = restarted.dashboard()
    assert dashboard["metrics"] == result["metrics"]
    assert dashboard["unknown_usage_is_not_estimated"] is True
    assert dashboard["automatic_application"] is False


def test_finished_run_cannot_gain_events_and_cancellation_persists(store):
    execution = run(store)
    store.update_task(execution["task_id"], "cancelled")
    result = store.finish_run(execution["run_id"], "needs_review", candidate_id="a" * 32)
    assert result["status"] == "needs_review"
    assert store.get_task(execution["task_id"])["status"] == "cancelled"
    with pytest.raises(EvolutionStoreError, match="déjà terminée"):
        store.record_event(execution["run_id"], "usage", "measured", "Late event")
    with pytest.raises(EvolutionStoreError):
        store.finish_run(execution["run_id"], "failed")


def test_event_payload_excludes_prompts_credentials_and_unapproved_fields(store):
    execution = run(store)
    fictional_secret = "fixture-" + "credential-value"
    event = store.record_event(execution["run_id"], "usage", "measured", "api_key=" + fictional_secret,
                               data={"input_tokens": 11, "prompt": "private fictional prompt", "api_key": fictional_secret})
    assert event["data"] == {"input_tokens": 11}
    assert fictional_secret not in json.dumps(event)
    item = store.add_task("Redacted task", "authorization=" + fictional_secret, ["core.py"])
    assert fictional_secret not in item["description"]


@pytest.mark.parametrize("path", [".env", "data/private.txt", "../core.py", "/tmp/core.py"])
def test_private_and_traversal_task_paths_refused(store, path):
    with pytest.raises(EvolutionStoreError):
        store.add_task("Bad selection", "Fictional request", [path])
    assert store.list_tasks() == []


@pytest.mark.parametrize("data", [{"requests": True}, {"input_tokens": -1}, {"duration_seconds": float("nan")},
                                   {"duration_seconds": float("inf")}, {"candidate_id": "../invalid"}])
def test_invalid_measured_counters_are_not_stored(store, data):
    execution = run(store)
    with pytest.raises(EvolutionStoreError):
        store.record_event(execution["run_id"], "usage", "measured", "Invalid fixture", data=data)
    assert store.get_run(execution["run_id"])["events"] == []


def test_symlinked_store_does_not_touch_target(tmp_path):
    target = tmp_path / "untouched"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(EvolutionStoreError, match="liens symboliques"):
        EvolutionStore(linked)
    assert list(target.iterdir()) == []


def test_targeted_scope_persists_and_is_part_of_task_identity(store):
    first = store.add_task("Scoped task", "Fix fictional core", ["core.py"], targeted_tests=["tests/test_core.py"])
    assert first["targeted_tests"] == ["tests/test_core.py"]
    assert EvolutionStore(store.storage_root).get_task(first["task_id"])["targeted_tests"] == ["tests/test_core.py"]
    assert store.add_task("Scoped task", "Fix fictional core", ["core.py"], targeted_tests=["tests/test_core.py"])["task_id"] == first["task_id"]
    other = store.add_task("Scoped task", "Fix fictional core", ["core.py"], targeted_tests=["tests/test_other.py"])
    assert other["task_id"] != first["task_id"]
    legacy = store.add_task("Scoped task", "Fix fictional core", ["core.py"])
    assert legacy["targeted_tests"] is None
    assert legacy["task_id"] not in {first["task_id"], other["task_id"]}


def test_legacy_store_migration_preserves_tasks_and_default_scope(store):
    import sqlite3

    task = store.add_task("Legacy", "Fictional task", ["core.py"])
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("ALTER TABLE evolution_tasks DROP COLUMN targeted_tests")
        connection.execute("PRAGMA user_version=1")
    migrated = EvolutionStore(store.storage_root)
    assert migrated.get_task(task["task_id"])["targeted_tests"] is None
    assert migrated.add_task("Legacy", "Fictional task", ["core.py"])["task_id"] == task["task_id"]
    assert len(migrated.list_tasks()) == 1
    backup = store.directory / "evolution-v1-before-v2.sqlite3"
    assert backup.is_file()
    assert backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "targeted_tests" not in {row[1] for row in connection.execute("PRAGMA table_info(evolution_tasks)")}
        assert connection.execute("SELECT task_id FROM evolution_tasks").fetchone()[0] == task["task_id"]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_new_store_does_not_create_migration_backup(store):
    assert list(store.directory.glob("evolution-v*-before-v*.sqlite3")) == []


@pytest.mark.parametrize("symlink", [False, True])
def test_migration_refuses_existing_backup_without_modifying_it_or_schema(store, tmp_path, symlink):
    import sqlite3

    with sqlite3.connect(store.database_path) as connection:
        connection.execute("ALTER TABLE evolution_tasks DROP COLUMN targeted_tests")
        connection.execute("PRAGMA user_version=1")
    target = tmp_path / "untouched-backup"
    target.write_bytes(b"synthetic-original-backup")
    backup = store.directory / "evolution-v1-before-v2.sqlite3"
    if symlink:
        backup.symlink_to(target)
    else:
        backup.write_bytes(b"synthetic-original-backup")
    with pytest.raises(EvolutionStoreError, match="sauvegarde"):
        EvolutionStore(store.storage_root)
    assert target.read_bytes() == b"synthetic-original-backup"
    assert backup.read_bytes() == b"synthetic-original-backup"
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "targeted_tests" not in {row[1] for row in connection.execute("PRAGMA table_info(evolution_tasks)")}


@pytest.mark.parametrize("selection", [[], ["tests/test_a.py"] * 9, ["../test_a.py"], ["tests/test_a.py::test_a"], ["core.py"]])
def test_bad_targeted_scopes_are_never_persisted(store, selection):
    with pytest.raises(ValueError):
        store.add_task("Bad scope", "Fictional task", ["core.py"], targeted_tests=selection)
    assert store.list_tasks() == []
