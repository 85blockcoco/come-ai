"""Simple error monitor (N100-J09)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ErrorRecord:
    message: str
    context: str = ""
    at: str = ""


class ErrorMonitor:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = Path(".") / "errors.jsonl"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, message: str, context: str = "", at: str = "") -> ErrorRecord:
        import datetime
        if not at:
            at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rec = ErrorRecord(message=message, context=context, at=at)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        return rec

    def recent(self, limit: int = 20) -> list[ErrorRecord]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                out.append(ErrorRecord(**obj))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def count(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())