"""Tests for AI cache (N100-I06)."""

from __future__ import annotations

import time

from career.ai_cache import AICache


def test_set_get(tmp_path) -> None:
    c = AICache(tmp_path / "c.json")
    c.set("p", "v")
    assert c.get("p") == "v"


def test_miss() -> None:
    c = AICache.__new__(AICache)
    c.path = __import__("pathlib").Path("/tmp/nope.json")
    c.ttl_sec = 3600
    c._data = {}
    assert c.get("x") is None


def test_invalidate(tmp_path) -> None:
    c = AICache(tmp_path / "c.json")
    c.set("p", "v")
    c.invalidate("p")
    assert c.get("p") is None


def test_ttl_expiry(tmp_path) -> None:
    c = AICache(tmp_path / "c.json", ttl_sec=0.0)
    c.set("p", "v")
    time.sleep(0.01)
    assert c.get("p") is None