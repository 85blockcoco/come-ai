"""Configuration for the AI Arena (secrets only via environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0 or value != value:  # NaN guard
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


@dataclass
class ArenaConfig:
    per_provider_timeout: float = 30.0
    global_timeout: float = 45.0
    cache_enabled: bool = True
    cache_version: str = "1"
    disagreement_threshold: float = 0.5
    max_additional_providers: int = 1
    ollama_timeout: float = 5.0
    gemini_model: str = "gemini-2.5-flash"
    opencode_model: str = "opencode"
    ollama_url: str = "http://127.0.0.1:11434"
    gemini_api_key_env: str = "GEMINI_API_KEY"
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.per_provider_timeout <= 0:
            self.per_provider_timeout = 30.0
        if self.global_timeout <= 0:
            self.global_timeout = 45.0
        if self.disagreement_threshold < 0 or self.disagreement_threshold > 1:
            self.disagreement_threshold = 0.5


def get_config() -> ArenaConfig:
    return ArenaConfig(
        per_provider_timeout=_env_float("AI_ARENA_PER_PROVIDER_TIMEOUT", 30.0),
        global_timeout=_env_float("AI_ARENA_GLOBAL_TIMEOUT", 45.0),
        cache_enabled=_env_bool("AI_ARENA_CACHE", True),
        cache_version=os.environ.get("AI_ARENA_CACHE_VERSION", "1"),
        disagreement_threshold=_env_float("AI_ARENA_DISAGREEMENT_THRESHOLD", 0.5),
        ollama_timeout=_env_float("AI_ARENA_OLLAMA_TIMEOUT", 5.0),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    )
