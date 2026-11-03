"""Tests for personal memory (N100-I01)."""

from __future__ import annotations

from career.personal_memory import PersonalMemory


def test_set_get(tmp_path) -> None:
    m = PersonalMemory(tmp_path / "mem.json")
    m.set("name", "Alice", approved=True)
    e = m.get("name")
    assert e is not None
    assert e.value == "Alice"
    assert e.approved is True


def test_delete(tmp_path) -> None:
    m = PersonalMemory(tmp_path / "mem.json")
    m.set("x", 1)
    assert m.delete("x") is True
    assert m.get("x") is None
    assert m.delete("x") is False


def test_all(tmp_path) -> None:
    m = PersonalMemory(tmp_path / "mem.json")
    m.set("a", 1)
    m.set("b", 2)
    assert len(m.all()) == 2


def test_persistence(tmp_path) -> None:
    p = tmp_path / "mem.json"
    m1 = PersonalMemory(p)
    m1.set("k", "v")
    m2 = PersonalMemory(p)
    assert m2.get("k") is not None
    assert m2.get("k").value == "v"