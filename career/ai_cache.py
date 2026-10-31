"""Simple AI response cache (N100-I06)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class AICache:
    def __init__(self, path: str | Path | None = None, ttl_sec: float = 3600.0) -> None:
        if path is None:
            path = Path(".") / "ai_cache.json"
        self.path = Path(path)
        self.ttl_sec = ttl_sec
        self._data: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, TypeError):
                self._data = {}

    def _key(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def get(self, prompt: str) -> Any | None:
        entry = self._data.get(self._key(prompt))
        if not entry:
            return None
        if time.time() - entry.get("ts", 0) > self.ttl_sec:
            del self._data[self._key(prompt)]
            self._save()
            return None
        return entry.get("value")

    def set(self, prompt: str, value: Any) -> None:
        self._data[self._key(prompt)] = {"value": value, "ts": time.time()}
        self._save()

    def invalidate(self, prompt: str) -> None:
        self._data.pop(self._key(prompt), None)
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def clear(self) -> None:
        self._data = {}
        self._save()