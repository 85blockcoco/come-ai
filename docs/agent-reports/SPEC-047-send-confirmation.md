# Rapport mission CVBOOST-84 — SPEC-047 — Confirmation d'envoi manuelle + relance optimale

## Livré

1. **`career/send_confirmation.py`** — module pur (aucune E/S, déterministe) :
   - `SendEvidence` (canal `website`/`email`/`portal`, `sent_at`, note) et `SendRecord` (job_id, sent_at, channel, follow_up_due) ;
   - anti-fraude : un envoi déclaré > 24 h dans le futur → `SendConfirmationError` (erreur métier) ;
   - `compute_follow_up_due` : **+7 jours ouvrés** (week-ends exclus ; jours fériés ignorés si non fournis). Le jour d'envoi compte comme 1ᵉʳ jour ouvré → envoi vendredi ⇒ relance lundi (« vendredi → lundi ») ;
   - `advance_follow_up_due` : relance déjà faite ⇒ prochaine échéance +7 jours ouvrés ;
   - `build_followup_draft` : brouillon de relance court, français, prêt à copier (jamais envoyé automatiquement) ;
   - `prioritize_followups` : envoyés sans réponse, échus d'abord, puis par due date (option `response_received`).
2. **Service (`career/service.py`)** — table `send_confirmations` (ajoutée au schéma initial et dans `_migrate_to_v8`, additif, `user_version` reste 8 ; `job_qualification_snapshots.schema_version=7` inchangé) + méthodes `record_send`, `record_followup`, `send_followup_draft`, `get_apply_tracker`. Idempotence : ré-enregistrement ⇒ UPSERT de la ligne, un seul événement `send_recorded` dans `application_events`. Policy existante respectée : le stage ne passe à `submitted` que si le dépôt manuel a été approuvé ; réception déjà confirmée ⇒ refus.
3. **Endpoints (`career/router.py`)** :
   - `POST /api/career/send-confirmation/{job_id}` (canal invalide ⇒ 422 ; anti-fraude ⇒ 400) ;
   - `POST /api/career/send-confirmation/{job_id}/followup` ;
   - `GET /api/career/send-confirmation/{job_id}/draft` (`automatic_send: false`) ;
   - `GET /api/career/apply-tracker` (priorisés par due date, `automatic_followup: false`).

## Tests

- `tests/test_send_confirmation.py` — 18 tests : anti-fraude (+24 h/3 j refusés), canaux inconnus, +7 jours ouvrés (mercredi → jeudi, **vendredi → lundi**, envoi week-end, jours fériés fournis vs « hors données »), relance repoussée, brouillon français, idempotence (historique non dupliqué), refus sans approbation, Tracker priorisé (échu d'abord, sans réponse), REST complet (201/400/422).
- `pytest tests/test_send_confirmation.py` → 18 passed.
- Régression ciblée : `test_career_application_dashboard.py` 22 passed ; `test_career_application_sprint.py` 12 passed ; `test_qualification_snapshot_persistence.py` 8 passed ; `contract/test_variant_classification.py` 3 passed.
- La suite `test_career_agent.py` / la suite complète n'ont pas pu tourner ici : les processus sont tués par le OOM killer de la machine (jobs d'orchestration en fond), comme prévu par le cadre (« ne pas lancer la suite complète pendant les jobs en fond ») ; chaque fichier ciblé passe individuellement.
- Migration vérifiée à la main : base v7 → réouverture ⇒ `user_version=8` + table `send_confirmations` créée.

## Garanties

- Aucune soumission automatique, aucune relance automatique : tout est déclaré par la personne ; le module enregistre et rédige des brouillons locaux.
- Aucune donnée réelle (fixtures synthétiques exclusivement).

## Arborescence

- Branche : `worker/cvboost-84-1793027188235` (push en `agent/spec-047-send-confirmation`).
