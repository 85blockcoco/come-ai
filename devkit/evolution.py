"""Bounded model-assisted repairs that stop at a reviewable isolated candidate.

The engine is invoked explicitly. It neither schedules itself nor exposes an
application/rollback operation to a model. Reports and requests contain only
the source selected by the user and redacted diagnostics.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from types import MappingProxyType
from typing import Callable
import zipfile

from devkit.diagnostics import run_diagnostics
from devkit.exporting import KitError, build_issue_bundle, redact_text, source_fingerprint, source_path_allowed
from devkit.patching import PatchError, PatchWorkspace
from devkit.proposals import CodeProposal, ProposalContext
from devkit.evolution_providers import ProviderSettings, ProviderUnavailable, create_provider
from devkit.evolution_store import EvolutionStore


MAX_ITERATIONS = 3
MAX_REQUESTS = 3
MAX_CONTEXT_BYTES = 180_000
MAX_FEEDBACK_BYTES = 24_000


class EvolutionError(KitError):
    """A safe error in the explicit repair workflow."""


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _bounded(value: object, root: Path, limit: int = 12_000) -> str:
    text = redact_text(str(value), root)
    text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password|authorization)\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1[masqué]", text)
    return text.encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="ignore")


def _safe_report(report: dict, root: Path) -> dict:
    """Persist only measurable diagnostic fields; never arbitrary injected data."""
    if not isinstance(report, dict):
        raise EvolutionError("Le diagnostic n’a pas retourné de rapport exploitable.")
    result = {key: report.get(key) for key in (
        "status", "created_at", "source_fingerprint", "sandbox_used", "pytest_receipt_verified",
        "duration_seconds", "network",
    )}
    result.update({key: _count(report.get(key)) for key in (
        "tests_executed", "tests_passed", "tests_failed", "tests_skipped", "tests_collected", "collection_errors",
    )})
    result["checks"] = []
    if "targeted_tests" in report:
        from devkit.diagnostics import validate_targeted_tests

        result["targeted_tests"] = validate_targeted_tests(report["targeted_tests"])
    for check in report.get("checks", [])[:20]:
        if isinstance(check, dict):
            result["checks"].append({
                "name": _bounded(check.get("name", ""), root, 120),
                "status": check.get("status") if check.get("status") in {"passed", "failed", "blocked", "skipped"} else "blocked",
                "output": _bounded(check.get("output", ""), root),
            })
    return result


def _write_json(path: Path, value: dict) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise EvolutionError("Un dossier de rapport est remplacé par un lien symbolique.")
    descriptor, temporary = tempfile.mkstemp(prefix=".evolution-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def evaluate_candidate(baseline: dict, candidate: dict, changed_files: list[dict]) -> dict:
    """Deterministic evidence gate; every release remains an explicit user action."""
    paths = [item.get("path", "") for item in changed_files if isinstance(item, dict)]
    core_or_policy = any(
        path.endswith((".py", ".js", ".toml", ".ini"))
        or path.startswith(("requirements", "devkit/", "tests/"))
        or Path(path).name == "conftest.py"
        for path in paths
    )
    category = "B" if core_or_policy else "A"
    checks = candidate.get("checks", [])
    pytest_passed = any(isinstance(check, dict) and check.get("name") == "pytest" and check.get("status") == "passed" for check in checks)
    proof = (candidate.get("status") == "passed" and pytest_passed
             and candidate.get("sandbox_used") is True and candidate.get("pytest_receipt_verified") is True
             and _count(candidate.get("tests_executed")) > 0)
    regression = (_count(candidate.get("tests_executed")) < _count(baseline.get("tests_executed"))
                  or _count(candidate.get("tests_failed")) > 0
                  or baseline.get("targeted_tests") != candidate.get("targeted_tests"))
    protected = any(path.startswith("tests/") or Path(path).name in {"conftest.py", "pytest.ini"} for path in paths)
    if not proof:
        reason = "La copie doit réussir des tests effectivement terminés sous isolation OS."
    elif regression:
        reason = "Le candidat réduit le nombre de tests exécutés ou conserve des échecs."
    elif protected:
        reason = "Les tests ou leur configuration changent : revue manuelle de leur intégrité obligatoire."
    elif category == "B":
        reason = "Le code ou les dépendances changent : validation humaine obligatoire avant application."
    else:
        reason = "Candidat validé dans une copie ; application manuelle requise dans cette livraison."
    return {"category": category, "status": "needs_review" if proof and not regression else "failed",
            "tests_validated": bool(proof and not regression), "reason": reason,
            "test_integrity_review_required": protected, "auto_release_eligible": False,
            "main_application_modified": False, "verification": "sandbox_tests_single_provider"}


class EvolutionEngine:
    def __init__(self, project_root: Path, storage_root: Path, *, provider_factory=None,
                 diagnostic_runner=None, python_executable: Path | None = None):
        self.project_root = Path(project_root).resolve(strict=True)
        self.storage_root = Path(storage_root).absolute()
        self.patches = PatchWorkspace(self.project_root, self.storage_root)
        self.store = EvolutionStore(self.storage_root)
        self.evolution_dir = self.storage_root / "evolution"
        self.evolution_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.provider_factory = provider_factory or create_provider
        self.diagnostic_runner = diagnostic_runner or run_diagnostics
        self.python_executable = Path(python_executable or self.project_root / ".venv/bin/python")

    @contextmanager
    def execution_lock(self):
        """Shared nonblocking process lock; no simultaneous repair/test sessions."""
        descriptor = os.open(self.evolution_dir / "engine.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise EvolutionError("Une session de développement est déjà en cours.") from None
            yield
        finally:
            os.close(descriptor)

    @staticmethod
    def _limits(max_attempts: int, max_requests: int, timeout: float) -> tuple[int, int, float]:
        if any(not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 3 for value in (max_attempts, max_requests)):
            raise EvolutionError("La session accepte de 1 à 3 essais et requêtes au maximum.")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 1 <= timeout <= 1800:
            raise EvolutionError("Le délai maximal doit être compris entre 1 et 1800 secondes.")
        return max_attempts, max_requests, float(timeout)

    def run_next(self, settings: ProviderSettings, *, max_attempts: int = 2, max_requests: int = 2,
                 session_timeout_seconds: float = 300, is_cancelled: Callable[[], bool] | None = None) -> dict:
        self._limits(max_attempts, max_requests, session_timeout_seconds)
        with self.execution_lock():
            self.store.recover_interrupted()
            task = self.store.next_task()
            if task is None:
                return {"run_id": None, "status": "idle", "candidate_id": None, "main_application_modified": False}
            return self._run(task["task_id"], settings, max_attempts, max_requests, session_timeout_seconds, is_cancelled)

    def run_task(self, task_id: str, settings: ProviderSettings, *, max_attempts: int = 2, max_requests: int = 2,
                 session_timeout_seconds: float = 300, is_cancelled: Callable[[], bool] | None = None) -> dict:
        self._limits(max_attempts, max_requests, session_timeout_seconds)
        with self.execution_lock():
            self.store.recover_interrupted()
            if self.store.get_task(task_id)["status"] in {"waiting_provider", "failed", "cancelled"}:
                self.store.update_task(task_id, "queued")
            return self._run(task_id, settings, max_attempts, max_requests, session_timeout_seconds, is_cancelled)

    def _run(self, task_id, settings, max_attempts, max_requests, timeout, is_cancelled):
        task = self.store.claim_task(task_id)
        run = self.store.begin_run(task_id, settings.provider, settings.model, max_attempts=max_attempts, max_requests=max_requests)
        run_id = run["run_id"]
        started = time.monotonic()
        deadline = started + timeout
        candidate_id = None

        def checkpoint():
            if is_cancelled and is_cancelled():
                raise _Cancelled()
            if time.monotonic() >= deadline:
                raise _Deadline()

        def remaining():
            checkpoint()
            return max(1, int(deadline - time.monotonic()))

        def finish(status, reason):
            self.store.record_event(run_id, "finish", status, reason)
            return self.store.finish_run(run_id, status, candidate_id=candidate_id, reason=reason)

        try:
            checkpoint()
            from devkit.diagnostics import validate_targeted_tests

            targeted_tests = validate_targeted_tests(task.get("targeted_tests"), self.project_root)
            diagnostic_options = {"targeted_tests": targeted_tests} if targeted_tests is not None else {}
            # The provider performs only configuration checks at construction.
            # A missing setup terminates before an expensive baseline/retry loop.
            provider = self.provider_factory(self.project_root, replace(settings, timeout_seconds=min(settings.timeout_seconds, remaining())))
            self.store.record_route(run_id, getattr(provider, "provider_id", settings.provider), getattr(provider, "model_id", settings.model))
            if provider.is_remote and not settings.allow_remote:
                raise ProviderUnavailable("L’usage d’un fournisseur distant doit être activé explicitement.", "missing_configuration")
            run_dir = self.evolution_dir / "runs" / run_id
            if run_dir.parent.is_symlink() or run_dir.is_symlink():
                raise EvolutionError("Un dossier de session est remplacé par un lien symbolique.")
            run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
            selected = task["selected_files"]
            self.store.record_event(run_id, "baseline", "running", "Diagnostic réel des sources actuelles.")
            baseline = self.diagnostic_runner(self.project_root, report_dir=run_dir / "baseline",
                                               python_executable=self.python_executable, timeout_seconds=remaining(), require_sandbox=False, **diagnostic_options)
            baseline = _safe_report(baseline, self.project_root)
            checkpoint()
            _write_json(run_dir / "baseline.json", baseline)
            self.store.record_event(run_id, "baseline", baseline.get("status", "blocked"), "Diagnostic de référence terminé.", data={
                "tests_passed": baseline["tests_passed"], "tests_failed": baseline["tests_failed"], "tests_skipped": baseline["tests_skipped"],
            })
            if baseline.get("status") not in {"passed", "failed"} or baseline.get("source_fingerprint") != source_fingerprint(self.project_root):
                return finish("failed", "Le diagnostic de référence est bloqué ou ses sources ont changé.")
            bundle = run_dir / "request.zip"
            build_issue_bundle(self.project_root, bundle, title=task["title"], description=task["description"],
                               selected_files=selected, diagnostic_report=baseline,
                               errors="\n".join(check["output"] for check in baseline["checks"] if check["status"] == "failed"))
            with zipfile.ZipFile(bundle) as archive:
                issue = json.loads(archive.read("ISSUE.json"))
                sources = {path: archive.read("source/" + path).decode("utf-8") for path in issue["selected_files"]}
            issue["acceptance"] = _bounded(task.get("acceptance", ""), self.project_root, 8000)
            issue["baseline"] = baseline
            issue["application_policy"] = "Retourner uniquement un correctif du périmètre ; validation et application restent locales et manuelles."
            if len(json.dumps(issue, ensure_ascii=False).encode()) + sum(len(value.encode()) for value in sources.values()) > MAX_CONTEXT_BYTES:
                return finish("failed", "La demande dépasse la limite de contexte ; réduire les fichiers sélectionnés.")
            feedback = None
            dispatched = 0
            for attempt in range(1, min(max_attempts, max_requests) + 1):
                checkpoint()
                if dispatched >= max_requests:
                    return finish("failed", "La limite de requêtes est atteinte ; aucun nouvel appel lancé.")
                if baseline["source_fingerprint"] != source_fingerprint(self.project_root):
                    return finish("failed", "Les sources principales ont changé ; une nouvelle référence est nécessaire.")
                # Recreate a provider with the actual remaining timeout. A retry
                # always starts from the original sources, never its predecessor.
                if attempt > 1 or remaining() < settings.timeout_seconds:
                    provider = self.provider_factory(self.project_root, replace(settings, timeout_seconds=min(settings.timeout_seconds, remaining())))
                payload = dict(issue)
                if feedback:
                    payload["previous_attempt"] = feedback
                self.store.record_event(run_id, "generation", "running", "Demande de correctif au modèle choisi.", data={"attempt": attempt})
                checkpoint()
                provider.remaining_requests = max_requests - dispatched
                try:
                    proposal = provider.propose(ProposalContext(MappingProxyType(payload), MappingProxyType(sources)))
                except ProviderUnavailable as error:
                    self._record_usage(run_id, provider)
                    dispatched += _count(getattr(provider, "last_usage", {}).get("generation_requests"))
                    if error.category == "malformed_output" and attempt < min(max_attempts, max_requests):
                        # str(error) only ever holds authored messages with sanitized
                        # key names or finish-reason enums; never prompts or content.
                        detail = str(error).splitlines()[0][:300]
                        feedback = {"attempt": attempt, "status": "rejected", "errors": "La réponse n’est pas un correctif JSON exploitable (" + detail + "). Retourner exclusivement patch ou files, dans le périmètre initial."}
                        self.store.record_event(run_id, "generation", "rejected", feedback["errors"], data={"attempt": attempt})
                        continue
                    raise
                except Exception:
                    self._record_usage(run_id, provider)
                    raise
                self._record_usage(run_id, provider)
                dispatched += _count(getattr(provider, "last_usage", {}).get("generation_requests"))
                self.store.record_route(run_id, getattr(provider, "provider_id", settings.provider), getattr(provider, "model_id", settings.model))
                checkpoint()
                if not isinstance(proposal, CodeProposal) or bool(proposal.patch) == bool(proposal.files):
                    raise ProviderUnavailable("Le modèle doit retourner un patch ou des fichiers, exclusivement.", "malformed_output")
                try:
                    if baseline["source_fingerprint"] != source_fingerprint(self.project_root):
                        return finish("failed", "Les sources principales ont changé pendant la génération.")
                    staged = (self.patches.stage_patch(proposal.patch, allowed_paths=selected) if proposal.patch
                              else self.patches.stage_files(dict(proposal.files or {}), allowed_paths=selected))
                except (PatchError, KitError):
                    feedback = {"attempt": attempt, "status": "rejected", "errors": "Correctif refusé : format, périmètre ou sources invalides. Retourner un correctif complet sur les sources initiales."}
                    self.store.record_event(run_id, "staging", "rejected", feedback["errors"], data={"attempt": attempt})
                    if attempt >= min(max_attempts, max_requests):
                        return finish("failed", "Les correctifs proposés restent invalides dans le périmètre demandé.")
                    continue
                candidate_id = staged["candidate_id"]
                self.store.record_event(run_id, "staging", "completed", "Copie isolée et aperçu créés.", data={"attempt": attempt, "candidate_id": candidate_id})
                checkpoint()
                report = self.diagnostic_runner(self.patches.candidate_path(candidate_id), report_dir=run_dir / f"attempt-{attempt}",
                                                 python_executable=self.python_executable, timeout_seconds=remaining(), require_sandbox=True, **diagnostic_options)
                report = _safe_report(report, self.project_root)
                checkpoint()
                _write_json(run_dir / f"attempt-{attempt}.json", report)
                decision = evaluate_candidate(baseline, report, staged["changed_files"])
                if baseline["source_fingerprint"] != source_fingerprint(self.project_root):
                    decision.update(status="failed", reason="Les sources principales ont changé pendant la validation.", tests_validated=False)
                if decision["tests_validated"]:
                    try:
                        self.patches.mark_validation(candidate_id, report)
                    except PatchError:
                        decision.update(status="failed", reason="L’empreinte du candidat ne correspond pas au diagnostic.", tests_validated=False)
                _write_json(run_dir / f"decision-{attempt}.json", decision)
                self.store.record_event(run_id, "validation", decision["status"], decision["reason"], data={
                    "attempt": attempt, "candidate_id": candidate_id, "category": decision["category"],
                    "verification": decision["verification"], "tests_passed": report["tests_passed"],
                    "tests_failed": report["tests_failed"], "tests_skipped": report["tests_skipped"],
                })
                if decision["status"] == "needs_review":
                    return finish("needs_review", decision["reason"])
                if report.get("sandbox_used") is not True:
                    return finish("failed", "Isolation OS indisponible : le candidat ne peut pas être exécuté ou approuvé.")
                feedback = {"attempt": attempt, "status": "failed", "decision": decision,
                            "diff": _bounded(staged["diff"], self.project_root, MAX_FEEDBACK_BYTES // 2),
                            "errors": _bounded("\n".join(check["output"] for check in report["checks"] if check["status"] != "passed"), self.project_root, MAX_FEEDBACK_BYTES // 2)}
            return finish("failed", "La limite d’essais est atteinte ; consulter les candidats et leurs diagnostics.")
        except _Cancelled:
            return finish("cancelled", "Session arrêtée à la demande de l’utilisateur ; les sources principales sont conservées.")
        except _Deadline:
            return finish("failed", "Le délai maximal de la session est atteint ; aucun nouvel appel n’est lancé.")
        except ProviderUnavailable as error:
            self.store.record_event(run_id, "provider", "waiting", str(error), data={"category": error.category})
            return finish("waiting_provider", f"Fournisseur en attente ({error.category}) ; reprise uniquement sur action explicite.")
        except Exception:
            return finish("failed", "La session a rencontré une erreur locale ; consulter les étapes enregistrées.")

    def _record_usage(self, run_id: str, provider) -> None:
        usage = getattr(provider, "last_usage", None)
        if not isinstance(usage, dict):
            return
        measured = {key: value for key in ("input_tokens", "output_tokens", "total_tokens")
                    if isinstance((value := usage.get(key)), int) and not isinstance(value, bool) and value >= 0}
        requests = usage.get("generation_requests")
        if isinstance(requests, int) and not isinstance(requests, bool) and requests >= 0:
            measured["requests"] = requests
        if isinstance(usage.get("latency_ms"), (int, float)) and not isinstance(usage["latency_ms"], bool):
            measured["duration_seconds"] = max(0, usage["latency_ms"]) / 1000
        if measured:
            self.store.record_event(run_id, "usage", "measured", "Consommation déclarée par le fournisseur ; valeurs absentes non estimées.", data=measured)

    def import_diagnostic_issue(self, report: dict) -> dict | None:
        """Create one queued repair from real failures naming permitted source files."""
        clean = _safe_report(report, self.project_root)
        if clean.get("status") != "failed" or clean.get("source_fingerprint") != source_fingerprint(self.project_root):
            return None
        failed = [check for check in clean["checks"] if check["status"] == "failed"]
        if not failed:
            return None
        text = "\n".join(check["output"] for check in failed)
        # Read only the explicitly named permitted files, never walk document,
        # environment, private database or output directories.
        paths = set(re.findall(r"(?<![\w./-])((?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:py|js|css|html))(?=[:\s\"'()]|$)", text))
        selected = sorted(path for path in paths if source_path_allowed(path)
                          and not (self.project_root / path).is_symlink() and (self.project_root / path).is_file())[:10]
        if not selected:
            return None
        title = "Corriger les échecs du diagnostic local"
        for existing in self.store.list_tasks(limit=100):
            if existing.get("title") == title and existing.get("selected_files") == selected and existing.get("status") in {"queued", "running", "waiting_provider", "needs_review"}:
                return existing
        return self.store.add_task(title, "Le diagnostic de référence présente des échecs réels. Corriger leur cause dans le périmètre sélectionné.\n\n" + _bounded(text, self.project_root, 12_000),
                                   selected, acceptance="Tous les diagnostics et tests existants doivent réussir sans réduire leur nombre.", priority=10)


class _Cancelled(Exception):
    pass


class _Deadline(Exception):
    pass


__all__ = ["EvolutionEngine", "EvolutionError", "evaluate_candidate"]
