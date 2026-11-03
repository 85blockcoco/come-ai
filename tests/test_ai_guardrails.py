"""Tests for AI guardrails (N100-I04)."""

from career.ai_guardrails import check_output


def test_ok() -> None:
    r = check_output("Hello world")
    assert r.ok is True
    assert r.violations == []


def test_too_long() -> None:
    r = check_output("a" * 10001, max_length=100)
    assert r.ok is False
    assert "too_long" in r.violations


def test_sanitized() -> None:
    r = check_output("abc", max_length=2)
    assert r.sanitized == "ab"