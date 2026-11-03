# CVBOOST-74 — SPEC-039 — Ingestion email locale (IMAP)

## Livré
- `career/mail_states.py` : `MailState`, `is_recruiter_email()`, `classify_state()`,
  `MailEvidence`, `make_evidence()`.
- `career/mail_ingest.py` : `MailConfig`, `consent_granted()`, `fetch_headers()`,
  `ingest()`, `purge_old()`.
- Tests `tests/test_mail_ingest.py` (15 cas).
- Rapport `docs/agent-reports/CVBOOST-74-MAIL_INGEST.md`.

## Décisions
- Consentement OFF par défaut (env `CAREER_MAIL_CONSENT`).
- Headers-only pour les emails non-recruteur ; jamais de parsing du corps.
- État toujours `pending_user_confirmation` avant validation utilisateur.
- IMAP SSL, aucun SMTP, aucun cloud, aucune donnée email stockée > 24 mois.
- Purge optionnelle 24 mois.

## Limites
- Pas d'endpoints REST dans cette livraison (core module + tests).
- Pas de rapprochement automatique vers une candidature (linker fourni par l'appelant).
- Pas de chiffrement keychain (à câbler côté appelant).

## Validation
- `pytest -q tests/test_mail_ingest.py` → 15 passed
- `ruff check career/mail_ingest.py career/mail_states.py tests/test_mail_ingest.py` → All checks passed