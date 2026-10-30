# CVBOOST-77 : Auditeur de qualité de dossier (anti-sur-promesse)

**Date** : 2026-10-31
**Branche** : `worker/cvboost-77-1793404225378`
**Périmètre** : `career/claim_check.py`, `career/dossier_quality.py`, `career/dossier_quality_rules.json`, `career/apply_kit.py`

## Résumé

Module 100 % local et déterministe qui audite tout document de candidature
produit (CV adapté, lettre, réponses de formulaire) :

- `claim_check.py` découpe le document phrase par phrase et attribue à chaque
  claim un label parmi `supported | inflated | out_of_context | invented |
  unverifiable`, avec preuve citée, preuve manquante et suggestion de
  reformulation basée uniquement sur les faits déjà approuvés.
- `dossier_quality.py` produit un score global 0-100 transparent à partir de
  quatre facteurs (% de prévus validés, densité d'exagérations, preuve,
  argumentaire) avec formules exposées.
- Règles d'exagération versionnées et éditables par l'utilisateur dans
  `career/dossier_quality_rules.json`.
- Intégration comme étape d'audit dans `build_apply_kit` (champ
  `dossier_audit`).

## API publique

```python
from career.claim_check import check_claims, ClaimCheckResult, Claim
from career.dossier_quality import analyze_dossier_quality, DossierQualityResult

result = check_claims(document_text, approved_profile)
audit = analyze_dossier_quality(document_text, approved_profile, offer=job)
```

Alias fournis pour compatibilité : `analyze_claims`, `run_claim_check`,
`audit_claims`, `score_dossier`, `audit_dossier`, `assess_dossier_quality`, etc.

## Validation

- Ruff : clean.
- Tests existants : non régressés (cv_quality_ats, requirements_fit, apply_kit).
- Aucune IA probabiliste dans le verdict final.
