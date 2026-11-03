# N100-C07 — Filtre par type de stage finance

## Livré
- `career/finance_family.py` : `classify_finance_family()`, 8 familles.
- Tests `tests/test_finance_family.py` (11 cas).

## Validation
- `pytest -q tests/test_finance_family.py` → 11 passed
- `ruff check career/finance_family.py tests/test_finance_family.py` → All checks passed