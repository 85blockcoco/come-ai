# SPEC-009 — Browser E2E Tests Career

> Mission CVBOOST-39 · Priorité P1 · Playwright (Chromium)

## Objectif

Prouver dans un vrai navigateur que les 4 parcours Career incontournables
fonctionnent de bout en bout, avec une application FastAPI isolée, des données
100 % synthétiques, des captures en cas d'échec et un rapport HTML autonome.

## Livrables

```
tests/e2e/
├── conftest.py                  # serveur isolé + navigateur + captures + rapport HTML
├── test_offer_to_kit.py         # Parcours 1
├── test_profile_incomplete.py   # Parcours 2
├── test_anti_invention.py       # Parcours 3
├── test_no_auto_apply.py        # Parcours 4
├── fixtures/offers/             # goldman_mna, jpm_ibd, ms_equity_research
├── fixtures/profiles/           # senior_analyst, junior_mna
├── pages/                       # base, offer_list, offer_detail, prep_wizard, pipeline
└── utils.py                     # chargement fixtures + parsing couverture/artefacts
```

Production complétée pour rendre le parcours réellement testable :

- `GET /api/career/applications/{id}/artifacts/{kind}` — téléchargement contrôlé
  des trois fichiers du kit (CV DOCX, lettre DOCX, fiche Markdown). Le chemin est
  recalculé depuis la candidature puis confiné à `output/career/kits`.
- `career_static/career.js` — les artefacts du kit sont désormais des liens de
  téléchargement réels (plus seulement des chemins affichés).
- `tests/test_career_artifact_download.py` — 3 tests de contrat pour l'endpoint :
  types MIME, `no-store`, refus d'un type inconnu, refus d'une candidature
  inconnue et tentatives de traversée de chemin (`../`, `passwd`).

## Parcours couverts

1. **Offre → Kit complet** : import d'une offre synthétique via le formulaire,
   ouverture du détail, analyse, variante recommandée, changement manuel de
   variante, écarts sourcés, génération du kit, contrôle puis téléchargement des
   3 artefacts via leurs liens (CV DOCX, lettre DOCX, fiche Markdown), présence de
   la candidature dans le pipeline.
2. **Profil incomplet → Preuve → Couverture** : profil sans modélisation,
   exigence « Modélisation financière » signalée comme non trouvée, ajout d'une
   preuve M&A synthétique, nouvelle analyse, couverture strictement améliorée.
3. **Anti-invention** : aucun affirmation de modélisation dans le CV ou la lettre ;
   placeholder « À vérifier » et avertissement « non trouvé dans ton profil » ;
   rappel explicite qu'aucun envoi n'est effectué.
4. **Zéro envoi automatique** : tous les appels réseau sont capturés ; aucun appel
   externe, aucun `mailto:`/`tel:`, aucun LinkedIn ; la candidature reste locale,
   non `submitted`, non approuvée pour envoi manuel ; aucun formulaire/bouton
   d'envoi dans l'interface du kit.

## Isolation et déterminisme

- `uvicorn` sur un port libre, thread démon, `base_dir` = `tmp_path` par test.
- SQLite, exports et kits restent dans le répertoire temporaire du test.
- Offres et profils synthétiques uniquement (`*.example.test`).
- Playwright est optionnel : si le paquet est absent, les modules E2E sont ignorés
  à la collecte au lieu de casser la suite Python.

## Captures et rapport

- `pytest_runtest_makereport` capture `tests/e2e/artifacts/e2e_failure_<test>.png`
  en cas d'échec (best effort).
- `pytest_sessionfinish` écrit `e2e-report.html` à la racine du worktree : tableau
  résultat + durée + trace des échecs, sans dépendance externe (pas de plugin HTML).

## Validation

```bash
.venv/bin/python -m pytest -q tests/e2e --tb=short
.venv/bin/python -m ruff check tests/e2e career/router.py career/service.py
git diff --check
```

Résultat de la campagne : **4 tests passés** (`e2e-report.html`).
