"""Tests for recovery (N100-I02)."""

from __future__ import annotations

from career.recovery import retry_with_backoff


def test_success_first() -> None:
    r = retry_with_backoff(lambda: 42)
    assert r.ok is True
    assert r.attempts == 1
    assert r.result == 42


def test_retry_then_success() -> None:
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("fail")
        return "ok"

    r = retry_with_backoff(fn, max_attempts=3, base_delay=0.0, sleep=lambda x: None)
    assert r.ok is True
    assert r.attempts == 3


def test_all_fail() -> None:
    r = retry_with_backoff(lambda: (_ for _ in ()).throw(ValueError("boom")), max_attempts=2, base_delay=0.0, sleep=lambda x: None)
    assert r.ok is False
    assert r.attempts == 2
    assert "boom" in (r.last_error or "")


def test_backoff_delays() -> None:
    delays = []

    def fn():
        raise ValueError("x")

    retry_with_backoff(fn, max_attempts=3, base_delay=0.1, max_delay=0.5, sleep=delays.append)
    assert len(delays) == 2
    assert delays[0] == 0.1
    assert delays[1] == 0.2