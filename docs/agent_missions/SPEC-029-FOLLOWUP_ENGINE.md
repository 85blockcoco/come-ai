# MISSION SPEC-029 — Moteur de relances chronologiques

> **Priorité : P1** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-029-followup-engine`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
SPEC-025 dit QUI relancer ; il faut le QUAND et le COMBIEN (anti-spam).

## Mission
Planificateur de relances : lit candidatures + historique, calcule les actions du jour, refuse les sur-relances, s'intègre au cockpit existant.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/followup_engine.py        # FollowupPolicy, plan_today(), spam_guard()
tests/test_followup_engine.py
tests/fixtures/followups_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class FollowupAction:
    application_id: str
    due_date: str                  # ISO
    reason: str                    # no_response_j7, viewed_no_reply, deadline_soon
    channel: Literal["email","portal","in_person"]

@dataclass
class FollowupPlan:
    date: str
    actions: list[FollowupAction]
    blocked_reasons: dict[str, str]  # app_id -> pourquoi bloqué
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Windows : première relance J+7 ; jamais < 5 jours entre 2 relances d'une même candidature.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-029-followup_engine.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-029-followup-engine` (jamais main).
