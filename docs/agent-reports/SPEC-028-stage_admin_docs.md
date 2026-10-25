# SPEC-028 — Checklist documents administratifs stage

## Livré

- Module `career/stage_admin_docs.py` : `AdminItem`, `AdminChecklist`, `REQUIREMENTS_BY_COUNTRY`, `completeness()`, `build_admin_checklist()`, `render_recap()`.
- Pays couverts : France + Royaume-Uni, Allemagne, Pays-Bas, Belgique (codes ISO et alias FR/EN acceptés), soit le socle des connecteurs internationaux déjà branchés.
- Statuts par pièce : `missing`, `in_progress`, `ok`, `not_applicable`.
- Preuves exigées (`required_proofs`) + références de preuves (`proof_refs`) :
  - `missing_proofs` / `proofs_complete` par pièce ;
  - `proofs_required`, `proofs_provided`, `proof_percent`, `missing_proofs` dans `completeness()`.
  - Seules les pièces **requises et applicables** comptent dans le score de preuves ; une pièce optionnelle ou `not_applicable` ne pénalise pas.
- Calcul de complétion (global, pièces requises) + liste `blocking_missing`.
- Récap exportable en Markdown, texte et CSV (`render_recap(..., format="csv")`), avec échappement des cellules Markdown et repli sûr sur le texte pour un format inconnu.
- Validation stricte : statut hors référentiel → `ValueError` côté module et HTTP 422 côté API ; références de preuves dédupliquées, nettoyées (NUL/contrôles) et bornées (`MAX_PROOF_REFS=50`, 240 caractères).
- Fixture 100 % synthétique `tests/fixtures/admin_docs_synthetic.json` : scénarios par pays (statuts, preuves `syn-*`, complétion attendue) + contrat des pièces requises/optionnelles et des preuves exigées.
- Endpoints REST via `create_app()` :
  - `GET /api/career/admin-docs/checklist` (alias `/stage-admin-docs/...`)
  - `POST /api/career/admin-docs/checklist`
  - `GET /api/career/admin-docs/requirements`
  - `GET /api/career/admin-docs/recap`
- Tests : `tests/test_stage_admin_docs.py` — 27 tests (smoke HTTP `create_app()`, cas limites, contrat de fixture, statuts invalides, preuves manquantes, payload adversarial, export CSV).

## Décisions

- Module sans dépendance réseau/LLM/secrets ; toutes les données sont synthétiques et génériques.
- `REQUIREMENTS_BY_COUNTRY` expose exactement cinq pays canoniques ; les alias sont normalisés à la lecture via `normalize_country`, et un pays inconnu ne s'ajoute pas à la carte (repli explicite sur le socle France dans `requirements_for_country`).
- Complétion renvoyée sous forme dict-like comparable à un nombre pour compatibilité avec différents appels.
- Aucune persistance ni écriture base de données : l'état est transmis par l'appelant. Aucune migration, `SCHEMA_VERSION` inchangé.

## Limites

- Les listes sont génériques et indicatives ; à vérifier auprès de l'institution d'accueil et du consulat.
- Les `proof_refs` sont des étiquettes opaques fournies par l'appelant : le module ne lit aucun fichier, URL ou document.
- Pas de génération automatique de documents, pas d'envoi et pas de persistance locale dédiée dans cette version.
