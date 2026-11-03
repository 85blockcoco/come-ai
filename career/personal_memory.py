"""Personal memory store (N100-I01)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class MemoryEntry:
    key: str
    value: Any
    source: str = "user"
    approved: bool = False


class PersonalMemory:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = Path(".") / "personal_memory.json"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, MemoryEntry] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    v = {kk: vv for kk, vv in v.items() if kk != "key"}
                    self._data[k] = MemoryEntry(key=k, **v)
            except (json.JSONDecodeError, TypeError):
                self._data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps({k: asdict(v) for k, v in self._data.items()}, ensure_ascii=False, indent=2), encoding="utf-8")

    def set(self, key: str, value: Any, source: str = "user", approved: bool = False) -> MemoryEntry:
        entry = MemoryEntry(key=key, value=value, source=source, approved=approved)
        self._data[key] = entry
        self._save()
        return entry

    def get(self, key: str) -> MemoryEntry | None:
        return self._data.get(key)

    def all(self) -> list[MemoryEntry]:
        return list(self._data.values())

    def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False