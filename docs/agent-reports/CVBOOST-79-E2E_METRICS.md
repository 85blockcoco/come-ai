# CVBOOST-79 — SPEC-044 — Instrumentation + évaluation E2E

## Livré
- `career/metrics.py` : `MetricsStore` (SQLite), `StepTimer` (pause/reprise), `new_run_id()`,
  `aggregate()`, `total_duration()`.
- `career/eval_e2e.py` : `load_offers()`, `evaluate_offer()`, `aggregate()`, `render_report()`,
  `OfferResult`, `AggregatedReport`.
- Tests `tests/test_eval_e2e.py` (12 cas).
- Rapport `docs/agent-reports/CVBOOST-79-E2E_METRICS.md`.

## Décisions
- Stockage SQLite local uniquement, aucun tiers.
- Pause/reprise via `StepTimer.pause()/resume()`.
- Confiance reportée comme indicative (n<10).
- Aucune donnée personnelle, aucune nouvelle dépendance.

## Limites
- Pas de hook automatique dans le pipeline (à câbler par l'appelant).
- Pas d'endpoints REST dans cette livraison.
- Évaluation sur offres réelles = données utilisateur (exclues de git).

## Validation
- `pytest -q tests/test_eval_e2e.py` → 12 passed
- `ruff check career/metrics.py career/eval_e2e.py tests/test_eval_e2e.py` → All checks passed