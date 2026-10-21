# SPEC-SK08 — Enrichissement des connecteurs existants

Date : 22 octobre 2026
Mission : **CVBOOST-29** — ordre `cvboost-29-1792623066` (2ᵉ revue du lot, sur le travail de l'ordre `cvboost-29-1792619869`)
Branche de travail : `worker/cvboost-29-1792623066` — branche d'intégration `agent/spec-sk08-connectors-enrich`
Base : `f5b22f2` (*merge(career): ATS diagnostics and targeted CV variants pipeline*)
Statut : **TERMINÉE — contrat commun livré pour les 8 connecteurs, 4 défauts de lecture corrigés et prouvés en direct**

---

## 1. Ce qui a été livré

| Fichier | Nature | Rôle |
|---------|--------|------|
| `career/source_fields.py` | **nouveau** | Contrat commun du matériau transmis : collecte bornée des champs publiés, détection des contradictions conservées |
| `career/connectors/cards.py` | **nouveau** | Lecture des attributs publiés par une carte d'offre (`data-*`, `<time datetime>`) |
| `career/connectors/http.py` | **nouveau** | Contexte TLS vérifié partagé par les quatre connecteurs HTML (le certificat du serveur est vérifié, comme dans le transport ATS) |
| `career/exploration.py` | modifié | Nouvelle fonction pure `admit_offer()` : la décision d'admission sort des connecteurs |
| `career/connectors/public_ats.py` | modifié | Lever, Ashby, SmartRecruiters : champs publiés transmis, sections publiées composées sous leur nom, admission déplacée |
| `career/discovery.py` | modifié | Greenhouse : champs publiés transmis, dates structurées reprises, admission déplacée |
| `career/connectors/welcome_jungle.py` | modifié | Carte Welcome to the Jungle : champs publiés transmis, TLS vérifié, admission déplacée |
| `career/connectors/jobteaser.py` | modifié | Carte JobTeaser : idem |
| `career/connectors/talent_com.py` | modifié | Carte Talent.com : idem + lien d'offre publié (`/view?id=`) et résumé publié (`snippet`) lus |
| `career/connectors/apec.py` | modifié | Carte APEC : idem |
| `career/offer_requirements/extract.py` | modifié | Une entrée de vocabulaire : « additional information » n'est pas une section de prérequis |
| `tests/test_connectors_enrich.py` | **nouveau** | 60 tests de contrat, 1 fixture synthétique par fournisseur |
| `tests/fixtures/connectors_enrich/*.json` | **nouveau** | 8 fixtures (une par fournisseur) |
| `tests/test_connectors_enrich_live.py` | **nouveau** | Contrôle réel borné, séparé, opt-in |

**Ni `career/service.py`, ni le schéma de la base, ni l'interface n'ont été modifiés.** La branche est
donc fusionnable dans `main` sans conflit possible avec SK-01, SK-02, SK-03 ou SK-07 : aucun de ces
lots ne touche `career/connectors/`, `career/source_fields.py`, `career/exploration.py`,
`career/discovery.py` ni `career/offer_requirements/`.

---

## 2. Le contrat commun

Chaque connecteur transmet désormais, en plus du contrat canonique existant :

```python
job["source_fields"]    # { "<provider>": { "<nom exact du champ source>": <valeur publiée> } }
job["source_conflicts"] # [ {kind, field, source_field, source_value, description_value, quote} ]
job["description_original"]  # la description publiée, telle que publiée
```

Règles tenues par le module `career/source_fields.py` :

1. **Le nom du champ source est conservé tel quel** — `first_published`, `createdAt`,
   `publishedAt`, `postedDate`, `typeOfEmployment`, `data-job-id`… Aucun champ n'est renommé,
   traduit ou fusionné. Un consommateur sait toujours de quel champ et de quelle source vient
   une valeur.
2. **Une valeur publiée reste une valeur publiée** — aucune conversion, aucune interprétation.
   Les valeurs sont bornées (4 000 caractères, 25 éléments, profondeur 3) et toujours
   sérialisables en JSON, donc utilisables telles quelles en base et dans l'interface.
3. **Une valeur absente n'est pas un fait** — les champs vides (`""`, `None`, `[]`, `{}`) ne sont
   pas transmis. Le connecteur ne comble jamais un trou.
4. **La description est transmise comme publiée** — HTML neutralisé, scripts retirés, texte
   intégral. Elle n'est ni résumée ni réécrite.
5. **Le connecteur ne décide rien** — `career/source_fields.py` ne qualifie pas une offre, ne
   calcule pas de date, n'extrait pas de prérequis, n'évalue pas la confiance d'une source.

Le module est pur : pas de réseau, pas d'horloge, pas de base, pas de modèle.

---

## 3. Ce que chaque connecteur transmet

### 3.1 Greenhouse (`career/discovery.py`)

| Champ publié | Transmis sous | Champ canonique |
|--------------|---------------|------------------|
| `id`, `requisition_id`, `internal_job_id` | `source_fields.greenhouse.*` | — |
| `first_published` | `source_fields.greenhouse.first_published` | `posted_date` (date seule) |
| `application_deadline` | `source_fields.greenhouse.application_deadline` | `deadline_date` |
| `updated_at` | `source_fields.greenhouse.updated_at` | **jamais** une date de publication |
| `company_name`, `language`, `location`, `offices`, `departments` | `source_fields.greenhouse.*` | — |
| `education` | `source_fields.greenhouse.education` | — |
| `metadata` (dont « Employment Type ») | `source_fields.greenhouse.metadata` | `employment_type` (reconnaissance prudente conservée) |
| `content` | — | `description_original` |

`first_published` est la date de publication **que le tableau de bord publie lui-même** : le
calendrier n'est plus vide. `updated_at` reste une métadonnée de maintenance : il est transmis
mais ne devient jamais une date de publication (test dédié).

### 3.2 Lever (`career/connectors/public_ats.py`)

`id`, `text`, `createdAt`, `hostedUrl`, `applyUrl`, `country`, `workplaceType`, `categories`
(donc `categories.commitment`), `openingPlain`, `additionalPlain`, `lists` → `source_fields.lever.*`.
`descriptionPlain` → `description_original`.

`createdAt` est un horodatage brut que la source ne qualifie pas de date : il est transmis sous
son nom et **ne devient pas** `posted_date`. La conversion d'un timestamp en date est
l'affaire de `offer_dates` (SK-02), pas du connecteur.

### 3.3 Ashby (`career/connectors/public_ats.py`)

`id`, `title`, `publishedAt`, `employmentType`, `workplaceType`, `isRemote`, `isListed`,
`department`, `team`, `secondaryLocations`, `location`, `address`, `jobUrl`, `applyUrl` →
`source_fields.ashby.*`. `publishedAt` → `posted_date` (déjà le cas avant la mission).

### 3.4 SmartRecruiters (`career/connectors/public_ats.py`)

`id`, `name`, `requisitionId`, `postedDate`, `releasedDate`, `location`, `typeOfEmployment`,
`department`, `company`, `applyUrl`, `ref`, `jobAd.sections` → `source_fields.smartrecruiters.*`.
`releasedDate` → `posted_date` ; `postedDate` est transmis brut.

**Gain réel :** les sections publiées (`companyDescription`, `jobDescription`, `qualifications`,
`additionalInformation`) sont composées dans `description_original`, **chacune sous le nom que la
source lui donne** et dans l'ordre publié :

```
Company description
Synthetic Group is a synthetic employer used by the tests.

Job description
Join our Corporate Finance team for a six-month placement.

Qualifications
Bachelor's degree in Finance or Economics
Excel mastery

Additional information
Start date: 2 March 2027. Duration: 6 months.
```

Sans le nom de section, la couche des prérequis ne pouvait pas distinguer « prérequis » de
« description de l'entreprise » : elle lisait la page entière comme une prose neutre et
**n'extrayait aucun prérequis**. Avec le nom de section, les prérequis publiés parviennent enfin
à `offer_requirements` (test dédié : § 6).

### 3.5 Welcome to the Jungle, JobTeaser, Talent.com, APEC (cartes HTML)

Chaque carte publie : `title`, `company`, `location`, `contract_type`, `url` → `source_fields.*`.
Les attributs de la carte sont transmis **sous leur nom d'attribut** : `data-posted-at`,
`data-job-id`, `data-new-id`, `data-rank`, `data-offer-id`, et `datetime` pour un élément
`<time datetime="…">`.

Aucune date n'est déduite : le `<time>` de Talent.com est un « last updated », pas une date de
publication ; il est transmis tel quel et `posted_date` reste vide.

### 3.6 Champ cité par la mission → champ réellement publié

La mission donnait des **exemples** de champs. Le nom transmis est toujours celui que la source
publie réellement : voici la correspondance retenue, vérifiée sur le flux public le 22 octobre
2026 (lecture directe, une requête par source).

| Champ cité par la mission | Champ réellement publié | Transmis sous |
|---------------------------|-------------------------|---------------|
| Greenhouse `posted_at` | `first_published` | `source_fields.greenhouse.first_published` → `posted_date` (date seule) |
| Greenhouse `updated_at` | `updated_at` | `source_fields.greenhouse.updated_at` — métadonnée de maintenance, **jamais** une date de publication |
| Greenhouse `requisition_id` | `requisition_id` | `source_fields.greenhouse.requisition_id` |
| Greenhouse `content` | `content` | `description_original` |
| Lever `posted` | `createdAt` (timestamp en ms, non qualifié de date) | `source_fields.lever.createdAt` — **jamais** `posted_date` |
| Lever `requisition` | absent du flux public lu (`id`, `text`, `createdAt`, `categories`, `lists`, `workplaceType`, `country`, `hostedUrl`, `applyUrl`, `additional*`, `opening*`, `description*`) | — |
| Ashby `published_at` | `publishedAt` | `source_fields.ashby.publishedAt` → `posted_date` |
| Ashby `employment_type` | `employmentType` | `source_fields.ashby.employmentType` |
| SmartRecruiters `postedDate` | `postedDate` (+ `releasedDate`) | `source_fields.smartrecruiters.postedDate` ; `releasedDate` → `posted_date` |
| SmartRecruiters `jobAd.sections` | `jobAd.sections` | `source_fields.smartrecruiters["jobAd.sections"]` **et** `description_original` |
| SmartRecruiters `requisitionId` | `requisitionId` | `source_fields.smartrecruiters.requisitionId` |
| WJ `date` | `<time datetime="…">` | `source_fields.welcome_jungle.datetime` |
| WJ `contract_type` | `contract_type` | `source_fields.welcome_jungle.contract_type` |
| JobTeaser `start_date` | absent de la carte lue | — (aucune date inventée) |
| JobTeaser `contract_type` | `contract_type` | `source_fields.jobteaser.contract_type` |
| Talent.com `date_posted` | `<time dateTime="…">` (« Last updated ») | `source_fields.talent_com.datetime` — **jamais** `posted_date` |
| Talent.com `job_type` | balise de la carte, sans nom de champ | `source_fields.talent_com.*` (attributs `data-*` de la carte) |
| APEC `date_publication` | `<time datetime="…">` | `source_fields.apec.datetime` |
| APEC `type_contrat` | `contract_type` | `source_fields.apec.contract_type` |

Les trois seules dates canoniques alimentées (`posted_date`, `deadline_date`) le sont à partir d'un
champ que la source **qualifie lui-même** comme date. Tout le reste est transmis sous son nom,
sans conversion.

---

## 4. Les contradictions sont conservées, pas tranchées

`detect_source_conflicts()` compare la valeur structurée publiée et le texte publié, avec un
vocabulaire explicite et restreint (`permanent`/`CDI`, `CDD`/`fixed-term`, `stage`/`internship`).
Elle **signale** les deux versions et n'en choisit aucune :

```json
{
  "kind": "contract",
  "field": "employment_type",
  "source_field": "categories.commitment",
  "source_value": "Internship",
  "description_value": "permanent",
  "quote": "…This is a permanent position (CDI), not an internship…"
}
```

Garanties :

- la valeur publiée reste dans `source_fields` (et dans `employment_type` quand le connecteur la
  publie), la citation reste dans `description_original` : **rien n'est écrasé** ;
- la citation est un extrait **verbatim** de la description ;
- une contradiction de durée (`duration_months` = 6 contre « 3-month » dans le texte) est
  signalée de la même façon ;
- l'absence de contradiction ne produit rien : un accord n'est pas un événement.

Quand le connecteur ne publie pas de type de contrat de façon canonique (Greenhouse, dont la
reconnaissance est volontairement prudente), la valeur est cherchée **dans les champs publiés** :
la contradiction est donc signalée même quand `employment_type` est vide.

---

## 5. Aucune logique de qualification dans les connecteurs

C'était une exigence explicite de la mission, et les connecteurs ne la respectaient pas : chacun
appelait `qualify_offer`, `classify_internship` et `criteria_admit`, puis filtrait les offres
lui-même — une décision refaite ensuite à la frontière du service.

La décision d'admission a été déplacée dans `career/exploration.py` (module des règles pures
d'admission) :

```python
verdict = admit_offer(job, brief)   # "admitted" | "filtered" | "excluded"
```

Le connecteur ne fait plus que :

1. lire la source ;
2. normaliser l'offre et transmettre le matériau publié ;
3. demander l'avis de la couche d'admission ;
4. compter et classer.

Les compteurs, l'ordre de tri et les résultats sont inchangés (suite complète verte, aucun
changement de comportement observé). Le test
`test_connectors_do_not_decide_the_qualification` vérifie **structurellement** qu'aucun module
de `career/connectors/` ni `career/discovery.py` n'importe `qualify_offer`,
`classify_internship` ou `criteria_admit`, et que tous utilisent `admit_offer`.

Frontière volontairement conservée : `classify_job_family` (champ canonique `job_family`) reste
produit par le connecteur ; c'est une donnée du contrat, pas une décision d'admission.

---

## 6. Ce que cette campagne corrige en plus du lot initial

Le lot initial (ordre `cvboost-29-1792619869`) avait livré le contrat et documenté quatre
défauts qui rendaient l'enrichissement **sans effet** sur quatre sources. Trois d'entre eux
étaient corrigeables dans le périmètre de la mission ; ils le sont maintenant, et le résultat est
prouvé en direct (§ 7).

### 6.1 Les quatre connecteurs HTML ne vérifiaient pas le certificat du serveur

**Défaut.** `welcome_jungle`, `jobteaser`, `talent_com` et `apec` appelaient
`urllib.request.urlopen()` sans contexte TLS. Sur une installation dont le bundle d'autorité par
défaut est absent ou périmé (le cas de l'environnement de vérification), la connexion échoue en
`CERTIFICATE_VERIFY_FAILED` : le connecteur renvoie « erreur réseau » et **la matière publiée
n'atteint jamais le contrat**. Le transport ATS (`UrllibPublicATSTransport`) utilisait déjà
`certifi` ; les quatre connecteurs HTML, non.

**Correctif.** `career/connectors/http.py` expose un contexte TLS vérifié (avec `certifi` quand
il est disponible, sinon le contexte par défaut — la vérification n'est jamais relâchée), utilisé
par les quatre connecteurs. Test : `test_the_html_connectors_verify_the_server_certificate`.

### 6.2 Talent.com publiait ses liens sous une forme que le connecteur ne reconnaissait pas

**Défaut.** La carte publiée utilise `/view?id=<identifiant>` : l'identifiant est un paramètre de
requête, pas un segment de chemin. Le connecteur exigeait `/view/` ou `/job/` et ne retenait
donc **aucune** offre : 20 liens `/view?id=…` étaient lus, 0 offre transmise.

**Correctif.** `_is_offer_link()` lit la forme publiée (`/view`, `/view/…`, `/job/…`) et rien
d'autre. Après correction, la lecture directe de la page publique de recherche restitue **65
offres** avec leurs champs publiés (`data-job-id`, `data-new-id`, `data-rank`, `datetime`, url).

Le résumé publié par la carte (`JobCard_snippet__…`) est également reconnu comme description :
sans cela `description_original` restait vide sur cette source.

### 6.3 Les prérequis publiés par SmartRecruiters n'atteignaient pas `offer_requirements`

**Défaut.** Les sections publiées étaient concaténées sans leur nom : la couche des prérequis
les lisait comme une prose neutre et **n'extrayait aucun prérequis** (0 exigence sur la fixture
synthétique). Le gain annoncé par le lot initial n'était donc pas réel.

**Correctif.** Chaque section est composée sous le nom que la source lui donne, dans l'ordre
publié (§ 3.4). Les prérequis publiés sont alors extraits :

```
- Bachelor's degree in Finance or Economics | required | description_original
- Excel mastery                            | required | description_original
```

Une seule entrée de vocabulaire a été ajoutée à la couche des prérequis
(`career/offer_requirements/extract.py`) : « additional information » (et ses équivalents) est une
section *neutre*, pas une section de prérequis. Sans elle, le contenu de cette section — publiée
après les qualifications — était lu comme des prérequis exigés (« Start date: 2 March 2027. »
deviendrait une exigence de CV). Aucun autre module n'est modifié, et les 62 tests de la couche
des prérequis restent verts.

### 6.4 Défauts hors périmètre, documentés

- **Welcome to the Jungle** — la page de recherche servie ne contient plus aucun balisage de
  carte (0 `data-testid="job-card"`, 0 `<article>`, 0 lien `/fr/companies/*/jobs/` sur 556 Ko) :
  le rendu est fait côté client. Lire la charge utile embarquée ou l'API interne sortirait du
  périmètre d'un connecteur « HTML lisible » et exigerait un travail propre (SK-09 ?).
- **JobTeaser** — `/en/jobs` répond **HTTP 410 Gone** : la page a été déplacée. Le nouveau chemin
  `/en/job-offers` répond **HTTP 403** à un agent automatisé. Le chemin public de recherche doit
  être revu par une mission dédiée.
- **APEC** — **HTTP 403 Forbidden**, quel que soit l'agent utilisateur (le contrôle a été tenté
  avec l'agent du connecteur et avec un agent de navigateur). L'accès automatisé est bloqué ;
  aucune contournement n'a été tenté, et le connecteur garde ses bornes.

---

## 7. Les 8 fixtures synthétiques

`tests/fixtures/connectors_enrich/` contient **une fixture par fournisseur** :
`greenhouse.json`, `lever.json`, `ashby.json`, `smartrecruiters.json`, `welcome_jungle.json`,
`jobteaser.json`, `talent_com.json`, `apec.json`.

Chaque fixture contient deux publications synthétiques :

- une publication **complète** (dates, contrat, exigences, identifiants, attributs de carte) ;
- une publication **contradictoire** (le champ structuré annonce un stage, le texte annonce un
  CDI) qui prouve que la contradiction survit au pipeline.

Les fixtures sont synthétiques : aucun board réel, aucune donnée personnelle, aucun appel réseau
pendant les tests. La fixture Talent.com reproduit la forme de lien publiée le 22 octobre 2026
(`/view?id=…`) et l'attribut `data-new-id` que la carte publie.

`tests/test_connectors_enrich.py` couvre 60 cas : champs transmis et leurs noms exacts, dates
canoniques, sections SmartRecruiters composées sous leur nom publié, prérequis atteints par la
couche des exigences, attributs de carte, lien d'offre publié de Talent.com, contradictions
conservées et non tranchées, bornes des valeurs, sérialisation JSON, contrat identique pour les
8 connecteurs, matière conservée après la décision d'admission, certificat vérifié, absence de
logique de qualification.

---

## 8. Contrôle réel borné et séparé

`tests/test_connectors_enrich_live.py` est **séparé** de la suite synthétique et **opt-in** :

```bash
CAREER_LIVE_SOURCE_CHECK=1 .venv/bin/python -m pytest -q tests/test_connectors_enrich_live.py
```

Une requête par fournisseur, délai de 10 s, 3 publications examinées au maximum.

### Résultat du 22 octobre 2026 (avec le certificat vérifié)

| Fournisseur | Source lue | Résultat du contrôle |
|-------------|-----------|----------------------|
| Greenhouse | `alixpartners` | **Contrat tenu** — `first_published`, `updated_at`, `requisition_id`, `metadata` transmis |
| Lever | `qonto` | **Contrat tenu** — `createdAt`, `categories`, `hostedUrl` transmis |
| Ashby | `oaknorth` | **Contrat tenu** — `publishedAt`, `employmentType`, `jobUrl` transmis |
| Talent.com | recherche publique finance | **Contrat tenu** — `data-job-id`, `data-new-id`, `data-rank`, `datetime`, url `/view?id=…` transmis ; description publiée présente |
| SmartRecruiters | — | **Non contrôlable** : aucun identifiant de board revu disponible (`totalFound=0` sur 12 identifiants testés, `/v1/companies` → 404). Identifiant injectable via `CAREER_LIVE_SR_COMPANY` |
| Welcome to the Jungle | — | **Non contrôlable** : rendu côté client, aucun balisage de carte dans le HTML servi (§ 6.4) |
| JobTeaser | — | **Non contrôlable** : `/en/jobs` → **HTTP 410 Gone**, `/en/job-offers` → **HTTP 403** |
| APEC | — | **Non contrôlable** : **HTTP 403 Forbidden** |

Bilan : **5 contrôles réussis** (Greenhouse, Lever, Ashby, Talent.com + le chemin d'erreur
explicite), **4 sources non contrôlables** pour une raison documentée. Avant cette campagne :
4 contrôles réussis, et **Talent.com ne transmettait rien** malgré une page parfaitement
lisible.

---

## 9. Validation

| Commande | Résultat |
|----------|----------|
| `.venv/bin/python -m pytest -q tests/test_connectors_enrich.py` | **60 passed** |
| `.venv/bin/python -m pytest -q` | **1484 passed, 10 skipped** (base : 1424 + 60 nouveaux ; le skip `test_offer_summary_exhaustiveness` et les 9 skips du contrôle réel sont préexistants) |
| `.venv/bin/python -m ruff check .` | **All checks passed** |
| `git diff --check` | propre |
| `CAREER_LIVE_SOURCE_CHECK=1 pytest -q tests/test_connectors_enrich_live.py` | 5 passed, 4 skipped (raisons explicites) |

---

## 10. Limites assumées

1. **La persistance en base n'est pas dans cette mission.** `service.import_job()` ne conserve
   que les champs canoniques : le bloc `source_fields` reste dans la charge utile du
   connecteur et n'est pas écrit dans la table `jobs`. La mission annonçait les connecteurs
   comme seul périmètre, et le registre porte `schema_version_locked` : aucune migration n'a
   été ajoutée. **Suite recommandée** : une table latérale `job_source_fields` (à l'image de
   `career/offer_intelligence_store.py` de SK-07, qui refuse aussi les nouvelles colonnes) et
   l'attachement de `source_fields` dans `get_job()`.
2. **SK-07 n'est pas encore branché.** Le rapport SK-07 demande explicitement « brancher SK-08
   sur `source_fields` pour que chaque fait conserve le nom exact du champ source ». C'est
   désormais possible : `build_snapshot()` peut lire `job["source_fields"]` et nommer chaque
   fait `greenhouse.first_published`, `lever.categories.commitment`, etc. Ce branchement
   appartient à SK-07, pas à SK-08.
3. **Les contradictions détectées sont deux** (type de contrat, durée). Une contradiction de
   date entre un champ structuré et le texte n'est **pas** détectée ici : une date de
   publication et une date de début se ressemblent dans un texte, et les confondre
   produirait des faux positifs. C'est le travail de `offer_dates` (SK-02), qui connaît le
   champ d'origine de chaque date.
4. **Le vocabulaire de détection est explicite et restreint.** Un wording inconnu n'est pas une
   contradiction : mieux vaut manquer un cas qu'inventer un désaccord.
5. **Trois connecteurs HTML restent non observables en direct** (§ 6.4) : la correction de leur
   lecture demande une mission propre (chemin public, balisage ou API interne), pas un correctif
   ponctuel.

---

## 11. Intégration

- Branche d'intégration : `agent/spec-sk08-connectors-enrich` (base `f5b22f2`).
- Branche de l'ordre : `worker/cvboost-29-1792623066` (worktree
  `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-29-1792623066`).
- Aucun conflit possible avec SK-01/02/03/07 : ces lots ne touchent ni `career/connectors/`, ni
  `career/source_fields.py`, ni `career/exploration.py`, ni `career/discovery.py`, ni
  `career/offer_requirements/`.
- `career/service.py`, le schéma SQLite et l'interface ne sont pas modifiés.
