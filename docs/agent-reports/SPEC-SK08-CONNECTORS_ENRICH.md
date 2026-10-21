# SPEC-SK08 — Enrichissement des connecteurs existants

Date : 22 octobre 2026
Mission : **CVBOOST-29** — ordre `cvboost-29-1792619869`
Branche de travail : `worker/cvboost-29-1792619869`
Base : `f5b22f2` (*merge(career): ATS diagnostics and targeted CV variants pipeline*)
Statut : **TERMINÉE — contrat commun livré pour les 8 connecteurs**

---

## 1. Ce qui a été livré

| Fichier | Nature | Rôle |
|---------|--------|------|
| `career/source_fields.py` | **nouveau** | Contrat commun du matériau transmis : collecte bornée des champs publiés, détection des contradictions conservées |
| `career/connectors/cards.py` | **nouveau** | Lecture des attributs publiés par une carte d'offre (`data-*`, `<time datetime>`) |
| `career/exploration.py` | modifié | Nouvelle fonction pure `admit_offer()` : la décision d'admission sort des connecteurs |
| `career/connectors/public_ats.py` | modifié | Lever, Ashby, SmartRecruiters : champs publiés transmis + admission déplacée |
| `career/discovery.py` | modifié | Greenhouse : champs publiés transmis, dates structurées reprises, admission déplacée |
| `career/connectors/welcome_jungle.py` | modifié | Carte Welcome to the Jungle : champs publiés transmis + admission déplacée |
| `career/connectors/jobteaser.py` | modifié | Carte JobTeaser : idem |
| `career/connectors/talent_com.py` | modifié | Carte Talent.com : idem |
| `career/connectors/apec.py` | modifié | Carte APEC : idem |
| `tests/test_connectors_enrich.py` | **nouveau** | 54 tests de contrat, 1 fixture synthétique par fournisseur |
| `tests/fixtures/connectors_enrich/*.json` | **nouveau** | 8 fixtures (une par fournisseur) |
| `tests/test_connectors_enrich_live.py` | **nouveau** | Contrôle réel borné, séparé, opt-in |

**Aucun fichier existant hors périmètre n'a été modifié.** Ni `career/service.py`, ni le schéma de
la base, ni l'interface. La branche est donc fusionnable dans `main` sans conflit possible avec
SK-01, SK-02, SK-03 ou SK-07 (aucun de ces lots ne touche `career/connectors/` ni
`career/source_fields.py`).

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

**Gains réels :** les sections publiées (`companyDescription`, `jobDescription`,
`qualifications`, `additionalInformation`) sont composées dans `description_original`. Les
**prérequis** publiés par la source parviennent enfin au extracteur
`offer_requirements`, qui les traitait auparavant sur une description vide.

### 3.5 Welcome to the Jungle, JobTeaser, Talent.com, APEC (cartes HTML)

Chaque carte publie : `title`, `company`, `location`, `contract_type`, `url` → `source_fields.*`.
Les attributs de la carte sont transmis **sous leur nom d'attribut** : `data-posted-at`,
`data-job-id`, `data-rank`, `data-offer-id`, et `datetime` pour un élément `<time datetime="…">`.

Aucune date n'est déduite : le `<time>` de Talent.com est un « last updated », pas une date de
publication ; il est transmis tel quel et `posted_date` reste vide.

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

## 6. Les 8 fixtures synthétiques

`tests/fixtures/connectors_enrich/` contient **une fixture par fournisseur** :
`greenhouse.json`, `lever.json`, `ashby.json`, `smartrecruiters.json`, `welcome_jungle.json`,
`jobteaser.json`, `talent_com.json`, `apec.json`.

Chaque fixture contient deux publications synthétiques :

- une publication **complète** (dates, contrat, exigences, identifiants, attributs de carte) ;
- une publication **contradictoire** (le champ structuré annonce un stage, le texte annonce un
  CDI) qui prouve que la contradiction survit au pipeline.

Les fixtures sont synthétiques : aucun board réel, aucune donnée personnelle, aucun appel réseau
pendant les tests.

`tests/test_connectors_enrich.py` couvre 54 cas : champs transmis et leurs noms exacts, dates
canoniques, sections SmartRecruiters, attributs de carte, contradictions conservées et non
tranchées, bornes des valeurs, sérialisation JSON, contrat identique pour les 8 connecteurs,
absence de logique de qualification.

---

## 7. Contrôle réel borné et séparé

`tests/test_connectors_enrich_live.py` est **séparé** de la suite synthétique et **opt-in** :

```bash
CAREER_LIVE_SOURCE_CHECK=1 .venv/bin/python -m pytest -q tests/test_connectors_enrich_live.py
```

Une requête par fournisseur, délai de 10 s, 3 publications examinées au maximum.

### Résultat du 22 octobre 2026

| Fournisseur | Source lue | Résultat du contrôle |
|-------------|-----------|----------------------|
| Greenhouse | `alixpartners` | **Contrat tenu** — `first_published`, `updated_at`, `requisition_id`, `metadata` transmis |
| Lever | `qonto` | **Contrat tenu** — `createdAt`, `categories`, `hostedUrl` transmis |
| Ashby | `oaknorth` | **Contrat tenu** — `publishedAt`, `employmentType`, `jobUrl` transmis |
| SmartRecruiters | — | **Non contrôlable** : aucun identifiant de board revu disponible (`totalFound=0` sur 12 identifiants testés, `/v1/companies` → 404). Identifiant injectable via `CAREER_LIVE_SR_COMPANY` |
| Welcome to the Jungle | — | **Non contrôlable** : la page de recherche servie ne contient plus de balisage exploitable (0 `data-testid="job-card"`, 0 `<article>`, 0 lien `/fr/companies/*/jobs/` sur 556 Ko) — rendu côté client |
| JobTeaser | — | **Non contrôlable** : l'endpoint répond **HTTP 410 Gone** |
| Talent.com | — | **Non contrôlable** : 40 cartes `data-job-id` et 20 liens `href="/view?id=…"` mais **0** `href="/view/"` — le connecteur exige `/view/` et ne retient donc aucun lien |
| APEC | — | **Non contrôlable** : l'endpoint répond **HTTP 403 Forbidden** |

Bilan : **4 contrôles réussis** (Greenhouse, Lever, Ashby + le chemin d'erreur explicite),
**4 sources non contrôlables** pour une raison documentée.

### Deux défauts préexistants à traiter (hors périmètre SK-08)

Ces défauts existaient avant la mission et ne sont pas causés par l'enrichissement ; ils sont
signalés parce qu'ils rendent l'enrichissement sans effet pour ces quatre sources :

1. **Talent.com** — le test de lien (`"/job/" in href or "/view/" in href`) ne correspond plus au
   format publié (`/view?id=…`). Correctif ponctuel : accepter `/view?id=`.
2. **Welcome to the Jungle** — le balisage des cartes n'est plus dans le HTML servi ; le
   connecteur ne peut rien lire. Il faut lire la charge utile embarquée ou l'API interne.
3. **JobTeaser** — endpoint 410 : l'URL de recherche doit être revue.
4. **APEC** — 403 pour cet agent utilisateur : l'accès réel demande un autre mode d'accès.

---

## 8. Validation

| Commande | Résultat |
|----------|----------|
| `.venv/bin/python -m pytest -q tests/test_connectors_enrich.py` | **54 passed** |
| `.venv/bin/python -m pytest -q` | **1478 passed, 1 skipped** (base : 1424 passed + 54 nouveaux ; le skip `test_offer_summary_exhaustiveness` est préexistant) |
| `.venv/bin/python -m ruff check .` | **All checks passed** |
| `git diff --check` | propre |
| `CAREER_LIVE_SOURCE_CHECK=1 pytest -q tests/test_connectors_enrich_live.py` | 4 passed, 5 skipped (raisons explicites) |

---

## 9. Limites assumées

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
5. **Les quatre connecteurs HTML restent non observables en direct** (§ 7).

---

## 10. Intégration

- Branche : `worker/cvboost-29-1792619869` (worktree `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-29-1792619869`).
- Base : `f5b22f2` — aucun conflit possible avec SK-01/02/03/07 (`career/connectors/` et
  `career/source_fields.py` ne sont touchés par aucun de ces lots ; `career/exploration.py`
  n'y reçoit qu'une fonction ajoutée).
- `career/service.py`, le schéma SQLite et l'interface ne sont pas modifiés.
