# MISSION SPEC-036 — Bilan hebdo & objectifs

> **Priorité : P2** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-036-weekly-review`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Un bilan hebdomadaire (candidatures, effort vs résultats) motive et cale les objectifs.

## Mission
Agrégateur hebdo : N candidatures envoyées, taux de réponse, temps par étape, comparaison à l'objectif fixé, top 3 actions recommandées pour la semaine suivante.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/weekly_review.py          # weekly_summary(), objective_check(), recommend_next()
tests/test_weekly_review.py
tests/fixtures/weekly_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class WeeklySummary:
    iso_week: str
    applications_sent: int
    responses: int
    interview_rate: float
    objective_met: bool | None
    top_actions: list[str]         # max 3

@dataclass
class Objective:
    metric: Literal["applications","responses","interviews"]
    target: int

```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Objectifs absents → objective_met=None et top_actions basées sur les données seules.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-036-weekly_review.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-036-weekly-review` (jamais main).
