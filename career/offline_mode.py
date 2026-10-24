"""Local, expiring cache for Career reads (offline mode).

This module provides a small, dependency-free cache that can be used by the
Career workspace to keep "already seen" data available without network access:
offers, checklists, dossiers, and similar read models.  Everything stays on
the local machine; no secret or personal data is sent anywhere.

Public API:
    * :class:`CacheEntry` / :class:`OfflineDecision` dataclasses (contract).
    * :class:`OfflineCache` persistent key/value cache with TTL.
    * :func:`freshness_policy` decides whether a cached entry is fresh or stale.
    * :func:`serve_or_cache` implements the "network first, cache fallback"
      read strategy and returns the payload together with an
      :class:`OfflineDecision`.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

__all__ = [
    "CacheEntry",
    "OfflineCache",
    "OfflineDecision",
    "OfflineUnavailableError",
    "age_hours",
    "freshness_policy",
    "serve_or_cache",
]


# ---------------------------------------------------------------------------
# Contract dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """One cached read."""

    key: str
    payload: dict
    fetched_at: str  # ISO 8601
    max_age_hours: int

    def age_hours(self, *, now: Any = None) -> float | None:
        return _age_hours(self, now=now)

    def is_fresh(self, *, now: Any = None) -> bool:
        age = _age_hours(self, now=now)
        if age is None:
            return False
        return age <= float(self.max_age_hours)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "payload": self.payload,
            "fetched_at": self.fetched_at,
            "max_age_hours": int(self.max_age_hours),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "CacheEntry":
        if not isinstance(data, dict):
            raise ValueError("cache entry must be an object")
        key = str(data.get("key") or "")
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            payload = {"value": payload}
        try:
            max_age = int(data.get("max_age_hours", 24))
        except (TypeError, ValueError):
            max_age = 24
        if max_age < 0:
            max_age = 0
        fetched_at = str(data.get("fetched_at") or _now_iso())
        return cls(key=key, payload=payload, fetched_at=fetched_at, max_age_hours=max_age)


@dataclass
class OfflineDecision:
    """Outcome of a (possibly cached) read."""

    source: Literal["network", "cache", "stale"]
    age_hours: float | None
    degraded_fields: list[str] = field(default_factory=list)


class OfflineUnavailableError(RuntimeError):
    """Raised when no network and no usable cache entry exist."""


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="microseconds")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _coerce_now(value: Any) -> datetime:
    if value is None:
        return _now()
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    parsed = _parse_datetime(value)
    if parsed is None:
        return _now()
    return parsed


def _age_hours(entry: CacheEntry, *, now: Any = None) -> float | None:
    if entry is None:
        return None
    fetched = _parse_datetime(getattr(entry, "fetched_at", None))
    if fetched is None:
        return None
    current = _coerce_now(now)
    delta = (current - fetched).total_seconds() / 3600.0
    if delta < 0:
        delta = 0.0
    return float(delta)


def age_hours(entry: Any, *, now: Any = None) -> float | None:
    """Public helper: age in hours of a cache entry (or None)."""
    if entry is None:
        return None
    if hasattr(entry, "to_dict") and not hasattr(entry, "fetched_at"):
        try:
            entry = CacheEntry.from_dict(entry)
        except Exception:
            return None
    try:
        return _age_hours(entry, now=now)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cache store
# ---------------------------------------------------------------------------


def _safe_key(key: Any) -> str:
    text = str(key if key is not None else "").strip()
    if not text:
        raise ValueError("cache key must be a non-empty string")
    if len(text) > 512:
        text = text[:512]
    return text


def _storage_name(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"


class OfflineCache:
    """Persistent, TTL-based local cache.

    The cache stores one JSON file per key under ``cache_dir``.  All
    operations are synchronous and local; there is no network access.
    """

    def __init__(
        self,
        cache_dir: Any = None,
        *,
        base_dir: Any = None,
        directory: Any = None,
        root: Any = None,
        path: Any = None,
        namespace: str | None = None,
    ):
        raw = cache_dir if cache_dir is not None else base_dir
        if raw is None:
            raw = directory if directory is not None else root
        if raw is None:
            raw = path
        if raw is None:
            raw = Path.cwd() / "offline_cache"
        self.cache_dir = Path(raw).expanduser()
        if namespace:
            self.cache_dir = self.cache_dir / str(namespace)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            os.chmod(self.cache_dir, 0o700)
        except OSError:
            pass

    # -- core CRUD ---------------------------------------------------------

    def _path_for(self, key: str) -> Path:
        return self.cache_dir / _storage_name(key)

    def put(
        self,
        key: Any,
        payload: Any = None,
        *,
        max_age_hours: Any = None,
        fetched_at: Any = None,
        ttl_hours: Any = None,
        entry: CacheEntry | None = None,
        **kwargs: Any,
    ) -> CacheEntry:
        """Store ``payload`` under ``key`` and return the entry."""
        key_text = _safe_key(key)
        if entry is not None:
            new_entry = CacheEntry(
                key=key_text,
                payload=dict(entry.payload) if isinstance(entry.payload, dict) else {"value": entry.payload},
                fetched_at=str(entry.fetched_at or _now_iso()),
                max_age_hours=int(entry.max_age_hours if entry.max_age_hours is not None else 24),
            )
        else:
            if max_age_hours is None:
                max_age_hours = kwargs.pop("ttl", None)
            if max_age_hours is None:
                max_age_hours = ttl_hours
            if max_age_hours is None:
                max_age_hours = kwargs.get("max_age", 24)
            try:
                max_age = int(max_age_hours)
            except (TypeError, ValueError):
                max_age = 24
            if max_age < 0:
                max_age = 0
            if not isinstance(payload, dict):
                if isinstance(payload, (list, tuple)):
                    payload = {"items": list(payload)}
                elif payload is None:
                    payload = {}
                else:
                    payload = {"value": payload}
            fetched = fetched_at if fetched_at is not None else kwargs.get("fetched_at")
            if fetched is None:
                fetched = _now_iso()
            new_entry = CacheEntry(
                key=key_text,
                payload=dict(payload),
                fetched_at=str(fetched),
                max_age_hours=max_age,
            )
        # Persist.
        path = self._path_for(key_text)
        try:
            path.write_text(
                json.dumps(new_entry.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
        except OSError:
            pass
        return new_entry

    # Aliases
    def set(self, *args: Any, **kwargs: Any) -> CacheEntry:
        return self.put(*args, **kwargs)

    def add(self, *args: Any, **kwargs: Any) -> CacheEntry:
        return self.put(*args, **kwargs)

    def store(self, *args: Any, **kwargs: Any) -> CacheEntry:
        return self.put(*args, **kwargs)

    def save(self, *args: Any, **kwargs: Any) -> CacheEntry:
        return self.put(*args, **kwargs)

    def put_entry(self, entry: CacheEntry, **kwargs: Any) -> CacheEntry:
        return self.put(entry.key, entry.payload, max_age_hours=entry.max_age_hours, fetched_at=entry.fetched_at, **kwargs)

    def get(self, key: Any) -> CacheEntry | None:
        try:
            key_text = _safe_key(key)
        except ValueError:
            return None
        path = self._path_for(key_text)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        try:
            return CacheEntry.from_dict(data)
        except Exception:
            return None

    # Aliases for reads
    def get_entry(self, key: Any) -> CacheEntry | None:
        return self.get(key)

    def read(self, key: Any) -> CacheEntry | None:
        return self.get(key)

    def load(self, key: Any) -> CacheEntry | None:
        return self.get(key)

    def fetch(self, key: Any) -> CacheEntry | None:
        return self.get(key)

    def has(self, key: Any) -> bool:
        return self.get(key) is not None

    def exists(self, key: Any) -> bool:
        return self.has(key)

    def contains(self, key: Any) -> bool:
        return self.has(key)

    def __contains__(self, key: Any) -> bool:
        return self.has(key)

    def __getitem__(self, key: Any) -> CacheEntry:
        entry = self.get(key)
        if entry is None:
            raise KeyError(key)
        return entry

    def __setitem__(self, key: Any, value: Any) -> None:
        if isinstance(value, CacheEntry):
            self.put_entry(value)
        elif isinstance(value, tuple) and len(value) >= 2:
            self.put(key, value[0], max_age_hours=value[1] if len(value) > 1 else 24)
        elif isinstance(value, dict) and "payload" in value and "fetched_at" in value:
            self.put(
                key,
                value.get("payload", {}),
                max_age_hours=value.get("max_age_hours", value.get("max_age", 24)),
                fetched_at=value.get("fetched_at"),
            )
        else:
            self.put(key, value)

    def delete(self, key: Any) -> bool:
        try:
            key_text = _safe_key(key)
        except ValueError:
            return False
        path = self._path_for(key_text)
        try:
            if path.is_file():
                path.unlink()
                return True
        except OSError:
            return False
        return False

    def remove(self, key: Any) -> bool:
        return self.delete(key)

    def evict(self, key: Any) -> bool:
        return self.delete(key)

    def discard(self, key: Any) -> None:
        self.delete(key)

    def clear(self) -> int:
        count = 0
        try:
            for path in self.cache_dir.glob("*.json"):
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    pass
        except OSError:
            pass
        return count

    def list_keys(self) -> list[str]:
        keys: list[str] = []
        try:
            for path in self.cache_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    key = data.get("key")
                    if isinstance(key, str) and key:
                        keys.append(key)
                except Exception:
                    continue
        except OSError:
            pass
        return keys

    def keys(self) -> list[str]:
        return self.list_keys()

    def entries(self) -> list[CacheEntry]:
        result: list[CacheEntry] = []
        for key in self.list_keys():
            entry = self.get(key)
            if entry is not None:
                result.append(entry)
        return result

    def all(self) -> list[CacheEntry]:
        return self.entries()

    def values(self) -> list[CacheEntry]:
        return self.entries()

    def items(self) -> list[tuple[str, CacheEntry]]:
        return [(e.key, e) for e in self.entries()]

    def __len__(self) -> int:
        return len(self.list_keys())

    def __iter__(self) -> Iterable[str]:
        return iter(self.list_keys())

    def serve_or_cache(self, *args: Any, **kwargs: Any) -> tuple[Any, OfflineDecision]:
        return serve_or_cache(self, *args, **kwargs)


# ---------------------------------------------------------------------------
# Freshness policy
# ---------------------------------------------------------------------------


def freshness_policy(
    entry: Any,
    *,
    now: Any = None,
    max_age_hours: Any = None,
    degraded_fields: Any = None,
    stale_fields: Any = None,
    fields: Any = None,
    **kwargs: Any,
) -> OfflineDecision:
    """Return an :class:`OfflineDecision` for ``entry``.

    ``entry`` may be a :class:`CacheEntry`, a dict, or ``None``.
    """
    if entry is None:
        df = degraded_fields if degraded_fields is not None else (stale_fields if stale_fields is not None else fields)
        if df is None:
            df = kwargs.get("degraded_fields", [])
        return OfflineDecision(
            source="stale",
            age_hours=None,
            degraded_fields=list(df or []),
        )
    if isinstance(entry, dict):
        try:
            entry = CacheEntry.from_dict(entry)
        except Exception:
            return OfflineDecision(source="stale", age_hours=None, degraded_fields=list(degraded_fields or []))

    if max_age_hours is None:
        max_age_hours = getattr(entry, "max_age_hours", 24)
    try:
        ma = float(max_age_hours)
    except (TypeError, ValueError):
        ma = float(getattr(entry, "max_age_hours", 24) or 24)
    age = _age_hours(entry, now=now)

    if degraded_fields is None:
        degraded_fields = stale_fields if stale_fields is not None else fields
    if degraded_fields is None:
        degraded_fields = kwargs.get("degraded_fields", [])
    degraded_list = list(degraded_fields or [])

    if age is not None and age <= ma:
        return OfflineDecision(source="cache", age_hours=age, degraded_fields=[])
    return OfflineDecision(source="stale", age_hours=age, degraded_fields=degraded_list)


# ---------------------------------------------------------------------------
# serve_or_cache
# ---------------------------------------------------------------------------


def _resolve_serve_args(
    first: Any,
    second: Any,
    third: Any,
    *,
    cache: Any,
    key: Any,
    fetcher: Any,
) -> tuple[Any, Any, Any]:
    if cache is None:
        # Case A: first is cache-like
        if _looks_like_cache(first) and not isinstance(first, str):
            cache = first
            if isinstance(second, str):
                key = key if key is not None else second
                fetcher = fetcher if fetcher is not None else third
            elif callable(second):
                fetcher = fetcher if fetcher is not None else second
                key = key if key is not None else third
            else:
                key = key if key is not None else third
                fetcher = fetcher if fetcher is not None else second
        # Case B: second is cache-like (first=key, second=cache)
        elif _looks_like_cache(second):
            key = key if key is not None else (first if isinstance(first, str) else key)
            cache = second
            fetcher = fetcher if fetcher is not None else third
            if key is None and isinstance(first, str):
                key = first
        # Case C: third is cache-like (first=key, second=fetcher, third=cache)
        elif _looks_like_cache(third):
            if isinstance(first, str):
                key = key if key is not None else first
            fetcher = fetcher if fetcher is not None else (second if callable(second) else fetcher)
            cache = third
        # Case D: first is str key, second callable fetcher, no cache positional -> error unless cache kw
        else:
            if isinstance(first, str):
                key = key if key is not None else first
            if callable(second) and fetcher is None:
                fetcher = second
            cache = first if _looks_like_cache(first) else cache
    if key is None and isinstance(first, str):
        key = first
    if key is None:
        raise ValueError("cache key is required")
    if cache is None:
        raise ValueError("cache is required")
    return cache, key, fetcher


def _looks_like_cache(obj: Any) -> bool:
    if obj is None:
        return False
    if isinstance(obj, OfflineCache):
        return True
    if isinstance(obj, (str, Path)):
        return True
    if hasattr(obj, "get") and hasattr(obj, "put"):
        return True
    return False


def _coerce_cache(cache: Any) -> OfflineCache:
    if isinstance(cache, OfflineCache):
        return cache
    if isinstance(cache, (str, Path)):
        return OfflineCache(cache)
    if hasattr(cache, "get") and hasattr(cache, "put"):
        # Duck-typed cache; wrap lightly by delegating? Return as-is via adapter.
        return cache  # type: ignore[return-value]
    return OfflineCache(cache)


def serve_or_cache(
    first: Any = None,
    second: Any = None,
    third: Any = None,
    *,
    cache: Any = None,
    key: Any = None,
    fetcher: Any = None,
    fetch: Any = None,
    loader: Any = None,
    max_age_hours: Any = None,
    ttl_hours: Any = None,
    now: Any = None,
    offline: bool = False,
    force_refresh: bool = False,
    force_network: bool = False,
    degraded_fields: Any = None,
    stale_fields: Any = None,
    **kwargs: Any,
) -> tuple[Any, OfflineDecision]:
    """Network-first read with cache fallback.

    Returns ``(payload, decision)``.
    """
    if fetch is not None:
        fetcher = fetch
    if loader is not None:
        fetcher = loader
    if max_age_hours is None:
        max_age_hours = ttl_hours
    if max_age_hours is None:
        max_age_hours = kwargs.get("max_age_hours", kwargs.get("ttl", 24))
    try:
        max_age = int(max_age_hours)
    except (TypeError, ValueError):
        max_age = 24
    if max_age < 0:
        max_age = 0

    cache_obj, key_text, fetch_callable = _resolve_serve_args(
        first, second, third, cache=cache, key=key, fetcher=fetcher
    )
    cache_obj = _coerce_cache(cache_obj)
    key_text = _safe_key(key_text)

    degraded = degraded_fields if degraded_fields is not None else stale_fields
    if degraded is None:
        degraded = kwargs.get("degraded_fields", [])

    network_error: Exception | None = None

    if (not offline) and callable(fetch_callable):
        try:
            payload = fetch_callable()
            if not isinstance(payload, dict):
                if isinstance(payload, (list, tuple)):
                    payload = {"items": list(payload)}
                elif payload is None:
                    payload = {}
                else:
                    payload = {"value": payload}
            cache_obj.put(key_text, payload, max_age_hours=max_age, fetched_at=_now_iso())
            return payload, OfflineDecision(source="network", age_hours=0.0, degraded_fields=[])
        except Exception as exc:  # noqa: BLE001 - fallback to cache
            network_error = exc

    entry = cache_obj.get(key_text)
    if entry is not None:
        decision = freshness_policy(
            entry,
            now=now,
            max_age_hours=max_age,
            degraded_fields=degraded,
        )
        return entry.payload, decision

    if network_error is not None:
        raise network_error
    raise OfflineUnavailableError(f"no cached value for key {key_text!r}")
