# SPEC-046 — Détection plateforme ATS & guide humain

## Livré

- `career/ats_guide.py` : détection statique de 10 plateformes
  (`greenhouse`, `lever`, `workday`, `smartrecruiters`, `recruitcrm`,
  `breezy`, `jobvite`, `ashby`, `ripplematch`, `custom`) à partir de l'URL
  et/ou du nom de source.
- `human_apply_guide(job)` : étapes humaines numérotées, champs attendus
  (vocabulaire des quick-answers SPEC-045), compte requis, durée estimée et
  URL directe du formulaire quand le motif est stable.
- `GET /api/career/ats-guide/{job_id}` via `create_career_router()`, sans
  casser `schema_version=7`.
- Repli honnête `platform=None` pour une URL publique inconnue.
- Refus propre (`UnsafeApplyURLError`, HTTP 400) pour les liens dangereux :
  schéma non HTTP(S), identifiants intégrés, caractères de contrôle ou
  d'injection, hôte interne/adresse IP/port non standard.

## Garanties

- Aucune requête HTTP sortante, aucun import réseau.
- Aucune soumission automatique de candidature.
- Fixtures et offres synthétiques uniquement.
- URL directe dérivée localement, sans suivre de redirection.

## Tests

`tests/test_ats_guide.py` — 50 tests :

- détection des 9 ATS + `custom` + inconnu + domaine trompeur ;
- guide complet pour chaque plateforme (étapes, champs, compte, durée) ;
- motifs d'URL directe (Greenhouse `#app`, Lever `/apply`, Workday `/apply`,
  SmartRecruiters `?oga=true`, Ashby `/application`, etc.) ;
- repli générique honnête et source connue sans URL ;
- 14 URL malveillantes ou internes refusées ;
- smoke tests de l'endpoint (200, 400 lien interne, 400 offre inconnue) ;
- absence de code réseau/soumission.

```text
pytest -q tests/test_ats_guide.py                         → 50 passed
pytest -q tests/test_career_application_kit.py \
          tests/test_career_application_prep_regressions.py \
          tests/test_career_public_ats_connectors.py      → 37 passed
ruff check career/ats_guide.py career/router.py tests/test_ats_guide.py
                                                          → All checks passed
```
