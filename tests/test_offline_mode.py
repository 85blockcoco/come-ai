"""Tests SPEC-032 : cache hors-ligne local et bandeau d'état.

Toutes les données viennent de ``tests/fixtures/offline_synthetic.json``.
Aucun accès réseau n'est effectué : les « network readers » sont des lambdas.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from career.offline_mode import (
    CACHE_FILE_NAME,
    CACHE_SCHEMA_VERSION,
    DEFAULT_MAX_AGE_HOURS,
    FRESHNESS_POLICY_HOURS,
    MAX_AGE_ENV,
    MAX_PAYLOAD_BYTES,
    CacheEntry,
    OfflineCache,
    OfflineCacheError,
    OfflineDataUnavailable,
    OfflineDecision,
    decision_for_entry,
    entry_age_hours,
    freshness_policy,
    normalize_key,
    offline_banner,
    serve_or_cache,
)
from career.service import DELETE_CONFIRMATION, SCHEMA_VERSION, CareerService
from come_ai_web import create_app

FIXTURE_PATH = Path(__file__).with_name("fixtures") / "offline_synthetic.json"
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def synthetic() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def make_cache(tmp_path: Path, **kwargs: Any) -> OfflineCache:
    kwargs.setdefault("clock", lambda: NOW)
    kwargs.setdefault("environ", {})
    return OfflineCache(tmp_path / "offline", **kwargs)


@contextmanager
def career_client(tmp_path: Path) -> Iterator[tuple[CareerService, TestClient]]:
    service = CareerService(tmp_path, curated_sources=())
    app = create_app(base_dir=tmp_path, career_override=service)
    with TestClient(app) as client:
        yield service, client


# ---------------------------------------------------------------------------
# Politique de fraîcheur
# ---------------------------------------------------------------------------
def test_freshness_policy_defaults_per_kind() -> None:
    assert freshness_policy("jobs") == 6
    assert freshness_policy("checklists") == 72
    assert freshness_policy("applications") == 12
    assert freshness_policy("profile") == 24
    assert freshness_policy("un type inconnu") == DEFAULT_MAX_AGE_HOURS
    assert freshness_policy("") == DEFAULT_MAX_AGE_HOURS
    assert FRESHNESS_POLICY_HOURS["default"] == DEFAULT_MAX_AGE_HOURS


def test_freshness_policy_env_only_for_default_window() -> None:
    assert freshness_policy("custom", environ={MAX_AGE_ENV: "12"}) == 12
    assert freshness_policy("jobs", environ={MAX_AGE_ENV: "12"}) == 6
    # A malformed shell export must not break the local app.
    assert freshness_policy("custom", environ={MAX_AGE_ENV: "abc"}) == DEFAULT_MAX_AGE_HOURS
    assert freshness_policy("custom", environ={MAX_AGE_ENV: "0"}) == DEFAULT_MAX_AGE_HOURS
    assert freshness_policy("custom", environ={MAX_AGE_ENV: "-3"}) == DEFAULT_MAX_AGE_HOURS


def test_freshness_policy_explicit_overrides_win_and_are_validated() -> None:
    assert freshness_policy("jobs", overrides={"jobs": 48}) == 48
    with pytest.raises(OfflineCacheError):
        freshness_policy("jobs", overrides={"jobs": 0})
    with pytest.raises(OfflineCacheError):
        freshness_policy("jobs", overrides={"jobs": True})


# ---------------------------------------------------------------------------
# Lecture / écriture du cache
# ---------------------------------------------------------------------------
def test_cache_roundtrip_is_persisted_privately(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    entry = cache.put("jobs:fr", {"jobs": synthetic()["jobs"]}, kind="jobs")

    assert isinstance(entry, CacheEntry)
    assert entry.max_age_hours == 6
    assert entry.fetched_at == NOW.isoformat()
    assert CacheEntry.from_dict(entry.to_dict()) == entry
    assert cache.get("jobs:fr") == entry

    reopened = OfflineCache(tmp_path / "offline")
    assert reopened.get("jobs:fr") == entry

    cache_file = tmp_path / "offline" / CACHE_FILE_NAME
    assert stat.S_IMODE(os.stat(cache_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "offline").st_mode) == 0o700
    raw = json.loads(cache_file.read_text(encoding="utf-8"))
    assert raw["schema_version"] == CACHE_SCHEMA_VERSION
    assert "jobs:fr" in raw["entries"]


def test_cache_put_defaults_to_policy_and_accepts_iso_timestamp(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    entry = cache.put(
        "checklists:app-1",
        {"checklist": synthetic()["checklists"]},
        kind="checklists",
        fetched_at="2026-10-20T08:00:00Z",
    )
    assert entry.max_age_hours == 72
    assert entry.fetched_at == "2026-10-20T08:00:00+00:00"


def test_cache_age_and_freshness_boundary(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put("profile:main", {"skills": ["Excel"]}, max_age_hours=2)

    entry = cache.get("profile:main")
    assert entry is not None
    exact = decision_for_entry(entry, now=NOW + timedelta(hours=2))
    assert exact.source == "cache"
    assert exact.degraded_fields == []

    stale = decision_for_entry(entry, now=NOW + timedelta(hours=2, minutes=30))
    assert stale.source == "stale"
    assert stale.age_hours == 2.5
    assert stale.degraded_fields == ["skills"]


def test_future_timestamp_is_clamped_to_zero_age(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put(
        "profile:main",
        {"skills": ["Excel"]},
        max_age_hours=1,
        fetched_at=NOW + timedelta(hours=10),
    )
    entry = cache.get("profile:main")
    assert entry is not None
    assert entry_age_hours(entry, now=NOW) == 0.0
    assert decision_for_entry(entry, now=NOW).source == "cache"


def test_entry_limit_keeps_the_newest_entries(tmp_path: Path) -> None:
    cache = make_cache(tmp_path, max_entries=3)
    for index in range(5):
        cache.put(
            f"k:{index}",
            {"index": index},
            max_age_hours=5,
            fetched_at=NOW + timedelta(minutes=index),
        )
    keys = [item["key"] for item in cache.summaries(now=NOW)]
    assert keys == ["k:2", "k:3", "k:4"]


def test_inventory_never_returns_payloads(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put("profile:main", {"skills": ["Excel"]}, max_age_hours=5)
    summary = cache.summaries(now=NOW)[0]
    assert summary["key"] == "profile:main"
    assert summary["stale"] is False
    assert summary["field_count"] == 1
    assert "payload" not in summary


def test_delete_and_clear(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put("a:1", {"value": 1}, max_age_hours=1)
    cache.put("b:2", {"value": 2}, max_age_hours=1)
    assert cache.delete("a:1") is True
    assert cache.delete("a:1") is False
    assert cache.clear() == 1
    assert cache.status(now=NOW)["entry_count"] == 0


# ---------------------------------------------------------------------------
# serve_or_cache
# ---------------------------------------------------------------------------
def test_serve_or_cache_prefers_network_and_populates_cache(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    calls: list[int] = []

    def reader() -> dict[str, Any]:
        calls.append(1)
        return {"jobs": synthetic()["jobs"]}

    result = serve_or_cache("jobs:fr", cache=cache, reader=reader, kind="jobs", now=NOW)
    assert calls == [1]
    assert result.decision.source == "network"
    assert result.decision.age_hours == 0.0
    assert result.decision.degraded_fields == []
    assert cache.get("jobs:fr") is not None


def test_serve_or_cache_offline_never_calls_reader(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put("profile:main", {"display_name": "Camille Synthétique"}, max_age_hours=5)
    calls: list[int] = []

    def reader() -> dict[str, Any]:
        calls.append(1)
        return {"display_name": "Ne doit pas être lu"}

    result = serve_or_cache(
        "profile:main", cache=cache, reader=reader, network_ok=False, kind="profile", now=NOW
    )
    assert calls == []
    assert result.payload == {"display_name": "Camille Synthétique"}
    assert result.decision.source == "cache"


def test_serve_or_cache_falls_back_when_reader_fails(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put("jobs:fr", {"jobs": synthetic()["jobs"]}, kind="jobs")

    def broken() -> dict[str, Any]:
        raise TimeoutError("réseau indisponible")

    result = serve_or_cache("jobs:fr", cache=cache, reader=broken, kind="jobs", now=NOW)
    assert result.decision.source == "cache"
    assert result.payload["jobs"][0]["company"] == "Banque Synthétique"


def test_serve_or_cache_reports_stale_after_reader_failure(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    cache.put(
        "checklists:app-1",
        {"checked": ["cv_reviewed"], "updated": False},
        max_age_hours=1,
        fetched_at=NOW - timedelta(hours=5),
    )

    def broken() -> dict[str, Any]:
        raise ConnectionError("hors-ligne")

    result = serve_or_cache(
        "checklists:app-1", cache=cache, reader=broken, kind="checklists", now=NOW
    )
    assert result.decision.source == "stale"
    assert result.decision.age_hours == 5.0
    assert result.decision.degraded_fields == ["checked", "updated"]
    banner = offline_banner(result.decision)
    assert banner["offline"] is True
    assert banner["level"] == "stale"
    assert "2 champ(s)" in banner["message"]


def test_serve_or_cache_without_copy_raises_honest_error(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    with pytest.raises(OfflineDataUnavailable):
        serve_or_cache("jobs:missing", cache=cache, network_ok=False, now=NOW)


def test_serve_or_cache_survives_unwritable_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = make_cache(tmp_path)

    def broken_put(*_: Any, **__: Any) -> CacheEntry:
        raise OSError("disque plein")

    monkeypatch.setattr(cache, "put", broken_put)
    result = serve_or_cache(
        "jobs:fr", cache=cache, reader=lambda: {"jobs": synthetic()["jobs"]}, now=NOW
    )
    assert result.decision.source == "network"


def test_serve_or_cache_rejects_non_object_reader_output(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    with pytest.raises(OfflineCacheError):
        serve_or_cache("jobs:fr", cache=cache, reader=lambda: ["pas", "un", "objet"])


def test_banner_for_online_read() -> None:
    banner = offline_banner(
        OfflineDecision(source="network", age_hours=0.0, degraded_fields=[])
    )
    assert banner == {
        "offline": False,
        "level": "online",
        "source": "network",
        "age_hours": 0.0,
        "degraded_fields": [],
        "message": "Données actualisées à l'instant.",
    }


# ---------------------------------------------------------------------------
# Adversarial : clés, payloads, fichiers corrompus
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "../escape",
        "a/b",
        "..",
        "Uppercase",
        "accentué",
        "line\nbreak",
        "x" * 121,
        " leading-space",
    ],
)
def test_adversarial_keys_are_rejected(tmp_path: Path, bad_key: str) -> None:
    cache = make_cache(tmp_path)
    with pytest.raises(OfflineCacheError):
        normalize_key(bad_key)
    with pytest.raises(OfflineCacheError):
        cache.put(bad_key, {"value": 1}, max_age_hours=1)
    assert not (tmp_path / "offline").exists()


@pytest.mark.parametrize(
    "bad_payload",
    [
        {},
        ["not", "a", "dict"],
        {"object": object()},
        {"nan": float("nan")},
    ],
)
def test_adversarial_payloads_are_rejected(
    tmp_path: Path, bad_payload: Any
) -> None:
    cache = make_cache(tmp_path)
    with pytest.raises(OfflineCacheError):
        cache.put("jobs:fr", bad_payload, max_age_hours=1)


def test_oversized_payload_is_rejected(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    with pytest.raises(OfflineCacheError):
        cache.put("jobs:fr", {"blob": "x" * MAX_PAYLOAD_BYTES}, max_age_hours=1)


def test_invalid_max_age_is_rejected(tmp_path: Path) -> None:
    cache = make_cache(tmp_path)
    for bad in (0, -1, True, 24 * 366, "6"):
        with pytest.raises(OfflineCacheError):
            cache.put("jobs:fr", {"value": 1}, max_age_hours=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        "[]",
        '{"schema_version": 999, "entries": {}}',
        '{"schema_version": 1}',
        '{"schema_version": 1, "entries": []}',
    ],
)
def test_corrupted_cache_file_is_ignored(tmp_path: Path, content: str) -> None:
    directory = tmp_path / "offline"
    directory.mkdir()
    (directory / CACHE_FILE_NAME).write_text(content, encoding="utf-8")
    cache = make_cache(tmp_path)
    assert cache.get("jobs:fr") is None
    status = cache.status(now=NOW)
    assert status["corrupted"] is True
    assert status["entry_count"] == 0
    # A write repairs the file instead of crashing.
    cache.put("jobs:fr", {"value": 1}, max_age_hours=1)
    assert cache.get("jobs:fr") is not None


def test_tampered_entries_are_dropped_individually(tmp_path: Path) -> None:
    directory = tmp_path / "offline"
    directory.mkdir()
    good = {
        "key": "jobs:fr",
        "payload": {"jobs": synthetic()["jobs"]},
        "fetched_at": NOW.isoformat(),
        "max_age_hours": 5,
    }
    document = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "entries": {
            "jobs:fr": good,
            "bool": {
                "key": "bool",
                "payload": {"x": 1},
                "fetched_at": NOW.isoformat(),
                "max_age_hours": True,
            },
            "moved": dict(good, key="jobs:other"),
            "not-an-object": "payload",
            "bad-date": dict(good, key="bad-date", fetched_at="hier"),
        },
    }
    (directory / CACHE_FILE_NAME).write_text(
        json.dumps(document), encoding="utf-8"
    )

    cache = make_cache(tmp_path)
    assert cache.get("jobs:fr") is not None
    for key in ("bool", "moved", "not-an-object", "bad-date"):
        assert cache.get(key) is None
    status = cache.status(now=NOW)
    assert status["entry_count"] == 1
    assert status["dropped_entries"] == 4
    assert status["corrupted"] is False


def test_oversized_cache_file_is_ignored(tmp_path: Path) -> None:
    directory = tmp_path / "offline"
    directory.mkdir()
    (directory / CACHE_FILE_NAME).write_text(
        "x" * (8 * 1024 * 1024 + 1), encoding="utf-8"
    )
    cache = make_cache(tmp_path)
    assert cache.get("jobs:fr") is None
    assert cache.status(now=NOW)["corrupted"] is True


# ---------------------------------------------------------------------------
# API REST via le vrai create_app()
# ---------------------------------------------------------------------------
def test_offline_http_smoke_and_banner(tmp_path: Path) -> None:
    fixture = synthetic()
    with career_client(tmp_path) as (_, client):
        status = client.get("/api/career/offline/status")
        assert status.status_code == 200
        payload = status.json()
        assert payload["storage"] == "local_user_dir"
        assert payload["entry_count"] == 0
        assert payload["policy_hours"]["checklists"] == 72
        assert not (tmp_path / "career_data" / "offline").exists()

        assert client.put(
            "/api/career/profile",
            json={"display_name": fixture["profile"]["display_name"], "skills": "Excel"},
        ).status_code == 200

        online = client.get("/api/career/offline/read/profile/profile:main?network=true")
        assert online.status_code == 200
        online_payload = online.json()
        assert online_payload["decision"]["source"] == "network"
        assert online_payload["banner"]["offline"] is False
        assert online_payload["automatic_submission"] is False
        assert online_payload["payload"]["skills"] == "Excel"

        client.put("/api/career/profile", json={"skills": "Excel, Python"})

        offline = client.get("/api/career/offline/read/profile/profile:main?network=false")
        assert offline.status_code == 200
        offline_payload = offline.json()
        assert offline_payload["decision"]["source"] == "cache"
        assert offline_payload["payload"]["skills"] == "Excel"
        assert offline_payload["banner"]["offline"] is True
        assert offline_payload["banner"]["level"] == "cached"
        assert offline_payload["banner"]["source"] == "cache"
        assert offline_payload["banner"]["age_hours"] >= 0.0

        entry = client.get("/api/career/offline/cache/profile:main")
        assert entry.status_code == 200
        assert entry.json()["entry"]["key"] == "profile:main"

        inventory = client.get("/api/career/offline/cache").json()["entries"]
        assert [item["key"] for item in inventory] == ["profile:main"]
        assert "payload" not in inventory[0]

        assert client.delete("/api/career/offline/cache/profile:main").json() == {"deleted": True}
        assert client.get("/api/career/offline/cache/profile:main").status_code == 404


def test_offline_http_manual_entry_and_stale_banner(tmp_path: Path) -> None:
    fixture = synthetic()
    with career_client(tmp_path) as (_, client):
        stored = client.post(
            "/api/career/offline/cache",
            json={
                "key": "jobs:fr",
                "kind": "jobs",
                "payload": {"jobs": fixture["jobs"]},
                "max_age_hours": 1,
                "fetched_at": fixture["fetched_at"],
            },
        )
        assert stored.status_code == 201
        assert stored.json()["entry"]["max_age_hours"] == 1

        stale = client.get("/api/career/offline/read/jobs/jobs:fr?network=false")
        assert stale.status_code == 200
        body = stale.json()
        assert body["decision"]["source"] == "stale"
        assert body["decision"]["degraded_fields"] == ["jobs"]
        assert body["banner"]["level"] == "stale"
        assert body["payload"]["jobs"][0]["company"] == "Banque Synthétique"

        cleared = client.request("DELETE", "/api/career/offline/cache")
        assert cleared.status_code == 200
        assert cleared.json() == {"deleted": 1}


def test_offline_http_missing_copy_is_503(tmp_path: Path) -> None:
    with career_client(tmp_path) as (_, client):
        response = client.get("/api/career/offline/read/jobs/jobs:missing?network=false")
        assert response.status_code == 503
        assert "Aucune copie locale" in response.json()["detail"]


def test_offline_http_rejects_adversarial_requests(tmp_path: Path) -> None:
    with career_client(tmp_path) as (_, client):
        bad_key = client.post(
            "/api/career/offline/cache",
            json={"key": "../escape", "payload": {"value": 1}},
        )
        assert bad_key.status_code == 400

        bad_kind = client.get("/api/career/offline/read/evil/jobs:fr?network=false")
        assert bad_kind.status_code == 400

        bad_payload = client.post(
            "/api/career/offline/cache",
            json={"key": "jobs:fr", "payload": {"blob": "x" * (MAX_PAYLOAD_BYTES + 1)}},
        )
        assert bad_payload.status_code == 400

        assert not (tmp_path / "escape").exists()
        assert not (tmp_path / "offline" / ".." / "escape").exists()


def test_offline_http_respects_career_schema_version(tmp_path: Path) -> None:
    with career_client(tmp_path) as (service, client):
        connection = sqlite3.connect(service.db_path)
        try:
            before = connection.execute("PRAGMA user_version").fetchone()[0]
            assert before == SCHEMA_VERSION
            client.get("/api/career/offline/status")
            client.get("/api/career/offline/read/jobs/jobs:fr?network=true")
            after = connection.execute("PRAGMA user_version").fetchone()[0]
        finally:
            connection.close()
        assert after == before


def test_offline_cache_is_erased_by_privacy_reset(tmp_path: Path) -> None:
    with career_client(tmp_path) as (_, client):
        client.post(
            "/api/career/offline/cache",
            json={"key": "profile:main", "payload": {"display_name": "Camille Synthétique"}},
        )
        assert client.get("/api/career/offline/status").json()["entry_count"] == 1

        reset = client.request(
            "DELETE", "/api/career/data", json={"confirmation": DELETE_CONFIRMATION}
        )
        assert reset.status_code == 200
        assert client.get("/api/career/offline/status").json()["entry_count"] == 0
