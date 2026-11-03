# Preuve — MVP révision Venture Capital

Date de recette : 2 novembre 2026

Branche de livraison : `agent/n100-carrier-20261101`

Commit de code US6 : `2671d0f33dd20a2f91d1aac3d888fe7960821270`

Commit de code EDHEC : `56628202c1a84fb3e5a84b2bdb8e287fd8f5b74c`

Commit de code US4 : `6d2a72e187c785ed2f87ef049e63d162b2f3e0ae`

## Périmètre prouvé

Le package `academics/vc/` et la sous-commande `nage.py vc` livrent :

- US1 : session de rappel actif quotidienne, reprise après interruption, quatre notes ;
- US2 : drills de formules avec étapes et diagnostics ;
- US3 : cas chiffrés évalués par critères pondérés ;
- US4 : examen blanc chronométré, notation QCM/numérique/ouverte, topics faibles,
  séance de rattrapage et oral simulé sans corrigé ;
- US5 : radar de maîtrise et plan de révision borné ;
- US6 : ingestion de notes `.txt`/`.md`/PDF texte, citations exactes, approbation explicite,
  rejet persistant et détection de source modifiée ;
- US7 : lexique FR/EN et décodeur de term sheet ;
- US8 : rapport de progression et rétention ;
- outil d'examen EDHEC 2023-2025 : annales dérivées, correction automatique, fiche de
  formules, plan de 90 minutes et page HTML hors-ligne.

Les données restent dans `~/.nage/vc/` ou dans `NAGE_VC_HOME`. Aucun appel réseau, aucune
soumission automatique, aucun secret et aucune donnée personnelle ne sont ajoutés au dépôt.

## 1. Tests ciblés

Commande réellement exécutée :

```text
.venv/bin/python -m pytest -q tests/test_vc_*.py
```

Résultat :

```text
........................................................................ [ 49%]
........................................................................ [ 99%]
.                                                                        [100%]
145 passed in 4.76s
```

Les fichiers couverts sont :

```text
tests/test_vc_cases.py
tests/test_vc_cli.py
tests/test_vc_content.py
tests/test_vc_drills.py
tests/test_vc_exams.py
tests/test_vc_glossary.py
tests/test_vc_mastery.py
tests/test_vc_notes.py
tests/test_vc_report.py
tests/test_vc_scheduler.py
tests/test_vc_smoke.py
tests/test_vc_storage.py
```

## 1 bis. Suite complète

La suite complète a été rejouée dans une copie propre construite depuis le working tree,
avec deux exclusions volontaires pour isoler le lot US6 :

- `nage.py` remis à `HEAD` (les modifications utilisateur `vc tutor`/`vc master` non
  commitées importent `vc_tutor`, qui charge `.env` dans `os.environ`) ;
- `academics/vc/cli.py` limité aux hunks US6 (les hunks utilisateur `tutor`/`master` sont
  absents).

Commande réellement exécutée, seule et séquentielle :

```text
.venv/bin/python -m pytest -q
```

Résultat :

```text
3888 passed, 1 skipped in 177.77s (0:02:57)
```

Le skip est le test `tests/test_offer_summary_exhaustiveness.py::...` qui exige un script
ou une base absents de la copie isolée.

Contrôle de non-régression : la même suite exécutée dans le working tree complet donne
`3865 passed, 24 failed`. Les 24 échecs sont tous dans des tests réseau/configuration
(`test_hybrid_chat.py`, `test_come_ai_v3.py`, `test_intelligence_router.py`) et sont causés
par les modifications utilisateur non commitées de `nage.py`. Preuve : `vc_tutor.load_env()`
copie `.env` dans `os.environ` dès l'import, et `AppConfig.load()` donne priorité à
`os.environ` sur le `.env` temporaire du test. Aucun de ces échecs ne touche `academics/vc/`
ni les fichiers du commit US6. Les tests concernés passent seuls et le lot VC reste vert.

## 2. Qualité statique

Commande réellement exécutée sur la copie propre `HEAD + US6` :

```text
.venv/bin/python -m ruff check academics/vc tests/test_vc_*.py
```

Résultat :

```text
All checks passed!
```

Dans le working tree complet, `nage.py` et les sections utilisateur de
`academics/vc/cli.py` contiennent des erreurs ruff préexistantes (`E401` sur
`import subprocess, sys`, `F841`/`F821` dans les commandes `tutor`). Elles sont hors du
périmètre US6, n'ont pas été modifiées et ne sont pas présentes dans le commit.

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
11. démarrage d'un examen de 4 questions, 100 points, sans corrigé dans la sortie ;
12. reprise du même examen, soumission à 1.0, historique écrit et examen actif supprimé ;
13. oral VC07 avec relances, sans réponse modèle ;
14. radar alimenté par les résultats d'examen ;
15. examen expiré avec statut `expired` et réponses conservées ;
16. suppression refusée avec une mauvaise phrase (code 2), puis acceptée avec la phrase exacte.

Sortie réelle du smoke US4 :

```text
SMOKE_EXAM_OK /private/var/folders/jd/ymcfd0zs7kzc6f90p1x6gh5c0000gp/T/vc-exam-smoke-8ymgxcl6
```

Le smoke historique P1 reste valide :

```text
SMOKE_OK /private/var/folders/jd/ymcfd0zs7kzc6f90p1x6gh5c0000gp/T/opencode/vc-smoke-qh43ll4m
session ses-63bbd86f504c total 20 report /private/var/folders/jd/ymcfd0zs7kzc6f90p1x6gh5c0000gp/T/opencode/vc-smoke-qh43ll4m/vc/reports/2026-11-02-progress.md
```

### Smoke US6 — notes citées

```text
SMOKE_INGEST 5 fe4a9a0ab9ef
SMOKE_LIST {'proposed': 4, 'a_completer': 1, 'approved': 0, 'rejected': 0}
SMOKE_APPROVE vcnote-45d5ab2056df
SMOKE_A_COMPLETER blocked
SMOKE_A_COMPLETER answered
SMOKE_REJECT_REINGEST 1
SMOKE_REPLACE {'imported', 'superseded'}
SMOKE_SCAN_PDF rejected
SMOKE_REVIEW_TOTAL 10
SMOKE_NO_REPO_LEAK ok
SMOKE_NOTES_OK /private/var/folders/jd/ymcfd0zs7kzc6f90p1x6gh5c0000gp/T/vc-notes-smoke-3jgjhs0r
```

Le smoke crée un marqueur privé dans une note temporaire, vérifie qu'il reste dans
`notes/<source_id>.txt`, puis exécute `git grep` et `git status` pour prouver qu'il n'apparaît
jamais dans le dépôt. Les erreurs de source modifiée ne recopient pas le texte de la note.

## 4. Contenu livré

| Élément | Quantité vérifiée |
| --- | --- |
| Topics | 20 |
| Cartes | 50 |
| Drills | 24 |
| Cas | 4 |
| Termes de glossaire | 42 |
| Questions d'examen | 20 (5 par topic VC04, VC05, VC07, VC09) |
| Formats d'examen | QCM, numérique, ouvert |
| Points d'examen | 100 |

Les tests de contenu vérifient aussi :

- l'ordre du curriculum et l'unicité des identifiants ;
- la présence d'étapes de calcul dont le dernier résultat égale la réponse ;
- la somme des poids de chaque cas à 1.0 ;
- l'unicité et la non-vacuité des termes FR/EN, avec exemple obligatoire ;
- la validité des points, unités, choix QCM, mots-clés et réponses numériques d'examen ;
- le rejet d'une version de schéma non supportée, d'un topic dupliqué et d'un terme de
  glossaire dupliqué au chargement.

## 5. Sécurité et vie privée

Vérifications réalisées :

- refus d'un dossier VC qui est un lien symbolique ;
- permissions `700` sur le dossier et `600` sur les fichiers ;
- refus d'un `NAGE_VC_HOME` relatif ;
- suppression limitée au dossier VC avec phrase exacte ;
- aucune écriture dans le dépôt : `.nage/` et `vc_data/` sont dans `.gitignore` ;
- les notes importées restent dans `~/.nage/vc/notes/` et ne sont jamais recopiées dans un
  message d'erreur ou dans le dépôt ;
- scan de secrets sur `academics/vc/`, `specs/004-venture-capital-revision/` et
  `tests/test_vc_*.py` : aucun motif de clé ou de clé privée.

## 6. Limites assumées

- La façade HTTP et la page statique ne sont pas livrées.
- Le contenu est un MVP original : l'extension à 200 cartes / 100 drills / 20 cas /
  100 questions / 120 termes reste un backlog.
- Les scores de cas et d'examen sont des grilles déterministes, pas une évaluation humaine.
- L'extraction PDF dépend de la couche texte ; un scan sans OCR est refusé explicitement.

## 7. Livraison

- Branche : `agent/n100-carrier-20261101`
- Commit de code US6 : `2671d0f33dd20a2f91d1aac3d888fe7960821270`
- Push fast-forward vérifié : `48cb521..2671d0f`
- `git ls-remote` après push :
  `2671d0f33dd20a2f91d1aac3d888fe7960821270 refs/heads/agent/n100-carrier-20261101`
- Commit de code US4 : `6d2a72e187c785ed2f87ef049e63d162b2f3e0ae`
- Aucun force-push, aucun reset, aucune réécriture d'historique.
- Un commit de documentation postérieur peut déplacer le tip ; les SHA de code US4 et US6
  restent ceux ci-dessus.

## 8. Reproduce

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -m pytest -q tests/test_vc_*.py
.venv/bin/python -m ruff check academics/vc tests/test_vc_*.py
.venv/bin/python nage.py vc review --minutes 10
.venv/bin/python nage.py vc notes ingest cours_vc.md --topic VC04
.venv/bin/python nage.py vc notes list
.venv/bin/python nage.py vc exam start --questions 20 --minutes 30 --seed 7
.venv/bin/python nage.py vc oral VC07 --count 5
```

## 9. Lot outil d'examen EDHEC (annales 2023-2025)

### Contenu livré

- `academics/vc/pastpapers.py` : chargement et validation des sujets, payload, template,
  correction déterministe des QCM et des réponses numériques (unités et tolérances),
  auto-évaluation des questions ouvertes et des cas.
- `academics/vc/cram.py` : fiche de 7 familles de formules, 14 pièges, plan de 90 minutes
  paramétrable, rendu Markdown et HTML autonome/imprimable.
- `academics/vc/content/paper_2023.json` : 22 questions.
- `academics/vc/content/paper_2024.json` : 24 questions.
- `academics/vc/content/paper_2025.json` : 21 questions.
- `tests/test_vc_pastpapers.py` : 15 tests.
- CLI : `vc paper list|show|template|grade`, `vc cram`, `vc formulas`, et `nage.py vc`
  sans sous-commande qui lance directement le plan de 90 minutes.

Les sujets sont un **pack dérivé** : questions condensées et paraphrasées, réponses
numériques et corrigés pas à pas reproduits. Les annales brutes `docs/vc_study/` ne sont
pas suivies par Git et ne sont pas livrées.

### Tests ciblés

Commande exécutée dans la copie propre :

```text
.venv/bin/python -m pytest -q tests/test_vc_*.py
```

Résultat :

```text
160 passed in 5.03s
```

### Suite complète

Copie propre construite depuis le working tree, avec les deux exclusions volontaires :

- `nage.py` remis à `HEAD` (les modifications utilisateur importent `vc_tutor.py`, qui
  recharge `.env` dans `os.environ`) ;
- `academics/vc/cli.py` reconstruit depuis `HEAD` avec uniquement les hunks EDHEC
  (`paper`, `cram`, `formulas`, `vc` sans sous-commande) ; les hunks `tutor`/`master`
  sont absents.

Commande réellement exécutée, seule et séquentielle :

```text
.venv/bin/python -m pytest -q
```

Résultat :

```text
3904 passed in 170.13s (0:02:50)
```

### Ruff

```text
.venv/bin/python -m ruff check academics/vc tests/test_vc_*.py
All checks passed!
```

### Smoke CLI réel

```text
python nage.py vc
python nage.py vc paper list --json
python nage.py vc paper template 2025 --output answers.json
python nage.py vc paper grade 2025 --answers answers.json
python nage.py vc cram --html cram.html --markdown cram.md
```

- `vc` sans argument affiche le plan de 90 minutes ;
- `paper list` renvoie `[(2023, 22), (2024, 24), (2025, 21)]` ;
- `paper template 2025` écrit 28 réponses auto-corrigeables ;
- `paper grade 2025` avec les bonnes réponses donne `35/35 (100.0%)` ;
- `cram` écrit un HTML de 92 029 octets et un Markdown de 49 747 octets ;
- le HTML contient 67 `<details>` équilibrés et aucun lien `http://` ou `https://` ;
- résultat final : `SMOKE_EDHEC_OK`.

### Livraison du lot

- Commit de code : `56628202c1a84fb3e5a84b2bdb8e287fd8f5b74c`
- Branche : `agent/n100-carrier-20261101`
- Push fast-forward vérifié : `6d38ed3..5662820`
- `git ls-remote` après push :
  `56628202c1a84fb3e5a84b2bdb8e287fd8f5b74c refs/heads/agent/n100-carrier-20261101`
- Aucun force-push, aucun reset, aucune réécriture d'historique.

### Limites assumées

- Le pack est dérivé et paraphrasé ; il ne remplace pas les énoncés originaux.
- Les questions ouvertes et les cas sont auto-évalués à partir du corrigé, pas notés par
  un humain.
- Le cas Apfel 2024 utilise, dans son tableau officiel, un besoin en fonds de roulement
  égal à 10 % de l'EBITDA alors que l'énoncé indique 10 % du chiffre d'affaires ; le
  corrigé livré documente cet écart et reproduit les valeurs officielles.
