"""Memoization helpers for the AI Arena."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _stable(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


@dataclass
class ArenaCache:
    enabled: bool = True
    version: str = "1"
    max_size: int = 256
    _store: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def make_key(self, request: Any, provider: str = "", model: str = "") -> str:
        payload = {
            "version": self.version,
            "provider": provider,
            "model": model,
            "task_type": getattr(request, "task_type", request),
            "input_payload": getattr(request, "input_payload", {}),
            "model_hint": getattr(request, "model_hint", None),
        }
        raw = _stable(payload)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Any:
        if not self.enabled:
            return None
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        if len(self._store) >= self.max_size:
            # Drop oldest entries (dict preserves insertion order).
            for old in list(self._store)[: max(1, self.max_size // 4)]:
                self._store.pop(old, None)
        self._store[key] = value

    def invalidate(self, version: str | None = None) -> None:
        if version is not None:
            self.version = version
        self._store.clear()

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    # Convenience aliases.
    def get_cached(self, key: str) -> Any:
        return self.get(key)

    def put(self, key: str, value: Any) -> None:
        self.set(key, value)

    @property
    def disabled(self) -> bool:
        return not self.enabled
