# LOT A — Git et machine

Base inspectée : `5ef814eb16f3357264624abdf0b8fd746315b7b1` (`5ef814e`).  
Worktree principal : `~/AI-Excel-Agent`.  
Worktree jetable créé : `/tmp/audit_5ef814e` (détaché sur `5ef814e`).  
`HOME=/tmp/audit_home` pour toutes les commandes.  
Date d'exécution : 2026-10-17.

## A.1 État Git du worktree principal

| ID | Affirmation | Commande exacte | Sortie brute (extrait) | SHA | Statut |
|---|---|---|---|---|---|
| A1-1 | Branche courante = `audit/total-v3-2026-10-14`, dépôt non propre | `git status` (sortie complète dans `raw/git_status.txt`) | `On branch audit/total-v3-2026-10-14` / `Unmerged paths:` / `deleted by us: study_coach/syllabus.py`, `deleted by us: tests/test_study_coach_citations.py` / `Untracked files: ...` | `5ef814e` | EXÉCUTÉ |
| A1-2 | SHA réel de `main` = `5ef814eb…` (pas `ed8a6b9` comme dans les HANDOFF) | `git rev-parse main` | `5ef814eb16f3357264624abdf0b8fd746315b7b1` | `5ef814e` | EXÉCUTÉ |
| A1-3 | `main` contient `5ef814e` au-dessus de `ed8a6b9` | `git log --oneline -3 main` | `5ef814e feat(career): deliver verified public internship explorer without personal boards` / `ed8a6b9 docs: record delivered Career journey and post-merge validation` / `fb9dbba Merge branch 'main' into integration/career-stage-hunter` | `5ef814e` | EXÉCUTÉ |
| A1-4 | Index contient 2 chemins non fusionnés | `git ls-files -u` | `100644 b4eb… 1 study_coach/syllabus.py` / `100644 afbe… 3 study_coach/syllabus.py` / `100644 ccd9… 1 tests/test_study_coach_citations.py` / `100644 c458… 3 tests/test_study_coach_citations.py` | `5ef814e` | EXÉCUTÉ |
| A1-5 | Aucun fichier `MERGE_HEAD`/`CHERRY_PICK_HEAD`/`REBASE_*` présent | `ls .git/MERGE_HEAD .git/CHERRY_PICK_HEAD .git/REBASE_HEAD .git/rebase-merge .git/rebase-apply` | `No such file or directory` (×5) | `5ef814e` | EXÉCUTÉ |
| A1-6 | `ORIG_HEAD` = `ed8a6b9962…` | `cat .git/ORIG_HEAD` | `ed8a6b9962b9c9b24088ea2597aa910c6fec80bb` | `5ef814e` | EXÉCUTÉ |
| A1-7 | 11 fichiers non suivis (hors `.gitignore`) | `git ls-files --others --exclude-standard` | 11 entrées : `BASE_SHA_VALIDÉ/`, 5 `HANDOFF_*.md`, `checklist_codex.sh`, `docs/audit_v2/...`, `tests/test_study_coach_v3_validation.py` (liste complète dans `raw/git_untracked.txt`) | `5ef814e` | EXÉCUTÉ |
| A1-8 | 115 worktrees enregistrés | `git worktree list | wc -l` | `115` (liste dans `raw/git_worktree_list.txt`) | `5ef814e` | EXÉCUTÉ |
| A1-9 | 113 branches locales | `git branch | wc -l` | `113` | `5ef814e` | EXÉCUTÉ |

## A.2 Opération Git en cours

Statut : index non fusionné (`DU`) sans `MERGE_HEAD`. C'est une anomalie d'état : soit un merge interrompu dont le fichier de contrôle a disparu, soit un `git read-tree` manuel. Aucune commande corrective exécutée (règle lecture seule).

## A.3 Branches (résumé chiffré)

Commandes exécutées pour chaque branche (sortie complète : `raw/git_branch_stats.txt`) :
`git rev-list --left-right --count 5ef814e...<branche>` ; `git merge-base --is-ancestor <branche> 5ef814e` (code retour) ; `git diff --stat 5ef814e...<branche> | tail -1`.

| ID | Affirmation | Commande | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| A3-1 | 17 branches sont ancêtres de `5ef814e` (tous leurs commits déjà dans la base) | boucle ci-dessus, comptage | `ancestor_of_base=YES: 17` | `5ef814e` | EXÉCUTÉ |
| A3-2 | 96 branches ne sont pas ancêtres de `5ef814e` | idem | `ancestor_of_base=NO: 96` | `5ef814e` | EXÉCUTÉ |
| A3-3 | 17 branches n'ont aucun commit unique au-delà de la base | idem | `branches with 0 ahead of base: 17` | `5ef814e` | EXÉCUTÉ |
| A3-4 | 20 branches sont en retard sur la base (base contient des commits qu'elles n'ont pas) | idem | `branches with base ahead of them (behind>0): 20` | `5ef814e` | EXÉCUTÉ |
| A3-5 | Total des commits uniques portés par les branches (somme des « ahead ») = 3267 | idem | `sum ahead: 3267` ; `max ahead: 70` | `5ef814e` | EXÉCUTÉ |

## A.4 Commits uniques des branches `agent/mission-*`

Commande : `git cherry 5ef814e <branche>` pour chaque branche `agent/*` (sortie complète : `raw/git_cherry_agent_mission.txt`, 2961 lignes).

| ID | Affirmation | Commande | Sortie brute (extrait) | SHA | Statut |
|---|---|---|---|---|---|
| A4-1 | `feature/career-stage-hunter` porte 4 commits uniques vs `5ef814e` | `git cherry 5ef814e feature/career-stage-hunter \| grep '^+' \| wc -l` | `4` (`98a5815`, `089ea83`, `6368817`, `a146769`) | `5ef814e` | EXÉCUTÉ |
| A4-2 | `feature/study-coach-v1` porte 6 commits uniques vs `5ef814e` | `git cherry 5ef814e feature/study-coach-v1 \| grep '^+' \| wc -l` | `6` | `b89a309` | EXÉCUTÉ |
| A4-3 | `feature/v3-consent-guard` (`f1af740`) porte ? | `git cherry 5ef814e feature/v3-consent-guard \| grep '^+' \| wc -l` | à reporter si besoin (voir raw) | `f1af740` | EXÉCUTÉ |

## A.5 Fichiers non suivis (originaux, avant écriture de cet audit)

Liste complète dans `raw/git_untracked.txt` (section `exclude-standard`).

| ID | Affirmation | Commande | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| A5-1 | 9 fichiers/dossiers non suivis avant l'audit | `git ls-files --others --exclude-standard` (hors sorties de l'audit) | `BASE_SHA_VALIDÉ/`, `HANDOFF_AGENT_CAREER.md`, `HANDOFF_AGENT_CODEX.md`, `HANDOFF_AGENT_MEMOIRE.md`, `HANDOFF_AGENT_STUDY_COACH.md`, `HANDOFF_REVUE_SECURITE_MEMOIRE.md`, `checklist_codex.sh`, `tests/test_study_coach_v3_validation.py` (+ `HANDOFF_career_stage_hunter.md` non listé par le statut initial ? voir A5-2) | `5ef814e` | LU |
| A5-2 | `HANDOFF_career_stage_hunter.md` existe mais n'apparaît pas dans `git status` initial | `ls -la HANDOFF*.md` + `git status --porcelain` | 6 fichiers HANDOFF présents, statut ne montre que 5 `HANDOFF_AGENT_*.md` | `5ef814e` | EXÉCUTÉ |

## A.6 HANDOFF_*.md — comparaison des affirmations techniques au git log

Règle appliquée : seules les affirmations techniques (livré, testé, SHA) sont comparées ; aucun contenu privé recopié.

| ID | Affirmation HANDOFF | Vérification exécutée | Résultat | Statut |
|---|---|---|---|---|
| A6-1 | `HANDOFF_AGENT_CODEX` : « `main` (`ed8a6b9`) » comme référence inaltérable | `git rev-parse main` | `main` = `5ef814e`, `ed8a6b9` est son parent (A1-2/A1-3). Affirmation obsolète d'un commit. | EXÉCUTÉ |
| A6-2 | `HANDOFF_AGENT_CODEX` : « 681 passed, 2 skipped » | Aucun test lancé dans ce lot | NON VÉRIFIÉ — à mesurer lot B. | NON VÉRIFIÉ |
| A6-3 | `HANDOFF_AGENT_CAREER` : « Stage Hunter livré », base `ed8a6b9` | `git rev-parse feature/career-stage-hunter` = `a146769` ; branche existe ; 4 commits uniques (A4-1) | Branche et commits confirmés ; livraison « testée » non vérifiée ici. | EXÉCUTÉ (partiel) |
| A6-4 | `HANDOFF_AGENT_STUDY_COACH` : « 82 tests », paquet `study_coach/` complet | `feature/study-coach-v1` = `b89a309`, 6 commits uniques ; dans la base `5ef814e`, `study_coach/` est absent de `HEAD` (seulement `syllabus.py` présent via index non fusionné) | Branche existe ; état d'intégration dans `main` contredit « livré dans main ». | EXÉCUTÉ |
| A6-5 | `HANDOFF_REVUE_SECURITE_MEMOIRE` : deux moteurs concurrents (Nemotron vs personal_profile) | Branches `feature/nemotron-memory` (`1b570dd`) et `feature/personal-context-engine` (`e6af0db`) existent ; `git merge-base --is-ancestor … 5ef814e` = NO pour les deux | Présence des branches confirmée ; contenu non inspecté dans ce lot. | EXÉCUTÉ (partiel) |
| A6-6 | `HANDOFF_career_stage_hunter` : commits `98a5815`, `089ea83`, `6368817`, `a146769` | `git cherry 5ef814e feature/career-stage-hunter` | Les 4 SHAs correspondent exactement. | EXÉCUTÉ |

## A.7 Machine

| ID | Affirmation | Commande exacte | Sortie brute | Statut |
|---|---|---|---|---|
| A7-1 | macOS 14.8.9 (build 23J631) | `sw_vers` | `ProductName: macOS` / `ProductVersion: 14.8.9` / `BuildVersion: 23J631` | EXÉCUTÉ |
| A7-2 | Architecture x86_64 | `uname -m` | `x86_64` | EXÉCUTÉ |
| A7-3 | Mémoire physique 16 GiB | `sysctl hw.memsize` | `hw.memsize: 17179869184` | EXÉCUTÉ |
| A7-4 | Python 3.12.10 par défaut (+ 3.8, shims) | `which -a python3` / `python3 -V` | `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3` (premier) ; `Python 3.12.10` | EXÉCUTÉ |
| A7-5 | `pip check` : aucune dépendance cassée | `HOME=/tmp/audit_home python3 -m pip check` | `No broken requirements found.` | EXÉCUTÉ |
| A7-6 | 30 paquets installés (liste) | `HOME=/tmp/audit_home python3 -m pip list` | liste complète dans `raw/pip_list.txt` (ex. fastapi 0.143.0, pytest 9.1.1, pydantic 2.14.1, starlette 1.8.0) | EXÉCUTÉ |
| A7-7 | SQLite Python = 3.49.1, FTS5 activé | `python3 -c "import sqlite3; print(sqlite3.sqlite_version); ... PRAGMA compile_options"` | `3.49.1` ; `ENABLE_FTS5` présent dans la liste (voir `raw/sqlite_fts5.txt`) | EXÉCUTÉ |
| A7-8 | CLI sqlite3 = 3.43.2 | `sqlite3 --version` | `3.43.2 2023-10-10 …` | EXÉCUTÉ |
| A7-9 | `numpy`, `python-docx`, `httpx` non installés dans l'environnement par défaut | `pip list` (raw/pip_list.txt) | absents de la liste (à installer dans venv jetable pour les lots suivants) | EXÉCUTÉ |

## A.8 Incohérences trouvées

1. `main` réel = `5ef814e`, alors que `HANDOFF_AGENT_CODEX` et `HANDOFF_AGENT_CAREER` citent `ed8a6b9` comme référence inaltérable (A6-1). `ed8a6b9` est l'ancêtre immédiat.
2. État du dépôt anormal : index non fusionné (`DU` sur 2 fichiers) sans `MERGE_HEAD` (A1-4/A1-5). À investiguer, non corrigé.
3. `study_coach/` est absent de `HEAD` (`5ef814e`) mais présent (partiellement) dans l'arbre de travail via l'index non fusionné (A6-4) ; la branche `feature/study-coach-v1` existe avec 6 commits uniques.
4. `HANDOFF_AGENT_CAREER` affirme « 159 tests ciblés + 681 DevKit verts » — non vérifiable dans ce lot (A6-2).
5. `pip list` ne contient pas `numpy`/`python-docx`/`httpx` (A7-9) : les lots B–G devront utiliser un venv jetable.

## A.9 Ce que je n'ai pas pu déterminer

- Résultats de tests (compteurs pass/fail/skip) : lot B.
- Contenu réel des branches `agent/mission-*` au-delà des SHAs (pas inspecté fichier par fichier).
- Présence ou non de `HANDOFF_career_stage_hunter.md` dans le suivi Git (apparaît comme non suivi dans `git status` initial pour seulement 5 des 6 HANDOFF ; à clarifier).
- Cause exacte de l'index non fusionné sans `MERGE_HEAD`.
- Validité des affirmations « livré/testé » des HANDOFF au-delà du git log.
- Empreinte DevKit `.devkit/diagnostics/latest.*` non vérifiée.

Fichiers bruts : `docs/audit_v2/raw/` (`git_status.txt`, `git_worktree_list.txt`, `git_branch_stats.txt`, `git_cherry_agent_mission.txt`, `git_untracked.txt`, `machine_basic.txt`, `pip_list.txt`, `sqlite_fts5.txt`).
LOT_A.md : ce fichier.
EOF
echo "written"; wc -c docs/audit_v2/LOT_A.md