# SPEC-020 — Experience Reformulator

## Livraison

Modules créés :
- `career/exp_constraints.py` — garde-fous anti-invention, verbes d'action, max 2 lignes.
- `career/exp_scorer.py` — score ATS, couverture mots-clés, score jury.
- `career/exp_reformulate.py` — orchestrateur + dataclasses `ReformulatedBullet`, `RecommendVerdict`.
- `career/exp_router.py` — endpoints FastAPI.
- `career_static/js/exp-reformulator.js` — comparateur + apply.

## Validation

- `pytest -q tests/test_exp_reformulator.py` → 15 passed
- `ruff check .` → All checks passed
- `git diff --check` → clean
