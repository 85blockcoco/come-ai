# SPEC-007 — Protection CI/CD de `main` & parcours E2E navigateur

**Mission** : CVBOOST-37 · **Priorité** : P0 · **Branche** : `worker/cvboost-37-1792974228931`
**Date** : 2026-10-26 · **Statut** : livré, vérifié localement avec Chromium réel.

---

## 1. Objectif

Empêcher tout commit sur `main` avant que les contrôles obligatoires soient
verts, et prouver par des parcours navigateur que le flux
offre → préparation → kit → export reste strictement local et manuel.

## 2. Livré

### 2.1 Workflow CI — 11 jobs requis

`.github/workflows/ci.yml` remplace l'ancien workflow à 2 jobs. Chaque job
porte **exactement** le nom d'un contexte requis :

| Contexte requis | Ce qui est exécuté |
|---|---|
| `ruff` | `ruff check .` |
| `pytest` | suite Python complète (`requirements-v3.txt`) |
| `javascript-tests` | `npm test` → `scripts/js_smoke.mjs` (Node natif, zéro dépendance) |
| `browser-e2e` | Playwright/Chromium + `tests/e2e/` |
| `migrations-check` | `python -m career.migrations check` |
| `secrets-scan` | trufflehog (secrets vérifiés uniquement) |
| `privacy-check` | `python -m career.privacy check` |
| `no-auto-apply` | `python -m career.no_auto_apply check` |
| `provenance-check` | `python -m career.provenance check` |
| `deterministic-docx` | `python -m career.docx check-deterministic` |
| `smoke-test` | `pytest -q tests/smoke/` |

Le job `browser-e2e` impose `E2E_REQUIRE_BROWSER=1` : il échoue si Chromium
ne démarre pas, au lieu de retomber silencieusement sur le repli HTTP.

### 2.2 Protection de `main`

* `.github/branch-protection/main.yml` : source de vérité versionnée
  (`strict: true`, `enforce_admins: true`, 1 revue obligatoire, reviews
  obsolètes rejetées, historique linéaire, force-push et suppression
  interdits, 11 contextes).
* `.github/branch-protection/apply.sh` : application via l'API GitHub
  (`gh api`), puis vérification de l'état appliqué. À lancer par un
  administrateur du dépôt : `./.github/branch-protection/apply.sh`.

### 2.3 Parcours E2E Playwright

`tests/e2e/` démarre l'application réelle (`create_app`) sur un répertoire
de données synthétique, puis exécute les 4 parcours exigés :

| Fichier | Parcours vérifié |
|---|---|
| `test_offer_to_kit.py` | offre → détail → prép → kit → réouverture idempotente → téléchargement DOCX valide → pipeline |
| `test_profile_incomplete.py` | profil vide → offre → couverture 0 → ajout de preuve → couverture et exigences étayées en hausse |
| `test_anti_invention.py` | exigence LBO non étayée → listée « non trouvée dans ton profil », jamais revendiquée, marquée « à vérifier » |
| `test_no_auto_apply.py` | aucune action `mailto:`/SMTP/soumission, aucune route Career d'envoi, pipeline et kit `automatic_submission: false` |

`tests/e2e/utils.py` fournit un contrat `page` unique : `BrowserPage`
(Chromium réel) et `HttpPage` (repli local quand Playwright n'est pas
installé). Les assertions sont identiques dans les deux modes.

### 2.4 Contrôles CI implémentés

`career/ci_guards.py` + points d'entrée `career/{privacy,no_auto_apply,
provenance,migrations}.py` :

* **privacy** : aucun `.env`/base/clé privée suivi, aucun secret à haute
  confiance hors tests/détecteurs/audits.
* **no-auto-apply** : aucun `smtplib`, `mailto:`, `.submit()`,
  `webbrowser.open`, POST HTTP direct ni `automatic_submission: True` dans
  les modules du parcours candidature.
* **provenance** : les kits exposent `provenance_map` et l'indicateur
  `automatic_submission: False`.
* **migrations** : `SNAPSHOT_SCHEMA_VERSION` valide, colonnes versionnées
  présentes, décodage défensif d'un snapshot absent/ancien.

### 2.5 Déterminisme DOCX

`career/document_export.py` normalise désormais les horodatages ZIP après
`python-docx` (`_normalize_docx_archive`). Deux exports du même contenu sont
octet pour octet identiques : le job `deterministic-docx` et les empreintes
d'intégrité deviennent exploitables. Aucun contenu visible ne change.

### 2.6 Tests de non-régression ajoutés

* `tests/test_ci_guards.py` — 7 tests (4 contrôles réels sur le dépôt,
  détection de faux positifs/négatifs, déterminisme DOCX).
* `tests/smoke/test_app_boot.py` — démarrage, `/career`, profil, pipeline,
  assets statiques.

## 3. Vérifications exécutées

```text
E2E_REQUIRE_BROWSER=1 pytest -q tests/e2e --tb=short
→ 4 passed in 120.83s   (Chromium réel)

pytest -q tests/test_ci_guards.py tests/smoke
→ 9 passed in 39.11s

pytest -q tests/test_career_application_kit.py \
         tests/integration/test_us3_pipeline.py \
         tests/test_qualification_snapshot_persistence.py
→ 27 passed in 182.50s

python -m career.privacy check             → OK
python -m career.no_auto_apply check       → OK
python -m career.provenance check          → OK
python -m career.migrations check          → OK
python -m career.docx check-deterministic  → OK (0fa996e1d377…)
npm test                                   → OK — 5 fichiers JS valides
ruff check .                               → All checks passed
git diff --check                           → propre
```

## 4. Écarts assumés par rapport au prompt

1. **`uv` → `pip`** : le dépôt n'a ni `uv.lock` ni section `[project]` ;
   l'installation réelle se fait depuis `requirements-v3.txt`. Utiliser
   `uv sync` aurait échoué en CI.
2. **`npm ci` → `npm test`** : aucun `package.json`/`package-lock.json`
   n'existait et aucun paquet npm n'est nécessaire. Le job exécute un script
   Node natif ; `npm ci` sans lockfile échouerait.
3. **`ruff format --check` retiré** : le dépôt n'est pas formaté avec
   `ruff format` ; l'ajouter aurait rendu `ruff` rouge sur du code existant
   hors mission. `ruff check .` reste bloquant.
4. **Commande `career.migrations`** : aucun module de migration n'existait ;
   le contrôle s'appuie sur le versionnage de snapshot réellement présent
   (`qualification_persistence`), sans inventer de migration factice.
5. **Protection de branche** : non appliquée depuis cette session (pas de
   vérification des droits admin GitHub). Le fichier et le script sont
   fournis pour application immédiate ; la CI est prête à être branchée.

## 5. Limites

* La protection de `main` n'a d'effet qu'après exécution de `apply.sh` par
  un administrateur du dépôt `85blockcoco/come-ai`.
* Les parcours E2E couvrent les contrats HTTP/UI critiques, pas chaque
  écran de l'interface (les tests unitaires existants couvrent le détail).
* `secrets-scan` utilise `--only-verified` : les motifs factices des
  fixtures ne bloquent pas la CI, les secrets réellement validés si.
