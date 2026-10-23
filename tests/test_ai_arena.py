"""Tests for the AI Arena (SPEC-017)."""

from __future__ import annotations

import asyncio

from career.ai import IARequest, IAResponse, ArenaVerdict, run_arena
from career.ai.cache import ArenaCache
from career.ai.providers import GeminiAI, OllamaAI, OpenCodeAI, create_default_providers


def _provider(name, content, *, available=True, delay=0, raise_exc=None):
    class P:
        provider = name
        model = f"{name}-model"

        def is_available(self):
            return available

        async def run(self, request):
            if delay:
                await asyncio.sleep(delay)
            if raise_exc is not None:
                raise raise_exc
            return IAResponse(provider=name, model=self.model, content=content)

    return P()


def test_basic_run_with_two_providers():
    p1 = _provider("alpha", {"bullets": ["a", "b"], "evidence_ids": ["e1"]})
    p2 = _provider("beta", {"bullets": ["c"]})
    req = IARequest("reformulate", {"text": "cv"})
    verdict = run_arena(req, providers=[p1, p2], use_cache=False)
    assert isinstance(verdict, ArenaVerdict)
    assert verdict.winner == "alpha"
    assert set(verdict.jury_scores) == {"alpha", "beta"}
    assert "a" in verdict.merged_bullets and "c" in verdict.merged_bullets
    assert verdict.disagreement >= 0


def test_provider_unavailable_skipped():
    p1 = _provider("alpha", {"bullets": ["a"]}, available=False)
    p2 = _provider("beta", {"bullets": ["b"]})
    req = IARequest("keywords", {"text": "x"})
    verdict = run_arena(req, providers=[p1, p2], use_cache=False)
    assert verdict.winner == "beta"
    assert "alpha" not in verdict.jury_scores


def test_provider_exception_skipped():
    p1 = _provider("alpha", {}, raise_exc=RuntimeError("boom"))
    p2 = _provider("beta", {"bullets": ["b"]})
    req = IARequest("keywords", {"text": "x"})
    verdict = run_arena(req, providers=[p1, p2], use_cache=False)
    assert verdict.winner == "beta"


def test_timeout_skips_slow_provider():
    p1 = _provider("slow", {"bullets": ["s"]}, delay=2)
    p2 = _provider("fast", {"bullets": ["f"]})
    req = IARequest("keywords", {"text": "x"})
    verdict = run_arena(req, providers=[p1, p2], per_provider_timeout=0.1, global_timeout=5, use_cache=False)
    assert verdict.winner == "fast"
    assert "slow" not in verdict.jury_scores


def test_empty_response_handled():
    p1 = _provider("alpha", {})
    req = IARequest("score", {"value": 1})
    verdict = run_arena(req, providers=[p1], use_cache=False)
    assert isinstance(verdict, ArenaVerdict)
    assert verdict.winner == "alpha"


def test_malformed_provider_content_coerced():
    class P:
        provider = "weird"
        model = "m"
        def is_available(self):
            return True
        async def run(self, request):
            return "just text"
    verdict = run_arena(IARequest("research", {"q": "q"}), providers=[P()], use_cache=False)
    assert verdict.responses[0].content.get("text") == "just text"


def test_cache_hit():
    p = _provider("alpha", {"bullets": ["a"]})
    req = IARequest("keywords", {"text": "cache"})
    cache = ArenaCache(enabled=True, version="v1")
    v1 = run_arena(req, providers=[p], cache=cache, use_cache=True)
    # second run should hit cache even if provider unavailable now
    p2 = _provider("alpha", {"bullets": ["different"]}, available=False)
    v2 = run_arena(req, providers=[p2], cache=cache, use_cache=True)
    assert v2.responses[0].cached is True
    assert v2.merged_bullets == v1.merged_bullets


def test_cache_disabled():
    p = _provider("alpha", {"bullets": ["a"]})
    req = IARequest("keywords", {"text": "nocache"})
    cache = ArenaCache(enabled=False)
    run_arena(req, providers=[p], cache=cache, use_cache=False)
    p2 = _provider("alpha", {"bullets": ["b"]}, available=True)
    v2 = run_arena(req, providers=[p2], cache=cache, use_cache=False)
    assert v2.merged_bullets == ["b"]


def test_async_entrypoint():
    async def main():
        p = _provider("alpha", {"bullets": ["a"]})
        req = IARequest("keywords", {"text": "async"})
        return await run_arena(req, providers=[p], use_cache=False)
    v = asyncio.run(main())
    assert v.winner == "alpha"


def test_create_default_providers_filters():
    ps = create_default_providers()
    assert isinstance(ps, list)
    # At least the three known providers are attempted.
    names = {getattr(p, "provider", None) for p in ps}
    assert {"opencode", "ollama", "gemini"}.issubset(names)


def test_opencode_gemini_ollama_constructors():
    o = OpenCodeAI(available=True)
    g = GeminiAI(api_key="k", available=True)
    ol = OllamaAI(available=True)
    assert o.is_available() and g.is_available() and ol.is_available()


def test_jury_disagreement_and_merge():
    from career.ai.jury import jury_verdict, merge_bullets, disagreement_of
    r1 = IAResponse("a", "m", {"bullets": ["x"]})
    r2 = IAResponse("b", "m", {"bullets": ["y"]})
    req = IARequest("reformulate", {})
    v = jury_verdict(req, [r1, r2])
    assert v["winner"] in {"a", "b"}
    assert isinstance(v["disagreement"], float)
    assert merge_bullets([r1, r2]) == ["x", "y"]
    assert disagreement_of(v["scores"]) == v["disagreement"]
