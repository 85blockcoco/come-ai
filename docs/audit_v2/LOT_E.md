# LOT E — Mémoire, Career, Study

Base : worktree jetable `/tmp/audit_5ef814e` sur `5ef814e`. `HOME=/tmp/audit_home`.

## E.1 Graphe d'imports (AST) depuis `come_ai_web.py`

Script : `/tmp/audit_E_graph.py` (sortie `raw/audit_E_graph_out.txt`). Modules locaux considérés : 54 (hors tests).

| ID | Affirmation | Commande / preuve | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| E1-1 | 25 modules atteints depuis `come_ai_web.py` | script AST récursif | `REACHED_COUNT 25` | `5ef814e` | EXÉCUTÉ |
| E1-2 | 29 modules jamais atteints | idem | `UNREACHED_COUNT 29` | `5ef814e` | EXÉCUTÉ |
| E1-3 | `memory_storage` est atteint | liste reached | `memory_storage` présent | `5ef814e` | EXÉCUTÉ |
| E1-4 | `personal_memory` est atteint | liste reached | `personal_memory` présent | `5ef814e` | EXÉCUTÉ |

Modules atteints (25) :
`career.profile_import`, `career.router`, `career.service`, `come_ai_web`, `devkit.diagnostics`, `devkit.evolution`, `devkit.evolution_manager`, `devkit.evolution_providers`, `devkit.evolution_store`, `devkit.exporting`, `devkit.intelligence_router`, `devkit.model_catalog`, `devkit.patching`, `devkit.proposals`, `devkit.router`, `devkit.service`, `free_ai_router`, `hybrid_chat`, `intelligence_bridge`, `memory_storage`, `personal_memory`, `task_queue`, `usage_ledger`, `v5_orchestrator`, `workspace_core`.

Modules jamais atteints (29) :
`agent`, `agent_v2`, `app_v3`, `career.application_prep`, `career.application_studio`, `career.calendar_export`, `career.discovery`, `career.document_export`, `career.exploration`, `career.intake`, `career.interview`, `career.models`, `career.ocr`, `career.scoring`, `career.source_registry`, `career.sources`, `career.stage_search`, `devkit.__main__`, `devkit.credentials`, `devkit.local_benchmark`, `devkit.offline_smoke`, `evals.__main__`, `evals.checks`, `evals.come_ai_target`, `evals.report`, `evals.runner`, `evals.schema`, `local_ai_runtime`, `run_come_ai_v3`.

## E.2 Schéma SQLite (base synthétique)

Création via `PersonalMemoryStore(tmp_path)` (aucune base réelle). `SCHEMA_VERSION = 2` (`personal_memory.py:44`).

Tables et objets (DDL `personal_memory.py:299-346`) :
- `projects` (id PK, name, name_key UNIQUE, description, created_at, updated_at)
- `sources` (id PK, content_hash UNIQUE, title, original_filename, source_kind CHECK, source_type, category, char_count, chunk_count, imported_at, updated_at)
- `source_projects` (source_id FK, project_id FK, linked_at, PK composite)
- `memory_chunks` (id PK, source_id FK, ordinal, page_number, sheet_name, line_start, line_end, content, UNIQUE(source_id,ordinal))
- index : `memory_chunks_source_idx`, `source_projects_project_idx`, `sources_category_idx`
- `memory_chunks_fts` : VIRTUAL TABLE FTS5 (chunk_id UNINDEXED, source_id UNINDEXED, title, content, tokenize unicode61 remove_diacritics 2)

## E.3 Requêtes FTS5 hostiles sur base synthétique

Script : `/tmp/audit_E_fts.py` + `/tmp/audit_E_fts2.py` (sortie `raw/audit_E_fts_out.txt`). Base synthétique créée par `import_text`.

| ID | Requête hostile | Comportement observé | Statut |
|---|---|---|---|
| E3-1 | `"` , `*`, `-`, `()` | `PersonalMemoryError : La recherche doit contenir au moins un mot ou un nombre.` | EXÉCUTÉ |
| E3-2 | `NEAR`, `AND`, `OR`, `AND OR`, `foo*`, `NEAR(a,b)`, `" OR 1=1`, `a AND`, `a OR`, `a - b`, `a *` | acceptées comme mots, 0 résultat (aucune injection d'opérateur) | EXÉCUTÉ |
| E3-3 | `memory NEAR chat` | 0 résultat (traité comme mots littéraux) | EXÉCUTÉ |
| E3-4 | Recherche normale (`chat`, `mémoire`, `memoire`, `FTS5`, `token`, `secret`) | 1 résultat chacune | EXÉCUTÉ |

Mécanisme : `_safe_fts_query` (`personal_memory.py:1201`) extrait les termes via `_QUERY_TERM_RE` (mots), les tronque à 64 chars, max 10 termes, puis les cite et les joint par `AND`. Les opérateurs FTS5 ne peuvent pas être injectés.

## E.4 Career — discovery vs exploration

| ID | Affirmation | Preuve | Statut |
|---|---|---|---|
| E4-1 | `discovery.py` et `exploration.py` sont des modules distincts (pas des doublons) | `diff -u` : 470 lignes vs 158, rôles différents (réseau Greenhouse vs règles d'admission) | EXÉCUTÉ |
| E4-2 | `sources.py` contient deux méthodes `discover` dans deux classes distinctes : `JobSourceConnector` (Protocol) et `ManualJobSource` | `career/sources.py:102` et `:111` | LU |
| E4-3 | Le second ne masque pas le premier (classes différentes, pas de redéfinition globale) | lecture `career/sources.py:98-113` | LU |
| E4-4 | Seul `career/stage_search.py` importe `career.sources` (`SEARCH_TERMS`) | `grep` : 1 fichier | EXÉCUTÉ |

## E.5 Study — contenu réel

| ID | Affirmation | Preuve | Statut |
|---|---|---|---|
| E5-1 | À `5ef814e`, `study_coach/` est absent de `HEAD` et du worktree jetable | `git ls-tree -r HEAD | grep study_coach` → vide ; `find study_coach` → vide | EXÉCUTÉ |
| E5-2 | La branche `feature/study-coach-v1` (`8a26f52`) contient 15 modules + 8 tests | `git ls-tree -r --name-only 8a26f52 | grep study_coach` | EXÉCUTÉ |
| E5-3 | La branche `test/rc-study-citations-adversarial` (`e0ac7fb`) contient la même arborescence | idem pour `e0ac7fb` | EXÉCUTÉ |
| E5-4 | Différences entre `8a26f52` et `e0ac7fb` dans `study_coach/` : seulement `demo.py` et `syllabus.py` | `git diff --name-only 8a26f52 e0ac7fb -- 'study_coach/*'` | EXÉCUTÉ |
| E5-5 | Différences de tests : `test_study_coach_citations.py` et `test_study_coach_v3_validation.py` | idem `tests/test_study_coach*` | EXÉCUTÉ |

## E.6 Incohérences trouvées

1. `memory_storage.py` est importé par `come_ai_web.py` (donc atteint) mais c'est un service de diagnostic disque, pas de stockage de souvenirs ; nom trompeur.
2. `study_coach/` est présenté comme livré dans `HANDOFF_AGENT_STUDY_COACH.md`, mais il est absent de la base `5ef814e` (E5-1) ; il existe seulement sur branche séparée.
3. Le graphe d'imports montre que 29 modules (dont tout Career avancé, Study, evals) ne sont pas atteints depuis le point d'entrée web, donc non chargés en production.
4. `sources.py` contient deux `discover` dans deux classes distinctes ; ce n'est pas un masquage, mais la proximité peut prêter à confusion.

## E.7 Ce que je n'ai pas pu déterminer

- Contenu exact des 29 modules non atteints (pas inspectés fichier par fichier).
- Schéma des bases Career (pas de SQLite dans ce lot ; Career utilise JSON/settings).
- État de la branche `feature/v3-study-validation` (`8a26f52`) au-delà de la liste de fichiers.
- Impact réel de l'absence de `study_coach` sur les tests de la base (aucun test study dans `5ef814e`).

Fichiers bruts : `docs/audit_v2/raw/audit_E_graph_out.txt`, `docs/audit_v2/raw/audit_E_fts_out.txt`.
LOT_E.md : ce fichier.
EOF
cp /tmp/audit_E_graph_out.txt docs/audit_v2/raw/audit_E_graph_out.txt
cp /tmp/audit_E_fts_out.txt docs/audit_v2/raw/audit_E_fts_out.txt
sed -i '' 's#/Users/comedelavenne#~#g; s#/tmp/audit_5ef814e#WORKTREE#g' docs/audit_v2/raw/audit_E_graph_out.txt docs/audit_v2/raw/audit_E_fts_out.txt docs/audit_v2/LOT_E.md
wc -c docs/audit_v2/LOT_E.md