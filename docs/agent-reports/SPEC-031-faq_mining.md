# SPEC-031 — Minage FAQ sectorielle des offres

## Livré

- `career/faq_mining.py` : extraction déterministe des attentes par secteur/famille de poste,
  clustering d'intentions (`cluster_intents`), questions probables (`expected_questions`,
  `question_for_intent`), FAQ sectorielle (`mine_sector_faq`, `mine_all_sector_faqs`) et
  éléments de réponse issus du profil (`profile_answer_elements`).
- `tests/test_faq_mining.py` + `tests/fixtures/faq_offers_synthetic.json` : 9 tests synthétiques
  (contrat, fréquences, déterminisme, adversarial, REST).
- Endpoints REST `/api/career/faq-mine` (POST explicite, GET offres locales) via `create_app()`.
- Rapport présent.

## Décisions

- Aucun appel réseau, aucun modèle, aucune horloge : clustering par vocabulaire d'intentions versionné.
- Anti-invention : les réponses profil sont des extraits verbatim ; liste vide si aucune preuve.
- Bornes de sécurité (`MAX_OFFERS`, etc.) et validation FastAPI (`top_n`, `max_questions`).

## Limites

- Heuristique par mots-clés normalisés ; pas d'analyse sémantique.
- `sector` manquant côté GET renvoie `[]` si aucune offre locale.
- `schema_version` inchangé (7).
