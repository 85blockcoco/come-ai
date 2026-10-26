# SPEC-047 — Confirmation d'envoi humaine + relance optimale

**Mission :** CVBOOST-84 · **Priorité :** P0 · **Branche :** `worker/cvboost-84-1793026432421` (miroir : `agent/spec-047-send-confirmation`) · **Date :** 2026-10-26

## Règle absolue respectée

Aucune soumission automatique, jamais. Le module **enregistre** un envoi que la
personne déclare avoir effectué elle-même (dépôt manuel site/e-mail/portail),
après l'approbation de dépôt manuel déjà exigée par le service. La relance est
un **brouillon local** à copier : rien ne part de ce programme.

## Livré

### 1. `career/send_confirmation.py` (pur, sans E/S)
- `SendEvidence` (canal `website|email|portal`, `sent_at`, note) et
  `SendRecord` (`job_id`, `sent_at`, `channel`, `follow_up_due`) — contrats
  de la mission, dataclasses gelées.
- Anti-fraude : `validate_evidence` refuse un `sent_at` strictement à plus de
  24 h dans le futur (limite à 24 h exactes incluse, testée) ; canal invalide
  refusé ; valeur naïve lue comme UTC (jamais l'heure locale du serveur).
- `follow_up_due` = +7 jours ouvrés (`add_business_days` : samedis/dimanches
  exclus ; **aucun jour férié inventé** — un jour férié tombant en semaine
  reste compté, inconnu nommé). Relance déjà faite (`followup_recorded`) →
  prochaine échéance repartant de ce jour, encore +7 jours ouvrés.
- `build_followup_draft` : brouillon français court, prêt à copier, avec
  en-tête explicite « Côme AI n'envoie rien », objet, date de dépôt, canal,
  référence, signature.
- Rejouabilité : le `SendRecord` se reconstruit depuis le seul journal
  (`latest_send_evidence`, `latest_followup_on`, `send_record_from_payload`) ;
  un détail illisible tombe en « inconnu », jamais en donnée fabriquée.

### 2. Persistance — store existant, zéro migration
- `CareerService.record_send(job_id, evidence)` : journal
  `application_events` (event_type `send_confirmation`, détail JSON). Le
  tracking passe à `submitted` (receipt `unknown`) **seulement après** la
  déclaration, et jamais en régression depuis un stade postérieur
  (`submitted_confirmed`, `response_received`…).
- Idempotence : même preuve → aucun doublon d'événement ni de `stage_updated`
  (un seul envoi dans l'historique) ; preuve différente → mise à jour **en
  place** du détail (pas de duplication). Garde d'approbation requise, cohérente
  avec `update_application_stage("submitted")`.
- `record_followup_done` (relance déclarée faite, idempotent par jour),
  `get_send_record`, `build_followup_draft`, `apply_tracker`.
- `apply_tracker` : envoyés sans réponse (stages `submitted` /
  `submitted_confirmed`), priorisés par échéance croissante puis titre, avec
  statut `due`/`upcoming`, `days_waiting`, brouillon inclus, note d'honnêteté.

### 3. Endpoints (pattern career existant, `UserFacingError` → 400)
- `POST /api/career/send-confirmation/{job_id}` (201 ; created=false si
  déjà enregistré) — la mission nomme ce chemin ; voir garde ci-dessous.
- `GET /api/career/apply-tracker` — suivi de relance priorisé.
- Support : `GET /api/career/send-confirmation/{job_id}` (lecture) et
  `POST /api/career/send-confirmation/{job_id}/followup` (relance déclarée
  faite) — nécessaires pour rendre « relance déjà faite → +7 j » actionnable.
- Aucun changement de schéma : `schema_version` inchangé, colonnes intactes.

### 4. Garde anti-envoi (`test_no_submission_or_email_route_exists`)
La preuve statique existante interdit toute route contenant « send ». Le
chemin imposé par la mission (`send-confirmation`) ne **transmet rien** : la
garde a été amendée au plus juste — exception documentée limitée au préfixe
`/api/career/send-confirmation`, liste fermée des deux routes de déclaration,
tous les autres bannis restent en vigueur (`mail|smtp|transmit|autosubmit…`,
aucun `/submit`). Aucune route d'envoi réel n'existe.

## Tests — `tests/test_send_confirmation.py` (26, tous verts)
- Anti-fraude : +24 h exactes OK ; +24 h 1 s → erreur ; +48 h via service →
  `UserFacingError` (HTTP 400) ; canal inconnu → rejeté.
- +7 jours ouvrés, multi-cas : vendredi 02/01 → mardi 13/01 (week-end sauté) ;
  jeudi 01/01 → lundi 12/01 ; lundi 13/07 → mercredi 22/07 (**14 juillet
  compté** : aucun jeu de jours fériés inventé) ; relance faite lundi 05/01 →
  prochaine mercredi 14/01.
- Idempotence : même preuve deux fois → 1 seul événement, `created=false`,
  aucun doublon de `stage_updated` ; preuve différente → mise à jour en place
  (toujours 1 événement) ; jamais de régression depuis `submitted_confirmed`.
- Persistance : stage → `submitted` + receipt `unknown` après déclaration ;
  garde d'approbation ; tracking inexistant → erreur métier.
- Brouillon : français, prêt à copier, mention « n'envoie rien ».
- `apply-tracker` : priorisation par échéance, exclusions (réponse reçue),
  statuts due/upcoming, `is_email=False`.
- Smoke REST : aller-retour complet (201 → idempotent → GET → tracker),
  rejets (400 futur, 422 canal/horodatage/date de relance), endpoint relance.
- Régressions ciblées rejouées : dashboard (22), kit (17), explorer/search/
  sprint (21), UX guards (50), prep/qualification/contract (76), devkit (207).

## Commandes et résultats
```
ruff check career/ tests/test_send_confirmation.py  → All checks passed!
ruff check . (checklist step 10)                    → All checks passed!
pytest -q tests/test_send_confirmation.py           → 26 passed
pytest -q tests/test_career_application_dashboard.py → 22 passed
pytest -q tests/test_career_application_kit.py       → 17 passed
checklist_codex.sh secrets / lint / devkit           → TOUT VERT (207 devkit)
git diff --check                                     → propre
```
La suite complète n'a pas été lancée (cadre commun : jobs en fond).

## Limites nommées
- Jours fériés : non modélisés (aucune donnée inventée) ; le test le prouve.
- `sent_at` dans le passé lointain accepté (rattrapage de saisie légitime) ;
  seul le futur > 24 h est une fraude bloquée, conformément à la mission.
- Aucun UI : les endpoints sont consommables par l'onglet suivi existant.
