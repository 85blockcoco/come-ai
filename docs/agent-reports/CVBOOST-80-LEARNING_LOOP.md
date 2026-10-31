# CVBOOST-80 — SPEC-045 — Boucle d'apprentissage variantes → résultats

## Livré
- `career/learning.py` : `Experience`, `LearningStore` (SQLite), `analyze()`,
  `VariantStats`, `LearningReport`, `to_dict()`.
- Tests `tests/test_learning.py` (10 cas).

## Décisions
- Analyse descriptive uniquement, aucune IA/ML.
- Verrou n<30 : `model_allowed=False` en dessous du seuil.
- Corrélation jamais présentée comme causalité (disclaimer explicite).
- Un moteur appris ne remplace jamais l'audit qualité ni l'éligibilité.
- Aucune donnée réelle, aucune nouvelle dépendance.

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests).
- Pas de saisie manuelle UI (à câbler).
- Intervalle de Wald simple (indicatif).

## Validation
- `pytest -q tests/test_learning.py` → 10 passed
- `ruff check career/learning.py tests/test_learning.py` → All checks passed