# Mission 11 — Filtre pays côté connecteurs (zéro France)

Date : 21 octobre 2026
Branche : `worker/cvboost-11-1792589874` (base `main` = `a054c97`)
Statut : **TERMINÉE — le filtre est appliqué par les connecteurs eux-mêmes**

---

## 1. Ce qui a été fait

L'exclusion géographique n'est plus un tri fait **après** la lecture d'une offre : elle est
décidée **par le connecteur, sur l'offre brute**, avant que l'offre ne devienne une offre.
Une offre française ne coûte donc plus de quota, ne rejoint plus la base et ne peut pas
polluer les classements.

| Fichier | Ce qui change |
|---|---|
| `career/stage_search.py` | Vocabulaire pays : codes ISO, alias de noms, `canonicalize_country()`, `resolve_countries()`, `city_hint_countries()`, `canonical_country_codes()`, nouvelle clé de brief `countries_exclude`, `vocabulary()` expose l'exclusion. |
| `career/discovery.py` | `GeoExclusionMetrics` (compteurs par pays) et `CountryFilter` (la décision d'exclure), partagés par tous les connecteurs. `GreenhouseJobBoardConnector` filtre chaque offre brute et expose `health_check()`. `split_location()` (découpage de localisation partagé) et `https_opener()` (repli `certifi` partagé) sont ajoutés pour les connecteurs HTML. |
| `career/connectors/public_ats.py` | Lever / Ashby / SmartRecruiters : `countries_exclude` appliqué par offre brute, preuve pays lue dans les champs documentés de chaque flux (`country`, `address.postalAddress.addressCountry`, `location.country`), `country_canonical` publié, `health_check()` ajouté. |
| `career/connectors/welcome_jungle.py` | `FR` retiré de `refinementList[office.country_code][]` **dans la requête**, double contrôle local sur la carte, `country_canonical`, métriques, lecture TLS via le repli `certifi` partagé, découpage de localisation partagé. |
| `career/connectors/jobteaser.py` | `FR` retiré de `countries[]` **dans la requête**, double contrôle local, `country_canonical`, métriques, repli `certifi`, découpage partagé. |
| `career/connectors/talent_com.py` | Exclusion par offre brute, `country_canonical`, métriques, repli `certifi`, découpage partagé. |
| `career/connectors/apec.py` | Exclusion par offre brute, `country_canonical`, métriques, repli `certifi`, découpage partagé. |
| `tests/test_connectors_geo_filter.py` | **Nouveau** — 36 tests dédiés (14 exigés par la mission + 22 de couverture supplémentaire). |

Les quatre connecteurs HTML perdaient leur exclusion France codée en dur
(`_is_france_location`) : elle est remplacée par le filtre paramétrable, plus la preuve pays
lue dans la carte (`office.country_code` et équivalent, quel que soit le nom exact de
l'attribut).

---

## 2. Les règles de décision

### 2.1 Ce qui constitue une preuve pays

Un pays n'est retenu que si **la source l'écrit** :

1. un code ISO alpha-2 (`FR`, `fr`, `Fr`), alpha-3 (`FRA`) ou un nom de pays en anglais ou en
   français (`France`, `French Republic`, `République française`, `Deutschland`, `Suisse`,
   `Italia`, `United Kingdom`, `UK`…) ;
2. un code ISO **écrit en capitales** dans le texte (`Paris, FR`) — un mot ordinaire en
   minuscules n'est jamais lu comme un pays, donc `Frankfurt am Main` ne devient pas l'Arménie
   (`AM`) ;
3. à défaut, et **uniquement pour les quatre boards HTML** qui ne publient aucun champ pays,
   une liste de villes connues (`Paris` → FR, `Frankfurt` → DE…).

**Un pays n'est jamais déduit d'un nom de ville seul** sur Greenhouse et les ATS : une offre
située à « Paris » sans pays reste une candidate au pays *inconnu*, exactement comme avant
(`test_country_unknown_is_not_invented_from_city` continue de passer). C'est la garantie
existante du produit, et elle n'est pas cassée.

### 2.2 Exclure, garder, ou signaler un cas mixte

- Une offre dont **tous** les pays annoncés sont exclus → **exclue à la source**.
- Une offre qui annonce **plusieurs** pays, dont un exclu et un autre non → **gardée**, et
  comptée dans `mixed_count` / `excluded_by_country` : la source la place aussi hors du pays
  exclu, ce n'est pas à nous de trancher.
- Une offre dont **aucun** pays n'est connu → **gardée** (`unknown_count`), jamais inventée.

### 2.3 Le défaut et la reprise

- `default_brief()["countries_exclude"] == ["FR"]` et `validate_brief({})["countries_exclude"] == ["FR"]` :
  **sans brief, la France est exclue**.
- `validate_brief({"countries_exclude": []})["countries_exclude"] == []` : une liste vide
  explicite **rouvre** la France, pour le connecteur comme pour la requête envoyée au board
  (le code `FR` revient dans `refinementList[office.country_code][]`).
- Le nom du pays est lu sans casse : `fr`, `Fr`, `FR`, `France` donnent tous `FR`.
- Un pays inconnu est **refusé** par `validate_brief` (« Le pays « Klingon » n'est pas
  reconnu ») plutôt que d'être silencieusement ignoré.

---

## 3. Mesures sur trois lectures réelles

Trois lectures réelles du registre curaté (`career/source_registry.py`), via les connecteurs
réels et le brief réel (tous les domaines financiers, `countries_exclude = ["FR"]`).

### 3.1 Par source — `excluded_by_country`

| Source | Provider | Offres brutes | Gardées après le filtre pays | Exclues | `excluded_by_country` | `mixed_by_country` |
|---|---|---|---|---|---|---|
| Qonto | lever | 45 | 18 | 27 | `{"FR": 27}` | `{}` |
| Pigment | lever | 139 | 92 | 47 | `{"FR": 47}` | `{}` |
| OakNorth | ashby | 24 | 24 | 0 | `{}` | `{}` |
| Thought Machine | ashby | 40 | 40 | 0 | `{}` | `{}` |
| Alan | ashby | 128 | 38 | 70 | `{"FR": 70}` | `{"FR": 20}` |
| Contentsquare | lever | 18 | 18 | 0 | `{}` | `{}` |
| Welcome to the Jungle / JobTeaser / Talent.com / APEC | html | 0 | 0 | 0 | `{}` | `{}` |

Totaux sur les trois runs : `excluded_by_country = {"FR": 144}` et
`mixed_by_country = {"FR": 20}` — **identiques sur les trois runs** (le run 3 a relu Pigment
avec succès ; un run précédent avait perdu cette source sur un délai dépassé, pas sur le
filtre).

### 3.2 Chemin produit complet (`service.explore_internships`)

| Run | Sources tentées / réussies | Offres retenues | Pays des offres retenues | Offres françaises retenues |
|---|---|---|---|---|
| 1 | 14 / 14 | 39 | Chine, Hong Kong, Pays-Bas, Suède, Royaume-Uni, États-Unis, inconnu | **0** |
| 2 | 8 / 8 | 33 | idem | **0** |
| 3 | 13 / 12 | 39 | idem | **0** |

**Zéro offre France parvenue dans la base sur les trois runs réels.**

### 3.3 Ce que les boards HTML n'ont pas donné

Les quatre boards HTML ont renvoyé **zéro carte** pendant ces runs. La lecture est désormais
possible — leur transport HTTPS utilise le repli `certifi` que le transport Greenhouse
utilise déjà, sans affaiblir la vérification du certificat — mais **la page de recherche
servie ne contient aucun élément `data-testid="job-card"`** : elle est rendue côté client.
Les sélecteurs du parser ne correspondent donc plus au balisage publié.

C'est une limite **préexistante et hors périmètre** : le filtre pays de ces quatre
connecteurs est correct (il est testé sur HTML synthétique, comme le reste de leur
contrat), mais leurs sélecteurs de balisage demanderaient une reprise à part. Les compteurs
`raw_count` de ces connecteurs valent donc 0 sur les runs réels — et 0 **avant** comme
**après** cette mission.

---

## 4. Tests

### 4.1 Nouveau fichier `tests/test_connectors_geo_filter.py` — 36 tests

Les 14 tests exigés par la mission, avec leur nom :

| Test exigé | Présent |
|---|---|
| `test_greenhouse_excludes_france` | oui |
| `test_welcome_jungle_excludes_france` | oui |
| `test_jobteaser_excludes_france` | oui |
| `test_talent_com_excludes_france` | oui |
| `test_apec_excludes_france` | oui |
| `test_canonicalize_country_fr_variants` | oui |
| `test_frankfurt_not_excluded` | oui |
| `test_countries_exclude_empty` | oui |
| `test_override_via_brief` | oui |
| `test_default_is_fr_excluded` | oui |
| `test_metrics_excluded_count` | oui |
| `test_greenhouse_office_country_code` | oui |
| `test_mixed_countries` | oui |
| `test_case_insensitive` | oui |

En plus : `test_boards_exclude_france` (paramétré sur les 4 boards), `test_public_ats_excludes_france`
(Lever + Ashby + SmartRecruiters), `test_welcome_jungle_drops_the_excluded_country_from_the_request`,
`test_jobteaser_drops_the_excluded_country_from_the_request`,
`test_reopening_france_asks_the_board_for_france_again`, `test_vocabulary_exposes_the_country_exclusion`,
`test_greenhouse_publishes_the_canonical_country`, `test_unknown_country_is_never_invented`,
`test_brief_rejects_an_unknown_country`, `test_boards_health_check_exposes_the_geo_metrics`,
`test_mixed_posting_is_kept_and_counted_apart`,
`test_no_french_offer_over_500_synthetic_offers` (600 offres synthétiques, 0 française),
`test_locations_are_split_on_the_shared_separators` (6 cas),
`test_dashed_location_is_excluded_like_a_comma_one`,
`test_greenhouse_publishes_the_canonical_country`.

### 4.2 Quatre fichiers de tests existants modifiés — et pourquoi

| Fichier | Modification | Raison |
|---|---|---|
| `tests/test_welcome_jungle_connector.py`, `tests/test_jobteaser_connector.py`, `tests/test_talent_com_connector.py`, `tests/test_apec_connector.py` | l'assertion d'ensemble de clés de `health_check()` inclut les nouvelles métriques pays | `health_check()` expose désormais `raw_count`, `kept_count`, `filtered_count`, `excluded_count`, `mixed_count`, `unknown_count`, `excluded_by_country`, `mixed_by_country` — c'est une exigence de la mission ; l'assertion était une égalité d'ensemble, elle devait suivre. |
| `tests/test_career_discovery_selection.py` | le corpus synthétique passe de « Paris / Lyon, France » à « London / Manchester, United Kingdom » | Ces 13 tests portent sur l'**ordre de sélection** et la **pondération**, pas sur la géographie ; leur corpus était situé en France et était donc refusé à la source. Aucune assertion n'a changé, seule la localisation du corpus. |
| `tests/test_career_agent.py` | idem, une localisation | Même raison : le test porte sur la borne d'hôte et l'assainissement HTML. |

Aucune assertion existante n'a été affaiblie : dans tous les cas, la localisation du corpus ou
l'ensemble de clés attendu a été mis à jour, jamais le sens du test.

### 4.3 Commandes exécutées

```text
.venv/bin/python -m pytest -q tests/test_connectors_geo_filter.py   -> 36 passed
.venv/bin/python -m pytest -q                                       -> 1409 passed, 1 skipped
.venv/bin/python -m ruff check .                                    -> All checks passed!
git diff --check                                                    -> propre
```

Baseline avant mission : `1373 passed, 1 skipped`. Après : `1409 passed, 1 skipped`
(+ 36 nouveaux tests, aucune régression).

---

## 5. Périmètre

### 5.1 Respecté

- Modifiés **uniquement** : `career/stage_search.py`, `career/discovery.py`,
  `career/connectors/public_ats.py`, `career/connectors/welcome_jungle.py`,
  `career/connectors/jobteaser.py`, `career/connectors/talent_com.py`,
  `career/connectors/apec.py`, les 6 fichiers de tests listés ci-dessus, plus les deux
  fichiers nouveaux (`tests/test_connectors_geo_filter.py`, ce rapport).
- **Intacts** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`,
  aucune migration, `SCHEMA_VERSION` inchangé. Vérifié par `git status --short`.
- Aucun appel réseau dans les tests : les connecteurs HTML reçoivent un `fetch` injecté, les
  connecteurs ATS un `transport` injecté.

### 5.2 Deux points laissés ouverts, volontairement

1. **`career/router.py` est interdit par la mission**, or `StageSearchPayload` y vit. La
   nouvelle clé `countries_exclude` est donc exposée par le **contrat de brief**
   (`validate_brief`, `default_brief`, `vocabulary()`) mais **pas encore** par le payload
   HTTP : `pydantic` ignore le champ inconnu. Concrètement, la personne ne peut pas encore
   rouvrir la France depuis le formulaire web ; elle le peut depuis le brief enregistré
   (`PUT /api/career/stage-search` → `validate_brief` → stocké). **À câbler à l'intégration.**
2. **`discover_stage_offers()` n'existe pas dans ce code** : l'entrée de production est
   `CareerService.explore_internships()` → `connector.discover_internships(...)` /
   `discover_ranked(...)`, qui reçoivent le brief. Le défaut « sans brief → France exclue » y
   est appliqué, et vérifié par test.

L'API décrite dans la mission (`iter_offers()`, `RawOffer`, `canonicalize_country()` dans un
module de connecteurs) ne correspond pas au code réel de ce dépôt ; la mission a donc été
réalisée sur l'API réelle, en conservant l'intention : filtrage côté source, normalisation du
pays avant filtrage, défaut France exclue, reprise possible, métriques par pays.

---

## 6. Ce qui est publié sur chaque offre

Chaque offre conservée porte désormais `country_canonical` (code ISO alpha-2, ou chaîne vide
si la source n'annonce pas de pays) en plus de `country` (le libellé source, inchangé). Le
champ n'entre pas dans la base : `career/service.py` ne conserve que ses colonnes fixes et
est hors périmètre.

---

## 7. Limites connues

- Une offre **sans pays** reste retenue et `unknown_count` l'incrémente : on ne refuse pas
  une offre dont on ignore la localisation.
- Une offre **multi-pays** (par exemple `London, United Kingdom / Paris, France`) est retenue
  et comptée dans `mixed_count` / `mixed_by_country` : la source la place aussi hors du pays
  exclu.
- L'exclusion est **par pays**, pas par ville : la liste `excluded_cities` du brief continue
  d'être traitée au niveau de la qualification (`career/offer_qualification.py`, hors
  périmètre), pas au niveau de la source.
- `excluded_by_country` ne compte **que** les offres réellement exclues ; les cas mixtes sont
  comptés à part dans `mixed_by_country`, pour que `excluded_count` et
  `sum(excluded_by_country.values())` restent cohérents.
