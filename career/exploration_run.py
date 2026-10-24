"""Persistent state of one Career exploration run.

A run is the server-side record of a single exploration.  It walks through
ordered phases and every counter it exposes is incremented by a step that
actually completed: no phase is announced before it starts and no counter is
filled in to make a progress bar look busy.

The state is written to the local Career settings as one small JSON document,
so a page reload can resume the very same run from its identifier alone.  The
run never stores the person's search brief: only phases, counters, timings and
the identifiers of the public sources that were consulted.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import clean_text, utc_now


PHASE_PREPARING = "preparing"
PHASE_CONSULTING = "consulting"
PHASE_NORMALIZING = "normalizing"
PHASE_QUALIFYING = "qualifying"
PHASE_DEDUPLICATING = "deduplicating"
PHASE_RANKING = "ranking"
PHASE_PERSISTING = "persisting"
PHASE_COMPLETED = "completed"

# The real, sequential order of an exploration.  ``completed`` is the last
# phase: a run that reached it stored its snapshot.
EXPLORATION_PHASES: tuple[str, ...] = (
    PHASE_PREPARING,
    PHASE_CONSULTING,
    PHASE_NORMALIZING,
    PHASE_QUALIFYING,
    PHASE_DEDUPLICATING,
    PHASE_RANKING,
    PHASE_PERSISTING,
    PHASE_COMPLETED,
)

RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_CANCELLED = "cancelled"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_INTERRUPTED = "interrupted"

RUN_STATUSES: tuple[str, ...] = (
    RUN_STATUS_RUNNING,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
)

# Terminal statuses never change again: the frontend stops polling on them.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(
    {
        RUN_STATUS_COMPLETED,
        RUN_STATUS_CANCELLED,
        RUN_STATUS_FAILED,
        RUN_STATUS_INTERRUPTED,
    }
)

PHASE_STATUS_RUNNING = "running"
PHASE_STATUS_COMPLETED = "completed"
PHASE_STATUS_CANCELLED = "cancelled"

# The runs are stored in the Career settings table; a reset of the local
# Career data therefore erases them together with the rest of the space.
EXPLORATION_RUNS_SETTING_KEY = "exploration_runs_v1"

# Only the recent runs are kept: they are a progress trace, not a history of
# the person's activity.
MAX_STORED_RUNS = 20


def is_terminal_status(status: str) -> bool:
    """Whether a run status means the exploration will not move again."""
    return clean_text(status, limit=40) in TERMINAL_RUN_STATUSES


@dataclass
class ExplorationRun:
    """The real state of one exploration run."""

    run_id: str
    status: str = RUN_STATUS_RUNNING
    phase: str = PHASE_PREPARING
    sources_total: int = 0
    sources_planned: int = 0
    sources_completed: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    offers_read: int = 0
    offers_normalized: int = 0
    offers_qualified: int = 0
    offers_deduplicated: int = 0
    offers_ranked: int = 0
    offers_persisted: int = 0
    cancel_requested: bool = False
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    elapsed_seconds: float = 0.0
    error: str = ""
    message: str = ""
    phases: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    # -- phase bookkeeping -------------------------------------------------
    def begin_phase(self, phase: str) -> None:
        """Enter a phase; the phase is only listed once it really starts."""
        name = clean_text(phase, limit=40)
        if name not in EXPLORATION_PHASES:
            raise ValueError(f"unknown exploration phase: {phase}")
        self.phase = name
        self.updated_at = utc_now()
        for entry in self.phases:
            if entry.get("phase") == name:
                entry["status"] = PHASE_STATUS_RUNNING
                entry["started_at"] = self.updated_at
                entry["finished_at"] = ""
                return
        self.phases.append({
            "phase": name,
            "status": PHASE_STATUS_RUNNING,
            "started_at": self.updated_at,
            "finished_at": "",
        })

    def end_phase(self, phase: str, *, status: str = PHASE_STATUS_COMPLETED, note: str = "") -> None:
        """Close a phase that really finished."""
        name = clean_text(phase, limit=40)
        self.updated_at = utc_now()
        for entry in self.phases:
            if entry.get("phase") == name:
                entry["status"] = status
                entry["finished_at"] = self.updated_at
                if note:
                    entry["note"] = clean_text(note, limit=400)
                return
        self.phases.append({
            "phase": name,
            "status": status,
            "started_at": "",
            "finished_at": self.updated_at,
            **({"note": clean_text(note, limit=400)} if note else {}),
        })

    def phases_completed(self) -> int:
        """How many phases of the plan really finished."""
        return sum(
            1
            for entry in self.phases
            if entry.get("status") == PHASE_STATUS_COMPLETED and entry.get("phase") != PHASE_COMPLETED
        )

    def sources_pending(self) -> int:
        """Sources that are planned but not finished yet."""
        return max(0, self.sources_planned - self.sources_completed)

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "phase": self.phase,
            "sources_total": self.sources_total,
            "sources_planned": self.sources_planned,
            "sources_completed": self.sources_completed,
            "sources_succeeded": self.sources_succeeded,
            "sources_failed": self.sources_failed,
            "offers_read": self.offers_read,
            "offers_normalized": self.offers_normalized,
            "offers_qualified": self.offers_qualified,
            "offers_deduplicated": self.offers_deduplicated,
            "offers_ranked": self.offers_ranked,
            "offers_persisted": self.offers_persisted,
            "cancel_requested": self.cancel_requested,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": self.elapsed_seconds,
            "error": self.error,
            "message": self.message,
            "phases": list(self.phases),
            "outcomes": list(self.outcomes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExplorationRun":
        payload = data if isinstance(data, dict) else {}

        def counter(name: str) -> int:
            value = payload.get(name, 0)
            return int(value) if isinstance(value, int) and value >= 0 else 0

        def text(name: str) -> str:
            return clean_text(payload.get(name), limit=2_000)

        phases = payload.get("phases")
        outcomes = payload.get("outcomes")
        status = text("status") or RUN_STATUS_RUNNING
        if status not in RUN_STATUSES:
            status = RUN_STATUS_RUNNING
        phase = text("phase") or PHASE_PREPARING
        if phase not in EXPLORATION_PHASES:
            phase = PHASE_PREPARING
        return cls(
            run_id=text("run_id"),
            status=status,
            phase=phase,
            sources_total=counter("sources_total"),
            sources_planned=counter("sources_planned"),
            sources_completed=counter("sources_completed"),
            sources_succeeded=counter("sources_succeeded"),
            sources_failed=counter("sources_failed"),
            offers_read=counter("offers_read"),
            offers_normalized=counter("offers_normalized"),
            offers_qualified=counter("offers_qualified"),
            offers_deduplicated=counter("offers_deduplicated"),
            offers_ranked=counter("offers_ranked"),
            offers_persisted=counter("offers_persisted"),
            cancel_requested=bool(payload.get("cancel_requested", False)),
            started_at=text("started_at"),
            updated_at=text("updated_at"),
            finished_at=text("finished_at"),
            elapsed_seconds=float(payload.get("elapsed_seconds") or 0.0),
            error=text("error"),
            message=text("message"),
            phases=list(phases) if isinstance(phases, list) else [],
            outcomes=list(outcomes) if isinstance(outcomes, list) else [],
        )

    def to_public_dict(self) -> dict[str, Any]:
        """The public contract of the exploration API."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "phase": self.phase,
            "phase_order": list(EXPLORATION_PHASES),
            "phases": list(self.phases),
            "phases_completed": self.phases_completed(),
            "sources_total": self.sources_total,
            "sources_planned": self.sources_planned,
            "sources_completed": self.sources_completed,
            "sources_succeeded": self.sources_succeeded,
            "sources_failed": self.sources_failed,
            "sources_pending": self.sources_pending(),
            "offers_read": self.offers_read,
            "offers_normalized": self.offers_normalized,
            "offers_qualified": self.offers_qualified,
            "offers_deduplicated": self.offers_deduplicated,
            "offers_ranked": self.offers_ranked,
            "offers_persisted": self.offers_persisted,
            "cancel_requested": self.cancel_requested,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "error": self.error,
            "message": self.message,
            "outcomes": list(self.outcomes),
        }


class ExplorationRunStore:
    """Run state persisted as one JSON document in the local Career settings.

    The store is deliberately tiny and side-effect free apart from its own
    document: it never performs network I/O and never invents a state.  Every
    write replaces the whole document so a reload always reads a consistent
    snapshot.
    """

    def __init__(self, *, load: Callable[[], str], save: Callable[[str], None]):
        self._load = load
        self._save = save
        self._lock = threading.RLock()

    def _read(self) -> list[ExplorationRun]:
        try:
            raw = self._load()
        except Exception:
            return []
        if not raw:
            return []
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if not isinstance(decoded, list):
            return []
        runs: list[ExplorationRun] = []
        for item in decoded:
            if isinstance(item, dict) and item.get("run_id"):
                runs.append(ExplorationRun.from_dict(item))
        return runs

    def _write(self, runs: list[ExplorationRun]) -> None:
        payload = json.dumps([run.to_dict() for run in runs[:MAX_STORED_RUNS]], ensure_ascii=False)
        self._save(payload)

    def list_runs(self, *, limit: int = MAX_STORED_RUNS) -> list[ExplorationRun]:
        """The most recent runs first."""
        bounded = max(1, min(int(limit), MAX_STORED_RUNS))
        with self._lock:
            runs = self._read()
        runs.sort(key=lambda run: run.started_at or run.updated_at, reverse=True)
        return runs[:bounded]

    def get(self, run_id: str) -> ExplorationRun | None:
        identifier = clean_text(run_id, limit=120)
        if not identifier:
            return None
        with self._lock:
            for run in self._read():
                if run.run_id == identifier:
                    return run
        return None

    def save(self, run: ExplorationRun) -> None:
        """Insert or replace one run and keep the document bounded."""
        with self._lock:
            runs = [item for item in self._read() if item.run_id != run.run_id]
            runs.insert(0, run)
            self._write(runs)

    def recover_interrupted(self) -> list[ExplorationRun]:
        """Close the runs left open by a previous process.

        A run that was still marked as running when the local process stopped
        did not finish its work: it is reported as interrupted, never as
        completed, and the offers it had already collected stay visible in its
        counters.
        """
        recovered: list[ExplorationRun] = []
        with self._lock:
            runs = self._read()
            changed = False
            for run in runs:
                if run.status == RUN_STATUS_RUNNING:
                    run.status = RUN_STATUS_INTERRUPTED
                    run.finished_at = utc_now()
                    run.updated_at = run.finished_at
                    run.message = (
                        "L’application locale s’est arrêtée avant la fin de cette exploration. "
                        "Les sources déjà consultées et leurs compteurs restent visibles."
                    )
                    recovered.append(run)
                    changed = True
            if changed:
                self._write(runs)
        return recovered
