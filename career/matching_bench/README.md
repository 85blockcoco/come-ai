# Banc adversarial de matching CV/offre (`career/matching_bench/`)

Banc d'évaluation reproductible du matching CV/offre et du plan CV
(mission **CVBOOST-08**).

Le banc ne simule pas le produit : il **appelle le code applicatif réel**
(`prepare_application`, `analyze_offer`, `score_brief_match`,
`assess_education_access`, `qualify_offer`) sur des couples CV/offre
synthétiques, puis confronte le résultat à une **vérité terrain écrite à la
main** pour chaque cas. Il ne modifie aucune règle métier.

## Lancement

```bash
PYTHONPATH=. python -m career.matching_bench list
PYTHONPATH=. python -m career.matching_bench run --out .devkit/bench
PYTHONPATH=. python -m career.matching_bench compare base.json candidat.json
PYTHONPATH=. python -m career.matching_bench thresholds --write
PYTHONPATH=. python -m pytest -q tests/test_matching_bench_*.py
```

`run` sort avec le code 1 si un seuil est violé : le banc sert de porte,
pas seulement de rapport.

## Ce qui est mesuré, et ce qui ne l'est pas

| Provenance | Statut | Ce que cela signifie |
|---|---|---|
| **Simulée** (fixtures synthétiques) | mesuré | Métriques calculées sur 118 couples synthétiques, exécution locale déterministe. |
| **Application vérifiée** | mesuré | Comportement produit par le code applicatif réel, pas par une reconstruction. |
| **Réseau réel** | `not_measured` | Aucune source officielle n'est contactée : ce chiffre ne vaut pas une mesure du réseau. |

Les trois axes sont mesurés **séparément** et ne sont jamais additionnés :

- **couverture** documentaire : exigences détectées et étayées par le profil ;
- **admissibilité** : contrat, durée et période de l'offre face aux critères ;
- **pertinence** : correspondance lexicale avec le brief de recherche.

## Deux familles de validateurs

- **Invariants durs** (`contracts.HARD_CHECKS`) : le contrat du produit. Une
  violation est un **défaut**, pas un score. Preuve verbatim, exigence
  traçable, locator résoluble, négation traitée, aucun contact, absent ⇒
  rien n'est ajouté, déterminisme, inconnu reste inconnu, axes non mélangés.
- **Contrôles sémantiques** (`contracts.SEMANTIC_CHECKS`) : comparaison avec
  la vérité terrain. C'est le seul endroit où un taux a du sens.

## Contenu

```
career/matching_bench/
├── contracts.py          vocabulaire, familles, seuils, politique réseau
├── fixtures.py           chargement + validation stricte des couples
├── generate_fixtures.py  générateur déterministe (--check pour vérifier)
├── validators.py         invariants durs et contrôles sémantiques
├── runner.py             exécution, métriques séparées, axes
├── thresholds.py         portes de régression, comparaison de runs
├── report.py             rapports JSON et Markdown
├── __main__.py           CLI
└── fixtures/
    ├── cv_offer_pairs.json   118 couples synthétiques versionnés
    └── thresholds.json       ligne de base et limites versionnées
```

## Règles d'hygiène

- 100 % synthétique : entreprises, offres, profils et domaines d'exemple
  réservés (`exemple-fake.test`). Le loader **refuse** un jeu de fixtures
  qui contient une adresse en dehors d'un domaine réservé.
- Aucun appel réseau, aucun secret, aucune donnée personnelle.
- Les verdicts d'admissibilité sont des tests de chemin de décision sur
  données synthétiques : ils ne prouvent aucune couverture de source réelle.
