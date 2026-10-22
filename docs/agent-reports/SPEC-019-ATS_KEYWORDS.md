# SPEC-019 — ATS Keywords Intelligence

## Livré

Modules :
- `career/keyword_extract.py` — extraction déterministe + normalisation + déduplication, pondération.
- `career/keyword_scorer.py` — formule de poids, classification must/nice/implicit, couverture, gaps.
- `career/keyword_arena.py` — consensus multi-IA local, garde anti-hallucination.
- `career/keyword_report.py` — rapport JSON/HTML.
- `career/keywords/` — package de commodité.
- `tests/test_keywords.py` — tests extraction, adversarial, déterminisme.

## Contrats

- `Keyword` et `KeywordProfile` dataclasses conformes au prompt.
- `weight = 0.5*freq_offer + 0.2*is_in_title_or_requirements + 0.2*web_stack_confirm + 0.1*jury_boost`.
- Trois niveaux : must / nice / implicit.
- Couverture et gaps calculés vs profil.

## Validation

- `ruff check .` → All checks passed
- `pytest -q tests/test_keywords.py` → 17 passed
- `git diff --check` → clean
