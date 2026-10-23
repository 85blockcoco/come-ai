# SPEC-027 — Simulateur d'entretien STAR

## Livré
- Module `career/interview_sim.py` : `InterviewQuestion`, `StarWorksheet`, `build_question_set()`, `self_score()`.
- Fixture synthétique `tests/fixtures/interview_offers_synthetic.json`.
- Tests `tests/test_interview_sim.py`.
- Endpoints REST via `create_app()` (question-sets, worksheets, self-score).

## Décisions
- Génération déterministe avec `seed` configurable (défaut 0).
- Au moins 12 questions par offre, 4 kinds présents.
- `self_score` renvoie une valeur numérique hybride (float + détails).
- Aucun appel LLM, aucune donnée réelle.

## Limites
- Questions basées sur mots-clés simples de l'offre.
- Score aligné sur la complétude STAR.
- Deux tests pré-existants échouent en présence de `GEMINI_API_KEY` (environnement), non liés à ce module.