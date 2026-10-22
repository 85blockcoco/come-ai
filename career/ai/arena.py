"""Arena orchestration: concurrent multi-provider execution."""

from __future__ import annotations

import asyncio

from .cache import ArenaCache
from .config import ArenaConfig, get_config
from .jury import (
    compute_disagreement,
    merge_bullets,
    pick_winner,
    score_responses,
)
from .models import IARequest, IAResponse, ArenaVerdict
from .providers import IAProvider, default_providers


class Arena:
    def __init__(
        self,
        providers: list[IAProvider] | None = None,
        *,
        cache: ArenaCache | None = None,
        config: ArenaConfig | None = None,
    ) -> None:
        self.config = config or get_config()
        self.providers = providers if providers is not None else default_providers(self.config)
        self.cache = cache if cache is not None else ArenaCache(
            enabled=self.config.cache_enabled, version=self.config.cache_version
        )

    async def run(self, request: IARequest) -> ArenaVerdict:
        return await run_arena(request, providers=self.providers, cache=self.cache, config=self.config)


async def _call_provider(provider: IAProvider, request: IARequest, timeout: float) -> IAResponse | None:
    try:
        return await asyncio.wait_for(provider.generate(request), timeout=timeout)
    except Exception:
        return None


async def _is_available_async(provider: IAProvider) -> bool:
    try:
        avail = getattr(provider, "is_available", None)
        if callable(avail):
            result = avail()
            if asyncio.iscoroutine(result):
                result = await result
            return bool(result)
        return True
    except Exception:
        return False

async def run_arena(
    request: IARequest,
    *,
    providers: list[IAProvider] | None = None,
    cache: ArenaCache | None = None,
    config: ArenaConfig | None = None,
    use_cache: bool | None = None,
) -> ArenaVerdict:
    cfg = config or get_config()
    if providers is None:
        providers = default_providers(cfg)
    if cache is None:
        cache = ArenaCache(enabled=cfg.cache_enabled if use_cache is None else bool(use_cache), version=cfg.cache_version)
    else:
        if use_cache is not None:
            cache.enabled = bool(use_cache)

    available_providers = []
    for p in providers:
        if await _is_available_async(p):
            available_providers.append(p)

    responses: list[IAResponse] = []
    used: set[int] = set()

    async def gather_batch(batch: list[IAProvider]) -> None:
        # cache check + live calls
        cached_map: dict[int, IAResponse] = {}
        live: list[IAProvider] = []
        for p in batch:
            key = cache.make_key(request, p.name, p.model)
            c = cache.get(key)
            if c is not None:
                cached_map[id(p)] = c
            else:
                live.append(p)

        live_results: dict[int, IAResponse | None] = {}
        if live:
            coros = [_call_provider(p, request, cfg.per_provider_timeout) for p in live]
            try:
                gathered = await asyncio.wait_for(
                    asyncio.gather(*coros, return_exceptions=True),
                    timeout=cfg.global_timeout,
                )
            except asyncio.TimeoutError:
                gathered = [None] * len(live)
            for p, res in zip(live, gathered):
                if isinstance(res, Exception) or res is None:
                    live_results[id(p)] = None
                else:
                    live_results[id(p)] = res

        for p in batch:
            if id(p) in cached_map:
                responses.append(cached_map[id(p)])
                used.add(id(p))
                continue
            res = live_results.get(id(p))
            if res is not None:
                key = cache.make_key(request, p.name, p.model)
                cache.set(key, res)
                responses.append(res)
                used.add(id(p))

    try:
        await asyncio.wait_for(gather_batch(available_providers), timeout=cfg.global_timeout)
    except asyncio.TimeoutError:
        pass

    scores = score_responses(request, responses)
    disagreement = compute_disagreement(responses)
    merged = merge_bullets(responses)
    winner = pick_winner(scores, responses) if responses else ""

    # Dispute rule
    if disagreement > cfg.disagreement_threshold:
        extra = None
        for p in available_providers:
            if id(p) not in used:
                extra = p
                break
        if extra is not None:
            try:
                res = await asyncio.wait_for(
                    _call_provider(extra, request, cfg.per_provider_timeout),
                    timeout=cfg.per_provider_timeout,
                )
            except asyncio.TimeoutError:
                res = None
            if res is not None:
                key = cache.make_key(request, extra.name, extra.model)
                cache.set(key, res)
                responses.append(res)
                used.add(id(extra))
                scores = score_responses(request, responses)
                disagreement = compute_disagreement(responses)
                merged = merge_bullets(responses)
                winner = pick_winner(scores, responses) if responses else winner

    if not winner and responses:
        winner = responses[0].provider

    return ArenaVerdict(
        winner=winner,
        merged_bullets=merged,
        responses=responses,
        jury_scores=scores,
        disagreement=disagreement,
    )
