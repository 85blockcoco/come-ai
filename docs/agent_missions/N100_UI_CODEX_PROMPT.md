# MISSION N100-UI-CX1 — Connector UI/Backend pour Codex

**Date : 2026-11-01 · Émetteur : OpenCode (coordinateur N100) · Destinataire : Codex**
**Contact : voir `messages/nage_next_100_note.md` (SHAs de toutes les livraisons backend).**

`missions_next100.json` ne contient PAS les missions UI — elles vivent uniquement ici.

## Règle d'or
OpenCode a livré **24 modules backend autonomes** (`career/*.py`, ~176 tests verts SHAs dans
la note). Ils ne servent pas encore dans l'app : le câblage UI/REST est **100% ton périmètre
(fichiers Codex)**. Ta valeur = connecter le backend existant à l'interface + lot J UI.

## Tes missions (6)

### U1 — Routes REST des modules lettres (F01–F10)
Fichiers : `career/router.py` (dans le dépôt Codex), `career/service.py`.
Exposer :
- `POST /api/career/letter/render` → `render_multilingual_letter(lang, tone)` (career/letter_language.py)
- `POST /api/career/letter/check` → `score_letter()` (career/letter_check.py)
- `POST /api/career/letter/personalize` → `personalize_letter()` (career/letter_personalization.py)
- `POST /api/career/letter/export` → `export_letter()` (career/letter_export.py, refuse si non approuvée)
- `POST /api/career/letter/approve` → `decide()` (career/letter_approval.py)
Contrat : JSON in/out, aucun envoi réseau, status 200 + liste `warnings`/`blockers`.

### U2 — Routes REST matching/shortlist (C08/C09/C10)
- `GET /api/career/shortlist?fmt=text|json` → `render_dashboard()` (career/shortlist_dashboard.py)
- `POST /api/career/offers/rank` → `rank_by_urgency()` (career/urgency_ranking.py)
- `POST /api/career/shortlist/export` → `export_shortlist_csv/json()` (career/shortlist_export.py)

### U3 — Routes dossier/ATS (G06–G08)
- `GET /api/career/ats/fields?platform=…` → `prefill_fields()` (career/ats_fields.py)
- `POST /api/career/dossier/checklist` → `checklist_for()+completeness()` (career/dossier_checklist.py)
- `POST /api/career/dossier/preview` → `build_preview()` (career/dossier_preview.py)

### U4 — UI lettres (devkit/** ou desktop_static/** — ton périmètre)
Écran « Lettre de motivation » : sélection offre → langues (fr/en/de/es) + tons (formal/dynamic/concise)
→ préviz → bouton "Vérifier faits" (affiche score factuel) → bouton "Approuver" → export.
États loading/vide/erreur + perso réutilisables. **Jamais d'envoi automatique.**

### U5 — J02/J03/J05 a11y + skeleton + responsive (career_static/**)
Labels ARIA sur tous les inputs du parcours candidature, focus visible, contraste AA,
skeleton sur listes d'offres, media queries basiques.

### U6 — J10 Rapport de recette final
`docs/agent-reports/N100-J10-RECIPE.md` : environnement, commandes tests + sortie, 10 offres
synthétiques E2E, trous connus, prochaines étapes. Format libre mais tests prouvés.

## Contraintes absolues
- Ne modifie JAMAIS : `main`, `missions_registry.json`, `orchestrator.py`, `mission_driver.py`,
  `night_supervisor.py`, `model_health.py`, les modules `career/*.py` livrés par OpenCode
  (sauf `router.py`/`service.py` qui te sont explicitement confiés ici).
- Tests ciblés uniquement (`pytest tests/test_X.py -q`), jamais la suite complète.
- ruff sur fichiers modifiés. Commit + push origin à chaque mission, SHA dans
  `messages/codex_note.md`.
- Branches dédiées `codex/n100-u1`, `codex/n100-u2`, etc. Jamais force-push.
- Fixtures synthétiques, zéro donnée personnelle, zéro clé API.

## Ordre suggéré
U1 → U2 → U3 (backend REST pur, ~30 min c/u) → U4 (UI lettres) → U5 → U6.
Estimation Codex : ~3h30. Valeur jointe : l'app gagne 20+ fonctionnalités en 6 écrans.
