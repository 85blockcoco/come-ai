# SPEC-026 — Comparateur d'offres côte à côte

## Livré

- `career/offer_compare.py` : `OfferRow`, `CompareVerdict`, `DecisionMatrix`,
  `compare_offers()`, `normalize_attr()` et `verdict_to_dict()`.
- Matrice alignée `attr → offre → valeur` ; tout attribut absent d'une offre
  vaut explicitement `None` (jamais `0` par défaut).
- Score pondéré configurable via `weights`, classement `ranking` (meilleure
  offre en premier) et tie-breaker fraîcheur puis adéquation
  (`tie_breaker_used`).
- Endpoints REST `POST /api/career/offers/compare` (alias
  `POST /api/career/offer-compare`) servis par `create_app()`, sans modifier
  le schéma de base (`SCHEMA_VERSION = 8` du service Career reste intact).
- Fixture strictement synthétique
  `tests/fixtures/offers_compare_synthetic.json` (4 offres, une valeur
  manquante, dates et montants textuels).
- `tests/test_offer_compare.py` : 33 tests (normalisation, contrat, classement,
  tie-breakers, REST via `create_app()`, cas limites et adversariaux).

## Décisions

### Normalisation (`normalize_attr`)

- Montants : `"42 000 €"` → `42000`, `"48k"` → `48000`, `"1,5M"` →
  `1500000.0`, `"1 234,50 €"` → `1234.5`, `"12%"` → `12`.
- Valeurs absentes (`""`, `"n/a"`, `"nc"`, `"inconnu"`, `"—"`…) → `None`.
- Booléens textuels (`"oui"`/`"non"`, `"true"`/`"false"`) → `bool`.
- Dates ISO (`YYYY-MM-DD`) et françaises (`JJ/MM/AAAA`) → date ISO.
- `NaN`/`inf` → `None` pour rester JSON-safe et ne jamais fausser un score.
- Signatures acceptées : `(attr, value)`, `(mapping, attr)`, `(value)` et
  `attr=/value=`.

### Score pondéré

- Sans `weights`, chaque attribut pèse `1`. Avec `weights`, les attributs non
  listés pèsent `0` : la pondération est donc réellement configurable.
- Les noms de poids sont tolérants à la casse et aux séparateurs
  (`Salary`, `FIT`).
- Une valeur `None`/non numérique est ignorée (ni numérateur ni dénominateur) :
  une offre incomplète est jugée sur ses preuves disponibles, sans pénalité
  artificielle à `0`.
- Les attributs « coût-like » (`risk`, `cost`, `price`, `delay`, `distance`,
  `penalty`, `fee`, `frais`…) sont « plus bas = mieux » par défaut ;
  `higher_is_better` permet de surcharger cas par cas.
- Le score est arrondi à 6 décimales pour éviter que du bruit flottant ne
  casse une égalité parfaite.

### Tie-breaker

- Ordre : score décroissant, puis `freshness`, puis `fit` (configurable via
  `tie_breakers`).
- Les noms sont résolus par alias (`fresh`, `posted`, `match`, `score`…).
- à égalité complète, l'ordre d'entrée est conservé (déterministe).
- `tie_breaker_used` n'est `True` que si un tie-breaker a réellement
  départagé des offres de même score.

### API et erreurs

- Le payload est borné à 100 offres, 10 tie-breakers.
- Identifiants dupliqués, offres non-mapping et types invalides sont rejetés
  en `400` (`UserFacingError`) plutôt qu'en `500`.
- `POST` avec `offers: []` renvoie une matrice vide valide.

### Compatibilité et validation

- Le schéma local Career reste inchangé (`SCHEMA_VERSION = 8`), aucune
  migration ni nouvelle table n'est introduite.
- `tests/test_career_agent.py` : l'assertion sur le nombre de familles métier
  par défaut est alignée sur la taxonomie généralisée déjà présente dans
  `career/models.py` (14 familles au lieu de 6). Correction de test uniquement,
  aucun changement de comportement produit.
- Validation exécutée dans le worktree :
  - `.venv/bin/python -m pytest -q tests/test_offer_compare.py` →
    **33 passed** ;
  - `.venv/bin/python -m pytest -q` → **1541 passed, 1 skipped** ;
  - `.venv/bin/python -m ruff check .` → **All checks passed** ;
  - `git diff --check` → **clean**.

## Limites

- Le score compare des valeurs brutes : un attribut à grande échelle (salaire)
  domine un attribut à petite échelle (fit) à poids égal. Il faut pondérer en
  conséquence, ou normaliser en amont ; aucune mise à l'échelle min-max n'est
  appliquée pour rester prévisible et auditable.
- L'heuristique « plus bas = mieux » reste heuristique ; `higher_is_better`
  est la source de vérité pour les attributs ambigus.
- Les tie-breakers comparent les valeurs disponibles telles quelles ; une
  fraîcheur exprimée en texte libre non daté ne peut pas être ordonnée
  finement.
- Pas de persistance, pas d'UI dédiée et aucun accès réseau dans cette
  mission : le comparateur est un calcul local déterministe.
