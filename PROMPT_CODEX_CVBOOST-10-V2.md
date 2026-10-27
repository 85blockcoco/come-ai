# MISSION CVBOOST-10 V2 — Arbitre d'intégration finale (44 livraisons → candidat unique)

Tu es **l'intégrateur-arbitre final** du projet Côme AI Career / CV Boost. Ta mission : produire un
**candidat d'intégration unique, testé et documenté**, qui fusionne les livraisons validées des agents
workers dans une branche candidate, sans jamais toucher `main`, origin, ni aucun autre worktree.

## Constat de départ
- Tu travailles dans le worktree `/Users/comedelavenne/AI-Excel-Agent-integration-v2`, branche
  `integration/cvboost-10-v2`, créée depuis `main` = `f5b22f2`.
- Le repo principal `/Users/comedelavenne/AI-Excel-Agent` exécute en parallèle une **flotte d'agents
  живants** (workers). NE TOUCHE JAMAIS à : `messages/`, `missions_registry.json`,
  `mission_driver*`, `orchestrator*`, `guardian*`, `.mission_driver.pid`, `.orchestrator.pid` ni aux
  processus/terminaux de cette flotte.
- Nouvelles branches peuvent apparaître sur origin pendant ton travail : utilise le **snapshot
  ci-dessous** (44 missions done) comme périmètre. Ce qui arrive après ton fetch initial est hors lot.

## Périmètre : 44 livraisons done (registre véridiqué)
| Lot | Branche (origine la plus proche, cotidl) | Contenu |
|-----|------------------------------------------|---------|
| 01 | `agent/cvboost-01-cv-quality` | Analyseur structure CV |
| 02 | `agent/cvboost-02` | Extraction/provenance |
| 03 | `agent/cvboost-03` | UI + tests navigateur |
| 04 | `agent/cvboost-04-ats` | Formats PDF/DOCX, ATS |
| 05 | `agent/cvboost-05` | Workflow candidature full-stack |
| 06 | `agent/cvboost-06-sources` | Connecteurs sources |
| 07 | `agent/cvboost-07-dedup` | Déduplication |
| 08 | `agent/cvboost-08-adversarial` | Banc adversarial matching |
| 09 | `agent/cvboost-09` | Dashboard candidatures |
| 11 | `agent/cvboost-11-geo-filter` | Filtre géo |
| 13 | `agent/cvboost-13-geo-ranking` | Ranking géo |
| 16 | `agent/cvboost-16-salary-extractor` | Extracteur salaires |
| 21 | `agent/cvboost-21-matching` | Matching CV/offre |
| 22 | `agent/spec-sk01-source-trust` | Source trust |
| 23 | `agent/spec-sk02-offer-dates` | Dates offres |
| 24 | `agent/spec-sk03-requirements-fit` | Requirements fit |
| 25 | `agent/spec-sk04-source-coverage` | Source coverage |
| 26 | `agent/spec-sk05-exploration-progress` | Exploration progress |
| 27 | `agent/spec-sk06-dedup` | Dédup améliorée |
| 28 | `agent/spec-sk07-offer-intelligence-bridge` | Bridge intelligence offre |
| 29 | `agent/spec-sk08-connectors-enrich` | Connecteurs enrichis |
| 30 | `agent/spec-sk09-daily-search` | Recherche quotidienne |
| 31 | `agent/spec-sk10-candidate-profile` | Profil candidat |
| 32 | `agent/spec-sk11-application-dossier` | Dossier de candidature |
| 34 | `agent/spec-004-cv-review-workspace` | Workspace review CV |
| 35 | `agent/spec-005-daily-command-center` | Command center |
| 36 | `agent/spec-006-offer-freshness-dedup` | Freshness dedup |
| 38 | `agent/spec-008-evidence-center` | Evidence center |
| 40 | `agent/spec-010-interview-prep` | Interview prep |
| 41 | `agent/spec-sk14-intl-sources` | Sources internationales |
| 42 | `agent/spec-sk17-conditions-extractor` | Extracteur conditions |
| 43 | `agent/spec-sk18-missions-extractor` | Extracteur missions |
| 44 | `agent/spec-sk19-education-extractor` | Extracteur éducation |
| 45 | `agent/spec-sk20-exhaustiveness-scoring` | Scoring exhaustivité |
| 46 | `agent/spec-011-traceability` | Traçabilité |
| 47 | `agent/spec-012-evidence-freshness` | Evidence freshness |
| 48 | `agent/spec-013-dependencies-impact` | Dépendances & impact |
| 49 | `agent/spec-014-constitution` | Constitution |
| 50 | `agent/spec-015-creation-assistant` | Creation assistant |
| 52 | `agent/spec-017-ai-arena-core` (+ dupes `worker/cvboost-52-*`) | AI Arena multi-IA |
| 53 | `agent/spec-018-web-researcher` | Web researcher |
| 54 | `agent/spec-019-ats-keywords` (+ dupes `worker/cvboost-54-*`) | ATS keywords |
| 55 | `agent/spec-020-experience-reformulator` (+ `worker/cvboost-55-*`) | Reformulateur expérience |
| 58 | `agent/spec-023-personal-memory` | Mémoire personnelle |

**Règle de résolution de branche** : pour chaque lot, si les noms `agent/...` du tableau n'existent
pas sur origin, cherche `git branch -r | grep -iE "cvboost-<ID>-"` et retiens la branche dont le
tip porte le rapport/le code du SPEC correspondant (préfère le commit le plus récent ayant un
`docs/agent-reports/CVBOOST-<ID>*` ou `SPEC-*`). Si **plusieurs branches existent pour le même lot**
(doublons worker), retiens **une seule** — celle avec le push le plus récent **et** un diff non vide
vs main ; les autres sont REJETÉES (mentionne-les dans le rapport).

## INVALIDES / requisimientos de sécurité (bloquants, non négociables)
1. **Jamais** `git push`, `git pull`, `git fetch origin` *(autorise 1 seul fetch initial)*, `git rebase`,
   `git reset --hard` sur une branche partagée, checkout de `main`, ni aucun merge vers `main`.
2. **Jamais** détruire, kill, modifier ou créer un fichier dans les worktrees `*-worker-cvboost-*`,
   `AI-Excel-Agent` racine (hors lectures), ni tuer un process.
3. **Jamais** lire `.env`, CV réels, bases utilisateurs réelles ; tests sur fixtures synthétiques uniquement.
4. **Jamais** d'appel réseau réel ni d'envoi de candidature/emails ; rien ne quitte la machine.
5. Pas de nouvelle dépendance sans justification écrite dans le rapport.
6. Aucun skip/xfail ajouté ou supprimé dans les tests.

## PROCESSUS (dans l'ordre)
1. **Inventaire** : 1 fetch initial, liste les SHAs tips de chaque lot (tableau dans le rapport),
   vérifie rapports `docs/agent-reports/CVBOOST-*` sur chaque branche.
2. **Cartographie** fichiers partagés (`career/service.py`, `career_static/career.js`, `career/router.py`,
   `career/` ...) → détermine un **ordre de vagues par dépendances** (utiliser les deps du lot et la
   logique produit : extra-lots base d'abord — 01..09,11,13,16,21 — puis sk01-sk11 — puis SPEC 004-023).
3. **Intégration par vagues** (≈6-8 vagues de 5-10 lots). Pour chaque lot d'une vague :
   `git merge --no-ff <lot>` (ou `git cherry-pick` si un lot est court et linéaire — garde
   `--no-ff` comme défaut). Résouds les conflits **par contrat fonctionnel** (jamais « le fichier le
   plus récent gagne ») : garde les deux capacités quand elles sont orthogonales ; documente tout
   arbitrage. Après chaque lot : **tests ciblés** du module touché, puis commit `merge(candidate): lot <ID> — <titre>`.
4. **Vague complète** : `.venv/bin/python -m pytest -q` depuis `/Users/comedelavenne/AI-Excel-Agent`
   **OU** crée un venv propre dans le worktree (`python3 -m venv .venv-int && .venv-int/bin/pip install -e .
   -r requirements.txt` si présent) — la suite de référence est **1454+ tests verts** ; attendu :
   **≥1450 pass, 0 fail, 0 error**. Zéro régression tolérée sur ces nombres.
5. **Qualité** : `git diff --check` propre, pas de secrets (scan simple : mots-clés password/key/token),
   pas d'imports inutilisés sur les fichiers touchés (ruff si dispo).
6. **Recette navigateur synthétique** : lancer le serveur local de l'app (`career`/`come_ai_web.py`,
   port loopback), vérifier le flux principal : offre → plan CV → profil → kit candidature → export
   local → suivi. Aucune donnée réelle. Éteins le serveur après. (Si l'app ne démarre pas, prouve-le
   dans le rapport et marque la recette NON VÉRIFIÉE — ne bloque pas tout le lot dessus).
7. **Perf** : note le temps de démarrage serveur et le rendu d'une page clé (Mac Intel, honnête et grossier).

## LIVRABLES (obligatoires)
1. Branche candidate `integration/cvboost-10-v2`, commits propres par lot, tags de vagues en message.
2. `docs/agent-reports/CVBOOST-10-INTEGRATION-V2.md` :
   - tableau vagues → lots → SHA intégrés / REJETÉS + motifs ;
   - table des conflits résolus + règle de décision ;
   - nombres de tests réels par vague (pass/fail/skip exacts) + recette navigateur ;
   - limites, risques, procédure de rollback (`git reset` SHAs par vague) ;
   - verdict final : **MERGE AUTORISÉ** ou **MERGE REFUSÉ** (et pourquoi).
3. Aucun push : le merge final reste à l'utilisateur.

Commence par l'inventaire. Travaille par petites étapes vérifiées. Qualité > vitesse.
