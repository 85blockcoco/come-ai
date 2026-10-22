"""AI providers for the arena (opencode, ollama, gemini)."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Awaitable, Callable, Protocol
from .config import ArenaConfig, get_config
from .models import IARequest, IAResponse

ProviderTransport = Callable[[IARequest], Awaitable[IAResponse]]


class ProviderError(Exception):
    """Raised when a provider cannot produce a valid response."""


class IAProvider(Protocol):
    name: str
    model: str

    def is_available(self) -> bool: ...

    async def generate(self, request: IARequest) -> IAResponse: ...


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _safe_json(text: str) -> dict:
    text = text.strip()
    if not text:
        raise ProviderError("empty response")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract a JSON object (prefer the last balanced block)
        import re

        matches = list(re.finditer(r"\{.*\}", text, re.S))
        candidate = None
        for m in reversed(matches):
            try:
                candidate = json.loads(m.group(0))
                break
            except json.JSONDecodeError:
                continue
        if candidate is None:
            # fallback: first { to last }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    candidate = json.loads(text[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise ProviderError("malformed response") from exc
            else:
                raise ProviderError("malformed response")
        parsed = candidate
    if not isinstance(parsed, dict):
        raise ProviderError("response is not a JSON object")
    return parsed


def _normalize_content(content: Any) -> dict:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        text = content.strip()
        if not text:
            raise ProviderError("empty response")
        try:
            return _safe_json(text)
        except ProviderError:
            return {"text": text, "bullets": [text[:200]]}
    if content is None:
        raise ProviderError("empty response")
    return {"value": content}


class OpenCodeAI:
    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        transport: Callable[[IARequest], Awaitable[IAResponse]] | None = None,
        available: bool | None = None,
        config: ArenaConfig | None = None,
    ) -> None:
        cfg = config or get_config()
        self.name = "opencode"
        self.model = model or cfg.opencode_model
        self.base_url = base_url or os.environ.get("OPENCODE_API_URL")
        self.timeout = float(timeout)
        self._transport = transport
        self._available_override = available
        self.config = cfg

    def is_available(self) -> bool:
        if self._available_override is not None:
            return bool(self._available_override)
        if os.environ.get("OPENCODE") == "1" or os.environ.get("OPENCODE_TERMINAL") == "1":
            return True
        if self.base_url:
            return True
        return False

    async def generate(self, request: IARequest) -> IAResponse:
        if self._transport is not None:
            return await self._transport(request)
        start = _now_ms()
        # If a base URL is configured, attempt a minimal HTTP call.
        if self.base_url:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        self.base_url.rstrip("/") + "/v1/chat/completions",
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": _request_prompt(request)}],
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    text = ""
                    if isinstance(data, dict):
                        choices = data.get("choices")
                        if isinstance(choices, list) and choices:
                            msg = choices[0].get("message", {})
                            text = msg.get("content", "") if isinstance(msg, dict) else ""
                        text = text or data.get("content", "") or ""
                    content = _normalize_content(text if text else data)
                    return IAResponse(
                        provider=self.name, model=self.model, content=content,
                        latency_ms=_now_ms() - start, cached=False,
                    )
            except Exception as exc:
                raise ProviderError(f"opencode unavailable: {exc}") from exc
        # Local fallback: deterministic synthesis so the provider is usable in-process.
        content = _local_synthesize(request, self.name)
        return IAResponse(
            provider=self.name, model=self.model, content=content,
            latency_ms=_now_ms() - start, cached=False,
        )

    # alias
    async def run(self, request: IARequest) -> IAResponse:
        return await self.generate(request)


class OllamaAI:
    def __init__(
        self,
        *,
        model: str = "qwen3.5:2b-q4_K_M",
        base_url: str | None = None,
        timeout: float | None = None,
        transport: Callable[[IARequest], Awaitable[IAResponse]] | None = None,
        available: bool | None = None,
        config: ArenaConfig | None = None,
    ) -> None:
        cfg = config or get_config()
        self.name = "ollama"
        self.model = model
        self.base_url = (base_url or cfg.ollama_url).rstrip("/")
        self.timeout = float(timeout if timeout is not None else cfg.ollama_timeout)
        self._transport = transport
        self._available_override = available
        self.config = cfg

    def is_available(self) -> bool:
        if self._available_override is not None:
            return bool(self._available_override)
        try:
            import httpx

            r = httpx.get(self.base_url + "/api/version", timeout=min(self.timeout, 2.0))
            return r.status_code == 200
        except Exception:
            return False

    async def generate(self, request: IARequest) -> IAResponse:
        if self._transport is not None:
            return await self._transport(request)
        start = _now_ms()
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.base_url + "/api/generate",
                    json={"model": self.model, "prompt": _request_prompt(request), "stream": False},
                )
                resp.raise_for_status()
                data = resp.json()
                text = data.get("response", "") if isinstance(data, dict) else ""
                content = _normalize_content(text if text.strip() else data)
                return IAResponse(
                    provider=self.name, model=self.model, content=content,
                    latency_ms=_now_ms() - start, cached=False,
                )
        except Exception as exc:
            raise ProviderError(f"ollama unavailable: {exc}") from exc

    async def run(self, request: IARequest) -> IAResponse:
        return await self.generate(request)


class GeminiAI:
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: Callable[[IARequest], Awaitable[IAResponse]] | None = None,
        available: bool | None = None,
        config: ArenaConfig | None = None,
    ) -> None:
        cfg = config or get_config()
        self.name = "gemini"
        self.model = model or cfg.gemini_model
        self.api_key = api_key if api_key is not None else os.environ.get(cfg.gemini_api_key_env)
        self.timeout = float(timeout)
        self._transport = transport
        self._available_override = available
        self.config = cfg

    def is_available(self) -> bool:
        if self._available_override is not None:
            return bool(self._available_override)
        return bool(self.api_key)

    async def generate(self, request: IARequest) -> IAResponse:
        if self._transport is not None:
            return await self._transport(request)
        if not self.api_key:
            raise ProviderError("gemini missing api key")
        start = _now_ms()
        candidate_models = [self.model] + [m for m in ("gemma-4-26b-a4b-it",) if m != self.model]
        last_exc: Exception | None = None
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for model in candidate_models:
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                        f"?key={self.api_key}"
                    )
                    try:
                        resp = await client.post(
                            url,
                            json={
                                "contents": [{"parts": [{"text": _request_prompt(request)}]}],
                                "generationConfig": {"responseMimeType": "application/json"},
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        text = ""
                        if isinstance(data, dict):
                            cands = data.get("candidates")
                            if isinstance(cands, list) and cands:
                                parts = cands[0].get("content", {}).get("parts", [])
                                if isinstance(parts, list):
                                    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
                        content = _normalize_content(text if text.strip() else data)
                        self.model = model
                        return IAResponse(
                            provider=self.name, model=model, content=content,
                            latency_ms=_now_ms() - start, cached=False,
                        )
                    except httpx.HTTPStatusError as exc:
                        last_exc = exc
                        if exc.response.status_code in (400, 404):
                            continue
                        raise
                if last_exc is not None:
                    raise last_exc
        except Exception as exc:
            raise ProviderError(f"gemini error: {exc}") from exc

    async def run(self, request: IARequest) -> IAResponse:
        return await self.generate(request)


def _request_prompt(request: IARequest) -> str:
    try:
        return (
            "Tâche: " + str(request.task_type) + "\n"
            "Payload: " + json.dumps(request.input_payload, ensure_ascii=False, default=str) + "\n"
            "Réponds uniquement en JSON objet avec des bullets et des ids de preuves si applicable."
        )
    except Exception:
        return str(request.input_payload)


def _local_synthesize(request: IARequest, provider: str) -> dict:
    payload = request.input_payload if isinstance(request.input_payload, dict) else {}
    bullets = []
    # Extract candidate strings
    for key in ("bullets", "items", "requirements", "keywords"):
        val = payload.get(key)
        if isinstance(val, list):
            for v in val:
                bullets.append(str(v))
    if not bullets:
        # Build from text fields
        for key in ("text", "job_description", "offer", "profile", "cv"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                # naive split into sentences
                for sent in val.replace("\n", " ").split("."):
                    s = sent.strip()
                    if len(s) > 20:
                        bullets.append(s[:120])
    if not bullets:
        bullets = [f"{provider}: idée générée pour {request.task_type}"]
    # dedup
    seen = set()
    out = []
    for b in bullets:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return {
        "bullets": out[:8],
        "keywords": payload.get("keywords", []) if isinstance(payload.get("keywords"), list) else [],
        "provider": provider,
    }


def default_providers(config: ArenaConfig | None = None) -> list[IAProvider]:
    cfg = config or get_config()
    providers: list[IAProvider] = []
    # opencode first
    providers.append(OpenCodeAI(config=cfg))
    providers.append(OllamaAI(config=cfg))
    providers.append(GeminiAI(config=cfg))
    return providers
