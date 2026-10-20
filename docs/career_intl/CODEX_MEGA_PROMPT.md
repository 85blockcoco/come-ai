# CODEX MEGA-PROMPT — Intégration et finalisation Career

Tu es Codex. Tu travailles seul, sans réponse humaine. Base : commit a7815a7 (ou candidat d’intégration si fourni).

## Objectif
Intégrer et finaliser les briques Career pour un usage réel satisfaisant :
- Carte + tri par correspondance.
- Fiche détaillée offre par offre.
- Résumé IA structuré avec consentement cloud.
- Maximum d’infos par offre.
- Sources étendues et bornées.

## Chemins autorisés
career_static/index.html, career_static/career.js
career/application_prep.py, career/application_studio.py
career/service.py, career/router.py
career/exploration.py, career/source_registry.py
career/connectors/public_ats.py, career/discovery.py
tests/test_career_*.py
docs/career_intl/agents/REPORT_CODEX_MEGA.md (nouveau)

## Interdits
Aucun vrai CV, e-mail, téléphone, profil personnel, base réelle.
Aucun merge/push/rebase/stash/clean/prune.
Aucun skip/xfail/test supprimé.

## Étapes
1. Intégrer UI-MAP, UI-DETAIL, AI-SUM.
2. Câbler consent_guard pour résumé IA (fallback local si refus).
3. Ajouter endpoint /api/career/jobs/{id}/summary.
4. Afficher dans la fiche détaillée : missions, prérequis, dates, pertinence, lien, résumé IA optionnel.
5. Vérifier carte + tri avec données réelles.
6. Lancer tests ciblés + audit live_source_check.
7. Rédiger REPORT_CODEX_MEGA.md avec métriques.

## Critères de succès
- UI : carte + tri + fiche détaillée + résumé IA avec consentement.
- Backend : endpoint summary + consent_guard câblé.
- Tests verts.
- Rapport avec métriques réelles (aucune donnée personnelle).
