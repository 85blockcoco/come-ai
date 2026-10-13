# Côme AI — référence de pilotage de l’intégration

État vérifié le 13 octobre 2026. Responsable de l’intégration : Codex.

Ce document décrit les livraisons acceptées et celles encore séparées. Il ne remplace pas les résultats d’exécution. Toute future session doit le lire, contrôler `git status` dans chaque worktree concerné et annoncer un périmètre limité avant de modifier des fichiers.

## État accepté de main

- Base de départ : `1b570ddf4734f5f8698c49c3972586e3c6685754`.
- Lot 1 accepté : `c64d4da7d7844fab4a9fa06467c7170a5265a696`.
- Contribution MiMo source : `4b55f013cf1484f8fc36fd722a7a839627c80fb8`, branche `feature/moteur-format-fiabilisation`.
- Intégration préparée, corrigée et testée sur `integration/lot1-mimo`, puis avancée de `main` par `git merge --ff-only`.
- Ce document est versionné séparément. Le commit de documentation ne change pas le code validé.
- Aucun appel API, achat, téléchargement ou lecture de clé n’a été nécessaire.

## Lots et responsabilités

| Lot / module | État réel | Responsable / provenance | Branche et commit | Preuves et prochaine action |
| --- | --- | --- | --- | --- |
| 1 — génération de correctifs et diagnostics (`devkit/evolution*.py`) | Intégré : diagnostic de format précis mais sans fragments arbitraires ; consommation conservée avant rejet de troncation ou substitution | MiMo pour la contribution initiale ; Codex pour le durcissement et l’acceptation | `main`, `c64d4da` ; source `4b55f01` | 96 tests ciblés ; 416 + 2 dans DevKit ; les 2 scénarios ignorés réussis séparément ; revue indépendante sans blocage |
| 2 — faits observés, quotas, `Retry-After`, bridge | Commits identifiés, pas encore intégrés ; ne pas fusionner tant que Step 5 travaille | Step 5 propriétaire du worktree ; Codex intégrateur | `feature/step5-intelligence-centrale` : `7e3fafb`, `22255c8` | Vérifier la migration additive, la sémantique des quotas et les tests après gel |
| 3 — raccordement du chat au décideur | Non accepté : les quatre blocages sont présents dans la révision examinée | Step 5 ; Codex valide après livraison stabilisée | `41224d8` sur la branche Step 5 | Conserver le couple fournisseur/modèle ; repli local admissible en panne catalogue ; refus de capacité sans contournement ; normaliser `ollama` / `ollama_local` |
| Cycle de correction supplémentaire Step 5 | Commit récent identifié, non revu et non accepté | Step 5 | `8c5c2129ed58c84316882c58fd4123f81f72d4a1` | Contribution apparue pendant l’intégration ; ne pas confondre son message de commit avec une preuve de cycle réel |
| 4 — parcours utilisateur Excel + notes + rapport + suivi | Pas exécuté ; pas annoncé opérationnel | Codex après acceptation des lots 2 et 3 | Aucun commit de livraison | Exécuter de vrais outils sur des données synthétiques, vérifier les sources et la confirmation avant écriture |
| Laboratoire qualité `evals/` | Travail indépendant, nouveaux fichiers non suivis préservés ; non intégré | Auteur à confirmer, ne pas l’attribuer sur le seul nom d’un modèle/session | `feature/evals-qualite`, base `1b570dd` au point de reprise | Ne bloque pas les lots 1 à 3 ; accepter plus tard avec son contrat et ses tests |
| Mémoire Nemotron | Travail indépendant ; aucune nouvelle livraison intégrée ici | Nemotron | `feature/nemotron-memory`, base `1b570dd` au point de reprise | Ne bloque pas l’intégration ; rechercher une livraison stabilisée avant tout raccordement |

La dernière tête Step 5 observée est `8c5c212`. L’utilisateur a demandé son gel ; cette demande n’est pas encore une confirmation de fin. Une copie propre à un instant donné ne prouve pas qu’un agent a cessé ses modifications.

## Périmètre fonctionnel conservé

| Module | Responsabilité conservée | Niveau de preuve dans cette livraison |
| --- | --- | --- |
| `come_ai_web.py`, `app_v3.py`, `v5_static/` | Interface/API V5 et application locale | Non-régression automatisée ; aucun nouveau parcours navigateur complet |
| `hybrid_chat.py`, `free_ai_router.py`, catalogue et routeurs | Chat et appels hybrides soumis aux règles de gratuité | Comportements couverts par les tests existants ; nouveau raccordement Step 5 non accepté ; pas de benchmark de qualité cloud |
| `workspace_core.py`, outils locaux | Import, inspection, calculs et rapports contrôlés | Smoke test réel hors IA : CSV, inspection, analyse, rapport Excel réussis |
| `personal_memory.py` et modules mémoire existants | Mémoire locale et contexte documentaire | Tests existants ; ne pas annoncer une recherche sémantique Nemotron intégrée |
| `task_queue.py` et orchestrateur existant | Persistance et exécution de types de plans pris en charge | Une ligne SQLite ne démontre pas l’exécution d’une tâche utilisateur quelconque |
| Career, Study, Finance et autres espaces existants | Espaces conservés sans refonte | Non-régression de la suite, pas de nouvelle qualification exhaustive de chaque parcours |
| `devkit/` | Export sécurisé, diagnostic, staging isolé, validation, historique et retour arrière | Suite hors réseau + scénarios réels de sandbox sur fixtures ; génération IA simulée dans ces validations |

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

## Blocages à lever, par priorité

1. **Gel Step 5 confirmé** : commit final communiqué, worktree propre, agent non actif. Aucun merge de sa branche mouvante.
2. **Lot 2** : préserver les anciennes lignes SQLite avec migration additive ; ne pas inventer `remaining_requests=0` depuis une erreur quota ; distinguer cooldown observé/calculé ; respecter `Retry-After=0` ; dédupliquer les noms de tests ledger qui écrasent des définitions antérieures.
3. **Lot 3** : corriger les quatre refus d’acceptation du tableau et ajouter les régressions correspondantes. Rejeter un tarif, une preuve de gratuité ou des capacités manquants ; pas de métadonnées réputées gratuites par défaut.
4. **Lot 4** : distinguer une tâche personnelle à accomplir et un plan logiciel exécutable. Ne pas présenter un texte libre enregistré comme un workflow déjà exécuté. Prouver le worker, les résultats, la confirmation, le rapport généré, les citations et le suivi.
5. **Après consolidation** : évaluer les contributions `evals` et Nemotron indépendamment. Garder l’auto-amélioration expérimentale en copie isolée, sans déploiement critique automatique.

## Critères d’acceptation pour les prochaines sessions

- Périmètre de fichiers et propriétaire définis ; pas de modification simultanée d’un fichier appartenant à un autre agent actif.
- Snapshot/commit exact et worktree propre ; sauvegarde des changements non suivis avant toute intégration.
- Diff relu ; gratuité stricte et permissions non affaiblies ; aucun secret, donnée personnelle ou base privée dans un correctif/document.
- Tests ciblés d’abord, puis DevKit hors réseau ; scénarios OS ignorés exécutés séparément si concernés.
- Rapport lié à l’empreinte réelle des sources ; succès HTTP distinct de fiabilité technique et de qualité de réponse.
- Chaque lot accepté dans un commit indépendant. Aucun test réel de fournisseur sans confirmation des règles de gratuité et budget borné.
- Mise à jour de ce document : état réel, agent, branche/commit, commandes, tests, blocages et prochaine action.

Prochaine action : recevoir le commit final gelé de Step 5, préparer une nouvelle copie d’intégration et accepter le lot 2 seul avant de traiter le raccordement du chat.
