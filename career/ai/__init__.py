"""AI Arena — multi-provider concurrent engine (SPEC-017).

Pure orchestration helpers. Providers are opt-in and never raise on missing
configuration: unavailable providers are skipped silently.
"""

from __future__ import annotations

from .arena import Arena, AIArena, ArenaRunner, run_arena, run_arena_async, run_arena_sync
from .cache import ArenaCache
from .config import ArenaConfig, load_arena_config
from .jury import Jury, jury_verdict, score_response
from .models import ArenaVerdict, IARequest, IAResponse
from .providers import GeminiAI, IAProvider, OllamaAI, OpenCodeAI, create_default_providers

__all__ = [
    "Arena",
    "AIArena",
    "ArenaCache",
    "ArenaConfig",
    "ArenaRunner",
    "ArenaVerdict",
    "GeminiAI",
    "IAProvider",
    "IARequest",
    "IAResponse",
    "Jury",
    "OllamaAI",
    "OpenCodeAI",
    "create_default_providers",
    "jury_verdict",
    "load_arena_config",
    "run_arena",
    "run_arena_async",
    "run_arena_sync",
    "score_response",
]
