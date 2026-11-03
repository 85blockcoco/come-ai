"""Configuration for the AI Arena."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArenaConfig:
    per_provider_timeout: float = 30.0
    global_timeout: float = 45.0
    cache_enabled: bool = True
    cache_version: str = "1"
    scoring_style: str = "deterministic"
    providers: list[str] = field(default_factory=lambda: ["opencode", "ollama", "gemini"])
    max_merged_bullets: int = 10
    disagreement_threshold: float = 0.5

    @classmethod
    def from_env(cls) -> "ArenaConfig":
        def _float(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, default))
            except (TypeError, ValueError):
                return default

        def _bool(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        providers_raw = os.environ.get("AI_ARENA_PROVIDERS")
        providers = [p.strip() for p in providers_raw.split(",") if p.strip()] if providers_raw else None
        return cls(
            per_provider_timeout=_float("AI_ARENA_PROVIDER_TIMEOUT", 30.0),
            global_timeout=_float("AI_ARENA_GLOBAL_TIMEOUT", 45.0),
            cache_enabled=_bool("AI_ARENA_CACHE", True),
            cache_version=os.environ.get("AI_ARENA_CACHE_VERSION", "1"),
            scoring_style=os.environ.get("AI_ARENA_SCORING", "deterministic"),
            providers=providers or ["opencode", "ollama", "gemini"],
            max_merged_bullets=int(os.environ.get("AI_ARENA_MAX_BULLETS", "10") or 10),
            disagreement_threshold=_float("AI_ARENA_DISAGREEMENT_THRESHOLD", 0.5),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "per_provider_timeout": self.per_provider_timeout,
            "global_timeout": self.global_timeout,
            "cache_enabled": self.cache_enabled,
            "cache_version": self.cache_version,
            "scoring_style": self.scoring_style,
            "providers": list(self.providers),
            "max_merged_bullets": self.max_merged_bullets,
            "disagreement_threshold": self.disagreement_threshold,
        }


def load_arena_config() -> ArenaConfig:
    return ArenaConfig.from_env()


# Backwards-friendly alias.
ArenaSettings = ArenaConfig
