# SPEC-011 — Registre de traçabilité des exigences

Statut : TERMINÉE (testé sur données synthétiques ; aucun réseau ; aucune donnée personnelle réelle ; aucune candidature envoyée).

Mission : CVBOOST-46 — SPEC-011, branche `worker/cvboost-46-1792666523`,
worktree `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-46-1792666523`.

## 1. Ce qui a été construit

| Fichier | Rôle |
| --- | --- |
| `career/traceability.py` | Cœur pur : `RequirementTrace`, `TraceEvent`, `TraceabilityRegistry`, règles métier, mappages SK-02, liaison automatique SK-21 |
| `career/traceability_store.py` | Persistance SQLite : `TraceabilityStore` (tables `traceability_traces` / `traceability_events`) + `TraceabilityService` (façade API) |
| `career/traceability_audit.py` | Rapports d'audit purs : couverture, gaps, dérogations, timeline, évolution, incohérences, export CSV/JSON |
| `career/router.py` | 22 endpoints `/api/career/traceability/...` (CRUD, audit, export/import, actions de lot) |
| `career/service.py` | Intégration : création automatique à l'import d'offre (SK-02), liaison automatique au matching (SK-21), effacement à la remise à zéro |
| `career_static/js/traceability.js` | Module d'interface : filtres, tri, historique par exigence, actions de lot, export |
| `career_static/index.html` | Onglet « Traçabilité » + vue `view-traceability` |
| `career_static/career.js` | Enregistrement de la vue (`careerViews`, `labelForView`, `refreshView`) |
| `career_static/career.css` | Styles de la vue (lignes, faits, timeline, actions de lot) |
| `tests/test_traceability.py` | 68 tests : règles métier, persistance, audit, API HTTP, intégration Career, garde-fous d'interface |

La base du registre est **séparée** : `career_data/traceability.sqlite3`.
Elle ne dépend pas du schéma `career.sqlite3` (aucune migration, aucun
`SCHEMA_VERSION` touché), reste hors Git (`.gitignore` → `career_data/`) et
n'est créée qu'à la première utilisation.

## 2. Contrat livré

### `RequirementTrace` (entité centrale)

Champs du contrat : `trace_id`, `requirement_id`, `requirement_text`, `source`,
`category`, `criticality`, `evidence_id`, `evidence_quote`, `status`,
`created_at`, `updated_at`, `history`, `tags`.

Champs ajoutés (audit et integration, sans modifier le contrat) :
`offer_id`, `cv_id`, `locator`, `source_field`, `confidence` (provenance SK-02),
`link_origin` (`manual` / `auto`), `review_state`
(`not_required` / `pending` / `confirmed` / `rejected`), `match_kind`,
`deleted` + `deleted_at` (suppression logique : la piste d'audit reste
lisible).

### `TraceEvent` (historique)

`event_id`, `timestamp`, `event_type`, `old_value`, `new_value`, `actor`
(`system` / `user` / `worker`), `comment`.

Types du contrat : `created`, `linked`, `unlinked`, `status_changed`,
`category_changed`, `criticality_changed`, `waived`, `reopened`.
Extensions additives (documentées dans le module) : `tags_changed`,
`deleted`, `link_confirmed`, `link_rejected` — elles servent la règle
« toute modification est tracée », l'objectif « traquer les suppressions »
et la validation manuelle des liaisons automatiques.

### Vocabulaire

`category` : `skill`, `experience`, `education`, `language`, `tool`,
`certification`, `soft_skill`, `other`.
`criticality` : `mandatory`, `preferred`, `nice_to_have`, `contextual`.
`status` : `uncovered`, `covered`, `partial`, `contradicted`, `waived`.

### Déterminisme

- `trace_id` = `trace_` + UUID **version 5** dérivé de `(source, requirement_id)` :
  réimporter la même exigence retombe sur la même trace (import idempotent,
  jamais de doublon d'événement).
- `event_id` = hachage du contenu de l'événement (trace, type, horodatage,
  anciennes et nouvelles valeurs, index) : pas de `random`, pas d'horloge
  cachée.
- L'horloge est injectable (`clock=`) : une scène se rejoue à l'identique.

## 3. Règles métier appliquées

| Règle de la mission | Implémentation |
| --- | --- |
| 1. Création auto à l'extraction d'une offre (SK-02) | `CareerService.import_job` → `sync_traceability_requirements` → `analyze_offer` (SK-02) → `register_offer_analysis`. Import idempotent. |
| 2. Liaison auto au matching (SK-21) | `CareerService.get_job_prep` → `sync_traceability_evidence` → `auto_link_evidence`. Correspondance **exacte** seulement (`exact_claim`, `verbatim_quote` avec ≥ 12 caractères normalisés) ; la liaison reste `review_state="pending"`, le statut ne change pas. |
| 3. Validation manuelle | `POST .../confirm` (→ `covered`, `review_state="confirmed"`) et `POST .../reject` (→ preuve retirée, `uncovered`, `review_state="rejected"`). |
| 4. Immuabilité de l'historique | `TraceEvent` est *frozen* ; les événements ne sont jamais modifiés ni supprimés (`INSERT OR IGNORE` sur `event_id`) ; le texte et la source de l'exigence ne sont jamais réécrits. |
| 5. Cohérence « covered = preuve + citation » | `set_status("covered")` est refusé sans `evidence_id` **et** `evidence_quote` ; une liaison manuelle sans citation ne couvre pas ; remplacer une preuve citée par une preuve sans citation fait retomber le statut orphelin sur `uncovered` (événement `status_changed` tracé). |
| 6. Audit trail | Chaque mutation écrit un événement daté avec `actor` et `comment` ; la suppression est logique (`deleted`) et laisse l'historique. |

Garde-fous supplémentaires :

- les passages `injection_suspect` de SK-02 **ne deviennent jamais** des
  exigences (une offre est une donnée, pas une instruction) ;
- une dérogation (`waived`) exige une justification écrite, lisible dans
  l'historique et dans le rapport « waived » ;
- un registre vide donne 0 %, jamais 100 % ;
- le rapport d'audit expose les incohérences au lieu de les réparer
  (`covered_without_proof`, `partial_without_proof`, `covered_without_review`).

## 4. API HTTP

Toutes les routes sont sous `/api/career/traceability` (le préfixe de l'espace
Career). Le contrat littéral de la mission est **aussi** exposé sans ce
préfixe : `/traceability/requirements`, `/traceability/audit/coverage`,
`/traceability/export`, etc. Les deux espaces désignent exactement les mêmes
opérations (aucune duplication de code : les routes sont aliasées sur les
mêmes handlers).

| Méthode | Route | Rôle |
| --- | --- | --- |
| `POST` | `/requirements` | Créer une exigence (201) |
| `GET` | `/requirements` | Liste filtrée : `status`, `category`, `criticality`, `offer_id`, `cv_id`, `source`, `tag`, `query`, `review_state` |
| `GET` | `/requirements/{trace_id}` | Détail complet + historique |
| `PATCH` | `/requirements/{trace_id}` | Modifier statut, catégorie, criticité, tags |
| `DELETE` | `/requirements/{trace_id}` | Suppression logique (historique conservé) |
| `POST` | `/requirements/{trace_id}/link-evidence` | Lier une preuve (cité) |
| `POST` | `/requirements/{trace_id}/unlink-evidence` | Délier la preuve |
| `POST` | `/requirements/{trace_id}/waive` | Dérogation motivée |
| `POST` | `/requirements/{trace_id}/reopen` | Lever la dérogation |
| `POST` | `/requirements/{trace_id}/confirm` | Valider une liaison automatique |
| `POST` | `/requirements/{trace_id}/reject` | Rejeter une liaison automatique |
| `POST` | `/batch` | Actions de lot (`confirm`, `reject`, `unlink`, `waive`) — un échec n'annule pas les autres |
| `POST` | `/offer-analysis` | Enregistrer une analyse SK-02 |
| `POST` | `/auto-link` | Proposer des liaisons automatiques (SK-10 / SK-21) |
| `GET` | `/audit/coverage` | Couverture globale, par offre, par CV |
| `GET` | `/audit/gaps` | Exigences obligatoires non couvertes |
| `GET` | `/audit/waived` | Dérogations et justifications |
| `GET` | `/audit/history` | Historique global filtré (trace, type, acteur, période) |
| `GET` | `/audit/evolution` | Courbe de couverture reconstruite par rejeu de l'historique |
| `GET` | `/audit/report` | Rapport d'audit complet + incohérences |
| `GET` | `/export?export_format=json\|csv` | Export complet |
| `POST` | `/import` | Import d'un export (idempotent, historique fusionné) |

## 5. Rapports d'audit

| Rapport demandé | Fonction |
| --- | --- |
| Couverture par offre | `coverage_by_offer` (total, évalué, couvert, partiel, non couvert, contredit, dérogé, taux global et obligatoire) |
| Couverture par CV | `coverage_by_cv` |
| Gaps critiques | `critical_gaps` (obligatoires non couvertes, `partial` et `contradicted` inclus) |
| Historique des changements | `history_timeline` (filtres trace / type / acteur / période) |
| Exigences levées | `waived_requirements` (justification et date de la dérogation) |
| Évolution dans le temps | `coverage_over_time` (rejeu chronologique des événements) |
| Vue d'ensemble | `coverage_summary` (par statut, catégorie, criticité, revues en attente) |
| Cohérence | `audit_report` → `inconsistencies` |

## 6. Interface locale

Nouvel onglet « Traçabilité » (`career_static/js/traceability.js`, autonome,
sans dépendance externe) :

- **filtres** : statut, catégorie, criticité, état de validation, offre,
  recherche plein texte ;
- **tri déterministe** : criticité → statut → texte (aucune « pertinence »
  estimée dans le navigateur) ;
- **indicateurs** : total, taux de couverture, taux de couverture des
  obligations, liaisons en attente (chiffres venus de l'API locale) ;
- **historique par exigence** : panneau de détail avec la timeline des
  événements (type, acteur, horodatage, commentaire) ;
- **actions** : valider / rejeter une liaison automatique, retirer une preuve,
  lever une exigence, lever une dérogation ;
- **actions de lot** : sélection multiple puis `confirm`, `reject`, `unlink`,
  `waive` (rapport par exigence : appliquée / en échec) ;
- **export** : liens JSON et CSV vers l'API locale.

Règle d'honnêteté appliquée dans l'interface : le module ne déclare jamais un
statut lui-même (`status: "covered"` n'apparaît pas dans le code JS), il
affiche celui renvoyé par l'API ; une liaison automatique en attente est
explicitement signalée « à valider ».

## 7. Preuves réelles

- Tests ciblés : `68 passed` (`tests/test_traceability.py`).
- Suite complète : `1487 passed, 1 skipped` (le skip est préexistant :
  `tests/test_offer_summary_exhaustiveness.py` — script ou base absents).
- `ruff check .` : `All checks passed!`.
- `git diff --check` : propre.
- `node --check career_static/js/traceability.js` : OK.
- Routes vérifiées : 19 chemins / 22 opérations sous `/api/career/traceability`
  (+ les alias `/traceability/...`), aucun doublon de méthode.
- `./checklist_codex.sh` : voir §8.

### Relation avec la tentative précédente

Une tentative antérieure de la même mission a été poussée sur
`origin/worker/cvboost-46-1792666436` (commits `86a6f88` + `71d14c1`) :
même périmètre, mais persistance JSON et **sans** intégration du service
Career (pas de création automatique à l'import d'offre, pas de liaison
automatique au matching) et avec une base de tests plus réduite.

La branche livrée ici (`worker/cvboost-46-1792666523`) reprend le correctif
de cohérence de `71d14c1` (une liaison de preuve sans citation fait retomber
un statut `covered` orphelin sur `uncovered`, covered par un test de
régression) et ajoute ce qui manquait :

- l'intégration Career (SK-02 → registre, SK-21 → proposition de liaison) ;
- une persistance SQLite indexée dans `career_data/` (indépendante du schéma
  `career.sqlite3`, donc sans migration) ;
- les rapports `audit/evolution` et les actions de lot ;
- 68 tests contre 30.

C'est cette branche qu'il faut relire et intégrer ; l'ancienne peut être
abandonnée.

## 8. Checklist de validation

`./checklist_codex.sh` exécuté dans le worktree avec le venv du dépôt principal
(`VENV_PY` / lien `.venv` local, non versionné) :

| Étape | Résultat |
| --- | --- |
| 1. Tests main | ✅ 1484 passed, 1 skipped |
| 2-4. Worktrees mémoire / profil | ⚠️ absents dans ce worktree (étapes ignorées, préexistant) |
| 5. Aucun secret tracké | ✅ aucun fichier sensible ajouté |
| 6. Mémoire injectée dans le chat | ⚠️ non concerné par SPEC-011 (rappel affiché) |
| 7. DevKit | ✅ vert |
| 8. Study Coach | ⚠️ worktree absent (ignoré) |
| 9. Empreinte DevKit | ⚠️ rapports absents (étape ignorée) |
| 10. Lint ruff | ✅ All checks passed |
| 11. Interdits | ✅ rappel affiché |

## 9. Limites honnêtes

- SK-10 (centre de preuves) et SK-21 (matching CV↔offre) vivent sur d'autres
  branches : le registre consomme leurs sorties **par contrat public** (dictionnaires
  ou objets portant `evidence_id` / `claim` / `quote`), jamais par import dur.
  Tant que ces modules ne sont pas fusionnés, la liaison automatique est
  alimentée par le matching local existant (`application_prep`), pas par
  SPEC-008.
- La couverture d'une exigence est déclarée **manuellement** (ou après
  validation d'une liaison automatique). Le registre ne « calcule » pas une
  couverture : il enregistre, relie et trace.
- Le matching automatique est volontairement restrictif (égalité normalisée ou
  citation verbatim ≥ 12 caractères). Une preuve proche mais non identique
  n'est pas liée : mieux vaut une « non couverte » signalée qu'une couverture
  inventée.
- La suppression est logique : la trace reste dans l'export et dans
  l'historique. Seule la remise à zéro des données personnelles efface
  réellement le registre.
- Aucune vérification navigateur réelle n'a été faite (hors périmètre de la
  mission) : les garde-fous d'interface sont des tests statiques et un test
  Node du tri déterministe.
- La base `career_data/traceability.sqlite3` n'est pas incluse dans
  `career/privacy-export` (qui exporte le périmètre `career.sqlite3`) ; elle
  reste néanmoins effacée par la remise à zéro des données Career.

## 10. Rollback

Modifications additives sur une branche dédiée :
`git revert` du commit, ou suppression des fichiers listés au §1. Aucune
migration de base existante, aucun changement de schéma `career.sqlite3`,
aucune modification d'un consommateur de l'interface Career au-delà de
l'ajout d'un onglet (réversible en retirant l'onglet, la vue et l'appel du
module).
