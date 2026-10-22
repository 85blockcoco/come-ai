# SPEC-006 — Fraîcheur, complétude, déduplication et confiance des sources

**Mission** : CVBOOST-36 (ordre `cvboost-36-1792648573`)
**Branche de travail** : `worker/cvboost-36-1792648573` (worktree `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-36-1792648573`)
**Base** : `main` @ `f5b22f2`
**Date** : 2026-10-22
**Statut** : livrée, vérifiée, poussée

---

## 1. Ce que j'ai trouvé avant d'écrire

La mission annonce « Repose sur SK-01, SK-02, SK-06 ». J'ai vérifié l'état
réel de ces trois briques dans le dépôt **avant** d'écrire une ligne :

| Brique | Branche | Fichiers | État sur `main` |
|--------|---------|----------|-----------------|
| **SK-01** — confiance de la source | `agent/spec-sk01-source-trust` | `career/source_trust.py` (644 l.), `tests/test_source_trust.py` (296 l.) | **non mergée** |
| **SK-02** — dates de l'offre | `agent/spec-sk02-offer-dates` | `career/offer_dates.py` (1527 l.), `tests/test_offer_dates.py` (364 l.) | **non mergée** |
| **SK-06** — déduplication multi-sources | `agent/spec-sk06-dedup` | `career/job_deduplication.py` (2045 l.), 3 fichiers de tests (1601 l.) | **non mergée** |

`main` ne contenait **aucune** de ces trois briques : sans elles, « réutilise
SK-01 » était impossible et le module aurait dû réinventer un contrat de
confiance et un contrat de fusion — exactement ce que la mission interdit.

**Décision** : branche de travail = `main` + **trois fusions explicites** des
briques dont SPEC-006 dépend, puis SPEC-006 par-dessus. Les fusions sont
visibles, nommées et sans conflit (`git merge-tree` vérifié avant chaque
fusion) :

```
f0111bb merge(deps): SPEC-SK-01 (source trust) requis par SPEC-006
0e2b528 merge(deps): SPEC-SK-02 (dates d'offre) requis par SPEC-006
817cf49 merge(deps): SPEC-SK-06 (deduplication) requis par SPEC-006
```

Ce qui a été **réutilisé tel quel** (aucune réimplémentation) :

- `check_trust()` de SK-01 : statut, `provider`, `canonical_host`,
  `employer_match`, `registry_evidence`, `reasons` — SPEC-006 ne redécide
  **jamais** la confiance d'un lien ;
- `deduplicate_jobs()` de SK-06 : groupement, `provenances`, `conflicts`,
  `choose_best` — SPEC-006 ne fusionne **jamais** deux offres par lui-même ;
- `extract_offer_dates()` de SK-02 : lecture multilingue des dates, y compris
  la règle « un mois ne devient jamais un jour inventé ».

---

## 2. Les modules livrés

| Fichier | Lignes | Rôle |
|---------|--------|------|
| `career/offer_quality.py` | 1026 | Cœur pur : fraîcheur, complétude, confiance, déduplication, changements |
| `career/offer_quality_store.py` | 224 | Cache local, historique des changements, sonde HTTP bornée |
| `career/router.py` | +30 | `GET /api/career/offer-quality/{id}`, `GET .../history`, `POST .../refresh` |
| `career/service.py` | +130 | Lecture des offres, rafraîchissement, persistance, effacement |
| `career_static/js/offer-quality.js` | 146 | Badges de fraîcheur, de complétude et de source |
| `career_static/index.html` | +1 | Chargement du module |
| `career_static/career.js` | +4 | Appel de `CareerOfferQuality.decorate(card, job)` |
| `tests/test_offer_quality.py` | 589 | **46 tests** synthétiques, 100 % hors ligne |

### API publique du cœur pur

| Fonction | Rôle |
|----------|------|
| `assess(offer_id, catalog, *, now, verified_at, source_url_status, previous)` | Verdict complet d'une offre lue dans un catalogue |
| `assess_offer(offer, *, offer_id, now, verified_at, source_url_status, previous, duplicates)` | Verdict complet d'un dictionnaire d'offre |
| `assess_freshness(offer, ...)` | Fraîcheur : dernière vérif, statut URL, activité, date limite, changements |
| `assess_completeness(offer)` | Complétude : score 0-100 + champs manquants |
| `assess_source_trust(offer, *, url, provider, tier)` | Confiance de la source (verdict SK-01) |
| `assess_deduplication(offer, duplicates)` | Identité canonique, sources, provenance, contradictions |
| `detect_changes(previous, current, detected_at)` | Champs modifiés entre deux vérifications |
| `offer_facts(offer)` | Faits surveillés, normalisés et comparables |
| `source_tier(provider)` / `tier_label(tier)` | Priorité d'une source (table de la mission) |
| `deadline_hint_from_text(offer)` | Date limite lue dans le texte (SK-02), sans inventer de jour |
| `is_refresh_due(last_verified_at)` | Une vérification a-t-elle plus de 24 h ? |

**Pureté vérifiée par les tests** : aucun réseau, aucune horloge implicite,
aucune écriture, aucun dictionnaire reçu n'est modifié, deux appels avec les
mêmes entrées rendent le même verdict.

---

## 3. Le contrat

### `GET /api/career/offer-quality/{offer_id}` (lecture seule)

```json
{
  "offer_id": "job_1",
  "assessed_at": "2026-10-21T08:00:00Z",
  "freshness": {
    "last_verified_at": "2026-10-21T08:00:00Z",
    "source_url_status": 200,
    "source_url": "https://boards.greenhouse.io/acme/jobs/123",
    "is_active": true,
    "deadline_date": "2026-10-25",
    "days_until_deadline": 4,
    "changes_since_last_check": [
      {"field": "deadline_date", "old": "2026-10-20", "new": "2026-10-25", "detected_at": "2026-10-21T08:00:00Z"}
    ],
    "status": "fresh",
    "age_days": 0,
    "reasons": ["La page source répond 200 : l'offre est toujours publiée."]
  },
  "completeness": {
    "score": 84,
    "missing_fields": ["duration_months", "salary_range"],
    "present_fields": ["title", "company", "description", "requirements", "location", "dates", "employment_type", "official_url"],
    "has_requirements": true,
    "has_location": true,
    "has_dates": true,
    "reasons": ["Informations manquantes : duration_months, salary_range."]
  },
  "source_trust": {
    "status": "verified",
    "provider": "greenhouse",
    "canonical_host": "boards.greenhouse.io",
    "employer_match": "confirmed",
    "registry_evidence": "registry:greenhouse:acme",
    "checked_at": "2026-10-21T08:00:00Z",
    "tier": 2,
    "tier_label": "ATS officiel",
    "reasons": ["..."]
  },
  "deduplication": {
    "canonical_id": "canon_86fbd2d14f",
    "sources": [
      {"provider": "greenhouse", "url": "https://boards.greenhouse.io/acme/jobs/123", "trust": "verified", "raw_id": "123", "tier": 2, "tier_label": "ATS officiel", "is_primary": true},
      {"provider": "jobteaser", "url": "...", "trust": "unverified", "raw_id": "789", "tier": 3, "tier_label": "Plateforme partenaire", "is_primary": false}
    ],
    "merged_from": ["greenhouse:123", "jobteaser:789"],
    "contradictions": ["employment_type : greenhouse:123=stage / jobteaser:789=internship"],
    "primary_provider": "greenhouse",
    "duplicate_count": 1,
    "reasons": ["..."]
  }
}
```

### `POST /api/career/offer-quality/refresh`

```json
{"offer_ids": ["job_1", "job_2"], "force": false}
```

```json
{
  "refreshed_at": "2026-10-21T08:00:00.000000+00:00",
  "forced": false,
  "count": 2,
  "changed": 1,
  "offers": [
    {
      "offer_id": "job_1",
      "changed": true,
      "changes": [{"field": "deadline_date", "old": "2026-10-25", "new": "2026-11-05", "detected_at": "2026-10-21T08:00:00Z"}],
      "verified_online": false,
      "reverification_due": true,
      "quality": { "...": "contrat complet ci-dessus" }
    }
  ]
}
```

### `GET /api/career/offer-quality/{offer_id}/history`

```json
{
  "offer_id": "job_1",
  "history": [
    {"field": "deadline_date", "old": "2026-10-25", "new": "2026-11-05", "detected_at": "2026-10-21T08:00:00Z"}
  ],
  "count": 1
}
```

---

## 4. Les règles appliquées

### Fraîcheur

| Situation | `status` | `is_active` |
|-----------|----------|-------------|
| Vérifiée il y a moins de 7 jours | `fresh` | oui |
| Vérifiée entre 8 et 30 jours | `aging` | oui |
| Vérifiée depuis plus de 30 jours | `stale` | oui |
| Date limite dépassée, source fermée, ou page en 404/410 | `expired` | **non** |
| Jamais vérifiée et page jamais contrôlée | `unknown` | oui |

Une erreur serveur (5xx) **n'expire pas** une offre : elle prouve que le
serveur a un problème, pas que l'offre a disparu. La date limite est lue
dans le champ structuré, ou à défaut dans le texte via SK-02 — **jamais
complétée par un jour inventé**.

### Complétude

Score = somme des poids des faits présents (total 100) :

| Fait | Poids | | Fait | Poids |
|------|-------|---|------|-------|
| `title` | 10 | | `duration_months` | 8 |
| `company` | 10 | | `salary_range` | 8 |
| `description` | 12 | | `employment_type` | 6 |
| `requirements` | 12 | | `official_url` | 12 |
| `location` | 8 | | `dates` | 14 |

Le couple d'exemple de la mission (`salary_range` et `duration_months`
manquants) rend **exactement 84**, comme dans le contrat.

### Priorité des sources (table de la mission)

| Priorité | Source | `tier` |
|----------|--------|--------|
| 1 | Page officielle entreprise (`company_career`, `employer_sites`, …) | 1 |
| 2 | ATS officiel (Greenhouse, Lever, Ashby, SmartRecruiters) | 2 |
| 3 | Plateforme partenaire (WJ, JT, Talent, APEC) | 3 |
| 4 | Agrégateur | 4 |
| 5 | Saisie manuelle | 5 |

- **Toutes** les sources sont conservées dans `sources[]`, avec leur
  `provider`, leur `url`, leur `raw_id` et leur confiance propre ;
- `merged_from[]` liste les identités `provider:raw_id` ;
- `canonical_id` est ancré sur la source **la plus officielle** du groupe :
  ajouter une plateforme partenaire ne change pas l'identité, découvrir la
  page officielle de l'employeur la change — et ce changement reste visible
  dans l'historique ;
- les contradictions entre sources restent lisibles dans `contradictions[]` ;
- une source **partenaire** n'est jamais présentée comme une source
  officielle : sa confiance vaut `unverified`, et une offre qui n'a qu'elle
  est `missing` (« aucune source officielle »), pas `contradictory`.

---

## 5. Le rafraîchissement contrôlé

| `force` | Effet |
|---------|-------|
| `false` (défaut) | Ré-évaluation **locale** : comparaison avec le dernier instantané, détection des changements, écriture de l'historique. **Aucun appel réseau.** |
| `true` | Idem + **une** requête HTTP bornée sur l'URL de la source (HEAD, 6 s, corps jamais lu au-delà de 4 Ko). Le statut observé est stocké avec l'heure de vérification. |

La sonde est injectable (`CareerService(..., offer_quality_probe=...)`), ce
qui rend le réseau testable et désactivable. Elle ne requête jamais qu'une
URL `http(s)` et ne renvoie jamais de code d'erreur pour une source
injoignable : une source injoignable est **inconnue**, pas « disparue ».

Le stockage est un **unique fichier JSON local** (`career_data/offer_quality.json`),
écrit de façon atomique, en `0600`, dans le répertoire privé `0700` de
Career. Il est effacé avec le reste de l'espace Career
(`DELETE /api/career/data`). Un fichier corrompu ne casse jamais
l'application : il est traité comme un historique vide.

---

## 6. L'interface

`career_static/js/offer-quality.js` lit le contrat local et ajoute **trois
badges** sur la carte d'une offre :

- **Fraîcheur** — « Fraîche », « Fraîcheur à revérifier », « Fraîcheur
  périmée », « Offre expirée », « Fraîcheur inconnue », avec le nombre de
  jours avant la date limite ;
- **Complétude** — « Complétude 84/100 · 2 manquante(s) » ;
- **Source** — « Source officielle vérifiée · ATS officiel », avec le
  `tier` de la source prioritaire, plus un badge « N source(s)
  dupliquée(s) » quand l'offre est publiée ailleurs.

Le module n'écrit jamais dans une offre et ne déclare jamais une source
« vérifiée » de son propre chef : le statut vient toujours du serveur, qui
applique SK-01.

---

## 7. Vérification

| Commande | Résultat |
|----------|----------|
| `.venv/bin/python -m pytest -q tests/test_offer_quality.py` | **46 passed** |
| `.venv/bin/python -m pytest -q` | **2068 passed, 1 skipped** (base : 2022 passed) |
| `.venv/bin/python -m ruff check .` | **All checks passed** |
| `git diff --check` | propre |

Les 46 tests couvrent : le contrat (forme et sérialisation), la fraîcheur
(fresh / aging / stale / expired / unknown, 404, 5xx, date limite du
texte), la complétude (84 de la mission, 100, 0, durée vide), la confiance
(bord officiel, plateforme partenaire, source absente, provider déclaré
contradictoire), la déduplication (fusion, provenance conservée, page
officielle prioritaire, contradictions visibles, une seule source), les
changements (premier contrôle sans changement, champ modifié, champ
disparu, ordre stable), la pureté (dictionnaire non modifié, verdict
rejouable), le catalogue, le store (snapshot, historique borné, fichier
corrompu, permissions `0600`), les routes HTTP (contrat, offre inconnue,
changement détecté, sonde forcée/non forcée, historique, effacement), et
les garde-fous d'interface.

Aucune régression : les 2022 tests préexistants passent tous, y compris les
suites SK-01, SK-02 et SK-06 amenées par les fusions.

---

## 8. Limites assumées et suites

1. **Pas de scraping automatique.** La sonde ne fait qu'un `HEAD` sur une URL
   déjà connue, et seulement sur demande explicite (`force=true`). SPEC-006
   ne remplace pas un connecteur de board.
2. **La langue des descriptions courtes.** SK-02 détecte parfois mal la
   langue d'une description d'une ligne ; `deadline_hint_from_text` essaie
   donc `auto`, `fr` et `en` et **retient la langue qui lit réellement des
   dates**. Un jour n'est jamais inventé.
3. **La confiance affichée est celle du lien prioritaire.** Quand une offre
   n'a que des sources partenaires, le verdict global est `missing` — le
   détail par source reste dans `sources[]`.
4. **Suites possibles** : brancher `sources[]` sur la carte de l'offre
   (liste des boards qui publient la même annonce), et un badge « conformité
   d'échéance » based sur `days_until_deadline` dans le tableau de bord
   Applications.

---

## 9. Fichiers touchés

**Nouveaux** : `career/offer_quality.py`, `career/offer_quality_store.py`,
`career_static/js/offer-quality.js`, `tests/test_offer_quality.py`,
`docs/agent-reports/SPEC-006-OFFER_QUALITY.md`.

**Modifiés** : `career/service.py` (3 méthodes + catalogue privé + effacement),
`career/router.py` (3 routes + payload), `career_static/index.html`
(script), `career_static/career.js` (appel du module).

**Fusionnés** (dépendances exigées par la mission) : `career/source_trust.py`,
`career/offer_dates.py`, `career/job_deduplication.py` + leurs tests et
fixtures.
