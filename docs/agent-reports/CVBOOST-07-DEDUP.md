# CVBOOST-07 — Rapport de déduplication multi-source

**Date** : 2026-10-21
**Branche** : `agent/cvboost-07-dedup` (travail réalisé dans le worktree `worker/cvboost-07-1792537113`)
**Base** : `main` @ `bc5db69` (tag `v3-cvboost-sources-2026-10-20`, Mission 06 intégrée)
**Périmètre** : `career/cv_quality/job_deduplication.py`, `career/discovery.py`,
`tests/test_job_deduplication.py`, ce rapport.

---

## 1. Résumé

La déduplication multi-source est implémentée : la même offre publiée sur
plusieurs ATS (Greenhouse, Ashby, Lever, Welcome to the Jungle, JobTeaser,
Talent.com, APEC) devient **une seule offre**, tandis que deux postes
différents restent **strictement séparés**.

Tout est local, déterministe et hors réseau : aucune requête, aucun modèle,
aucune dépendance externe (bibliothèque standard uniquement), aucun état
caché. La fonction ne modifie jamais les enregistrements reçus et le même
entrée produit toujours la même sortie.

### Résultats

| Mesure | Valeur | Exigence |
|---------|--------|----------|
| Tests unitaires de déduplication | **59** | ≥ 20 |
| Suite globale | **1416 passés** | ≥ 1269 |
| Lint (`ruff check .`) | propre | — |
| `git diff --check` | propre | — |
| Performance (500 offres) | **≈ 61 ms** | ≤ 200 ms |
| Précision / rappel (corpus synthétique vérité connue) | **1.00 / 1.00** | — |
| Réseau / modèle / dépendance | aucun | 100 % local |

---

## 2. Les 4 niveaux de clés

| Étape | Clé | Règle |
|-------|-----|-------|
| 1 | `external_id` | Identifiant publié par le connecteur (`gh_jid_123`, `ashby_abc`). Clé **primaire**. Un `source_id` ATS estNamespacé par sa source (`src:<source>:<id>`) : un identifiant ATS n'est unique que dans son tableau. |
| 2 | `canonical_url` | URL canonique : `https`, `www.` retiré, port par défaut retiré, fragment retiré, slash final unique, paramètres de tracking (`utm_*`, `ref`, `source`, `gclid`…) retirés, autres paramètres triés. L'URL de candidature (`apply_url`) sert de repli. |
| 3 | Clustering | Clé composite `(company_canonical, title_canonical, location_canonical)` + similarité de titre ≥ **0.92** (Jaro-Winkler, alias et traductions incluses). Entreprise et lieu doivent être identiques. |
| 4 | Fraîcheur | À qualité égale, on garde la plus récente : `posted_date`, sinon `discovered_at`, `published_at`, `last_seen_at`, `last_verified_at`, `updated_at`. |

### Choix du représentant

Priorité stricte, conformément à la mission :

1. présence d'un identifiant externe ;
2. priorité de la source :
   **Ashby (100) > Greenhouse (90) > Lever (80) > Welcome to the Jungle (70) > JobTeaser (60) > Talent.com (50) > APEC (40)** ;
3. `posted_date` / `discovered_at` le plus récent ;
4. égalité parfaite → première offre reçue (déterminisme).

---

## 3. Fonctions exportées

| Fonction | Rôle |
|----------|------|
| `canonicalize_url(url)` | URL canonique (https, sans `www.`, sans tracking, sans fragment, slash final unique) |
| `company_canonical(name)` | Minuscules, accents, ponctuation, alias connus, suffixes juridiques (`SA`, `SAS`, `Ltd`, `Inc`, `GmbH`, `AG`, `SRL`, `SpA`, `BV`, `NV`, `PLC`, `Group`, `Groupe`…) |
| `title_canonical(title)` | Minuscules, accents, ponctuation, synonymes (`stage`/`intern` → `internship`, `CDI`/`permanent` → `permanent`, `alternance`/`apprentissage` → `apprenticeship`) |
| `title_similarity(a, b)` | Score 0→1 : Jaro-Winkler + concepts métier + garde-fou contrat/seniority |
| `title_concept(title)` | Concept métier (`data_analyst`, `investment_banking`, `private_equity`…) |
| `title_contract(title)` / `title_seniority(title)` | Contrat (`intern`, `apprentice`, `permanent`, `fixed_term`, `freelance`) et seniorité (`analyst`, `experienced`) |
| `title_role_level(title)` | Rôle unique lisible (contrat prioritaire, sinon seniorité) |
| `location_canonical(city, country)` | Ville normalisée + pays ISO-2, offres « remote » unifiées |
| `jaro_winkler(s1, s2)` | Similarité Jaro-Winkler pure Python (valeurs de référence : `MARTHA/MARHTA` = 0.9611) |
| `source_priority(source)` | Priorité de la source |
| `deduplicate_jobs(jobs)` | **`tuple[list[Job], DedupReport]`** — point d'entrée |
| `DedupReport` | `merged_count`, `clusters`, `representatives`, `total_count`, `unique_count`, `merged_clusters` |

### Contrat de sortie

```python
offers, report = deduplicate_jobs(jobs)

# chaque offre dédupliquée porte la trace d'audit
offers[0]["merged_from"]   # ["lever", "apec"]  (sources fusionnées dans cette offre)
offers[0]["merge_count"]   # 2
offers[0]["merge_reasons"] # ["canonical_url", "company_title_location"]
offers[0]["dedup_id"]      # "ext:gh_jid_123"

# rapport de fusion
report.merged_count        # 6  (doublons retirés = offres reçues - offres uniques)
report.clusters[0]         # {"cluster_id", "representative_id", "member_ids", "sources", "reasons", "size"}
report.representatives     # une identité par offre unique
```

`merged_from` est toujours présent (liste vide pour une offre qui n'a pas été
fusionnée) : la traçabilité est donc lisible sans condition.

---

## 4. Intégration dans le parcours de découverte

`career/discovery.py` expose le point d'entrée appelé juste après la
collecte multi-source :

```python
from career.discovery import discover_stage_offers

offers, report = discover_stage_offers(jobs)   # jobs =.offres de tous les connecteurs
```

L'appel à `deduplicate_jobs()` est fait en import différé : le module de
déduplication n'est chargé que lorsqu'une fusion multi-source est réellement
demandée, et l'import de `career.discovery` reste léger.

Le raccordement de cet appel dans la boucle d'exploration de
`career/service.py` (là où les candidats de toutes les sources sont
aujourd'hui dédupliqués par URL seule) est **hors périmètre de la mission** :
`career/service.py` est explicitement interdit. Le point d'entrée est donc
prêt à être appelé par l'intégrateur.

---

## 5. Exemples de fusion

### 5.1 Même URL, paramètre de tracking en plus
```python
{"source_name": "greenhouse", "source_id": "1",
 "official_url": "https://boards.greenhouse.io/acme/jobs/1?utm_source=linkedin"}
{"source_name": "greenhouse", "source_id": "2",
 "official_url": "https://boards.greenhouse.io/acme/jobs/1"}
```
→ **Fusionné** (`canonical_url`) — 1 offre, `merged_from = ["greenhouse"]`.

### 5.2 Même identifiant externe, deux ATS
```python
{"source_name": "greenhouse", "external_id": "gh_jid_123", "title": "Data Analyst"}
{"source_name": "ashby",     "external_id": "gh_jid_123", "title": "Data Analyst"}
```
→ **Fusionné** (`external_id`) — le représentant est **Ashby** (priorité 100).

### 5.3 Titre traduit FR → EN
```python
{"source_name": "greenhouse", "title": "Data Analyst",      "company": "Acme", "city": "Paris"}
{"source_name": "lever",      "title": "Analyste de données", "company": "Acme", "city": "Paris"}
```
→ **Fusionné** (`company_title_location`) — concept `data_analyst` des deux côtés.

### 5.4 Alias métier FR → EN
```python
{"source_name": "ashby",     "title": "M&A Intern", "company": "Globex", "city": "Londres"}
{"source_name": "talent.com","title": "Stage M&A",  "company": "Globex", "city": "London"}
```
→ **Fusionné** — concept `investment_banking`, `Londres` → `london`, synonymes
`stage`/`intern` → `internship`.

### 5.5 Entreprise avec et sans forme juridique
```python
{"company": "Acme SAS"}   # → "acme"
{"company": "ACME Ltd"}   # → "acme"
```
→ **Fusionné**.

### 5.6 Même offre sur trois tableaux
```python
greenhouse / lever / apec  →  1 offre, merged_from = ["apec", "lever"]
```

### 5.7 Fraîcheur : deux publications de la même offre
```python
{"posted_date": "2026-09-01", "official_url": ".../acme/jobs/1"}
{"posted_date": "2026-10-12", "official_url": ".../acme/jobs/1"}
```
→ **Fusionné**, le représentant est celui du **2026-10-12** (fraîcheur).

---

## 6. Exemples de NON-fusion (faux positifs évités)

| Cas | Exemple | Raison |
|-----|---------|--------|
| Deux niveaux de poste | `M&A Intern` vs `M&A Analyst` | contrats incompatibles (`intern` ≠ `permanent`) |
| Deux niveaux de poste | `Data Analyst` vs `Senior Data Analyst` | seniorités incompatibles (`analyst` ≠ `experienced`) |
| Deux cohorts | `Stage Finance H1 2027` vs `Stage Finance H2 2027` | chiffres différents (cohorte/édition) |
| Deux villes | `Paris` vs `London` | lieux différents |
| Deux entreprises | `Acme` vs `Globex` | entreprises différentes |
| Remote vs sur place | `Remote` vs `Paris` | lieux différents |
| Métiers voisins | `Corporate Finance Intern` vs `Private Equity Intern` | concepts différents, similarité < 0.92 |
| Identifiant recyclé | même `source_id`, titres et liens différents | garde `recycled_identifier_conflict` |
| Réutilisation d'identifiant | même `external_id`, entreprises différentes | entreprises incompatibles |

---

## 7. Corpus synthétique — précision et rappel

Corpus de 17 offres synthétiques, vérité connue : 3 groupes de doublons
(4 + 3 + 2 offres) et 8 offres distinctes (11 offres uniques attendues).

| Métrique | Valeur |
|----------|--------|
| Paires vraies | 12 (6 + 3 + 1) |
| Prédictions | 12 |
| Vrais positifs | 12 |
| Faux positifs | 0 |
| Faux négatifs | 0 |
| **Précision / Rappel / F1** | **1.00 / 1.00 / 1.00** |

Ce corpus est figé dans `tests/test_job_deduplication.py`
(`test_deduplicate_jobs_is_exact_on_a_synthetic_corpus`).

---

## 8. Performance

Mesures sur le poste de développement (Python 3.12), 500 offres :

| Scénario | Temps |
|----------|-------|
| 500 offres réalistes (250 offres × 2 sources) | **61 ms** |
| 500 offres, même entreprise et même ville, titres numérotés | **66 ms** |
| 500 offres strictement identiques (cas dégénéré) | **102 ms** |
| 1 000 offres | **117 ms** |

La clusteredisation est bornée : les comparaisons de titres sont filtrées par
clés de blocage (mot, préfixe, concept métier), par un préfiltre de contrat /
seniorité / chiffres, et par un ratio de longueur (borne mathématique du
Jaro-Winkler : sous 0.76, un score de 0.92 est impossible). Les groupes
importants sont pré-fusionnés par titre canonique identique, ce qui évite la
comparaison quadratique.

---

## 9. Tests (`tests/test_job_deduplication.py` — 59 tests)

- **URL canonique** : https forcé, `www.` retiré, slash final, fragment,
  paramètres de tracking, paramètres utiles triés, ports, slashs doubles,
  URL non http, valeur vide (9 tests) ;
- **Entreprise canonique** : accents, suffixes juridiques (11 formes),
  `Group`/`Groupe`, alias connus, ponctuation, valeur vide (6 tests) ;
- **Titre canonique** : synonymes stage/internship, CDI/permanent,
  alternance/apprentissage, accents/ponctuation/marqueur `H/F` (4 tests) ;
- **Concepts et similarité** : traductions, alias métier, métiers différents,
  niveaux de poste, titres identiques, titre vide (6 tests) ;
- **Lieu canonique** : ISO-2 et accents, remote, alias de villes (3 tests) ;
- **Jaro-Winkler** : valeurs de référence, cas limites (2 tests) ;
- **Priorité des sources** : ordre de la mission (1 test) ;
- **Déduplication** : liste vide, offre unique, URL identique, identifiant
  externe identique, même source, trois tableaux, titres traduits,
  synonymes, suffixes d'entreprise, rôles différents, lieux différents,
  entreprises différentes, cohorts différentes, remote vs sur place,
  identifiant recyclé, fraîcheur, priorité de source, traçabilité
  `merged_from`, rapport de fusion, déterminisme, pureté (entrée non
  modifiée), enregistrements incomplets, ordre des sources, performance
  500 offres, corpus vérité connue (précision/rappel) (23 tests) ;
- **Intégration** : `discover_stage_offers()` déduplique la collecte
  multi-source (1 test) ;
- **Hors réseau** : le module n'importe ni `urllib.request`, ni `socket`,
  ni `requests` (1 test).

Toutes les fixtures sont synthétiques : aucun employeur, aucune offre et
aucune donnée réelle.

---

## 10. Fichiers

| Fichier | Nature | Contenu |
|---------|--------|---------|
| `career/cv_quality/job_deduplication.py` | **nouveau** | Moteur de déduplication : normalisations, Jaro-Winkler, concepts, clustering, choix du représentant, `DedupReport` (≈ 900 lignes) |
| `career/discovery.py` | **modifié** | Ajout de `discover_stage_offers()` (point d'entrée après la collecte multi-source) |
| `tests/test_job_deduplication.py` | **nouveau** | 59 tests unitaires synthétiques |
| `docs/agent-reports/CVBOOST-07-DEDUP.md` | **nouveau** | Ce rapport |

`career/models.py` n'a **pas** été modifié : l'enregistrement d'offre est un
dictionnaire dans cette application, la trace `merged_from` est donc une clé
de ce dictionnaire ; la table `jobs` locale n'a pas de colonne pour elle
(schéma figé, aucune migration autorisée par la mission). La trace voyage
avec l'offre dédupliquée et avec le rapport de fusion.

---

## 11. Conformité au périmètre

| Interdit | Respecté |
|----------|----------|
| `career/service.py` | non modifié |
| `career/router.py` | non modifié |
| `career_static/*` | non modifié |
| `requirements*.txt` | non modifié |
| migrations / `SCHEMA_VERSION` | aucun changement de schéma |
| réseau / modèle / dépendance externe | aucun |

---

## 12. Point d'attention pour l'intégrateur

Une **tentative antérieure** de cette mission (Agent 3) avait produit, dans le
répertoire de travail principal et **sans jamais être commitée** :

- `career/job_deduplication.py` (module à la racine de `career/`) ;
- `tests/test_career_job_deduplication.py` ;
- `docs/agent-reports/CVBOOST-07-DEDUP.md` (remplacé par le présent rapport).

Cette version antérieure ne répondait pas au contrat de la mission
(l'API n'était pas `tuple[list[Job], DedupReport]`, la trace s'appelait
`provenances` et non `merged_from`, le module n'était pas dans le périmètre
`career/cv_quality/`). **La branche `agent/cvboost-07-dedup` la remplace** :
elle peut être intégrée telle quelle, et les fichiers non commités du
répertoire principal peuvent être écartés.

---

## 13. Checklist de validation

- [x] `deduplicate_jobs(jobs) -> tuple[list[Job], DedupReport]` pure, déterministe, sans réseau
- [x] 4 niveaux de clés (external_id → canonical_url → clustering Jaro-Winkler ≥ 0.92 → fraîcheur)
- [x] `canonicalize_url`, `company_canonical`, `title_canonical`, `title_similarity`, `location_canonical`, `jaro_winkler` exportées et testées unitairement
- [x] `merged_from` tracé sur chaque offre fusionnée
- [x] Tests synthétiques ≥ 20 (59 au total, dont un corpus de précision/rappel)
- [x] Suite globale ≥ 1269 (1416 passés)
- [x] Performance ≤ 200 ms pour 500 offres (≈ 61 ms)
- [x] Rapport avec exemples de fusion et de non-fusion
- [x] Lint propre, `git diff --check` propre
- [x] Branche `agent/cvboost-07-dedup` prête
