# N100-A01 — Connecteur UK (sources internationales finance)

## Livré
- `career/connectors/uk_sources.py` : parseurs prospects/gradcracker/targetjobs.
- Tests `tests/test_uk_sources.py` (9 cas).

## Validation
- `pytest -q tests/test_uk_sources.py` → 9 passed
- `ruff check career/connectors/uk_sources.py tests/test_uk_sources.py` → All checks passed