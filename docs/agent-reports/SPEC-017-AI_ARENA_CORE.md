# SPEC-017 — AI Arena Core

Module multi-IA concurrent pour l'adaptation Career.

## Modules livrés

- `career/ai/__init__.py`
- `career/ai/models.py` — `IARequest`, `IAResponse`, `ArenaVerdict`
- `career/ai/config.py` — `ArenaConfig`, `get_config()` (env only)
- `career/ai/cache.py` — `ArenaCache` (memoization, version, toggle)
- `career/ai/providers.py` — `IAProvider`, `OpenCodeAI`, `OllamaAI`, `GeminiAI`, `default_providers`
- `career/ai/jury.py` — scoring déterministe, merge, disagreement
- `career/ai/arena.py` — `run_arena()`, `Arena`
- `career/ai/router.py` — `create_ai_router()` (POST/GET endpoints)

## Règles respectées

- Concurrence async (`asyncio.gather`), timeout par IA 30s, global 45s (configurable).
- Provider indisponible ignoré silencieusement.
- Secrets uniquement via env.
- Dispute > 0.5 → ré-évaluation best effort avec un provider supplémentaire.
- Cache désactivable (env `AI_ARENA_CACHE=0` ou `use_cache=False`).

## Tests

`tests/test_ai_arena.py` (à ajouter) couvre providers KO, timeout, réponse vide, hors-format, cache off.
