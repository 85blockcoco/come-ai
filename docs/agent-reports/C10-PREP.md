# Mission 10 — préparation de l'intégration Career CV Boost

Date : 20 octobre 2026  
Branche : `integration/prep-01`  
Base : `e3c77f4a81b0e3c48a86d27b08f48ed539c1d26d`  
Statut : **TERMINÉE — outil prêt pour la phase 2**

## Isolation respectée

Le worktree d'intégration est `/Users/comedelavenne/AI-Excel-Agent-integration`.
Aucun fichier non suivi ou modifié par les agents dans le checkout principal n'a été lu,
modifié, complété, supprimé ou testé. Aucun merge, rebase, push, stash, clean ou changement
de `main` n'a été effectué.

## Outil livré

Commande :

```bash
python scripts/audit_integration.py \
  --branch agent/cvboost-NN \
  --base e3c77f4a81b0e3c48a86d27b08f48ed539c1d26d \
  --allow-path CHEMIN_AUTORISE
```

Options de sécurité :

- `--allow-path` déclare le périmètre normal du lot ; sans périmètre, le lot est refusé.
- `--allow-shared-path career/service.py` ou `career_static/career.js` est indispensable en
  plus du périmètre normal si un lot touche un de ces deux fichiers très partagés.
- `--allow-network-path` permet à l'intégrateur d'autoriser explicitement un connecteur réseau
  déjà revu ; le réseau ajouté ailleurs est refusé.
- `--output` choisit le journal JSON. Par défaut, il est écrit dans
  `.devkit/integration-audits/`.

L'outil vérifie :

1. la validité de la branche et l'ascendance de la base ;
2. tous les fichiers modifiés contre le périmètre déclaré ;
3. les fichiers partagés nécessitant une seconde autorisation explicite ;
4. les lignes ajoutées pour `SCHEMA_VERSION`, `window.prompt`, appels réseau non autorisés,
   secrets, clé privée, activation d'une soumission automatique ou primitives d'envoi ;
5. les données ressemblant à des données personnelles dans les tests et évaluations ;
6. le marquage synthétique obligatoire des fichiers contenant `_REAL` dans leur nom ;
7. l'ajout d'un test `TestClient` lorsqu'une route Career est modifiée ;
8. un checkout détaché dans un worktree temporaire ;
9. `pytest`, `ruff check` et `git diff --check` dans ce checkout ;
10. la suppression du seul worktree temporaire créé par l'outil, même après une erreur ;
11. un verdict console et un journal JSON structuré.

Les lignes ayant déclenché un motif de secret ne sont jamais copiées dans le journal. Seuls le
nom de la règle, le chemin et le numéro de ligne sont conservés.

## Tests automatisés de l'outil

Commande réellement exécutée :

```text
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_audit_integration.py
```

Résultat :

```text
.....                                                                    [100%]
5 passed in 15.39s
```

Contrôle qualité réellement exécuté :

```text
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m ruff check scripts/audit_integration.py tests/test_audit_integration.py
All checks passed!
```

`git diff --check` : sortie vide, code retour 0.

## Validation complète du worktree d'intégration

La checklist a d'abord été appelée sans configuration et a refusé de démarrer, car un worktree
Git ne contient pas son propre `.venv`. Elle a été relancée sans installation avec :

```text
VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python ./checklist_codex.sh
```

Résultat de la suite globale exécutée par cette checklist :

```text
1153 passed in 329.40s (0:05:29)
```

DevKit : `207 passed in 40.73s`. La checklist termine néanmoins avec `ÉCHEC(S)` car son filtre
de noms considère à tort les fichiers de code légitimes `secret_redaction.py` et
`tests/test_secret_redaction_parity.py` comme des secrets trackés. Aucun contenu de secret n'a
été signalé. Les worktrees mémoire et Study Coach ainsi que les rapports DevKit étaient absents
relativement à ce worktree et ont été ignorés. Le script n'a pas trouvé l'exécutable `ruff` sur
le `PATH` du shell, mais le module présent dans le venv a été exécuté séparément :

```text
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m ruff check .
All checks passed!
```

`git diff --check` est également propre. Ces limites de la checklist existante sont documentées ;
elle n'a pas été modifiée dans cette mission.

## Double preuve par la commande publique

Un dépôt Git entièrement synthétique a été créé sous un répertoire temporaire. Sa base est
`d45b8e5941dccfd335669381be0c5983646072d9`.

### Lot propre

Branche synthétique : `agent/proof-clean` (`5f2f992`).  
Périmètre déclaré : `feature.py`, `test_feature.py`.

Résultat réel :

```text
[OK] base_is_ancestor
[OK] declared_scope
[OK] shared_files
[OK] forbidden_patterns
[OK] temporary_worktree
[OK] pytest
[OK] ruff
[OK] diff_check
VERDICT : MERGE AUTORISÉ
```

### Lot fautif

Branche synthétique : `agent/proof-unsafe` (`5f887be`).  
Le diff contient volontairement un import réseau, un appel `window.prompt` sous forme de chaîne
et un secret factice.

Résultat réel :

```text
[REFUS] forbidden_patterns — 3 constat(s) bloquant(s)
[BLOQUANT] network_call — unsafe.py:1
[BLOQUANT] secret_openai — unsafe.py:3
[BLOQUANT] window_prompt — unsafe.py:4
VERDICT : MERGE REFUSÉ
expected_exit=2
```

Le secret factice est absent du journal JSON (`secret_absent_du_journal=oui`). La validation
dynamique n'est pas lancée sur un lot déjà refusé statiquement.

### Auto-audit du lot C10-PREP

L'outil a ensuite audité sa propre branche depuis la base `e3c77f4`, avec les trois fichiers du
lot déclarés explicitement et les tests ciblés exécutés dans son worktree jetable. Les contrôles
de descendance, périmètre, fichiers partagés, motifs interdits, création/nettoyage du worktree,
Pytest, Ruff et `git diff --check` ont tous réussi. Verdict réel : `MERGE AUTORISÉ`.

Un premier essai avait correctement mis au jour un faux positif auto-induit par les lexèmes de la
règle de détection d'envoi d'e-mail présents dans le scanner lui-même. La construction de cette
expression régulière a été rendue auto-hébergeable, puis couverte par les six tests ciblés avant
ce nouvel auto-audit vert.

## Limites connues

- Un scanner lexical ne prouve pas l'absence de comportement dangereux indirect ou obfusqué ; la
  revue humaine du diff reste obligatoire.
- `ruff` et `pytest` prouvent le candidat checkouté, pas les services externes ni un parcours réel.
- Les connecteurs réseau doivent être autorisés chemin par chemin après revue de leur hôte,
  transport, limites et tests hors ligne.
- L'outil ne fusionne rien et ne juge pas la valeur produit d'une fonctionnalité.
- La présence de `TestClient` est une garde structurelle, pas la preuve suffisante de tous les cas HTTP.
- La phase 2 devra comparer les résultats annoncés dans les rapports aux commandes réellement rejouées.

## Branches attendues en phase 2

L'intégrateur attend les branches gelées suivantes :

1. `agent/cvboost-01`
2. `agent/cvboost-02`
3. `agent/cvboost-03`
4. `agent/cvboost-04`
5. `agent/cvboost-05`
6. `agent/cvboost-06`
7. `agent/cvboost-07`
8. `agent/cvboost-08`
9. `agent/cvboost-09`

Au moment du pré-vol, les références visibles étaient `agent/cvboost-02`, `03`, `05`, `08` et
`09`. Cette observation ne signifie ni que ces lots sont terminés ni que les autres n'existent pas
dans un environnement OpenCode détaché. Aucune branche ne sera auditée avant confirmation de gel et
communication du commit final.

## Phase 2 restant à exécuter

Pour chaque lot gelé : résoudre le SHA final, lire le rapport, déclarer le périmètre, exécuter
l'auditeur, revoir le diff, rejouer les tests ciblés, puis seulement préparer un candidat empilé.
Après les neuf lots : recette navigateur complète, tests globaux, contrôle des performances,
rapport d'intégration et décision finale `MERGE AUTORISÉ` ou `MERGE REFUSÉ`. `main` restera inchangé
jusqu'à une validation humaine explicite.
