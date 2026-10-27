"""Arena orchestration: concurrent multi-provider execution."""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from .cache import ArenaCache
from .config import ArenaConfig
from .jury import (
    disagreement_of,
    merge_bullets,
    score_responses,
)
from .models import ArenaVerdict, IARequest, IAResponse
from .providers import create_default_providers


def _is_available(provider: Any) -> bool:
    for name in ("is_available", "available", "is_ready"):
        attr = getattr(provider, name, None)
        if callable(attr):
            try:
                return bool(attr())
            except Exception:
                return False
    # Property-style.
    for name in ("available", "ready", "enabled"):
        if hasattr(provider, name) and not callable(getattr(provider, name)):
            try:
                return bool(getattr(provider, name))
            except Exception:
                return False
    return True


def _provider_name(provider: Any) -> str:
    for attr in ("provider", "name", "provider_id", "id"):
        val = getattr(provider, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return type(provider).__name__


def _provider_model(provider: Any) -> str:
    val = getattr(provider, "model", None)
    if isinstance(val, str) and val.strip():
        return val.strip()
    val = getattr(provider, "model_id", None)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return ""


async def _call_provider(provider: Any, request: IARequest) -> IAResponse:
    # Find a callable entry point.
    runner = None
    for name in ("run", "generate", "complete", "propose", "execute", "ask", "__call__"):
        cand = getattr(provider, name, None)
        if callable(cand):
            runner = cand
            break
    if runner is None:
        raise RuntimeError("provider has no runnable method")

    started = time.monotonic()
    result = runner(request)
    if inspect.isawaitable(result):
        result = await result
    latency = round((time.monotonic() - started) * 1000, 2)

    if isinstance(result, IAResponse):
        if not result.latency_ms:
            result.latency_ms = latency
        if not result.provider:
            result.provider = _provider_name(provider)
        if not result.model:
            result.model = _provider_model(provider)
        return result

    if isinstance(result, dict):
        provider_name = result.get("provider") or _provider_name(provider)
        model = result.get("model") or _provider_model(provider)
        content = result.get("content", result)
        cached = bool(result.get("cached", False))
        lat = result.get("latency_ms", latency)
        return IAResponse(provider=str(provider_name), model=str(model), content=content, latency_ms=float(lat), cached=cached)

    # Object with attributes.
    provider_name = getattr(result, "provider", None) or _provider_name(provider)
    model = getattr(result, "model", None) or _provider_model(provider)
    content = getattr(result, "content", None)
    if content is None:
        content = getattr(result, "result", None)
    if content is None:
        content = result
    cached = bool(getattr(result, "cached", False))
    lat = getattr(result, "latency_ms", latency)
    return IAResponse(provider=str(provider_name), model=str(model), content=content, latency_ms=float(lat), cached=cached)


async def _run_one(provider: Any, request: IARequest, timeout: float) -> IAResponse | None:
    try:
        return await asyncio.wait_for(_call_provider(provider, request), timeout=timeout)
    except Exception:
        return None


async def _async_run_arena(
    request: IARequest,
    *,
    providers: list[Any] | None = None,
    config: ArenaConfig | None = None,
    cache: ArenaCache | None = None,
    use_cache: bool | None = None,
    timeout: float | None = None,
    global_timeout: float | None = None,
    per_provider_timeout: float | None = None,
    max_merged_bullets: int | None = None,
    disagreement_threshold: float | None = None,
    **kwargs: Any,
) -> ArenaVerdict:
    if providers is None:
        for alias in ("provider", "providers_list", "provider_list", "provider_names"):
            if alias in kwargs:
                val = kwargs.pop(alias)
                if isinstance(val, (list, tuple)):
                    providers = list(val)
                else:
                    providers = [val]
                break

    if isinstance(config, dict):
        config = ArenaConfig(**{k: v for k, v in config.items() if k in ArenaConfig.__dataclass_fields__})
    if timeout is None:
        for alias in ("timeout_per_provider", "per_timeout", "provider_timeout"):
            if alias in kwargs:
                timeout = kwargs.pop(alias)
                break
    if global_timeout is None:
        for alias in ("global_time", "overall_timeout", "total_timeout"):
            if alias in kwargs:
                global_timeout = kwargs.pop(alias)
                break
    cfg = config or ArenaConfig()

    # Resolve provider name strings into default provider instances.
    if isinstance(providers, (list, tuple)) and providers and all(isinstance(p, str) for p in providers):
        defaults = create_default_providers(cfg)
        by_name = {_provider_name(p).lower(): p for p in defaults}
        providers = [by_name[p.strip().lower()] for p in providers if p.strip().lower() in by_name]
    if per_provider_timeout is not None:
        cfg.per_provider_timeout = per_provider_timeout
    if global_timeout is not None:
        cfg.global_timeout = global_timeout
    if timeout is not None:
        cfg.per_provider_timeout = timeout
    if max_merged_bullets is not None:
        cfg.max_merged_bullets = max_merged_bullets
    if disagreement_threshold is not None:
        cfg.disagreement_threshold = disagreement_threshold

    cache_enabled = cfg.cache_enabled if use_cache is None else bool(use_cache)
    if cache is None:
        cache = ArenaCache(enabled=cache_enabled, version=cfg.cache_version)
    else:
        cache.enabled = cache_enabled and getattr(cache, "enabled", True)

    if providers is None:
        providers = create_default_providers(cfg)

    # Filter available providers.
    available = [p for p in (providers or []) if _is_available(p)]

    # Cache lookup (keyed by request + configured provider names, not just available).
    configured_names = ",".join(_provider_name(p) for p in (providers or []))
    cache_key = cache.make_key(request, provider=configured_names, model="arena")
    if cache.enabled:
        cached_verdict = cache.get(cache_key)
        if cached_verdict is not None:
            # Mark responses cached.
            try:
                for r in getattr(cached_verdict, "responses", []) or []:
                    r.cached = True
            except Exception:
                pass
            return cached_verdict

    # Determine per-provider timeout.
    per_timeout = float(cfg.per_provider_timeout)
    glob_timeout = float(cfg.global_timeout)

    responses: list[IAResponse] = []
    attempted: set[str] = set()

    async def run_all(prov_list: list[Any]) -> list[IAResponse]:
        tasks = []
        for p in prov_list:
            attempted.add(_provider_name(p))
            tasks.append(_run_one(p, request, per_timeout))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = []
        for res in results:
            if isinstance(res, IAResponse):
                out.append(res)
            elif isinstance(res, Exception):
                pass
            elif res is not None:
                # Should not happen, but coerce.
                pass
        return out

    try:
        responses = await asyncio.wait_for(run_all(available), timeout=glob_timeout)
    except asyncio.TimeoutError:
        # Collect whatever finished? gather cancelled; keep empty/partial.
        responses = []

    # Score.
    scores = score_responses(request, responses)
    # Re-evaluation if disagreement high.
    disagreement = disagreement_of(scores)
    if responses and disagreement > cfg.disagreement_threshold:
        # Try to find one extra provider not attempted among defaults.
        extra_candidates = []
        try:
            defaults = create_default_providers(cfg)
        except Exception:
            defaults = []
        for p in defaults:
            if _provider_name(p) not in attempted and _is_available(p):
                extra_candidates.append(p)
        if extra_candidates:
            extra_resp = await _run_one(extra_candidates[0], request, per_timeout)
            if isinstance(extra_resp, IAResponse):
                responses.append(extra_resp)
                scores = score_responses(request, responses)
                disagreement = disagreement_of(scores)

    # Winner.
    winner = ""
    if scores:
        winner = max(scores, key=lambda k: scores[k])
    # Merged bullets best-of: sort responses by score desc for fusion.
    ordered = sorted(responses, key=lambda r: scores.get(r.provider, 0.0), reverse=True)
    bullets = merge_bullets(ordered, limit=cfg.max_merged_bullets)

    verdict = ArenaVerdict(
        winner=winner,
        merged_bullets=bullets,
        responses=responses,
        jury_scores=scores,
        disagreement=float(disagreement),
    )

    if cache.enabled:
        cache.set(cache_key, verdict)

    return verdict


def run_arena(*args: Any, **kwargs: Any) -> Any:
    """Sync/async entry point.

    Returns a coroutine when called inside a running event loop, otherwise runs
    the arena synchronously and returns an ``ArenaVerdict``.
    """
    for key in ("request", "arena_request", "ia_request"):
        if key in kwargs and not args:
            args = (kwargs.pop(key),)
            break
    coro = _async_run_arena(*args, **kwargs)
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False
    if running:
        return coro
    # If no running loop, execute synchronously.
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Fallback for nested loops.
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()


# Sync alias for tests that prefer explicit name.
run_arena_sync = run_arena


class Arena:
    """Small stateful wrapper around ``run_arena``."""

    def __init__(self, providers=None, config=None, cache=None, **kwargs):
        self.providers = providers
        self.config = config
        self.cache = cache
        self.kwargs = kwargs

    def run(self, request, **kwargs):
        merged = dict(self.kwargs)
        merged.update(kwargs)
        return run_arena(request, providers=self.providers, config=self.config, cache=self.cache, **merged)

    async def run_async(self, request, **kwargs):
        merged = dict(self.kwargs)
        merged.update(kwargs)
        return await run_arena_async(request, providers=self.providers, config=self.config, cache=self.cache, **merged)


AIArena = Arena
ArenaRunner = Arena


def run_arena_async(*args: Any, **kwargs: Any) -> Any:
    return _async_run_arena(*args, **kwargs)
