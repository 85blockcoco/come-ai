# MISSION SPEC-032 — Mode hors-ligne & cache local

> **Priorité : P1** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-032-offline-cache`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
L'app doit rester utilisable sans réseau (train, Ariège, coupures) : recherche, dossier, checklist.

## Mission
Couche de cache local ?expire? pour les lectures (offres vues, checklists, dossiers) avec politique de fraîcheur et bandeau d'état hors-ligne.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/offline_mode.py           # OfflineCache, freshness_policy(), serve_or_cache()
tests/test_offline_mode.py
tests/fixtures/offline_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class CacheEntry:
    key: str
    payload: dict
    fetched_at: str                # ISO
    max_age_hours: int

@dataclass
class OfflineDecision:
    source: Literal["network","cache","stale"]
    age_hours: float | None
    degraded_fields: list[str]     # champs servis 'stale'
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Aucune écriture de donnée personnelle hors du workspace local ; cache chiffrable à disque (accepté: plain JSON tant que local user dir).

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-032-offline_mode.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-032-offline-cache` (jamais main).
