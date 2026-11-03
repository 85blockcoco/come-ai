# MISSION SPEC KIT — SPEC-007 : CI/CD GitHub Protection & Browser E2E

> **Priorité : P0** — Module transverse, worktree dédié. Doit être fait AVANT Spec-009 (E2E tests).

---

## Contexte

Le push a affiché : "Bypassed rule violations: 2 of 2 required status checks are expected". Main peut recevoir un commit avant que les contrôles obligatoires soient verts.

---

## Objectif

Sécuriser **complètement** la branche `main` : branch protection rules, required status checks, PR obligatoire, merge seulement si tout vert. Ajouter les tests navigateur E2E dans la CI.

---

## Travaux à faire

### 1. Branch Protection Rules (via GitHub API ou manuel documenté)

```yaml
# .github/branch-protection/main.yml (documentation)
protection_rules:
  - required_status_checks:
      strict: true
      contexts:
        - "ruff"
        - "pytest"
        - "javascript-tests"
        - "browser-e2e"
        - "migrations-check"
        - "secrets-scan"
        - "privacy-check"
        - "no-auto-apply"
        - "provenance-check"
        - "deterministic-docx"
        - "smoke-test"
    enforce_admins: true
  - required_pull_request_reviews:
      required_approving_review_count: 1
      dismiss_stale_reviews: true
      require_code_owner_reviews: false
  - restrictions: null
  - allow_force_pushes: false
  - allow_deletions: false
  - required_linear_history: true
```

### 2. GitHub Actions Workflow (`.github/ci.yml`)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  test-python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras
      - run: uv run pytest -q --tb=short

  test-javascript:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: '20'}
      - run: npm ci
      - run: npm test

  browser-e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - uses: actions/setup-node@v4
      - run: uv sync --all-extras
      - run: uv run playwright install --with-deps chromium
      - run: uv run pytest -q tests/e2e/ --tb=short

  migrations-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run python -m career.migrations check

  secrets-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: trufflesecurity/trufflehog@v3
        with: {path: ., fail: true}

  privacy-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run python -m career.privacy check

  no-auto-apply:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run python -m career.no_auto_apply check

  provenance-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run python -m career.provenance check

  deterministic-docx:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run python -m career.docx check-deterministic

  smoke-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv run pytest -q tests/smoke/ --tb=short
```

### 3. Tests navigateur E2E (Playwright)

```
tests/e2e/
├── conftest.py
├── test_offer_to_kit.py          # Parcours 1: offre → kit → export
├── test_profile_incomplete.py    # Parcours 2: profil incomplet → preuve → couverture
├── test_anti_invention.py        # Parcours 3: anti-invention
├── test_no_auto_apply.py         # Parcours 4: zéro envoi auto
├── fixtures/
│   ├── offers/
│   └── profiles/
└── utils.py
```

### Scénarios obligatoires

| Parcours | Description |
|----------|-------------|
| `test_offer_to_kit` | Importer offre → détail → prépa → variante → écarts → kit → download → pipeline |
| `test_profile_incomplete` | Profil incomplet → analyser offre → preuves manquantes → ajouter preuve → couverture ↑ |
| `test_anti_invention` | Profil sans modélisation → offre exige modélisation → kit → vérifier placeholder/avertissement |
| `test_no_auto_apply` | Aucune action UI/API n'envoie formulaire, contacte recruteur, téléverse doc, crée comm externe |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/e2e/ --tb=short
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Branch protection rules appliquées (ou documentées si pas admin)
- [ ] Workflow CI avec 11 jobs requis
- [ ] 4 tests E2E Playwright passent
- [ ] Ruff, pytest, js tests, migrations, secrets, privacy, no-auto-apply, provenance, deterministic-docx, smoke-test tous requis
- [ ] `enforce_admins: true`
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-007-CI_CD_PROTECTION.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-007-ci-cd-protection`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.