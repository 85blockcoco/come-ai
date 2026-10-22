# SPEC-011 — Registre de traçabilité des exigences

Statut : TERMINÉE (testé sur données synthétiques ; aucun réseau ; aucune donnée personnelle réelle ; aucune candidature envoyée).

Mission : CVBOOST-46 — SPEC-011, branche `agent/spec-011-traceability`
(branche de travail `worker/cvboost-46-1792684254`, worktree
`/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-46-1792684254`).

Cette livraison reprend la livraison déjà présente sur
`agent/spec-011-traceability` (campagne précédente, ordre
`cvboost-46-1792666523`) et lui ajoute une **campagne adversariale** :
10 défauts réels du registre ont été reproduits, corrigés dans le code, puis
verrouillés par 30 tests dédiés (§8).

## 1. Ce qui a été construit

| Fichier | Rôle |
| --- | --- |
| `career/traceability.py` | Cœur pur : `RequirementTrace`, `TraceEvent`, `TraceabilityRegistry`, règles métier, mappages SK-02, liaison automatique SK-21 |
| `career/traceability_store.py` | Persistance SQLite : `TraceabilityStore` (tables `traceability_traces` / `traceability_events`) + `TraceabilityService` (façade API) |
| `career/traceability_audit.py` | Rapports d'audit purs : couverture, gaps, dérogations, remplacements, timeline, évolution, incohérences |
| `career/router.py` | 23 endpoints `/api/career/traceability/...` (CRUD, audit, export/import, actions de lot) + les 23 alias `/traceability/...` |
| `career/service.py` | Intégration : création automatique à l'import d'offre (SK-02), liaison automatique au matching (SK-21), effacement à la remise à zéro, journalisation des échecs de synchronisation |
| `career_static/js/traceability.js` | Module d'interface : filtres, tri, historique par exigence, actions de lot, export |
| `career_static/index.html` | Onglet « Traçabilité » + vue `view-traceability` |
| `career_static/career.js` | Enregistrement de la vue (`careerViews`, `labelForView`, `refreshView`) |
| `career_static/career.css` | Styles de la vue (lignes, faits, timeline, actions de lot) |
| `tests/test_traceability.py` | 68 tests : règles métier, persistance, audit, API HTTP, intégration Career, garde-fous d'interface |
| `tests/test_traceability_adversarial.py` | **30 tests adversariaux** : les 10 garanties corrigées en §8 |

La base du registre est **séparée** : `career_data/traceability.sqlite3`.
Elle ne dépend pas du schéma `career.sqlite3` (aucune migration, aucun
`SCHEMA_VERSION` touché), reste hors Git (`.gitignore` → `career_data/`) et
n'est créée qu'à la première utilisation.

## 2. Contrat livré

### `RequirementTrace` (entité centrale)

Champs du contrat : `trace_id`, `requirement_id`, `requirement_text`, `source`,
`category`, `criticality`, `evidence_id`, `evidence_quote`, `status`,
`created_at`, `updated_at`, `history`, `tags`.

Champs ajoutés (audit et intégration, sans modifier le contrat) :
`offer_id`, `cv_id`, `locator`, `source_field`, `confidence` (provenance SK-02),
`link_origin` (`manual` / `auto`), `review_state`
(`not_required` / `pending` / `confirmed` / `rejected`), `match_kind`,
`deleted` + `deleted_at` (suppression logique : la piste d'audit reste
lisible), `superseded_at` + `superseded_by` (exigence retirée de son offre).

### `TraceEvent` (historique)

`event_id`, `timestamp`, `event_type`, `old_value`, `new_value`, `actor`
(`system` / `user` / `worker`), `comment`.

Types du contrat : `created`, `linked`, `unlinked`, `status_changed`,
`category_changed`, `criticality_changed`, `waived`, `reopened`.
Extensions additives (documentées dans le module) : `tags_changed`,
`deleted`, `link_confirmed`, `link_rejected`, `requirement_changed`,
`superseded`, `restored` — elles servent la règle « toute modification est
tracée », l'objectif « traquer les suppressions », la validation manuelle des
liaisons automatiques et le suivi des modifications de l'exigence elle-même.

### Vocabulaire

`category` : `skill`, `experience`, `education`, `language`, `tool`,
`certification`, `soft_skill`, `other`.
`criticality` : `mandatory`, `preferred`, `nice_to_have`, `contextual`.
`status` : `uncovered`, `covered`, `partial`, `contradicted`, `waived`.

### Déterminisme

- `trace_id` = `trace_` + UUID **version 5** dérivé de `(source, requirement_id)` :
  réimporter la même exigence retombe sur la même trace (import idempotent,
  jamais de doublon d'événement). Cette identité est **vérifiée** à l'import :
  un identifiant forgé est refusé.
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
| 4. Immuabilité de l'historique | `TraceEvent` est *frozen* ; les événements ne sont jamais modifiés ni supprimés (`INSERT OR IGNORE` sur `event_id`) ; le texte de l'exigence n'est jamais réécrit silencieusement (un changement de texte laisse un événement `requirement_changed`). |
| 5. Cohérence « covered = preuve + citation + lien validé » | `set_status("covered")` est refusé sans `evidence_id` **et** `evidence_quote`, et refusé tant que le lien est `pending` ; une liaison automatique ne peut pas déclarer une couverture ; une liaison manuelle sans citation ne couvre pas ; remplacer une preuve citée par une preuve sans citation fait retomber le statut orphelin sur `uncovered` (événement `status_changed` tracé). |
| 6. Audit trail | Chaque mutation écrit un événement daté avec `actor` et `comment` ; la suppression est logique (`deleted`) et laisse l'historique. |

Garde-fous supplémentaires :

- les passages `injection_suspect` de SK-02 **ne deviennent jamais** des
  exigences (une offre est une donnée, pas une instruction) ;
- une dérogation (`waived`) exige une justification écrite, lisible dans
  l'historique et dans le rapport « waived » ; retirer une preuve n'annule
  pas une dérogation ;
- un registre vide donne 0 %, jamais 100 % ;
- une exigence que son offre ne demande plus est **supersédée** : elle sort
  du dénominateur de couverture et n'est plus comptée comme gap (une analyse
  SK-02 *tronquée* ne supersède jamais rien) ;
- le rapport d'audit expose les incohérences au lieu de les réparer
  (`covered_without_proof`, `partial_without_proof`, `covered_without_review`) ;
- un changement refusé (statut, catégorie, liaison) **ne laisse aucun état
  divergent** : la mémoire et la base restent identiques ;
- un échec de synchronisation du registre n'annule jamais un import d'offre,
  mais il est **journalisé** (`traceability_requirements_sync_failed`) au lieu
  d'être silencieusement avalé.

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
| `POST` | `/requirements/{trace_id}/link-evidence` | Lier une preuve (citée) |
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
| `GET` | `/audit/superseded` | Exigences que leur offre ne demande plus |
| `GET` | `/audit/history` | Historique global filtré (trace, type, acteur, période) |
| `GET` | `/audit/evolution` | Courbe de couverture reconstruite par rejeu de l'historique |
| `GET` | `/audit/report` | Rapport d'audit complet + incohérences |
| `GET` | `/export?export_format=json\|csv` | Export complet |
| `POST` | `/import` | Import d'un export (idempotent, historique fusionné) |

## 5. Rapports d'audit

| Rapport demandé | Fonction |
| --- | --- |
| Couverture par offre | `coverage_by_offer` (total, évalué, couvert, partiel, non couvert, contredit, dérogé, remplacé, taux global et obligatoire) |
| Couverture par CV | `coverage_by_cv` |
| Gaps critiques | `critical_gaps` (obligatoires non couvertes, `partial` et `contradicted` inclus ; les exigences remplacées n'en sont pas) |
| Historique des changements | `history_timeline` (filtres trace / type / acteur / période) |
| Exigences levées | `waived_requirements` (justification et date de la dérogation) |
| Exigences remplacées | `superseded_requirements` |
| Évolution dans le temps | `coverage_over_time` (rejeu chronologique des événements, dénominateur limité aux exigences déjà créées) |
| Vue d'ensemble | `coverage_summary` (par statut, catégorie, criticité, revues en attente) |
| Cohérence | `audit_report` → `inconsistencies` |

Définitions explicites (pour que les chiffres soient discutables) : une
exigence `waived` **ou** supersédée est exclue du dénominateur de
couverture ; le taux est `covered / (total - waived - superseded)`, arrondi à
quatre décimales, et vaut `0.0` quand il n'y a rien à évaluer.

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
- **exigences remplacées** : signalées dans la liste et dans le détail ;
- **export** : liens JSON et CSV vers l'API locale.

Règle d'honnêteté appliquée dans l'interface : le module ne déclare jamais un
statut lui-même (`status: "covered"` n'apparaît pas dans le code JS), il
affiche celui renvoyé par l'API ; une liaison automatique en attente est
explicitement signalée « à valider ».

## 7. Preuves réelles

- Tests ciblés : `98 passed` (`tests/test_traceability.py` 68 +
  `tests/test_traceability_adversarial.py` 30).
- Suite complète : `1522 passed, 1 skipped` (le skip est préexistant :
  `tests/test_offer_summary_exhaustiveness.py` — script ou base absents).
- `ruff check .` : `All checks passed!`.
- `git diff --check` : propre.
- `node --check career_static/js/traceability.js` : OK.
- Routes vérifiées : 23 opérations sous `/api/career/traceability` (+ les 23
  alias `/traceability/...`), aucun doublon de méthode.
- `./checklist_codex.sh` : voir §9.

## 8. Campagne adversariale (10 défauts réels corrigés)

La livraison précédente était complète fonctionnellement mais **n'avait pas
été attaquée**. La présente campagne a cherché, à chaque couche, un chemin
par lequel le registre pouvait **mentir** — sur un chiffre, sur un statut, ou
sur l'état conservé. Chaque défaut ci-dessous a été **reproduit** avant
correction, puis corrigé **dans le module** (jamais dans les attentes des
tests) et verrouillé par un test dédié.

| # | Défaut reproduit | Effet du défaut | Correctif | Test |
| --- | --- | --- | --- | --- |
| 1 | La courbe de couverture comptait **toutes** les exigences, même celles créées plus tard | Le taux d'un point ancient était dégradé par des exigences qui n'existaient pas encore | `coverage_over_time` ne compte que les exigences déjà créées (`states` démarré vide) | `test_the_coverage_curve_only_counts_the_requirements_that_existed` |
| 2 | Une liaison automatique sur une exigence couverte la laissait **`covered`** | Une exigence était couverte par une preuve que personne n'avait validée (le rapport d'audit le signalait, le registre l'autorisait) | Une proposition automatique retire la couverture (`uncovered`) et l'historique trace le changement | `test_an_automatic_link_never_keeps_a_coverage` |
| 3 | `link_evidence(origin="auto", status="covered")` **passait** | Une machine déclarait une couverture — contraire aux règles métier n° 2 et 3 | Refus explicite, **avant** toute mutation | `test_an_automatic_link_cannot_claim_a_coverage` |
| 4 | `set_status("covered")` sur une liaison `pending` **passait** | Idem, par un autre chemin | `set_status` refuse « covered » tant que le lien est en attente | `test_a_pending_link_cannot_be_declared_covered_by_hand` |
| 5 | Un `PATCH` refusé laissait la catégorie et les tags modifiés **en mémoire seulement** | L'API affichait un état que la base ne contenait pas ; le changement disparaissait au redémarrage | Mise à jour **atomique** : instantané / restauration en cas de refus | `test_a_refused_update_leaves_memory_and_disk_identical` |
| 6 | `confirm_link` sur une liaison sans citation échouait **après** mutation | Le statut de validation était changé sans être persisté | Contrôle de la citation **avant** mutation | `test_confirming_a_link_without_a_quote_is_refused_before_any_mutation` |
| 7 | Un import pouvait **forger** l'identité d'une trace | Deux traces pour une même exigence : double comptage, double gap | L'import vérifie `trace_id == requirement_trace_id(source, requirement_id)` et refuse le reste (`invalid`) | `test_an_import_cannot_forge_the_identity_of_a_requirement` |
| 8 | La fusion d'import comparait les horodatages **en chaîne** | `…:17.123456+00:00` était jugé *antérieur* à `…:17+00:00` : la mauvaise version gagnait | Comparaison par **instant** (`_timestamp_key`) | `test_the_import_orders_two_versions_by_instant_not_by_string` |
| 9 | La fusion d'import ne copiait que 6 champs | L'état de validation d'une version plus récente revenait à `not_required` : une liaison confirmée redevenait « à valider » | La fusion copie **l'état complet** de la version la plus récente | `test_an_import_restores_the_review_state_of_a_newer_version` |
| 10 | Le résumé d'une liaison automatique annonçait `skipped = nombre de preuves` et ne renvoyait pas `pending` | Les compteurs du résumé ne voulaient rien dire | Compteurs exacts (`considered`, `skipped`, `pending_count`, `evidence_count`) | `test_the_auto_link_summary_counts_what_it_says` |

Deux défauts de conception ont en outre été corrigés au-delà des
réproductions strictes :

- **une exigence retirée de son offre devenait un gap éternel** : elle est
  maintenant *supersédée* (`superseded_at`), elle sort du dénominateur de
  couverture et n'est plus comptée comme gap — mais une analyse SK-02
  **tronquée** ne supersède jamais rien, et seule l'intégration SK-02 (analyse
  complète) le fait ;
- **une exigence supprimée puis retrouvée dans sa source disparaissait du
  registre** : elle revient avec un événement `restored` explicite.

Enfin, l'API a été durcie sur deux points :

- un échec de synchronisation du registre est **journalisé** dans
  `career_audit_log` (`traceability_requirements_sync_failed`,
  `traceability_evidence_sync_failed`) au lieu d'être avalé en silence ;
- les refus sont vérifiés **avant** mutation dans `link_evidence` et
  `unlink_evidence` (une liaison refusée ne retire plus la preuve
  existante).

## 9. Checklist de validation

`./checklist_codex.sh` exécuté dans le worktree avec le venv du dépôt principal
(`VENV_PY` / lien `.venv` local, non versionné) :

| Étape | Résultat |
| --- | --- |
| 1. Tests main | ✅ suite complète verte (1522 passed, 1 skipped — le skip est préexistant) |
| 2-4. Worktrees mémoire / profil | ⚠️ absents dans ce worktree (étapes ignorées, préexistant) |
| 5. Aucun secret tracké | ✅ aucun fichier sensible ajouté |
| 6. Mémoire injectée dans le chat | ⚠️ non concerné par SPEC-011 (rappel affiché) |
| 7. DevKit | ✅ 207 passed |
| 8. Study Coach | ⚠️ worktree absent (ignoré) |
| 9. Empreinte DevKit | ⚠️ rapports absents (étape ignorée) |
| 10. Lint ruff | ✅ All checks passed |
| 11. Interdits | ✅ rappel affiché |

Verdict : **TOUT VERT** (les étapes ignorées le sont pour des worktrees
absents, sans rapport avec SPEC-011).

## 10. Limites honnêtes

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
- La supersession dépend de l'extraktion SK-02 : elle ne vaut que pour une
  analyse **complète**. Si l'extraction elle-même change (nouveau
  extracteur), des exigences peuvent être supersédées à tort — l'événement
  `superseded` reste dans l'historique, la correction est possible.
- La suppression est logique : la trace reste dans l'export et dans
  l'historique. Seule la remise à zéro des données personnelles efface
  réellement le registre.
- Aucune vérification navigateur réelle n'a été faite (hors périmètre de la
  mission) : les garde-fous d'interface sont des tests statiques et un test
  Node du tri déterministe.
- La base `career_data/traceability.sqlite3` n'est pas incluse dans
  `career/privacy-export` (qui exporte le périmètre `career.sqlite3`) ; elle
  reste néanmoins effacée par la remise à zéro des données Career.
- La campagne adversariale porte sur le registre lui-même : elle ne dit rien
  de la qualité de l'extraction SK-02 ni de celle du matching SK-21, qui
  restent des modules d'autres branches.

## 11. Rollback

Modifications additives sur une branche dédiée :
`git revert` du commit, ou suppression des fichiers listés au §1. Aucune
migration de base existante, aucun changement de schéma `career.sqlite3`,
aucune modification d'un consommateur de l'interface Career au-delà de
l'ajout d'un onglet (réversible en retirant l'onglet, la vue et l'appel du
module).
