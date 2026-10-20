# Prompts de mission — améliorations Career (UI + IA)

## Mission A — Carte et tri des offres (UI)
Chemins autorisés : career_static/index.html, career_static/career.js, tests/test_career_stage_hunter_ui_guards.py (lecture), docs/career_intl/agents/REPORT_UI_MAP.md (nouveau).
But : afficher une carte des offres disponibles et permettre le tri par correspondance croissante/décroissante.
Contrat : réutiliser les données déjà chargées (city, country, stage_match.score) ; aucun appel réseau supplémentaire ; persister le choix de tri dans localStorage.
Critères : carte affiche ville + nombre d’offres ; tri ascendant montre d’abord les moins bien notées ; choix persiste.

## Mission B — Fiche détaillée offre par offre (UI)
Chemins autorisés : career_static/index.html, career_static/career.js, career/service.py (lecture seule), docs/career_intl/agents/REPORT_UI_DETAIL.md (nouveau).
But : écran « Détail offre » présentant lieu, début/fin, missions, prérequis, date de candidature, date de publication, pertinence, lien officiel ; navigation une par une.
Contrat : utiliser get_job_prep(job_id) ; aucune donnée personnelle ; aucun appel réseau supplémentaire.
Critères : toutes les métadonnées disponibles affichées ; navigation précédent/suivant ; lien officiel cliquable.

## Mission C — Résumé IA d’une offre (backend + UI)
Chemins autorisés : career/application_studio.py, career/application_prep.py, career/service.py (lecture), career_static/career.js (si autorisé), docs/career_intl/agents/REPORT_AI_SUMMARY.md (nouveau).
But : générer un résumé structuré (missions, prérequis, dates, pertinence) pour une offre, avec consentement cloud explicite.
Contrat : utiliser le consent_guard existant ; aucun contenu personnel sans consentement ; sortie bornée et factuelle.
Critères : résumé généré uniquement après consentement ; aucune invention ; fallback local si refus.
