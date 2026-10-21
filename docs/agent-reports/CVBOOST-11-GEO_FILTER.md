# CVBOOST-11 — Filtre pays côté connecteurs (Zéro France)

**Branche** : `agent/cvboost-11-geo-filter` (worktree dédié `/Users/comedelavenne/AI-Excel-Agent-cvboost-11-geo-filter`)
**Base** : `main` (tag `v3-cvboost-sources-2026-10-20`, SHA `3a0d1ee`)
**Date** : 2026-10-21
**Auteur** : Agent Mission 11

---

## 1. Ce qui a été livré

La France ne doit plus jamais entrer dans la base locale. Jusqu'ici elle
n'était écartée **après** la lecture de l'offre : le connecteur consommait
son quota, l'offre transitoit par la base, et le filtre de second niveau
rejetait l'offre au moment de la qualifier. Le filtre est désormais poussé
**côté source** : chaque connecteur normalise le pays qu'il publie, puis
écarte l'offre **avant** qu'elle ne devienne un enregistrement local.

| Fichier | Rôle |
|---|---|
| `career/countries.py` | **Nouveau** — vocabulaire ISO 3166-1 canonique (`FR`, `fr`, `FRA`, `France`, `Royaume-Uni`…), sans inférence géographique |
| `career/discovery.py` | Greenhouse : lecture de `office.country_code`, filtre à la source, `excluded_by_country`, `health_check()`, point d'entrée `discover_stage_offers()` |
| `career/stage_search.py` | `countries_exclude` dans le brief et le vocabulaire ; défaut France, vidable par la personne |
| `career/connectors/public_ats.py` | ATS publics (Lever, Ashby, SmartRecruiters) : filtre à la source + `health_check()` |
| `career/connectors/welcome_jungle.py` | Filtre à la source + refinement pays demandé à l'API + `health_check()` |
| `career/connectors/jobteaser.py` | Idem |
| `career/connectors/talent_com.py` | Idem |
| `career/connectors/apec.py` | Idem |
| `tests/test_connectors_geo_filter.py` | **Nouveau** — 30 tests synthétiques (aucun socket ouvert) |
| `docs/agent-reports/CVBOOST-11-GEO_FILTER.md` | Ce rapport |

Fichiers de test existants mis à jour (conséquence assumée du changement de
comportement, voir §5) : `tests/test_{welcome_jungle,jobteaser,talent_com,apec}_connector.py`,
`tests/test_career_discovery_selection.py`, `tests/test_career_agent.py`.

---

## 2. Le contrat de filtrage

### 2.1 Normalisation avant décision

`career/countries.py` ne reconnaît un pays que sur une formulation
**explicite** :

| Formulation | Résultat |
|---|---|
| `FR`, `fr`, `Fr`, `FRA`, `France`, `République Française` | `FR` |
| `DE`, `Germany`, `DEU`, `Deutschland` | `DE` |
| `GB`, `UK`, `United Kingdom`, `Great Britain` | `GB` |
| `Frankfurt` (ville) | `""` — jamais `FR` |
| `Narnia` (libellé inconnu) | `""` — aucun pays inventé |

Une ville ne désigne **jamais** un pays : une offre publiée comme `Paris`
garde un pays inconnu et reste affichée « à vérifier », au lieu d'être
silencieusement écartée comme française. C'est une règle déjà portée par le
codebase (`test_country_unknown_is_not_invented_from_city`) et par la
Mission 13 (« pas de géo-inférence »).

`country_from_source()` accepte en revanche une localisation publiée en
entier dans le champ pays (`"London, United Kingdom"`) : le dernier segment
explicite est alors résolu.

### 2.2 Où le filtre est appliqué

| Connecteur | Point de filtrage | Offre France materialisée ? |
|---|---|---|
| Greenhouse | `career/discovery.py`, avant la qualification | non |
| Lever / Ashby / SmartRecruiters | `career/connectors/public_ats.py`, après normalisation | non |
| Welcome to the Jungle | `career/connectors/welcome_jungle.py`, dans `_iter_raw_offers` | non |
| JobTeaser | `career/connectors/jobteaser.py`, dans `_iter_raw_offers` | non |
| Talent.com | `career/connectors/talent_com.py`, dans `_iter_raw_offers` | non |
| APEC | `career/connectors/apec.py`, dans `_iter_raw_offers` | non |

Pour les quatre connecteurs HTML, l'offre exclue n'est même pas *lue* dans
la boucle de page : elle ne compte ni dans `raw_count`, ni dans le budget de
qualification, ni dans les places retenues. Welcome to the Jungle va plus
loin : le refinement `refinementList[office.country_code][]` demande
directement à l'API de ne pas renvoyer les pays exclus.

### 2.3 Le brief porte la liste

```python
"countries_exclude": ["FR"]   # codes ISO canoniques
```

La résolution est faite **une seule fois**, dans `validate_brief()`, et
suivre trois entrées dans cet ordre :

1. `countries_exclude` — liste explicite ; **une liste vide désactive le
   filtre** (c'est le seul moyen de faire revenir une offre française) ;
2. `excluded_countries` — l'ancienne liste libre que l'interface édite
   encore ; une liste vidée désactive elle aussi le filtre, sinon la
   personne ne pourrait pas annuler son exclusion depuis l'écran ;
3. aucune des deux — la France reste exclue, et un pays que la personne
   demande explicitement n'est pas exclu.

`vocabulary()` expose `default_countries_exclude` pour que l'interface
puisse afficher la règle par défaut.

### 2.4 Le point d'entrée

```python
discover_stage_offers(connectors, sources, selection_brief=None,
                      countries_exclude=None, deadline=None) -> list[dict]
```

`countries_exclude=None` prend `["FR"]` : sans argument, la France est
exclue. Le point d'entrée ne filtre rien lui-même, il transmet la liste à
chaque connecteur, qui l'applique de son côté.

---

## 3. Métriques : `excluded_by_country` par connecteur

Trois exécutions consécutives par connecteur sur un flux synthétique mixte
(120 offres : France, Allemagne, Royaume-Uni). **Aucun appel réseau** : les
connecteurs lisent un flux injecté, comme le fait la suite de tests. Les
compteurs viennent de `health_check()`.

| Connecteur | Offres lues | Offres exclues | `excluded_by_country` | Offres retournées | Runs 1 / 2 / 3 |
|---|---|---|---|---|---|
| greenhouse | 120 | 40 | `{"FR": 40}` | 80 | identiques |
| lever | 120 | 40 | `{"FR": 40}` | 80 | identiques |
| welcome_jungle | 600 | 200 | `{"FR": 200}` | 150 (plafond `max_results`) | identiques |
| jobteaser | 600 | 200 | `{"FR": 200}` | 150 (plafond `max_results`) | identiques |
| talent_com | 600 | 200 | `{"FR": 200}` | 150 (plafond `max_results`) | identiques |
| apec | 600 | 200 | `{"FR": 200}` | 150 (plafond `max_results`) | identiques |

Les 600 lignes des connecteurs HTML correspondent à 5 pages de 120 offres ;
les 150 retournées sont le plafond de rétention, pas un tri pays : les
offres exclues ne consomment aucune place.

`health_check()` expose désormais, pour chaque connecteur :

```python
{"provider", "last_error", "raw_count", "filtered_count", "excluded_count",
 "country_excluded_count", "excluded_by_country"}
```

et le payload `DiscoveryPayload` porte `country_excluded_count` et
`excluded_by_country` (les offres écartées pour pays restent comptées dans
`excluded_count` : un pays exclu est une offre non conforme, pas une offre
malformée).

---

## 4. Tests

`tests/test_connectors_geo_filter.py` — 30 tests synthétiques, aucun socket
ouvert :

| Cas couvert | Test |
|---|---|
| Variantes FR (`FR`, `fr`, `Fr`, `FRA`, `France`) | `test_canonicalize_country_fr_variants` |
| Une ville n'est pas un pays | `test_canonicalize_country_does_not_read_a_city_as_a_country` |
| Un libellé inconnu n'invente rien | `test_canonicalize_country_reads_explicit_wording_only` |
| Liste d'exclusion sans doublon ni pays inventé | `test_canonical_country_codes_keeps_order_and_drops_unknown_wordings` |
| Localisation publiée en entier dans le champ pays | `test_country_from_source_resolves_a_location_published_in_the_country_field` |
| France exclue par défaut | `test_default_exclusion_is_france` |
| Greenhouse écarte la France | `test_greenhouse_excludes_france` |
| `office.country_code` lu comme fait publié | `test_greenhouse_office_country_code_is_used_to_deduce_the_country` |
| « Frankfurt » ≠ « FR » | `test_greenhouse_frankfurt_is_not_excluded_by_the_fr_code` |
| Défaut sans brief | `test_greenhouse_default_is_fr_excluded` |
| France revenue via le brief | `test_greenhouse_brief_can_bring_france_back` |
| Les 4 connecteurs HTML | `test_{welcome_jungle,jobteaser,talent_com,apec}_excludes_france` |
| Les autres pays passent | `test_html_connectors_keep_the_offers_of_other_countries` |
| Casse insensible | `test_html_connector_case_insensitive_country_variants_are_excluded` |
| France autorisée explicitement | `test_html_connector_can_be_told_to_allow_france` |
| ATS publics | `test_public_ats_connectors_exclude_france` |
| Compteurs par pays | `test_metrics_excluded_count` |
| Métriques exposées partout | `test_every_connector_exposes_the_geographic_metrics` |
| Lot mélangé | `test_mixed_countries_only_excludes_the_excluded_one` |
| 600 offres, aucune France survivante | `test_no_french_offer_survives_six_hundred_synthetic_offers` |
| Point d'entrée : défaut / transmission / annulation | `test_discover_stage_offers_{excludes_france_by_default,forwards_the_default_exclusion_list,can_bring_france_back}` |
| Pays inconnu | `test_unknown_country_wording_excludes_nothing` |

---

## 5. Régressions assumées

Le changement est un changement de produit : une offre française ne doit
plus atteindre la base. Deux familles de tests existants ont donc dû être
mis à jour, **sans affaiblir aucune assertion** :

1. `tests/test_{welcome_jungle,jobteaser,talent_com,apec}_connector.py` —
   `health_check()` expose désormais quatre clés de plus (`raw_count`,
   `filtered_count`, `excluded_count`, `excluded_by_country`). Les
   assertions de contenu sont inchangées.

2. `tests/test_career_discovery_selection.py` et
   `tests/test_career_agent.py` — les board synthétiques publiaient toutes
   leurs offres en France (`"Paris, France"`). Ces tests mesurent le
   **classement** et la **sélection avant le plafond de 150**, pas la
   géographie : leurs fixtures sont désormais publiées au Royaume-Uni
   (`"London, United Kingdom"`), pour que les offres atteignent enfin le
   classement qu'ils veulent observer. Les assertions (161 offres
   évaluées, ordre stable, place du profil « late-finance », …) sont
   inchangées.

Ce n'est pas un contournement : une offre française est désormais écartée
avant le classement, donc elle ne peut plus être observée dans un test de
classement.

---

## 6. Hors périmètre

* `career/service.py`, `career/router.py`, `career_static/*`,
  `requirements*.txt`, migrations et `SCHEMA_VERSION` : **intouchés**, comme
  l'impose la mission.
* Conséquence à signaler : le champ `countries_exclude` n'est pas exposé
  dans `StageSearchPayload` (qui vit dans `career/router.py`, hors
  périmètre). L'interface continue donc à piloter l'exclusion par
  `excluded_countries`, que `validate_brief()` relaie désormais vers
  `countries_exclude` : vider « France » dans l'interface désactive bien le
  filtre source. La Mission 13 pourra ajouter `preferred_countries` /
  `excluded_countries` au modèle de requête si le périmètre est rouvert.
* La qualification (`career/offer_qualification.py`) n'a pas été modifiée :
  la source-side filter est *en plus* de l'exclusion de qualification, pas
  à sa place. Une offre déjà enregistrée reste donc qualifiée comme avant.

---

## 7. Commandes de validation

```
.venv/bin/python -m pytest -q                            → 1397 passed, 1 skipped
.venv/bin/python -m pytest -q tests/test_connectors_geo_filter.py → 30 passed
.venv/bin/python -m ruff check .                         → All checks passed!
git diff --check                                          → propre
```

La suite complète passe de **1367** tests (base `main`) à **1397** :
1367 inchangés + 30 nouveaux. Aucune régression.
