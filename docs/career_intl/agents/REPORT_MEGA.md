STATUT: TERMINÉE
MISSION: MEGA — Intégration et finalisation Career (usage réel satisfaisant)

## Livré
- Carte des offres par ville + tri asc/desc persistant dans Stage Hunter.
- Fiche détaillée offre par offre avec navigation précédent/suivant.
- Résumé structuré local (`summarize_offer`) exposé par `/api/career/jobs/{id}/summary`.
- Résumé IA optionnel avec consentement cloud via `consent_guard` (fallback local si refus).
- Maximum d’informations par offre : missions, prérequis, dates, pertinence, lien officiel.
- Sources étendues et bornées via registre public (21 sources).

## Backend
- `career/application_prep.py`: ajout de `summarize_offer`.
- `career/service.py`: `get_job_summary` / `summarize_job` + câblage `consent_guard`.
- `career/router.py`: `GET`/`POST /api/career/jobs/{job_id}/summary` avec `JobSummaryPayload`.
- Consentement cloud : `consent_guard` initialisé dans `CareerService` (`data_dir/consent`), vérification/consommation unique, repli local.

## UI
- `career_static/index.html`: sélecteur de tri, carte `#stagehunter-map`, fiche `#stagehunter-detail` + navigation.
- `career_static/career.js`: `renderStageMap`, `renderStageMatches` (tri), `loadStageDetail` (champs + missions + résumé IA optionnel).

## Tests
- `tests/test_career_*.py`: 327 passed.
- `tests/test_consent_guard_*.py`: 185 passed.
- `scripts/live_source_check`: 21/21 sources réussies, 0 échec, 0 non interrogée.

## Métriques live (audit borné, aucune donnée personnelle)
- Sources interrogées: 21
- Sources réussies: 21
- Sources échouées: 0
- Offres brutes évaluées: 1774
- Offres retenues: 45
- Offres conformes (confirmed): 23
- Offres à vérifier (uncertain): 1059
- Offres exclues: 692
- Temps total: 33,08 s

## Limites
- Le résumé IA cloud nécessite un fournisseur configuré et un consentement explicite; sinon repli local.
- Les champs absents restent inconnus (aucune invention).
- Audit réseau dépendant de la disponibilité des sources publiques.
