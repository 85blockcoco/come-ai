# MISSION SPEC-026 — Comparateur d'offres côte à côte

> **Priorité : P1** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-026-offer-compare`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Le candidat hésite entre plusieurs offres similaires ; il faut comparer objectivement.

## Mission
Comparateur : attributs normalisés alignés par offre, score pondéré configurable, verdict lisible avec tie-breaker (fraîcheur + fit).

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/offer_compare.py          # compare_offers(), DecisionMatrix, normalize_attr()
tests/test_offer_compare.py
tests/fixtures/offers_compare_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class OfferRow:
    offer_id: str
    attrs: dict[str, str | int | float | None]   # normalisés

@dataclass
class CompareVerdict:
    matrix: dict[str, dict[str, object]]      # attr -> offer -> valeur
    weighted_scores: dict[str, float]
    ranking: list[str]                         # offer_ids, best first
    tie_breaker_used: bool
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Attribut manquant → None explicite (jamais 0 par défaut) et tolérance dans le score.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-026-offer_compare.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-026-offer-compare` (jamais main).
