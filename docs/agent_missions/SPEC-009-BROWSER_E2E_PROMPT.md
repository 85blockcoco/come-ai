# MISSION SPEC KIT — SPEC-009 : Browser E2E Tests Career

> **Priorité : P1** — Après SPEC-007 (CI/CD). Worktree dédié, Playwright.

---

## Contexte

Les tests Python sont nombreux mais il faut prouver que l'utilisateur peut **réellement** accomplir le parcours complet dans le navigateur.

---

## Objectif

Créer la suite **Playwright** complète pour les 4 parcours incontournables, avec fixtures synthétiques, FastAPI isolé, captures d'échec, rapport HTML.

---

## Structure à créer

```
tests/e2e/
├── conftest.py
├── test_offer_to_kit.py          # Parcours 1
├── test_profile_incomplete.py    # Parcours 2
├── test_anti_invention.py        # Parcours 3
├── test_no_auto_apply.py         # Parcours 4
├── fixtures/
│   ├── offers/
│   │   ├── goldman_mna.json
│   │   ├── jpm_ibd.json
│   │   └── ms_equity_research.json
│   └── profiles/
│       ├── senior_analyst.yaml
│       └── junior_mna.yaml
├── pages/
│   ├── base.py
│   ├── offer_list.py
│   ├── offer_detail.py
│   ├── prep_wizard.py
│   └── pipeline.py
└── utils.py
```

---

## 4 Parcours obligatoires

### 1. `test_offer_to_kit` — Offre → Kit complet

```python
async def test_offer_to_kit(page, app):
    # 1. Importer offre (upload JSON ou URL)
    # 2. Ouvrir détail offre
    # 3. Lancer préparation
    # 4. Consulter variante recommandée
    # 5. Changer manuellement de variante
    # 6. Examiner écarts (couverture, preuves)
    # 7. Générer kit
    # 8. Télécharger 3 fichiers (CV, lettre, fiche)
    # 9. Retrouver candidature dans pipeline
    # Assertions: fichiers existent, pipeline mis à jour
```

### 2. `test_profile_incomplete` — Profil incomplet → Preuve → Couverture

```python
async def test_profile_incomplete(page, app):
    # 1. Profil incomplet (ex: pas de modélisation)
    # 2. Analyser offre exigeant modélisation
    # 3. Constater preuves manquantes (to_verify)
    # 4. Ajouter preuve (expérience M&A)
    # 5. Relancer analyse
    # 6. Constater amélioration couverture (ex: 65% → 85%)
    # Assertions: couverture améliorée, preuve liée
```

### 3. `test_anti_invention` — Protection anti-invention

```python
async def test_anti_invention(page, app):
    # 1. Profil SANS compétence modélisation
    # 2. Offre exigeant modélisation
    # 3. Générer kit
    # 4. Vérifier: JAMAIS affirmation "modélisation" dans CV/lettre
    # 5. Vérifier: placeholder "À vérifier: modélisation" présent
    # 6. Vérifier: avertissement "Aucune preuve" visible
    # Assertions: zéro invention, placeholder/avertissement présents
```

### 4. `test_no_auto_apply` — Zéro envoi automatique

```python
async def test_no_auto_apply(page, app):
    # 1. Parcours complet jusqu'au kit généré
    # 2. Vérifier AUCUNE action UI/API:
    #    - n'envoie formulaire candidature
    #    - ne contacte recruteur (email, LinkedIn, etc.)
    #    - ne téléverse doc vers site externe
    #    - ne crée communication externe sans consentement
    # 3. Mock network requests → assert 0 appels externes non consentis
```

---

## Infrastructure

### `conftest.py` — Fixtures

```python
@pytest.fixture(scope="session")
def app():
    # Lance FastAPI temporaire sur port aléatoire
    # Base SQLite en mémoire
    # Données synthétiques uniquement
    yield base_url

@pytest.fixture
def page(app):
    browser = await playwright.chromium.launch()
    context = await browser.new_context()
    page = await context.new_page()
    yield page
    await context.close()
```

### Capture d'échec

```python
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if call.when == "call" and outcome.excinfo:
        page = item.funcargs.get("page")
        if page:
            await page.screenshot(path=f"e2e_failure_{item.name}.png", full_page=True)
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/e2e/ --tb=short --html=e2e-report.html
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] 4 tests E2E passent (Playwright)
- [ ] FastAPI temporaire isolé, SQLite mémoire
- [ ] Fixtures 100% synthétiques
- [ ] Captures d'écran en cas d'échec
- [ ] Rapport HTML généré (`e2e-report.html`)
- [ ] Zéro appel réseau non consenti dans test_no_auto_apply
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-009-BROWSER_E2E.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-009-browser-e2e`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.