# SPEC-026 — Comparateur d'offres côte à côte

## Livré

- Module `career/offer_compare.py` : `OfferRow`, `CompareVerdict`, `DecisionMatrix`, `compare_offers`, `normalize_attr`.
- Attributs normalisés alignés dans `matrix` (attr → offre → valeur), attribut manquant → `None`.
- Score pondéré configurable (`weights`), attributs non listés pèsent 0 ; pondération renormalisée sur les attributs présents (tolérance aux manquants).
- Tie-breaker fraîcheur puis adéquation (`tie_breaker_used`).
- Endpoint REST `POST /api/career/offers/compare` (alias `/api/career/offer-compare`) via `create_app()`.
- Fixture synthétique `tests/fixtures/offers_compare_synthetic.json`.
- Tests `tests/test_offer_compare.py` (10 cas dont adversarial).

## Limites

- Heuristique simple pour attributs "coût-like" (plus bas = mieux) ; surcharge possible via `higher_is_better`.
- Pas de persistance ni d'UI dédiée dans cette mission.
