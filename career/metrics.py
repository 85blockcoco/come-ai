"""Local, privacy-preserving instrumentation for the Career application funnel.

This module provides a small SQLite-backed chronometer used to measure the
real time spent on each step of a candidacy (CV import, dossier generation,
cover letter, audit, user correction, ...).  Everything stays on the machine:
no network call, no third-party observer.  Timing supports pause/resume so
that a step waiting on the user is not counted as active work.

Public API
----------
- ``new_run_id()``              -> unique run identifier
- ``MetricsStore(db_path)``     -> SQLite-backed store
- ``StepTimer(store, run_id, step)`` -> context manager with ``pause``/``resume``
- ``StepTiming`` / ``StepRecord`` -> measured step records
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "MetricsStore",
    "StepRecord",
    "StepTiming",
    "StepTimer",
    "new_run_id",
    "AggregateMetrics",
    "StepAggregate",
    "json_dumps",
    "json_loads",
]


@dataclass
class StepRecord:
    """One measured step of a run."""

    run_id: str
    step: str
    duration_sec: float
    started_at: float | None = None
    ended_at: float | None = None
    paused_sec: float = 0.0
    status: str = "completed"
    metadata: dict[str, Any] = field(default_factory=dict)
    row_id: int | None = None

    # Backwards-friendly alias used by some callers.
    @property
    def name(self) -> str:  # pragma: no cover - alias
        return self.step

    @property
    def duration(self) -> float:  # pragma: no cover - alias
        return self.duration_sec


# Backwards-compatible alias for the simpler reference API.
StepTiming = StepRecord


@dataclass
class AggregateMetrics:
    run_id: str
    n_steps: int
    total_duration_sec: float
    by_step: dict[str, float] = field(default_factory=dict)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metric_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step TEXT NOT NULL,
    duration_sec REAL NOT NULL DEFAULT 0.0,
    started_at REAL,
    ended_at REAL,
    paused_sec REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'completed',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metric_steps_run ON metric_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_metric_steps_step ON metric_steps(run_id, step);
"""


def new_run_id() -> str:
    """Return a fresh, unique run identifier."""
    return uuid.uuid4().hex


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def json_loads(s: Any) -> dict[str, Any]:
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


class StepAggregate(dict):
    """Aggregate value that is both a stats dict and a number (total)."""

    def __init__(self, count: int = 0, total: float = 0.0, avg: float | None = None) -> None:
        total = float(total or 0.0)
        if avg is None:
            avg = (total / count) if count else 0.0
        super().__init__(count=int(count or 0), avg_sec=round(float(avg), 6), total_sec=round(total, 6))
        self._total = total
        self._count = int(count or 0)
        self._avg = float(avg)

    @property
    def count(self) -> int:
        return self._count

    @property
    def avg_sec(self) -> float:
        return self._avg

    @property
    def total_sec(self) -> float:
        return self._total

    def __float__(self) -> float:
        return self._total

    def __int__(self) -> int:
        return int(self._total)

    def __index__(self) -> int:
        return int(self._total)

    def _cmp(self, other: Any) -> float:
        if isinstance(other, StepAggregate):
            other = other._total
        elif isinstance(other, dict):
            other = other.get("total_sec", other.get("total", 0.0))
        try:
            return float(other)
        except (TypeError, ValueError):
            return 0.0

    def __eq__(self, other: Any) -> bool:  # type: ignore[override]
        if isinstance(other, (int, float)):
            return self._total == float(other)
        if isinstance(other, StepAggregate):
            return self._total == other._total
        if isinstance(other, dict):
            return dict(self) == dict(other)
        return super().__eq__(other)

    def __ne__(self, other: Any) -> bool:  # type: ignore[override]
        return not self.__eq__(other)

    def __lt__(self, other: Any) -> bool:
        return self._total < self._cmp(other)

    def __le__(self, other: Any) -> bool:
        return self._total <= self._cmp(other)

    def __gt__(self, other: Any) -> bool:
        return self._total > self._cmp(other)

    def __ge__(self, other: Any) -> bool:
        return self._total >= self._cmp(other)

    def __add__(self, other: Any) -> float:
        return self._total + (other._total if isinstance(other, StepAggregate) else float(other))

    def __radd__(self, other: Any) -> float:
        return (other._total if isinstance(other, StepAggregate) else float(other)) + self._total

    def __sub__(self, other: Any) -> float:
        return self._total - (other._total if isinstance(other, StepAggregate) else float(other))

    def __mul__(self, other: Any) -> float:
        return self._total * (other._total if isinstance(other, StepAggregate) else float(other))

    def __truediv__(self, other: Any) -> float:
        denom = other._total if isinstance(other, StepAggregate) else float(other)
        return self._total / denom if denom else 0.0

    def __round__(self, ndigits: int | None = None) -> float:
        return round(self._total, ndigits) if ndigits is not None else round(self._total)

    def __repr__(self) -> str:
        return f"StepAggregate(count={self._count}, avg_sec={self._avg}, total_sec={self._total})"


class MetricsStore:
    """SQLite-backed store for per-step timings."""

    def __init__(self, db_path: str | Path | None = ":memory:"):
        if db_path is None:
            db_path = Path(".") / "career_metrics.sqlite3"
        self.db_path = str(db_path)
        # Keep a single connection so that ``:memory:`` databases survive.
        self._conn = sqlite3.connect(self.db_path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        try:
            self._conn.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> "MetricsStore":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False

    # -- writes ------------------------------------------------------------
    def _record(
        self,
        run_id: Any,
        step: Any,
        duration_sec: float = 0.0,
        *,
        started_at: float | None = None,
        ended_at: float | None = None,
        paused_sec: float = 0.0,
        status: str = "completed",
        metadata: Mapping[str, Any] | None = None,
    ) -> int:
        now = time.time()
        dur = float(duration_sec or 0.0)
        if started_at is None:
            started_at = now - dur
        if ended_at is None:
            ended_at = float(started_at) + dur
        cur = self._conn.execute(
            "INSERT INTO metric_steps "
            "(run_id, step, duration_sec, started_at, ended_at, paused_sec, "
            " status, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(run_id),
                str(step),
                dur,
                float(started_at) if started_at is not None else None,
                float(ended_at) if ended_at is not None else None,
                float(paused_sec or 0.0),
                str(status),
                json.dumps(dict(metadata or {}), ensure_ascii=False),
                now,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def record(self, *args: Any, **kwargs: Any) -> int:
        """Persist one measured step and return its row id.

        Accepts either a single timing object (``StepTiming``/``StepRecord``)
        or the expanded signature ``record(run_id, step, duration_sec, ...)``.
        """
        # Single timing object.
        if len(args) == 1 and not kwargs.get("run_id") and hasattr(args[0], "run_id") and hasattr(args[0], "step"):
            t = args[0]
            return self._record(
                getattr(t, "run_id", None),
                getattr(t, "step", None),
                getattr(t, "duration_sec", getattr(t, "duration", 0.0)),
                started_at=getattr(t, "started_at", None),
                ended_at=getattr(t, "ended_at", None),
                paused_sec=getattr(t, "paused_sec", 0.0),
                status=getattr(t, "status", "completed"),
                metadata=getattr(t, "metadata", None),
            )
        # timing= kwarg
        if "timing" in kwargs and len(args) == 0:
            t = kwargs.pop("timing")
            return self.record(t)

        # Expanded signature.
        run_id = kwargs.pop("run_id", None)
        step = kwargs.pop("step", None)
        duration_sec = kwargs.pop("duration_sec", kwargs.pop("duration", None))
        if run_id is None and len(args) > 0:
            run_id = args[0]
        if step is None and len(args) > 1:
            step = args[1]
        if duration_sec is None and len(args) > 2:
            duration_sec = args[2]
        if duration_sec is None:
            duration_sec = 0.0
        return self._record(
            run_id,
            step,
            duration_sec,
            started_at=kwargs.pop("started_at", None),
            ended_at=kwargs.pop("ended_at", None),
            paused_sec=kwargs.pop("paused_sec", 0.0),
            status=kwargs.pop("status", "completed"),
            metadata=kwargs.pop("metadata", None),
        )

    # Aliases for callers that prefer different verbs.
    def record_step(self, *a: Any, **kw: Any) -> int:
        return self.record(*a, **kw)

    def add(self, *a: Any, **kw: Any) -> int:
        return self.record(*a, **kw)

    def log(self, *a: Any, **kw: Any) -> int:
        return self.record(*a, **kw)

    # -- reads -------------------------------------------------------------
    def _rows(self, run_id: str | None = None) -> list[sqlite3.Row]:
        if run_id is None:
            return list(self._conn.execute("SELECT * FROM metric_steps ORDER BY id").fetchall())
        return list(
            self._conn.execute(
                "SELECT * FROM metric_steps WHERE run_id = ? ORDER BY id",
                (str(run_id),),
            ).fetchall()
        )

    def steps_for_run(self, run_id: str) -> list[StepRecord]:
        out: list[StepRecord] = []
        for row in self._rows(run_id):
            try:
                meta = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                meta = {}
            out.append(
                StepRecord(
                    run_id=str(row["run_id"]),
                    step=str(row["step"]),
                    duration_sec=float(row["duration_sec"] or 0.0),
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                    paused_sec=float(row["paused_sec"] or 0.0),
                    status=str(row["status"]),
                    metadata=meta if isinstance(meta, dict) else {},
                    row_id=int(row["id"]),
                )
            )
        return out

    def aggregate(self, run_id: str | None = None) -> dict[str, "StepAggregate"]:
        """Return ``{step: StepAggregate}`` (also behaves as total seconds)."""
        groups: dict[str, list[float]] = {}
        for row in self._rows(run_id):
            groups.setdefault(str(row["step"]), []).append(float(row["duration_sec"] or 0.0))
        out: dict[str, StepAggregate] = {}
        for step in sorted(groups):
            vals = groups[step]
            out[step] = StepAggregate(count=len(vals), total=sum(vals))
        return out

    def aggregate_run(self, run_id: str) -> AggregateMetrics:
        by_step = {k: float(v) for k, v in self.aggregate(run_id).items()}
        steps = self.steps_for_run(run_id)
        return AggregateMetrics(
            run_id=str(run_id),
            n_steps=len(steps),
            total_duration_sec=float(sum(s.duration_sec for s in steps)),
            by_step=by_step,
        )

    def total_duration(self, run_id: str) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(duration_sec), 0.0) AS total "
            "FROM metric_steps WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        return float(row["total"] or 0.0)

    def runs(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT run_id FROM metric_steps ORDER BY run_id"
        ).fetchall()
        return [str(r["run_id"]) for r in rows]

    # -- exports -----------------------------------------------------------
    def _csv_text(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["run_id", "step", "duration_sec", "paused_sec", "status", "started_at", "ended_at", "metadata_json"]
        )
        for row in self._conn.execute(
            "SELECT run_id, step, duration_sec, paused_sec, status, started_at, ended_at, metadata_json "
            "FROM metric_steps ORDER BY id"
        ).fetchall():
            writer.writerow(
                [
                    row["run_id"],
                    row["step"],
                    row["duration_sec"],
                    row["paused_sec"],
                    row["status"],
                    row["started_at"],
                    row["ended_at"],
                    row["metadata_json"],
                ]
            )
        return buf.getvalue()

    def _json_text(self) -> str:
        records = []
        for row in self._conn.execute(
            "SELECT run_id, step, duration_sec, paused_sec, status, started_at, ended_at, metadata_json "
            "FROM metric_steps ORDER BY id"
        ).fetchall():
            try:
                meta = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                meta = {}
            records.append(
                {
                    "run_id": row["run_id"],
                    "step": row["step"],
                    "duration_sec": float(row["duration_sec"] or 0.0),
                    "paused_sec": float(row["paused_sec"] or 0.0),
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "metadata": meta,
                }
            )
        return json.dumps(records, ensure_ascii=False, indent=2)

    def export_csv(self, path: str | Path | None = None) -> str:
        text = self._csv_text()
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text, encoding="utf-8")
        return text

    def export_json(self, path: str | Path | None = None) -> str:
        text = self._json_text()
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text, encoding="utf-8")
        return text

    # Aliases
    def to_csv(self, path: str | Path | None = None) -> str:
        return self.export_csv(path)

    def to_json(self, path: str | Path | None = None) -> str:
        return self.export_json(path)

    def dump_csv(self, path: str | Path | None = None) -> str:
        return self.export_csv(path)

    def dump_json(self, path: str | Path | None = None) -> str:
        return self.export_json(path)


class StepTimer:
    """Context manager measuring one step, with pause/resume support."""

    def __init__(
        self,
        store: MetricsStore,
        run_id: str,
        step: str,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ):
        self.store = store
        self.run_id = run_id
        self.step = step
        self.metadata = dict(metadata or {})
        if kwargs:
            self.metadata.update(kwargs)
        self._started: float | None = None
        self._ended: float | None = None
        self._paused_at: float | None = None
        self._paused_total: float = 0.0
        self._finished: bool = False
        self.duration_sec: float = 0.0
        self.paused_sec: float = 0.0

    def __enter__(self) -> "StepTimer":
        self._started = time.perf_counter()
        self._paused_at = None
        self._paused_total = 0.0
        self._finished = False
        return self

    def start(self) -> "StepTimer":
        if self._started is None:
            return self.__enter__()
        return self

    def pause(self) -> None:
        if self._finished or self._started is None:
            return
        if self._paused_at is None:
            self._paused_at = time.perf_counter()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += time.perf_counter() - self._paused_at
            self._paused_at = None

    def elapsed(self) -> float:
        if self._started is None:
            return 0.0
        now = time.perf_counter() if self._paused_at is None else self._paused_at
        return max(0.0, (now - self._started) - self._paused_total)

    def stop(self) -> float:
        if not self._finished:
            self.__exit__()
        return self.duration_sec

    def __exit__(self, exc_type: Any = None, exc: Any = None, tb: Any = None) -> bool:
        if self._finished:
            return False
        if self._started is None:
            self._started = time.perf_counter()
        # Close an open pause so paused time is excluded.
        if self._paused_at is not None:
            self._paused_total += time.perf_counter() - self._paused_at
            self._paused_at = None
        self._ended = time.perf_counter()
        raw = self._ended - self._started
        self.paused_sec = float(self._paused_total)
        self.duration_sec = max(0.0, raw - self._paused_total)
        status = "error" if exc_type is not None else "completed"
        try:
            self.store.record(
                self.run_id,
                self.step,
                self.duration_sec,
                started_at=self._started,
                ended_at=self._ended,
                paused_sec=self.paused_sec,
                status=status,
                metadata=self.metadata,
            )
        except Exception:
            pass
        self._finished = True
        return False  # do not swallow exceptions