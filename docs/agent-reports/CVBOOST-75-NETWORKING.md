# Rapport CVBOOST-75 — SPEC-040 — Annuaire networking local

## Livré

- `career/networking_schema.py` — schéma SQLite local + store (`NetworkingStore`) :
  - table `networking_contacts` : { nom, poste (headline), entreprise, école, relation (`first`/`second`/`alumni`/`unknown`), email, profile_url, notes, dernier contact, prochaine action, source, provenance (JSON) } ;
  - table `networking_profile_facts` : faits du profil utilisateur (école, rôle, headline) avec source et origine ;
  - table `networking_imports` : audit de chaque import (fichier, type, lignes) ;
  - upsert idempotent : un ré-import rafraîchit les champs importés **sans jamais écraser** les champs utilisateur (`notes`, `dernier contact`, `prochaine action`) ;
  - `purge()` : purge totale refusée sans `force=True`, purge par rétention `older_than_days`, avec `PRAGMA secure_delete = ON`.
- `career/networking.py` — logique métier, 100 % hors ligne :
  1. **Import LinkedIn local** (`Profile.csv`, `Connections.csv`) : parsing robuste (BOM, colonnes optionnelles, entreprise entre guillemets avec virgule, dates multi-format ISO/EN/FR/jours/mois), faits taggés `source=linkedin_export`, aucune émission réseau ;
  2. **Recommandations de cibles** (`recommend_targets`) : match poste cible ↔ poste/département du contact, détection de desks finance (IBC, M&A, TMT, coverage via `DESK_FAMILIES` versionnée), bonus alumni (école, insensible aux accents), bonus recruteur ; chaque recommandation est dédupliquée par personne et cite **sa provenance** (qui le dit, où : `Connections.csv`, URL de preuve web, ou saisie manuelle) ;
  3. **Brouillons de messages** segmentés (`alumni_first_contact`, `school_recruiter`, `coverage_desk`), rédigés **uniquement** depuis les faits approuvés passés en argument ; brouillons contingents (`MissingFactError` si un fait requis manque) ; `export_drafts()` écrit un fichier local — **aucun envoi**.
- `tests/test_networking.py` — 53 tests (parsing CSV, alumni policy, dédup, provenance, brouillons contingents, purge, tests adversariaux anti-réseau).

## Sécurité

- Aucune dépendance réseau : `requests`/`socket`/`urllib`/`smtplib` absents des deux modules (test adversarial dédié).
- Import strictement local : l'export LinkedIn reste sur disque, les faits vont dans le SQLite local de l'utilisateur.
- Jamais de scraping de masse ni d'annuaire public : les contacts `web_researcher` ne sont créés que par l'utilisateur, avec preuve (URL) obligatoire et citée.
- Purge RGPD : wipe total derrière `force=True`, rétention paramétrable.

## Décisions

- `lastrowid` après `ON CONFLICT DO UPDATE` étant peu fiable, le store relit le contact par sa clé unique `(full_name, company, source)`.
- Le dédoublonnage des recommandations se fait sur (nom normalisé, entreprise normalisée) pour qu'une même personne importée deux fois ne produise qu'une recommandation.
- La relation LinkedIn (`Connections.csv` = relations de 1er degré) est normalisée sur une liste fermée (`first`/`second`/`alumni`/`unknown`).

## Limites

- Le parsing `Profile.csv` couvre les colonnes usuelles (`Schools`, `Positions`, `Headline`) ; les colonnes inconnues sont ignorées sans erreur.
- Pas d'endpoint REST : la mission ne le demande pas ; le store est prêt à être branché sur `career/router.py` ultérieurement.

## Tests

```
.venv/bin/python -m pytest -q tests/test_networking.py → 53 passed
ruff check career/networking.py career/networking_schema.py tests/test_networking.py → All checks passed
git diff --check → clean
```
