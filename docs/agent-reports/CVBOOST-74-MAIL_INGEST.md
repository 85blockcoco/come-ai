# CVBOOST-74 — SPEC-039 — Ingestion email locale (IMAP, consentement)

**Branche** : `agent/spec-039-mail-ingest` · **Statut** : done

## Livrés

| Fichier | Rôle |
|---|---|
| `career/mail_states.py` | Classification d'état (received/interview/assessment/rejection/offer_received/unknown) avec confiance et termes déclencheurs |
| `career/mail_ingest.py` | Config IMAP, consentement OFF par défaut, parsing RFC822 (headers+corps UTF-8), filtre recruteur, rapprochement strict, empreinte SHA-256, dédup, purge 24 mois, pipeline |
| `tests/test_mail_ingest.py` | 69 tests synthétiques (parsing, filtre, états, consentement, rapprochement, dédup, purge, IMAP mock) |
| `career/router.py` | 3 endpoints REST (`/api/career/mail-ingest/parse`, `/detect-state`, `/filter`) |

## Contrats respectés

- Consentement explicite : OFF par défaut, `require_consent` lève `PermissionError`.
- Aucun SMTP, aucun cloud, aucun forwarding ; IMAP uniquement via config explicite.
- Emails non-recrutement : jamais de parsing du corps (filtre avant).
- État détecté toujours `pending_user_confirmation` (jamais appliqué sans validation).
- Purge optionnelle au-delà de 24 mois.
- SHA-256 + horodatage pour chaque email matché (preuve).

## Limites

- IMAP réel non testé (mock local) ; keyring optionnel (absent de l'environnement, fallback gracieux).
- Application de l'état à une candidature nécessite confirmation utilisateur (`apply_state_to_application(..., confirm=True)`).
- Le rapprochement est strict (entreprise/ID offre) et peut renvoyer `None` si aucune correspondance.

## Tests

```
pytest -q tests/test_mail_ingest.py → 69 passed
ruff check career/mail_ingest.py career/mail_states.py tests/test_mail_ingest.py career/router.py → All checks passed
git diff --check → propre
```