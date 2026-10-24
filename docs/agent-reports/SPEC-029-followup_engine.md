# SPEC-029 — Moteur de relances chronologiques

## Livré
- `career/followup_engine.py` : `FollowupPolicy`, `FollowupAction`, `FollowupPlan`, `plan_today()`, `spam_guard()`.
- Endpoints REST via `create_app()` : `/api/career/followups`, `/api/career/followup-plan`, `/api/career/followups/plan`.
- Fixture synthétique `tests/fixtures/followups_synthetic.json`.
- Tests `tests/test_followup_engine.py` (cas limites + adversarial).

## Règles appliquées
- Première relance J+7.
- Jamais moins de 5 jours entre deux relances d'une même candidature.
- Anti-spam via `spam_guard()`.
- Données synthétiques uniquement.

## Décisions
- Une seule action par candidature et par jour, raison prioritaire parmi `deadline_soon`, `viewed_no_reply`, `no_response_j7`.
- `due_date` = date du plan (jour courant).
- Candidatures closes/offre ignorées ; blocages enregistrés dans `blocked_reasons`.

## Limites
- Planification déterministe locale, aucun envoi automatique.
- Les canaux sont suggérés (email/portal/in_person), jamais exécutés.