# SPEC-032 — Mode hors-ligne & cache local

## Livré
- Module `career/offline_mode.py` : `CacheEntry`, `OfflineDecision`, `OfflineCache`, `freshness_policy()`, `serve_or_cache()`.
- Cache persistant local (JSON, un fichier par clé) avec TTL (`max_age_hours`).
- Politique de fraîcheur : `source` ∈ {network, cache, stale}, `age_hours`, `degraded_fields`.
- Stratégie de lecture `serve_or_cache` : réseau d'abord, repli cache, détection stale.
- Endpoints REST via `create_career_router()` :
  - `GET /api/career/offline/status`
  - `GET /api/career/offline/cache/{key}`
  - `POST /api/career/offline/cache`
  - `DELETE /api/career/offline/cache/{key}`
- Fixture synthétique `tests/fixtures/offline_synthetic.json`.
- Tests `tests/test_offline_mode.py` (24 tests, cas limites + adversarial).

## Décisions
- Stockage plain JSON dans le répertoire utilisateur local (`career_data/offline_cache`), permissions 0600/0700.
- Aucune donnée réelle : fixtures synthétiques uniquement.
- Pas de migration de schéma SQLite (cache hors base).
- `OfflineCache` accepte un chemin ou un objet duck-typed pour faciliter les tests.

## Limites
- Le cache n'est pas chiffré (plain JSON local), conformément à l'acceptation de la spec.
- Pas de synchronisation automatique ni d'invalidation cross-process avancée.
- Le bandeau hors-ligne côté UI consomme `/api/career/offline/status`.

## Validation
- `pytest -q tests/test_offline_mode.py` → 24 passed
- `ruff check .` → All checks passed
- `git diff --check` → CLEAN
"""