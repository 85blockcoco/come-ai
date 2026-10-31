# N100-B05 — Niveau diplôme requis (BBA/Bac+4/M2/MBA)

## Livré
- `career/degree_level.py` : `detect_degree_level()`, `is_accessible_bba_bac4()`.
- Tests `tests/test_degree_level.py` (11 cas).

## Validation
- `pytest -q tests/test_degree_level.py` → 11 passed
- `ruff check career/degree_level.py tests/test_degree_level.py` → All checks passed