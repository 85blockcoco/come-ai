# N100-G05 — Export groupé (zip)

## Livré
- `career/bundle_export.py` : `create_bundle()`, `list_bundle()`, `BundleResult`.
- Tests `tests/test_bundle_export.py` (6 cas).

## Validation
- `pytest -q tests/test_bundle_export.py` → 6 passed
- `ruff check career/bundle_export.py tests/test_bundle_export.py` → All checks passed