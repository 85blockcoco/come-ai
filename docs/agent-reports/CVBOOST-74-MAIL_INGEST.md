# CVBOOST-74 — Ingestion email locale (IMAP)

## Livré
- `career/mail_ingest.py` : configuration IMAP locale, parsing robuste UTF-8, filtre heuristique recruteur, consentement explicite (OFF par défaut), hachage SHA-256, preuve mail, rapprochement strict vers une candidature, fetch IMAP injectable, purge 24 mois.
- `career/mail_states.py` : détection déterministe d'état (reçu, entretien, assessment, refus, offre), confiance, proposition toujours en attente de confirmation utilisateur.
- Tests synthétiques : `tests/test_mail_ingest.py`, `tests/test_mail_states.py`.

## Tests
- pytest ciblé : 87 passed
- ruff : All checks passed
