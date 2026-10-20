# Atelier Développeur — maintenance Côme AI

Ce kit utilise Python 3.12 et le venv existants. Ses diagnostics, exports et
imports de correctifs ne déclenchent aucune installation ni aucun appel IA.

## Une commande pour vérifier le projet

```bash
cd ~/AI-Excel-Agent
.venv/bin/python -m devkit check
```

Le kit copie le code autorisé, puis vérifie la syntaxe Python, les versions
installées, `pip check`, tous les tests de `tests/`, le smoke test V3 et la
syntaxe JavaScript avec Node s’il est disponible. Les scripts historiques
`agent.py`, `agent_v2.py` et `test_gemini.py` (retirés du dépôt) restent
exclus de sa copie. Les tests utilisent des fixtures fictives, sans les
documents de l’application.

Rapports : `.devkit/diagnostics/latest.md` et `latest.json`, avec historique
daté, erreurs utiles, états passed/failed/blocked/skipped, nombre de tests,
versions et empreinte SHA-256 des sources réellement testées. Le délai global
est de 600 secondes ; `check --timeout 300` permet de le réduire. Codes de
sortie : 0 réussite, 1 échec, 2 vérification bloquée.

Le runner construit un environnement sans clés ni proxy et expurge ses
sorties des formes courantes de secrets et de chemins personnels. Sur ce
Mac, `sandbox-exec` refuse le réseau, la lecture des originaux et les écritures
hors de la copie temporaire. Le venv et les bibliothèques du système restent
lisibles. Si cette isolation OS ne fonctionne pas, la validation d’un
correctif est bloquée : une garde Python seule ne suffit pas pour l’appliquer.

## Exporter le code

```bash
.venv/bin/python -m devkit export
```

Une archive neuve est créée dans `.devkit/exports/`. L’option
`--output /chemin/nouveau-snapshot.zip` choisit une autre destination, sans
écrasement. L’export joint le dernier diagnostic et sa date ; il ne relance
pas les tests. Le ZIP contient :

- `source/` : code, interfaces, tests et documentation autorisés ;
- `MANIFEST.json` : chemins relatifs, tailles et empreintes ;
- `ARCHITECTURE.md` : rôles des modules et périmètre fourni ;
- `DEPENDENCIES.json` : noms et versions, sans URL d’installation privée ;
- `DIAGNOSTICS.json` : rapport expurgé ou absence de rapport explicitée.

La liste blanche exclut `.env`, `.venv`, `data`, `output`, `logs`,
`career_data`, `memory_data`, `state`, `.devkit`, caches, clés, archives,
bases, documents et liens symboliques. Limites : 1 Mio par fichier, 15 Mio au
total et 1 000 fichiers. Un secret potentiel dans le code bloque l’export
sans afficher de fragment. Le kit ne peut pas déterminer si un commentaire
ou une description libre contient des faits personnels : relis le dossier
technique avant de le partager.

## Transmettre un problème à une autre IA

```bash
.venv/bin/python -m devkit issue \
  --title "L’analyse CSV retourne une erreur" \
  --description "Étapes, résultat observé et résultat attendu." \
  --file workspace_core.py \
  --file tests/test_come_ai_v3.py
```

Il faut choisir au moins un fichier source relatif au projet. Ajoute
`--errors-file /chemin/erreur.txt` pour un message technique choisi
volontairement. Les journaux ne sont jamais joints automatiquement.

La demande ajoute `ISSUE.md` et `ISSUE.json` (schéma version 1) : problème,
erreurs expurgées, fichiers concernés et empreintes, architecture,
dépendances et dernier rapport. Seul le code sélectionné est inclus. Joins
ce ZIP à ChatGPT Chat, Work, Gemini ou Codex avec cette instruction :

> Lis ISSUE.md et source/. Retourne un correctif minimal au format unified
> diff avec chemins relatifs au projet, puis explique les changements et
> tests. Utilise des données fictives. Ne demande aucune clé API.

Pour exécuter le projet exporté sur une autre machine, il faut un Python
disposant des dépendances listées. `python -m devkit --python /chemin/python
check` utilise ce runtime. Le kit n’installe rien automatiquement.

## Importer et vérifier un correctif

```bash
.venv/bin/python -m devkit stage --patch /chemin/correction.patch
.venv/bin/python -m devkit preview ID_CANDIDAT
.venv/bin/python -m devkit check --candidate ID_CANDIDAT
.venv/bin/python -m devkit apply ID_CANDIDAT --confirm
.venv/bin/python -m devkit rollback ID_TRANSACTION --confirm
```

`stage` retourne l’identifiant et le diff exact, en préparant une copie
isolée. `check --candidate` teste cette copie avec le venv principal en
lecture seule. `apply` exige une suite pytest effectivement exécutée et
réussie, la sandbox OS active et les empreintes actuelles du candidat et du
projet principal. Il faut également confirmer l’action.

Les fichiers complets sont acceptés :

```bash
.venv/bin/python -m devkit stage \
  --file workspace_core.py=/chemin/workspace_core_corrige.py
```

Le mode interface « Fichiers corrigés » accepte un objet JSON :

```json
{"module.py": "def exemple():\n    return 42\n"}
```

Les patchs peuvent ajouter, modifier ou supprimer des fichiers source.
Chemins absolus, traversées, liens symboliques, binaires, renommages et
changements de permissions sont refusés. Une édition du projet après la
préparation bloque l’application ; une édition après application empêche
son écrasement par le retour arrière. Les sauvegardes et historiques
survivent au redémarrage dans `.devkit/candidates/` et `.devkit/transactions/`.

Les écritures sont atomiques, avec verrou interprocessus et sauvegardes
avant/après. Une erreur déclenche une tentative de restauration. L’état
rare `recovery_required` signale une récupération manuelle nécessaire si
une édition concurrente empêche cette restauration. Relis le diff, y
compris les modifications éventuelles des tests. Après application ou
restauration, redémarre Côme AI pour charger le nouveau code.

## Interface locale et extension IA

Lance `.venv/bin/python run_come_ai_v3.py` comme auparavant, puis ouvre
**Atelier Développeur** dans `/v5`. Il permet de consulter les diagnostics,
télécharger les exports, préparer une demande, importer un correctif,
voir son aperçu, tester sa copie et confirmer l’application ou le retour
arrière. Une seule vérification de l’atelier s’exécute à la fois. Les
archives restent sur le disque ; un nouvel export recrée son lien de
téléchargement après redémarrage. Les copies et sauvegardes conservées
restent accessibles depuis l’historique.

`devkit/proposals.py` fournit le contrat `CorrectionProvider` et
`propose_in_isolation`. Un adaptateur reçoit uniquement les sources
sélectionnées et la demande expurgée, puis retourne du texte à préparer
dans une copie. Ce contrat n’expose aucune commande ni opération
d’application du correctif. Le circuit est testé avec un faux modèle local.
Aucun adaptateur réel Gemini, OpenRouter ou Ollama n’est activé ici ; leur
ajout pourra utiliser la politique de gratuité existante et une génération
volontaire avec budget explicite. Les correctifs restent testés et appliqués
manuellement, même lorsqu’ils viennent d’une IA.
