# Préparation — évaluation du risque de merge CVBOOST-10 V2

| Élément | État |
|---|---|
| Type | Préparation initiale ; complétée par le verdict final dans `CODEX_VERDICT.md` |
| Sources lues | `CODEX_RECETTE_E2E.md`, `docs/agent-reports/CVBOOST-10-INTEGRATION-V2.md`, critères de tests de `PROMPT_CODEX_CVBOOST-10-V2.md` |
| `RESULTAT_TESTS_FINAL.md` | Absent du worktree à la vérification ; non consulté |
| Smoke-test | Non exécuté |
| Code produit | Non modifié |

## Trois points déterminants à réévaluer au signal

| Rang | Point | Éléments chiffrés disponibles | Conséquence pour la décision finale |
|---:|---|---|---|
| 1 | Complétude des merges et provenance des 12 lots | État final vérifié : `44, 45, 46, 47, 48, 49, 50, 52, 53, 54, 55, 58` tous présents en merges `--no-ff`, source et SHA merge consignés dans le rapport d’intégration. Le commit retenu pour le lot 52 est `286418f`; le candidat contenant `messages/result.json` n’a pas été retenu. | Complétude des lots acquise. L’historique confirme 12 merges; aucun élément de `messages/` n’a été ajouté par ces commits selon l’arbitrage documenté. |
| 2 | Échecs de tests ciblés déjà documentés | Lots en échec : 21 (`1060 pass, 172 fail`), 29 (`88 pass, 61 fail`), 38 (`68 pass, 24 fail`), 40 (`25 pass, 4 fail`), 43 (`143 pass, 4 fail`). Total arithmétique des échecs de ces cinq lignes : **265**. Le rapport donne aussi une sous-suite structurée du lot 21 à `29 pass, 22 fail` ; ce chiffre est présenté séparément et n’est pas ajouté au total. L’échantillon kit/dossier exécuté ici : **50 pass, 0 fail**, ce qui ne couvre ni ces cinq lots ni toute la suite. | Comparer les tests ciblés après réparations avec ces résultats historiques : ils doivent être résolus ou expliqués par des preuves reproductibles. Les 50 tests réussis ne suffisent pas à lever ce risque. |
| 3 | Suite finale et seuil d’acceptation global | Exécution complète actuelle : **5876 pass, 193 fail, 11 skip** sur 6080. Critère source : référence `1454+` tests verts et minimum **≥1450 pass, 0 fail, 0 error**. `CODEX_RECETTE_E2E.md` rapporte un parcours HTTP synthétique réussi 5/5; rendu visuel et erreurs console restent non vérifiés. | Le seuil de suite complète échoue nettement et suffit à refuser le merge. Le parcours HTTP soutient le fonctionnement du kit, mais n’annule pas les 193 tests rouges. |

## Commande de relance préparée et vérifiée sur 50 tests

| Champ | Valeur |
|---|---|
| Sélection | Premiers 50 node IDs collectés dans `tests/test_career_application_kit.py`, `tests/test_application_dossier.py`, `tests/test_application_dossier_integration.py` (84 collectés au total avant sélection) |
| Commande exacte exécutée | `noglob /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q -x -p no:cacheprovider $(/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest --collect-only -q tests/test_career_application_kit.py tests/test_application_dossier.py tests/test_application_dossier_integration.py | sed -n '/^tests\//p' | head -n 50)` |
| Résultat réel | **50 passed in 8.72s** |
| Flags validés | `-q -x -p no:cacheprovider` |
| Interprétation | Vérifie la commande, le chemin Python et un échantillon ciblé de 50 tests sous 10 minutes ; ce résultat n’est ni la suite complète ni un verdict d’intégration. |

## Commande exacte proposée après le signal — suite complète

| Usage | Commande |
|---|---|
| Exécution complète sans arrêt au premier échec, sans cache pytest | `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q -p no:cacheprovider` |
| Lecture des résultats à relever | Nombre réel `passed`, `failed`, `error` (et `skipped` s’il y en a) ; seuil d’acceptation documenté : `≥1450 pass`, `0 fail`, `0 error` |

| Vérification environnement | Résultat |
|---|---|
| `.venv/bin/python` dans le worktree courant | Absent |
| Interpréteur utilisé pour l’échantillon | `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python` (Python 3.12 du dépôt de référence), tests collectés et exécutés depuis le worktree candidat courant |

| Statut de préparation | L’utilisateur a supprimé l’attente du signal; évaluation finale menée sur le worktree courant |

## État Git observé pendant la préparation

| Contrôle | Résultat |
|---|---|
| HEAD observé | `69d8555` — `recette E2E HTTP kit 1-clic: 5/5 vertes (guard profil, déduplication, consent, 6 formats, personnalisation)` |
| Fichiers en conflit d’index | `career/router.py`, `career/service.py` (`UU`) |
| Entrées d’index | `career/router.py`: base `d2218fd`, stage 2 `8ee0b71`, stage 3 `d35bfff`; `career/service.py`: base `b8b76c9`, stage 2 `a59a450`, stage 3 `66f93f2` |
| Métadonnées de séquence | `MERGE_HEAD`, `CHERRY_PICK_HEAD` et `REBASE_HEAD` non présents au moment du contrôle ; les entrées d’index non résolues sont néanmoins présentes |
| Présence dans le worktree | Les deux familles de routes existent dans le contenu de travail : dossier (`/dossier`, `/dossier/export`) et revue CV (`/cv-review`, `/cv-review/decide`, `/cv-review/history`, `/cv-review/export`) ; les méthodes de service `build_application_dossier`, `get_cv_review_workspace` et `export_cv_review` sont présentes. |
| Conséquence | État candidat non propre à ce contrôle. La résolution de ces deux fichiers et la validation de l’index doivent être établies avant d’interpréter une nouvelle suite comme état final. Aucune résolution faite ici. |
