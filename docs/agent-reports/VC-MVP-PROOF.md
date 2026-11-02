# Preuve — MVP révision Venture Capital

Date de recette : 2 novembre 2026

Branche de livraison : `agent/n100-carrier-20261101`

Commit de code : `41084f458c8de66fe2983aeac121e489a8f63910`

## Périmètre prouvé

Le package `academics/vc/` et la sous-commande `nage.py vc` livrent :

- US1 : session de rappel actif quotidienne, reprise après interruption, quatre notes ;
- US2 : drills de formules avec étapes et diagnostics ;
- US3 : cas chiffrés évalués par critères pondérés ;
- US5 : radar de maîtrise et plan de révision borné ;
- US7 : lexique FR/EN et décodeur de term sheet ;
- US8 : rapport de progression et rétention.

Les données restent dans `~/.nage/vc/` ou dans `NAGE_VC_HOME`. Aucun appel réseau, aucune
soumission automatique, aucun secret et aucune donnée personnelle ne sont ajoutés au dépôt.

## 1. Tests ciblés

Commande réellement exécutée :

```text
.venv/bin/python -m pytest -q tests/test_vc_*.py
```

Résultat :

```text
........................................................................ [ 69%]
...............................                                          [100%]
103 passed in 2.74s
```

Les fichiers couverts sont :

```text
tests/test_vc_cases.py
tests/test_vc_cli.py
tests/test_vc_content.py
tests/test_vc_drills.py
tests/test_vc_glossary.py
tests/test_vc_mastery.py
tests/test_vc_report.py
tests/test_vc_scheduler.py
tests/test_vc_smoke.py
tests/test_vc_storage.py
```

## 1 bis. Suite complète

Commande réellement exécutée, seule et séquentielle :

```text
.venv/bin/python -m pytest -q
```

Résultat :

```text
3847 passed in 221.79s (0:03:41)
```

## 2. Qualité statique

Commande réellement exécutée :

```text
.venv/bin/python -m ruff check academics/vc nage.py tests/test_vc_*.py
```

Résultat :

```text
All checks passed!
```

## 3. Smoke CLI réel

Le smoke a été exécuté avec `subprocess` sur un dossier temporaire isolé, sans toucher aux
données utilisateur. Il vérifie :

1. démarrage d'une session de 20 cartes ;
2. révélation d'une carte ;
3. notation `good` et avancement du curseur ;
4. reprise de la même session après interruption ;
5. liste de 6 drills VC04, bonne réponse, mauvaise réponse (`formula`) et réponse non
   numérique (`unit`) ;
6. drill aléatoire déterministe sur VC09 ;
7. affichage d'un cas sans réponse modèle avant soumission ;
8. correction d'un cas à 1.0 avec réponse modèle après soumission ;
9. recherche de glossaire et décodage d'un term sheet avec clause inconnue ;
10. radar sur 20 topics, plan borné à 30 minutes, rapport écrit dans `reports/` ;
11. suppression refusée avec une mauvaise phrase (code 2), puis acceptée avec la phrase exacte.

Sortie réelle :

```text
SMOKE_OK /private/var/folders/jd/ymcfd0zs7kzc6f90p1x6gh5c0000gp/T/opencode/vc-smoke-qh43ll4m
session ses-63bbd86f504c total 20 report /private/var/folders/jd/ymcfd0zs7kzc6f90p1x6gh5c0000gp/T/opencode/vc-smoke-qh43ll4m/vc/reports/2026-11-02-progress.md
```

## 4. Contenu livré

| Élément | Quantité vérifiée |
| --- | --- |
| Topics | 20 |
| Cartes | 50 |
| Drills | 24 |
| Cas | 4 |
| Termes de glossaire | 42 |
| Questions d'examen | 0 (US4 non livrée) |

Les tests de contenu vérifient aussi :

- l'ordre du curriculum et l'unicité des identifiants ;
- la présence d'étapes de calcul dont le dernier résultat égale la réponse ;
- la somme des poids de chaque cas à 1.0 ;
- l'unicité et la non-vacuité des termes FR/EN, avec exemple obligatoire ;
- le rejet d'une version de schéma non supportée, d'un topic dupliqué et d'un terme de
  glossaire dupliqué au chargement.

## 5. Sécurité et vie privée

Vérifications réalisées :

- refus d'un dossier VC qui est un lien symbolique ;
- permissions `700` sur le dossier et `600` sur les fichiers ;
- refus d'un `NAGE_VC_HOME` relatif ;
- suppression limitée au dossier VC avec phrase exacte ;
- aucune écriture dans le dépôt : `.nage/` et `vc_data/` sont dans `.gitignore` ;
- scan de secrets sur `academics/vc/`, `specs/004-venture-capital-revision/` et
  `tests/test_vc_*.py` : aucun motif de clé ou de clé privée.

## 6. Limites assumées

- US4 (examens blancs, oral) et US6 (ingestion de notes) ne sont pas livrées.
- La façade HTTP et la page statique ne sont pas livrées.
- Le contenu est un MVP original : l'extension à 200 cartes / 100 drills / 20 cas /
  100 questions / 120 termes reste un backlog.
- Le score des cas est une grille déterministe, pas une évaluation humaine.

## 7. Reproduce

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -m pytest -q tests/test_vc_*.py
.venv/bin/python -m ruff check academics/vc nage.py tests/test_vc_*.py
.venv/bin/python nage.py vc review --minutes 10
```
