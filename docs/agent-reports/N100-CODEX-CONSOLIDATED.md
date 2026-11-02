# N100 — Candidate consolidée Codex

Date : 2026-11-02
Base : `origin/agent/n100-carrier-20261101` réconcilié au commit OpenCode `93fde22a47a18438174569608f0c86ed9a08f503`.

## Contenu intégré

- U2 : routes shortlist, urgence et export à cible serveur.
- U3 : préremplissage ATS, checklist et aperçu du dossier.
- U4 : écran de lettre multilingue, contrôle factuel, approbation et export local.
- U5 : labels accessibles, focus visible, skeletons et responsive Career.
- U7 : routes académiques locales à opérations explicitement autorisées.
- Durcissement : le booléen client `approved` ne peut pas contourner le registre d'approbation ; le chemin d'export de lettre est imposé côté serveur.
- Recette E2E OpenCode J01 sur dix offres synthétiques conservée depuis la base.
- Réconciliation du dernier U2 OpenCode sans doublon de routes ni régression U3/U4.
- Approbations de lettres liées au contenu exact relu (empreinte SHA-256), export et téléchargement local contrôlés.
- Shortlist persistante normalisée (date limite, score et localisation) et export CSV protégé contre l'injection de formules.
- Routes académiques bornées par opérations autorisées, modèles stricts et limites numériques.

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

Résultat : `64 passed in 20.59s`.

Également verts :

- Ruff sur tous les fichiers Python modifiés et tests ciblés ;
- `node --check desktop_static/app.js` ;
- `node --check career_static/career.js` ;
- `git diff --check`.

Après la réconciliation carrier, Ruff, les deux contrôles JavaScript et `git diff --check` sont toujours verts.

La suite complète n'a pas été exécutée. Aucun fichier personnel, secret ou fournisseur externe n'a été utilisé. Aucune candidature n'a été envoyée.

## Revue requise

- accepter ou ajuster le contrat REST U7 avant intégration définitive ;
- rejouer la commande ciblée ci-dessus après toute modification ;
- ne pas fusionner dans `main` sans décision humaine explicite.
