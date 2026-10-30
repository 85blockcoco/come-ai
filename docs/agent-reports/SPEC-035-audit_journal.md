# SPEC-035 — Journal d'audit des décisions

## Livré

- `career/audit_journal.py` : `AuditJournal`, `AuditEntry`, `AuditExplanation`, `record()`, `explain()`, `search()`, `entries()`, `list()`, `get()`, `stats()`, `verify()`/`verify_integrity()`.
- Journal append-only, chaîné par sha256 (`prev_hash`), détection d'altération.
- `tests/test_audit_journal.py` : 23 tests (contrat, enregistrement, recherche, explication, persistance, intégrité adversarial, smoke REST).
- `tests/fixtures/audit_synthetic.json` : 8 entrées synthétiques.
- Routes REST dans `career/router.py` : `GET /api/career/audit-journal`, `GET /api/career/audit-journal/integrity`, `GET /api/career/audit-journal/{decision_id}/explanation` (lecture seule).

## Décisions

- Stockage JSONL local, surchargeable par `AUDIT_JOURNAL_PATH`, emplacement par défaut `career_data/audit/audit_journal.jsonl`.
- Validation stricte des champs et payloads JSON ; horodatage ISO 8601 normalisé en UTC.
- Explication déterministe en français avec facteurs contributifs triés.
- Aucune API d'écriture exposée (append-only).

## Limites

- Pas de pagination côté serveur au-delà de `limit`/`offset` déjà supportés.
- Facteurs extraits heuristiquement depuis `context`/`outcome`.
- `tests/test_career_agent.py::test_local_storage_profile_preferences_and_persistence` échoue de manière préexistante (comptage des familles par défaut), sans lien avec ce livrable.