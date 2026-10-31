"""Local timing instrumentation for the Career pipeline (SPEC-044).

Records per-step durations (import CV, generation, audit, correction, ...) into a
local SQLite database.  No cloud, no third-party observers.  Pause/resume
supported via explicit start/stop calls.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class StepTiming:
    run_id: str
    step: str
    started_at: float
    ended_at: float
    duration_sec: float
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class MetricsStore:
    """SQLite-backed timing store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path(".") / "career_metrics.sqlite3"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL NOT NULL,
                duration_sec REAL NOT NULL,
                metadata TEXT
            )"""
        )
        self._conn.commit()

    def record(self, timing: StepTiming) -> int:
        cur = self._conn.execute(
            "INSERT INTO steps (run_id, step, started_at, ended_at, duration_sec, metadata) VALUES (?,?,?,?,?,?)",
            (timing.run_id, timing.step, timing.started_at, timing.ended_at, timing.duration_sec,
             json_dumps(timing.metadata)),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def steps_for_run(self, run_id: str) -> list[StepTiming]:
        rows = self._conn.execute(
            "SELECT run_id, step, started_at, ended_at, duration_sec, metadata FROM steps WHERE run_id=?",
            (run_id,),
        ).fetchall()
        out = []
        for r in rows:
            out.append(StepTiming(run_id=r[0], step=r[1], started_at=r[2], ended_at=r[3],
                                 duration_sec=r[4], metadata=json_loads(r[5])))
        return out

    def aggregate(self, run_id: str | None = None) -> dict[str, Any]:
        q = "SELECT step, COUNT(*), AVG(duration_sec), SUM(duration_sec) FROM steps"
        params: tuple[Any, ...] = ()
        if run_id is not None:
            q += " WHERE run_id=?"
            params = (run_id,)
        q += " GROUP BY step"
        rows = self._conn.execute(q, params).fetchall()
        return {r[0]: {"count": r[1], "avg_sec": round(r[2], 3), "total_sec": round(r[3], 3)} for r in rows}

    def total_duration(self, run_id: str) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(duration_sec),0) FROM steps WHERE run_id=?", (run_id,)
        ).fetchone()
        return float(row[0]) if row else 0.0

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MetricsStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def json_loads(s: Any) -> dict[str, Any]:
    import json
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


class StepTimer:
    """Context manager that records a timed step."""

    def __init__(self, store: MetricsStore, run_id: str, step: str, metadata: dict[str, Any] | None = None) -> None:
        self.store = store
        self.run_id = run_id
        self.step = step
        self.metadata = metadata or {}
        self._start: float | None = None
        self._paused_at: float | None = None
        self._accumulated: float = 0.0

    def __enter__(self) -> "StepTimer":
        self._start = time.time()
        return self

    def __exit__(self, *exc) -> None:
        end = time.time()
        start = self._start if self._start is not None else end
        dur = end - start - self._accumulated_paused()
        timing = StepTiming(
            run_id=self.run_id,
            step=self.step,
            started_at=start,
            ended_at=end,
            duration_sec=round(max(0.0, dur), 6),
            metadata=self.metadata,
        )
        self.store.record(timing)

    def _accumulated_paused(self) -> float:
        return 0.0

    def pause(self) -> None:
        self._paused_at = time.time()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._accumulated += time.time() - self._paused_at
            self._paused_at = None


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]