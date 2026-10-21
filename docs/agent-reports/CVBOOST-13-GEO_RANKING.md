# CVBOOST-13 — Ranking géographique (Boost étranger, Pénalité France)

> **Mission** : 13 — Ranking géographique (Boost étranger, Pénalité France)
> **Branche** : `agent/cvboost-13-geo-ranking-v2`
> **Base** : `main` (3a0d1ee)
> **Livré** : score géographique déterministe (pénalité France `-50`, boost pays ciblé `+20`, neutre `0`), intégré au classement de la découverte, configurable par le brief.
> **Validation** : `pytest -q` → **1387 passed, 1 skipped** (aucune régression) · `ruff check .` → **All checks passed** · `git diff --check` → propre.

---

## 1. Pourquoi cette mission

Le filtre connecteur (Mission 11) pousse `countries_exclude=["FR"]` **côté source**. Il reste
néanmoins des offres France qui passent (données incomplètes : `country` vide, libellé inattendu,
connecteur qui ne publie pas le pays). Le classement doit alors **refuser de mettre la France
en tête**, même quand l'adéquation compétences est parfaite.

C'est exactement ce que fait cette mission : le pays devient un **signal de classement
explicite, borné et justifié**, jamais une inférence.

---

## 2. Règles produit implémentées

| Règle | Implémentation | Preuve |
|---|---|---|
| **Pénalité France forte** : `country = FR` → `-50` points | `GEO_EXCLUDED_PENALTY = -50` | `test_france_penalty_50` |
| **Boost pays ciblés** : pays du brief → `+20` points (une seule fois) | `GEO_PREFERRED_BOOST = 20` | `test_preferred_country_boost_20`, `test_multiple_preferred_is_not_cumulative` |
| **Neutre** : pays ni exclu ni ciblé → `0` | `geo_score_for()` | `test_neutral_country` |
| **Transparence** : `geo_score`, `geo_reason`, `country` dans le résultat | `QualifiedOffer.geo_score/geo_reason` | `test_geo_reason_is_visible_in_the_qualification` |
| **Pas de géo-inférence** : le pays n'est jamais déduit d'une ville | `country_code_for()` : liste fermée de pays ; `"Frankfurt"` → pays inconnu | `test_frankfurt_is_not_france`, `test_no_geographic_inference_from_the_city` |
| **Configurable par le brief** | `preferred_countries` + `geo_excluded_countries` | `test_preferred_override_default`, `test_excluded_override_default` |
| **Score borné 0-100** | `total_score = max(0, min(100, base + geo))` | `test_score_is_bounded_between_0_and_100` |
| **France jamais en tête** | Le classement place toute offre pénalisée **après** toutes les autres | `test_france_never_leads_the_ranking` |

Règle de priorité : **exclu > ciblé**. Un pays à la fois exclu et ciblé est pénalisé (jamais
récompensé). Les points ne se cumulent jamais.

---

## 3. Adaptation au code réel (le prompt d'origine décrivait une API différente)

Le prompt de mission partait d'une API qui n'existe pas dans ce dépôt. Voici la correspondance
réelle retenue, sans jamais sortir du périmètre autorisé :

| Prompt d'origine | Code réel | Décision |
|---|---|---|
| `qualify_offer(job, brief) -> OfferQualification.total_score` | `career/offer_qualification.py` : `qualify_offer(offer, *, ...) -> QualifiedOffer` (dataclass figée, sans score) | `geo_score` / `geo_reason` ajoutés à `QualifiedOffer` (champs par défaut, donc compatibles) ; le score total est calculé côté classement |
| `Brief` / `Job` | `dict[str, Any]` | le brief est le dictionnaire normalisé de `career/stage_search.py` |
| `StageSearchPayload` dans `career/models.py` | la classe est dans **`career/router.py`**, explicitement **interdit** de modification | la configuration passe par le brief (`default_brief` / `validate_brief`) ; les listes de pays sont exposées dans le **vocabulaire** (payload JSON libre) |
| `discover_ranked()` dans `career/discovery.py` | `GreenhouseJobBoardConnector.discover_ranked()` + `_normalise()` | le tri de sélection utilise `total_score` et un rang géographique |

Fichiers modifiés (périmètre autorisé, rien de plus) :

| Fichier | Modification |
|---|---|
| `career/models.py` | `DEFAULT_PREFERRED_COUNTRIES`, `DEFAULT_GEO_EXCLUDED_COUNTRIES`, `GEO_PREFERRED_BOOST`, `GEO_EXCLUDED_PENALTY` |
| `career/offer_qualification.py` | `country_code_for()`, `geo_score_for()`, `QualifiedOffer.geo_score/geo_reason`, paramètres `preferred_countries` / `geo_excluded_countries` de `qualify_offer()` |
| `career/stage_search.py` | brief : `preferred_countries` + `geo_excluded_countries` ; vocabulaire ; `score_brief_match()` renvoie `geo_score`, `geo_reason`, `total_score` |
| `career/discovery.py` | clé de tri : pays pénalisé en dernier, puis `total_score`, puis `geo_score` |
| `tests/test_geo_ranking.py` | **nouveau** — 20 tests synthétiques, 100 % offline |
| `docs/agent-reports/CVBOOST-13-GEO_RANKING.md` | ce rapport |

---

## 4. Fonctionnement détaillé

### 4.1 Lecture du pays (aucune inférence)

`country_code_for()` (`career/offer_qualification.py`) normalise une valeur de source vers un code
ISO-2, via une **liste fermée** de noms de pays (français, anglais, allemand) et de codes :

* `"France"`, `"fr"`, `"FRA"`, `"République Française"` → `FR`
* `"Deutschland"` → `DE` · `"United Kingdom"` → `GB` · `"Nederland"` → `NL`
* `"Frankfurt"`, `"Paris"`, `"Luxembourg City"` (sans pays explicite) → `""` (**pays inconnu**)

Le token est searched dans la liste ; aucun mot n'est converti en pays s'il n'est pas dans la
table. Une ville ne prouve jamais un pays.

### 4.2 Signal géographique

```python
geo_score, geo_reason = geo_score_for(
    country,
    preferred_countries=brief.get("preferred_countries"),
    excluded_countries=brief.get("geo_excluded_countries"),
)
# ("FR", ["FR"], []) -> (-50, "Pays exclu (FR)")
# ("DE", ["DE"], ["FR"]) -> (+20, "Pays ciblé (DE)")
# ("US", ["DE"], ["FR"]) -> (0, "Pays neutre (US)")
# ("", ...) -> (0, "Pays inconnu")
```

Le signal est **strictement un signal de classement** : il ne change jamais `target_status`,
ne rend jamais une offre non conforme, et ne filtre rien. L'exclusion dure reste décidée par le
brief (`excluded_countries` / `excluded_cities`), la Mission 11 filters en amont côté source.

### 4.3 Configuration par le brief

`career/stage_search.py` :

```python
"preferred_countries": ["DE", "GB", "CH", "NL", "LU", "BE", "IE", "AT", "SE", "NO", "DK", "FI",
                         "ES", "IT", "PT", "PL", "CZ", "HU", "RO", "BG", "HR", "SI", "SK", "EE",
                         "LV", "LT", "MT", "CY"],   # 28 pays UE/EEA/R-U
"geo_excluded_countries": ["FR"],
```

Règle de résolution (explicite, testée) :

1. `geo_excluded_countries` présent dans le brief → il gagne (même vide : la pénalité est coupée) ;
2. sinon `excluded_countries` présent → la liste d'exclusions de la personne sert aussi de liste
   de penalisation ;
3. sinon → défaut `["FR"]`.

Une liste de pays exclue **explicitement vide** désactive donc la pénalité France : le
« Zéro France » est un défaut, jamais une règle cachée.

### 4.4 Classement (`career/discovery.py`)

`score_brief_match()` renvoie désormais, en plus du score de pertinence :

| Clé | Sens |
|---|---|
| `score` | pertinence (inchangée : aucun test existant n'est impacté) |
| `geo_score` | points géographiques (`-50`, `+20` ou `0`) |
| `geo_reason` | raison lisible (`"Pays exclu (FR)"`) |
| `total_score` | `max(0, min(100, score + geo_score))` — le score utilisé par le classement |

La clé de tri de la sélection Greenhouse est devenue :

```python
key = (geo_rank, status_rank, -total_score, -geo_score, education_rank, job_id, canonical, digest)
```

* `geo_rank = 1` pour un pays pénalisé → **toute offre France passe après toutes les autres**,
  quelle que soit sa pertinence (contrainte produit n°1) ;
* `status_rank` : conforme avant « à vérifier » (règle métier existante) ;
* `total_score` : pertinence + signal géographique ;
* `-geo_score` : à score total identique, un pays ciblé passe devant un pays neutre
  (le plafond 100/100 rend sinon le boost invisible) ;
* identité de source et empreinte : jamais l'ordre d'arrivée.

---

## 5. Exemple de classement avant / après (mesuré, synthétique)

Cinq offres « M&A Intern » strictement équivalentes, brief = `{domains: ["M&A"], preferred_countries: ["DE", "NL"]}` :

| Offre | Pays | score base | geo | total | Rang final |
|---|---|---:|---:|---:|---:|
| `de-berlin` | Berlin, Germany | 100 | **+20** | 100 | **1** |
| `nl-ams` | Amsterdam, Netherlands | 100 | **+20** | 100 | **2** |
| `us-ny` | New York, United States | 100 | 0 | 100 | 3 |
| `fr-lyon` | Lyon, France | 100 | **-50** | 50 | 4 |
| `fr-paris` | Paris, France | 100 | **-50** | 50 | 5 |

**Avant** (score de pertinence seul) : les cinq offres étaient à égalité (100) — l'ordre était
dicté par l'identifiant de source, la France pouvait apparaître en tête.
**Après** : les deux offres France descendent en fin de liste, l'Allemagne et les Pays-Bas
remontent, les États-Unis restent neutres.

---

## 6. Tests

`tests/test_geo_ranking.py` — **20 tests**, synthétiques et 100 % offline (aucun réseau, aucun
appel de modèle, aucune donnée réelle).

| # | Test | Ce qu'il prouve |
|---|---|---|
| 1 | `test_france_penalty_50` | FR → `-50`, `total_score = score - 50` |
| 2 | `test_preferred_country_boost_20` | DE ciblé → `+20` |
| 3 | `test_multiple_preferred_is_not_cumulative` | NL listé 2 fois → `+20` une seule fois |
| 4 | `test_neutral_country` | US ni ciblé ni exclu → `0` |
| 5 | `test_country_unknown_neutral` | sans pays → `0`, raison « Pays inconnu » |
| 6 | `test_frankfurt_is_not_france` | `"Frankfurt"` → pays inconnu, jamais `-50` |
| 7 | `test_no_geographic_inference_from_the_city` | ville seule → aucune inférence |
| 8 | `test_preferred_override_default` | sans liste explicite → défaut UE (28 pays) |
| 9 | `test_excluded_override_default` | liste vide explicite → pénalité coupée |
| 10 | `test_explicit_geo_exclusion_list_wins` | la liste géographique prime |
| 11 | `test_brief_defaults_penalize_france_and_reward_europe` | défaut `["FR"]`, `validate_brief({}) == default_brief()` |
| 12 | `test_vocabulary_exposes_the_country_lists` | le formulaire peut afficher les pays |
| 13 | `test_geo_reason_is_visible_in_the_qualification` | `geo_score` / `geo_reason` / `country` dans le résultat |
| 14 | `test_score_is_bounded_between_0_and_100` | `0 ≤ total_score ≤ 100` |
| 15 | `test_geo_signal_never_changes_admissibility` | la pénalité ne rend pas l'offre non conforme |
| 16 | `test_geo_score_for_is_pure_and_explicit` | fonction pure, exclu > ciblé |
| 17 | `test_france_never_leads_the_ranking` | la France n'est jamais en tête |
| 18 | `test_ranking_integration_uses_the_total_score` | ordre `DE > US > FR` |
| 19 | `test_preferred_country_climbs_over_a_neutral_one` | un pays ciblé remonte |
| 20 | `test_internship_selection_reports_the_geographic_signal` | la qualification de stage porte le signal |

Commandes exécutées :

```bash
.venv/bin/python -m pytest -q tests/test_geo_ranking.py   # 20 passed
.venv/bin/python -m pytest -q                              # 1387 passed, 1 skipped
.venv/bin/python -m ruff check .                           # All checks passed
git diff --check                                           # propre
```

---

## 7. Limites connues et suites recommandées (pour le relecteur / Mission 10)

1. **Classement des offres déjà enregistrées** — `career/exploration.py::ranking_key()`, utilisé par
   `CareerService.list_stage_matches()`, trie encore sur le score de pertinence seul. Le signal
   géographique est calculé et exposé (`total_score`, `geo_score`, `geo_reason` dans chaque
   correspondance) mais n'est pas encore appliqué à cet ordre. `career/exploration.py` ne fait
   pas partie du périmètre autorisé de la Mission 13 : **intégrateur, appliquer `total_score`
   (et `geo_rank`) dans `ranking_key()`**.
2. **Exposer les pays dans l'interface** — `StageSearchPayload` vit dans `career/router.py`,
   explicitement interdit dans cette mission ; le modèle Pydantic ignore les champs inconnus,
   donc l'API HTTP ne peut pas encore transmettre `preferred_countries` /
   `geo_excluded_countries`. Les deux listes **sont** déjà livrées dans le vocabulaire
   (`GET /api/career/stage-search` → `vocabulary.preferred_countries` /
   `vocabulary.geo_excluded_countries`) : il ne manque que les deux champs du payload.
3. **Cohérence avec la Mission 11** — la Mission 11 canonicalise elle aussi les pays pour le
   filtre connecteur. Contrat d'intégration : le classement ne lit que le champ `country` de
   l'offre ; les deux tables de libellés doivent reconnaître les mêmes écritures de pays, sinon
   le filtre connecteur et le classement peuvent diverger.
4. **Plafond à 100** — `total_score` est borné à 100 : au-delà de 80 de pertinence, le boost
   `+20` n'est plus visible dans le score total. C'est pourquoi le tri utilise `-geo_score` comme
   critère secondaire : l'effet « bonus » reste visible même à 100/100.

---

## 8. Note de coordination

Pendant l'exécution, plusieurs workers CVBOOST ont tourné en parallèle et ont partagé les
répertoires de worktree (`.../worker-cvboost-13-1792571829`, `.../cvboost-13-geo`). Cette
livraison a donc été isolée sur la branche `agent/cvboost-13-geo-ranking-v2`
(worktree `AI-Excel-Agent-cvboost-13-geo-v2`), **sans** toucher au travail des autres workers :
seuls `career/models.py`, `career/offer_qualification.py`, `career/stage_search.py`,
`career/discovery.py` et `tests/test_geo_ranking.py` sont modifiés ici.
