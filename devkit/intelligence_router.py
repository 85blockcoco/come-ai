"""Price-gated correction routing with bounded, same-provider fallbacks."""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from devkit.evolution_providers import ProviderSettings, ProviderUnavailable, _settings_guard, create_provider, status_provider
from devkit.model_catalog import ModelCatalog, ModelCatalogError
from usage_ledger import UsageLedger


class RoutedCorrectionProvider:
    def __init__(self, project_root: Path, settings: ProviderSettings, *, catalog=None, factory=None):
        self.root = project_root
        self.settings = settings
        self.provider_id = settings.provider
        self.is_remote = self.provider_id != "ollama"
        self.catalog = catalog or ModelCatalog(project_root, project_root / ".devkit")
        self.factory = factory or create_provider
        self.last_usage = {}
        self.remaining_requests = 1
        self.ledger = UsageLedger(project_root / ".devkit" / "evolution" / "usage.sqlite3")
        _settings_guard(settings, allow_unresolved=True)
        if self.is_remote:
            status = status_provider(project_root, settings)
            if not status["configured"] and factory is None:
                raise ProviderUnavailable("La clé fournisseur n’est pas détectée ; aucun appel envoyé.", "missing_configuration")
            if not self.catalog.eligible(self.provider_id):
                self.catalog.refresh(self.provider_id, gemini_free_project_confirmed=settings.gemini_free_project_confirmed)
            self.model_id = self.catalog.choose_model(self.provider_id, requested=settings.model)
        else:
            if settings.model == "auto":
                raise ProviderUnavailable("Sélectionnez le modèle Qwen installé localement.", "missing_configuration")
            self.model_id = settings.model

    def propose(self, context):
        self.last_usage = {"generation_requests": 0, "input_tokens": None, "output_tokens": None, "total_tokens": None}
        started = time.monotonic()
        tried = []
        while len(tried) < min(3, self.remaining_requests):
            tried.append(self.model_id)
            left = self.settings.timeout_seconds - (time.monotonic() - started)
            if left < 1:
                raise ProviderUnavailable("Le délai de routage est atteint.", "transient")
            provider = self.factory(self.root, replace(self.settings, model=self.model_id, timeout_seconds=left))
            error = None
            try:
                result = provider.propose(context)
            except ProviderUnavailable as caught:
                error = caught
            usage = provider.last_usage or {}
            calls = usage.get("generation_requests", 0)
            self.last_usage["generation_requests"] += calls if isinstance(calls, int) and calls >= 0 else 0
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                value = usage.get(field)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    self.last_usage[field] = (self.last_usage[field] or 0) + value
            self.last_usage["latency_ms"] = round((time.monotonic() - started) * 1000)
            if calls:
                self.ledger.record_execution(provider=self.provider_id, model=self.model_id, mode="automatic", task_kind="code.correction",
                    outcome="failed" if error else "succeeded", latency_ms=round(usage.get("latency_ms") or 0),
                    input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"), total_tokens=usage.get("total_tokens"),
                    retry_count=0, fallback_state="used" if len(tried) > 1 else "not_used", verification_state="not_verified",
                    error_category=error.category if error else None,
                    retry_after_seconds=getattr(error, "retry_after_seconds", None) if error else None)
            if error is None:
                return result
            # Auth/quota/malformed data do not cause cloud rotation. Only an
            # unavailable model/server may use a different, verified free ID.
            if not self.is_remote or error.http_status not in {404, 500, 502, 503, 504} or len(tried) >= self.remaining_requests:
                raise error
            try:
                self.model_id = self.catalog.choose_model(self.provider_id, exclude_models=tried)
            except ModelCatalogError:
                raise error from None
        raise ProviderUnavailable("Le budget de requêtes du cycle est atteint.", "quota")


def create_routed_provider(project_root: Path, settings: ProviderSettings):
    try:
        return RoutedCorrectionProvider(project_root, settings)
    except ModelCatalogError as error:
        raise ProviderUnavailable(str(error), "price_unknown") from None
