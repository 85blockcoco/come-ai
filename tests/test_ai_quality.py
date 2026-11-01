"""Tests for AI quality (N100-I08)."""

from career.ai_quality import score_ai_output


def test_good() -> None:
    r = score_ai_output("Hello world. This is a test output with enough length.")
    assert r.score >= 70
    assert r.no_forbidden is True


def test_forbidden() -> None:
    r = score_ai_output("This is invented content.")
    assert r.no_forbidden is False
    assert r.score <= 70


def test_empty() -> None:
    r = score_ai_output("")
    assert r.score <= 30.0
    assert r.length_ok is False