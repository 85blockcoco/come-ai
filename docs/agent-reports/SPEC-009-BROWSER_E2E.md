# SPEC-009 — Browser E2E Tests Career

## Livré
- Suite Playwright dans `tests/e2e/` : conftest, 4 parcours, fixtures, page objects, utils.
- FastAPI isolé sur port aléatoire, SQLite en mémoire via `CareerService(base_dir)`.
- Captures d'écran en cas d'échec via hook `pytest_runtest_makereport`.
- Rapport HTML possible via `--html=e2e-report.html`.

## Tests
- `test_offer_to_kit` : profil + offre → préparation → variante → kit → artefacts → pipeline.
- `test_profile_incomplete` : profil incomplet → couverture → ajout de preuve → amélioration.
- `test_anti_invention` : aucune invention de "modélisation", placeholders et avertissement "Aucune preuve".
- `test_no_auto_apply` : aucun appel réseau externe, `automatic_submission is False`.

## Validation
- `pytest -q tests/e2e/` → 4 passed
- `ruff check tests/e2e` → All checks passed
- `git diff --check` → clean