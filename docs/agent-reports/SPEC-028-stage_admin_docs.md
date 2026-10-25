# SPEC-028 — Checklist documents administratifs stage

## Livré

- Module `career/stage_admin_docs.py` : `AdminItem`, `AdminChecklist`, `REQUIREMENTS_BY_COUNTRY`, `completeness()`, `build_admin_checklist()`, `render_recap()`.
- Pays couverts : France + Royaume-Uni, Allemagne, Pays-Bas, Belgique (aliases codes/ISO acceptés).
- Statuts par pièce : `missing`, `in_progress`, `ok`, `not_applicable`.
- Preuves exigées (`required_proofs`) + références de preuves (`proof_refs`).
- Calcul de complétion (global et pièces requises) + liste `blocking_missing`.
- Récap exportable (Markdown/texte).
- Endpoints REST via `create_app()` :
  - `GET /api/career/admin-docs/checklist` (alias `/stage-admin-docs/...`)
  - `POST /api/career/admin-docs/checklist`
  - `GET /api/career/admin-docs/requirements`
  - `GET /api/career/admin-docs/recap`
- Tests : `tests/test_stage_admin_docs.py` (17 tests, dont smoke HTTP et cas adversarial).

## Décisions

- Module sans dépendance réseau/LLM/secrets ; données synthétiques et génériques.
- `REQUIREMENTS_BY_COUNTRY` normalise les pays via `normalize_country` (codes et alias) sans augmenter le nombre de pays canoniques.
- Complétion renvoyée sous forme dict-like comparable à un nombre pour compatibilité avec différents appels.
- Aucune persistance base de données : état transmis par l'appelant (pas de changement de schéma).

## Limites

- Les listes sont génériques et indicatives ; à vérifier auprès de l'institution d'accueil et du consulat.
- Pas de génération automatique de documents ni d'envoi.
- Pas de persistance locale dédiée dans cette version.