# SPEC-SK14 — Sources spécialisées étranger (100% hors-France)

**Branche** : `worker/cvboost-41-1792654419` (worktree dédié `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-41-1792654419`), branche de registre `agent/spec-sk14-intl-sources`
**Base** : `main` (SHA `f5b22f2`) + dépendance **SK-11** intégrée (voir §2)
**Date** : 2026-10-22
**Auteur** : Agent Mission 41 (SK-14)

---

## 1. Ce qui a été livré

Quatre sources internationales lisent des offres **hors de France** et les
remettent au même contrat que les connecteurs français : admission,
qualification, classement, compteurs factuels. Le pays exclu n'est **jamais
demandé** à la source, et **jamais** renvoyé quand la source le publie
malgré tout.

| Fichier | Rôle |
|---|---|
| `career/connectors/intl_common.py` | **Nouveau** — plomberie partagée : lecteur HTTP poli (robots.txt, `Crawl-delay`, intervalle, taille bornée, hôtes autorisés), parseur de cartes tolérant, vocabulaire de rôle, lecture du pays canonique, santé des compteurs, boucle d'admission et de classement |
| `career/connectors/linkedin_europe.py` | **Nouveau** — recherche publique LinkedIn (invité), pays par pays via `location` |
| `career/connectors/eures.py` | **Nouveau** — API publique EURES (JSON), filtre pays dans `countryCodes` |
| `career/connectors/jobteaser_intl.py` | **Nouveau** — JobTeaser international, filtre pays dans `countries` |
| `career/connectors/glassdoor_intl.py` | **Nouveau** — Glassdoor international, filtre pays via `locId` |
| `career/connectors/__init__.py` | Enregistrement des 4 connecteurs (`CONNECTOR_SPECS`, `CONNECTOR_REGISTRY`, `default_exploration_connectors()`) |
| `tests/test_intl_sources.py` | **Nouveau** — 67 tests synthétiques (aucun socket ouvert) |
| `tests/fixtures/intl_sources/` | **Nouveau** — 4 fixtures synthétiques (HTML ×3, JSON ×1) |
| `docs/agent-reports/SPEC-SK14-INTL_SOURCES.md` | Ce rapport |
| `messages/result.json` | Rapport worker (lu par l'orchestrateur) — **non versionné** : le répertoire `messages/` est l'état de travail de l'orchestrateur, il ne doit pas entrer dans l'historique |

Fichier de test existant mis à jour (conséquence assumée du changement de
comportement, voir §7) : `tests/test_career_public_ats_connectors.py`.

---

## 2. La dépendance SK-11 était absente de la base

La mission déclare une dépendance à **SK-11** (filtre pays côté
connecteurs). Cette dépendance **n'était pas dans `main`** : `main` était
arrêtée à `f5b22f2` et ne contenait ni `career/countries.py` ni le contrat
`countries_exclude`.

Plutôt que de réinventer un vocabulaire pays — et de créer une collision
au moment de l'intégration — j'ai **intégré SK-11 par cherry-pick** des
trois commits qui portent le cœur du filtre :

| Commit | Portée |
|---|---|
| `3989b75` | `career/countries.py` (vocabulaire ISO canonique), filtre à la source des 5 connecteurs existants, `countries_exclude` dans le brief, métriques de payload |
| `3d0bedd` | Séparateurs de localisation partagés, repli TLS `certifi` |
| `cc6e68f` | Métriques de filtrage pays sur le payload |

Deux conflits ont été résolus à la main, tous deux dans le **rapport** de
SK-11 (fichier ajouté par SK-11, absent de `main`) : la version du rapport
au sommet de la branche SK-11 (`2c3e6a0`) a été retenue.

**Conséquence** : la branche livrée contient déjà SK-11. Le reviewer n'a
donc **pas** à fusionner SK-11 avant SK-14, et les deux missions se
fusionnent sans conflit de contenu (mêmes fichiers, même résultat).

---

## 3. Le contrat des sources internationales

### 3.1 Le pays est demandé à la source, pas filtré après coup

Chaque connecteur construit sa requête avec **seulement** les pays
autorisés. Le pays exclu n'est jamais demandé : il ne coûte pas de
requête, ne transite pas par la base et ne consomme pas de place.

| Connecteur | Requête | Filtre natif |
|---|---|---|
| LinkedIn Europe | `…/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=…&location=<pays>&f_WT=4&f_E=1&f_TPR=r604800&start=<offset>` | `location` = un pays par requête |
| EURES | `…/eures/eures-api/search?language=en&countryCodes=<codes>&pageSize=100&pageNumber=<n>` | `countryCodes` = les codes autorisés |
| JobTeaser International | `…/en/jobs?query=…&contract_type=internship&countries=<codes>&page=<n>` | `countries` = les codes autorisés |
| Glassdoor International | `…/Job/jobs.htm?sc.keyword=…&locT=C&locId=<id>&p=<n>` | `locId` = un pays par requête |

### 3.2 Le pays est relu sur les faits publiés

Le filtre est appliqué **deux fois**, et c'est volontaire : la requête
évite le pays exclu, mais une source peut répondre avec une offre d'un
autre pays. Le connecteur relit alors le pays **que la source publie**
(« Berlin, Germany », `location.countryCode`, …) et écarte l'offre **avant**
qu'elle ne devienne un enregistrement local.

Le pays n'est jamais deviné : une ville ne désigne pas un pays
(« Frankfurt » n'est pas `FR`), et une localisation sans pays reste
**inconnue** — elle n'est ni exclue, ni transformée.

Le code canonique vient du vocabulaire de SK-11 (`career/countries.py`) :
`FR`, `fr`, `FRA`, `France` → `FR` ; `DE`, `Germany` → `DE` ; etc.

### 3.3 Les compteurs de la santé

`health_check()` publie l'état factuel de la dernière lecture :

```json
{
  "last_ok": true, "last_error": null, "consecutive_failures": 0,
  "raw_offers": 13, "valid_offers": 5, "finance_offers": 4, "stage_offers": 5,
  "conforming_offers": 4, "to_verify_offers": 1,
  "raw_count": 13, "filtered_count": 8, "excluded_count": 8,
  "country_excluded_count": 8, "filtered_geo_count": 8,
  "excluded_by_country": {"FR": 8},
  "countries_seen": {"DE": 1, "GB": 1, "NL": 1, "CH": 1, "BE": 1},
  "france_ratio": 0.0, "requests": 8, "budget_exhausted": false
}
```

`france_ratio` est la part d'offres françaises **du corpus retenu** : une
source correctement filtrée publie `0.0`. Les offres écartées pour leur
pays sont comptées à part, dans `excluded_by_country`.

`filtered_geo_count` est le nom de la mission ; `country_excluded_count`
est le nom que SK-11 a déjà donné au même compteur sur le payload. Les
deux nomment **le même fait** et sont publiés tous les deux, dans
`health_check()` et sur le payload.

### 3.4 La politesse de la lecture

* **Hôtes autorisés** : chaque connecteur ne contacte que son ou ses hôtes ;
  une redirection vers un autre hôte est refusée.
* **`robots.txt`** : lu et respecté (`Allow` / `Disallow`, règle la plus
  longue, `Allow` l'emporte à égalité) ; un `robots.txt` illisible est
  traité comme « aucune règle publiée ».
* **`Crawl-delay`** : appliqué quand la source le publie ; l'intervalle
  propre du connecteur s'y ajoute s'il est plus court.
* **Intervalle** : LinkedIn 3 s, Glassdoor 5 s, JobTeaser 2 s, EURES 1 s.
* **Taille** : 8 Mio de corps maximum ; un corps plus gros est refusé.
* **Budget** : le nombre de requêtes d'une lecture est borné
  (`max_requests`), et la lecture s'interrompt quand le budget réseau de
  l'exploration est atteint.
* **Identité** : l'agent s'identifie honnêtement
  (`ComeAI-Career/1.0 (read-only public job source)`) et **ne fait pas
  tourner les identités** pour se faire passer pour quelqu'un d'autre.
  C'est un écart assumé par rapport à la mission (§6.1).

### 3.5 Le partage du code

Les quatre connecteurs partagent `career/connectors/intl_common.py` :
lecteur HTTP, parseur de cartes, lecture du pays, boucle d'admission,
compteurs. Chaque connecteur ne garde que ce qui lui est propre : son
URL, son parseur, ses pays, sa limite de débit. Le même contrat existe
déjà dans le dépôt (`career/connectors/public_ats.py`) : il n'y a donc pas
de nouvelle convention, seulement une généralisation.

---

## 4. Les quatre sources

### 4.1 LinkedIn Europe (`linkedin_europe.py`)

| | |
|---|---|
| Point d'entrée | `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` |
| Page publique | `https://www.linkedin.com/jobs/search` |
| Pays | DE, GB, NL, CH, BE, LU, IE, AT, SE, NO, DK, FI, ES, IT, PT, PL |
| Filtre natif | `location=<pays>` (un pays par requête) |
| Débit | 1 req / 3 s, 25 résultats par page, 8 requêtes au plus par lecture |
| Tier | `aggregator` |

Les cartes sont lues dans le fragment HTML public (`base-search-card`,
`base-card__full-link`, `job-search-card__location`, `<time datetime=…>`).
**La recherche invitée ne publie pas de description** : le champ reste
vide, l'offre est donc classée « à vérifier » quand la date de début est
inconnue. C'est un fait de la source, pas une lacune du connecteur.

Les pays sont lus **en tourniquet** : chaque pays reçoit une page avant
qu'un pays reçoive une seconde page. Un budget de requêtes limité donne
donc sa part à chaque pays au lieu de tout donner aux premiers.

### 4.2 EURES (`eures.py`)

| | |
|---|---|
| Point d'entrée | `https://ec.europa.eu/eures/eures-api/search` |
| Documentation | `https://ec.europa.eu/eures/eures-api/swagger-ui.html` |
| Pays | 31 codes UE/EEE/CH, France exclue |
| Filtre natif | `countryCodes=<codes>` — **une seule requête** pour tous les pays |
| Débit | 1 req / 1 s, 100 résultats par page, 5 pages au plus |
| Tier | **`official`** — service public de la Commission européenne |

C'est la seule source JSON : le connecteur lit `title`, `employerName`,
`location` (ville + `countryCode`), `contractType`, `description`,
`applicationUrl`, `publicationDate`, `startDate` et `duration` (en mois).
Les dates sont lues au format EURES (jour ISO **ou** millisecondes
d'époque) ; une date illisible reste vide.

L'enveloppe de réponse a changé au fil des versions de l'API : le lecteur
accepte `result.items`, `items`, `results`, `offers`, `jobs` et une liste
 nue, et **n'invente rien** devant une forme inconnue.

### 4.3 JobTeaser International (`jobteaser_intl.py`)

| | |
|---|---|
| Point d'entrée | `https://www.jobteaser.com/en/jobs` |
| Pays | DE, GB, NL, BE, CH, ES, IT, PT |
| Filtre natif | `countries=<codes>` — une requête pour tous les pays |
| Débit | 1 req / 2 s, 5 pages au plus |
| Tier | `aggregator` |

C'est la face internationale du même portail que le connecteur français
`career/connectors/jobteaser.py` : même lecture de cartes, filtre pays
différent. Voir §6.2 pour le chemin de l'endpoint.

### 4.4 Glassdoor International (`glassdoor_intl.py`)

| | |
|---|---|
| Point d'entrée | `https://www.glassdoor.com/Job/jobs.htm` |
| Pays | US, CA, GB, DE, NL, CH, BE, AT, IE, SE, NO, DK, FI, ES, IT, PT, PL, LU, AU, NZ, SG |
| Filtre natif | `locId=<identifiant pays>` + `locT=C` |
| Débit | 1 req / 5 s, 3 pages au plus, 4 requêtes au plus par lecture |
| Tier | `aggregator` |

Les identifiants de pays de Glassdoor sont **au mieux** : un portail peut
les réorganiser. C'est pourquoi la garantie n'est pas l'identifiant mais
la **relecture du pays publié** (§3.2) : un `locId` erroné ne peut pas
faire passer une offre française. Une source peut publier ses propres
identifiants (`location_ids`).

---

## 5. Les tests

`tests/test_intl_sources.py` — **67 tests**, tous synthétiques. Le module
`socket` est **bloqué** pendant toute la suite : un connecteur qui tenterait
le réseau ferait échouer le test au lieu de passer inaperçu.

| Famille | Ce qui est vérifié |
|---|---|
| Enregistrement | Les 4 connecteurs sont dans `CONNECTOR_SPECS` (avec URL de documentation vérifiée), dans `CONNECTOR_REGISTRY` et dans `default_exploration_connectors()` |
| Contrat commun | `DiscoveryPayload` valide, `source_verified=True`, `source_id`, URL officielle, pays canonique, compteurs cohérents (les trois égalités que le service exige), au moins une offre rendue |
| Santé | Les 11 clés de la mission sont publiées, `france_ratio == 0.0`, `countries_seen` sans `FR`, `valid_offers == somme(countries_seen)` |
| Filtre pays | Le pays exclu n'est **jamais demandé** (URL inspectées pour les 4 connecteurs) ; le pays exclu n'est **jamais rendu** ; **contre-test** : exclusion vidée → l'offre française revient (donc c'est bien le filtre qui l'écartait) ; une réponse EURES française est écartée alors que la France n'a jamais été demandée |
| Faits publiés | Titre, employeur, ville, pays, date de publication, date de début, durée, contrat, description (HTML converti en texte) |
| Frontière de source | Source non vérifiée refusée (`unverified_source`), source d'un autre fournisseur refusée (`invalid_source`), connecteur désactivé → **aucune requête** |
| Politesse | Intervalle respecté entre deux requêtes, hôte hors liste jamais contacté, `robots.txt` respecté, `Crawl-delay` appliqué, budget de requêtes borné, tourniquet des pays, arrêt propre à l'épuisement du budget |
| Dépendances | Analyse AST : **aucune** dépendance hors bibliothèque standard (seule exception tolérée : `certifi`, importé sous condition, avec repli standard) |
| Parcours réel | Le point d'entrée partagé `discover_stage_offers()` transmet l'exclusion ; **parcours de bout en bout** : le service d'exploration lit un connecteur international et **aucune offre française n'entre dans la base locale** |

### 5.1 Les chiffres des fixtures

| Connecteur | Requêtes | Offres brutes | Écartées (pays) | Offres rendues | `countries_seen` | `france_ratio` |
|---|---|---|---|---|---|---|
| LinkedIn Europe | 8 | 13 | 8 (`FR`) | 5 | DE 1, GB 1, NL 1, CH 1, BE 1 | 0.0 |
| EURES | 1 | 10 | 0 | 8 | DE, GB, NL, AT, ES, IT, PT, PL, BE, FI | 0.0 |
| JobTeaser International | 1 | 6 | 1 (`FR`) | 5 | DE, GB, NL, BE, ES | 0.0 |
| Glassdoor International | 4 | 9 | 4 (`FR`) | 5 | US 1, CA 1, GB 2, DE 1 | 0.0 |

Sur EURES, deux offres sur dix sont écartées **par la qualification** et
non par le pays : leur durée (4 et 5 mois) est inférieure aux 6 mois
demandés. C'est le comportement attendu, et il est distinct du filtre
géographique.

Sur LinkedIn et Glassdoor, toutes les offres rendues sont « à vérifier » :
les cartes de ces portails ne publient ni description complète ni date de
début. Le connecteur ne comble pas le vide.

---

## 6. Écarts assumés

### 6.1 `source_tier` : `official` et `aggregator`, pas `employer`

La mission demande `source_tier = "employer"` ou `"official"`. Seule la
valeur `official` est tenable ici :

* **EURES** est un service public de la Commission européenne → `official` ;
* **LinkedIn, JobTeaser et Glassdoor** sont des portails qui **republient**
  des offres écrites par des employeurs. Les nommer `employer`
  affirmerait que l'employeur a publié l'offre — un fait que personne
  n'a publié — et leur donnerait la priorité de déduplication maximale
  sur cette base fausse. Ils sont donc `aggregator`.

Le vocabulaire est explicite dans `career/connectors/intl_common.py`
(`SOURCE_TIER_OFFICIAL`, `SOURCE_TIER_EMPLOYER`, `SOURCE_TIER_AGGREGATOR`)
et un test verrouille l'invariant : **aucun connecteur ne revendique
`employer`**, et l'URL de chaque offre reste sur le domaine du portail
qui l'a republiée. `employer` reste réservé aux offres publiées par le
domaine de l'employeur lui-même.

### 6.2 Endpoint JobTeaser : `/en/jobs`, pas `/en/jobs/search`

La mission indique `https://www.jobteaser.com/en/jobs/search`. Le
connecteur français jumeau (`career/connectors/jobteaser.py`), vérifié
manuellement sur la page publique le 2026-10-20, utilise
`https://www.jobteaser.com/en/jobs`. J'ai retenu le chemin vérifié : un
chemin inventé aurait renvoyé une erreur 404 en production. Le filtre
pays, lui, est bien celui de la mission (`countries=`).

### 6.3 Pas de rotation d'agent utilisateur

La mission évoque une « rotation d'user-agent » pour Glassdoor. Roter
son identité pour contourner une protection anti-robot est une
contournement : je ne l'ai pas fait. Le connecteur s'identifie
honnêtement, respecte `robots.txt`, attend 5 secondes entre deux
requêtes et borne sa lecture. C'est plus lent, et c'est voulu.

### 6.4 `filtered_geo_count` : un alias, pas un nouveau champ de payload

SK-11 a déjà nommé ce compteur `country_excluded_count` sur le payload
(`DiscoveryPayload`). Modifier `career/discovery.py` pour ajouter un
second nom aurait créé un conflit d'intégration avec SK-11 sur le même
fichier. Le compteur est donc publié sous les **deux noms** dans
`health_check()` (`filtered_geo_count` et `country_excluded_count`), et
sous le nom de SK-11 sur le payload. Les deux décrivent le même fait.

### 6.5 Budget réseau : arrêt propre plutôt qu'erreur

Les connecteurs français lèvent `PublicSourceError(code="budget")` quand
le budget de 60 secondes est atteint, ce qui **jette** les offres déjà
lues. Une source internationale lit plusieurs pays dans une même lecture :
une coupure y est attendue, pas exceptionnelle. Le connecteur s'arrête,
conserve ce qu'il a lu, marque la lecture comme incomplète
(`truncated=True`, `budget_exhausted=True`) et rend un payload cohérent.

### 6.6 `enabled` : le connecteur désactivé ne lit rien

Comme le squelette de la mission l'indique, un connecteur non activé
refuse de lire (`code="connector_disabled"`) et n'envoie **aucune**
requête. La carte d'exploration les active explicitement, comme les
connecteurs existants.

---

## 7. Régressions assumées

`tests/test_career_public_ats_connectors.py` affirmait que la carte
d'exploration contenait **exactement** huit connecteurs. La mission demande
explicitement d'intégrer les quatre nouveaux dans
`default_exploration_connectors()` : l'affirmation a été mise à jour, et
elle vérifie maintenant aussi que les quatre connecteurs sont activés dans
la carte et **désactivés** à la construction directe.

Aucun autre fichier existant n'est modifié. Le service, le routeur, la
base et l'interface sont intacts.

---

## 8. Hors périmètre

* **Aucune source n'est ajoutée à `career/source_registry.py`.** Le
  registre n'accueille que « des sources identifiées depuis une page
  officielle d'employeur et réellement consultées ». Or la mission
  impose des **fixtures synthétiques** et interdit les vraies requêtes :
  écrire un `verified_at` pour une source jamais consultée serait une
  fausse preuve. Les quatre connecteurs sont donc enregistrés et
  activés dans la carte, mais **dormants** tant qu'une source curatée
  n'existe pas pour leur fournisseur — comportement documenté de toute la
  carte (« with no registered source for a provider, enabling it performs
  no I/O »).
* **Aucune modification de `career/discovery.py`, `career/service.py`,
  `career/router.py`, `career/stage_search.py` ou de l'interface.** La
  mission porte sur les connecteurs.
* **Aucune exécution réelle.** La mission demande des fixtures
  synthétiques et « pas de vraies requêtes en CI ». Les points d'entrée
  et la structure des cartes sont déduits de l'observation publique
  documentée dans la mission et de la cohérence avec les connecteurs
  jumeaux ; ils sont relus de façon tolérante (un nom de classe inconnu
  donne **moins** de faits, jamais de faux faits), et la garantie du
  pays ne repose pas sur le HTML mais sur la relecture canonique.
* **Aucun « Connecteurs » dans l'interface.** Le registre de sources et
  l'interface ne sont pas modifiés : c'est une autre mission.

---

## 9. Commandes de validation

```bash
VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python ./checklist_codex.sh all
.venv/bin/python -m pytest -q tests/test_intl_sources.py     # 67 passed
.venv/bin/python -m pytest -q                                # 1524 passed, 1 skipped
.venv/bin/python -m ruff check .                             # All checks passed
git diff --check                                             # propre
```

| Étape | Résultat |
|---|---|
| `pytest -q tests/test_intl_sources.py` | **67 passés** |
| `pytest -q` (suite complète) | **1524 passés, 1 ignoré** (base `main` : 1424 ; +33 tests SK-11 intégrés ; +67 tests SK-14) |
| `ruff check .` | **All checks passed** |
| `git diff --check` | propre |
| `./checklist_codex.sh all` | **TOUT VERT** |

---

## 10. Ce que le reviewer doit relire en priorité

1. **Le double filtre** (§3.1 et §3.2) : la requête évite le pays exclu,
   et la relecture du pays publié l'écarte malgré tout. C'est la garantie
   centrale de la mission.
2. **Le tier `aggregator`** (§6.1) : écart volontaire et argumenté par
   rapport au vocabulaire demandé ; c'est le point le plus susceptible
   d'être contesté.
3. **L'arrêt propre à l'épuisement du budget** (§6.5) : écart volontaire
   par rapport au `PublicSourceError(code="budget")` des connecteurs
   français.
4. **Les identifiants de pays de Glassdoor** (§4.4) : au mieux, et
   neutralisés par la relecture du pays publié.
5. **Le budget de requêtes** (`max_requests` : 8 pour LinkedIn, 4 pour
   Glassdoor) : à recaler selon le budget réseau réel de l'exploration
   quand une source curatée existera.
