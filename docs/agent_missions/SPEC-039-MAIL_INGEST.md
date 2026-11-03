# MISSION CVBOOST-74 — SPEC-039 — Ingestion email locale (IMAP, consentement) — détection des réponses recruteur

> **Priorité : P1** — Répond au besoin « retrouver invitations aux entretiens, préparer les
> réponses, organiser les relances » SANS jamais de tiers cloud.
> Selon l'utilisateur sk11 (événements candidature) + les 64/09 (relances, dashboard).

## OBJECTIF
Lire LA BOÎTE EMAIL DE L'UTILISATEUR via IMAP **local**, avec consentement explicite et
courbé limité uniquement aux emails VANCT de recrutement, pour update automatiquement
l'état des candidatures (reçu, entretien, KO, assessment) et calibrer les relances dues.

## PÉRIMÈTRE BUILD
Crée `career/mail_ingest.py`, `career/mail_states.py` et leurs tests.

FONCTIONS
1. Config locale explicite (IMAP host, login, mot de passe dans le IPVan local chiffré via
   keychain/keyring) — JAMAIS de stockage droit dans un fichier du dépôt.
2. IMAP INBOX unread/since; fetch headers + corps (UTF-8 robuste); applique un filtre
   heuristique recruiter (domaines de carrieres, patterns d'objet : interview, assessment,
   invitation, rejection, candidature).
3. Chaque email matché (1) est mis en Evidence Mail (preuve, sha256, timestamp, restant
   sourcé dans la database locale), (2) appartient à un candidat-linkingheur : rapproche
   vers une candidature (via l'entreprise ou l'ID offre) par matching strict.
4. Envoyer un rapport de trajet : bilan confiance par état : confiance, analyse
   silico pour l'utilisateur à RECONFIRMER (jamais d'état implicitement changé sans
   validation ; état "pending_user_confirmation").
5. Une fois validé, l'état alimente le moteur de relances existant (64) et le dashboard.

## SÉCURITÉ (blocants)
- Consentement explicite paramétrable (OFF par défaut, prompt au premier run).
- Aucun SMTP, aucun fetch cloud, aucun forwarding; tout reste sur le Mac.
- Aucune donnée email stockée au-delà de 24 mois : purge optionnelle.
- Emails personnels non-recruitement : JAMAIS ouverts en parsing (headers only).

## TESTS
≥ 40 cas : parsing headers/corps, match/latent myrée, consent OFF, ghost drafts,
rapprochement, doublons, purge 24 mois, IMAP fixture locale.

## RAPPORT
`docs/agent-reports/CVBOOST-74-MAIL_INGEST.md` — branche `agent/spec-039-mail-ingest`.
