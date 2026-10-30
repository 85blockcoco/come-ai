# SPEC-009 — Tests E2E navigateur Career

**Mission CVBOOST-39** · branche `worker/cvboost-39-1793359909653` ·
worktree `AI-Excel-Agent-worker-cvboost-39-1793359909653`

**Livraison** : commit `0773c79`, poussé sur `origin/worker/cvboost-39-1793359909653`
(vérification flotte) et `origin/agent/spec-009-browser-e2e` (nom de branche
demandé par la mission).

## Livré

Suite Playwright complète pour les quatre parcours incontournables, avec
Page Objects, fixtures synthétiques, serveur FastAPI isolé, garde réseau,
captures d'échec et rapport HTML autonome.

| Livrable | Fichier |
|---|---|
| Parcours offre → kit | `tests/e2e/test_offer_to_kit.py` |
| Profil incomplet → preuve → couverture | `tests/e2e/test_profile_incomplete.py` |
| Anti-invention (adversarial) | `tests/e2e/test_anti_invention.py` |
| Zéro envoi automatique (adversarial) | `tests/e2e/test_no_auto_apply.py` |
| Infrastructure | `tests/e2e/conftest.py`, `tests/e2e/server.py`, `tests/e2e/utils.py` |
| Page Objects | `tests/e2e/pages/` (base, offre, détail, wizard, pipeline, profil) |
| Fixtures | `tests/e2e/fixtures/offers/*.json`, `tests/e2e/fixtures/profiles/*.yaml` |
| Mode d'emploi | `tests/e2e/README.md` |

## Vérifications exécutées

```text
python -m pytest -q tests/e2e
→ 5 passed

python -m pytest -q tests/e2e tests/test_career_application_kit.py \
    tests/test_apply_kit.py tests/test_career_application_prep_regressions.py
→ 28 passed

python -m ruff check tests/e2e
→ All checks passed
```

Exécuté avec l'interpréteur du driver de missions
(`/Library/Frameworks/Python.framework/Versions/3.12/.../Python`, celui qui
rejoue les tests à la vérification) **et** avec `.venv/bin/python` : mêmes
résultats.

## Décisions

1. **Serveur réel, base temporaire.** Chaque test lance `create_app(base_dir=tmp)`
   via Uvicorn dans un sous-processus, sur un port libre. Aucune donnée
   utilisateur, aucun appel aux boards publics.
2. **Isolation réseau.** `context.route("**/*")` n'autorise que l'origine
   locale ; les tentatives externes sont avortées et collectées. C'est la
   preuve du parcours « zéro envoi », pas seulement une absence de bouton.
3. **Fixtures synthétiques.** Entreprises en « Démonstration », URLs
   `example.test`, mention explicite « synthétique » ; `assert_synthetic_offer`
   échoue si une fixture ressemble à une donnée réelle.
4. **Anti-invention contextuelle.** Un terme métier est toléré uniquement s'il
   est présenté comme une lacune (« à vérifier », « à compléter », placeholder)
   ou s'il ne fait que citer l'offre (« Votre offre mentionne… »). Toute
   appropriation (« je maîtrise… ») reste une violation.
5. **Rapport et captures sans dépendance.** Hooks pytest maison : capture
   pleine page sur échec, rapport HTML autonome dans
   `tests/e2e/artifacts/` (ignoré par git). Pas de `pytest-html` requis.
6. **Dégradation propre.** Si Playwright ou Chromium manque, les tests sont
   *skipped* avec la commande d'installation, jamais de faux vert.

## Limites et points ouverts

- **Artefacts du kit non exposés par le GET.** `GET /applications/{id}/kit`
  ne renvoie pas `artifacts` : après re-rendu, l'interface ne réaffiche pas
  « Variante générée ». Le test vérifie la variante persistée (`draft.variant`)
  et les trois artefacts (`cv`, `cover_letter`, `prep_sheet`) via un appel
  idempotent au POST, puis vérifie leur présence sur disque. Un correctif
  produit consisterait à inclure `artifacts` dans le GET et à ajouter une route
  de téléchargement de la fiche de préparation.
- **Pas de route de téléchargement pour `prep_sheet.md`.** Les 4 exports
  téléchargeables (CV et lettre en DOCX/PDF) sont testés par de vrais
  téléchargements navigateur ; la fiche est validée sur disque.
- **Chromium uniquement.** Aucune matrice Firefox/WebKit.
- **Pas de câblage CI.** La mission ne modifiait pas `.github/` ; la suite est
  prête pour un job dédié (`playwright install chromium` puis
  `pytest tests/e2e`).
- **Suite complète non relancée.** Conformément à `COORDINATION.md` (ne pas
  lancer la suite entière pendant que la flotte tourne), la vérification s'est
  limitée à `tests/e2e` et aux tests Career directement liés au kit. Aucun code
  applicatif n'a été modifié : le risque de régression est nul hors nouveaux
  fichiers de test.
- **Dépendance d'environnement installée hors dépôt.** `playwright==1.64.1` et
  `pytest-playwright==0.10.0` ont été installés en *user site* pour
  l'interpréteur du driver (Chromium déjà en cache) afin que la vérification
  automatique exécute réellement le navigateur.
