# SPEC-011 — Registre de traçabilité des exigences

**Mission** : CVBOOST-46 — SPEC-011 (P0, module transverse)
**Branche** : `worker/cvboost-46-1792666375` (worktree dédié `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-46-1792666375`)
**Base** : `main` à `f5b22f2` (`merge(career): ATS diagnostics and targeted CV variants pipeline`)
**Date** : 2026-10-22
**Auteur** : Worker Mission CVBOOST-46

---

## 1. Ce qui a été livré

| Fichier | Rôle |
|---|---|
| `career/traceability.py` | Cœur métier pur : `RequirementTrace`, `TraceEvent`, `TraceabilityRegistry`, adaptateurs SK-02 / SK-21, export / import |
| `career/traceability_store.py` | Persistance SQLite : schéma, index, requêtes, journal d'événements en ajout seul |
| `career/traceability_audit.py` | Rapports d'audit : couverture, gaps, écartées, timeline, évolution |
| `career/service.py` | Migration de schéma v8 → v9 + façade service (CRUD, audit, export, import, synchronisation) |
| `career/router.py` | 18 routes CRUD / audit / export / import / synchronisation |
| `career_static/js/traceability.js` | Vue registre : filtres, tri, historique, actions batch |
| `career_static/index.html` | Onglet « Traçabilité », vue, barre d'actions batch, chargement du script |
| `career_static/career.js` | Enregistrement de la vue dans `careerViews`, `labelForView` et `refreshView` |
| `tests/test_traceability.py` | 69 tests (domaine, adaptateurs, audit, store, export/import, service, HTTP, garde-fous JS) |
| `docs/agent-reports/SPEC-011-TRACEABILITY.md` | Ce rapport |

**Aucun fichier existant n'est réécrit** : les offres, le profil, les candidatures et les brouillons du candidat restent inchangés. La migration v9 **ajoute** deux tables.

---

## 2. Le contrat central

### 2.1 `RequirementTrace`

Les noms de champs du contrat de la mission sont repris **verbatim** :

```python
trace_id, requirement_id, requirement_text, source, category, criticality,
evidence_id, evidence_quote, status, created_at, updated_at, history, tags
```

S'y ajoutent les champs de provenance et d'audit nécessaires aux rapports et aux filtres :
`offer_id`, `cv_id`, `source_field`, `locator`, `confidence`, `auto_linked`, `validated`, `waiver_reason`, `deleted`.

`to_dict()` ajoute les libellés français (`status_label`, `category_label`, `criticality_label`) pour que l'UI n'invente jamais sa propre taxonomie.

### 2.2 `TraceEvent`

```python
event_id, timestamp, event_type, old_value, new_value, actor, comment
```

`TraceEvent` est **`frozen`** : un événement écrit ne peut plus être modifié. Corriger une erreur se fait en **ajoutant** un événement, jamais en réécrivant le passé.

Les huit types d'événements de la mission (`created`, `linked`, `unlinked`, `status_changed`, `category_changed`, `criticality_changed`, `waived`, `reopened`) sont présents, plus quatre extensions explicites : `tags_changed`, `requirement_updated`, `deleted`, `validated` (étiquetage de masse, resynchronisation d'une exigence, suppression auditée, validation manuelle d'une liaison automatique).

---

## 3. Les règles métier, et comment elles sont tenues

| Règle de la mission | Implémentation | Preuve |
|---|---|---|
| 1. Création auto à l'extraction (SK-02) | `sync_offer_analysis()` : une trace par exigence extraite, texte **repris tel quel** | `test_the_offer_analysis_creates_one_trace_per_requirement` |
| 2. Liaison auto au matching (SK-21) | `apply_match_result()` : seule une action **avec extrait** lie une preuve ; le lien est marqué `auto` | `test_the_matcher_links_the_excerpt_it_returned`, `test_the_matcher_never_invents_a_proof` |
| 3. Validation manuelle | `validate_link(approved=True/False)` : confirmation ou rejet d'une liaison automatique | `test_an_automatic_link_can_be_confirmed_or_rejected` |
| 4. Immuabilité de l'historique | événements `frozen`, liste d'historique **remplacée** et jamais mutée en place | `test_the_history_is_immutable_and_never_rewritten` |
| 5. Cohérence « covered » | `covered` (et `contradicted`) exigent `evidence_id` **et** `evidence_quote` | `test_a_covered_requirement_always_carries_its_proof`, `test_a_proof_without_a_quote_is_refused` |
| 6. Audit trail | chaque mutation écrit un événement avec acteur, horodatage ISO 8601 et commentaire | toute la suite |

Règles de cohérence supplémentaires, explicites et testées :

- **Une preuve sans citation n'est pas une preuve** : `link_evidence()` refuse une citation vide.
- **`waived` n'est pas un statut qu'on pose paresseusement** : il faut passer par `waive()` avec une justification ; `update(status="waived")` est refusé.
- **Passer à `uncovered` détache la preuve** et l'enregistre (`unlinked` + `status_changed`) : l'état ne peut pas mentir.
- **Une exigence `waived` est réouvrable** ; la réouverture restaure `covered` si la preuve existe, sinon `uncovered`.
- **Une exigence supprimée garde son historique** (suppression logique + événement `deleted`).

---

## 4. Les intégrations Spec Kit

Le socle de cette mission (`main` à `f5b22f2`) contient **SK-02** (`career.offer_requirements`) mais **pas encore SK-10** ni **SK-21** (qui vivent dans d'autres worktrees). Les deux intégrations sont donc écrites comme des **adaptateurs à structure ouverte** (`duck typing`) : ils acceptent un dictionnaire ou un objet à champs, ce qui les rend utilisables aujourd'hui et compatibles avec les classes `EvidenceItem` (SPEC-008) et `MatchResult` (CVBOOST-21) telles qu'elles sont définies.

### 4.1 SK-02 → registre (création automatique)

```python
sync_offer_analysis(registry, analyze_offer(offer))
```

- `category` : `technical_skill→skill`, `language→language`, `education→education`, `experience→experience`, `availability/mobility/work_authorization→other`.
- `criticality` : `required→mandatory`, `preferred→preferred`, `contextual/unknown→contextual`. Un « preferred » portant un marqueur *nice to have* (dans le texte **ou** dans le titre de section) devient `nice_to_have` — un atout n'est **jamais** promu en obligatoire.
- `source_field`, `locator` et `confidence` de SK-02 sont conservés : la trace pointe vers le passage exact d'où elle vient.
- Un `injection_suspect` (une offre est une donnée non fiable, jamais une instruction) **ne devient jamais** une exigence tracée : il est listé dans `skipped`.
- Une seconde synchronisation ne duplique rien (`unchanged`) ; un texte modifié est mis à jour et l'événement `requirement_updated` est écrit.

### 4.2 SK-21 → registre (liaison automatique)

```python
apply_match_result(registry, match_result)
```

- Chaque action du matcher (`requirement_text`, `cv_evidence_text`, `confidence`, `reason`) est rapprochée d'une trace par texte **verbatim** puis normalisé.
- Sans extrait, rien n'est lié : l'action est comptée dans `no_evidence`.
- `confidence ≥ 0.8` → `covered`, sinon `partial`. **Un lien automatique ne rend jamais une exigence « couverte » par lui-même** : il est marqué `auto_linked=True`, `validated=None` et attend une validation humaine.
- Un extrait déjà lié n'est pas re-écrit (`already_linked`) : l'historique ne se double pas.

### 4.3 SK-10 → registre (preuve)

`evidence_reference()` lit l'identifiant et la citation d'un objet ou d'un dictionnaire exposant `id`/`evidence_id` et `quote`/`text` — le format exact de `EvidenceItem` (SPEC-008). L'UI et l'API acceptent les deux formes.

---

## 5. L'API

Les routes sont déclarées **une seule fois** et montées deux fois : sous le préfixe local de l'application (`/api/career/traceability/...`) et sous le chemin du contrat de la mission (`/traceability/...`, hors schéma OpenAPI pour ne pas le dupliquer).

| Méthode | Route | Effet |
|---|---|---|
| POST | `/requirements` | Crée une exigence (201) |
| GET | `/requirements` | Liste filtrée : `status`, `category`, `criticality`, `offer_id`, `cv_id`, `source`, `tag`, `include_deleted` |
| GET | `/requirements/{trace_id}` | Détail + historique complet |
| PATCH | `/requirements/{trace_id}` | Modifie `status`, `category`, `criticality`, `tags`, `comment` |
| POST | `/requirements/{trace_id}/link-evidence` | Lie une preuve (citation exacte obligatoire) |
| POST | `/requirements/{trace_id}/unlink-evidence` | Délie la preuve |
| POST | `/requirements/{trace_id}/waive` | Écarte avec justification obligatoire |
| POST | `/requirements/{trace_id}/reopen` | Rouvre une exigence écartée |
| POST | `/requirements/{trace_id}/validate` | Confirme ou rejette une liaison automatique |
| DELETE | `/requirements/{trace_id}` | Suppression logique, historique conservé |
| POST | `/requirements/link-matches` | Liaison automatique depuis un résultat de matching |
| POST | `/sync/{job_id}` | Synchronise une offre locale (SK-02) |
| GET | `/audit/coverage` | Couverture globale, par offre, par CV |
| GET | `/audit/gaps` | Exigences obligatoires non couvertes |
| GET | `/audit/history` | Timeline par exigence, courbe d'évolution, écartées |
| GET | `/export?export_format=json\|csv` | Export complet (JSON avec historique, CSV état courant) |
| POST | `/import` | Import d'un export (les traces déjà présentes sont conservées) |

**Choix de conception assumé** : les routes de la mission sont `/traceability/...` alors que la convention du dépôt est `/api/career/...`. Les deux sont servies : la convention pour l'application, le contrat pour la relecture.

**Erreurs** : une règle métier violée renvoie une **400** avec un message français lisible (`UserFacingError`), jamais une 500. Exemple réel :

> `Une exigence couverte doit référencer une preuve (evidence_id + evidence_quote). Relie d'abord une preuve, puis change le statut.`

---

## 6. Les rapports d'audit

| Rapport demandé | Livré | Ce qu'il dit (et ce qu'il ne dit pas) |
|---|---|---|
| Couverture par offre | `coverage_by_offer()` | `total`, `covered`, `partial`, `uncovered`, `contradicted`, `waived`, `coverage_rate`, `partial_rate`, `gaps` par offre |
| Couverture par CV | `coverage_by_cv()` | Même décompte, regroupé par `cv_id` |
| Gaps critiques | `critical_gaps()` | Les exigences **obligatoires** non couvertes ; une exigence écartée n'est pas un gap (c'est une décision, elle est reportée dans `waived`) |
| Historique des changements | `status_timeline()` | Tous les événements de statut par exigence, avec acteur et horodatage |
| Exigences écartées | `waived_requirements()` | Liste **avec la justification** |
| Évolution dans le temps | `coverage_evolution()` | Courbe reconstruite par rejeu des événements |

Deux garde-fous de vérité :

- **Une couverture partielle ne gonfle jamais le taux de couverture** : seul `covered` compte comme couvert, `partial` est reporté à part (`partial_rate`).
- **La courbe est reconstruite, pas stockée** : elle rejoue l'audit trail, donc elle est reproductible et ne peut pas diverger de l'historique.

Chaque pourcentage est livré **avec les comptes bruts** qui le produisent : le lecteur peut refaire l'arithmétique.

---

## 7. La persistance

Deux tables, ajoutées par la migration `SCHEMA_VERSION` 8 → 9 (et créées pour une base neuve par un `CREATE TABLE IF NOT EXISTS` idempotent) :

- `requirement_traces` : l'état courant d'une exigence, indexée sur `status`, `category`, `criticality`, `offer_id`, `cv_id`, `updated_at`.
- `trace_events` : le journal **en ajout seul**, indexé sur `(trace_id, timestamp)`, `(event_type, timestamp)`, `(actor, timestamp)`.

Les événements sont insérés avec `INSERT OR IGNORE` sur `event_id` : réécrire le même historique après un redémarrage ne duplique **rien** et ne réécrit **rien**.

La migration ne touche ni aux offres, ni au profil, ni aux candidatures : `test_an_existing_database_is_migrated_without_losing_the_offers` le prouve en simulant une base v8 (tables supprimées, `user_version` remis à 8) puis en rouvrant le service.

---

## 8. L'interface

Nouvelle vue « Traçabilité » (`career_static/js/traceability.js`, ~450 lignes) :

- **Cartes** : exigences tracées, couvertes, couverture partielle, gaps critiques, écartées, taux de couverture.
- **Filtres** : statut, catégorie, criticité, offre, recherche plein texte (exigence, citation, étiquette) ; tri « priorité », « modification récente », « par offre ».
- **Tri « priorité »** : obligatoire non couvert d'abord, covered en dernier.
- **Historique par exigence** : panneau de détail qui rejoue la timeline (acteur, horodatage, commentaire).
- **Actions batch** : écarter (justification obligatoire dans le champ du bandeau), délier les preuves, rouvrir les écartées, vider la sélection. Seules les exigences **éligibles** à l'action sont sélectionnées (`traceabilityBatchTargets`).
- **Import / export** : export CSV en un clic, export JSON via l'API, import d'un export JSON par sélecteur de fichier (la forme du fichier est vérifiée avant l'envoi, les exigences déjà présentes sont conservées et les entrées illisibles sont rapportées, jamais réparées).

Les garde-fous JavaScript s'exécutent dans **Node** sur les vraies fonctions du fichier (comme les autres garde-fous UI du dépôt) : tri, construction de la requête de filtre, sélection batch, comptage de couverture, recherche, et chargement du module sans navigateur.

---

## 9. Validation

| Commande | Résultat |
|---|---|
| `.venv/bin/python -m pytest -q tests/test_traceability.py` | **69 passed** |
| `.venv/bin/python -m pytest -q` | **1494 passed**, 1 skipped (pré-existant : `test_offer_summary_exhaustiveness`) |
| `.venv/bin/python -m ruff check .` | **All checks passed** |
| `git diff --check` | propre |

Le test `tests/test_qualification_snapshot_persistence.py` épinglait `SCHEMA_VERSION == 8` : il a été mis à jour à `9` (la version est une conséquence de la migration v9, pas un objectif de la mission). Le schéma du snapshot de qualification, lui, est inchangé et toujours vérifié colonne par colonne.

Répartition des 69 tests : 20 sur le domaine, 5 sur l'adaptateur SK-02, 6 sur l'adaptateur SK-21, 5 sur les rapports d'audit, 4 sur le store, 5 sur l'export/import, 12 sur le service et l'API HTTP, 12 sur la vue JavaScript.

---

## 10. Limites assumées

1. **SK-10 et SK-21 ne sont pas encore dans cette base.** Les deux intégrations sont donc des adaptateurs à structure ouverte, testés avec des doublures (`_FakeMatchResult`, dictionnaires). Quand `career/cv_quality/matching.py` (CVBOOST-21) et le centre de preuves (SPEC-008) seront fusionnés, les adaptateurs acceptent leurs objets tels quels : `MatchResult.actions` porte déjà `requirement_text` et `cv_evidence_text`, `EvidenceItem` porte déjà `id` et `quote`.
2. **Le sélecteur « lier une preuve » n'existe pas dans l'UI.** Lier suppose de choisir une preuve dans le centre de preuves (SPEC-008) ; proposer un champ libre dans cette vue pourrait laisser croire qu'une citation saisie est une preuve. L'API `link-evidence` est disponible et testée ; l'UI expose l'écart, la validation et la suppression. C'est un choix de vérité, pas un oubli — à lever quand SPEC-008 sera mergé.
3. **Le registre ne crée pas les exigences** : il ne fait que tracer celles que SK-02 a extraites. `sync_offer_analysis()` ne réécrit jamais le texte d'une exigence.
4. **`coverage_evolution()`** produit un point par événement de statut : la courbe est un journal rejoué, pas une agrégation temporelle lissée.
5. Le store ne connaît pas d'index sur `tags_json` (JSON) : le filtre par étiquette passe par un filtrage en mémoire. Le volume local (quelques centaines d'exigences) ne le justifie pas ; un index dedicated le ferait si le volume change.

---

## 11. Pour la relecture

- Le point de départ le plus simple : `career/traceability.py` (règles) → `career/traceability_audit.py` (ce qui est affirmé) → `career/traceability_store.py` (ce qui est stocké).
- La règle la plus discutable du rapport : **une exigence `waived` n'est pas un gap**. Une exigence obligatoire écartée est un écart assumé, pas une couverture manquante ; elle reste visible dans `waived_mandatory_count`.
- La seconde règle discutable : **une liaison automatique ne suffit pas à rendre une exigence couverte**. Elle est liée, marquée automatique, et attend une validation humaine.
