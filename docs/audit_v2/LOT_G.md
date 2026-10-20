# LOT G — Intégration

Base : worktree jetable `/tmp/audit_5ef814e` sur `5ef814e`. `HOME=/tmp/audit_home`.

## G.1 Branches feature/*, integration/*, test/*

Pour chaque branche : commits uniques vs `5ef814e` (`git cherry`), fichiers touchés (`git diff --name-only`), tests présents, conflits prévus (`git merge-tree`), verdict.

Table complète (45 branches) :

| Branche | Commits uniques | Fichiers touchés | Tests | Conflit prévu | Verdict |
|---|---:|---:|---:|---|---|
| feature/career-international-criteria | 11 | 105 | 28 | NO | integrer (sans conflit, tests presents) |
| feature/career-international-dossiers | 12 | 112 | 29 | NO | integrer (sans conflit, tests presents) |
| feature/career-international-dossiers-oc | 14 | 110 | 29 | NO | integrer (sans conflit, tests presents) |
| feature/career-international-sources | 12 | 113 | 27 | NO | integrer (sans conflit, tests presents) |
| feature/career-source-catalog | 8 | 55 | 4 | NO | integrer (sans conflit, tests presents) |
| feature/career-sources-overnight | 5 | 45 | 2 | NO | integrer (sans conflit, tests presents) |
| feature/career-stage-hunter | 4 | 13 | 1 | NO | integrer (sans conflit, tests presents) |
| feature/come-ai-v6 | 10 | 24 | 9 | NO | integrer (sans conflit, tests presents) |
| feature/come-today-connecteurs | 17 | 53 | 16 | NO | integrer (sans conflit, tests presents) |
| feature/evals-qualite | 1 | 19 | 1 | NO | integrer (sans conflit, tests presents) |
| feature/excel-advanced-v6 | 5 | 39 | 14 | NO | integrer (sans conflit, tests presents) |
| feature/moteur-format-fiabilisation | 1 | 3 | 1 | NO | integrer (sans conflit, tests presents) |
| feature/nemotron-memory | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/noveria-career-integration | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/opencode-data | 4 | 21 | 8 | NO | integrer (sans conflit, tests presents) |
| feature/personal-context-engine | 2 | 28 | 9 | NO | integrer (sans conflit, tests presents) |
| feature/profile-integration-v1 | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/step5-intelligence-centrale | 5 | 9 | 4 | NO | integrer (sans conflit, tests presents) |
| feature/study-coach-v1 | 6 | 25 | 7 | NO | integrer (sans conflit, tests presents) |
| feature/v1-night-consent | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/v1-night-launcher | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/v1-night-profile | 18 | 114 | 34 | NO | integrer (sans conflit, tests presents) |
| feature/v1-night-today-gmx | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/v1-night-ui | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/v1-study-1014 | 19 | 119 | 34 | NO | integrer (sans conflit, tests presents) |
| feature/v3-consent-guard | 3 | 94 | 29 | NO | integrer (sans conflit, tests presents) |
| feature/v3-gmx-readonly | 1 | 23 | 8 | NO | integrer (sans conflit, tests presents) |
| feature/v3-study-validation | 3 | 76 | 22 | NO | integrer (sans conflit, tests presents) |
| feature/workspace-control-center | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/career-explorer | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/career-international-core | 68 | 272 | 87 | NO | integrer (sans conflit, tests presents) |
| integration/career-stage-hunter | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/come-ai-v3-candidate | 10 | 101 | 27 | NO | integrer (sans conflit, tests presents) |
| integration/come-ai-v3-release-candidate | 68 | 272 | 87 | NO | integrer (sans conflit, tests presents) |
| integration/consolidated | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/evals-qualite | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/lot1-mimo | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/profile-core | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/profile-study | 2 | 74 | 21 | NO | integrer (sans conflit, tests presents) |
| integration/step5-chat | 0 | 9 | 4 | NO | integrer (sans conflit, tests presents) |
| integration/step5-facts | 0 | 9 | 4 | NO | integrer (sans conflit, tests presents) |
| integration/study-web | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/v1-assembly-1014 | 21 | 120 | 34 | NO | integrer (sans conflit, tests presents) |
| test/rc-consent-adversarial | 18 | 115 | 34 | NO | integrer (sans conflit, tests presents) |
| test/rc-study-citations-adversarial | 19 | 117 | 34 | NO | integrer (sans conflit, tests presents) |


Verdicts synthétisés :
- `integrer` : sans conflit et avec tests.
- `attendre` : conflit ou absence de tests.
- `ignorer` : branche déjà contenue dans `5ef814e` (0 fichier touché).

## G.2 Fonctions de même nom définies dans plusieurs fichiers (AST)

Script : `/tmp/audit_G_ast.py` (sortie `raw/audit_G_ast_out.txt`). Fonctions top-level présentes dans ≥2 fichiers : **22**.

Liste : `_coerce_enum` (free_ai_router, task_queue, usage_ledger) ; `_component`, `_contains`, `_language_names` (career/scoring, career/stage_search) ; `_fold` (free_ai_router, hybrid_chat, v5_orchestrator) ; `_format_timestamp` (memory_storage, usage_ledger) ; `_integer` (devkit/evolution_store, devkit/model_catalog) ; `_now` (devkit/evolution_store, devkit/patching) ; `_prompt` (career/interview, devkit/evolution_providers) ; `_safe_report` (devkit/evolution, devkit/exporting) ; `_safe_text` (career/profile_import, devkit/evolution_store, hybrid_chat) ; `_string_list` (career/stage_search, evals/checks) ; `_timestamp` (devkit/model_catalog, usage_ledger) ; `_tokens` (career/application_prep, hybrid_chat) ; `_utc_now` (task_queue, usage_ledger) ; `add_csv` (tests) ; `ask_agent`, `inspect_excel` (agent, agent_v2) ; `main` (devkit/*, evals/*, run_come_ai_v3) ; `project` (tests) ; `redact_text` (devkit/exporting, task_queue, usage_ledger) ; `source_fingerprint` (devkit/diagnostics, devkit/exporting).

## G.3 Modules jamais importés depuis les points d'entrée

Les 29 modules listés en lot E (E1-2) ne sont pas atteints depuis `come_ai_web.py` :
`agent`, `agent_v2`, `app_v3`, `career.application_prep`, `career.application_studio`, `career.calendar_export`, `career.discovery`, `career.document_export`, `career.exploration`, `career.intake`, `career.interview`, `career.models`, `career.ocr`, `career.scoring`, `career.source_registry`, `career.sources`, `career.stage_search`, `devkit.__main__`, `devkit.credentials`, `devkit.local_benchmark`, `devkit.offline_smoke`, `evals.__main__`, `evals.checks`, `evals.come_ai_target`, `evals.report`, `evals.runner`, `evals.schema`, `local_ai_runtime`, `run_come_ai_v3`.

## G.4 Incohérences trouvées

1. 15 branches sont déjà contenues dans `5ef814e` (0 fichier touché) mais existent encore comme branches locales — nettoyage recommandé (cf. HANDOFF_AGENT_CODEX).
2. Aucun conflit prévu par `git merge-tree` sur les 45 branches, mais le merge-tree ne détecte pas les conflits sémantiques.
3. 22 noms de fonctions sont définis dans plusieurs fichiers ; risque de confusion lors de l'intégration.
4. Les branches `integration/career-international-core` et `integration/come-ai-v3-release-candidate` sont identiques (68 commits, 272 fichiers, 87 tests) — duplication à clarifier.

## G.5 Ce que je n'ai pas pu déterminer

- Tests réellement exécutés sur chaque branche (seule la présence de fichiers de tests a été vérifiée).
- Conflits sémantiques au-delà du merge-tree textuel.
- État des branches distantes (seules les branches locales ont été inspectées).

Fichiers bruts : `docs/audit_v2/raw/audit_G_branches.tsv`, `raw/audit_G_ast_out.txt`.
LOT_G.md : ce fichier.
EOF
table=$(cat /tmp/audit_G_table.md)
python3 - "$table" <<'PY'
import sys
p='docs/audit_v2/LOT_G.md'
s=open(p).read()
table=sys.argv[1]
s=s.replace('| Branche | Commits uniques | Fichiers touchés | Tests | Conflit prévu | Verdict |
|---|---:|---:|---:|---|---|
| feature/career-international-criteria | 11 | 105 | 28 | NO | integrer (sans conflit, tests presents) |
| feature/career-international-dossiers | 12 | 112 | 29 | NO | integrer (sans conflit, tests presents) |
| feature/career-international-dossiers-oc | 14 | 110 | 29 | NO | integrer (sans conflit, tests presents) |
| feature/career-international-sources | 12 | 113 | 27 | NO | integrer (sans conflit, tests presents) |
| feature/career-source-catalog | 8 | 55 | 4 | NO | integrer (sans conflit, tests presents) |
| feature/career-sources-overnight | 5 | 45 | 2 | NO | integrer (sans conflit, tests presents) |
| feature/career-stage-hunter | 4 | 13 | 1 | NO | integrer (sans conflit, tests presents) |
| feature/come-ai-v6 | 10 | 24 | 9 | NO | integrer (sans conflit, tests presents) |
| feature/come-today-connecteurs | 17 | 53 | 16 | NO | integrer (sans conflit, tests presents) |
| feature/evals-qualite | 1 | 19 | 1 | NO | integrer (sans conflit, tests presents) |
| feature/excel-advanced-v6 | 5 | 39 | 14 | NO | integrer (sans conflit, tests presents) |
| feature/moteur-format-fiabilisation | 1 | 3 | 1 | NO | integrer (sans conflit, tests presents) |
| feature/nemotron-memory | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/noveria-career-integration | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/opencode-data | 4 | 21 | 8 | NO | integrer (sans conflit, tests presents) |
| feature/personal-context-engine | 2 | 28 | 9 | NO | integrer (sans conflit, tests presents) |
| feature/profile-integration-v1 | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/step5-intelligence-centrale | 5 | 9 | 4 | NO | integrer (sans conflit, tests presents) |
| feature/study-coach-v1 | 6 | 25 | 7 | NO | integrer (sans conflit, tests presents) |
| feature/v1-night-consent | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/v1-night-launcher | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/v1-night-profile | 18 | 114 | 34 | NO | integrer (sans conflit, tests presents) |
| feature/v1-night-today-gmx | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/v1-night-ui | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| feature/v1-study-1014 | 19 | 119 | 34 | NO | integrer (sans conflit, tests presents) |
| feature/v3-consent-guard | 3 | 94 | 29 | NO | integrer (sans conflit, tests presents) |
| feature/v3-gmx-readonly | 1 | 23 | 8 | NO | integrer (sans conflit, tests presents) |
| feature/v3-study-validation | 3 | 76 | 22 | NO | integrer (sans conflit, tests presents) |
| feature/workspace-control-center | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/career-explorer | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/career-international-core | 68 | 272 | 87 | NO | integrer (sans conflit, tests presents) |
| integration/career-stage-hunter | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/come-ai-v3-candidate | 10 | 101 | 27 | NO | integrer (sans conflit, tests presents) |
| integration/come-ai-v3-release-candidate | 68 | 272 | 87 | NO | integrer (sans conflit, tests presents) |
| integration/consolidated | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/evals-qualite | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/lot1-mimo | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/profile-core | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/profile-study | 2 | 74 | 21 | NO | integrer (sans conflit, tests presents) |
| integration/step5-chat | 0 | 9 | 4 | NO | integrer (sans conflit, tests presents) |
| integration/step5-facts | 0 | 9 | 4 | NO | integrer (sans conflit, tests presents) |
| integration/study-web | 0 | 0 | 0 | NO | ignorer (deja dans 5ef814e) |
| integration/v1-assembly-1014 | 21 | 120 | 34 | NO | integrer (sans conflit, tests presents) |
| test/rc-consent-adversarial | 18 | 115 | 34 | NO | integrer (sans conflit, tests presents) |
| test/rc-study-citations-adversarial | 19 | 117 | 34 | NO | integrer (sans conflit, tests presents) |
', table)
open(p,'w').write(s)
print("ok")
PY
sed -i '' 's#~#~#g' docs/audit_v2/LOT_G.md
cp /tmp/audit_G_branches.tsv docs/audit_v2/raw/audit_G_branches.tsv
cp /tmp/audit_G_ast_out.txt docs/audit_v2/raw/audit_G_ast_out.txt
sed -i '' 's#~#~#g; s#/tmp/audit_5ef814e#WORKTREE#g' docs/audit_v2/raw/audit_G_branches.tsv docs/audit_v2/raw/audit_G_ast_out.txt
wc -c docs/audit_v2/LOT_G.md