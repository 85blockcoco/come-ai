"""Tests for error monitor (N100-J09)."""

from __future__ import annotations

from career.error_monitor import ErrorMonitor


def test_record_and_recent(tmp_path) -> None:
    m = ErrorMonitor(tmp_path / "errs.jsonl")
    m.record("boom", context="ctx")
    assert m.count() == 1
    recs = m.recent()
    assert len(recs) == 1
    assert recs[0].message == "boom"


def test_recent_limit(tmp_path) -> None:
    m = ErrorMonitor(tmp_path / "errs.jsonl")
    for i in range(5):
        m.record(f"err{i}")
    assert len(m.recent(limit=2)) == 2


def test_empty(tmp_path) -> None:
    m = ErrorMonitor(tmp_path / "errs.jsonl")
    assert m.recent() == []
    assert m.count() == 0