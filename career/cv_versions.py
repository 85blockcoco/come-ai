"""Versioning of CV variants (N100-E08).

In-memory + optional JSONL persistence of successive CV variant versions.
A version is never overwritten: we keep the full history (restore possible).
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class CvVersion:
    version_id: str
    cv_id: str
    created_at: str
    body: str
    note: str = ""


class CvVersionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._versions: dict[str, list[CvVersion]] = {}

    def add(self, cv_id: str, body: str, *, note: str = "", at: str = "") -> CvVersion:
        history = self._versions.setdefault(cv_id, [])
        stamp = at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        version = CvVersion(version_id=f"{cv_id}-v{len(history) + 1}", cv_id=cv_id, created_at=stamp, body=body, note=note)
        history.append(version)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(version), ensure_ascii=False) + "\n")
        return version

    def history(self, cv_id: str) -> list[CvVersion]:
        return list(self._versions.get(cv_id, []))

    def get(self, cv_id: str, version_id: str) -> CvVersion | None:
        for v in self._versions.get(cv_id, []):
            if v.version_id == version_id:
                return v
        return None

    def latest(self, cv_id: str) -> CvVersion | None:
        h = self._versions.get(cv_id)
        return h[-1] if h else None

    def restore(self, cv_id: str, version_id: str) -> CvVersion | None:
        return self.get(cv_id, version_id)
