"""Local facade for a bounded, explicitly started autonomous development run."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from devkit.evolution import EvolutionEngine
from devkit.evolution_providers import ProviderSettings, status_provider
from devkit.exporting import KitError
from workspace_core import read_dotenv


class EvolutionManager:
    def __init__(self, project_root: Path, storage_root: Path, *, python_executable: Path | None = None):
        self.project_root = project_root
        self.storage_root = storage_root
        self.python_executable = Path(python_executable or project_root / ".venv" / "bin" / "python")
        self.directory = storage_root / "evolution"
        if self.directory.is_symlink():
            raise KitError("Le dossier d’évolution doit être un dossier local réel.")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        from devkit.intelligence_router import create_routed_provider

        self.engine = EvolutionEngine(project_root, storage_root, python_executable=self.python_executable,
                                      provider_factory=create_routed_provider)
        self._cancel = threading.Event()

    def settings(self) -> ProviderSettings:
        path = self.directory / "config.json"
        if path.is_symlink():
            raise KitError("La configuration d’évolution ne peut pas être un lien symbolique.")
        if path.is_file():
            if path.stat().st_size > 16_000:
                raise KitError("Configuration d’évolution trop volumineuse.")
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.mode = data.pop("mode", "automatic")
                return ProviderSettings(**data)
            except (ValueError, TypeError):
                raise KitError("Configuration d’évolution invalide. Enregistre à nouveau les réglages.") from None
        # This reader runs inside the application. Neither the dictionary nor
        # any credential value is returned, logged, sent to a model or persisted.
        values = read_dotenv(self.project_root / ".env")
        self.mode = "automatic"
        confirmed = os.environ.get("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED", values.get("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED", "false")).casefold() == "true"
        return ProviderSettings(provider="gemini", model="auto", allow_remote=confirmed, gemini_free_project_confirmed=confirmed)

    def configure(self, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        mode = data.pop("mode", "automatic")
        if mode not in {"automatic", "offline", "performance"}:
            raise KitError("Mode de développement invalide.")
        if mode == "offline":
            data.update(provider="ollama", allow_remote=False, model=data.get("model") if data.get("provider") == "ollama" and data.get("model") != "auto" else "qwen3.5:2b")
        elif mode == "performance":
            # More room for a structured correction, while keeping the same
            # free-price and request-count gates. No claimed benchmark win.
            data.update(max_output_tokens=6000, timeout_seconds=60)
        settings = ProviderSettings(**data)
        path = self.directory / "config.json"
        if path.is_symlink():
            raise KitError("La configuration d’évolution ne peut pas être un lien symbolique.")
        # Only non-secret, strictly typed settings can reach this file.
        from devkit.patching import _atomic_write

        _atomic_write(path, json.dumps({**asdict(settings), "mode": mode}, ensure_ascii=False, indent=2).encode("utf-8"), 0o600)
        return {**asdict(settings), "mode": mode}

    def overview(self) -> dict[str, Any]:
        settings = self.settings()
        from devkit.model_catalog import ModelCatalog
        from usage_ledger import UsageLedger

        demo_path = self.directory / "latest_demo.json"
        demo = None
        if demo_path.is_file() and not demo_path.is_symlink() and demo_path.stat().st_size <= 512_000:
            try:
                demo = json.loads(demo_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return {
            "mode": getattr(self, "mode", "automatic"),
            "settings": asdict(settings),
            "provider": status_provider(self.project_root, settings),
            "tasks": self.engine.store.list_tasks(),
            "runs": self.engine.store.list_runs(),
            "dashboard": self.engine.store.dashboard(),
            "catalogue": ModelCatalog(self.project_root, self.storage_root).snapshot(),
            "usage": UsageLedger(self.directory / "usage.sqlite3").dashboard_summary(),
            "automatic_deployment": False,
            "scheduling": False,
            "latest_demo": demo,
        }

    def refresh_catalogue(self) -> dict[str, Any]:
        from devkit.model_catalog import ModelCatalog

        settings = self.settings()
        if settings.provider == "ollama" or not settings.allow_remote:
            raise KitError("L’actualisation cloud nécessite un fournisseur distant activé.")
        return ModelCatalog(self.project_root, self.storage_root).refresh(settings.provider, gemini_free_project_confirmed=settings.gemini_free_project_confirmed)

    def run(self, task_id: str | None = None, *, max_requests: int = 2, max_attempts: int = 2) -> dict[str, Any]:
        self._cancel.clear()
        options = {"max_requests": max_requests, "max_attempts": max_attempts, "session_timeout_seconds": 300, "is_cancelled": self._cancel.is_set}
        if task_id:
            return self.engine.run_task(task_id, self.settings(), **options)
        return self.engine.run_next(self.settings(), **options)

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        return {"status": "cancellation_requested", "message": "Arrêt demandé. Aucun nouvel appel ne sera lancé ; l’étape active reste bornée par son délai."}

    def run_demo(self, *, max_requests: int = 2) -> dict[str, Any]:
        """Reproduce a real redaction gap in a copy of Côme's own function.

        Only a fixture module is generated; the original implementation and
        private data remain untouched. The acceptance tests are outside the
        model's selected source scope and cannot be rewritten by its proposal.
        """
        import inspect
        import uuid
        from workspace_core import safe_error, compact
        from devkit.intelligence_router import create_routed_provider
        from devkit.patching import PatchWorkspace, _atomic_write

        self._cancel.clear()
        demo_id = uuid.uuid4().hex
        demo_dir = self.directory / "demos" / demo_id
        if demo_dir.parent.is_symlink():
            raise KitError("Le dossier de démonstration doit être local.")
        root = demo_dir / "source"
        root.mkdir(parents=True, mode=0o700)
        _atomic_write(root / "error_redaction.py", ("import re\nfrom formatting import compact\n\n" + inspect.getsource(safe_error)).encode(), 0o600)
        # Preserve the actual formatting dependency; only its string path is
        # relevant here. This support module is outside the model's write scope.
        formatting = "from typing import Any\n\ndef to_jsonable(value):\n    if not isinstance(value, str):\n        raise TypeError('Fixture expects text')\n    return value\n\n" + inspect.getsource(compact)
        _atomic_write(root / "formatting.py", formatting.encode(), 0o600)
        tests = root / "tests"
        tests.mkdir()
        test_code = (
            "from error_redaction import safe_error\n"
            "def test_openrouter_key_is_masked():\n"
            "    token = 'sk-or-v1-' + 'x' * 32\n"
            "    assert token not in safe_error(RuntimeError('failure: ' + token))\n"
            "def test_gemini_key_is_still_masked():\n"
            "    token = 'AIza' + 'y' * 35\n"
            "    assert token not in safe_error(RuntimeError(token))\n"
            "def test_normal_error_remains_readable():\n"
            "    assert 'failure' in safe_error(RuntimeError('failure'))\n"
        )
        _atomic_write(tests / "test_redaction.py", test_code.encode(), 0o600)
        state = demo_dir / "state"
        engine = EvolutionEngine(root, state, python_executable=self.python_executable,
                                 provider_factory=lambda _, settings: create_routed_provider(self.project_root, settings))
        task = engine.store.add_task("Corriger la redaction OpenRouter de Côme AI — démonstration isolée",
            "La fonction safe_error copiée du projet ne masque pas un jeton OpenRouter brut. Ajouter cette protection sans perdre les protections Gemini et chemins existantes. Aucun fichier de tests ne peut être modifié.",
            ["error_redaction.py"], "Les 3 tests de redaction doivent réussir. Retourner un patch minimal ou le fichier complet.")
        result = engine.run_task(task["task_id"], self.settings(), max_requests=max_requests, max_attempts=min(2, max_requests),
                                 session_timeout_seconds=300, is_cancelled=self._cancel.is_set)
        result.update(demo_id=demo_id, demo=True, main_application_modified=False, independent_review="pending")
        if result.get("candidate_id"):
            result["diff"] = PatchWorkspace(root, state).preview(result["candidate_id"])["diff"]
        _atomic_write(self.directory / "latest_demo.json", json.dumps(result, ensure_ascii=False, indent=2).encode(), 0o600)
        return result
