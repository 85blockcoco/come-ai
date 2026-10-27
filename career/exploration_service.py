"""Server-side orchestration of one Career exploration run.

The service owns the phases of an exploration: it consults the curated public
sources (at most two at a time), normalises the postings it really read,
re-qualifies them locally, removes the duplicates, ranks them and persists
the result.  Every counter of the run is incremented by a step that really
completed, so a page that polls the run never reads an invented progress.

Cancellation is cooperative: it is honoured between two sources, never in the
middle of one, and an interrupted exploration never overwrites the results of
the previous one.  A source that fails is isolated: the run continues and the
offers already collected stay untouched.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Protocol

from workspace_core import UserFacingError

from .discovery import DiscoveryPayload, GreenhouseBoard, PublicSourceError, parse_greenhouse_board_token
from .exploration import (
    EXPLORATION_LAST_SETTING,
    EXPLORATION_MAX_RESULTS,
    EXPLORATION_MAX_SOURCES,
    EXPLORATION_NETWORK_BUDGET_SECONDS,
    classify_internship,
    criteria_admit,
    ranking_key,
)
from .exploration_run import (
    EXPLORATION_RUNS_SETTING_KEY,
    PHASE_COMPLETED,
    PHASE_CONSULTING,
    PHASE_DEDUPLICATING,
    PHASE_NORMALIZING,
    PHASE_PERSISTING,
    PHASE_PREPARING,
    PHASE_QUALIFYING,
    PHASE_RANKING,
    PHASE_STATUS_CANCELLED,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    ExplorationRun,
    ExplorationRunStore,
)
from .models import canonical_url, clean_text, utc_now
from .offer_dates import extract_offer_dates
from .offer_qualification import qualify_offer
from .job_deduplication import deduplicate_jobs
from .source_trust import check_trust
from .stage_search import score_brief_match


# Two sources at a time: enough to keep the public boards calm, small enough
# to keep the local process predictable.
MAX_CONCURRENT_SOURCES = 2

# Fields a connector reports about one source.  They are copied as they are
# and never invented: a connector that does not report them stays at zero.
SOURCE_COUNT_FIELDS: tuple[str, ...] = (
    "raw_count",
    "evaluated_count",
    "invalid_count",
    "confirmed_count",
    "uncertain_count",
    "excluded_count",
    "relevant_count",
    "filtered_criteria_count",
)

# Status of one source inside a run.
SOURCE_STATUS_SUCCESS = "success"
SOURCE_STATUS_PARTIAL = "partial"
SOURCE_STATUS_CACHED = "cached"
SOURCE_STATUS_ERROR = "error"
SOURCE_STATUS_UNSUPPORTED = "unsupported"
SOURCE_STATUS_NOT_QUERIED = "not_queried"

# Limits applied to the offers kept in memory during one run.
MAX_NORMALIZED_OFFERS = 4_000


def brief_fingerprint(brief: dict[str, Any]) -> str:
    """Stable fingerprint of a search brief; it never leaves the local store."""
    return hashlib.sha256(json.dumps(brief, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def source_fingerprint(source: dict[str, Any], brief_hash: str) -> str:
    """Fingerprint of one source for one brief; used by the local read cache."""
    return hashlib.sha256(
        json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8") + brief_hash.encode("ascii")
    ).hexdigest()


@dataclass
class SourceResult:
    """What one source really returned during the consulting phase."""

    outcome: dict[str, Any]
    jobs: tuple[dict[str, Any], ...] = ()
    raw_count: int = 0
    verified_at: str = ""

    @property
    def status(self) -> str:
        return str(self.outcome.get("status") or SOURCE_STATUS_ERROR)


@dataclass
class _Candidate:
    """One offer that passed the local qualification."""

    job: dict[str, Any]
    match: dict[str, Any]
    classification: dict[str, Any]
    qualification: dict[str, Any]
    source_id: str = ""
    verified_at: str = ""
    board_token: str = ""
    key: tuple[Any, ...] = field(default_factory=tuple)


class ExplorationBackend(Protocol):
    """What an exploration needs from the local Career service."""

    def brief(self) -> dict[str, Any]:
        """The saved search brief of the person."""

    def sources(self) -> tuple[dict[str, Any], ...]:
        """The curated public sources that may be consulted."""

    def connector(self, provider: str) -> Any:
        """The connector of a provider, or ``None`` when it is not available."""

    def acquire_search_lock(self) -> bool:
        """Reserve the right to run one search at a time."""

    def release_search_lock(self) -> None:
        """Give the search lock back."""

    def cached_result(self, source_id: str, fingerprint: str) -> Any:
        """The last successful read of a source, when it is still valid."""

    def store_result(self, source_id: str, fingerprint: str, payload: Any) -> None:
        """Remember a successful read so a later run need not ask again."""

    def import_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store one offer in the local Career database."""

    def write_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Publish the result of the run as the last exploration snapshot."""

    def load_runs_document(self) -> str:
        """Read the stored runs document."""

    def save_runs_document(self, document: str) -> None:
        """Write the stored runs document."""


class CareerExplorationBackend:
    """Reads and writes the local Career service from inside its own package.

    The Career service keeps its exploration registry, its connectors, its
    local read cache and its settings table private: this adapter is the
    single place where the exploration pipeline reads them, so the pipeline
    and the synchronous explorer always work on the same sources.
    """

    def __init__(self, service: Any):
        self._service = service
        self._lock = threading.RLock()
        self._locked = False

    # -- inputs ------------------------------------------------------------
    def brief(self) -> dict[str, Any]:
        payload = self._service.get_stage_search()
        brief = payload.get("brief") if isinstance(payload, dict) else None
        return brief if isinstance(brief, dict) else {}

    def sources(self) -> tuple[dict[str, Any], ...]:
        registry = self._service._exploration_registry()
        return tuple(dict(source) for source in registry)

    def connector(self, provider: str) -> Any:
        connectors = getattr(self._service, "_exploration_connectors", {}) or {}
        return connectors.get(provider)

    # -- single search at a time -------------------------------------------
    def acquire_search_lock(self) -> bool:
        with self._lock:
            if self._locked:
                return False
            acquired = bool(self._service._discovery_lock.acquire(blocking=False))
            self._locked = acquired
            return acquired

    def release_search_lock(self) -> None:
        with self._lock:
            if not self._locked:
                return
            self._locked = False
        try:
            self._service._discovery_lock.release()
        except RuntimeError:
            pass

    # -- local read cache --------------------------------------------------
    def cached_result(self, source_id: str, fingerprint: str) -> Any:
        cached = (getattr(self._service, "_exploration_cache", {}) or {}).get(source_id)
        if not cached:
            return None
        if cached[0] != fingerprint:
            return None
        payload = cached[1]
        verified_at = getattr(payload, "verified_at", "")
        if not self._service._discovery_cache_valid(verified_at):
            return None
        return payload

    def store_result(self, source_id: str, fingerprint: str, payload: Any) -> None:
        cache = getattr(self._service, "_exploration_cache", None)
        if isinstance(cache, dict):
            cache[source_id] = (fingerprint, payload)

    # -- outputs -----------------------------------------------------------
    def import_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service.import_job(payload, preserve_unknown_source_fields=True)

    def write_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._service._lock, self._service._connection() as connection:
            connection.execute(
                "INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
                (EXPLORATION_LAST_SETTING, json.dumps(snapshot, ensure_ascii=False)),
            )

    def load_runs_document(self) -> str:
        with self._service._lock, self._service._connection() as connection:
            row = connection.execute(
                "SELECT setting_value FROM career_settings WHERE setting_key = ?",
                (EXPLORATION_RUNS_SETTING_KEY,),
            ).fetchone()
        return str(row["setting_value"]) if row else ""

    def save_runs_document(self, document: str) -> None:
        with self._service._lock, self._service._connection() as connection:
            connection.execute(
                "INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
                (EXPLORATION_RUNS_SETTING_KEY, document),
            )


class ExplorationService:
    """Runs the real phases of an exploration and publishes its progress."""

    def __init__(
        self,
        service: Any,
        *,
        backend: ExplorationBackend | None = None,
        max_concurrent_sources: int = MAX_CONCURRENT_SOURCES,
    ):
        self._backend = backend or CareerExplorationBackend(service)
        self._max_concurrent = max(1, min(int(max_concurrent_sources), MAX_CONCURRENT_SOURCES))
        self._store = ExplorationRunStore(
            load=self._backend.load_runs_document,
            save=self._backend.save_runs_document,
        )
        self._threads: dict[str, threading.Thread] = {}
        self._clocks: dict[str, float] = {}
        self._lock = threading.RLock()
        # A run left open by a previous process did not finish its work.
        self._store.recover_interrupted()

    # -- public API --------------------------------------------------------
    def start(self, *, force: bool = False) -> dict[str, Any]:
        """Start one exploration and return its first real state."""
        with self._lock:
            if any(thread.is_alive() for thread in self._threads.values()):
                raise UserFacingError(
                    "Une exploration est déjà en cours. Attends sa fin ou annule-la avant d’en lancer une autre."
                )
            if not self._backend.acquire_search_lock():
                raise UserFacingError(
                    "Une recherche d’opportunités est déjà en cours. Attends sa fin avant de relancer."
                )
            run_id = f"explore_run_{uuid.uuid4().hex}"
            started = utc_now()
            run = ExplorationRun(
                run_id=run_id,
                status=RUN_STATUS_RUNNING,
                phase=PHASE_PREPARING,
                started_at=started,
                updated_at=started,
                message="Préparation de l’exploration : les sources vérifiées du registre sont planifiées.",
            )
            self._store.save(run)
            self._clocks[run_id] = time.monotonic()
            thread = threading.Thread(
                target=self._run_guarded,
                args=(run_id, force),
                name=f"career-exploration-{run_id[-8:]}",
                daemon=True,
            )
            self._threads[run_id] = thread
            try:
                thread.start()
            except RuntimeError:
                # The thread never started: give the search lock back so the
                # next attempt is not refused by a lock nobody holds.
                self._threads.pop(run_id, None)
                self._clocks.pop(run_id, None)
                self._backend.release_search_lock()
                raise UserFacingError(
                    "L’exploration n’a pas pu démarrer. Réessaie dans un instant."
                )
        return run.to_public_dict()

    def state(self, run_id: str) -> dict[str, Any] | None:
        """The current state of one run, read from the local store."""
        run = self._store.get(run_id)
        return run.to_public_dict() if run else None

    def list_runs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """The most recent runs, newest first."""
        return [run.to_public_dict() for run in self._store.list_runs(limit=limit)]

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        """Ask a running exploration to stop between two sources."""
        run = self._store.get(run_id)
        if run is None:
            return None
        if run.status != RUN_STATUS_RUNNING:
            return run.to_public_dict()
        run.cancel_requested = True
        run.updated_at = utc_now()
        run.message = (
            "Annulation demandée : l’exploration s’arrête entre deux sources. "
            "Les résultats précédents sont conservés."
        )
        self._store.save(run)
        return run.to_public_dict()

    def wait_for(self, run_id: str, timeout: float = 10.0) -> dict[str, Any] | None:
        """Wait for a run to finish; used by the tests and by the shutdown."""
        thread = self._threads.get(run_id)
        if thread is not None:
            thread.join(timeout)
        return self.state(run_id)

    def active_run_ids(self) -> list[str]:
        """The runs whose background thread is still alive."""
        with self._lock:
            return [run_id for run_id, thread in self._threads.items() if thread.is_alive()]

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop every background run: no exploration outlives the application."""
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout)
        self._backend.release_search_lock()

    # -- the run -----------------------------------------------------------
    def _run_guarded(self, run_id: str, force: bool) -> None:
        try:
            self._execute(run_id, force=force)
        except Exception as error:  # noqa: BLE001 - the run must always end in a real state
            run = self._store.get(run_id)
            if run is not None:
                run.status = RUN_STATUS_FAILED
                run.error = clean_text(str(error), limit=500) or "Erreur locale pendant l’exploration."
                run.message = (
                    "L’exploration s’est interrompue sur une erreur locale. "
                    "Les offres déjà enregistrées sont conservées."
                )
                run.finished_at = utc_now()
                self._update(run)
        finally:
            self._backend.release_search_lock()
            with self._lock:
                self._clocks.pop(run_id, None)
                if len(self._threads) > 20:
                    for identifier, thread in list(self._threads.items()):
                        if not thread.is_alive():
                            self._threads.pop(identifier, None)

    def _update(self, run: ExplorationRun) -> None:
        # The cooperative cancel flag is written by another thread: it is
        # carried over so a progress update never erases the request.
        stored = self._store.get(run.run_id)
        if stored is not None and stored.cancel_requested:
            run.cancel_requested = True
        run.updated_at = utc_now()
        started = self._clocks.get(run.run_id)
        if started is not None:
            run.elapsed_seconds = time.monotonic() - started
        self._store.save(run)

    def _cancelled(self, run_id: str) -> bool:
        run = self._store.get(run_id)
        return bool(run and run.cancel_requested)

    def _finish_cancelled(self, run: ExplorationRun) -> None:
        run.status = RUN_STATUS_CANCELLED
        run.finished_at = utc_now()
        run.end_phase(run.phase, status=PHASE_STATUS_CANCELLED, note="Annulation coopérative entre deux sources.")
        run.message = (
            "Exploration annulée entre deux sources. Les résultats précédents et les offres déjà "
            "consultées sont conservés."
        )
        self._update(run)

    def _execute(self, run_id: str, *, force: bool) -> None:
        run = self._store.get(run_id)
        if run is None:
            return

        # 1. preparing — plan the sources that may really be consulted.
        run.begin_phase(PHASE_PREPARING)
        brief = self._backend.brief()
        fingerprint = brief_fingerprint(brief)
        sources = list(self._backend.sources())[:EXPLORATION_MAX_SOURCES]
        run.sources_total = len(sources)
        run.sources_planned = len(sources)
        self._update(run)
        run.end_phase(PHASE_PREPARING, note=f"{len(sources)} sources vérifiées planifiées.")
        self._update(run)
        if self._cancelled(run_id):
            self._finish_cancelled(run)
            return

        # 2. consulting — read the public sources, two at a time.
        run.begin_phase(PHASE_CONSULTING)
        self._update(run)
        deadline = time.monotonic() + EXPLORATION_NETWORK_BUDGET_SECONDS
        outcomes, collected = self._consult_sources(run, sources, brief, fingerprint, deadline, force=force)
        if self._cancelled(run_id):
            self._finish_cancelled(run)
            return
        run.end_phase(PHASE_CONSULTING, note=f"{run.sources_completed} sources traitées.")
        self._update(run)

        # 3. normalising — canonical facts for every posting that was read.
        run.begin_phase(PHASE_NORMALIZING)
        self._update(run)
        normalized: list[tuple[dict[str, Any], dict[str, Any]]] = []
        invalid = 0
        for offer, source in collected:
            normalized_offer = self._normalize_offer(offer, source)
            if normalized_offer is None:
                invalid += 1
                continue
            normalized.append((normalized_offer, source))
        run.offers_normalized = len(normalized)
        run.end_phase(PHASE_NORMALIZING, note=f"{len(normalized)} annonces normalisées.")
        self._update(run)
        if self._cancelled(run_id):
            self._finish_cancelled(run)
            return

        # 4. qualifying — re-qualify locally; connector output is never trusted.
        run.begin_phase(PHASE_QUALIFYING)
        self._update(run)
        candidates = self._qualify_offers(normalized, brief)
        run.offers_qualified = len(candidates)
        run.end_phase(PHASE_QUALIFYING, note=f"{len(candidates)} offres qualifiées.")
        self._update(run)
        if self._cancelled(run_id):
            self._finish_cancelled(run)
            return

        # 5. deduplicating — one record per canonical official URL.
        run.begin_phase(PHASE_DEDUPLICATING)
        self._update(run)
        unique = self._deduplicate(candidates)
        run.offers_deduplicated = len(unique)
        run.end_phase(PHASE_DEDUPLICATING, note=f"{len(unique)} offres uniques.")
        self._update(run)
        if self._cancelled(run_id):
            self._finish_cancelled(run)
            return

        # 6. ranking — the same deterministic order as the explorer report.
        run.begin_phase(PHASE_RANKING)
        self._update(run)
        ranked = sorted(unique, key=lambda candidate: candidate.key)[:EXPLORATION_MAX_RESULTS]
        run.offers_ranked = len(ranked)
        run.end_phase(PHASE_RANKING, note=f"{len(ranked)} offres classées.")
        self._update(run)
        if self._cancelled(run_id):
            self._finish_cancelled(run)
            return

        # 7. persisting — store the offers and publish the snapshot.
        run.begin_phase(PHASE_PERSISTING)
        self._update(run)
        match_refs, imported, updated, invalid_imports = self._persist_offers(ranked)
        run.offers_persisted = len(match_refs)
        summary = self._summary(run, outcomes, imported=imported, updated=updated,
                                invalid_imports=invalid_imports, invalid_offers=invalid)
        snapshot = {
            "run_id": run.run_id,
            "started_at": run.started_at,
            "finished_at": utc_now(),
            "brief_fingerprint": fingerprint,
            "outcomes": outcomes,
            "summary": summary,
            "match_refs": match_refs,
        }
        self._backend.write_snapshot(snapshot)
        run.end_phase(PHASE_PERSISTING, note=f"{len(match_refs)} offres enregistrées.")
        self._update(run)

        # 8. completed — the run really finished its work.
        run.begin_phase(PHASE_COMPLETED)
        run.status = RUN_STATUS_COMPLETED
        run.finished_at = utc_now()
        run.message = (
            f"Exploration terminée : {run.sources_succeeded} sources consultées, "
            f"{run.sources_failed} en erreur, {run.offers_persisted} offres enregistrées."
        )
        run.end_phase(PHASE_COMPLETED)
        self._update(run)

    # -- phases ------------------------------------------------------------
    def _consult_sources(
        self,
        run: ExplorationRun,
        sources: list[dict[str, Any]],
        brief: dict[str, Any],
        fingerprint: str,
        deadline: float,
        *,
        force: bool,
    ) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
        """Read the sources two at a time and report every finished source."""
        outcomes: list[dict[str, Any]] = []
        collected: list[tuple[dict[str, Any], dict[str, Any]]] = []
        pool = ThreadPoolExecutor(
            max_workers=self._max_concurrent, thread_name_prefix="career-exploration-source"
        )
        try:
            for index in range(0, len(sources), self._max_concurrent):
                if self._cancelled(run.run_id):
                    break
                chunk = sources[index:index + self._max_concurrent]
                futures = {
                    pool.submit(self._consult_source, source, brief, fingerprint, deadline, force): source
                    for source in chunk
                }
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as error:  # noqa: BLE001 - one source never breaks the run
                        result = SourceResult(
                            outcome={
                                "source_id": "",
                                "provider": "",
                                "company": "",
                                "status": SOURCE_STATUS_ERROR,
                                "attempted": False,
                                "error_code": clean_text(getattr(error, "code", "unexpected"), limit=40),
                                "message": "Cette source n’a pas pu être vérifiée. Les offres existantes sont conservées.",
                            }
                        )
                    outcomes.append(result.outcome)
                    collected.extend((job, result.outcome) for job in result.jobs)
                    run.sources_completed += 1
                    if result.status in {SOURCE_STATUS_SUCCESS, SOURCE_STATUS_PARTIAL, SOURCE_STATUS_CACHED}:
                        run.sources_succeeded += 1
                    elif result.status == SOURCE_STATUS_ERROR:
                        run.sources_failed += 1
                    run.offers_read += result.raw_count
                    run.outcomes = list(outcomes)
                    self._update(run)
        finally:
            pool.shutdown(wait=True)
        return outcomes, collected

    def _consult_source(
        self,
        source: dict[str, Any],
        brief: dict[str, Any],
        fingerprint: str,
        deadline: float,
        force: bool,
    ) -> SourceResult:
        """Consult one source; a failure never touches the offers already read."""
        source_id = clean_text(source.get("id"), limit=160)
        provider = clean_text(source.get("provider"), limit=40)
        company = clean_text(source.get("company"), limit=240)
        outcome: dict[str, Any] = {
            "source_id": source_id,
            "provider": provider,
            "company": company,
            "board_token": clean_text(source.get("board_token"), limit=160),
            "public_url": source.get("public_url", ""),
            "provenance_url": source.get("provenance_url", ""),
            "registry_verified_at": source.get("verified_at", ""),
            "attempted": False,
        }
        connector = self._backend.connector(provider)
        if connector is None or not callable(getattr(connector, "discover_internships", None)):
            outcome.update(
                status=SOURCE_STATUS_UNSUPPORTED,
                message="Connecteur non disponible ; source non consultée.",
            )
            return SourceResult(outcome=outcome)
        if not source_id or not company or not source.get("verified_at") or not source.get("provenance_url"):
            outcome.update(
                status=SOURCE_STATUS_UNSUPPORTED,
                message="Source sans identité ou provenance vérifiée ; non consultée.",
            )
            return SourceResult(outcome=outcome)
        cache_hash = source_fingerprint(source, fingerprint)
        cached = self._backend.cached_result(source_id, cache_hash)
        if not force and cached is not None:
            outcome.update(
                status=SOURCE_STATUS_CACHED,
                message="Dernière lecture réussie conservée (cache local).",
            )
            return self._result_from_payload(outcome, cached)
        if time.monotonic() >= deadline:
            outcome.update(
                status=SOURCE_STATUS_NOT_QUERIED,
                message="Budget réseau atteint ; cette source n’a pas été consultée.",
            )
            return SourceResult(outcome=outcome)
        try:
            descriptor = (
                GreenhouseBoard(source_id, company, parse_greenhouse_board_token(source.get("board_token")))
                if provider == "greenhouse"
                else source
            )
            outcome["attempted"] = True
            payload = connector.discover_internships(descriptor, selection_brief=brief, deadline=deadline)
            self._check_payload(payload)
            self._backend.store_result(source_id, cache_hash, payload)
            outcome.update(
                status=SOURCE_STATUS_SUCCESS,
                message="Flux officiel lu ; admission et classement effectués localement.",
            )
        except Exception as caught:  # noqa: BLE001 - a source failure is isolated
            code = clean_text(getattr(caught, "code", "unexpected"), limit=40)
            outcome.update(
                status=SOURCE_STATUS_ERROR,
                error_code=code,
                message="Cette source n’a pas pu être vérifiée. Les offres et candidatures existantes sont conservées.",
            )
            return SourceResult(outcome=outcome)
        return self._result_from_payload(outcome, payload)

    @staticmethod
    def _check_payload(payload: Any) -> None:
        """Refuse a connector result that is not coherent before using it."""
        if (
            not isinstance(payload, DiscoveryPayload)
            or not isinstance(payload.jobs, tuple)
            or any(not isinstance(job, dict) for job in payload.jobs)
        ):
            raise PublicSourceError(
                "Le connecteur n’a pas renvoyé un résultat d’exploration valide.", code="invalid_payload"
            )
        counts = tuple(int(getattr(payload, name, 0)) for name in SOURCE_COUNT_FIELDS)
        if (
            any(count < 0 for count in counts)
            or payload.raw_count != payload.evaluated_count + payload.invalid_count
            or payload.evaluated_count != payload.confirmed_count + payload.uncertain_count + payload.excluded_count
            or payload.relevant_count + payload.filtered_criteria_count
            != payload.confirmed_count + payload.uncertain_count
            or len(payload.jobs) > min(EXPLORATION_MAX_RESULTS, payload.relevant_count)
        ):
            raise PublicSourceError(
                "Le connecteur n’a pas fourni des compteurs d’exploration cohérents.", code="invalid_counts"
            )

    @staticmethod
    def _result_from_payload(outcome: dict[str, Any], payload: Any) -> SourceResult:
        outcome.update({name: int(getattr(payload, name, 0)) for name in SOURCE_COUNT_FIELDS})
        outcome.update(
            verified_at=getattr(payload, "verified_at", ""),
            retained_count=len(payload.jobs),
            truncated=bool(getattr(payload, "truncated", False)),
        )
        if payload.invalid_count and outcome.get("status") in {SOURCE_STATUS_SUCCESS, SOURCE_STATUS_CACHED}:
            outcome.update(
                status=SOURCE_STATUS_PARTIAL,
                message="Flux officiel lu, avec des entrées incomplètes ou invalides ignorées.",
            )
        return SourceResult(
            outcome=outcome,
            jobs=tuple(payload.jobs),
            raw_count=int(payload.raw_count),
            verified_at=str(getattr(payload, "verified_at", "")),
        )

    @staticmethod
    def _normalize_offer(offer: dict[str, Any], source: dict[str, Any]) -> dict[str, Any] | None:
        """Canonical facts for one posting; an unreadable posting is dropped."""
        title = clean_text(offer.get("title"), limit=300)
        company = clean_text(offer.get("company"), limit=240) or clean_text(source.get("company"), limit=240)
        if not title or not company:
            return None
        url = clean_text(offer.get("official_url"), limit=2_000)
        if url:
            try:
                url = canonical_url(url)
            except UserFacingError:
                return None
        normalized = {
            "title": title,
            "company": company,
            "official_url": url,
            "source_name": clean_text(offer.get("source_name"), limit=120)
            or clean_text(source.get("provider"), limit=120),
            "source_id": clean_text(offer.get("source_id") or offer.get("external_id") or offer.get("id"), limit=240),
            "job_family": clean_text(offer.get("job_family"), limit=160),
            "city": clean_text(offer.get("city"), limit=160),
            "country": clean_text(offer.get("country"), limit=120),
            "posted_date": clean_text(offer.get("posted_date"), limit=32),
            "deadline_date": clean_text(offer.get("deadline_date"), limit=32),
            "start_date": clean_text(offer.get("start_date"), limit=32),
            "end_date": clean_text(offer.get("end_date"), limit=32),
            "duration_months": offer.get("duration_months") if isinstance(offer.get("duration_months"), int) else None,
            "source_status": clean_text(offer.get("source_status"), limit=40) or "unknown",
            "employment_type": clean_text(offer.get("employment_type"), limit=120),
            "role_level": clean_text(offer.get("role_level"), limit=120),
            "requirements": clean_text(offer.get("requirements"), limit=12_000),
            "languages_required": clean_text(offer.get("languages_required"), limit=2_000),
            "eligibility_requirement": clean_text(offer.get("eligibility_requirement"), limit=2_000),
            "description_original": clean_text(offer.get("description_original"), limit=30_000),
        }
        if isinstance(offer.get("source_fields"), dict):
            normalized["source_fields"] = offer["source_fields"]
        if isinstance(offer.get("source_conflicts"), list):
            normalized["source_conflicts"] = offer["source_conflicts"]
        return normalized

    def _qualify_offers(
        self,
        normalized: list[tuple[dict[str, Any], dict[str, Any]]],
        brief: dict[str, Any],
    ) -> list[_Candidate]:
        """Apply the local admission rules again, on the service boundary."""
        candidates: list[_Candidate] = []
        for job, source in normalized:
            if len(candidates) >= MAX_NORMALIZED_OFFERS:
                break
            verified_at = clean_text(source.get("verified_at"), limit=64)
            classification = classify_internship(job)
            match = score_brief_match(brief, job)
            qualification = qualify_offer(
                {**job, "source_verified": bool(verified_at)},
                allowed_contract_types=brief.get("contract_types"),
                allowed_start_months=brief.get("start_months"),
                required_start_date=brief.get("start_date"),
                minimum_stage_duration_months=brief.get("minimum_stage_duration_months", 6),
                excluded_countries=brief.get("excluded_countries"),
                excluded_cities=brief.get("excluded_cities"),
                require_known_location=brief.get("require_known_location", False),
            ).to_dict()
            qualification["temporal_facts"] = [
                fact.to_dict() for fact in extract_offer_dates(job)
            ]
            if qualification.get("target_status") == "non_conforming":
                continue
            if qualification.get("contract_type") == "unknown" and not classification.get("evidence"):
                continue
            qualified = {**job, "qualification": qualification}
            if not criteria_admit(match, qualified, brief):
                continue
            candidates.append(
                _Candidate(
                    job=qualified,
                    match=match,
                    classification=classification,
                    qualification=qualification,
                    source_id=clean_text(source.get("source_id"), limit=160),
                    verified_at=verified_at,
                    board_token=clean_text(source.get("board_token"), limit=160),
                    key=ranking_key(job, match),
                )
            )
        return candidates

    @staticmethod
    def _deduplicate(candidates: list[_Candidate]) -> list[_Candidate]:
        """Deduplicate offers while retaining bounded source evidence."""
        if not candidates:
            return []
        records: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            job = dict(candidate.job)
            trust = check_trust(
                clean_text(job.get("official_url"), limit=2_000),
                employer_hint=clean_text(job.get("company"), limit=200),
            )
            job.update({
                "_candidate_index": index,
                # A board id identifies the connector, not an individual job;
                # only the posting's own identifier is valid dedup evidence.
                "source_id": job.get("source_id", ""),
                "source_trust": trust.status,
                "last_verified_at": candidate.verified_at,
            })
            records.append(job)

        kept: list[_Candidate] = []
        for group in deduplicate_jobs(records):
            best = group["best"]
            representative = candidates[int(best["_candidate_index"])]
            # A duplicate can carry a date passage that the elected record
            # does not. Preserve the union of cited temporal facts before the
            # merged offer is persisted; deduplication must remove duplicate
            # rows, never discard stronger source evidence.
            temporal_facts: list[dict[str, Any]] = []
            temporal_keys: set[str] = set()
            for view in group["provenances"]:
                record = view.get("record") if isinstance(view, dict) else None
                qualification = record.get("qualification") if isinstance(record, dict) else None
                facts = qualification.get("temporal_facts") if isinstance(qualification, dict) else None
                for fact in facts if isinstance(facts, list) else []:
                    if not isinstance(fact, dict):
                        continue
                    key = json.dumps(fact, sort_keys=True, ensure_ascii=False)
                    if key in temporal_keys:
                        continue
                    temporal_keys.add(key)
                    temporal_facts.append(dict(fact))
            if temporal_facts:
                representative.qualification["temporal_facts"] = temporal_facts[:50]
            provenances = [
                {
                    "source_name": item.get("source_name", ""),
                    "source_id": item.get("source_id", ""),
                    "official_url": item.get("official_url", ""),
                    "trust": item.get("trust", "missing"),
                    "is_representative": bool(item.get("is_representative")),
                }
                for item in group["provenances"][:25]
            ]
            representative.qualification["source_provenance"] = provenances
            representative.qualification["source_conflicts"] = {
                clean_text(field_name, limit=80): {
                    clean_text(source_id, limit=160): clean_text(value, limit=300)
                    for source_id, value in list(values.items())[:10]
                }
                for field_name, values in list(group["conflicts"].items())[:20]
                if isinstance(values, dict)
            }
            representative.qualification["dedup_reasons"] = [
                clean_text(reason, limit=200) for reason in group["match_reasons"][:20]
            ]
            kept.append(representative)
        return kept

    def _persist_offers(
        self,
        ranked: list[_Candidate],
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        """Store the ranked offers; one unreadable offer never stops the rest."""
        match_refs: list[dict[str, Any]] = []
        imported = 0
        updated = 0
        invalid_imports = 0
        for candidate in ranked:
            payload = dict(candidate.job)
            payload["source_id"] = f"curated:{candidate.board_token}:{payload.get('source_id', '')}"
            try:
                stored = self._backend.import_offer(payload)
            except UserFacingError:
                invalid_imports += 1
                continue
            imported += int(bool(stored.get("created")))
            updated += int(not stored.get("created"))
            match_refs.append({
                "job_id": stored.get("id", ""),
                "source_id": candidate.source_id,
                "verified_at": candidate.verified_at,
            })
        return match_refs, imported, updated, invalid_imports

    @staticmethod
    def _summary(
        run: ExplorationRun,
        outcomes: list[dict[str, Any]],
        *,
        imported: int,
        updated: int,
        invalid_imports: int,
        invalid_offers: int,
    ) -> dict[str, Any]:
        """The same counters as the synchronous explorer report."""
        summary: dict[str, Any] = {
            "sources_total": run.sources_total,
            "sources_attempted": sum(1 for item in outcomes if item.get("attempted")),
            "sources_succeeded": run.sources_succeeded,
            "sources_cached": sum(1 for item in outcomes if item.get("status") == SOURCE_STATUS_CACHED),
            "sources_failed": run.sources_failed,
            "sources_not_queried": sum(
                1 for item in outcomes if item.get("status") in {SOURCE_STATUS_NOT_QUERIED, SOURCE_STATUS_UNSUPPORTED}
            ),
            "retained_count": run.offers_persisted,
            "imported_count": imported,
            "updated_count": updated,
            "invalid_imports": invalid_imports,
            "invalid_offers": invalid_offers,
            "duplicate_count": max(0, run.offers_qualified - run.offers_deduplicated),
            "elapsed_seconds": round(run.elapsed_seconds, 3),
            "partial": run.sources_failed > 0 or invalid_imports > 0 or invalid_offers > 0,
            "counts_include_cached_sources": any(item.get("status") == SOURCE_STATUS_CACHED for item in outcomes),
        }
        for name in SOURCE_COUNT_FIELDS:
            summary[name] = sum(int(item.get(name, 0) or 0) for item in outcomes)
        return summary
