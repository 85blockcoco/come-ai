"""Tests for circuit breaker (N100-I03)."""

from __future__ import annotations

import time

from career.circuit_breaker import CircuitBreaker, CircuitState


def test_initially_closed() -> None:
    cb = CircuitBreaker(threshold=3)
    assert cb.state() == CircuitState.CLOSED
    assert cb.allow() is True


def test_opens_after_threshold() -> None:
    cb = CircuitBreaker(threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.state() == CircuitState.OPEN
    assert cb.allow() is False


def test_success_resets() -> None:
    cb = CircuitBreaker(threshold=2)
    cb.record_failure()
    cb.record_success()
    assert cb.state() == CircuitState.CLOSED
    assert cb._failures == 0


def test_call_success() -> None:
    cb = CircuitBreaker(threshold=2)
    assert cb.call(lambda: 42) == 42


def test_call_failure_opens() -> None:
    cb = CircuitBreaker(threshold=1)
    try:
        cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
    except ValueError:
        pass
    assert cb.state() == CircuitState.OPEN
    try:
        cb.call(lambda: 1)
    except RuntimeError:
        pass


def test_half_open_after_reset() -> None:
    cb = CircuitBreaker(threshold=1, reset_after_sec=0.01)
    cb.record_failure()
    assert cb.state() == CircuitState.OPEN
    time.sleep(0.02)
    assert cb.state() == CircuitState.HALF_OPEN
    assert cb.allow() is True