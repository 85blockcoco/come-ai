# SPEC-031 — Minage FAQ sectorielle des offres

## Livré
- Module `career/faq_mining.py` : `SectorFaq`, `cluster_intents()`, `mine_sector_faq()`,
  `expected_questions()`.
- Tests `tests/test_faq_mining.py` (13 cas).
- Fixture synthétique `tests/fixtures/faq_offers_synthetic.json`.

## Décisions
- Clustering déterministe par secteur/famille (aucun appel réseau).
- Top terms par fréquence (Counter), questions générées depuis les termes dominants.
- Aucune donnée réelle, aucune nouvelle dépendance.

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests).
- Clustering simple par champ `sector`/`family`/`category` (pas de NLP avancé).
- Profile answers = intersection des termes profil avec les top terms.

## Validation
- `pytest -q tests/test_faq_mining.py` → 13 passed
- `ruff check career/faq_mining.py tests/test_faq_mining.py` → All checks passed