"""Tests du mode hors-ligne et du cache local (SPEC-032)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from career.offline_mode import (
    CacheEntry,
    OfflineCache,
    OfflineDecision,
    freshness_policy,
    serve_or_cache,
)
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


def _future(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="microseconds")


def _past(hours: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="microseconds")


# --- Dataclasses -------------------------------------------------------------


def test_cache_entry_roundtrip() -> None:
    entry = CacheEntry(key="k", payload={"a": 1}, fetched_at=_past(1), max_age_hours=2)
    d = entry.to_dict()
    restored = CacheEntry.from_dict(d)
    assert restored.key == "k"
    assert restored.payload == {"a": 1}
    assert restored.max_age_hours == 2


def test_offline_decision_defaults() -> None:
    decision = OfflineDecision(source="network", age_hours=0.0)
    assert decision.degraded_fields == []
    assert decision.source == "network"


# --- Cache CRUD --------------------------------------------------------------


def test_cache_put_get(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    entry = cache.put("offers", {"items": [1, 2]}, max_age_hours=3)
    assert entry.key == "offers"
    got = cache.get("offers")
    assert got is not None
    assert got.payload == {"items": [1, 2]}
    assert cache.has("offers")
    assert "offers" in cache


def test_cache_persistence(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    cache.put("k", {"x": 42}, max_age_hours=10)
    # New instance reads from disk.
    cache2 = OfflineCache(tmp_path)
    got = cache2.get("k")
    assert got is not None
    assert got.payload == {"x": 42}


def test_cache_delete_clear(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    cache.put("a", {"v": 1})
    cache.put("b", {"v": 2})
    assert cache.delete("a") is True
    assert cache.get("a") is None
    assert cache.clear() >= 1
    assert len(cache) == 0


def test_cache_entry_not_found_raises(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    with pytest.raises(KeyError):
        _ = cache["missing"]


def test_cache_list_keys(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    cache.put("one", {"v": 1})
    cache.put("two", {"v": 2})
    assert set(cache.list_keys()) == {"one", "two"}


# --- Freshness policy ---------------------------------------------------------


def test_freshness_fresh() -> None:
    entry = CacheEntry(key="k", payload={"a": 1}, fetched_at=_past(1), max_age_hours=5)
    decision = freshness_policy(entry)
    assert decision.source == "cache"
    assert decision.age_hours is not None
    assert decision.age_hours >= 0


def test_freshness_stale() -> None:
    entry = CacheEntry(key="k", payload={"a": 1}, fetched_at=_past(10), max_age_hours=2)
    decision = freshness_policy(entry)
    assert decision.source == "stale"
    assert decision.age_hours is not None
    assert decision.age_hours > 2


def test_freshness_none() -> None:
    decision = freshness_policy(None)
    assert decision.source == "stale"
    assert decision.age_hours is None


def test_freshness_max_age_override() -> None:
    entry = CacheEntry(key="k", payload={"a": 1}, fetched_at=_past(3), max_age_hours=1)
    decision = freshness_policy(entry, max_age_hours=10)
    assert decision.source == "cache"


def test_freshness_degraded_fields() -> None:
    entry = CacheEntry(key="k", payload={"a": 1}, fetched_at=_past(10), max_age_hours=1)
    decision = freshness_policy(entry, degraded_fields=["a"])
    assert decision.source == "stale"
    assert decision.degraded_fields == ["a"]


# --- serve_or_cache -----------------------------------------------------------


def test_serve_or_cache_network_success(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    calls = {"n": 0}

    def fetch() -> dict:
        calls["n"] += 1
        return {"value": 7}

    payload, decision = serve_or_cache(cache, "k", fetch, max_age_hours=4)
    assert payload == {"value": 7}
    assert decision.source == "network"
    assert cache.get("k") is not None
    assert calls["n"] == 1


def test_serve_or_cache_fallback_cache(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    cache.put("k", {"value": 99}, max_age_hours=10)

    def fetch() -> dict:
        raise RuntimeError("network down")

    payload, decision = serve_or_cache(cache, "k", fetch, max_age_hours=10)
    assert payload == {"value": 99}
    assert decision.source == "cache"


def test_serve_or_cache_stale(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    cache.put("k", {"value": 99}, max_age_hours=1, fetched_at=_past(5))

    def fetch() -> dict:
        raise RuntimeError("network down")

    payload, decision = serve_or_cache(cache, "k", fetch, max_age_hours=1)
    assert payload == {"value": 99}
    assert decision.source == "stale"


def test_serve_or_cache_offline_flag(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    cache.put("k", {"value": 5}, max_age_hours=10)
    payload, decision = serve_or_cache(cache, "k", lambda: {"value": 6}, offline=True)
    assert payload == {"value": 5}
    assert decision.source == "cache"


def test_serve_or_cache_no_cache_raises(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)

    def fetch() -> dict:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        serve_or_cache(cache, "k", fetch)


def test_serve_or_cache_method(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    payload, decision = cache.serve_or_cache("m", lambda: {"ok": True}, max_age_hours=2)
    assert payload == {"ok": True}
    assert decision.source == "network"


def test_serve_or_cache_positional_swap(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    # key, cache, fetcher order should also work
    payload, decision = serve_or_cache("x", cache, lambda: {"x": 1})
    assert payload == {"x": 1}
    assert decision.source == "network"


# --- Adversarial --------------------------------------------------------------


def test_adversarial_corrupt_cache_file(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    cache.put("k", {"v": 1})
    # Corrupt the underlying file.
    path = cache._path_for("k")
    path.write_text("{not json", encoding="utf-8")
    assert cache.get("k") is None
    # serve_or_cache should not crash when cache is corrupt and network works.
    payload, decision = serve_or_cache(cache, "k", lambda: {"v": 2})
    assert payload == {"v": 2}
    assert decision.source == "network"


def test_adversarial_invalid_iso(tmp_path: Path) -> None:
    entry = CacheEntry(key="k", payload={"v": 1}, fetched_at="not-a-date", max_age_hours=1)
    decision = freshness_policy(entry)
    assert decision.source == "stale"
    assert decision.age_hours is None


def test_adversarial_huge_key(tmp_path: Path) -> None:
    cache = OfflineCache(tmp_path)
    long_key = "k" * 1000
    entry = cache.put(long_key, {"v": 1})
    assert cache.get(long_key) is not None
    assert entry.key == long_key[:512]


# --- REST smoke test ---------------------------------------------------------


def test_offline_rest_smoke(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(error)})

    client = TestClient(app)
    status = client.get("/api/career/offline/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is True

    put = client.post(
        "/api/career/offline/cache",
        json={"key": "demo", "payload": {"value": 3}, "max_age_hours": 5},
    )
    assert put.status_code == 200

    got = client.get("/api/career/offline/cache/demo")
    assert got.status_code == 200
    assert got.json()["payload"] == {"value": 3}

    deleted = client.delete("/api/career/offline/cache/demo")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_offline_rest_404(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    app = FastAPI()
    app.include_router(create_career_router(service))
    client = TestClient(app)
    resp = client.get("/api/career/offline/cache/nope")
    assert resp.status_code == 404
