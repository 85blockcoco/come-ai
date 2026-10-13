"""Explicit metadata discovery for the zero-spend evolution workshop.

There is no generation request here. Gemini metadata proves API visibility,
not a free account tier, remaining quota, tool support or billing status. Its
text-only price evidence is a conservative list checked against Google's
official pricing page on 2026-10-13. OpenRouter price evidence comes from its
public model catalogue; every declared price must explicitly equal zero.

Only normalized metadata is persisted. Credentials are loaded at request time,
used in a header, and never included in the cache or a public error.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

from devkit.exporting import KitError


GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
GEMINI_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
GEMINI_METADATA_REFERENCE = "https://ai.google.dev/api/models"
OPENROUTER_METADATA_REFERENCE = "https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties"
PRICE_REFERENCE_DATE = "2026-10-13"
CATALOG_TTL_SECONDS = 24 * 60 * 60
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_MODELS = 2000
GEMINI_FREE_TEXT_MODELS = frozenset({
    "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
})
# This is a preference, not a quality benchmark or an availability claim.
GEMINI_PREFERENCE = (
    "gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-pro",
    "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite",
)
_GEMINI_ID = re.compile(r"gemini-[a-z0-9][a-z0-9.-]{0,95}\Z")
_OPENROUTER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_SECRET_FRAGMENT = re.compile(r"(?:AIza|sk-(?:proj|or|ant)-|sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]+|gsk_[A-Za-z0-9]+|hf_[A-Za-z0-9]{16,})")
_CAPABILITIES = frozenset({"text", "code", "function_calling", "structured_output", "long_context"})
Transport = Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None, float], dict[str, Any]]


class ModelCatalogError(KitError):
    """A bounded catalogue failure safe to show without upstream details."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age(value: object) -> float | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return None
        age = time.time() - stamp.timestamp()
        return age if age >= -60 else None
    except (ValueError, OverflowError, OSError):
        return None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 100_000_000 else None


def _model_id(value: object, provider: str) -> str | None:
    if not isinstance(value, str) or _SECRET_FRAGMENT.search(value) or "://" in value:
        return None
    if provider == "gemini":
        value = value.removeprefix("models/")
        return value if _GEMINI_ID.fullmatch(value) else None
    return value if _OPENROUTER_ID.fullmatch(value) else None


def _zero_prices(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, dict) or not {"prompt", "completion"}.issubset(raw) or not 2 <= len(raw) <= 32:
        return None
    result = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _FIELD.fullmatch(key) or isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 128:
            return None
        try:
            price = Decimal(str(value))
            if not price.is_finite() or price != 0:
                return None
        except (InvalidOperation, ValueError):
            return None
        result[key] = "0"
    return result


def _normalized_model(raw: dict, provider: str, free_confirmed: bool) -> dict | None:
    model_id = _model_id(raw.get("name") if provider == "gemini" else raw.get("id"), provider)
    if model_id is None:
        return None
    if provider == "gemini":
        methods = sorted({value for value in raw.get("supportedGenerationMethods", [])
                          if isinstance(value, str) and value in {"generateContent", "countTokens", "embedContent", "batchGenerateContent"}}) if isinstance(raw.get("supportedGenerationMethods"), list) else []
        generates = "generateContent" in methods
        price_verified = free_confirmed and model_id in GEMINI_FREE_TEXT_MODELS
        capabilities = ["code", "text"] if generates else []
        return {
            "model_id": model_id, "provider_id": provider, "accessible": True,
            "generation_methods": methods, "capabilities": capabilities,
            "input_token_limit": _integer(raw.get("inputTokenLimit")),
            "output_token_limit": _integer(raw.get("outputTokenLimit")),
            "price_status": "zero_confirmed" if price_verified else "unknown",
            "price_evidence": "official_text_standard_free_tier_and_user_declaration" if price_verified else None,
            "price_reference": GEMINI_PRICING_URL if model_id in GEMINI_FREE_TEXT_MODELS else None,
            "price_reference_date": PRICE_REFERENCE_DATE if model_id in GEMINI_FREE_TEXT_MODELS else None,
            "quota_status": "unknown", "prices": None,
        }
    # A suffix alone is insufficient; every price in the response must be zero.
    prices = _zero_prices(raw.get("pricing"))
    params = raw.get("supported_parameters")
    supported = {item for item in params if isinstance(item, str)} if isinstance(params, list) else set()
    architecture = raw.get("architecture")
    outputs = architecture.get("output_modalities") if isinstance(architecture, dict) else None
    # Older catalogue responses default to text; explicitly other modalities do not.
    generates = outputs is None or (isinstance(outputs, list) and "text" in outputs)
    capabilities = {"code", "text"} if generates else set()
    if "tools" in supported:
        capabilities.add("function_calling")
    if "response_format" in supported or "structured_outputs" in supported:
        capabilities.add("structured_output")
    context = _integer(raw.get("context_length"))
    if context is not None and context >= 128_000:
        capabilities.add("long_context")
    verified = model_id.endswith(":free") and prices is not None
    top = raw.get("top_provider")
    return {
        "model_id": model_id, "provider_id": provider, "accessible": True,
        "generation_methods": ["chat_completions"] if generates else [],
        "capabilities": sorted(capabilities), "input_token_limit": context,
        "output_token_limit": _integer(top.get("max_completion_tokens")) if isinstance(top, dict) else None,
        "price_status": "zero_confirmed" if verified else "unknown",
        "price_evidence": "public_catalogue_all_declared_prices_zero" if verified else None,
        "price_reference": OPENROUTER_METADATA_REFERENCE if verified else None,
        "price_reference_date": None, "quota_status": "unknown", "prices": prices if verified else None,
    }


class ModelCatalog:
    """Persistent, inert snapshot; only ``refresh`` performs metadata requests.

    ``storage_root`` is normally ``project/.devkit``. A refreshed cloud snapshot
    is selectable for 24 hours. Reading status never refreshes it or consumes a
    generation request. An expired snapshot remains visible but is ineligible.
    """

    def __init__(self, project_root: Path, storage_root: Path, transport: Transport | None = None):
        project = Path(project_root).absolute()
        if project.is_symlink() or not project.is_dir():
            raise ModelCatalogError("Le catalogue exige un projet local existant.")
        self.project_root = project.resolve()
        self.storage_root = Path(storage_root).absolute()
        self.directory = self.storage_root / "evolution"
        self.path = self.directory / "catalogue.json"
        self.transport = transport
        self._assert_paths()

    def _assert_paths(self) -> None:
        for path in (self.storage_root, self.directory, self.path):
            if path.is_symlink():
                raise ModelCatalogError("Le stockage du catalogue doit rester local, sans lien symbolique.")
        for path in self.storage_root.parents:
            if path.is_symlink():
                raise ModelCatalogError("Le stockage du catalogue doit rester local, sans lien symbolique.")

    def _read(self) -> dict:
        self._assert_paths()
        if not self.path.exists():
            return {"schema_version": 1, "providers": {}}
        try:
            if self.path.stat().st_size > MAX_CATALOG_BYTES:
                raise ModelCatalogError("Le catalogue sauvegardé dépasse la taille autorisée.")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("providers"), dict):
                raise ValueError("schema")
            clean = {"schema_version": 1, "providers": {}}
            for provider in ("gemini", "openrouter"):
                entry = raw["providers"].get(provider)
                if not isinstance(entry, dict) or _age(entry.get("verified_at")) is None or not isinstance(entry.get("models"), list) or len(entry["models"]) > MAX_MODELS:
                    continue
                models = []
                confirmed = entry.get("gemini_free_project_confirmed") is True
                for item in entry["models"]:
                    if not isinstance(item, dict):
                        continue
                    # Re-normalize a saved record instead of trusting arbitrary cached fields.
                    adapted = {"name": item.get("model_id"), "supportedGenerationMethods": item.get("generation_methods"),
                               "inputTokenLimit": item.get("input_token_limit"), "outputTokenLimit": item.get("output_token_limit")}
                    if provider == "openrouter":
                        adapted = {"id": item.get("model_id"), "pricing": item.get("prices"), "context_length": item.get("input_token_limit"),
                                   "top_provider": {"max_completion_tokens": item.get("output_token_limit")},
                                   "architecture": {"output_modalities": ["text"] if "chat_completions" in item.get("generation_methods", []) else []},
                                   "supported_parameters": [param for capability, param in (("function_calling", "tools"), ("structured_output", "response_format"))
                                                            if isinstance(item.get("capabilities"), list) and capability in item["capabilities"]]}
                    model = _normalized_model(adapted, provider, confirmed)
                    if model is not None:
                        models.append(model)
                clean["providers"][provider] = {
                    "provider_id": provider, "verified_at": entry["verified_at"],
                    "source": GEMINI_METADATA_REFERENCE if provider == "gemini" else OPENROUTER_METADATA_REFERENCE,
                    "gemini_free_project_confirmed": confirmed if provider == "gemini" else False,
                    "complete": entry.get("complete") is True, "models": models,
                }
            return clean
        except (OSError, ValueError, UnicodeError, RecursionError, TypeError):
            raise ModelCatalogError("Le catalogue sauvegardé est illisible ; actualisez-le explicitement.") from None

    def snapshot(self) -> dict:
        data = self._read()
        for entry in data["providers"].values():
            age = _age(entry["verified_at"])
            fresh = age is not None and age <= CATALOG_TTL_SECONDS
            entry.update(status="fresh" if fresh else "stale", quota_status="unknown", ttl_seconds=CATALOG_TTL_SECONDS,
                         price_verification="official_document_and_free_project_declaration" if entry["provider_id"] == "gemini" else "catalogue_price_fields")
            for model in entry["models"]:
                model["eligible"] = fresh and model["price_status"] == "zero_confirmed" and "code" in model["capabilities"]
        return {**data, "status": "available" if data["providers"] else "not_refreshed", "network_used": False,
                "generation_requests": 0, "metadata_requests": 0, "budget_api_paid": 0}

    def refresh(self, provider: str, *, gemini_free_project_confirmed: bool = False) -> dict:
        if provider not in {"gemini", "openrouter"}:
            raise ModelCatalogError("Actualisez Gemini ou OpenRouter.")
        if not isinstance(gemini_free_project_confirmed, bool):
            raise ModelCatalogError("La déclaration de palier gratuit doit être explicite.")
        if provider == "gemini" and not gemini_free_project_confirmed:
            raise ModelCatalogError("Confirmez un projet Gemini gratuit sans facturation avant son actualisation.")
        from devkit.evolution_providers import ProviderUnavailable, _credential, bounded_json_transport
        headers = {}
        if provider == "gemini":
            key = _credential(self.project_root, "GEMINI_API_KEY")
            if key is None:
                raise ModelCatalogError("La clé Gemini n’est pas configurée dans le projet.")
            headers = {"x-goog-api-key": key}
        transport = self.transport or bounded_json_transport
        url = GEMINI_MODELS_URL if provider == "gemini" else OPENROUTER_MODELS_URL
        try:
            raw = transport("GET", url, headers, None, 20)
        except ProviderUnavailable:
            raise
        except Exception:
            raise ModelCatalogError("Le fournisseur n’a pas retourné de catalogue exploitable.") from None
        collection = raw.get("models" if provider == "gemini" else "data") if isinstance(raw, dict) else None
        if not isinstance(collection, list) or len(collection) > MAX_MODELS:
            raise ModelCatalogError("Le fournisseur a retourné un catalogue inexploitable.")
        models_by_id = {}
        for item in collection:
            model = _normalized_model(item, provider, gemini_free_project_confirmed) if isinstance(item, dict) else None
            if model is not None:
                models_by_id[model["model_id"]] = model
        entry = {"provider_id": provider, "verified_at": _timestamp(),
                 "source": GEMINI_METADATA_REFERENCE if provider == "gemini" else OPENROUTER_METADATA_REFERENCE,
                 "gemini_free_project_confirmed": gemini_free_project_confirmed if provider == "gemini" else False,
                 "complete": not bool(raw.get("nextPageToken")) if provider == "gemini" else True,
                 "models": sorted(models_by_id.values(), key=lambda model: model["model_id"])}
        self._assert_paths()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.directory / "catalogue.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            data = self._read()
            data["providers"][provider] = entry
            handle, temporary = tempfile.mkstemp(prefix=".catalogue-", dir=self.directory)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                self._assert_paths()
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        finally:
            os.close(descriptor)
        result = self.snapshot()
        result.update(network_used=True, metadata_requests=1, refreshed_provider=provider)
        return result

    def eligible(self, provider: str, capability: str = "code") -> list[dict]:
        if provider not in {"gemini", "openrouter"} or capability not in _CAPABILITIES:
            raise ModelCatalogError("Le fournisseur ou la capacité demandée est inconnu.")
        entry = self.snapshot()["providers"].get(provider)
        if not entry or entry["status"] != "fresh":
            return []
        return [item for item in entry["models"] if item["eligible"] and capability in item["capabilities"]]

    def choose_model(self, provider: str, requested: str = "auto", exclude_models=()) -> str:
        models = self.eligible(provider)
        if not isinstance(requested, str) or isinstance(exclude_models, str):
            raise ModelCatalogError("La sélection de modèle est invalide.")
        excluded = set(exclude_models)
        candidates = [item for item in models if item["model_id"] not in excluded]
        if requested != "auto":
            normalized = _model_id(requested, provider)
            if normalized and any(item["model_id"] == normalized for item in candidates):
                return normalized
            raise ModelCatalogError("Le modèle demandé n’est pas accessible avec un prix nul confirmé et un catalogue récent.")
        if provider == "gemini":
            candidates.sort(key=lambda model: GEMINI_PREFERENCE.index(model["model_id"]) if model["model_id"] in GEMINI_PREFERENCE else len(GEMINI_PREFERENCE))
        else:
            # Larger context is only a tie-breaker; no invented quality score.
            candidates.sort(key=lambda model: (-(model["input_token_limit"] or 0), model["model_id"]))
        if not candidates:
            raise ModelCatalogError("Aucun modèle accessible au prix nul confirmé ; actualisez le catalogue explicitement.")
        return candidates[0]["model_id"]
