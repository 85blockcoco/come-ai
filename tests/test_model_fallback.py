"""Tests for model fallback (N100-I07)."""

from career.model_fallback import try_models


def test_first_ok() -> None:
    m, r, errs = try_models(["a", "b"], lambda x: f"ok-{x}")
    assert m == "a"
    assert r == "ok-a"
    assert errs == []


def test_fallback() -> None:
    def call(m):
        if m == "a":
            raise RuntimeError("fail a")
        return f"ok-{m}"
    m, r, errs = try_models(["a", "b"], call)
    assert m == "b"
    assert r == "ok-b"
    assert len(errs) == 1


def test_all_fail() -> None:
    m, r, errs = try_models(["a", "b"], lambda x: (_ for _ in ()).throw(ValueError("x")))
    assert m is None
    assert r is None
    assert len(errs) == 2