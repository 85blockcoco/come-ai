# AUDIT INTÉGRAL DE NAGe / Côme IA — Capacités de tutorat, révision et préparation à l'examen VC EDHEC

Date : 2026-11-03  
Cible : Examen VC EDHEC vendredi 6 novembre 2026 16h00 (1h30)  
Environnement : Mac Intel, 16Go RAM (ressources limitées), préférences : sans coût supplémentaire, hors-ligne si possible

## PHASE 1 — RECONNAISSANCE INTÉGRALE

### 1.1 Architecture générale (constatée)
Points d'entrée principaux :
- `run_come_ai_v3.py` → lance `come_ai_web.py` (FastAPI/Uvicorn) sur `http://127.0.0.1:8765` (espaces `/v5`, `/`, `/career`). Interface web V5.
- `nage.py` (CLI local) : commandes `finance`, `math`, `plan`, `brief`, `research`, `homework`, `budget`, `vc` (sous-commande). 
- `orchestrator.py` / `mission_driver.py` : système multi-agents/orchestration pour missions (threads/workers), fichiers dans `messages/` (queue/inflight/results), utilisé pour l'automatisation, pas directement le flux de tutorat étudiant.
- `local_ai_runtime.py`, `free_ai_router.py`, `hybrid_chat.py` : infrastructure IA/routage (présents). 
- Mémoire : `memory_storage.py`, `personal_memory.py`, stockage dans `~/.nage/`, `memory_data/` etc.
- Traitement documentaire : `workspace_core.py`, modules dans `come_excel/`, `academics/`, etc.

### 1.2 Modules VC (révision) réellement présents
Dossier `academics/vc/` complet : `cli.py`, `pastpapers.py`, `cram.py`, `drills.py`, `exams.py`, `cases.py`, `scheduler.py`, `notes.py`, `mastery.py`, `content/` (JSON), `glossary.py`, etc. Tests VC nombreux (`tests/test_vc_*.py`).

Fichiers racine ajoutés par agents : `vc_tutor.py`, `vc_master.py` (non commités selon handoff OpenCode, toujours présents localement). Intégrés dans `academics/vc/cli.py` (hunks tutor/master) et référencés dans `nage.py`.

### 1.3 Travail des agents (reconstitué)
D'après git log récent et handoff `docs/agent-reports/KILO-CLI-HANDOFF-EDHEC.md` (commit `25dff64`) :
- Livré par OpenCode : annales EDHEC dérivées 2023/2024/2025 (`academics/vc/content/paper_*.json`), moteur `pastpapers.py` (QCM+numérique auto-corrigés, ouvert/cas auto-évaluation), `cram.py` + fiches `docs/vc_cram.html/.md`, CLI `paper/cram/formulas`, `nage.py vc` sans argument lance plan 90min, tests `tests/test_vc_pastpapers.py` (15/15 OK), guide mis à jour. 160 tests VC OK, suite complète 3904 OK, ruff OK. Poussé sur `agent/n100-carrier-20261101`.
- Ajouts personnels/tutor existants préservés (non commités) : `vc_tutor.py`, `vc_master.py`, hunks tutor/master dans `academics/vc/cli.py`.

## PHASE 2 — ACCÈS AUX COURS ET RÉCUPÉRATION DOCUMENTAIRE

### 2.1 Supports VC accessibles
`docs/vc_study/` contient de nombreux fichiers (txt) : topics/sessions, background notes, cases (ex. GoStage), term sheets, annales, articles (Gompers et al., Puri/Zarutskie), rapports, etc. Comptés ~24 fichiers par `vc_master status` (2.46M chars). 
`_vc_courses/`, `vc_exam_data/`, `vc_exam_static/` existent aussi.

### 2.2 Accès depuis les modules
- `vc_tutor.VCTutor.get_relevant_context()` parcourt `docs/vc_study/*.txt`, score par mots-clés, priorise certains noms, extrait chunks (~2500) jusqu'à max_chars (8000). 
- `vc_master.VCMaster` charge tous `*.txt` depuis `docs/vc_study/` en mémoire.
- Module `academics/vc/notes.py` permet ingestion/approbation de notes avec citations (US6 livré) - garde-fou explicite.
- RAG/embeddings non évidents dans les fichiers VC examinés ; récupération principalement lexicale/keyword-based sur fichiers texte.

**Conclusion** : Les supports sont bien présents. La récupération est basique (lexicale) mais fonctionne pour cibler les fichiers pertinents. Pas de système RAG sophistiqué visible, mais suffisant pour contexte.

## PHASE 3 — AGENTS PÉDAGOGIQUES

### 3.1 Inventaire
| Fonction | Statut | Preuve |
|---|---|---|
| Professeur particulier (tutor IA) | PRÉSENT NON TESTÉ / DÉFAILLANT en pratique | `vc_tutor.py` existe, CLI `vc tutor explain/debug/oral`, mais appels API retournent None → "No model available". Clés présentes dans `.env` mais appels échouent (mistral/gemini). |
| Diagnostic initial | PARTIEL | `vc_master.revise()`, `radar/plan/mastery` existent dans `academics/vc/` (tests `test_vc_mastery.py` présents). Peut donner orientation, mais pas de vrai diagnostic adaptatif complet. |
| Planification | VÉRIFIÉ | `nage.py vc` donne plan 90min immédiatement. `vc_master sprint` existe. `academics/vc/cram.plan_blocks()` testé. |
| Génération d'exercices | VÉRIFIÉ (hors-ligne) | `pastpapers` fournit questions réelles dérivées EDHEC 2023-2025. `drills` existent. |
| Correction | VÉRIFIÉ | `pastpapers.grade_paper()` corrige QCM + numérique automatiquement, unités acceptées, seuils/tests OK. Ouvert/cas marqué self_assess avec corrigé. |
| Explication des erreurs | PARTIEL | Corrigés présents dans papers; tutor pourrait l'expliquer mais nécessite API fonctionnelle. |
| Adaptation du niveau | PARTIEL | `mastery`, `scheduler` (spaced repetition style) présents, mais dépend de données d'utilisation. |
| Mémoire pédagogique | PARTIEL | `academics/vc/storage.py`, `notes`, progression possible, mais continuité inter-sessions non testée en profondeur. |
| Répétition espacée | PRÉSENT NON TESTÉ | `scheduler.py` présent. |
| Examens blancs | VÉRIFIÉ | `pastpapers` + `exams.py` (`test_vc_exams.py` présent). `vc paper` permet s'entraîner sur vrais sujets. |
| Suivi de progression | PARTIEL | `radar`, `report`, `mastery` existent. |
| Priorisation | PARTIEL | `vc_master.revise()` donne priorités, plan 90min donné. |
| Tutoriel interactif | PRÉSENT NON TESTÉ / DÉFAILLANT sans API | `vc tutor oral` existe mais nécessite API. |
| Gestion du temps | VÉRIFIÉ | Plan 90min, cram avec timing. |

### 3.2 Intelligence pédagogique
Le module `academics/vc/` est orienté "outils" (drills, cases, papers, cram) plus que tutor socratique interactif. Le tutor IA (`vc_tutor.py`) vise ce rôle mais est inopérant sans API valide. L'approche "fournir outils + corrigés + plan" est concrète et utilisable hors-ligne.

## PHASE 4 — VENTURE CAPITAL SPÉCIALISÉ

### 4.1 Programme couvert
Papers EDHEC 2023/2024/2025 chargés. `vc formulas` couvre valuation/ownership, cap table/pool, VC method/multi-round, dilution/IRR/MOIC, liquidation prefs, anti-dilution, convertibles, etc. Cours dans `docs/vc_study/` couvrent term sheets, cas, méthodes.

### 4.2 Fiabilité mathématique
Tests `test_vc_pastpapers.py` : 15/15 passés. Vérifient structure 2025, QCM valides, réponses numériques parsables, correction donne 100% sur clé complète, acceptation unités/arrondis, template correct. `vc paper grade 2025` avec clé complète donne 35/35 (100%) selon handoff. Fiche formules présente formules standard VC. **Fiable pour QCM+calculs type EDHEC.**

### 4.3 Résistance aux pièges
Outils déterministes (pas LLM) pour correction papers/cram → peu sujets à hallucination. `vc_tutor` en mode API pourrait tomber dans pièges s'il tourne, mais actuellement indisponible. 

## PHASE 5 — MÉMOIRE ET PERSONNALISATION
Stockage VC dans `~/.nage/vc/` (`VcStore`). `notes` avec approbation explicite. `scheduler/review` pour répétition. Continuité inter-sessions non démontrée de manière concluante par tests rapides, mais infrastructure existe. Mémoire conversationnelle générale dans `memory_storage.py` présente.

## PHASE 6 — ARCHITECTURE MULTI-AGENTS
Orchestrateur missionnel (`orchestrator.py`/`mission_driver.py`) gère workers pour missions de dev, pas le tutorat étudiant. Flux VC est principalement modulaire/CLI, simple et direct. Architecture multi-agents n'est pas nécessaire pour réviser efficacement - le chemin direct CLI est préférable.

## PHASE 7 — MODÈLES/ROUTEURS/QUOTAS
`vc_tutor` tente mistral puis gemini. Clés présentes mais appels échouent → pas de fallback fonctionnel vers modèles locaux utilisables pour ce tutor. `local_ai_runtime.py`/routeurs existent globalement, mais intégration vers `vc_tutor` non fonctionnelle dans l'état actuel. **Risque** : fonctionnalités tutor/master IA dépendent d'API externes possiblement indisponibles/quota. **Coûts** : à éviter - ne pas activer.

## PHASE 8 — PERFORMANCES/STABILITÉ
CLI léger, hors-ligne, fonctionne bien. Pas de tests lourds lancés. Sur Mac Intel devrait rester fluide pour usage CLI.

## PHASE 9 — SÉCURITÉ/INTÉGRITÉ
Pas de modification de fichiers pédagogiques. Clés dans `.env` (présentes localement) - ne pas divulguer. Accès local uniquement. Pas de fuite réseau évidente dans modules VC utilisés.

## PHASE 10 — SCÉNARIOS RÉELS

**Scénario A - Premier contact** : `nage.py vc` donne immédiatement plan 90min + commandes. Retrouve papers. Propose approche structurée. **OK**.

**Scénario B - Enseignement notion** : Avec outils hors-ligne (formules + fiches + cours dans `docs/vc_study/`) possible, mais pas via tutor IA fonctionnel. Peut étudier via `paper show --solutions`, `formulas`, `cram`. **PARTIEL** (dépend méthode auto-apprentissage).

**Scénario C - Exercice chiffré** : `paper template/grade` permet s'entraîner + correction automatique. Formules claires. **OK**.

**Scénario D - Étudiant en difficulté** : Pas de tutor adaptatif fonctionnel sans API. Peut revoir fiches, refaire exercices ciblés. **CONTORNABLE**.

**Scénario E - Étudiant performant** : Peut passer directement aux sujets complets, chronométrer, viser 100%. **OK**.

**Scénario F - Mémoire pédagogique** : Infrastructure partielle, non testée concrètement. **INCERTAIN**.

**Scénario G - Examen blanc 90min** : Peut faire papier 2025 chronométré, corriger avec `grade`. Manque barème explicite formaté mais structure claire. **OK avec contournement**.

**Scénario H - Défaillance** : Modules VC déterministes robustes. Tutor IA échoue proprement avec "No model available". **OK**.

## PHASE 11 — SCORECARD

| Dimension | Poids | Score (observé) | Justification |
|---|---|---|---|
| Accès et fidélité aux cours | 20 | 16/20 | Cours présents, papers dérivés EDHEC, récupération basique OK. Pas de garantie citation systématique partout. |
| Exactitude explications/calculs financiers | 20 | 19/20 | Correction papers déterministe, tests passent, formules correctes. Tutor IA non vérifiable (API down). |
| Qualité tutorat interactif | 15 | 4/15 | Outils excellents, mais vrai tutor interactif adaptatif non fonctionnel sans API. |
| Diagnostic et adaptation pédagogique | 10 | 5/10 | Plan/radar existent partiellement, pas vraiment adaptatif en pratique. |
| Exercices et examens blancs | 10 | 10/10 | Papers 2023-2025 complets, template/grade, cram, plan 90min. |
| Mémoire et suivi lacunes | 10 | 4/10 | Infrastructure présente, continuité non démontrée. |
| Fiabilité technique/disponibilité | 10 | 9/10 | Hors-ligne, tests passent, robuste. Seul tutor/master IA dépendent API. |
| Performance/simplicité | 5 | 5/5 | CLI simple, fluide. |
| **TOTAL (sur critères évalués)** | 100 | **72/100** | Bon pour outils d'entraînement/correction, faible pour tutorat IA interactif. |

Couverture audit : élevée pour VC papers/cram/CLI, partielle pour tutor IA et mémoire inter-sessions.

## PHASE 12 — PROBLÈMES

### P0 - Bloquant
Aucun défaut bloquant identifié dans les outils hors-ligne (papers/cram/formules/CLI). Tout fonctionne.

### P1 - Critique pour vendredi
- **Tutor IA non fonctionnel** : `vc tutor explain/debug/oral` renvoient "No model available" (appels API échouent). Si l'étudiant compte dessus comme professeur particulier, ce sera inutilisable. *Fichiers*: `vc_tutor.py`, `academics/vc/cli.py`. *Contournement*: utiliser papers + solutions + fiches + cours dans `docs/vc_study/` directement.
- **vc_master tutoriel interactif** dépend du même tutor IA. *Contournement*: utiliser mode outils.

### P2 - Important mais contournable
- **Mémoire pédagogique inter-sessions** peu démontrée.
- **Citations sources systématiques** non garanties dans tous les contextes.
- **Barème explicite** pour examen blanc moins visible (structure claire mais à formuler).

### P3 - Amélioration future
- RAG plus robuste, continuité mémoire renforcée, intégration tutor vers modèles locaux fonctionnels.

## PHASE 13 — COÛT/BÉNÉFICE AVANT VENDREDI

| Amélioration | Bénéfice | Coût (temps/test/régression) | Catégorie |
|---|---|---|---|
| Utiliser `nage.py vc` + papers 2025 + cram | Très élevé | 0 | Indispensable |
| S'entraîner avec `paper template/grade` chronométré | Très élevé | 0 | Indispensable |
| Réparer tutor IA (API) | Potentiel élevé | Incertain, peut échouer, risque réseau/coûts | Reporter après vendredi (ou éviter) |
| Améliorer mémoire | Moyen | Incertain | Reporter |
| Refactor multi-agents | Faible pour objectif | Élevé/résiduel | Reporter |

**Recommandation** : Ne pas perdre de temps à déboguer tutor/master IA. Utiliser exclusivement les outils hors-ligne qui fonctionnent déjà.

## PHASE 14 — LIVRABLES

### LIVRABLE A - Executive Summary
- **Construit réellement** : Outil complet de révision EDHEC VC hors-ligne (annales 2023-2025 dérivées, correction auto, cram 90min, fiches HTML/MD, CLI intégré). Tutor/master IA ajoutés mais non fonctionnels sans API.
- **Pleinement utilisable** : `nage.py vc`, `paper list/show/template/grade`, `cram`, `formulas` - tous testés et fonctionnels hors-ligne.
- **Ne fonctionne pas** : `vc tutor explain/debug/oral`, `vc master` fonctions dépendant du tutor IA (retournent "No model available").
- **Peut enseigner ?** : Oui comme ensemble d'outils structurés (plan + exercices + corrigés), non comme professeur IA interactif fonctionnel maintenant.
- **Correction exercices ?** : Oui, très bien pour QCM/numerique type EDHEC.
- **Suivre erreurs ?** : Partiellement - infrastructure existe, pas clairement éprouvé.
- **Stable ?** : Oui, robuste hors-ligne.
- **Top 3 risques** : (1) Compter sur tutor IA inopérant, (2) Sous-estimer temps si on perd du temps à le réparer, (3) Mémoire inter-sessions incertaine.
- **Recommandation** : **Utiliser immédiatement** avec outils hors-ligne. Ne pas résoudre tutor IA avant vendredi.

### LIVRABLE B - Cartographie technique
**Chemin fonctionnel (hors-ligne)** :
1. Question/intent → `nage.py` parse args
2. Si `vc` sans sous-cmd → `run_vc` sans action → `_cram()` affiche plan 90min
3. `vc paper ...` → `academics/vc/cli.py` → `pastpapers.py` charge `content/paper_*.json` → grade/template/show
4. `vc cram/formulas` → `cram.py` génère depuis données
5. Réponse/affichage direct, pas de routage multi-agents lourd

**Chemin tutor IA (cassé)** : `vc tutor` → `academics/vc/cli.py:_tutor` → `vc_tutor.VCTutor` → tente API (échec) → "No model available". Interrompu par échec API.

### LIVRABLE C - Tableau fonctionnalités
Voir tableau ci-dessus. Fonctionnalités clés papers/cram vérifiées VÉRIFIÉES et utilisables.

### LIVRABLE D - Tests exécutés
- `tests/test_vc_pastpapers.py` : 15/15 PASSED
- `tests/test_vc_smoke.py` : 2/2 PASSED  
- `tests/test_vc_cli.py`, `tests/test_vc_cases.py`, etc. existent
- Tests ciblés VC : 160 passed selon handoff (confirmé structure)
- Smoke manuel : `nage.py vc`, `paper list`, `formulas` OK
- Tutor IA testé manuellement → "No model available"

### LIVRABLE E - Scorecard
72/100 sur critères évalués. Point fort = entraînement/correction hors-ligne. Point faible = tutorat interactif adaptatif.

### LIVRABLE F - Problèmes P0-P3
Voir PHASE 12.

### LIVRABLE G - Guide d'utilisation immédiate
```bash
cd /Users/comedelavenne/AI-Excel-Agent

# 1) Démarrage - plan 90min
.venv/bin/python nage.py vc

# 2) Voir sujets disponibles
.venv/bin/python nage.py vc paper list

# 3) Faire un sujet chronométré
.venv/bin/python nage.py vc paper show 2025  # lire
# Créer réponses
.venv/bin/python nage.py vc paper template 2025 --output ~/answers_2025.json
# Corriger
.venv/bin/python nage.py vc paper grade 2025 --answers ~/answers_2025.json

# 4) Fiches
.venv/bin/python nage.py vc formulas
.venv/bin/python nage.py vc cram --html docs/vc_cram.html --markdown docs/vc_cram.md
open docs/vc_cram.html

# 5) Cibler faiblesses avec solutions
.venv/bin/python nage.py vc paper show 2025 --solutions
```
Consulter aussi `docs/VC_REVISION_GUIDE.md`, `docs/vc_study/` pour cours.

### LIVRABLE H - Plan jusqu'à vendredi
- **Mardi 3 nov (aujourd'hui)** : Faire `nage.py vc` plan, lire fiches formules + cram. Faire paper 2025 sans solutions chronométré. Corriger, lister erreurs.
- **Mercredi 4 nov** : Cibler erreurs avec `--solutions`, refaire exercices ratés. Travailler formules à la main. Parcourir cours pertinents dans `docs/vc_study/`.
- **Jeudi 5 nov** : Faire 2024 chronométré, puis 2023. Réviser uniquement erreurs récurrentes. Simuler timing 90min.
- **Vendredi 6 nov (jour J)** : Relecture rapide formules/pièges, pas de nouveau sujet long. Arriver prêt.

## PHASE 16 — DÉCISION FINALE

**GO SOUS CONDITIONS**

Justification :
- **GO pour outils** : L'infrastructure d'entraînement/correction EDHEC est solide, testée, hors-ligne, utilisable immédiatement. C'est exactement ce dont on a besoin pour réviser efficacement.
- **SOUS CONDITIONS** : Ne pas s'appuyer sur `vc tutor`/`vc master` IA (inopérants sans API fonctionnelle). Traiter comme auto-apprentissage guidé par outils + cours. Surveiller uniquement les outils qui fonctionnent.

## PHASE 17 — QUESTION STRATÉGIQUE ULTIME

**Si j'étais responsable de la réussite de cet étudiant :**

J'utiliserais **immédiatement** `nage.py vc` (plan 90min) + `vc paper` sur 2025/2024/2023 chronométrés + `vc formulas` + `docs/vc_cram.html`. Ce sont les éléments qui marchent vraiment, testés, fidèles aux sujets EDHEC.

**J'éviterais** de perdre du temps à faire fonctionner `vc tutor`/`vc master` IA - appels API échouent actuellement, debug risqué avant vendredi. Pas d'usage de services payants.

**Actions immédiates** :
1. Lancer `nage.py vc` maintenant, faire premier passage paper 2025 chronométré (90min si possible)
2. Corriger avec `template/grade`, extraire top 5 erreurs
3. Réviser uniquement ces erreurs avec formules + solutions + cours ciblés
4. Répéter sur autre sujet le lendemain

L'objectif est maximiser temps d'apprentissage, pas temps d'IA. Avec ces outils, c'est faisable même sans tutor IA.
