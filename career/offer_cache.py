"""Local offer cache with TTL invalidation (N100-A09)."""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_TTL_SECONDS = 7 * 24 * 3600


class OfferCache:
    def __init__(self, path: str | Path | None = None, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self._data: dict[str, dict[str, Any]] = {}
        if self.path and self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, TypeError):
                self._data = {}

    @staticmethod
    def _key(offer: Any) -> str:
        identity = offer.get("url") or offer.get("id") or offer.get("title", "")
        raw = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def put(self, offer: dict[str, Any]) -> str:
        key = self._key(offer)
        self._data[key] = {"offer": dict(offer), "ts": datetime.datetime.now(datetime.timezone.utc).timestamp()}
        self._flush()
        return key

    def get(self, offer: dict[str, Any]) -> dict[str, Any] | None:
        entry = self._data.get(self._key(offer))
        if entry is None:
            return None
        if self._expired(entry["ts"]):
            self._data.pop(self._key(offer), None)
            self._flush()
            return None
        return entry["offer"]

    def _expired(self, ts: float) -> bool:
        return (datetime.datetime.now(datetime.timezone.utc).timestamp() - ts) > self.ttl_seconds

    def invalidate(self, offer: dict[str, Any]) -> None:
        self._data.pop(self._key(offer), None)
        self._flush()

    def clear(self) -> None:
        self._data = {}
        self._flush()

    def purge_expired(self) -> int:
        stale = [k for k, v in self._data.items() if self._expired(v["ts"])]
        for k in stale:
            self._data.pop(k, None)
        self._flush()
        return len(stale)

    def _flush(self) -> None:
        if not self.path:
            return
        self.path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def size(self) -> int:
        return len(self._data)
