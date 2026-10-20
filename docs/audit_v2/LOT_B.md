# LOT B — Tests

Base inspectée : worktree jetable `/tmp/audit_5ef814e` détaché sur `5ef814eb…` (`5ef814e`).  
`HOME=/tmp/audit_home`.  
Venv jetable créé : `/tmp/audit_venv` (`--system-site-packages`) ; paquets autorisés installés : `numpy`, `httpx`, `python-docx`.  
Constat : le venv jetable ne contient pas `pandas`/`openpyxl` (non autorisés à l'installation réseau selon règle 5) ; `workspace_core.py:31` importe `pandas`, ce qui casse la collecte de 24 modules. Pour mesurer la suite réellement, exécution complémentaire avec le venv du dépôt `~/.venv` (lecture seule, `HOME` factice) qui contient `pandas 3.0.6`.  
Date d'exécution : 2026-10-17.

## B.1 Collecte (`pytest --collect-only -q`)

| ID | Affirmation | Commande exacte | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| B1-1 | Venv jetable : 252 tests collectés, 24 erreurs de collecte | `cd WORKTREE && HOME=/tmp/audit_home /tmp/audit_venv/bin/python -m pytest --collect-only -q` | `252 tests collected, 24 errors in 4.27s` puis `252 tests collected, 24 errors in 3.12s` après install httpx | `5ef814e` | EXÉCUTÉ |
| B1-2 | Cause exacte des 24 erreurs : `ModuleNotFoundError: No module named 'pandas'` (21) + `'openpyxl'` (3) via `workspace_core.py:31` | extrait `raw/test_collect_jet_v2.txt` | `workspace_core.py:31: import pandas as pd` → `E ModuleNotFoundError: No module named 'pandas'` | `5ef814e` | EXÉCUTÉ |
| B1-3 | Venv projet : 749 tests collectés, 0 erreur | `cd WORKTREE && HOME=/tmp/audit_home ~/.venv/bin/python -m pytest --collect-only -q` | `749 tests collected in 3.02s` | `5ef814e` | EXÉCUTÉ |
| B1-4 | 37 modules de test | comptage des préfixes dans `raw/test_collect_project_venv.txt` | `TOTAL 749 modules 37` | `5ef814e` | EXÉCUTÉ |

Modules en erreur de collecte (venv jetable) — liste exacte :
`tests/test_calendar_export.py`, `test_career_action_plan.py`, `test_career_agent.py`, `test_career_discovery_selection.py`, `test_career_exploration.py`, `test_career_explorer_regressions.py`, `test_career_explorer_web.py`, `test_career_stage_hunter.py`, `test_career_stage_hunter_ui_guards.py`, `test_come_ai_v3.py`, `test_devkit_integration.py`, `test_evolution.py`, `test_evolution_configuration.py`, `test_evolution_providers.py`, `test_evolution_real_sandbox.py`, `test_evolution_web.py`, `test_hybrid_chat.py`, `test_hybrid_secret_guards.py`, `test_hybrid_web.py`, `test_intelligence_router.py`, `test_personal_memory.py`, `test_v5_orchestrator.py`, `test_v5_web.py`, `evals/tests/test_come_ai_target.py`.

## B.2 Suite complète

| ID | Affirmation | Commande exacte | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| B2-1 | 749 tests passés, 0 échec, 0 erreur, 0 skip | `cd WORKTREE && HOME=/tmp/audit_home ~/.venv/bin/python -m pytest -q --durations=15 -o faulthandler_timeout=120` | `749 passed in 52.88s` | `5ef814e` | EXÉCUTÉ |
| B2-2 | Durée totale 52,88 s ; test le plus lent 3,85 s | idem | `749 passed in 52.88s` + tableau slowest 15 | `5ef814e` | EXÉCUTÉ |

Top 15 durées (extrait `raw/test_full_suite.txt`) :
1. `tests/test_career_exploration.py::test_global_top_150_is_chosen_across_sources_and_exact_aliases_deduped` — 3.85 s
2. `tests/test_career_discovery_selection.py::test_changed_criteria_invalidate_selection_cache_without_losing_tracking` — 3.79 s
3. `tests/test_evolution_real_sandbox.py::test_demo_uses_real_sandbox_and_preserves_immutable_acceptance_tests` — 3.72 s
4. `tests/test_devkit_real_workflow.py::test_real_sandbox_patch_validation_apply_and_rollback` — 1.84 s
5. `tests/test_career_discovery_selection.py::test_service_imports_late_finance_offer_using_saved_brief` — 1.81 s
6. `tests/test_career_stage_hunter_ui_guards.py::test_stage_hunter_search_preserves_actual_discovery_result[http-error]` — 0.63 s
7. `tests/test_career_explorer_web.py::test_zero_personal_boards_http_explore_prepare_track_and_cache` — 0.55 s
8. `tests/test_career_agent.py::test_discovery_routes_use_an_injected_offline_connector_and_keep_exports_private` — 0.49 s
9. `tests/test_career_stage_hunter.py::test_full_http_journey_from_brief_to_offer_received` — 0.48 s
10. `tests/test_hybrid_web.py::test_production_career_ai_uses_common_router_and_refuses_truncation[True]` — 0.47 s
11. `tests/test_evolution_web.py::test_evolution_backlog_settings_persist_and_offline_forces_local_provider` — 0.46 s
12. `tests/test_career_agent.py::test_career_routes_are_local_and_do_not_break_v3` — 0.46 s
13. `tests/test_v5_web.py::test_v5_memory_is_source_cited_and_survives_app_restart` — 0.45 s
14. `tests/test_devkit_diagnostics.py::test_real_bootstrap_collects_application_and_evaluation_tests[folders2]` — 0.42 s
15. `tests/test_task_queue.py::test_errors_messages_and_terminal_state_are_bounded_and_redacted` — 0.42 s

## B.3 Tableau module | collectés | passés | échoués | erreurs | skippés

Tous les modules ci-dessous : échoués = 0, erreurs = 0, skippés = 0 (sortie `749 passed`).

| Module | Collectés | Passés | Échoués | Erreurs | Skippés |
|---|---:|---:|---:|---:|---:|
| evals/tests/test_come_ai_target.py | 19 | 19 | 0 | 0 | 0 |
| evals/tests/test_evals.py | 78 | 78 | 0 | 0 | 0 |
| tests/test_calendar_export.py | 5 | 5 | 0 | 0 | 0 |
| tests/test_career_action_plan.py | 3 | 3 | 0 | 0 | 0 |
| tests/test_career_agent.py | 37 | 37 | 0 | 0 | 0 |
| tests/test_career_discovery_selection.py | 13 | 13 | 0 | 0 | 0 |
| tests/test_career_exploration.py | 43 | 43 | 0 | 0 | 0 |
| tests/test_career_explorer_regressions.py | 21 | 21 | 0 | 0 | 0 |
| tests/test_career_explorer_web.py | 2 | 2 | 0 | 0 | 0 |
| tests/test_career_stage_hunter.py | 52 | 52 | 0 | 0 | 0 |
| tests/test_career_stage_hunter_ui_guards.py | 10 | 10 | 0 | 0 | 0 |
| tests/test_come_ai_v3.py | 14 | 14 | 0 | 0 | 0 |
| tests/test_devkit_diagnostics.py | 13 | 13 | 0 | 0 | 0 |
| tests/test_devkit_exporting.py | 27 | 27 | 0 | 0 | 0 |
| tests/test_devkit_integration.py | 5 | 5 | 0 | 0 | 0 |
| tests/test_devkit_patching.py | 26 | 26 | 0 | 0 | 0 |
| tests/test_devkit_real_workflow.py | 1 | 1 | 0 | 0 | 0 |
| tests/test_evolution.py | 22 | 22 | 0 | 0 | 0 |
| tests/test_evolution_configuration.py | 19 | 19 | 0 | 0 | 0 |
| tests/test_evolution_providers.py | 74 | 74 | 0 | 0 | 0 |
| tests/test_evolution_real_sandbox.py | 1 | 1 | 0 | 0 | 0 |
| tests/test_evolution_store.py | 16 | 16 | 0 | 0 | 0 |
| tests/test_evolution_web.py | 1 | 1 | 0 | 0 | 0 |
| tests/test_free_ai_router.py | 10 | 10 | 0 | 0 | 0 |
| tests/test_hybrid_chat.py | 107 | 107 | 0 | 0 | 0 |
| tests/test_hybrid_secret_guards.py | 5 | 5 | 0 | 0 | 0 |
| tests/test_hybrid_web.py | 19 | 19 | 0 | 0 | 0 |
| tests/test_intelligence_bridge.py | 39 | 39 | 0 | 0 | 0 |
| tests/test_intelligence_router.py | 5 | 5 | 0 | 0 | 0 |
| tests/test_local_runtime.py | 3 | 3 | 0 | 0 | 0 |
| tests/test_memory_storage.py | 7 | 7 | 0 | 0 | 0 |
| tests/test_model_catalog.py | 20 | 20 | 0 | 0 | 0 |
| tests/test_personal_memory.py | 11 | 11 | 0 | 0 | 0 |
| tests/test_task_queue.py | 5 | 5 | 0 | 0 | 0 |
| tests/test_usage_ledger.py | 7 | 7 | 0 | 0 | 0 |
| tests/test_v5_orchestrator.py | 4 | 4 | 0 | 0 | 0 |
| tests/test_v5_web.py | 5 | 5 | 0 | 0 | 0 |
| **TOTAL** | **749** | **749** | **0** | **0** | **0** |

## B.4 `skip` / `xfail` / `importorskip`

| ID | Affirmation | Commande exacte | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| B4-1 | 3 occurrences de `skipif` dans le code de tests | `grep -rn "pytest.mark.skip\|pytest.mark.xfail\|importorskip" tests evals` | `tests/test_evolution_real_sandbox.py:12: @pytest.mark.skipif(sys.platform != "darwin" or os.environ.get("COME_AI_DIAGNOSTICS_OFFLINE") == "1", ...)` / `tests/test_devkit_real_workflow.py:16-17: @pytest.mark.skipif(...)` | `5ef814e` | EXÉCUTÉ |
| B4-2 | Aucun `xfail` ni `importorskip` | idem | aucune ligne supplémentaire | `5ef814e` | EXÉCUTÉ |
| B4-3 | Dans l'exécution complète, aucun test n'a été skippé (749 passed) | sortie B2-1 | `749 passed in 52.88s` (aucun `s`/`x` dans `-ra`) | `5ef814e` | EXÉCUTÉ |

## B.5 Conftest et blocage des sockets

| ID | Affirmation | Commande exacte | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| B5-1 | Aucun fichier `conftest.py` dans le dépôt | `find . -name "conftest*.py"` | aucun résultat | `5ef814e` | EXÉCUTÉ |
| B5-2 | Aucun blocage global de sockets (pytest-socket absent) | `grep -R "pytest_socket\|block_socket\|disable_socket" .` | aucun résultat | `5ef814e` | EXÉCUTÉ |
| B5-3 | Blocage réseau fait manuellement dans 2 modules de tests | `grep -n "socket" tests/test_free_ai_router.py tests/test_evolution_providers.py` | `monkeypatch.setattr(socket, "create_connection", network_forbidden/forbidden)` | `5ef814e` | EXÉCUTÉ |

## B.6 Modèle factice dans les tests de chat, mémoire, study

| ID | Affirmation | Commande / preuve | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| B6-1 | Chat (`test_hybrid_chat.py`, 107 tests) utilise un fournisseur factice (`FakeRouter`), pas de réseau | lecture `tests/test_hybrid_chat.py:27-44` | `class FakeRouter` avec `eligible/refresh/choose_model` synthétiques ; docstring « no real key, provider or personal file » | `5ef814e` | LU |
| B6-2 | Chat web (`test_hybrid_web.py`) utilise un stub inerte | lecture `tests/test_hybrid_web.py:1-32` | « inert provider stub and fictional data » ; `SimpleNamespace(HybridChatService=factory)` | `5ef814e` | LU |
| B6-3 | Mémoire (`test_personal_memory.py`, `test_memory_storage.py`, `test_v5_*`) : aucun modèle/fournisseur construit | lecture docstrings | `test_personal_memory.py`: « nor create a model/provider client or a network call » ; `test_v5_web.py`: « No model/provider is constructed » | `5ef814e` | LU |
| B6-4 | Aucun test « study » dans la base `5ef814e` (study_coach est sur branche séparée) | `ls tests \| grep -i study` | aucun fichier | `5ef814e` | EXÉCUTÉ |

## B.7 Incohérences trouvées

1. `HANDOFF_AGENT_CODEX` affirme « 681 passed, 2 skipped » sur `main` ; mesure réelle à `5ef814e` = **749 passed, 0 skipped** (B2-1). Écart de +68 tests, 0 skip au lieu de 2.
2. `HANDOFF_AGENT_CAREER` affirme « 159 tests ciblés + 681 DevKit verts » ; non vérifié tel quel, mais la suite complète fait 749 (B2-1).
3. `HANDOFF_AGENT_STUDY_COACH` affirme « 82 tests » pour `study_coach/` ; aucune suite study dans la base `5ef814e` (B6-4) — tests présents seulement sur `feature/study-coach-v1` (6 commits uniques, lot A).
4. Le venv jetable imposé ne permet pas de collecter 24 modules faute de `pandas`/`openpyxl` (B1-1/B1-2) ; la mesure complète a nécessité le venv du dépôt. C'est un écart entre l'environnement « jetable » et les dépendances réelles du projet.
5. `pytest.ini` fixe `testpaths = tests evals/tests` et `addopts = -ra` ; aucun timeout par test n'est disponible (pas de `pytest-timeout`) — seul `faulthandler_timeout` (ini) a pu être activé.

## B.8 Ce que je n'ai pas pu déterminer

- Comportement des 24 modules en venv jetable sans `pandas` : non exécutés (collecte échoue). Leur code n'a pas été mesuré dans cet environnement.
- Durée par test individuel au-delà du top 15 (sortie tronquée à 15 par `--durations=15`).
- Couverture de code (aucun outil de coverage invoqué).
- Tests study_coach (absents de la base) : à mesurer sur la branche dédiée.
- Présence d'un timeout par test réel : plugin absent ; non déterminé si des tests peuvent dépasser 120 s (aucun ne l'a fait ici).


## B.9 Vérification indépendante par module

| ID | Affirmation | Commande exacte | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| B9-1 | Rejeu module par module : 37 modules, 0 échec, somme = 749 | `for f in $(find tests evals/tests -name 'test_*.py'); do pytest -q "$f"; done` | `exit=0` pour les 37 ; `total passed sum = 749` (voir `raw/test_B_per_module_verify.txt`) | `5ef814e` | EXÉCUTÉ |


Fichiers bruts : `docs/audit_v2/raw/test_collect_jet_v2.txt`, `test_collect_project_venv.txt`, `test_full_suite.txt`.
LOT_B.md : ce fichier.
EOF
wc -c docs/audit_v2/LOT_B.md