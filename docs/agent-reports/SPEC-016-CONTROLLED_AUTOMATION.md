# SPEC-016 — Automatisation Contrôlée

## Livré
- Modules: `career/automation_policy.py`, `career/automation_audit.py`, `career/automation_dashboard.py`, `career/controlled_automation.py`.
- Orchestrateur `AutomationOrchestrator` avec submit/get/pause/resume/cancel/approve_checkpoint/get_dashboard_data.
- Endpoints REST `/automation/*` et alias `/api/career/automation/*`.
- UI `career_static/js/automation-dashboard.js`.
- Tests `tests/test_controlled_automation.py`.

## Décisions
- Exécution synchrone locale, points de validation humaine bloquants.
- Audit trail in-memory avec export JSON/CSV.
- Aucune soumission automatique; tous les effets externes restent derrière checkpoint humain.

## Limites
- Pas de persistance SQLite des exécutions (in-memory).
- Circuit breaker simplifié.
- UI minimale.
