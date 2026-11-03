# N100-D04 — Registre de preuves (evidence)

## Livré
- `career/evidence_registry.py` : `Evidence`, `EvidenceRegistry` (add, list, get, verify_chain).
- Tests `tests/test_evidence_registry.py` (8 cas, dont adversarial).

## Validation
- `pytest -q tests/test_evidence_registry.py` → 8 passed
- `ruff check career/evidence_registry.py tests/test_evidence_registry.py` → All checks passed