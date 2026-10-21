# SPEC SK-07 — Offer Intelligence Bridge (CVBOOST-28)

**Branche** : `agent/spec-sk07-offer-intelligence-bridge` (+ `worker/cvboost-28-1792613558`)
**Base** : `main` local (`f5b22f2`) + fusion de SK-01 / SK-02 / SK-03
**Date** : 2026-10-21
**Auteur** : Agent Mission 28 (worker)

---

## 1. Ce qui a été livré

```
career/offer_intelligence.py                          # constructeur de snapshot (p pur)
career/offer_intelligence_store.py                    # persistance versionnée (p pur)
career/service.py                                     # import, explorer, détail, matching, prépa, kit
career/application_prep.py                             # la prépa lit le contrat canonique
career/application_studio.py                           # la lettre cite le contrat canonique
career/router.py                                      # GET /api/career/offer-intelligence/{job_id}
tests/test_offer_intelligence.py                      # 37 tests
tests/fixtures/offer_intelligence/offers.json         # 8 offres synthétiques gelées
docs/agent-reports/SPEC-SK07-OFFER_INTELLIGENCE_BRIDGE.md   # ce rapport
```

**Huit offres 100 % synthétiques** (aucune entreprise, aucun poste, aucune personne réelle),
**37 tests**, modules **purs, déterministes, hors ligne** : pas d'horloge (sauf injection),
pas de hasard, pas de réseau, pas de modèle.

> **Intégration en amont** — SK-07 consomme SK-01 (confiance), SK-02 (dates) et SK-03
> (adéquation). Les trois branches (`agent/spec-sk01-source-trust`,
> `agent/spec-sk02-offer-dates`, `agent/spec-sk03-requirements-fit`) ont donc été **fusionnées
> dans ce worktree** (commit `4d95a54`, fusion propre, aucun conflit : ce sont des ajouts
> de fichiers purs). SK-04 (couverture) et SK-05 (progression d'exploration) ne sont pas
> consommés par le pont et restent sur leur branche, à integrator séparément.

---

## 2. Le contrat : un snapshot unique, versionné

```python
from career.offer_intelligence import build_snapshot

snapshot = build_snapshot(offer_raw, qualified_data) -> OfferIntelligenceSnapshot
```

| Bloc | Contenu |
|------|---------|
| `job_id` | identité de l'offre |
| `schema_version` | version du contrat d'intelligence |
| `source_hash` | empreinte du **texte source exact** (sha256, 64 caractères) |
| `temporal_facts` | publication, deadline, start, end, duration — avec bornes, précision, état de confiance et preuve |
| `requirements` | les enregistrements canoniques de prérequis, avec leur identifiant stable |
| `contradictions` | les preuves incompatibles, gardées côte à côte, jamais arbitrées |
| `missing` | ce que la source ne prouve pas — toujours « à vérifier » |
| `qualifications` | la qualification contractuelle **attribuée à la source** |
| `trust` | la décision de confiance explicite (SK-01) |
| `geo` / `lang` | localisation et langues, avec leur preuve |
| `provenance_map` | pour chaque fait : le champ, le passage cité et ses offsets |

### Un fait temporel

```json
{
  "id": "tf_57f5143cb2d64ac4",
  "kind": "deadline",
  "precision": "exact_date",
  "value": "2026-11-15",
  "lower_bound": null,
  "upper_bound": null,
  "confidence_state": "confirmed",
  "source_fact_id": "deadline@description_original:0",
  "evidence": {
    "source_kind": "official_text",
    "source_id": "9001",
    "source_field": "description_original",
    "locator": "offset:0:25",
    "quote": "Apply by 15 November 2026",
    "start_offset": 0,
    "end_offset": 25
  }
}
```

### Une exigence

```json
{
  "id": "req_825e12e58aab2265",
  "text": "Advanced Excel",
  "source_field": "requirements",
  "locator": "line:1",
  "category": "technical_skill",
  "modality": "required",
  "confidence": 0.9,
  "negated": false,
  "injection_suspect": false,
  "evidence": { "quote": "Advanced Excel", "start_offset": 0, "end_offset": 14 }
}
```

---

## 3. Zéro divergence : une exigence, un identifiant, tous les écrans

Les six consommateurs de la mission lisent **le même snapshot** :

| Écran | Point d'entrée | Identifiants |
|-------|----------------|--------------|
| Explorer (liste) | `GET /api/career/jobs` | `job["offer_intelligence_summary"]["requirement_ids"]` |
| Fiche détaillée | `GET /api/career/jobs/{id}` | `job["offer_intelligence"]["requirements"][*]["id"]` |
| Pont (route dédiée) | `GET /api/career/offer-intelligence/{id}` | `snapshot["requirements"][*]["id"]` |
| Matching | `GET /api/career/stage-search/matches` | `match["requirement_ids"]` |
| Préparation CV | `GET /api/career/jobs/{id}/prep` | `prep["offer_intelligence"]["requirement_ids"]` |
| Lettre & checklist | `GET /api/career/applications/{id}/kit` | mêmes enregistrements canoniques |

Test de garde : `test_every_screen_shares_the_same_requirement_identifiers` compare les six
listes — elles sont **strictement égales**.

Les identifiants viennent du contrat canonique existant
(`career.offer_requirements.analyze_offer`, `req_` + sha256) : **aucun second analyseur de
prérequis n'a été créé**. L'ancienne extraction lexicale de `application_prep.extract_requirements`
reste en place comme fonction de compatibilité (appelée sans snapshot) ; le chemin produit
(service, prépa, kit, lettre) lit désormais le contrat canonique.

---

## 4. Persistance versionnée, sans nouvelle colonne sur les offres

Table dédiée `job_offer_intelligence_snapshots` :

```
job_id | version | schema_version | source_hash | summary_json | snapshot_json | is_current | created_at | updated_at
```

`jobs` n'est **pas** touchée : pas de colonne ajoutée, pas de migration destructrice, pas de
réécriture des données de la personne. La table est créée par `CREATE TABLE IF NOT EXISTS`
(cf. `career/offer_intelligence_store.ensure_schema`), sans passage de `SCHEMA_VERSION`.

| Cas d'import | Comportement vérifié |
|--------------|----------------------|
| Texte identique | Même version, **mêmes identifiants**, pas de nouvelle ligne |
| Texte modifié | **Nouvelle version**, nouveaux identifiants, l'ancienne passe en historique |
| Note personnelle | Préservée (`test_the_notes_shortlist_and_application_survive_a_reimport`) |
| Shortlist | Préservé |
| Candidature | Préservée (id + étape) |
| Preuve obsolète | Retirée du snapshot courant, conservée dans l'historique (`test_a_stale_evidence_is_never_presented_as_current`) |

`source_hash` ne dépend que des **champs source** : une note, un raccourci ou une étape de
candidature ne change jamais l'empreinte (`test_source_hash_ignores_the_user_state_of_the_offer`).

---

## 5. Règles métier respectées

| Règle | Preuve |
|-------|--------|
| Une échéance n'est jamais une date de début | `test_a_deadline_is_never_reused_as_a_start_date` |
| Un mois seul ne devient jamais un jour | `test_a_month_only_statement_never_becomes_an_exact_day` |
| « up to six months » est un maximum, jamais un minimum | `test_an_upper_bound_never_proves_a_minimum` |
| Un fait confirmé porte sa citation et ses offsets | `test_every_confirmed_fact_carries_its_quote_and_its_offsets` |
| Une information manquante est « à vérifier », jamais « absente » | `test_a_missing_information_stays_to_verify_and_is_never_dropped` |
| Une contradiction garde les deux versions | `test_a_contradiction_keeps_both_sides_without_choosing_one` |
| Une tentative d'injection reste une donnée inerte | `test_an_injection_attempt_stays_inert_data` |
| Une échéance dépassée reste visible | `test_an_expired_deadline_stays_visible` |
| Aucun appel réseau ni modèle | `test_the_snapshot_works_offline_without_any_model_call` (socket interdit) |
| Le snapshot ne contient aucune donnée de candidat | `test_the_snapshot_never_carries_candidate_profile_data` |

### Corpus gelé

`tests/fixtures/offer_intelligence/offers.json` — 8 cas, fr / en / de / it / es :

français complet · échéance ≠ début · allemand (durée exacte) · italien (mois seul) ·
espagnol (mois seul) · champ structuré contre texte · échéance dépassée · injection + troncature.

Le test `test_frozen_corpus_classifies_every_fact_and_requirement` compare **exactement** les
faits, les exigences, les informations manquantes et le nombre de contradictions de chaque cas.

---

## 6. Ce qui a été modifié dans l'existant (et pourquoi)

| Fichier | Modification |
|---------|--------------|
| `career/service.py` | Table dédiée ; construction et versionnement du snapshot à l'import ; snapshot attaché au détail, résumé à l'explorer ; identifiants attachés au matching ; snapshot passé à la prépa et au kit |
| `career/application_prep.py` | `prepare_application(..., intelligence=...)` : quand un snapshot est présent, la liste des exigences est celle du contrat canonique et chaque élément porte son identifiant ; bloc `offer_intelligence` exposé (identifiants, manques, contradictions) |
| `career/application_studio.py` | `_offer_summary` cite les exigences canoniques quand le snapshot est présent |
| `career/router.py` | `GET /api/career/jobs/{id}/offer-intelligence` et `GET /api/career/offer-intelligence/{id}` (alias, pas une copie) |

**Aucun test existant n'a été modifié.** `extract_requirements` garde son comportement historique
(l'extracteur lexical) pour les appels directs sans snapshot : les tests historiques restent
verts, le chemin produit lit le contrat canonique.

---

## 7. Validation

| Commande | Résultat |
|----------|----------|
| `pytest -q tests/test_offer_intelligence.py` | **37 passed** |
| `pytest -q tests/test_offer_dates.py tests/test_source_trust.py tests/test_requirements_fit.py` | **834 passed** (SK-01/02/03 fusionnés) |
| `pytest -q` (suite complète) | **2295 passed, 1 skipped** (skip pré-existant `test_offer_summary_exhaustiveness`) |
| `ruff check .` | **All checks passed** |
| `git diff --check` | **propre** |

Répartition : 2258 tests avant SK-07 (base `f5b22f2` + SK-01/02/03 fusionnés) → 2295 après
SK-07, soit **+37** (le fichier `tests/test_offer_intelligence.py` en compte 37, dont un test
paramétré sur les 8 cas du corpus gelé).

---

## 8. Limites assumées

- **Le snapshot ne contient que des faits attribués à la source.** Le statut d'adéquation aux
  critères de la personne (`target_status`), l'admissibilité géographique et le statut de
  contrat dépendant du jour restent dans la couche de matching : une préférence modifiée ne
  doit pas créer une nouvelle version de l'analyse.
- **La confiance de la source est horodatée** (`checked_at`). C'est la seule valeur non
  déterministe du document ; les identifiants, eux, sont stables.
- **Le contrat SK-01/02/03 est réutilisé tel quel.** SK-07 n'améliore ni le détecteur de dates
  ni le classifieur de prérequis : il les branche. Une correction de ces modules se répercute
  automatiquement sur le snapshot.
- **L'interface web n'a pas été refaite.** Les écrans consomment déjà `prep["requirements"]` ;
  ils montrent désormais les textes canoniques et disposent des identifiants dans la charge utile.
- **SK-04 et SK-05 ne sont pas fusionnés ici** : ils ne sont pas consommés par le pont.

---

## 9. Suite proposée

1. Exposer le bloc `offer_intelligence` dans l'interface (fiche détaillée : faits confirmés,
   contradictions, à vérifier).
2. Brancher SK-08 (enrichissement des connecteurs) sur `source_fields` pour que chaque fait
   conserve le nom exact du champ source.
3. Faire de `career.requirements_fit` (SK-03) le producteur des verdicts
   `supported / unsupported / contradicted / to_verify` dans le snapshot, pour que la
   correspondance profil ↔ offre soit elle aussi versionnée.
