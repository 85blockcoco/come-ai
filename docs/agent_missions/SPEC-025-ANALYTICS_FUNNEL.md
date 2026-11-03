# MISSION SPEC-025 — Analytics funnel candidatures

> **Priorité : P1** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-025-funnel-analytics`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Le suivi existe (statuts candidatures) mais rien ne quantifie où les candidatures meurent.

## Mission
Module analytics : entonnoir de conversion par étape, par semaine et par canal de source, avec détection automatique de l'étape goulot.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/analytics_funnel.py      # compute_funnel(), funnel_by_channel(), weakest_stage()
tests/test_analytics_funnel.py
tests/fixtures/analytics_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class FunnelStage:
    stage: Literal["sent","viewed","prepped","lettered","followed_up","interview","offer"]
    count: int
    conversion_from_prev: float  # 0.0-1.0

@dataclass
class FunnelReport:
    stages: list[FunnelStage]
    weekly_series: dict[str, dict]   # ISO-week -> {stage: count}
    bottleneck_stage: str
    per_channel: dict[str, list[FunnelStage]]
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Entonnoir vide → rapport dégénéré cohérent (jamais de division par zéro).

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-025-analytics_funnel.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-025-funnel-analytics` (jamais main).
