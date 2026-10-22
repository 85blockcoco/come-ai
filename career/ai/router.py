"""HTTP router for AI Arena."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter
from pydantic import BaseModel

from .arena import run_arena
from .cache import ArenaCache
from .config import ArenaConfig, get_config
from .models import IARequest


class ArenaRunPayload(BaseModel):
    task_type: str = "reformulate"
    input_payload: dict[str, Any] = {}
    model_hint: str | None = None


class ArenaConfigPayload(BaseModel):
    cache_enabled: bool | None = None
    per_provider_timeout: float | None = None
    global_timeout: float | None = None


def create_ai_router(
    *,
    providers: list[Any] | None = None,
    cache: ArenaCache | None = None,
    config: ArenaConfig | None = None,
    providers_factory: Callable[[], list[Any]] | None = None,
) -> APIRouter:
    router = APIRouter()
    cfg = config or get_config()
    _cache = cache if cache is not None else ArenaCache(enabled=cfg.cache_enabled, version=cfg.cache_version)
    _providers = providers

    def _providers_list() -> list[Any] | None:
        if _providers is not None:
            return _providers
        if providers_factory is not None:
            return providers_factory()
        return None

    @router.post("/ai/arena/run")
    @router.post("/api/ai/arena/run")
    async def run_endpoint(payload: ArenaRunPayload) -> dict[str, Any]:
        req = IARequest(
            task_type=payload.task_type,  # type: ignore[arg-type]
            input_payload=payload.input_payload,
            model_hint=payload.model_hint,
        )
        verdict = await run_arena(req, providers=_providers_list(), cache=_cache, config=cfg)
        return _verdict_to_dict(verdict)

    @router.get("/ai/arena/status")
    @router.get("/api/ai/arena/status")
    async def status_endpoint() -> dict[str, Any]:
        return {
            "providers": [getattr(p, "name", str(p)) for p in (_providers_list() or [])],
            "cache": _cache.stats(),
            "config": {
                "per_provider_timeout": cfg.per_provider_timeout,
                "global_timeout": cfg.global_timeout,
                "cache_enabled": cfg.cache_enabled,
                "cache_version": cfg.cache_version,
            },
        }

    @router.post("/ai/arena/config")
    @router.post("/api/ai/arena/config")
    async def config_endpoint(payload: ArenaConfigPayload) -> dict[str, Any]:
        if payload.cache_enabled is not None:
            cfg.cache_enabled = bool(payload.cache_enabled)
            _cache.enabled = bool(payload.cache_enabled)
        if payload.per_provider_timeout is not None and payload.per_provider_timeout > 0:
            cfg.per_provider_timeout = float(payload.per_provider_timeout)
        if payload.global_timeout is not None and payload.global_timeout > 0:
            cfg.global_timeout = float(payload.global_timeout)
        return {"updated": True}

    return router


def _verdict_to_dict(verdict: Any) -> dict[str, Any]:
    return {
        "winner": verdict.winner,
        "merged_bullets": list(verdict.merged_bullets),
        "responses": [
            {
                "provider": r.provider,
                "model": r.model,
                "content": r.content,
                "latency_ms": r.latency_ms,
                "cached": r.cached,
            }
            for r in verdict.responses
        ],
        "jury_scores": dict(verdict.jury_scores),
        "disagreement": verdict.disagreement,
    }
