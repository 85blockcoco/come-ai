# SPEC-SK11 — Filtre pays côté connecteurs (CVBOOST-32)

**Branche** : `worker/cvboost-32-1792629152` (worktree dédié `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-32-1792629152`)
**Base** : `main` @ `f5b22f2`
**Date** : 2026-10-22
**Mission** : SK-11 — filtre pays appliqué au niveau du connecteur

---

## 1. Pourquoi

Le connecteur Greenhouse (85 % du corpus) ne filtrait **pas** par pays. Le filtre
`country` existait, mais seulement **après** coup, dans `qualify_offer`, au moment
de re-qualifier les offres déjà normalisées, notées et lues. Sur un board réel de
**439 publications**, 36 sont publiées en France : elles coûtaient une description
analysée, une qualification, un score et une place dans le classement pour finir
toutes rejetées.

La correction n'est pas « filtrer après coup », c'est **ne pas payer** l'offre
exclue. Le filtre est donc descendu dans le connecteur, avant la normalisation.

---

## 2. Ce qui est livré

| Fichier | Nature | Rôle |
|---------|--------|------|
| `career/geo.py` | **nouveau** | Lecture canonique d'un pays + décision de filtrage (pur, déterministe, sans réseau ni horloge) |
| `career/discovery.py` | modifié | `DiscoveryPayload.filtered_geo_count`, `countries_exclude`/`countries_include` sur `discover_ranked()` et `discover_internships()`, filtre **avant** la lecture de la description |
| `career/connectors/public_ats.py` | modifié | `countries_exclude`/`countries_include` sur `discover_internships()`, `_geo_evidence()` par fournisseur, filtre avant `_normalise_one()` |
| `career/connectors/welcome_jungle.py` | modifié | idem, filtre dans `_iter_raw_offers()` avant le parsing de la description |
| `career/connectors/jobteaser.py` | modifié | idem |
| `career/connectors/talent_com.py` | modifié | idem |
| `career/connectors/apec.py` | modifié | idem |
| `career/service.py` | modifié | Le service pousse les codes ISO issus des critères enregistrés ; `filtered_geo_count` exposé dans les compteurs d'audit |
| `tests/fixtures/geo_filter/geo_filter_cases.json` | **nouveau** | 25 cas synthétiques, tous connecteurs |
| `tests/test_geo_filter_connectors.py` | **nouveau** | 82 tests (les 26 cas × 2 assertions de comptage, + 30 tests de contrat) |
| `tests/test_geo_filter_connectors_live.py` | **nouveau** | 2 tests live bornés, séparés du corpus synthétique, ignorés sans `CAREER_LIVE_TESTS=1` |

---

## 3. Le contrat

```python
# Les huit connecteurs acceptent les deux paramètres.
def discover_internships(self, source, *, selection_brief, deadline=None,
                         countries_exclude: Sequence[str] | None = None,
                         countries_include: Sequence[str] | None = None) -> DiscoveryPayload: ...

# Greenhouse expose en plus le point d'entrée non « internships ».
def discover_ranked(self, board, *, selection_brief=None, internships_only=False,
                    deadline=None,
                    countries_exclude: Sequence[str] | None = None,
                    countries_include: Sequence[str] | None = None) -> DiscoveryPayload: ...
```

`countries_exclude` et `countries_include` sont des **codes ISO-3166-1 alpha-2**
(`["FR"]`). Le module `career/geo.py` accepte aussi des libellés de pays et les
convertit (`excluded_country_codes(["France"]) == ("FR",)`).

### 3.1 Valeur par défaut : zéro régression

| Valeur passée | Effet |
|---|---|
| `None` (paramètre absent) | **Comportement historique du connecteur** : les ATS ne filtraient aucun pays ; les quatre connecteurs scrapés excluaient déjà la France |
| `[]` (liste vide explicite) | Aucun filtre pays, sans toucher au reste |
| `["FR"]`, `["FR","DE"]`, `["Germany"]` | Exclusion des pays indiqués |

Le filtre est donc **opt-in côté connecteur** et **opt-out possible**. C'est ce qui
permet à `discover_opportunities` (import d'un board) de continuer d'enregistrer
tout ce que le board publie, sans casser les tests de sélection existants.

### 3.2 Compteur d'audit

`DiscoveryPayload` gagne `filtered_geo_count`, avec l'alias en lecture
`offers_filtered_geo` (nom de la règle 6 de la mission).

`excluded_count` compte désormais **toute** offre qui n'atteint pas les résultats :
celles dont la qualification est non conforme **et** celles retirées par le filtre
pays. `filtered_geo_count` est le sous-ensemble caused par le seul filtre pays.
Cette convention permet de conserver les quatre invariants de comptage déjà
vérifiés par le service :

```
raw_count            == evaluated_count + invalid_count
evaluated_count      == confirmed_count + uncertain_count + excluded_count
relevant_count + filtered_criteria_count == confirmed_count + uncertain_count
filtered_geo_count   <= excluded_count                    (invariant ajouté)
```

---

## 4. Les règles de décision (`career/geo.py`)

Le module est **pur** : pas de réseau, pas d'horloge, pas de fichier.

### 4.1 Lire un pays

`canonical_country_code(value)` renvoie le code ISO-3166-1 alpha-2 d'un libellé
**réellement publié** par la source, ou `""` si le libellé ne nomme aucun pays.

- Codes alpha-2 (`FR`, `fr`), alpha-3 (`FRA`), noms anglais (`France`,
  `United Kingdom`, `Germany`) et français (`Allemagne`, `Espagne`, `Suisse`,
  `Suède`, `Italie`, `Royaume-Uni`…) sont lus.
- `UK` → `GB`, `USA` → `US`, `Deutschland` → `DE`.
- **Un libellé illisible renvoie `""`** : un pays inconnu reste inconnu, il ne
  devient jamais la France.

### 4.2 Décider

```python
geo_filter_decision(*, location_text="", country="",
                    excluded_codes=(), included_codes=(),
                    hints=None) -> GeoDecision
```

Quatre règles, jamais violées :

1. **Le pays publié l'emporte sur le nom de ville.** `Paris, Germany` est gardé :
   la source a publié l'Allemagne.
2. **Plusieurs pays : exclusion seulement si *tous* sont exclus.**
   `Paris, France, United Kingdom` est gardé si seul `FR` est exclu ; il est
   exclu si `FR` et `GB` le sont tous les deux.
3. **Un pays inconnu n'est jamais exclu.** `Amsterdam` sans pays reste visible ;
   `Remote` reste visible ; `N/A` reste visible.
4. **Un indice de ville ne peut qu'exclure, jamais inclure.** Les tables
   `CITY_HINT_INDEX` (villes du monde) et `APEC_HINT_INDEX` (villes + régions
   françaises, qu'APEC publie) servent à *retirer* une offre, jamais à en
   déduire un pays.

### 4.3 Indices de ville

La règle historique `france`/`fr` + liste de villes a été **généralisée** :
`_is_france_location(city, country)` devient
`_is_excluded_location(location_text, country, excluded_codes)`, et la table
`_CITY_HINTS` associe ~330 villes à leur pays (Paris→FR, Berlin→DE,
Amsterdam→NL, Milan→IT, Warsaw→PL, Tel Aviv→IL, Singapore→SG…). Exclure `DE`
retire donc aussi une offre « Frankfurt ».

**Les indices ne s'appliquent qu'aux connecteurs scrapés**, qui publient des
libellés de lieu sans pays ; les ATS filtrent sur le **champ pays publié**, comme
le demande la spécification (« Greenhouse / Ashby / offre sans pays → gardée »).

---

## 5. Les huit connecteurs

| Connecteur | Point d'application | Avant normalisation | Filtre sur | Indices de ville |
|---|---|---|---|---|
| Greenhouse | `career/discovery.py::_normalise` | oui (avant `source_html_to_text`) | champ pays + libellé de lieu | non |
| Lever | `public_ats.py::discover_internships` | oui (avant `_normalise_one`) | `categories.location` + `country` | non |
| Ashby | idem | oui | `address.postalAddress` | non |
| SmartRecruiters | idem | oui | `location.city` + `location.country` | non |
| Welcome to the Jungle | `welcome_jungle.py::_iter_raw_offers` | oui (avant le parsing de la description) | libellé de lieu scrapé | oui |
| JobTeaser | idem | oui | idem | oui |
| Talent.com | idem | oui | idem | oui |
| APEC | idem | oui | idem | oui (+ régions FR) |

Chaque connecteur expose `_geo_evidence(raw)` (ATS) ou `_is_excluded_location(...)`
(scrapés) : la décision de filtrage est lisible et testable sans réseau.

---

## 6. Le service

```python
# career/service.py
@staticmethod
def _geo_filter_for_brief(brief) -> tuple[tuple[str, ...], tuple[str, ...]]:
    raw = brief.get("geo_excluded_countries") or brief.get("excluded_countries") or ()
    excluded = excluded_country_codes(raw)
    return excluded or ("FR",), ()
```

Les critères enregistrés nomment les pays **dans les mots de la personne**
(`["France"]`) ; les connecteurs lisent des codes ISO. `get_stage_search()`
définit déjà `excluded_countries = ["France"]` et `excluded_cities = ["Paris"]`
par défaut : la conversion donne donc `("FR",)` sans rien inventer. Un pays
exclu illisible n'est jamais deviné — la France reste exclue parce qu'elle est
la recherche internationale par défaut du produit.

Le filtre est poussé dans `explore_internships()`, c'est-à-dire **au moment où
les connecteurs sont lus**, via une vérification de signature
(`_accepts_keyword`) : un connecteur écrit avant ce filtre continue de
fonctionner, il ne reçoit simplement pas le paramètre.

### 6.1 Périmètre : pourquoi `discover_opportunities()` n'est pas filtré

`discover_opportunities()` est l'**import de board** : il enregistre dans le
tracker local tout ce que le board publie. `explore_internships()` est le
**parcours de recherche** : c'est là que la personne voit les résultats
(`EXPLORATION_MAX_RESULTS = 150`, l'ordre de grandeur des « 120 offres » de la
mission).

Filtrer aussi l'import aurait supprimé du tracker local des offres que les
tests de sélection du dépôt utilisent comme terrain (`"Paris, France"`), et
aurait fait passer une régression de 5 tests pour une économie de CPU que le
filtre de recherche apporte déjà. La mission demande « zéro régression » :
le choix est donc explicite et documenté, pas un oubli.

**Conséquence** : une offre française reste dans le tracker local, mais elle
n'atteint jamais les résultats de recherche et n'est plus jamais qualifiée ni
notée. Elle est déjà écartée des correspondances de stage par
`qualify_offer(excluded_countries=...)` au niveau du service.

### 6.2 `countries_include`

Le paramètre existe sur les huit connecteurs et est testé, mais il **n'est pas**
déduit du brief. La raison : `brief["countries"]` signifie « pays préférés »
et est déjà traité par `criteria_admit` ; le pousser dans un filtre d'inclusion
changerait le classement et les compteurs d'un flux qui fonctionne. Le paramètre
est réservé à une source **100 % ciblée** (EURES, LinkedIn Europe), comme le
précise la mission. Utiliser `countries_include=["DE"]` sur une source publique
retire les offres dont le pays publié n'est pas l'Allemagne, et garde les
offres de pays inconnu.

---

## 7. Fixtures synthétiques

`tests/fixtures/geo_filter/geo_filter_cases.json` : **26 cas**, tous
connecteurs, tous synthétiques (aucun employeur, board ou URL réel). Les
libellés de lieu reprennent la forme exacte que publient les sources.

| # | Connecteur | Cas | Attendu |
|---|---|---|---|
| 1 | Greenhouse | `Paris, France` | filtrée |
| 2 | Greenhouse | `London, United Kingdom` | gardée |
| 3 | Greenhouse | `Paris/London/Berlin` (multi-lieu) | gardée |
| 4 | Greenhouse | sans pays | gardée (inconnu ≠ France) |
| 5 | Greenhouse | `Paris, France` avec `excluded=["DE"]` | gardée |
| 6 | Lever | `Frankfurt, Germany` | gardée |
| 7 | Lever | `Paris, France` | filtrée |
| 8 | Lever | sans pays | gardée |
| 9 | Ashby | sans adresse pays | gardée |
| 10 | Ashby | `Amsterdam, Netherlands` | gardée |
| 11 | Ashby | `Paris, France` | filtrée |
| 12 | SmartRecruiters | pays composite `France, United Kingdom` | gardée (autre pays autorisé) |
| 13 | SmartRecruiters | `Paris / France` | filtrée |
| 14 | SmartRecruiters | `Munich / Germany` avec `included=["DE"]` | gardée |
| 15 | SmartRecruiters | `Lyon / France` avec `included=["DE"]` | filtrée |
| 16 | Welcome to the Jungle | `Paris, France` | filtrée côté client |
| 17 | Welcome to the Jungle | `Berlin, Germany` | gardée |
| 18 | Welcome to the Jungle | `Paris/London` (multi-lieu) | gardée |
| 19 | JobTeaser | `Remote` (entreprise FR) | gardée (remote ≠ France) |
| 20 | JobTeaser | `Paris, France` | filtrée |
| 21 | Talent.com | `Munich, Germany` | gardée |
| 22 | Talent.com | `Paris` (ville seule) | filtrée (indice de ville) |
| 23 | APEC | `Paris` | filtrée |
| 24 | APEC | `London, United Kingdom` | gardée |
| 25 | Greenhouse | `Paris, France` **sans paramètre** | gardée (zéro régression) |
| 26 | Greenhouse | `Paris, France` + `Frankfurt, Germany`, `excluded=["FR","DE"]` | les deux filtrées |

La spécification de la mission demandait 12 fixtures minimum : le corpus en
compte 26 cas et couvre **les huit connecteurs**.

---

## 8. Test live (borné, séparé)

`tests/test_geo_filter_connectors_live.py`, activé par `CAREER_LIVE_TESTS=1` :
un seul board public Greenhouse, une seule lecture, aucune écriture, aucune
candidature envoyée.

```
CAREER_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_geo_filter_connectors_live.py
2 passed in 14.96s
```

Mesures réelles sur le board public `datadog` (439 publications) :

| Compteur | Valeur |
|---|---|
| `raw_count` | 439 |
| `evaluated_count` | 439 |
| `invalid_count` | 0 |
| **`filtered_geo_count`** | **36** |
| `excluded_count` | 240 |
| `relevant_count` | 5 |
| **offres gardées publiées uniquement en France** | **0** |

Les 36 offres retirées sont exactement les publications `Paris, France` (34),
`Bordeaux, France; Grenoble, France; Lyon, France; …` (1) et `France, Remote`
(1) — c'est-à-dire les offres dont **tous** les pays publiés sont exclus. Les
offres multi-pays (`Dublin, Ireland; London, United Kingdom; Paris, France`)
restent visibles, comme le veut la spécification.

Le second test live relit le même board **sans** le paramètre et vérifie que les
offres françaises sont bien présentes : c'est la preuve directe de la règle
« connecteur sans paramètre = comportement actuel ».

---

## 9. Preuves de zéro régression

| Vérification | Résultat |
|---|---|
| `pytest -q` avant | 1424 passés, 1 ignoré |
| `pytest -q` après | **1506 passés, 3 ignorés** (1 ignoré historique + 2 tests live) |
| Tests du dépôt modifiés | **aucun** — aucun fichier de test existant n'a été touché |
| `ruff check .` | *All checks passed* |
| `git diff --check` | propre |
| `./checklist_codex.sh` | **TOUT VERT** |

Les 82 tests ajoutés sont dans deux nouveaux fichiers. Aucun test existant n'a
été réécrit pour faire passer l'implémentation.

---

## 10. Limites connues et hors périmètre

1. **Un indice de ville peut être faux.** `Nice` est une ville française et un
   mot anglais ; `Split` (Croatie) a été retiré de la table pour cette
   raison. Un indice ne sert qu'à *retirer* une offre : le risque est une offre
   retirée à tort, pas une offre gardée à tort.
2. **Le board `datadog` publie des libellés libres** (`SF, NYC, CHI, SEA`,
   `Remote from the US`). Aucun pays n'y est lisible → l'offre est conservée et
   reste à vérifier. C'est le choix assumé : un pays inconnu ne devient jamais
   un pays exclu.
3. **`countries_include` n'est pas câblé sur le brief** (voir § 6.2).
4. **Le filtre n'est pas poussé dans `discover_opportunities()`** (voir § 6.1).
5. `career/connectors/public_ats.py::parse()` reste un primitive de parsing
   brute : il ne filtre pas. Il n'est utilisé que par les tests, jamais par le
   chemin de découverte.
6. Le tableau des pays couvre ~130 pays ; un libellé hors tableau reste
   « inconnu ».

---

## 11. Validation

```bash
./checklist_codex.sh                                  # TOUT VERT
.venv/bin/python -m pytest -q tests/test_geo_filter_connectors.py    # 82 passed
.venv/bin/python -m pytest -q                                         # 1506 passed, 3 skipped
CAREER_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_geo_filter_connectors_live.py  # 2 passed
.venv/bin/python -m ruff check .                                      # All checks passed
git diff --check                                                       # propre
```
