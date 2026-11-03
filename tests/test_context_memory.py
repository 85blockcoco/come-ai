"""Tests for context memory (N100-I09)."""

from career.context_memory import ContextMemory


def test_set_get() -> None:
    m = ContextMemory()
    m.set("x", 42)
    assert m.get("x") == 42


def test_default() -> None:
    m = ContextMemory()
    assert m.get("nope", "d") == "d"


def test_clear() -> None:
    m = ContextMemory()
    m.set("x", 1)
    m.clear()
    assert m.get("x") is None
    assert m.all() == {}