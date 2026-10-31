# N100-F01 — Lettre de motivation ciblée

## Livré
- `career/cover_letter.py` : `CoverLetter`, `build_cover_letter()`, `to_dict()`.
- Tests `tests/test_cover_letter.py` (7 cas).

## Décisions
- Génération à partir de faits approuvés uniquement.
- Placeholder explicite si aucune preuve.
- Aucune donnée réelle, aucune nouvelle dépendance.

## Validation
- `pytest -q tests/test_cover_letter.py` → 7 passed
- `ruff check career/cover_letter.py tests/test_cover_letter.py` → All checks passed