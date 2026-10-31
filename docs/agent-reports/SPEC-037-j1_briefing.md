# SPEC-037 — Briefing J-1 veille d'entretien

## Livré
- `career/j1_briefing.py` : `BriefingDoc`, `build_j1_briefing()`, `to_dict()`.
- Tests `tests/test_j1_briefing.py` (8 cas).

## Décisions
- Agrégateur déterministe, aucune dépendance externe.
- STAR worksheets filtrés par seuil de complétude (défaut 0.8).
- Sections incomplètes marquées explicitement (jamais masquées).
- Aucune donnée réelle.

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests).
- Pas de génération automatique des questions (consomme SPEC-031).
- Pas de checklist admin automatique (consomme SPEC-028).

## Validation
- `pytest -q tests/test_j1_briefing.py` → 8 passed
- `ruff check career/j1_briefing.py tests/test_j1_briefing.py` → All checks passed