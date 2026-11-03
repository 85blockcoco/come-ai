# Quickstart: Venture Capital Revision Coach

**Feature**: `004-venture-capital-revision`

Ce guide utilise le CLI local. Aucune connexion réseau, aucune clé API, aucune
donnée dans le dépôt. Les données d'apprentissage vivent dans `~/.nage/vc/`.

## 1. Vérifier l'installation

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python nage.py vc --help
```

Si la commande n'existe pas encore, le MVP n'est pas installé sur cette
branche. Voir `tasks.md`.

## 2. Première session de révision (10 minutes)

```bash
.venv/bin/python nage.py vc review --minutes 10
```

Le programme affiche une question. Appuyez sur Entrée pour révéler la réponse,
puis notez votre rappel :

- `again` : je ne savais pas ;
- `hard` : difficile, réponse incomplète ;
- `good` : correct ;
- `easy` : immédiat et sûr.

La carte est replanifiée immédiatement. Une session interrompue reprend au même
endroit :

```bash
.venv/bin/python nage.py vc review --minutes 10
```

Version non interactive (utile pour tester) :

```bash
.venv/bin/python nage.py vc review --minutes 10 --json
.venv/bin/python nage.py vc review --session <id> --reveal --json
.venv/bin/python nage.py vc review --session <id> --grade good --json
```

## 3. Drills de formules

Lister les exercices :

```bash
.venv/bin/python nage.py vc drill list --topic VC04
```

Répondre à un drill :

```bash
.venv/bin/python nage.py vc drill run VC04-D01 --answer "10 M€"
```

La correction affiche les étapes, l'unité et, en cas d'erreur, la catégorie :
`formula`, `order`, `unit`, `missing_data` ou `convention`.

Tirage déterministe :

```bash
.venv/bin/python nage.py vc drill random --topic VC07 --seed 7
```

## 4. Cas VC

```bash
.venv/bin/python nage.py vc case list
.venv/bin/python nage.py vc case show VC03-CASE01
```

Préparer un fichier de réponses :

```json
{
  "q1": "Post-money = 10 M€. L'investisseur détient 20 %.",
  "q2": "La liquidation preference 1x lui rend d'abord 2 M€."
}
```

```bash
.venv/bin/python nage.py vc case grade VC03-CASE01 --answers answers.json
```

Le résultat donne un score par critère, les nombres non justifiés et le corrigé
modèle. Ce n'est pas une note humaine : lisez la grille et auto-évaluez la
nuance.

## 5. Radar et plan

```bash
.venv/bin/python nage.py vc radar
.venv/bin/python nage.py vc plan --minutes 60 --exam-date 2026-12-15
```

Le radar distingue `untested`, `fragile`, `developing` et `solid`. Le plan ne
dépasse jamais la capacité demandée et explique chaque activité.

## 6. Examen blanc et oral

```bash
.venv/bin/python nage.py vc exam start --questions 20 --minutes 30 --seed 7
.venv/bin/python nage.py vc exam submit <exam_id> --answers answers.json
.venv/bin/python nage.py vc oral VC07 --count 5
```

## 7. Importer ses notes de cours

```bash
.venv/bin/python nage.py vc notes ingest ~/Documents/cours-vc.md --topic VC04
```

Chaque proposition affiche sa citation. Rien n'est ajouté au deck sans
approbation :

```bash
.venv/bin/python nage.py vc notes approve <proposal_id>
.venv/bin/python nage.py vc notes reject <proposal_id>
```

Les notes restent dans `~/.nage/vc/notes/` et ne sont jamais copiées dans le
dépôt.

## 8. Lexique et term sheet

```bash
.venv/bin/python nage.py vc glossary search "liquidation preference"
.venv/bin/python nage.py vc term-sheet decode term_sheet.txt
```

Un terme absent renvoie `non documenté`, jamais une invention.

## 9. Rapport de progression

```bash
.venv/bin/python nage.py vc report --days 30
```

Le rapport Markdown est écrit dans `~/.nage/vc/reports/`. Il contient les
topics couverts, les cartes dues, la rétention à 1/7/30 jours, les erreurs
récurrentes et les prochaines actions.

## 10. Supprimer les données VC

```bash
.venv/bin/python nage.py vc delete --confirm "SUPPRIMER MES DONNEES VC"
```

Cette commande supprime uniquement `~/.nage/vc/`. Elle ne touche ni Career, ni
`data/`, ni `output/`.

## Tests ciblés

```bash
.venv/bin/python -m pytest -q tests/test_vc_scheduler.py tests/test_vc_drills.py tests/test_vc_cases.py tests/test_vc_cli.py
.venv/bin/python -m ruff check academics/vc nage.py tests/test_vc_*.py
```

La suite complète se lance seule et séquentiellement avant livraison :

```bash
COME_AI_DIAGNOSTICS_OFFLINE=1 .venv/bin/python -m pytest -q
```

## Parcours recommandé pour l'examen

1. **J-21** : session de 45 min par jour, 2 topics, radar chaque semaine.
2. **J-14** : ajouter 2 cas par semaine et un examen blanc de 20 questions.
3. **J-7** : mode `exam_eve`, cartes dues + topics fragiles, 1 cas/jour.
4. **J-1** : 10 min de cartes dues, relire les erreurs récurrentes, dormir.
5. **Jour J** : ne pas découvrir de nouveau contenu ; relire le lexique et les
   formules.

## Dépannage

| Problème | Solution |
|----------|----------|
| `vc` inconnu | vérifier la branche et `nage.py` ; voir `tasks.md`. |
| Aucune carte due | lancer `vc drill random` ou avancer la date avec `--today` pour tester. |
| Session bloquée | `vc review --session <id> --status` ; les réponses déjà données sont conservées. |
| Notes PDF vides | le PDF est probablement scanné ; utiliser un PDF texte ou coller le texte. |
| Doute sur une carte | la marquer `a_completer` et vérifier avec le cours. |
