"""Focused offline tests for the persistent Côme AI task queue."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from task_queue import (
    MAX_MESSAGES_PER_TASK,
    InvalidTaskStateError,
    TaskKind,
    TaskQueue,
    TaskQueueError,
    TaskRunner,
    TaskStatus,
)


def wait_for(predicate: object, *, timeout: float = 2.0) -> None:
    """Keep threaded tests deterministic without depending on implementation sleeps."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Condition non satisfaite avant le délai de test.")


def make_queue(tmp_path: Path) -> TaskQueue:
    return TaskQueue(tmp_path / "local-task-queue.sqlite3")


def test_queue_persists_typed_redacted_bounded_payloads(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    task = queue.create_task(
        TaskKind.DOCUMENT_INDEX,
        {
            "document_id": "doc_123",
            "api_key": ('AIzaThis' + 'MustNeve' + 'rBeStore' + 'dInTheQu' + 'eue01234' + '56789'),
            "nested": {"authorization": ('Bearer a' + '-very-se' + 'nsitive-' + 'token-va' + 'lue')},
        },
    )

    restored = TaskQueue(queue.database_path).get_task(task.id)
    assert restored.kind is TaskKind.DOCUMENT_INDEX
    assert restored.status is TaskStatus.QUEUED
    assert restored.payload["document_id"] == "doc_123"
    assert restored.payload["api_key"] == "[secret redacted]"
    assert restored.payload["nested"] == {"authorization": "[secret redacted]"}
    assert restored.messages[-1].text == "Tâche ajoutée à la file locale."

    with pytest.raises(TaskQueueError, match="trop long"):
        queue.create_task(TaskKind.DOCUMENT_INDEX, {"instructions": "x" * 20_000})

    with pytest.raises(TaskQueueError, match="Type de tâche invalide"):
        queue.create_task("python_exec", {"code": "print('no')"})


def test_restart_requeues_running_work_and_finalizes_requested_cancellation(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    resumable = queue.create_task(TaskKind.MEMORY_INDEX, {"source_id": "doc_1"})
    cancel_me = queue.create_task(TaskKind.MEMORY_INDEX, {"source_id": "doc_2"})
    assert queue.claim_next().id == resumable.id  # type: ignore[union-attr]
    assert queue.claim_next().id == cancel_me.id  # type: ignore[union-attr]
    queue.request_cancel(cancel_me.id)

    restarted = TaskQueue(queue.database_path)
    resumed = restarted.get_task(resumable.id)
    cancelled = restarted.get_task(cancel_me.id)

    assert resumed.status is TaskStatus.QUEUED
    assert resumed.started_at is None
    assert any("redémarrage" in message.text for message in resumed.messages)
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.cancellation_requested is True


def test_runner_uses_only_registered_handlers_and_persists_progress_and_result(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    calls: list[str] = []

    def controlled_index(context: object, payload: object) -> dict[str, object]:
        # The handler stands in for later app-owned, controlled workspace code.
        assert hasattr(context, "set_progress")
        assert isinstance(payload, dict)
        calls.append(str(payload["document_id"]))
        context.set_progress(45, "Index local en cours")  # type: ignore[attr-defined]
        return {
            "document_id": payload["document_id"],
            "indexed": True,
            "api_key": ('AIzaThis' + 'OutputMu' + 'stNeverR' + 'eachSQLi' + 'te012345' + '6789'),
        }

    runner = TaskRunner(queue, {TaskKind.DOCUMENT_INDEX: controlled_index})
    good = runner.submit(TaskKind.DOCUMENT_INDEX, {"document_id": "doc_7"})
    unsupported = runner.submit(TaskKind.PDF_OCR, {"document_id": "doc_8"})

    completed = runner.run_once()
    rejected = runner.run_once()

    assert completed is not None and completed.status is TaskStatus.SUCCEEDED
    assert completed.progress == 100
    assert completed.result == {
        "document_id": "doc_7",
        "indexed": True,
        "api_key": "[secret redacted]",
    }
    assert calls == ["doc_7"]
    assert rejected is not None and rejected.id == unsupported.id
    assert rejected.status is TaskStatus.FAILED
    assert "Aucun gestionnaire local autorisé" in (rejected.error or "")
    assert queue.get_task(good.id).messages[-1].text == "Tâche locale terminée."


def test_cooperative_cancellation_stops_worker_without_executing_untrusted_code(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    started = threading.Event()
    observed_checkpoints = 0

    def long_local_work(context: object, _payload: object) -> dict[str, bool]:
        nonlocal observed_checkpoints
        assert hasattr(context, "set_progress") and hasattr(context, "checkpoint")
        context.set_progress(10, "Travail local démarré")  # type: ignore[attr-defined]
        started.set()
        while True:
            observed_checkpoints += 1
            context.checkpoint()  # type: ignore[attr-defined]
            time.sleep(0.01)

    runner = TaskRunner(
        queue,
        {TaskKind.SPREADSHEET_ANALYSIS: long_local_work},
        poll_interval_seconds=0.05,
    )
    runner.start()
    task = runner.submit(TaskKind.SPREADSHEET_ANALYSIS, {"file_id": "f_abc"})
    try:
        assert started.wait(timeout=1.0)
        cancelling = runner.cancel(task.id)
        assert cancelling.status is TaskStatus.CANCELLING
        wait_for(lambda: queue.get_task(task.id).status is TaskStatus.CANCELLED)
        finished = queue.get_task(task.id)
        assert finished.status is TaskStatus.CANCELLED
        assert observed_checkpoints > 0
        assert runner.active_task_id is None
    finally:
        runner.stop(wait=True, timeout=1.0)


def test_errors_messages_and_terminal_state_are_bounded_and_redacted(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    task = queue.create_task(TaskKind.FINANCE_ANALYSIS, {"file_id": "f_finance"})
    running = queue.claim_next()
    assert running is not None and running.id == task.id
    failed = queue.finish_failed(
        task.id,
        ('provider' + ' says ap' + 'i_key=AI' + 'zaDoNotE' + 'xposeThi' + 'sValue12' + '34567890' + '12345678' + '90 ') + "x" * 3_000,
    )
    assert failed.status is TaskStatus.FAILED
    assert "AIzaDoNotExpose" not in (failed.error or "")
    assert "[secret redacted]" in (failed.error or "")
    assert len(failed.error or "") <= 2_000

    with pytest.raises(InvalidTaskStateError):
        queue.update_progress(task.id, 100)

    message_task = queue.create_task(TaskKind.STUDY_PLAN, {"goal": "réviser"})
    for number in range(MAX_MESSAGES_PER_TASK + 5):
        queue.append_message(message_task.id, f"message {number}")
    messages = queue.get_task(message_task.id).messages
    assert len(messages) == MAX_MESSAGES_PER_TASK
    assert messages[-1].text == f"message {MAX_MESSAGES_PER_TASK + 4}"
