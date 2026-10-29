# SPEC-040 — Annuaire networking local (export LinkedIn, alumni, desks)

**Mission** : CVBOOST-75 · **Branche de travail** : `worker/cvboost-75-1793234839089` · **Statut** : done

## Livrés

| Fichier | Rôle |
|---|---|
| `career/networking_schema.py` | `Contact`, `Provenance`, relations, validation, ids déterministes, schéma SQLite |
| `career/networking.py` | Import export LinkedIn, store SQLite local, recommandations, brouillons, faits web |
| `tests/test_networking.py` | 86 tests synthétiques (parsing, alumni-policy, dédup, purge, brouillons, sécurité) |
| `docs/agent-reports/CVBOOST-75-NETWORKING.md` | Ce rapport |

## Fonctions

### 1. Import d’un export LinkedIn local

`parse_linkedin_export(source)` lit uniquement `Profile.csv` et `Connections.csv`
(`Education.csv` optionnel). `source` peut être un dossier décompressé ou un mapping
`{nom_fichier: texte}` pour les tests.

- BOM, préambule `Notes:`, en-têtes localisés (`Prénom`, `Société`, `Établissement`) et
  virgules dans les noms sont gérés.
- Chaque contact est tagué `source=linkedin_export` avec la provenance
  `"Export LinkedIn — Connections.csv, ligne N"`.
- `import_linkedin_export(store, source)` écrit dans SQLite et reste idempotent au
  ré-import (même `contact_id`, provenances dédupliquées).
- Limites locales : 5 Mo par fichier, 5 000 connexions ; une ligne sans nom complet ou
  avec un en-tête inconnu produit un avertissement, jamais une invention.

### 2. Schéma contact local (SQLite)

`Contact` : `name`, `role`, `company`, `school`, `relation` (`first`/`second`/`alumni`),
`notes`, `last_contact`, `next_action` (+ `email`, `linkedin_url` si l’export les
contient). Tables `networking_contacts` et `networking_provenance` (clé étrangère,
`ON DELETE CASCADE`, base en `0600`).

Politique alumni : un contact n’est `alumni` que si une **école explicite** est présente
et correspond à une école du profil. L’import ne déduit jamais alumni d’une entreprise,
d’un nom ou d’une proximité ; `mark_alumni()` exige l’école.

### 3. Cibles recommandées (voracité déterministe)

`recommend_targets(contacts, target_role=..., target_departments=..., viewer_schools=...)`
classe par signaux puis sélectionne en glouton :

- recouvrement métier avec le poste cible (+6/token, plafond +18) ;
- desk finance identifié (+8) et desk ciblé (+20) : `M&A`, `TMT`, `IBC`, `coverage`,
  `ECM`, `DCM`, `Leveraged Finance`, `Private Equity` ;
- alumni prouvé (+25) ou école partagée à confirmer (+18) ;
- relation 1er degré (+8), 2nd degré (+2).

Déduplication par `contact_id` et par personne, plafond par entreprise (2 par défaut),
score minimal 12, ordre stable. **Chaque résultat expose `provenance` (source, qui,
URL, date)**.

### 4. Brouillons segmentés, jamais envoyés

`build_networking_draft()` propose trois modèles : `alumni_first_contact`,
`school_recruiter`, `coverage_desk`. Le modèle doit être applicable au contact
(alumni prouvé, rôle recruteur explicite, desk identifié) sinon `DraftNotApplicable`.

- Seuls les faits `approved=True` sont utilisés ; chaque segment conserve son `fact_id`.
- `can_send=False` en dur ; `export_drafts()` écrit un JSON ou un texte local en `0600`.
  Aucune fonction d’envoi, d’upload ou d’export de l’annuaire n’existe.

### 5. Faits publics du Web Researcher

`record_public_facts()` exige un nom de source, une URL `http(s)` et un extrait de
preuve. **Une seule page par entreprise par recherche** : une seconde URL pour la même
entreprise fait échouer tout le lot avant la première écriture.

## Sécurité (blocants respectés)

- Aucune requête réseau : le module n’importe ni `requests`, ni `urllib.request`,
  ni `socket`, ni navigateur (test dédié).
- Import local uniquement, aucun scraping d’annuaire, fichiers jamais envoyés.
- Aucun export de l’annuaire ; seuls les brouillons sont écrits localement.
- SQL entièrement paramétré ; métacaractères stockés littéralement (test dédié).

## Vérifications

```text
pytest -q tests/test_networking.py  → 86 passed
ruff check career/networking.py career/networking_schema.py tests/test_networking.py
                                     → All checks passed
git diff --check                     → propre
```

## Limites

- `Connections.csv` ne contient pas l’école : les alumni issus de l’import restent
  `first` tant qu’une école explicite n’est pas fournie (choix volontaire).
- Pas d’endpoint REST dans cette mission : les modules sont prêts à être branchés sur
  `CareerService`/`create_app()` dans une mission d’intégration.
- Les recommandations sont lexicales (déterministes, sans modèle) ; le Web Researcher
  reste seul responsable des faits publics et de leurs preuves.
