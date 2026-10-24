# SPEC-028 — Checklist documents administratifs stage

## Livré

- Module `career/stage_admin_docs.py` : `AdminItem`, `AdminChecklist`, `REQUIREMENTS_BY_COUNTRY`, `build_checklist`, `completeness`, `update_item`.
- Exigences par pays : FR + pays couverts par les connecteurs internationaux (GB, DE, NL, BE, LU, CH, IT, ES, PT, IE, AT), repli générique INTL pour pays inconnu.
- Routes REST dans `career/router.py` : `/api/career/stage-admin-docs`, `/api/career/stage-admin-docs/{country}`, `/api/career/admin-docs`, POST de mise à jour.
- Service : `get_stage_admin_docs`, `update_stage_admin_docs`.
- Fixture synthétique `tests/fixtures/admin_docs_synthetic.json`.
- Tests : `tests/test_stage_admin_docs.py` (20 cas, dont cas limites et adversarial).

## Décisions

- Aucune donnée réelle ; fixtures synthétiques uniquement.
- `blocking_missing` recalculé automatiquement depuis les items requis au statut `missing`.
- `completeness()` retourne une fraction 0.0–1.0 (part des items `ok` ou `not_applicable`).
- Pays inconnu → repli sur le jeu international (visa + autorisation de travail).
- Aucun changement de `SCHEMA_VERSION`.

## Limites

- Les exigences sont des modèles déterministes, pas des conseils juridiques.
- Pas de persistance en base : la checklist est reconstruite à la demande.
- Les statuts sont fournis par l'appelant (UI) ; aucune vérification documentaire automatique.
