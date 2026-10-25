"""Small application facade shared by the terminal and local workshop UI."""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from devkit.diagnostics import run_diagnostics
from devkit.exporting import KitError, build_issue_bundle, export_snapshot, source_inventory, source_fingerprint
from devkit.patching import PatchWorkspace


class DeveloperWorkshop:
    """One maintenance worker, no model call and no automatic application.

    Persistent artifacts are kept outside source/data directories. The HTTP
    caller can select opaque candidate/artifact IDs, never filesystem paths,
    commands, a Python interpreter or a destination for a write.
    """

    def __init__(self, project_root: Path, storage_root: Path | None = None, *, busy_check: Callable[[], bool] | None = None):
        self.project_root = project_root.resolve()
        # The app is already running inside its selected Python environment.
        # Reuse that exact interpreter for isolated diagnostics instead of
        # guessing that a second venv exists under every project root.
        self.python_executable = Path(sys.executable)
        self.storage_root = storage_root or self.project_root / ".devkit"
        if self.storage_root.is_symlink():
            raise KitError("Le dossier de l’atelier doit être un dossier local réel.")
        self.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.reports = self.storage_root / "diagnostics"
        self.artifacts = self.storage_root / "exports"
        for directory in (self.reports, self.artifacts):
            if directory.is_symlink():
                raise KitError("Un dossier de l’atelier pointe vers un lien symbolique.")
            directory.mkdir(mode=0o700, exist_ok=True)
        self.patches = PatchWorkspace(self.project_root, self.storage_root)
        self.token = secrets.token_urlsafe(32)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="come-ai-workshop")
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._artifacts: dict[str, Path] = {}
        self._evolution: Any | None = None
        self._busy_check = busy_check or (lambda: False)

    def close(self) -> None:
        if self._evolution is not None:
            self._evolution.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def evolution(self) -> Any:
        with self._lock:
            if self._evolution is None:
                from devkit.evolution_manager import EvolutionManager

                self._evolution = EvolutionManager(
                    self.project_root, self.storage_root, python_executable=self.python_executable
                )
            return self._evolution

    def start_evolution(self, task_id: str | None = None, *, max_requests: int = 2, max_attempts: int = 2, demo: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._busy_check():
                raise KitError("Côme AI exécute déjà une tâche locale. Relance le cycle lorsque le workspace est disponible.")
            if any(job["status"] in {"queued", "running"} for job in self._jobs.values()):
                raise KitError("Un diagnostic ou un cycle est déjà en cours dans l’atelier.")
            self.evolution()  # Validate local configuration before scheduling.
            job_id = uuid.uuid4().hex
            job = {"job_id": job_id, "kind": "evolution", "status": "queued", "candidate_id": None,
                   "report": None, "message": "Cycle de développement en attente."}
            self._jobs[job_id] = job
            self._executor.submit(self._run_evolution, job_id, task_id, max_requests, max_attempts, demo)
            return self._public_job(job)

    def _run_evolution(self, job_id: str, task_id: str | None, max_requests: int, max_attempts: int, demo: bool) -> None:
        with self._lock:
            self._jobs[job_id].update(status="running", message="Diagnostic, génération bornée et validation isolée en cours…")
        try:
            result = self.evolution().run_demo(max_requests=max_requests) if demo else self.evolution().run(task_id, max_requests=max_requests, max_attempts=max_attempts)
            with self._lock:
                self._jobs[job_id].update(status="completed", report=result, candidate_id=None if demo else result.get("candidate_id"),
                                           message=f"Cycle terminé : {result.get('status', 'enregistré')}.")
        except Exception:
            with self._lock:
                self._jobs[job_id].update(status="failed", message="Cycle interrompu. Consulte son historique persistant dans l’atelier.")

    def latest_report(self) -> dict[str, Any] | None:
        path = self.reports / "latest.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            return None
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            return report if isinstance(report, dict) else None
        except (OSError, ValueError):
            return None

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = [self._public_job(job) for job in self._jobs.values() if job["status"] in {"queued", "running"}]
        latest = self.latest_report()
        return {
            "available": True,
            "version": "1.0",
            "remote_model_used": False,
            "automatic_application": False,
            "latest_report": latest,
            "diagnostics_current": bool(latest and latest.get("source_fingerprint") == source_fingerprint(self.project_root)),
            "active_jobs": active,
            "candidates": self.patches.list_candidates(),
            "transactions": self.patches.list_transactions(),
            "source_files": [{"path": item["path"], "size_bytes": item["size_bytes"]} for item in source_inventory(self.project_root)],
        }

    def start_diagnostics(self, candidate_id: str | None = None) -> dict[str, Any]:
        # Resolve a candidate synchronously before allocating a job. It cannot
        # be swapped for a browser-provided disk path.
        root = self.patches.candidate_path(candidate_id) if candidate_id else self.project_root
        with self._lock:
            if any(job["status"] in {"queued", "running"} for job in self._jobs.values()):
                raise KitError("Un diagnostic est déjà en cours dans l’atelier.")
            job_id = uuid.uuid4().hex
            job = {"job_id": job_id, "status": "queued", "candidate_id": candidate_id, "report": None, "message": "Diagnostic local en attente."}
            self._jobs[job_id] = job
            self._executor.submit(self._run_diagnostics, job_id, root, candidate_id)
            # Retain only a small transient history; reports themselves persist.
            terminal = [key for key, item in self._jobs.items() if item["status"] not in {"queued", "running"}]
            for key in terminal[:-20]:
                del self._jobs[key]
            return self._public_job(job)

    def _run_diagnostics(self, job_id: str, root: Path, candidate_id: str | None) -> None:
        with self._lock:
            self._jobs[job_id].update(status="running", message="Tests et diagnostics dans une copie isolée…")
        try:
            report = run_diagnostics(
                root,
                report_dir=self.reports if candidate_id is None else self.storage_root / "candidate_reports" / str(candidate_id),
                python_executable=self.python_executable,
                require_sandbox=candidate_id is not None,
            )
            if candidate_id:
                try:
                    self.patches.mark_validation(candidate_id, report)
                except ValueError:
                    # Keep the actual failing/blocked report visible. A failed
                    # test never turns into a generic worker error or approval.
                    pass
            with self._lock:
                self._jobs[job_id].update(status="completed", report=report, message="Diagnostic terminé.")
        except Exception:
            # Neither exception text nor a traceback crosses the UI boundary.
            # The runner's bounded report holds any intended technical output.
            with self._lock:
                self._jobs[job_id].update(status="failed", message="Le diagnostic n’a pas pu être finalisé. Consulte la commande de maintenance locale.")

    def job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KitError("Diagnostic introuvable dans cette session.")
            return self._public_job(self._jobs[job_id])

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {"kind": job.get("kind", "diagnostics"), **{key: job[key] for key in ("job_id", "status", "candidate_id", "report", "message")}}

    def _export(self, *, issue: dict[str, Any] | None = None) -> dict[str, Any]:
        artifact_id = uuid.uuid4().hex
        path = self.artifacts / (f"demande-{artifact_id}.zip" if issue else f"projet-{artifact_id}.zip")
        if issue:
            result = build_issue_bundle(self.project_root, path, diagnostic_report=self.latest_report(), **issue)
        else:
            result = export_snapshot(self.project_root, path, diagnostic_report=self.latest_report())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        with self._lock:
            self._artifacts[artifact_id] = path
        return {
            "artifact_id": artifact_id,
            "filename": path.name,
            "file_count": result.get("file_count"),
            "bytes": path.stat().st_size,
            "download_url": f"/api/devkit/artifacts/{artifact_id}",
            "remote_model_used": False,
        }

    def export_project(self) -> dict[str, Any]:
        return self._export()

    def export_issue(self, *, title: str, description: str, errors: str = "", selected_files: list[str] | None = None) -> dict[str, Any]:
        return self._export(issue={"title": title, "description": description, "errors": errors, "selected_files": selected_files})

    def artifact_path(self, artifact_id: str) -> Path:
        with self._lock:
            path = self._artifacts.get(artifact_id)
        if path is None or path.is_symlink() or not path.is_file():
            raise KitError("Archive introuvable dans cette session. Crée un nouvel export.")
        return path

    def apply(self, candidate_id: str) -> dict[str, Any]:
        with self._lock:
            if any(job["status"] in {"queued", "running"} for job in self._jobs.values()):
                raise KitError("Attends la fin du diagnostic avant d’appliquer un correctif.")
            return self.patches.apply(candidate_id)

    def rollback(self, transaction_id: str) -> dict[str, Any]:
        with self._lock:
            if any(job["status"] in {"queued", "running"} for job in self._jobs.values()):
                raise KitError("Attends la fin du diagnostic avant le retour arrière.")
            return self.patches.rollback(transaction_id)
