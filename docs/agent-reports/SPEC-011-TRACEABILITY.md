# SPEC-011 — Registre de traçabilité des exigences (CVBOOST-46)

Statut : TERMINÉE (testé sur fixtures synthétiques ; aucune donnée réelle ; aucun réseau ; aucun envoi).

## 1. Ce qui a été construit

| Fichier | Rôle |
| --- | --- |
| `career/traceability.py` | Cœur : `RequirementTrace`, `TraceEvent`, `TraceabilityRegistry` (CRUD, historique immuable, règles de cohérence) + adaptateurs SK-02 / SK-10 / SK-21 |
| `career/traceability_store.py` | Persistance locale : fichier JSON, écriture atomique, indexation/requêtes, export JSON/CSV, import |
| `career/traceability_audit.py` | Rapports d'audit : couverture par offre, couverture par CV, gaps critiques, renonciations, timeline, courbe de couverture |
| `career/router.py` | Endpoints CRUD / audit / export (montés dans `create_career_router`, donc dans l'application) |
| `career_static/js/traceability.js` | UI du registre : filtres, tri, historique par exigence, actions individuelles et groupées |
| `career_static/index.html` | Onglet « Traçabilité » + vue registre + panneau d'audit |
| `career_static/career.js` | Routing de la nouvelle vue (hash + titre d'onglet) |
| `tests/test_traceability.py` | 33 tests (cœur, persistance, audit, intégrations, API HTTP) |

## 2. Contrat livré

### Entités

`RequirementTrace` : `trace_id`, `requirement_id`, `requirement_text`, `source`, `category`,
`criticality`, `evidence_id`, `evidence_quote`, `status`, `created_at`, `updated_at`,
`history`, `tags`.

`TraceEvent` : `event_id`, `timestamp`, `event_type`, `old_value`, `new_value`, `actor`, `comment`.

Vocabulaire : `category` ∈ skill · experience · education · language · tool · certification ·
soft_skill · other ; `criticality` ∈ mandatory · preferred · nice_to_have · contextual ;
`status` ∈ uncovered · covered · partial · contradicted · waived ;
`event_type` ∈ created · linked · unlinked · status_changed · category_changed ·
criticality_changed · waived · reopened (+ deux extensions documentées : `deleted` pour la
suppression archivée et `tags_changed` pour un changement de tags — le vocabulaire du
contrat n'est jamais réinterprété) ;
`actor` ∈ system · user · worker.

### Règles métier appliquées

1. **Création auto (SK-02)** — `traces_from_offer_analysis()` /
   `TraceabilityRegistry.sync_offer_analysis()` traduisent la sortie de
   `career.offer_requirements.analyze_offer()` en traçabilités. La synchronisation est
   **idempotente** : réanalyser la même offre met à jour les traces existantes au lieu de
   les dupliquer (clé = `requirement_id` + `source`).
2. **Liaison auto (SK-21)** — `link_matching_actions()` convertit les codes d'action en
   statuts : `HIGHLIGHT` → covered, `QUANTIFY`/`REPHRASE`/`CONFIRM_LANGUAGE` → partial,
   `DO_NOT_ADD` → uncovered. Une action **sans citation ne couvre jamais** une exigence.
3. **Validation manuelle** — l'utilisateur lie, retire, renonce ou reclassifie depuis l'UI ou
   l'API ; chaque action porte `actor`, `timestamp` et `comment`.
4. **Immuabilité** — l'historique est *append-only* : `TraceEvent` est `frozen`, chaque
   modification remplace la liste par une nouvelle liste, aucun événement écrit n'est
   réécrit. La suppression archive la trace (`deleted`) : la piste d'audit survit.
5. **Cohérence** — `status="covered"` **exige** `evidence_id` **et** `evidence_quote`
   (création, mise à jour et liaison). Retirer une preuve fait retomber l'exigence à
   `uncovered` : le registre ne laisse jamais une exigence couverte sans preuve. Lier une
   preuve **sans citation** ne couvre rien : le statut reste ce qu'il était.
6. **Audit trail** — chaque mutation produit un événement ; les rapports se reconstruisent
   par relecture de l'historique, sans horloge ni supposition.

### API HTTP

Chaque route est exposée deux fois : sous le préfixe historique `/api/career/traceability/…`
et sous les chemins du contrat SPEC-011 `/traceability/…`.

| Méthode | Route | Rôle |
| --- | --- | --- |
| POST | `/traceability/requirements` | Créer une traçabilité (201) |
| GET | `/traceability/requirements` | Liste filtrée (status, category, criticality, source, offer_id, cv_id, tag, q, include_deleted) |
| GET | `/traceability/requirements/{trace_id}` | Détail + historique + justification |
| PATCH | `/traceability/requirements/{trace_id}` | Modifier statut, preuve, tags, catégorie, criticité |
| POST | `/traceability/requirements/{trace_id}/link-evidence` | Lier une preuve |
| POST | `/traceability/requirements/{trace_id}/unlink-evidence` | Délier une preuve |
| POST | `/traceability/requirements/{trace_id}/waive` | Renoncer (justification obligatoire) |
| POST | `/traceability/requirements/{trace_id}/reopen` | Rouvrir une exigence renoncée |
| DELETE | `/traceability/requirements/{trace_id}` | Archiver (l'historique reste) |
| GET | `/traceability/audit/coverage` | Couverture par offre / par CV + courbe dans le temps |
| GET | `/traceability/audit/gaps` | Exigences mandatory non couvertes |
| GET | `/traceability/audit/history` | Historique global filtré (trace, type, acteur, source, since, until) |
| GET | `/traceability/audit/waived` | Exigences renoncées + justifications |
| GET | `/traceability/export?export_format=json\|csv` | Export complet |
| POST | `/traceability/sync-offer` | Création automatique depuis l'analyse SK-02 d'une offre |
| POST | `/traceability/import` | Import d'un export JSON (`replace` ou `merge`) |

Erreurs métier → `400` avec `detail` lisible (aucune traceback exposée) ; le registre
refuse une catégorie, une criticité, un statut ou un acteur hors vocabulaire.

### Rapports d'audit

| Rapport | Contenu |
| --- | --- |
| Couverture par offre | total / assessed / covered / partial / uncovered / contradicted / waived, `covered_pct`, `effective_pct` (une exigence partielle compte pour moitié), répartition par catégorie et criticité |
| Couverture par CV | mêmes compteurs, limités aux exigences rattachées à un CV (`cv_<id>`) |
| Gaps critiques | exigences `mandatory` non couvertes (ni `covered`, ni `waived`) |
| Historique | timeline filtrable, chaque ligne porte l'exigence, l'acteur, l'ancien et le nouveau valeur |
| Renonciations | liste des exigences `waived` avec leur justification |
| Évolution | courbe de couverture reconstruite par relecture des événements |

Définition retenue : `covered_pct = covered / (total − waived)`. Une exigence renoncée ne
gonfle ni la couverture ni le reste à faire ; `effective_pct = (covered + 0,5 × partial) / assessed`.

## 3. Persistance

Fichier local : `<career_data>/traceability/registry.json` (surchargeable par la variable
d'environnement `CAREER_TRACEABILITY_PATH`). Format versionné (`schema_version: 1`), écriture
**atomique** (fichier temporaire + `os.replace`), relecture stricte : un fichier corrompu
lève une erreur explicite au lieu de faire croire à un registre vide — une piste d'audit ne
s'efface pas dans le silence. L'export JSON est ré-importable tel quel ; l'export CSV est
séparé par des points-virgules (Excel FR).

## 4. UI

Onglet « Traçabilité » de l'espace Career :

- filtres (statut, catégorie, criticité, offre, CV, tag, recherche plein texte) et tri
  (dernière mise à jour / criticité / statut) ;
- fiche par exigence : texte, source, catégorie, criticité, statut, preuve, tags ;
- panneau de détail avec l'historique complet (type d'événement, horodatage, acteur,
  commentaire, ancienne → nouvelle valeur) ;
- actions individuelles : lier une preuve, retirer la preuve, renoncer (justification
  obligatoire) ;
- actions groupées sur la sélection : changement de statut, renonciation ;
- panneau d'audit : métriques, couverture par offre, gaps obligatoires, renonciations ;
- export JSON / CSV.

Aucun appel sortant, aucune candidature envoyée : l'onglet ne fait que lire et écrire le
registre local.

## 5. Preuves

Worktree : `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-46-1792666436`,
branche `worker/cvboost-46-1792666436`, base `f5b22f2`.

- Tests ciblés : `33 passed` (`tests/test_traceability.py`).
- Suite complète : `1457 passed, 1 skipped` en 293 s (1 skipped = script optionnel absent,
  `tests/test_offer_summary_exhaustiveness.py`) — aucune régression.
- `checklist_codex.sh main` : `TOUT VERT` (HEAD `86a6f88`, refait vert sur `71d14c1`).
- `checklist_codex.sh secrets` : `TOUT VERT` ; `checklist_codex.sh lint` : `All checks passed!`.
- `ruff check career/ tests/test_traceability.py` : `All checks passed!`.
- `git diff --check` : propre (working tree et index).
- `node --check career_static/js/traceability.js` : syntaxe JS valide.
- `checklist_codex.sh` lancé avec `VENV_PY` pointant sur le venv principal (le worktree
  n'embarque pas de `.venv`).

Commits : `86a6f88` (fonctionnel) puis `71d14c1` (correction « une mise à jour combinée
ne perd plus les changements voisins »), poussés sur
`origin/worker/cvboost-46-1792666436`.

## 6. Limites assumées

- **SK-10 et SK-21 ne sont pas encore dans cette base.** Les adaptateurs acceptent donc des
  dicts ou des objets duck-typés (`id`/`fact_id`/`evidence_id`, `quote`/`text`, `code`,
  `evidence{quote, field, offset}`) et fonctionnent dès que les modules existent ; ils ne
  lèvent jamais si l'intégration n'est pas branchée. Le branchement définitif se fera
  quand `career/candidate_profile.py` (SK-10) et `career/cv_quality/matching.py` (SK-21)
  seront intégrés : il suffira d'appeler `link_evidence_item()` et
  `link_matching_actions()` sur les résultats réels.
- **Le registre ne modifie pas le service Career.** La persistance est isolée dans son
  propre fichier JSON plutôt que dans la base SQLite du service ( migrations v1→v8 ) : le
  registre traverse ainsi les migrations sans risque et reste exportable/importable.
- Le `source` d'une exigence est une étiquette libre (`offer_<id>`, `cv_<id>`, `manual`) ;
  les filtres `offer_id` / `cv_id` en découlent par découpage, jamais par similarité.
- Une exigence supprimée est archivée, pas effacée : elle sort des listes par défaut
  (`include_deleted=true` pour la retrouver) et reste dans l'export d'audit.
