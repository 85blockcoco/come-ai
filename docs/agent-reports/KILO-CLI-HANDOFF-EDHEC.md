# Rapport de passation — Kilo CLI

Date : 3 novembre 2026
Dépôt : `/Users/comedelavenne/AI-Excel-Agent`
Branche de livraison : `agent/n100-carrier-20261101`
Branche locale de travail : `agent/n100-G05-bundle-export`

## 1. Objectif

Livrer, avant l'examen EDHEC de venture capital, un outil de révision **simple**,
**hors-ligne** et **utilisable en 90 minutes** : annales corrigées, fiche de formules,
plan de bataille et page imprimable.

Le livrable ne devait pas dépendre d'un modèle payant, ne devait envoyer aucune
candidature, et ne devait pas versionner les annales brutes `docs/vc_study/`.

## 2. Résultat

L'outil est livré, testé, poussé et vérifié.

| Élément | État |
| --- | --- |
| Sujets EDHEC dérivés 2023 / 2024 / 2025 | 22 / 24 / 21 questions |
| Correction automatique QCM + numérique | livrée |
| Auto-évaluation des questions ouvertes et des cas | livrée |
| Fiche de formules | 7 familles |
| Pièges d'examen | 14 |
| Plan de 90 minutes | livré, paramétrable |
| Page HTML autonome et imprimable | `docs/vc_cram.html` |
| Fiche Markdown | `docs/vc_cram.md` |
| Tests VC ciblés | 160 passed |
| Suite complète dans une copie propre | 3904 passed |
| Ruff | OK |
| Smoke CLI | `SMOKE_EDHEC_OK`, 35/35 au sujet 2025 |

## 3. Fichiers livrés

| Fichier | Rôle |
| --- | --- |
| `academics/vc/pastpapers.py` | Chargement, validation, payload, template et correction des annales. |
| `academics/vc/cram.py` | Formules, pièges, plan 90 min, rendu Markdown et HTML. |
| `academics/vc/content/paper_2023.json` | Sujet 2023 dérivé. |
| `academics/vc/content/paper_2024.json` | Sujet 2024 dérivé. |
| `academics/vc/content/paper_2025.json` | Sujet 2025 dérivé, le plus proche de l'examen. |
| `academics/vc/cli.py` | Commandes `paper`, `cram`, `formulas`, et `vc` sans sous-commande. |
| `tests/test_vc_pastpapers.py` | 15 tests du lot EDHEC. |
| `docs/vc_cram.html` | Fiche complète imprimable, sans réseau. |
| `docs/vc_cram.md` | Même contenu en Markdown. |
| `docs/VC_REVISION_GUIDE.md` | Mode d'emploi, section 11 « Outil d'examen EDHEC ». |
| `docs/agent-reports/VC-MVP-PROOF.md` | Preuve détaillée, section 9. |
| `specs/004-venture-capital-revision/tasks.md` | Note d'implémentation du lot EDHEC. |

## 4. Utilisation immédiate

```bash
cd /Users/comedelavenne/AI-Excel-Agent

# Plan de 90 minutes
.venv/bin/python nage.py vc

# Fiche de formules + 14 pièges
.venv/bin/python nage.py vc formulas

# Sujets
.venv/bin/python nage.py vc paper list
.venv/bin/python nage.py vc paper show 2025
.venv/bin/python nage.py vc paper show 2025 --section A
.venv/bin/python nage.py vc paper show 2025 --solutions

# Entraînement corrigé
.venv/bin/python nage.py vc paper template 2025 --output answers.json
.venv/bin/python nage.py vc paper grade 2025 --answers answers.json

# Fiche imprimable
.venv/bin/python nage.py vc cram --html docs/vc_cram.html --markdown docs/vc_cram.md
open docs/vc_cram.html
```

Format du fichier de réponses :

```json
{
  "2025-A01": "D",
  "2025-B16": "54 %",
  "2025-B17a": "1.82"
}
```

Les unités `%`, `M€`, `k€` et `x` sont acceptées. Les QCM et les calculs sont corrigés
automatiquement ; les questions ouvertes et les cas sont marqués `self_assess` et le
corrigé s'affiche pour une auto-évaluation.

## 5. Preuves exécutées

### 5.1 Depuis un export propre de `HEAD`

```bash
ROOT=/Users/comedelavenne/AI-Excel-Agent
CHECK=$(mktemp -d)
git -C "$ROOT" archive HEAD | tar -x -C "$CHECK"
cd "$CHECK"
"$ROOT/.venv/bin/python" -m pytest -q tests/test_vc_*.py
"$ROOT/.venv/bin/python" -m ruff check academics/vc tests/test_vc_*.py
```

Résultat réel :

```text
160 passed in 6.93s
All checks passed!
```

Cela prouve que le commit de livraison est autosuffisant pour le package VC.

### 5.2 Suite complète

La suite complète a été lancée **seule et séquentielle** dans une copie propre construite
depuis le working tree, avec deux exclusions volontaires :

- `nage.py` remis à `HEAD` : les modifications utilisateur importent `vc_tutor.py`, qui
  recharge `.env` dans `os.environ` ;
- `academics/vc/cli.py` remis à `HEAD` : les hunks utilisateur `tutor`/`master` sont exclus
  du livrable.

Commande :

```bash
.venv/bin/python -m pytest -q
```

Résultat réel :

```text
3904 passed in 170.13s (0:02:50)
```

Ruff :

```text
.venv/bin/python -m ruff check academics/vc tests/test_vc_*.py
All checks passed!
```

### 5.3 Smoke CLI réel

```text
python nage.py vc
python nage.py vc paper list --json
python nage.py vc paper template 2025 --output answers.json
python nage.py vc paper grade 2025 --answers answers.json
python nage.py vc cram --html cram.html --markdown cram.md
```

Constats :

- `vc` sans argument affiche le plan de 90 minutes ;
- `paper list` renvoie `[(2023, 22), (2024, 24), (2025, 21)]` ;
- `paper template 2025` écrit 28 réponses auto-corrigeables (champs vides) ;
- `paper grade 2025` avec les 33 réponses de la clé complète donne `35/35 (100.0%)` ;
- le HTML généré fait 92 029 octets, le Markdown 49 747 octets ;
- 67 `<details>` ouverts et 67 fermés ;
- aucun lien `http://` ou `https://` ;
- résultat final : `SMOKE_EDHEC_OK`.

## 6. État Git

Commits du lot :

```text
9e8fbe0 docs(vc): note the EDHEC exam tool in the task plan
46db228 docs(vc): record EDHEC past-paper proof
5662820 feat(vc): add EDHEC past-paper trainer and cram sheet
```

- Commit de code : `56628202c1a84fb3e5a84b2bdb8e287fd8f5b74c`
- Commit de preuve : `46db228550939e3ad0bc5d71020176eb531dce00`
- Tip distant au moment de rédiger ce rapport (avant son propre commit) :
  `9e8fbe0c8481f154834f437777a55f77e8b56126`
- Branche distante : `agent/n100-carrier-20261101`
- Push fast-forward uniquement, aucun force-push, aucun reset, aucune réécriture.

Pour connaître le tip courant, y compris le commit de ce rapport :

```bash
git ls-remote origin refs/heads/agent/n100-carrier-20261101
```

### Modifications utilisateur à ne pas toucher

Le working tree contient encore, volontairement :

- `academics/vc/cli.py` : hunks personnels `tutor`/`master`, non commités ;
- `nage.py` : modifications personnelles ;
- de nombreux fichiers non suivis préexistants (`vc_tutor.py`, `vc_master.py`,
  `docs/vc_study/`, `_vc_courses/`, etc.).

Le CLI commité ne contient **aucun** hunk `tutor`/`master`. Vérification :

```bash
git show HEAD:academics/vc/cli.py | grep -c "tutor_cmd\|master_cmd"
# 0
```

## 7. Décisions d'architecture

- Les données apprenant restent dans `~/.nage/vc/` ou `NAGE_VC_HOME` ; aucun appel réseau.
- Les annales livrées sont un **pack dérivé** : questions condensées et paraphrasées,
  réponses numériques et corrigés reproduits. Les fichiers bruts `docs/vc_study/` restent
  non suivis.
- `pastpapers.py` est indépendant du moteur `exams.py` : les sujets réels ont des sections,
  des cas multi-parties et des questions ouvertes que le modèle générique ne représente pas
  bien.
- `cram.py` génère le HTML et le Markdown depuis les données ; aucune fiche n'est maintenue
  à la main.
- `nage.py vc` sans sous-commande lance directement le plan de 90 minutes.
- La correction est déterministe : QCM et numérique automatiques, ouvert et cas en
  auto-évaluation.

## 8. Limites et points d'attention

1. Le pack est dérivé et paraphrasé ; il ne remplace pas les énoncés originaux.
2. Les questions ouvertes et les cas ne sont pas notés par un humain.
3. Le cas Apfel 2024 utilise, dans son tableau officiel, un besoin en fonds de roulement
   égal à 10 % de l'EBITDA alors que l'énoncé indique 10 % du chiffre d'affaires. Le corrigé
   livré documente cet écart et reproduit les valeurs officielles.
4. `paper show --section` filtre l'affichage texte ; le mode `--json` renvoie le sujet
   complet. À corriger si un usage scripté du filtre est nécessaire.
5. La façade HTTP et la page statique restent hors périmètre.
6. Les objectifs de contenu 200 cartes / 100 drills / 20 cas / 100 questions / 120 termes
   restent un backlog.

## 9. Prochaines étapes suggérées pour Kilo

### Priorité 1 — finir US5

- `T167` : ajouter dans `tests/test_vc_mastery.py` un test de l'ordre de priorité
  « urgence d'examen, faiblesse, cartes dues, ordre des topics ».
- `T181` : vérifier et compléter la documentation radar/plan dans
  `docs/VC_REVISION_GUIDE.md` (section 8), puis cocher la tâche.

### Priorité 2 — cohérence CLI

- Faire respecter `--section` en mode `--json` dans `paper show`, avec un test ciblé.
- Vérifier et documenter le contrat de `paper grade --json` (le mode existe déjà).

### Priorité 3 — contenu

- Étendre progressivement les cartes, drills, cas, questions et termes sans copier de
  manuel protégé.
- Maintenir `academics/vc/content/` comme répertoire de données, sans `__init__.py`.

### Priorité 4 — surface

- Façade HTTP et page statique, en réutilisant le contrat JSON existant.

## 10. Règles à respecter

- Ne jamais modifier `main`.
- Aucun force-push, `reset --hard`, `git clean`, suppression de branche/worktree ou
  réécriture d'historique.
- Ne pas toucher aux fichiers réservés : `orchestrator.py`, `mission_driver.py`,
  `night_supervisor.py`, `model_health.py`, `missions_registry.json`,
  `missions_next100.json`.
- Tests ciblés d'abord ; suite complète seulement séquentielle et seule ; maximum 4 workers.
- Ruff sur les fichiers modifiés.
- Modèles gratuits uniquement, aucun fallback payant.
- Aucune candidature envoyée automatiquement.
- Aucune donnée personnelle ni clé API dans le dépôt.
- Ne pas committer `docs/vc_study/` ni les annales brutes.
- Toujours pousser et vérifier le SHA distant avant de déclarer « done ».

## 11. Reproductibilité rapide

```bash
cd /Users/comedelavenne/AI-Excel-Agent

# Vérifier le tip distant
git ls-remote origin refs/heads/agent/n100-carrier-20261101

# Tests ciblés depuis HEAD, sans le working tree
CHECK=$(mktemp -d)
git archive HEAD | tar -x -C "$CHECK"
(cd "$CHECK" && /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_vc_*.py)
rm -rf "$CHECK"

# Smoke
.venv/bin/python nage.py vc paper grade 2025 --answers answers.json
```

Pour la suite complète, reconstruire une copie propre depuis le working tree, puis
remplacer `nage.py` et `academics/vc/cli.py` par leur version `HEAD` avant de lancer
`pytest -q`.
