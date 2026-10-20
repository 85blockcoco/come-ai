# MEGA-PROMPT — Intégration et finalisation Career (usage réel satisfaisant)

## Objectif
Transformer les briques existantes (branches isolées) en un outil utilisable et satisfaisant :
- Carte + tri par correspondance.
- Fiche détaillée offre par offre avec navigation.
- Résumé IA structuré avec consentement cloud.
- Maximum d’informations par offre (missions, prérequis, dates, pertinence, lien officiel).
- Sources étendues et bornées.

## Chemins autorisés
- career_static/index.html, career_static/career.js
- career/application_prep.py, career/application_studio.py
- career/service.py (lecture + ajouts d’endpoints si nécessaire)
- career/router.py (lecture + ajouts d’endpoints si nécessaire)
- career/exploration.py, career/source_registry.py
- career/connectors/public_ats.py, career/discovery.py
- tests/test_career_*.py, tests/test_usage_sim_kit.py
- docs/career_intl/agents/REPORT_MEGA.md (nouveau)

## Interdits
- Aucun vrai CV, e-mail, téléphone, profil personnel, base réelle.
- Aucun merge/push/rebase/stash/clean/prune.
- Aucun skip/xfail/test supprimé.

## Étapes
1. Intégrer les branches UI-MAP, UI-DETAIL, AI-SUM dans une branche candidate.
2. Câbler le consent_guard pour le résumé IA (fallback local si refus).
3. Ajouter un endpoint `/api/career/jobs/{id}/summary` renvoyant `summarize_offer`.
4. Afficher dans la fiche détaillée : missions, prérequis, dates, pertinence, lien, résumé IA optionnel.
5. Vérifier que la carte et le tri fonctionnent avec les données réelles.
6. Lancer les tests ciblés et un audit `live_source_check`.
7. Rédiger REPORT_MEGA.md avec métriques (offres, conformes, à vérifier, temps).

## Critères de succès
- UI : carte + tri + fiche détaillée + résumé IA avec consentement.
- Backend : endpoint summary + consent_guard câblé.
- Tests verts.
- Rapport avec métriques réelles (aucune donnée personnelle).
