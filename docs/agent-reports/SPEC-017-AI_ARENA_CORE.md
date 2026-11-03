# Rapport — SPEC-017 — AI Arena Core

## Livraison
- Package `career/ai/` : `__init__.py`, `models.py`, `providers.py`, `arena.py`, `jury.py`, `cache.py`, `config.py`.
- Types : `IARequest`, `IAResponse`, `ArenaVerdict`.
- Providers : `OpenCodeAI`, `OllamaAI`, `GeminiAI` + protocole `IAProvider` + `create_default_providers`.
- Orchestration : `run_arena` (sync/async), concurrence `asyncio`, timeouts par provider/global, skip silencieux.
- Jury déterministe : `score_response`, `score_responses`, `jury_verdict`, `merge_bullets`, `disagreement_of`.
- Cache : `ArenaCache` avec activation/désactivation (`use_cache`, `enabled`), invalidation par version.
- Config : `ArenaConfig`, `load_arena_config` (env).

## Tests
- `tests/test_ai_arena.py` : 12 cas (2+ providers, indisponibilité, exception, timeout, réponse vide/malformée, cache on/off, async, providers par défaut, jury).
- `pytest -q` : 1436 passed, 1 skipped.
- `ruff check .` : All checks passed.
- `git diff --check` : propre.

## Notes
- Aucun appel réseau au chargement ; providers indisponibles ignorés sans exception.
- Clés uniquement via environnement (`GEMINI_API_KEY`, `OPENCODE_*`, `OLLAMA_BASE_URL`).
