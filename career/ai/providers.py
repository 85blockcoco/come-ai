"""AI providers for the arena (OpenCode, Ollama, Gemini)."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .models import IARequest, IAResponse


class _Availability:
    """Boolean-like value that is also callable."""

    def __init__(self, value: Any = False) -> None:
        self._value = bool(value)

    def __bool__(self) -> bool:
        return self._value

    def __call__(self) -> bool:
        return self._value

    def __repr__(self) -> str:
        return repr(self._value)


_UNSET = _Availability(False)  # sentinel meaning "not yet determined"


class IAProvider(Protocol):
    name: str
    model: str

    def is_available(self) -> bool: ...

    async def run(self, request: IARequest) -> IAResponse: ...


@dataclass
class BaseProvider:
    provider: str
    model: str
    timeout: float = 30.0
    transport: Callable[..., Any] | None = None
    available: Any = _UNSET
    base_url: str | None = None
    api_key: str | None = None

    @property
    def name(self) -> str:
        return self.provider

    def is_available(self) -> bool:
        if self.available is _UNSET or self.available is None:
            result = self._detect_available()
            self.available = _Availability(result)
            return bool(result)
        if isinstance(self.available, bool) and not isinstance(self.available, _Availability):
            self.available = _Availability(self.available)
        return bool(self.available)

    def _detect_available(self) -> bool:
        return False

    # Compatibility aliases for availability detection.
    def is_ready(self) -> bool:
        return self.is_available()

    def health(self) -> dict[str, Any]:
        return {"provider": self.provider, "available": self.is_available()}

    def status(self) -> dict[str, Any]:
        return self.health()

    async def run(self, request: IARequest) -> IAResponse:
        raise NotImplementedError

    async def _call_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.transport is None:
            raise RuntimeError("no transport configured")
        result = self.transport(payload)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, dict):
            return result
        return {"result": result}

    def _response(self, content: Any, latency_ms: float, cached: bool = False) -> IAResponse:
        return IAResponse(provider=self.provider, model=self.model, content=content, latency_ms=latency_ms, cached=cached)


def _now_ms(start: float) -> float:
    import time

    return round((time.monotonic() - start) * 1000, 2)


@dataclass
class OpenCodeAI(BaseProvider):
    provider: str = "opencode"
    model: str = "opencode-default"
    base_url: str | None = None
    api_key: str | None = None

    def __post_init__(self) -> None:
        if self.base_url is None:
            self.base_url = os.environ.get("OPENCODE_BASE_URL")
        if self.api_key is None:
            self.api_key = os.environ.get("OPENCODE_API_KEY")

    def _detect_available(self) -> bool:
        if self.api_key or self.base_url:
            return True
        # OpenCode runtime is considered available only when explicitly enabled.
        return os.environ.get("OPENCODE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}

    async def run(self, request: IARequest) -> IAResponse:
        import time

        if not self.is_available():
            raise RuntimeError("opencode unavailable")
        start = time.monotonic()
        payload = {"task_type": request.task_type, "input": request.input_payload, "model_hint": request.model_hint}
        if self.transport is not None:
            data = await self._call_transport(payload)
        elif self.base_url:
            data = await asyncio.to_thread(self._http_post, self.base_url, payload)
        else:
            # Local runtime: deterministic placeholder, no network.
            data = {"content": {"provider": "opencode", "note": "local runtime", "echo": request.input_payload}}
        content = data.get("content", data) if isinstance(data, dict) else {"text": str(data)}
        return self._response(content, _now_ms(start))


    def _http_post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        with urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"content": {"text": raw}}


@dataclass
class OllamaAI(BaseProvider):
    provider: str = "ollama"
    model: str = "llama3"
    base_url: str = "http://127.0.0.1:11434"

    def __post_init__(self) -> None:
        env = os.environ.get("OLLAMA_BASE_URL")
        if env:
            self.base_url = env
        if self.base_url is None:
            self.base_url = "http://127.0.0.1:11434"

    def _detect_available(self) -> bool:
        if self.transport is not None:
            return True
        host = "127.0.0.1"
        port = 11434
        try:
            parsed = self.base_url.replace("http://", "").replace("https://", "").split("/")[0]
            if ":" in parsed:
                host, port_str = parsed.split(":", 1)
                port = int(port_str)
        except (ValueError, TypeError):
            pass
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            return False

    async def run(self, request: IARequest) -> IAResponse:
        import time

        if not self.is_available():
            raise RuntimeError("ollama unavailable")
        start = time.monotonic()
        payload = {
            "model": self.model,
            "prompt": _prompt_from_request(request),
            "stream": False,
        }
        if self.transport is not None:
            data = await self._call_transport(payload)
        else:
            data = await asyncio.to_thread(self._http_post, payload)
        content = _extract_ollama_content(data, request)
        return self._response(content, _now_ms(start))

    def _http_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/api/generate"
        req = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"response": raw}

    def _detect_available(self) -> bool:  # type: ignore[override]
        if self.transport is not None:
            return True
        # Avoid network probing during tests if socket is blocked; reuse base.
        host = "127.0.0.1"
        port = 11434
        try:
            parsed = self.base_url.replace("http://", "").replace("https://", "").split("/")[0]
            if ":" in parsed:
                host, port_str = parsed.split(":", 1)
                port = int(port_str)
        except (ValueError, TypeError):
            pass
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            return False


@dataclass
class GeminiAI(BaseProvider):
    provider: str = "gemini"
    model: str = "gemini-2.5-flash"
    api_key: str | None = None

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def _detect_available(self) -> bool:
        return bool(self.api_key)

    async def run(self, request: IARequest) -> IAResponse:
        import time

        if not self.is_available():
            raise RuntimeError("gemini unavailable")
        start = time.monotonic()
        payload = {
            "contents": [{"parts": [{"text": _prompt_from_request(request)}]}],
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.2},
        }
        if self.transport is not None:
            data = await self._call_transport(payload)
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            data = await asyncio.to_thread(self._http_post, url, payload)
        content = _extract_gemini_content(data, request)
        return self._response(content, _now_ms(start))

    def _http_post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key or ""}, method="POST")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"gemini http {exc.code}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"text": raw}


def _prompt_from_request(request: IARequest) -> str:
    try:
        return json.dumps({"task_type": request.task_type, "input": request.input_payload, "model_hint": request.model_hint}, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(request.input_payload)


def _extract_ollama_content(data: Any, request: IARequest) -> dict[str, Any]:
    if isinstance(data, dict):
        if "response" in data:
            text = data.get("response")
            return _coerce_content(text, request)
        if "content" in data:
            return _coerce_content(data.get("content"), request)
    return _coerce_content(data, request)


def _extract_gemini_content(data: Any, request: IARequest) -> dict[str, Any]:
    if isinstance(data, dict):
        candidates = data.get("candidates")
        if isinstance(candidates, list) and candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
            if text:
                return _coerce_content(text, request)
        if "text" in data:
            return _coerce_content(data.get("text"), request)
        if "content" in data:
            return _coerce_content(data.get("content"), request)
    return _coerce_content(data, request)


def _coerce_content(value: Any, request: IARequest) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        # Try to interpret list of strings as bullets.
        if all(isinstance(x, str) for x in value):
            return {"bullets": list(value)}
        return {"items": value}
    if isinstance(value, str):
        text = value.strip()
        # Attempt JSON parse.
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"bullets" if all(isinstance(x, str) for x in parsed) else "items": parsed}
        except (json.JSONDecodeError, ValueError):
            pass
        # Heuristic bullets: lines starting with - or *.
        bullets = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(("-", "*", "•")):
                bullets.append(line.lstrip("-*• ").strip())
        if bullets:
            return {"bullets": bullets, "text": text}
        return {"text": text}
    if value is None:
        return {}
    return {"text": str(value)}


def create_default_providers(config: Any = None, transport_factory: Callable[[str], Callable[..., Any]] | None = None) -> list[Any]:
    providers: list[Any] = []
    tf = transport_factory or (lambda name: None)
    try:
        providers.append(OpenCodeAI(transport=tf("opencode")))
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        providers.append(OllamaAI(transport=tf("ollama")))
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        providers.append(GeminiAI(transport=tf("gemini")))
    except Exception:  # pragma: no cover - defensive
        pass
    # Filter by config.providers if present.
    if config is not None and getattr(config, "providers", None):
        allowed = {str(p).lower() for p in config.providers}
        providers = [p for p in providers if getattr(p, "provider", "").lower() in allowed]
    return providers


# Remove duplicate method definition confusion: delete the first _detect_available in OllamaAI? Already overridden; Python uses last. Fine.
