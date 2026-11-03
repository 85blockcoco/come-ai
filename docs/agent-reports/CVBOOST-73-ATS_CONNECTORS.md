# CVBOOST-73 — SPEC-038 — Connecteurs pages-carrières banques & détection ATS

## Livré
- `career/connectors/ats_registry.py` : `detect_ats()`, `load_banks_list()`, `ats_for_bank()`,
  signatures versionnées (workday, successfactors, greenhouse, taleo, smartrecruiters,
  cameo, aplica, lever, ashby, unknown).
- `career/connectors/ats_generic.py` : `fetch_html()` (borné, 429 backoff), `parse_job()`
  (JSON-LD, Greenhouse, SmartRecruiters, fallback title/meta), `parse_job_from_url()`.
- `career/connectors/banks_list.json` : liste locale éditable de banques.
- Tests `tests/test_ats_connectors.py` (45 cas).
- Rapport `docs/agent-reports/CVBOOST-73-ATS_CONNECTORS.md`.

## Décisions
- Stdlib uniquement (urllib, json, re, ssl). Aucune nouvelle dépendance.
- Aucun auth, aucun envoi. Respect 429 avec backoff.
- Liste des banques externalisée dans JSON éditable.

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests).
- Polling par lot / TTL 24h non implémenté (à câbler par l'appelant).
- Pas de tests live (réseau désactivé par défaut).

## Validation
- `pytest -q tests/test_ats_connectors.py` → 45 passed
- `ruff check career/connectors/ats_registry.py career/connectors/ats_generic.py tests/test_ats_connectors.py` → All checks passed