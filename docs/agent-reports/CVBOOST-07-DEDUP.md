# CVBOOST-07 : Rapport de déduplication multi-source

**Date** : 2026-10-21  
**Branche** : `agent/cvboost-07-dedup`  
**Auteur** : Agent 3

---

## Résumé

Implémentation de la déduplication robuste multi-source pour fusionner les vraies doublons provenant de plusieurs ATS (Greenhouse, Ashby, Lever, Welcome to the Jungle, JobTeaser, Talent.com, APEC) sans fusionner deux postes différents.

### Résultats des tests
- ✅ **64 tests unitaires** de déduplication (tous passent)
- ✅ **1322 tests** dans la suite globale (≥ 1269 requis)
- ✅ **Performance** : < 50 ms pour 500 offres (bien en deçà du seuil de 200 ms)

---

## Algorithme implémenté

### 4 niveaux de clés (déterministe, 100% local)

| Étape | Clé | Description |
|-------|-----|-------------|
| 1 | `external_id` | Identifiant fourni par le connecteur (ex: `gh_jid_123`, `ashby_abc`) — clé primaire si présent |
| 2 | `canonical_url` | URL normalisée (HTTPS, sans www, sans params tracking `utm_*`, `gclid`, `ref`, `source`, sans fragment, slash final unique) |
| 3 | Clustering | Similarité Jaro-Winkler ≥ 0.92 sur `(company_canonical, title_canonical, location_canonical)` |
| 4 | Fraîcheur | Si tout correspond, garder la plus récente (`last_verified_at` > `posted_date`) |

### Sélection du représentant
Priorité : `source_tier` (employer > official boards) → `freshness` → `source_priority` (Ashby=100 > Greenhouse=90 > Lever=80 > WelcomeJungle=70 > JobTeaser=60 > Talent.com=50 > APEC=40) → `verified` → `completeness`

### Traçabilité
Chaque offre fusionnée conserve `merged_from: list[source_name]` via le champ `provenances` dans le groupe de déduplication.

---

## Fonctions exportées (testées unitairement)

| Fonction | Rôle |
|----------|------|
| `canonicalize_url(url)` | Normalisation URL canonique |
| `company_canonical(name)` | Normalisation entreprise (minuscules, accents, suffixes juridiques) |
| `title_canonical(title)` | Normalisation titre (synonymes FR/EN: stage/internship, CDI/permanent, alternance/apprentissage) |
| `location_canonical(city, country)` | Normalisation lieu (pays ISO-2, ville normalisée, remote unifié) |
| `canonical_title_concept(title)` | Mapping titre → concept métier (investment_banking, private_equity, asset_management, etc.) |
| `title_role_level(title)` | Extraction niveau rôle (intern, analyst, experienced, permanent) |
| `jaro_winkler(s1, s2)` | Similarité Jaro-Winkler pure Python |
| `match_records(a, b)` | Décision pairwise de fusion |
| `deduplicate_jobs(jobs)` | Déduplication complète → liste de groupes + rapport |
| `choose_best(records)` | Choix du représentant |
| `evaluate_deduplication(records, truth)` | Évaluation precision/recall/F1 |

---

## Exemples de fusion (merged = True)

### 1. Même URL avec paramètres de tracking
```python
# Greenhouse avec UTM
{"source_name": "greenhouse", "source_id": "4012345", 
 "official_url": "https://job-boards.greenhouse.io/lincolninternational/jobs/4012345?utm_source=linkedin&utm_campaign=2027",
 "company": "Lincoln International", "title": "M&A Intern", "city": "Paris"}

# Greenhouse sans tracking
{"source_name": "greenhouse", "source_id": "4012345",
 "official_url": "https://job-boards.greenhouse.io/lincolninternational/jobs/4012345",
 "company": "Lincoln International", "title": "M&A Intern", "city": "Paris"}
```
→ **Fusionné** (raison: `canonical_url_match`)

### 2. Même offre sur deux ATS différents
```python
# Greenhouse
{"source_name": "greenhouse", "source_id": "4012345",
 "official_url": "https://job-boards.greenhouse.io/lincolninternational/jobs/4012345",
 "company": "Lincoln International", "title": "M&A Intern", "city": "Paris"}

# Lever
{"source_name": "lever", "source_id": "a1b2c3",
 "official_url": "https://jobs.lever.co/lincoln-international/a1b2c3",
 "company": "Lincoln International", "title": "M&A Intern", "city": "Paris"}
```
→ **Fusionné** (raison: `company_title_location_cluster`, Jaro-Winkler=1.0 sur concept `investment_banking`)

### 3. Titre traduit FR/EN
```python
# Manuel FR
{"source_name": "manual", "title": "Stage Banque d'Affaires H1 2027", "company": "Rothschild & Co", "city": "Paris"}

# Greenhouse EN
{"source_name": "greenhouse", "source_id": "55", "title": "M&A Intern", "company": "Rothschild & Co", "city": "Paris"}
```
→ **Fusionné** (raison: `company_title_location_cluster`, concept `investment_banking` des deux côtés)

### 4. Alias entreprise
```python
# J.P. Morgan
{"source_name": "manual", "company": "J.P. Morgan", "title": "Stage Banque d'Affaires", "city": "Paris"}

# JPMorgan Chase & Co.
{"source_name": "lever", "source_id": "jpm1", "company": "JPMorgan Chase & Co.", "title": "Investment Banking Intern", "city": "Paris"}
```
→ **Fusionné** (company_canonical → `jpmorgan` pour les deux)

### 5. Même apply_url
```python
# Greenhouse
{"apply_url": "https://job-boards.greenhouse.io/lincolninternational/jobs/4099/apply", ...}

# Lever (board différent mais même lien de candidature)
{"apply_url": "https://job-boards.greenhouse.io/lincolninternational/jobs/4099/apply", ...}
```
→ **Fusionné** (raison: `apply_url_match`)

### 6. Ville métrononyme / traduction
```python
# "Paris La Défense" vs "Paris"
{"city": "Paris La Défense", "country": "France"}  → canonical: "paris,fr"
{"city": "Paris", "country": "France"}              → canonical: "paris,fr"
```
→ **Fusionné** (location_canonical unifie)

### 7. Remote variants
```python
# "Remote — Europe" vs "Télétravail"
{"city": "Remote — Europe"}  → canonical: "remote"
{"city": "Télétravail"}      → canonical: "remote"
```
→ **Fusionné**

### 8. Dates divergentes sur même URL
```python
# Même source_id, même URL, posted_date différent
{"source_id": "801", "official_url": "...", "posted_date": "2026-09-14"}
{"source_id": "801", "official_url": "...", "posted_date": "2026-10-01"}
```
→ **Fusionné** (conflit `posted_date` conservé visible dans `conflicts`)

---

## Exemples de NON-fusion (merged = False)

### 1. Deux niveaux différents (stagiaire vs analyste)
```python
{"title": "Stage M&A Paris", "role_level": "intern", ...}
{"title": "M&A Analyst", "role_level": "analyst", ...}
```
→ **Non fusionné** (raison: `role_level_conflict`)

### 2. Identifiant recyclé (même source_id, titre différent)
```python
{"source_id": "6001", "title": "M&A Intern 2027", "city": "London", "official_url": ".../6001"}
{"source_id": "6001", "title": "Private Equity Intern 2028", "city": "London", "official_url": ".../6001-reused"}
```
→ **Non fusionné** (raison: `recycled_identifier_conflict`, flag `identifier_collision=True`)

### 3. Identifiant recyclé (ville différente)
```python
{"source_id": "6100", "city": "London", "official_url": ".../6100"}
{"source_id": "6100", "city": "Milan", "official_url": ".../6100-v2"}
```
→ **Non fusionné** (raison: `recycled_identifier_conflict`)

### 4. Faux voisins : même entreprise, équipes différentes
```python
{"company": "Lazard", "title": "M&A Intern", "city": "Paris"}
{"company": "Lazard", "title": "Private Equity Intern", "city": "Paris"}
```
→ **Non fusionné** (raison: `different_role_same_employer`, Jaro-Winkler < 0.92)

### 5. Faux voisins : familles de métiers différentes
```python
{"company": "Union Bancaire Privée", "title": "Corporate Finance Intern", "city": "Geneva"}
{"company": "Union Bancaire Privée", "title": "Asset Management Intern", "city": "Geneva"}
```
→ **Non fusionné** (raison: `different_role_same_employer`)

### 6. Conflit entreprise (noms similaires)
```python
{"company": "Lincoln International", "title": "M&A Intern", "city": "Paris"}
{"company": "AlixPartners", "title": "M&A Intern", "city": "Paris"}
```
→ **Non fusionné** (raison: `company_conflict`)

### 7. Remote vs ville physique
```python
{"city": "Remote", "company": "Qube Research"}
{"city": "Milan", "company": "Qube Research"}
```
→ **Non fusionné** (raison: `city_conflict`)

### 8. Titres faibles sans identité partagée
```python
{"company": "Apprentie Finance", "title": "Sustainability Reporting Intern"}
{"company": "Apprentie Finance", "title": "Sustainability Focus Intern"}
```
→ **Non fusionné** (raison: `no_shared_identity`, concepts inconnus, Jaro-Winkler=0.89 < 0.92)

---

## Structure de sortie

```python
[
    {
        "dedup_id": "source:greenhouse:4012345",      # Clé stable
        "merged": True,                                # True si fusion
        "best": {...},                                 # Représentant élu
        "provenances": [                               # Toutes les sources
            {"source_name": "greenhouse", "source_id": "4012345", 
             "official_url": "...", "record": {...}, "weight": 90},
            {"source_name": "lever", "source_id": "a1b2c3", ...},
            {"source_name": "manual", "source_id": "", ...}
        ],
        "conflicts": {                                 # Champs divergents
            "posted_date": {
                "greenhouse:4012345": "2026-09-30",
                "lever:a1b2c3": "2026-10-01"
            }
        },
        "match_reasons": ["canonical_url_match", "company_title_location_cluster"],
        "identifier_collision": False,                 # True si ID recyclé détecté
        "member_indexes": [0, 1, 2]                    # Indices originaux
    }
]
```

---

## Métriques de qualité (corpus synthétique)

| Métrique | Valeur |
|----------|--------|
| Précision | 1.000 |
| Rappel | 1.000 |
| F1-score | 1.000 |
| Vrais positifs (paires) | 24 |
| Erreurs | 0 |

Corpus : 59 enregistrements, 22 vrais groupes (1 triple + 21 paires), 14 singletons.

---

## Fichiers modifiés

| Fichier | Changement |
|---------|------------|
| `career/job_deduplication.py` | **Nouveau** — Logique complète de déduplication (600+ lignes) |
| `career/discovery.py` | Ajout import + fonction `discover_stage_offers()` |
| `tests/test_career_job_deduplication.py` | Existant — 64 tests synthétiques (43 paires + groupes + évaluation) |

---

## Validation checklist

- [x] `deduplicate_jobs(jobs)` pure, déterministe, sans réseau
- [x] 4 niveaux de clés + fraîcheur
- [x] `canonicalize_url`, `company_canonical`, `title_canonical`, `location_canonical`, `canonical_title_concept`, `title_role_level`, `jaro_winkler` exportées et testées
- [x] `merged_from` tracé via `provenances` sur chaque offre fusionnée
- [x] Tests synthétiques ≥ 20 (43 paires + 10 groupes + évaluation = 64 tests)
- [x] Suite globale ≥ 1269 tests (1322 passés)
- [x] Rapport avec exemples fusion / non-fusion
- [x] Branche `agent/cvboost-07-dedup` prête

---

## Prochaines étapes

L'intégration dans le flux `service.py` (appel de `discover_stage_offers` après la collecte multi-source dans la boucle d'exploration) reste à faire côté application, mais la logique de déduplication est complète, testée et documentée.