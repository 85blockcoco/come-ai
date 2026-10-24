# SPEC-027 — Simulateur d'entretien STAR

## Livré
- Module `career/interview_sim.py` : `InterviewQuestion`, `StarWorksheet`,
  `build_question_set()`, `self_score()`.
- Fixture synthétique `tests/fixtures/interview_offers_synthetic.json` (3 offres).
- Tests `tests/test_interview_sim.py` (14 tests, dont smoke HTTP et cas adversarial).
- Endpoints REST via `create_app()` : question-sets/questions/question_set,
  GET questions, worksheets, self-score, score.

## Contrats
- `InterviewQuestion(kind, question, evidence_needed, ...)` avec
  `kind ∈ {behavior, technical, motivation, company}`.
- `StarWorksheet(question_id, situation, task, action, result, completeness)`
  avec `completeness` calculé (0–1, 4 champs STAR).
- `build_question_set(offer, *, seed=None, count=12, ...)` déterministe,
  ≥ 12 questions, les 4 kinds présents (même après shuffle).
- `self_score(...)` renvoie une valeur numérique 0–1 exposant aussi les détails
  (completeness, champs remplis, métrique, preuves).

## Décisions
- Génération déterministe avec `seed` configurable (défaut 0), `random.Random`.
- Questions basées sur les mots-clés et le secteur de l'offre (aucun LLM).
- Aucune donnée réelle ; fixtures synthétiques uniquement.
- `self_score` aligné sur la complétude STAR (bonus métrique/preuves non
  inflatoire, score ≤ 1).
- Endpoints exposés sans casser `SCHEMA_VERSION` (router uniquement).

## Validation
- `pytest -q tests/test_interview_sim.py` → 14 passed
- `pytest -q` → 1438 passed, 1 skipped
- `ruff check .` → All checks passed
- `git diff --check` → clean

## Limites
- Questions basées sur des gabarits mots-clés (pas de génération LLM).
- Score aligné sur la complétude STAR (pas d'évaluation sémantique).
- Langue des gabarits : français (l'offre peut être multilingue, les questions
  restent en français).