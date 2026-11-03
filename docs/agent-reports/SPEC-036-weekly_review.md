# SPEC-036 — Bilan hebdo & objectifs

## Livré
- Module `career/weekly_review.py` : `WeeklySummary`, `Objective`, `weekly_summary()`,
  `objective_check()`, `recommend_next()`, `to_dict()`.
- Tests `tests/test_weekly_review.py` (12 cas).
- Fixture synthétique `tests/fixtures/weekly_synthetic.json`.

## Décisions
- Agrégation pure et déterministe, aucune dépendance externe.
- Objectifs absents → `objective_met=None`, recommandations basées sur les données seules.
- Max 3 actions recommandées, dédupliquées.
- Aucune donnée réelle.

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests).
- Pas de persistance : l'appelant fournit les événements.
- Pas de comparaison semaine N vs N-1 (peut être ajouté).

## Validation
- `pytest -q tests/test_weekly_review.py` → 12 passed
- `ruff check career/weekly_review.py tests/test_weekly_review.py` → All checks passed