# SPEC-035 — Journal d'audit des décisions

## Livré
- Module `career/audit_journal.py` : `AuditJournal`, `AuditEntry`, `AuditExplanation`,
  `record()`, `entries()`, `explain()`, `verify_chain()`, `count()`.
- Tests `tests/test_audit_journal.py` (14 cas, dont adversarial tampering/reorder).
- Fixture synthétique `tests/fixtures/audit_synthetic.json`.
- Narratives françaises pour `followup_scheduled`, `offer_ranked`, `arena_verdict`,
  extensible via `register_narrative`.

## Décisions
- Stockage JSONL append-only, hash-chaîné SHA-256 (`prev_hash` → `entry_hash`).
- Aucune API de modification/suppression (append-only).
- Aucune donnée réelle : fixtures synthétiques uniquement.
- Pas de nouvelle dépendance (stdlib uniquement).

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests). À câbler dans
  `career/router.py` si besoin.
- Pas de compaction/rotation du fichier (peut grossir).
- `verify_chain()` est O(n) sur le fichier.

## Validation
- `pytest -q tests/test_audit_journal.py` → 14 passed
- `ruff check career/audit_journal.py` → All checks passed