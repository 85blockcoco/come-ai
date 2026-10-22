"""Memoization cache for AI Arena responses."""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from .models import IAResponse


class ArenaCache:
    def __init__(self, *, enabled: bool = True, version: str = "1") -> None:
        self.enabled = bool(enabled)
        self.version = str(version)
        self._store: dict[str, IAResponse] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def make_key(self, request: Any, provider: str, model: str) -> str:
        payload = {
            "task_type": getattr(request, "task_type", None),
            "input_payload": getattr(request, "input_payload", {}),
            "model_hint": getattr(request, "model_hint", None),
            "provider": provider,
            "model": model,
            "version": self.version,
        }
        raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> IAResponse | None:
        if not self.enabled:
            return None
        with self._lock:
            value = self._store.get(key)
            if value is None:
                self._misses += 1
                return None
            self._hits += 1
            # Return a copy-ish (dataclass) with cached=True
            try:
                return IAResponse(
                    provider=value.provider,
                    model=value.model,
                    content=dict(value.content) if isinstance(value.content, dict) else value.content,
                    latency_ms=value.latency_ms,
                    cached=True,
                )
            except Exception:
                return value

    def set(self, key: str, response: IAResponse) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._store[key] = response

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "version": self.version,
                "size": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
            }

    # Convenience
    def invalidate(self) -> None:
        self.clear()
