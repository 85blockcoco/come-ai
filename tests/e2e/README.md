# Tests E2E navigateur Career (SPEC-009)

Suite Playwright des quatre parcours incontournables de l'espace Career.
Chaque test démarre un serveur FastAPI réel, isolé, dans un sous-processus :

- port aléatoire sur `127.0.0.1` ;
- `base_dir` temporaire (SQLite, exports, mémoire) — aucune donnée réelle ;
- fixtures d'offres et de profils **synthétiques** uniquement ;
- clés IA retirées de l'environnement du serveur ;
- toute requête navigateur hors origine locale est avortée et journalisée.

## Lancer

```bash
# Interpréteur avec Playwright + Chromium installés
python -m pip install playwright pytest-playwright
playwright install chromium

python -m pytest -q tests/e2e
```

Le rapport HTML est écrit dans `tests/e2e/artifacts/report.html` ; une capture
pleine page est enregistrée dans ce même dossier à chaque échec
(`FAILED-<test>.png`). Ces artefacts sont ignorés par git.

## Parcours couverts

| Fichier | Parcours |
|---|---|
| `test_offer_to_kit.py` | Import d'offre → analyse locale → variante recommandée → changement manuel de variante → kit → 4 exports (CV/lettre × Word/PDF) + fiche de préparation côté serveur → pipeline |
| `test_profile_incomplete.py` | Profil incomplet → exigence non étayée → ajout de preuve dans Mon profil → couverture CV en hausse et preuve liée |
| `test_anti_invention.py` | Profil sans modélisation + offre l'exigeant → aucun document n'affirme la compétence ; placeholders et avertissements présents (adversarial) |
| `test_no_auto_apply.py` | Parcours complet → zéro requête externe, zéro écriture distante, aucun contrôle d'envoi, API `automated_submission=false` (adversarial) |

## Structure

```
tests/e2e/
├── conftest.py        # serveur isolé, navigateur, garde réseau, rapport HTML
├── server.py          # lance FastAPI sur un base_dir temporaire
├── utils.py           # chargement fixtures, couverture, détection d'invention
├── pages/             # Page Objects (base, offre, détail, wizard, pipeline, profil)
├── fixtures/
│   ├── offers/        # offres synthétiques (example.test)
│   └── profiles/      # profils YAML synthétiques
└── test_*.py
```

## Limites connues

- Chromium headless uniquement (pas de matrice Firefox/WebKit).
- Le `GET /api/career/applications/{id}/kit` ne renvoie pas les artefacts ciblés ;
  l'interface les affiche uniquement juste après la création. Le test vérifie
  donc la persistance de la variante et l'existence des trois fichiers via une
  réouverture idempotente de l'API.
- La fiche de préparation (`prep_sheet.md`) est générée côté serveur mais n'a
  pas de route de téléchargement navigateur ; elle est vérifiée sur disque.
- Sans Playwright dans l'interpréteur, les tests sont marqués *skipped* avec un
  message explicite au lieu d'échouer.
