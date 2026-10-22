"""AI Arena: concurrent multi-provider engine for Career adaptation."""

from .arena import (
    IARequest,
    IAResponse,
    ArenaVerdict,
    run_arena,
    Arena,
)
from .cache import ArenaCache
from .config import ArenaConfig, get_config
from .jury import score_responses, merge_bullets, compute_disagreement
from .providers import (
    IAProvider,
    OpenCodeAI,
    OllamaAI,
    GeminiAI,
    default_providers,
    ProviderError,
)
from .router import create_ai_router

__all__ = [
    "IARequest",
    "IAResponse",
    "ArenaVerdict",
    "run_arena",
    "Arena",
    "ArenaCache",
    "ArenaConfig",
    "get_config",
    "score_responses",
    "merge_bullets",
    "compute_disagreement",
    "IAProvider",
    "OpenCodeAI",
    "OllamaAI",
    "GeminiAI",
    "default_providers",
    "ProviderError",
    "create_ai_router",
]
