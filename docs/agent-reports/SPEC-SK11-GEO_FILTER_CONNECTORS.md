# SPEC-SK-11 — Filtre pays côté connecteurs (zéro France)

**Ordre de mission** : `cvboost-32-1792629250` (registry mission `32`)
**Branche** : `agent/spec-sk11-geo-filter-connectors` (branche de travail : `worker/cvboost-32-1792629250`)
**Base** : `main` (`f5b22f2`) + livraison CVBOOST-11 consolidée (`origin/agent/cvboost-11-geo-filter`)
**Date** : 2026-10-22
**Auteur** : agent worker SK-11

---

## 1. Ce qui a été livré

Le filtre pays existe désormais **au niveau de chaque connecteur** : le pays
publié par la source est normalisé, et l'offre est écartée **avant** qu'elle
ne soit normalisée complètement, qualifiée ou écrite en base locale.

Cette mission est une **reprise** de la mission CVBOOST-11, dont la livraison
complète se trouvait déjà sur `origin/agent/cvboost-11-geo-filter` (non
fusionnée dans `main`). Plutôt que d'écrire une seconde implémentation
compétitive, la livraison existante a été **consolidée sur `main`** (merge
`09c6d8e`), relue ligne à ligne, vérifiée contre les sources réelles, puis
**corrigée sur trois défauts réels** que la revue précédente n'avait pas vus.

| Fichier | Rôle |
|---|---|
| `career/countries.py` | Vocabulaire ISO 3166-1 canonique, résolution du pays publié, `GeoFilter`, `resolve_published_country()` |
| `career/discovery.py` | Greenhouse : filtre à la source, `offers_filtered_geo`, `health_check()`, `discover_stage_offers()`, `connector_geo_kwargs()` |
| `career/connectors/public_ats.py` | Lever, Ashby, SmartRecruiters : filtre à la source **avant** `_normalise_one()` |
| `career/connectors/welcome_jungle.py` | Filtre à la source, refinement pays demandé à la source |
| `career/connectors/jobteaser.py` | Idem |
| `career/connectors/talent_com.py` | Idem |
| `career/connectors/apec.py` | Idem |
| `career/stage_search.py` | `countries_exclude` / `countries_include` dans le brief, défaut France vidable |
| `career/service.py` | Le service **passe explicitement** la liste de pays à chaque connecteur |
| `tests/fixtures/geo_filter/*.json` | **Nouveau** — 8 fixtures synthétiques, 21 cas (matrice d'acceptation de la mission) |
| `tests/test_geo_filter_connectors.py` | **Nouveau** — la matrice d'acceptation de la mission, lisible depuis les fixtures |
| `tests/test_geo_filter_connectors_live.py` | **Nouveau** — contrôle réel borné, opt-in (`CAREER_GEO_LIVE=1`) |
| `tests/test_connectors_geo_filter.py` | Hérité de CVBOOST-11 — 39 tests synthétiques |
| `docs/agent-reports/SPEC-SK11-GEO_FILTER_CONNECTORS.md` | Ce rapport |

---

## 2. Les règles de la mission, et où elles sont tenues

| Règle de la mission | État | Preuve |
|---|---|---|
| 1. Le filtre s'applique **au niveau du connecteur** | ✅ | `career/countries.py::resolve_published_country` appelé dans les 6 modules de connecteur ; aucun filtre pays n'existe ailleurs dans le pipeline |
| 2. `countries_exclude` passé à `iter_offers()` / `discover_internships()` | ✅ | paramètre déclaré par les **8** connecteurs (`test_every_connector_accepts_the_geographic_parameters`) |
| 3. `countries_include` optionnel | ✅ | paramètre déclaré par les 8 connecteurs ; une liste d'inclusion ne garde que les pays nommés, un pays inconnu n'est jamais écarté |
| 4. Zéro régression : sans paramètre = comportement actuel | ✅ | paramètre par défaut `None` → repli sur le brief ; `connector_geo_kwargs()` n'envoie que les mots-clés déclarés, un connecteur tiers qui ignore le filtre n'est jamais cassé |
| 5. Filtrage **avant** qualification | ✅ | le filtre passe avant `source_html_to_text()` (Greenhouse, 4 connecteurs HTML) et avant `_normalise_one()` (ATS publics) ; mesuré par `test_the_filter_is_applied_before_the_description_is_parsed` |
| 6. Métrique `offers_filtered_geo` dans `DiscoveryPayload` | ✅ | propriété de `DiscoveryPayload` (égale à `country_excluded_count`), + `excluded_by_country` par pays, + `health_check()` par connecteur |
| Service : passage du paramètre | ✅ | `career/service.py::_geo_arguments()` + `connector_geo_kwargs()`, dans les **deux** parcours (boards personnels et explorateur) |
| 12+ fixtures synthétiques | ✅ | **21 cas** dans `tests/fixtures/geo_filter/` (8 fichiers), covering the 8 connecteurs + multi-loc + pays inconnu + code d'État |
| Test live borné | ✅ | `tests/test_geo_filter_connectors_live.py` (opt-in), 2 tests sur un board réel |
| Rapport | ✅ | ce document |

---

## 3. Les défauts réels trouvés et corrigés

Les trois défauts ci-dessous ne sont visibles que sur la réponse réelle des
sources : ils ne se reproduisent pas avec des fixtures qui écrivent les pays
comme le code s'attend à les lire.

### 3.1 Une localisation qui publie le pays seul n'était pas lue

Le board **AlixPartners** publie une offre dont la localisation est
exactement `France` :

```
id 7718401003 — "Vice President - Telecommunication, Media and Technology"
location: "France"
```

`_location_parts()` renvoyait `(country="", city="France")` : aucun pays n'était
lu, l'offre n'était donc pas filtrée et arrivait à la personne. C'est le
défaut le plus grave de la livraison précédente : **une offre française
déclarée comme française passait le filtre**.

*Correction* : `career/countries.py::countries_named_in_location()` lit les
**noms** de pays que la localisation publie, y compris quand la localisation
ne contient qu'un pays. Le code d'État américain reste exclu (voir 3.2).

*Mesure réelle* : sur le board AlixPartners, `offers_filtered_geo` passe de
`0` à `1`, et l'offre `7718401003` ne fait plus partie du résultat.

### 3.2 Un code d'État américain était lu comme un pays

Le board **Lincoln International** publie `Chicago, IL` (7 offres). La
lecture par code_alpha-2 faisait de `IL` **Israël** : une geography inventée,
publiée dans le payload de l'offre.

*Correction* : les abréviations postales des États-Unis qui sont aussi des
codes ISO 3166-1 (`AL`, `AR`, `CA`, `CO`, `DE`, `GA`, `ID`, `IL`, `IN`, `LA`,
`MA`, `MD`, `ME`, `MN`, `MO`, `MS`, `MT`, `NE`, `SC`, `SD`) ne sont **jamais**
lues dans une localisation en prose. Elles restent lues quand la source
publie le code dans un champ structurel (`address.postalAddress.addressCountry`
d'Ashby, `office.country_code` de Greenhouse), où le code est un fait publié.

*Mesure réelle* : les 7 offres `Chicago, IL` gardent un pays inconnu au lieu
de pretended Israël.

### 3.3 Le service ne passait pas la liste de pays au connecteur

`career/service.py` laissait le connecteur retrouver la liste dans le brief.
Le paramètre existait, mais **le service ne le passait pas** — la règle 2 de
la mission (« paramètre passé à `iter_offers()` / `discover_internships()` »)
n'était donc tenue qu'en partie.

*Correction* : `career/service.py` lit la liste une fois (`_geo_arguments()`)
et la passe explicitement à chaque connecteur, dans les deux parcours
(`discover_opportunities()` et `explore_internships()`), via
`connector_geo_kwargs()` qui n'envoie que les mots-clés réellement déclarés.

---

## 4. Le contrat de résolution du pays

### 4.1 Ordre de résolution

1. **Champ structurel** — le code publié par la source dans un champ pays
   (`office.country_code`, `addressCountry`, `location.country`) : c'est un
   fait, il gagne toujours.
2. **Noms publiés** — les pays que la localisation *nomme*
   (`"Paris, France"`, `"France"`, `"Germany"`, `"Hong Kong"`). Une
   localisation qui nomme plusieurs pays est une offre multi-pays.
3. **Code du dernier segment** — `"Paris, FR"` : un code nu dans l'emplacement
   pays, sauf s'il est aussi une abréviation d'État américain.

### 4.2 Ce qui n'est jamais fait

| Formulation | Résultat | Pourquoi |
|---|---|---|
| `Paris`, `Nantes`, `Lille` | pays **inconnu** | une ville ne désigne pas un pays ; l'offre est affichée « à vérifier », jamais écartée |
| `Chicago, IL` | pays **inconnu** | `IL` publie l'Illinois, pas Israël |
| `Dubai` | pays **inconnu** | c'est une ville |
| `Atlantis` | pays **inconnu** | aucun libellé connu |
| `Frankfurt` | pays **inconnu** | une ville en Allemagne n'est pas une offre française |

### 4.3 La règle multi-pays

Une offre qui publie plusieurs pays est **gardée dès qu'un seul de ces pays
est autorisé**, et écartée seulement si **tous** sont exclus. C'est la règle
de la table d'acceptation de la mission (« SmartRecruiters — offre multi-pays
dont FR → gardée si autre pays autorisé »).

Conséquence réelle : sur le corpus live, 3 offres
(`London, Greater London, England, United Kingdom, Paris, France` et deux
`Berlin, Berlin, Germany; Paris, Paris, France`) sont gardées, alors que la
livraison précédente les écartait. Elles restent des offres **non françaises**
— leur pays retenu est `GB` et `DE` — et une offre à Paris reste signalée
comme telle dans sa localisation d'origine, qui est conservée telle quelle.

---

## 5. Mesures réelles (sources publiques, 22-10-2026)

Lecture réelle des **15 boards Greenhouse** du registre (`career/source_registry.py`),
filtre `countries_exclude=["FR"]` :

| Mesure | Valeur |
|---|---|
| Offres lues | **1 380** |
| Offres écartées par le filtre pays | **65** (toutes `FR`) |
| Offres conservées | **129** |
| Offres conservées dont la localisation mentionne un lieu français | **17** |
| … dont la source ne publie **aucun pays** (`Paris`, `Nantes`, `Lille`) | **13** |
| … dont la source publie une offre multi-villes (Londres + Paris) | **4** |

Détail par board :

```
lincolninternational     raw=  41 kept=  3 filtered_geo=  3
alixpartners             raw= 125 kept=  7 filtered_geo=  1
schonfeld                raw=  69 kept= 12 filtered_geo=  0
point72                  raw= 215 kept= 20 filtered_geo=  0
quberesearchandtechnologies raw=201 kept=19 filtered_geo=  0
flowtraders              raw=  45 kept=  2 filtered_geo=  0
xtxmarketstechnologies   raw=   7 kept=  1 filtered_geo=  0
optiverus                raw= 165 kept= 26 filtered_geo=  0
mangroup                 raw=  57 kept=  6 filtered_geo=  0
aqr                      raw=  55 kept=  0 filtered_geo=  0
robinhood                raw= 153 kept=  8 filtered_geo=  0
generalatlantic          raw=  12 kept=  1 filtered_geo=  0
doctolib                 raw= 153 kept= 22 filtered_geo= 58
monzo                    raw=  68 kept=  2 filtered_geo=  0
dataiku                  raw=  14 kept=  0 filtered_geo=  3
```

Contrôle live borné (opt-in) :

```
CAREER_GEO_LIVE=1 .venv/bin/python -m pytest -q tests/test_geo_filter_connectors_live.py
→ 2 passed
```

Sur le board `lincolninternational` : `raw=41`, `kept=3`,
`offers_filtered_geo=3` (`{"FR": 3}`), pays conservés `{'', 'GB', 'SE'}` —
**aucune offre française dans le résultat**.

---

## 6. Limites connues et documentées

1. **Une ville seule ne désigne pas un pays.** 13 offres sur 1 380 (0,9 %)
   sont publiées par une source qui écrit `Paris`, `Nantes` ou `Lille` sans
   pays. Elles sont **conservées** et présentées comme *à vérifier* : les
   écarter supposerait de déduire un pays d'une ville, ce que le produit
   interdit. C'est un choix assumé, pas un oubli.
2. **Une localisation multi-pays est conservée** si un seul pays est
   autorisé (§4.3). Une offre Paris + Londres reste visible ; c'est ce que
   demande la table d'acceptation de la mission.
3. **Les codes de pays en prose** ne sont lus que dans l'emplacement pays
   (`"Paris, FR"`). Les codes d'État américains sont exclus (§3.2).
4. **`countries_include`** n'est pas exposé dans l'interface : il est lu par
   le brief et par les connecteurs, pour les sources 100 % ciblées. Le
   parcours personne continue de piloter l'exclusion (`countries_exclude`).

---

## 7. Validation

```bash
./checklist_codex.sh                       # TOUT VERT (main, lint, secrets, devkit)
.venv/bin/python -m pytest -q              # 1499 passed, 3 skipped
.venv/bin/python -m pytest -q tests/test_geo_filter_connectors.py
                                           # 39 passed (matrice d'acceptation)
CAREER_GEO_LIVE=1 .venv/bin/python -m pytest -q tests/test_geo_filter_connectors_live.py
                                           # 2 passed (contrôle réel)
.venv/bin/python -m ruff check .           # All checks passed
git diff --check                           # propre
```

Base de comparaison : `main` (`f5b22f2`) = 1 424 tests verts. Après la
consolidation et les corrections : **1 499 tests verts, 3 ignorés** (2 pour le
contrôle live opt-in, 1 pour un script absent du dépôt). **Aucune
régression.**

---

## 8. Pour la relecture

- La branche `agent/spec-sk11-geo-filter-connectors` contient le commit de
  consolidation (`09c6d8e`) puis les corrections (`171e6c7`).
- `origin/agent/cvboost-11-geo-filter` est **included** dans cette branche :
  la consolidation est un merge, pas une réécriture, et l'historique de la
  livraison précédente reste lisible.
- `career/service.py`, le schéma SQLite et l'interface ne sont pas modifiés :
  aucune migration, aucune dépendance ajoutée, aucun rollback nécessaire.
