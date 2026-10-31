# CVBOOST-77 — SPEC-042 — Auditeur de qualité de dossier (anti-sur-promesse)

## Livré
- `career/claim_check.py` : `check_claims()`, `Claim`, `ClaimReport`, `ats_keyword_stuffing()`,
  lexique d'exagération versionné.
- `career/dossier_quality.py` : `score_dossier()`, `QualityReport`, `to_dict()`, formule
  transparente (0-100).
- Tests `tests/test_dossier_quality.py` (20 cas, dont adversarial).
- Rapport `docs/agent-reports/CVBOOST-77-DOSSIER_QUALITY.md`.

## Décisions
- Verdict final déterministe (règles locales + lexique), aucune IA probabiliste.
- Score = 0.5*validated_ratio + 0.3*evidence_coverage + 0.2*(1-exaggeration_density),
  pénalisé par le bourrage ATS.
- Aucune donnée réelle, aucune nouvelle dépendance.

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests).
- Pas de fichier de règles externe (lexique en dur, éditable dans le module).
- Pas d'intégration dans le kit 1-clic (step 2) — à câbler.

## Validation
- `pytest -q tests/test_dossier_quality.py` → 20 passed
- `ruff check career/claim_check.py career/dossier_quality.py tests/test_dossier_quality.py` → All checks passed