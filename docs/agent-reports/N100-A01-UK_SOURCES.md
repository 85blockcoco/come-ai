# N100-A01 — Connecteur UK (sources internationales finance)

Date : 31 octobre 2026
Mission : **CVBOOST-91 — N100-A01**
Branche de travail : `worker/cvboost-91-1793409071184`
Statut : **TERMINÉE — connecteur borné, lecture seule, 67 tests synthétiques au vert**

---

## 1. Ce qui a été livré

| Fichier | Nature | Rôle |
|---------|--------|------|
| `career/connectors/uk_sources.py` | **nouveau** | Connecteur unique pour Prospects, Gradcracker et TargetJobs : lecture HTML publique bornée, parseur de cartes sémantiques, transport 429, compteurs de santé |
| `career/connectors/__init__.py` | modifié | Enregistrement des trois fournisseurs (`CONNECTOR_SPECS`, `CONNECTOR_REGISTRY`, `default_exploration_connectors`, export `UkSourcesConnector`) |
| `tests/test_uk_sources.py` | **nouveau** | 67 cas de contrat, 100 % synthétiques, aucun socket |
| `tests/fixtures/uk_sources_synthetic.json` | **nouveau** | 3 offres synthétiques par fournisseur (9 au total) |
| `docs/agent-reports/N100-A01-UK_SOURCES.md` | **nouveau** | Ce rapport |

Aucune donnée personnelle, aucun envoi, aucune authentification, aucune écriture distante.
Le connecteur ne lit que les pages publiques qu'un visiteur peut lire.

---

## 2. Le contrat commun

Les trois boards sont servis par une seule classe, `UkSourcesConnector`, qui expose
`providers = ("prospects", "gradcracker", "targetjobs")`. Chaque offre produite reprend
le contrat canonique utilisé par les autres connecteurs HTML :

- `source_name`, `source_id`, `official_url`, `apply_url` ;
- `company`, `title`, `city`, `country`, `country_canonical` ;
- `employment_type`, `description_original`, `source_status`, `source_verified` ;
- `source_fields[<provider>]` via `attach_source_material()`.

Les champs visibles et les attributs publiés (dont `data-job-id`, `data-offer-id`,
`data-vacancy-id` et `<time datetime>`) sont transmis **sous leur nom de source**,
sans renommage ni interprétation. C'est la couche d'admission
(`career.exploration.admit_offer`) qui décide si une offre correspond au brief ;
le connecteur ne tranche pas.

### Identité de la source

`discover_internships()` refuse :

- un fournisseur hors `prospects` / `gradcracker` / `targetjobs` (`invalid_source`) ;
- une source sans `id`, `company`, `verified_at` ou `provenance_url`
  (`unverified_source`).

### Liens

Un lien de carte n'est accepté que s'il reste sur l'hôte du board. Les liens absolus
vers un autre hôte, les schémas non HTTP(S) et les URL porteuses d'identifiants sont
écartés. Les pages de catégorie TargetJobs (`/internships/finance`) ne sont pas prises
pour des offres : un dernier segment sans chiffre et sans sous-chemin est rejeté.

---

## 3. Bornes et honnêteté du transport

| Borne | Valeur |
|-------|--------|
| Pages par fournisseur | 3 |
| Délai entre requêtes | 2 s (limite partagée) |
| Taille maximale d'une réponse | 8 Mio |
| Lignes évaluées | 300 |
| Résultats retournés | 150 |
| Retries sur HTTP 429 | 2 |
| Backoff | exponentiel 1 s puis 2 s, plafonné à 8 s |

- **429** : le délai `Retry-After` est honoré s'il est numérique et borné ; sinon le
  backoff exponentiel s'applique. Le compteur `throttled_requests` est exposé.
- **User-Agent** : `ComeAI-StageBot/1.0 (read-only internship search)`.
- **Erreurs** : 4xx/5xx, timeouts, erreurs réseau et réponses surdimensionnées
  renvoient `None`, sont enregistrés dans `health_check()` et n'interrompent jamais
  les autres pages.
- **Budget** : `deadline` (monotone) et plafond de lignes lèvent
  `PublicSourceError(code="budget" | "too_many_rows")`.

---

## 4. Géographie

Les trois sources sont UK-first :

- une localisation réduite à une ville (`Leeds`) est complétée par
  `United Kingdom`, puis canonicalisée en `GB` ;
- une localisation complète (`Paris, France`) est lue par `split_location()` et
  canonicalisée par `country_from_source()` ;
- une offre dont le pays est dans `countries_exclude` est écartée **côté source**,
  avant d'entrer dans le flux évalué. Elle est comptée dans
  `excluded_by_country`, `country_excluded_count` et `health_check()`.

Variantes françaises (`France`, `FRANCE`, `fr`, `FRA`) toutes reconnues.
Une liste d'exclusion vidée (`{"countries_exclude": []}`) laisse passer la France.

---

## 5. Parseur HTML

Le parseur est volontairement défensif plutôt que dépendant d'un DOM live :

- il reconnaît une carte par son wrapper (`article`, `li`, `div`), un marqueur de
  classe/`data-testid` (`job-card`, `job-result`, `vacancy`, `search-result`,
  `result-card`, `opportunity`, `offer-card`) ou un identifiant `data-*` d'offre ;
- il ignore les cartes imbriquées et les balises `script`, `style`, `noscript`,
  `template` ;
- il ne publie une carte que si un titre **et** un lien d'offre valide ont été lus ;
- il tolère un HTML tronqué ou mal formé sans lever ;
- Gradcracker a répondu `403` à une lecture automatisée pendant l'écriture ; le
  parseur garde donc le même contrat sémantique de carte au lieu de supposer un DOM
  qui n'a pas pu être observé. Aucun test n'ouvre de socket.

Le connecteur ne dépend pas de `career/source_normalizer` : ce module n'existe pas
dans le dépôt. La normalisation utilise `models.clean_text`, `models.canonical_url`,
`countries` et `source_fields`, comme les autres connecteurs.

---

## 6. Compteurs

`DiscoveryPayload` reste cohérent avec le contrat du service :

```
raw_count = evaluated_count + invalid_count
evaluated_count = confirmed_count + uncertain_count + excluded_count
relevant_count + filtered_criteria_count = confirmed_count + uncertain_count
```

`health_check()` expose en plus `raw_offers`, `valid_offers`, `finance_offers`,
`stage_offers`, `conforming_offers`, `to_verify_offers`, `raw_count`,
`filtered_count`, `excluded_count`, `excluded_by_country` et `throttled_requests`.

---

## 7. Tests

`tests/test_uk_sources.py` — **67 cas**, tous synthétiques :

- enregistrement et specs des trois fournisseurs ;
- mapping vers le contrat commun, identifiant et timestamp publiés inchangés ;
- champs manquants, description absente, carte sans titre ;
- hôte étranger, identifiants dans l'URL, lien de catégorie, tracking retiré ;
- exclusion France et variantes, liste vidée, ville seule, localisation à tiret ;
- bornes `max_pages`, `max_results`, plafond de lignes, deadline ;
- cohérence des compteurs et métriques de santé ;
- source non-UK, provenance manquante ;
- URL de recherche, clamp de page, fournisseur refusé ;
- 429 retenté puis abandonné, `Retry-After` honoré et borné, backoff exponentiel,
  rate limit, User-Agent, réponse surdimensionnée, 500, erreur réseau ;
- scripts/styles retirés de la description, entités HTML décodées.

Résultat :

```
$ .venv/bin/python -m pytest -q tests/test_uk_sources.py
67 passed

$ .venv/bin/python -m ruff check career/connectors/uk_sources.py \
    career/connectors/__init__.py tests/test_uk_sources.py
All checks passed!

$ git diff --check
(propre)
```

La suite complète n'a pas été lancée, conformément au contrat de sortie de la mission.

---

## 8. Ce que ce connecteur ne fait pas

- Il ne soumet aucune candidature.
- Il ne s'authentifie pas et ne stocke aucun cookie de session.
- Il ne suit pas un lien hors du board.
- Il n'interprète ni les dates ni les prérequis : ces décisions restent dans
  `offer_dates`, `offer_requirements` et la couche d'admission.
- Il ne prétend pas que Gradcracker est lisible en direct : le parseur suit un
  contrat sémantique vérifié par fixtures, et un contrôle live séparé reste
  nécessaire avant toute activation.
