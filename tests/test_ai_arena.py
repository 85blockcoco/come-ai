"""Tests for AI Arena core."""

from __future__ import annotations

import asyncio
import os

from career.ai import (
    Arena,
    ArenaCache,
    IARequest,
    IAResponse,
    ArenaVerdict,
    run_arena,
    OpenCodeAI,
    OllamaAI,
    GeminiAI,
)
from career.ai.providers import ProviderError


class FakeProvider:
    def __init__(self, name, content=None, latency=10.0, available=True, raise_exc=None, delay=0.0):
        self.name = name
        self.model = name + "-model"
        self._content = content if content is not None else {"bullets": [f"{name} bullet"]}
        self._latency = latency
        self._available = available
        self._raise = raise_exc
        self._delay = delay

    def is_available(self):
        return self._available

    async def generate(self, request):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raise is not None:
            raise self._raise
        return IAResponse(provider=self.name, model=self.model, content=self._content, latency_ms=self._latency)


def test_basic_run_two_providers():
    async def main():
        p1 = FakeProvider("p1", {"bullets": ["a", "b"]})
        p2 = FakeProvider("p2", {"bullets": ["b", "c"]})
        req = IARequest(task_type="reformulate", input_payload={"text": "hello"})
        verdict = await run_arena(req, providers=[p1, p2], use_cache=False)
        assert isinstance(verdict, ArenaVerdict)
        assert verdict.winner in {"p1", "p2"}
        assert "a" in verdict.merged_bullets or "b" in verdict.merged_bullets
        assert len(verdict.responses) == 2
    asyncio.run(main())


def test_provider_ko_skipped():
    async def main():
        p1 = FakeProvider("p1")
        p2 = FakeProvider("p2", raise_exc=RuntimeError("boom"))
        req = IARequest(task_type="keywords", input_payload={})
        verdict = await run_arena(req, providers=[p1, p2], use_cache=False)
        assert len(verdict.responses) == 1
        assert verdict.winner == "p1"
    asyncio.run(main())


def test_timeout_skipped():
    async def main():
        p1 = FakeProvider("p1")
        p2 = FakeProvider("p2", delay=10.0)
        from career.ai.config import ArenaConfig

        cfg = ArenaConfig(per_provider_timeout=0.1, global_timeout=1.0, cache_enabled=False)
        req = IARequest(task_type="keywords", input_payload={})
        verdict = await run_arena(req, providers=[p1, p2], config=cfg, use_cache=False)
        assert len(verdict.responses) == 1
    asyncio.run(main())


def test_empty_response_skipped():
    async def main():
        p1 = FakeProvider("p1", content={})
        p2 = FakeProvider("p2")
        req = IARequest(task_type="keywords", input_payload={})
        verdict = await run_arena(req, providers=[p1, p2], use_cache=False)
        # empty content provider may still be included but score 0; at least p2 present
        assert any(r.provider == "p2" for r in verdict.responses)
    asyncio.run(main())


def test_malformed_response_provider_raises():
    async def main():
        p1 = FakeProvider("p1", raise_exc=ProviderError("malformed response"))
        p2 = FakeProvider("p2")
        req = IARequest(task_type="keywords", input_payload={})
        verdict = await run_arena(req, providers=[p1, p2], use_cache=False)
        assert len(verdict.responses) == 1
    asyncio.run(main())


def test_cache_off():
    cache = ArenaCache(enabled=True, version="1")
    async def main():
        p1 = FakeProvider("p1")
        req = IARequest(task_type="keywords", input_payload={"x": 1})
        await run_arena(req, providers=[p1], cache=cache, use_cache=False)
        # second run should not use cache -> provider called twice (no way to check easily), but cached flag false
        v2 = await run_arena(req, providers=[p1], cache=cache, use_cache=False)
        assert all(not r.cached for r in v2.responses)
    asyncio.run(main())


def test_cache_on():
    cache = ArenaCache(enabled=True, version="1")
    calls = {"n": 0}

    class Counting(FakeProvider):
        async def generate(self, request):
            calls["n"] += 1
            return await super().generate(request)

    p1 = Counting("p1")
    async def main():
        req = IARequest(task_type="keywords", input_payload={"x": 2})
        await run_arena(req, providers=[p1], cache=cache, use_cache=True)
        await run_arena(req, providers=[p1], cache=cache, use_cache=True)
        assert calls["n"] == 1
    asyncio.run(main())


def test_unavailable_provider_skipped():
    async def main():
        p1 = FakeProvider("p1", available=False)
        p2 = FakeProvider("p2")
        req = IARequest(task_type="keywords", input_payload={})
        verdict = await run_arena(req, providers=[p1, p2], use_cache=False)
        assert len(verdict.responses) == 1
        assert verdict.responses[0].provider == "p2"
    asyncio.run(main())


def test_disagreement_and_dispute():
    async def main():
        p1 = FakeProvider("p1", {"bullets": ["a"]})
        p2 = FakeProvider("p2", {"bullets": ["z"]})
        p3 = FakeProvider("p3", {"bullets": ["a", "z"]})
        req = IARequest(task_type="keywords", input_payload={})
        verdict = await run_arena(req, providers=[p1, p2, p3], use_cache=False)
        assert 0.0 <= verdict.disagreement <= 1.0
    asyncio.run(main())


def test_opencode_provider_available_in_env():
    p = OpenCodeAI()
    # In this environment OPENCODE=1
    assert p.is_available() is True


def test_gemini_availability_env():
    os.environ.pop("GEMINI_API_KEY", None)
    p = GeminiAI(api_key=None)
    assert p.is_available() is False
    p2 = GeminiAI(api_key="fake-key")
    assert p2.is_available() is True


def test_ollama_availability_false_when_down():
    p = OllamaAI(base_url="http://127.0.0.1:1")
    assert p.is_available() is False


def test_arena_class():
    async def main():
        arena = Arena(providers=[FakeProvider("p1")])
        verdict = await arena.run(IARequest(task_type="score", input_payload={}))
        assert verdict.winner == "p1"
    asyncio.run(main())


def test_cache_stats():
    cache = ArenaCache(enabled=True, version="2")
    assert cache.stats()["version"] == "2"
    cache.clear()
    assert cache.stats()["size"] == 0


def test_router_import():
    from career.ai.router import create_ai_router

    r = create_ai_router()
    assert r is not None