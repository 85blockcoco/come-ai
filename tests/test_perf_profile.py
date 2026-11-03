"""Tests for perf profiling (N100-J08)."""

from __future__ import annotations


from career.perf_profile import profile, profile_many


def test_profile_ok() -> None:
    r = profile("t", lambda: None)
    assert r.ok is True
    assert r.name == "t"
    assert r.duration_sec >= 0.0


def test_profile_error() -> None:
    r = profile("t", lambda: (_ for _ in ()).throw(ValueError("boom")))
    assert r.ok is False
    assert "boom" in (r.error or "")


def test_profile_many() -> None:
    res = profile_many({"a": lambda: None, "b": lambda: None})
    assert len(res) == 2
    assert all(r.ok for r in res)