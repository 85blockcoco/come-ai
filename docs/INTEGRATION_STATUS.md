# Côme AI — référence de pilotage de l’intégration

État vérifié le 13 octobre 2026. Responsable de l’intégration : Codex.

Ce document décrit les livraisons acceptées et celles encore séparées. Il ne remplace pas les résultats d’exécution. Toute future session doit le lire, contrôler `git status` dans chaque worktree concerné et annoncer un périmètre limité avant de modifier des fichiers.

## État accepté de main

- **Career Stage Hunter livré** : commit métier `fe798858d51dfa4facccdad325b8b87ec62744a9`, intégré par avance rapide de `main` à `fb9dbba9fc8dce2c89407d8c91ba348fce84e40c`. Les sections plus bas décrivant la copie Career « préparée » sont historiques et remplacées par cette acceptation.
- Career accessible sur `http://127.0.0.1:8765/career#career/stagehunter`. Serveur principal démarré après contrôle du port libre ; aucun serveur préexistant arrêté ou redémarré. Port 8877 réservé à la fixture navigateur, pas aux données utilisateur.
- Après fusion : **161 tests ciblés réussis**, comprenant les 159 tests du parcours / non-régression ciblée et les 2 scénarios de sandbox réelle. Détails et limites : `docs/CAREER_STAGE_HUNTER_ACCEPTANCE.md`.
- Non-régression **rejouée dans main après fusion** : **681 réussis, 2 ignorés en 44,45 s** ; les deux ignorés réussissent dans la commande ciblée ci-dessus. Syntaxe Python / JavaScript, dépendances et smoke CSV → rapport Excel réussis. Rapport `.devkit/diagnostics/2026-10-13T21-46-46.599913Z.md`, empreinte identique à la copie `d7098a354143d36c18e1dd044db7edf628c0647c69aea88c315a843f520c0a6a`.
- Base de départ : `1b570ddf4734f5f8698c49c3972586e3c6685754`.
- Lot 1 accepté : `c64d4da7d7844fab4a9fa06467c7170a5265a696`.
- Laboratoire accepté : `c3652af`, adaptateur réel : `f9b8163`, collecte DevKit corrigée : `4e203a8`.
- Lot 2 accepté sur la base consolidée : `7def9859100437b28240b2151abebe7a4bc7805f`.
- Lot 3 accepté : `13fe634346322fae1073bc7597663ff03dc1da5e` (préparation `6937bc2`, source `41224d8`).
- Contribution MiMo source : `4b55f013cf1484f8fc36fd722a7a839627c80fb8`, branche `feature/moteur-format-fiabilisation`.
- Intégration préparée, corrigée et testée sur `integration/lot1-mimo`, puis avancée de `main` par `git merge --ff-only`.
- Ce document est versionné séparément. Le commit de documentation ne change pas le code validé.
- Aucun appel API, achat, téléchargement ou lecture de clé n’a été nécessaire.

## Lots et responsabilités

| Lot / module | État réel | Responsable / provenance | Branche et commit | Preuves et prochaine action |
| --- | --- | --- | --- | --- |
| Career Stage Hunter | **Intégré et disponible** : critères explicites, découverte classée avant limite 150, préparation factuelle et suivi utilisable dans le navigateur intégré | MiMo / Career pour la contribution ; Codex et sous-agents pour sélection, corrections du parcours et acceptation | `main`, métier `fe79885`, intégration `fb9dbba` ; source conservée `a146769` | 159 ciblés sur copie ; 161 ciblés et 681 réussis / 2 ignorés post-fusion ; vrai navigateur sur données fictives ; un GET public Greenhouse réel. Pas de candidature externe envoyée |
| 1 — génération de correctifs et diagnostics (`devkit/evolution*.py`) | Intégré : diagnostic de format précis mais sans fragments arbitraires ; consommation conservée avant rejet de troncation ou substitution | MiMo pour la contribution initiale ; Codex pour le durcissement et l’acceptation | `main`, `c64d4da` ; source `4b55f01` | 96 tests ciblés ; 416 + 2 dans DevKit ; les 2 scénarios ignorés réussis séparément ; revue indépendante sans blocage |
| 2 — faits observés, quotas, `Retry-After`, bridge | Intégré : données factuelles, aliases normalisés et migrations additives | Step 5 source ; Codex et sous-agent pour le durcissement ; revue indépendante | `main`, `7def985` ; sources `7e3fafb`, `22255c8` ; préparation `b6ffadf` | 81 tests ciblés ; 460 sur copie Lot 2 ; 561 sur base consolidée, chaque fois 2 scénarios OS ignorés |
| 3 — raccordement du chat au décideur | Intégré : les quatre blocages sont corrigés, y compris les modes manuel et hors ligne | Step 5 source ; Codex et sous-agent pour le durcissement | `main`, `13fe634` ; préparation `6937bc2` ; source `41224d8` | 181 tests ciblés ; 606 réussis et 2 ignorés en DevKit ; 2 scénarios OS réussis séparément ; requêtes cloud simulées seulement |
| Cycle de correction supplémentaire Step 5 | Revu et testé sur sa branche ; conservé, non intégré dans les lots faits/chat | Step 5 | `8c5c212`, branche gelée à `b535b6c` | Pipeline, sandbox, validation et rollback réels sur projet temporaire ; génération par `ScriptedModel`, donc fictive |
| 4 — parcours utilisateur Excel + notes + rapport + suivi | Pas exécuté ; pas annoncé opérationnel | Codex après acceptation des lots 2 et 3 | Aucun commit de livraison | Exécuter de vrais outils sur des données synthétiques, vérifier les sources et la confirmation avant écriture |
| Laboratoire qualité `evals/` | Intégré et durci ; 60 contrats historiques, séparés des 9 scénarios de services réels | OpenCode source ; Codex et sous-agents pour l’acceptation et l’adaptateur | Source `5216ff3`, main `c3652af`, `f9b8163`, `4e203a8` | 29 tests source ; 78 tests labo + 19 adaptateur ; 8 réussites réelles, 1 capacité non prise en charge, 0 simulation dans le score réel |
| Mémoire Nemotron | API profil partielle : deux fichiers modifiés, non commités, préservés ; pas intégrés | Nemotron | `feature/nemotron-memory`, base `1b570dd` | `come_ai_web.py`, `personal_memory.py` : 597 ajouts / 3 retraits ; endpoints spécifiques et frontend à qualifier ; ne pas créer un second store personnel |

La tête Step 5 vérifiée est `b535b6c562ad7586d53e762b19490cd3ba194623`, arbre propre. L’utilisateur a confirmé le gel ; les métadonnées locales indiquaient aussi `idle_outcome=succeeded`. Les 141 tests ciblés exécutés sur cette révision ont réussi, mais reproduisaient encore les quatre blocages : un grand nombre de tests verts ne les résout pas. L’intégration utilise les corrections relues, pas un merge aveugle de cette branche.

## Périmètre fonctionnel conservé

| Module | Responsabilité conservée | Niveau de preuve dans cette livraison |
| --- | --- | --- |
| `come_ai_web.py`, `app_v3.py`, `v5_static/` | Interface/API V5 et application locale | Non-régression automatisée ; aucun nouveau parcours navigateur complet |
| `hybrid_chat.py`, `free_ai_router.py`, catalogue et routeurs | Chat et appels hybrides soumis aux règles de gratuité | Faits/cooldowns et raccordement intégrés ; modèle exact testé jusqu’au payload avec transports fictifs ; pas de benchmark de qualité cloud |
| `workspace_core.py`, outils locaux | Import, inspection, calculs et rapports contrôlés | Smoke test réel hors IA : CSV, inspection, analyse, rapport Excel réussis |
| `personal_memory.py` et modules mémoire existants | Mémoire locale et contexte documentaire | Tests existants ; ne pas annoncer une recherche sémantique Nemotron intégrée |
| `task_queue.py` et orchestrateur existant | Persistance et exécution de types de plans pris en charge | Une ligne SQLite ne démontre pas l’exécution d’une tâche utilisateur quelconque |
| Career, Study, Finance et autres espaces existants | Espaces conservés sans refonte | Non-régression de la suite, pas de nouvelle qualification exhaustive de chaque parcours |
| `devkit/` | Export sécurisé, diagnostic, staging isolé, validation, historique et retour arrière | Suite hors réseau + scénarios réels de sandbox sur fixtures ; génération IA simulée dans ces validations |
| `evals/come_ai_target.py` | Adaptateur borné aux services existants sur workspaces temporaires | Calcul par le chat, FTS5/citation, CSV/XLSX, orchestrateur, refus d’écriture et d’outils exécutés réellement ; aucun modèle interrogé |

## Évaluations et validation de la consolidation

- Les 49 cas `supported` historiques décrivent des contrats, pas 49 parcours Côme AI vérifiés. Leur compteur `application_verified` reste à zéro. Une cible réelle doit déclarer ses capacités et son handler, sinon le cas est `unsupported`.
- `ComeAITarget` ne lit pas `expected` pour produire sa sortie. Il appelle les services réels, dans un nouveau workspace synthétique par cas, sans `AppConfig.load`, `.env`, documents privés ou génération de modèle.
- Les sockets TCP/DNS/UDP et le transport cloud sont bloqués ; les tests démontrent ce blocage. Les refus applicatifs attendus sont distincts des erreurs d’exécution imprévues.
- `real`, `simulated`, `unsupported`, `execution_error` et `incorrect` sont distingués. Le taux réel exclut les simulations ; consommation déclarée et RSS du processus ne sont pas des mesures de tokens/coût ni de RAM propre au modèle.
- Les comparaisons refusent les provenances incompatibles et les contrats modifiés sous un même ID. Les empreintes de cas/suite sont enregistrées ; une perte de couverture fait échouer le mode strict.
- `evals/tests` est inclus dans le bootstrap DevKit et la collecte pytest. Code et JSON synthétiques de `evals/cases/` sont exportables ; `evals/runs/` et `.devkit/` ne le sont pas. Les démonstrations de version 1 restent archivées et explicitement simulées.
- Laboratoire consolidé : **517 réussis, 2 ignorés**, rapport `.devkit/integration/evals-qualite/.devkit/diagnostics/2026-10-13T16-57-51.655489Z.md`.
- Avec lot 2 : **561 réussis, 2 ignorés**, rapport `.devkit/integration/evals-qualite/.devkit/diagnostics/2026-10-13T17-01-11.480567Z.md`.
- Avec lot 3 : **606 réussis, 2 ignorés**, rapport `.devkit/integration/evals-qualite/.devkit/diagnostics/2026-10-13T17-09-32.803059Z.md`. Les deux scénarios de sandbox ont été exécutés hors runner imbriqué : **2 réussis en 5,58 s**.
- Premier run réel avec empreintes : **8 réussis, 1 unsupported, aucune simulation**, JSON `.devkit/integration/evals-qualite/.devkit/evals/runs/fb0ae918436f.json`, rapport `real-services-validated.md` dans ce même dossier. Ce run précède le nouveau raccordement du chat ; le revalider sur l’état final.
- Revalidation sur lot 3 : **8 réussis réels, 1 unsupported, 0 simulation**, JSON `f57e74d6eef7.json`, rapport `final-real-services.md` dans le même dossier. Comparaison stricte : **aucune régression, aucune perte de couverture**, rapport `consolidation-comparison.md`.
- Empreinte source finale : `69f6b2982495c82bae696a3f4ae340963c89ac4fa331e68c6c69bc3d712aed03`.
- La revue indépendante supplémentaire du chat n’a pas abouti, faute de quota du sous-agent. Ne pas la compter comme une validation ; la revue principale, les 181 tests et la non-régression 606 ont abouti.

Commandes reproductibles, depuis la racine du projet :

```bash
.venv/bin/python -m pytest -q evals/tests
.venv/bin/python -m evals run --target come-ai --strict
.venv/bin/python -m devkit --python /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python check --timeout 300
```

## Preuves du lot 1 et commandes exécutées

Dans `/Users/comedelavenne/AI-Excel-Agent/.devkit/integration/lot1-mimo` :

```bash
git cherry-pick --no-commit 4b55f013cf1484f8fc36fd722a7a839627c80fb8
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_evolution_providers.py tests/test_evolution.py
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m devkit --python /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python check --timeout 300
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_devkit_real_workflow.py tests/test_evolution_real_sandbox.py
git diff --check
```

Les corrections ont été appliquées dans cette copie uniquement, avant le commit d’acceptation. Résultats :

- ciblés : **96 réussis**, 3,07 s ;
- DevKit : **416 réussis, 2 ignorés**, 41,35 s pour pytest ; Python, dépendances, smoke local et syntaxe JavaScript également réussis ;
- scénarios de sandbox hors runner déjà isolé : **2 réussis**, 5,75 s ;
- les deux tests ignorés par DevKit exigent une sandbox non imbriquée sur macOS : ils ne constituent donc plus une vérification manquante pour cette livraison ;
- empreinte source validée : `5caed8c98e2a452afc399a37fc0f277ef2b9e251feca0ffc31a1fa4f384ffe29` ;
- rapport : `.devkit/integration/lot1-mimo/.devkit/diagnostics/latest.md` et `latest.json`.

Acceptation dans `/Users/comedelavenne/AI-Excel-Agent` :

```bash
git merge --ff-only integration/lot1-mimo
git status --short
git log -1 --format='%H %s'
```

Les données de tests sont fictives. Les tokens conservés dans les tests proviennent de réponses simulées, pas d’une API réelle. La vérification OS et les calculs/rapports locaux, eux, sont réellement exécutés. Ce lot ne prouve ni un nouveau modèle connecté ni une amélioration de sa qualité cognitive.

## Point de reprise et conservation

Sauvegarde initiale privée :

`/Users/comedelavenne/AI-Excel-Agent/.devkit/integration/20261013T161928Z`

- `repository.bundle` : historique et références Git au moment du checkpoint, vérifié par `git bundle verify`.
- `manifest.json` : worktrees, commits, statuts, fichiers sauvegardés et empreintes.
- archives `*-changes.zip` : modifications de sources et nouveaux fichiers autorisés ; huit fichiers sauvegardés, dont les six nouveaux fichiers `evals/` présents à cet instant.
- les données, secrets, bases privées et fichiers hors liste autorisée restent dans leurs emplacements d’origine ; ils ne sont ni copiés ni supprimés.
- les changements postérieurs au checkpoint sont toujours dans les worktrees d’origine : contrôler l’état courant avant toute opération.

Recontrôler sans modifier :

```bash
cd /Users/comedelavenne/AI-Excel-Agent
git worktree list --porcelain
git status --short
git bundle verify .devkit/integration/20261013T161928Z/repository.bundle
```

La copie d’intégration et les worktrees des contributeurs sont conservés. Ce document dans `docs/` est versionné par Git ; il n’appartient pas actuellement à la liste de sources exportées par le DevKit. Les preuves locales et le bundle sont privés et exclus de Git.

## Inventaire du nouveau briefing général — 13 octobre 2026

Contrôle en lecture seule avant toute nouvelle intégration : `main` propre à `7def985` ; nouveau lot 3 alors indexé dans la copie consolidée, et son commit de préparation `6937bc2` conservé. Aucun merge global des nouvelles branches.

| Contribution | Révision et état constatés | Validation effectuée / manquante | Décision et prochaine action |
| --- | --- | --- | --- |
| Career Stage Hunter / MiMo | `feature/career-stage-hunter`, `a14676950b58d6833d396175949dffa69a44d9aa`, propre ; quatre commits propres au métier depuis `4e203a8` | 92 tests source réussis en 8,28 s ; **136 tests de la commande du handoff réussis en 18,02 s sur la copie issue du main consolidé** ; SSL `CERT_REQUIRED` et vérification hostname actifs | Copie `integration/career-stage-hunter` préparée, treize fichiers indexés et non intégrés à main. `_normalise()` tranche les 150 premières offres avant classement : corriger la sélection et les cas hors cap avant acceptation ; navigation/browser et vrai parcours final encore à vérifier |
| Personal Context Engine / Step 5 | `feature/personal-context-engine`, `8864b47`, dirty : review/store/README/contrat/test isolation + nouveaux tests confidentialité/suppression, handoff et modèle Space Bunny | 195 dédiés / 758 globaux / 21 démo annoncés, non rejoués ici sur cet état encore modifié | P1 : attendre livraison figée, auditer contrat et suppression ; candidat à la source de vérité des faits personnels approuvés |
| API profil Nemotron | Base `1b570dd`, deux fichiers non commités ; état décrit ci-dessus | 394 historiques annoncés, pas de suite d’endpoints spécifique vérifiée dans cette mission | P1 : adapter l’API à l’unique moteur personnel retenu ; ne pas fusionner le nouveau store en parallèle |
| Control Center | `feature/workspace-control-center`, base `7def985`, `Lanceurs/`, `workspace_control/` et trois fichiers de tests non suivis | Code présent, pas de nouveau commit ni tests rejoués ici | P1 après gel : intégrer lancement/état serveur/repères fiables, sans modifier les environnements ou tuer des processus arbitraires |
| Noveria Career Intelligence | `feature/noveria-career-integration`, base `7def985`, `career_intelligence/` et `tests/test_job_quality.py` non suivis | Existence vérifiée, fonctionnement non qualifié | P2 : réutiliser comme extension de Career, pas comme moteur concurrent ; aucun code privé de Noveria reçu/présumé |
| Profil Space Bunny | Export final non fourni/validé dans cette mission ; modèle de fichier candidat présent dans le worktree profil | Aucun souvenir personnel réel lu, approuvé ou importé par l’intégrateur | Validation individuelle par l’utilisateur ; aucun contenu intime implicitement envoyé aux clouds |
| Auto-amélioration Nemotron/OpenRouter | Appel `poolside/laguna-s-2.1:free` et candidat `7fd61db38202430b8f920ae2b7649fbb` rapportés par le briefing | Traces non authentifiées ici ; ne pas confondre avec le `ScriptedModel` de `8c5c212` | P2 : vérifier métadonnées/prix/sandbox/hashes sans lire de clé ; pas de nouveau cloud ni déploiement automatique |

Protection supplémentaire : `.devkit/integration/20261013T205420Z` contient le bundle complet vérifié et **32 fichiers source/texte/lanceurs non commités** provenant des 13 worktrees recensés. Les modes de fichiers sont dans le manifeste. Les JSON de données/modèles de profil et autres fichiers exclus restent intacts dans leur worktree : ce n’est pas un archivage des données privées. Refaire un checkpoint source avant de toucher à une livraison qui évolue.

Architecture mémoire proposée, **pas encore implémentée ni acceptée** : interface Mon profil → API V5 adaptée de Nemotron → Personal Context Engine comme source unique des faits approuvés → Chat/Career/Finance avec consentements explicites. La mémoire documentaire FTS5 et les données métier de candidatures conservent leur rôle ; ne pas dupliquer les faits personnels dans une deuxième base centrale. Contrats, statuts, révisions, historique, suppression réelle et exclusions cloud sont des portes d’acceptation, pas des présomptions.

L’application déjà en cours n’a pas été redémarrée ni testée dans un navigateur pendant cette consolidation. Le code serveur doit être rechargé pour utiliser le nouveau routage. Le parcours Career enrichi, les nouveaux endpoints profil et Control Center ne doivent pas être annoncés disponibles avant leur intégration et test de navigation.

## Blocages à lever, par priorité

1. **Career livré** : utiliser Stage Hunter pour les premières offres et candidatures manuelles. Le classement avant la coupe, la non-régression et le parcours navigateur ont été validés ; voir le rapport d’acceptation. Aucun dépôt automatique.
2. **P1 mémoire** : figer le moteur personnel, vérifier confidentialité/suppression, adapter l’API Nemotron et frontend. Une source de vérité, permissions explicites, aucune donnée réelle dans Git.
3. **P1 Control Center** : valider les lanceurs et diagnostics serveur, puis intégrer les composants utiles par lot autonome.
4. **P2 Noveria et auto-amélioration** : qualifier les fichiers existants et la trace du candidat signalé ; élargir sans second moteur Career ni déploiement critique automatique.
5. **Parcours utilisateur complet** : distinguer tâche personnelle et plan logiciel ; rapport après confirmation et worker réellement exécuté. Toujours non démontré par les seuls enregistrements SQLite ou les huit scénarios limités du labo.

## Critères d’acceptation pour les prochaines sessions

- Périmètre de fichiers et propriétaire définis ; pas de modification simultanée d’un fichier appartenant à un autre agent actif.
- Snapshot/commit exact et worktree propre ; sauvegarde des changements non suivis avant toute intégration.
- Diff relu ; gratuité stricte et permissions non affaiblies ; aucun secret, donnée personnelle ou base privée dans un correctif/document.
- Tests ciblés d’abord, puis DevKit hors réseau ; scénarios OS ignorés exécutés séparément si concernés.
- Rapport lié à l’empreinte réelle des sources ; succès HTTP distinct de fiabilité technique et de qualité de réponse.
- Chaque lot accepté dans un commit indépendant. Aucun test réel de fournisseur sans confirmation des règles de gratuité et budget borné.
- Mise à jour de ce document : état réel, agent, branche/commit, commandes, tests, blocages et prochaine action.

Prochaine action utilisateur : renseigner les critères dans Stage Hunter, configurer un board public exact ou importer une annonce, préparer et suivre une candidature. Les lots mémoire / Control Center / Noveria restent séparés ; aucune intégration supplémentaire dans cette livraison.

### Reprise exacte du lot Career préparé

Copie : `/Users/comedelavenne/AI-Excel-Agent/.devkit/integration/career-stage-hunter`, branche `integration/career-stage-hunter`, base `28323d4`. Les quatre contributions `98a5815`, `089ea83`, `6368817`, `a146769` ont été appliquées **sans commit**. Ne pas recommencer ce cherry-pick et ne pas fusionner le worktree tant qu’il est modifié. Aucun fichier des worktrees sources n’a été changé.

Commande réussie, depuis cette copie :

```bash
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_career_stage_hunter.py tests/test_career_agent.py tests/test_career_action_plan.py tests/test_calendar_export.py tests/test_come_ai_v3.py tests/test_hybrid_web.py tests/test_evolution_web.py tests/test_v5_web.py
```

Gates restantes avant commit et intégration :

1. Une annonce répondant aux critères mais située après l’index 150 doit pouvoir être retenue. Évaluer les candidats avant la coupe, avec classement déterministe réutilisant le module existant, critères explicites et limite conservée ; ne pas envoyer les critères ou le profil au board public.
2. Des entrées malformées en début de flux ne doivent pas éliminer des offres valides plus loin. La troncature et les limites de taille doivent rester visibles et bornées.
3. Préserver TLS obligatoire et interdiction des redirections arbitraires ; ne jamais résoudre un problème SSL avec un contexte non vérifié.
4. Rejouer les 136 tests, puis non-régression consolidée ; tester les vrais écrans sur un serveur isolé et un profil/offres fictifs. Un TestClient en processus ne prouve pas la navigation d’un navigateur.
5. Préparation et suivi oui, candidature externe jamais envoyée automatiquement. L’essai public Stripe annoncé par l’auteur (722/150) n’a pas été refait ni authentifié ici.
