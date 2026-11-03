# N100 — Candidate consolidée Codex

Date : 2026-11-01
Base : `origin/agent/n100-carrier-20261101` au commit `99a20691499f71608fd58bbfa7e9594223163ddb`.

## Contenu intégré

- U2 : routes shortlist, urgence et export à cible serveur.
- U3 : préremplissage ATS, checklist et aperçu du dossier.
- U4 : écran de lettre multilingue, contrôle factuel, approbation et export local.
- U5 : labels accessibles, focus visible, skeletons et responsive Career.
- U7 : routes académiques locales à opérations explicitement autorisées.
- Durcissement : le booléen client `approved` ne peut pas contourner le registre d'approbation ; le chemin d'export de lettre est imposé côté serveur.
- Recette E2E OpenCode J01 sur dix offres synthétiques conservée depuis la base.

## Validation réellement exécutée

```bash
.venv/bin/python -m pytest -q \
  tests/test_e2e_local_pipeline.py \
  tests/test_career_letter_routes.py \
  tests/test_career_shortlist_routes.py \
  tests/test_career_dossier_routes.py \
  tests/test_n100_letter_ui.py \
  tests/test_n100_career_accessibility.py \
  tests/test_academics_routes.py \
  tests/test_academics_integration.py
```

Résultat : `34 passed in 15.14s`.

Également verts :

- Ruff sur tous les fichiers Python modifiés et tests ciblés ;
- `node --check desktop_static/app.js` ;
- `node --check career_static/career.js` ;
- `git diff --check`.

La suite complète n'a pas été exécutée. Aucun fichier personnel, secret ou fournisseur externe n'a été utilisé. Aucune candidature n'a été envoyée.

## Revue requise

- accepter ou ajuster le contrat REST U7 avant intégration définitive ;
- rejouer la commande ciblée ci-dessus après toute modification ;
- ne pas fusionner dans `main` sans décision humaine explicite.
