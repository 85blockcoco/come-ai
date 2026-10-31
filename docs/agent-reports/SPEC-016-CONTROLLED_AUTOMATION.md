# SPEC-016 — Automatisation Contrôlée

## Livré
- `career/controlled_automation.py` : `ControlledAutomation`, `AutomationPolicy`,
  `AutomationRun`, `AutomationStep`, `AutomationStatus`, `dashboard()`, `to_dict()`,
  garde-fous (timeout, circuit breaker, retry), points de validation humaine,
  audit trail, rollback.
- Tests `tests/test_controlled_automation.py` (14 cas).

## Décisions
- Orchestration déterministe, locale, aucune IA probabiliste pour les verdicts.
- Validation humaine requise par défaut (opt-in auto via policy).
- Circuit breaker après N échecs consécutifs.
- Audit trail append-only par run.
- Aucune donnée réelle, aucune nouvelle dépendance.

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests).
- Pas de dashboard UI (module Python uniquement).
- Pas d'intégration avec les automatismes existants (pipelines, monitoring) — à câbler.
- Politiques/audit/dashboard modules séparés (automation_policy, automation_audit,
  automation_dashboard) non créés dans cette livraison.

## Validation
- `pytest -q tests/test_controlled_automation.py` → 14 passed
- `ruff check career/controlled_automation.py tests/test_controlled_automation.py` → All checks passed