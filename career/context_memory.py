"""Session context memory (N100-I09)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ContextMemory:
    _store: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._store is None:
            self._store = {}

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def clear(self) -> None:
        self._store.clear()

    def all(self) -> dict[str, Any]:
        return dict(self._store)