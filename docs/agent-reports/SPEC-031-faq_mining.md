# SPEC-031 — Minage FAQ sectorielle des offres

## Livré

- Module `career/faq_mining.py` : `SectorFaq`, `mine_sector_faq()`, `cluster_intents()`, `expected_questions()`.
- Fixture synthétique `tests/fixtures/faq_offers_synthetic.json`.
- Tests `tests/test_faq_mining.py` (cas limites + adversarial).
- Endpoints REST : `POST/GET /api/career/faq-mine` via `create_app()`.
- Capability `faq_mining` exposée dans `/api/career/health`.

## Décisions

- Clustering déterministe par secteur/famille de poste (`sector`, `job_family`, ...).
- Termes = tokens normalisés des attentes, fréquences triées par fréquence puis terme.
- Questions probables générées à partir des termes dominants + questions génériques sectorielles.
- Réponses issues des preuves du profil (snippets contenant le terme).

## Limites

- Tokenisation lexicale simple (pas de NLP avancé).
- Pas d'appel réseau ni de modèle.
- `top_n` par défaut = 10 termes.