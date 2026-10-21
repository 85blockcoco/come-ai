# SPEC-SK-06 — Déduplication multi-sources avec conservation des preuves

**Branche** : `worker/cvboost-27-1792608124` (worktree dédié)
**Base** : `main` (`f5b22f2`)
**Date** : 2026-10-21
**Auteur** : Worker Mission CVBOOST-27
**Mission** : `messages/task.json` → `cvboost-27-1792608124`

---

## 1. Recherche préalable (exigée par la mission)

La mission demandait de **retrouver et comparer** les contributions existantes
avant d'écrire quoi que ce soit. Inventaire réalisé sur toutes les branches et
tous les worktrees du dépôt :

| Source | Emplacement | Volume | Verdict |
|--------|-------------|--------|---------|
| `origin/agent/cvboost-07-dedup` | `career/cv_quality/job_deduplication.py` + `tests/test_job_deduplication.py` | première implémentation (modèle de titre, clés de blocage, rapport d'audit) | **Conservée** (fusionnée dans le module final) |
| `origin/agent/spec-sk06-dedup` | `career/job_deduplication.py` (1 917 lignes) + `tests/test_job_deduplication.py` (627 lignes) + `tests/fixtures/job_deduplication/` (3 JSON) | implémentation consolidée complète | **Retenue** — c'est le meilleur lot |
| WIP non versionné (racine du dépôt principal) | `career/job_deduplication.py` (33 Ko, non suivi) | version partielle, sans modèle de provenance ni de conflits | **Abandonnée** — strictement inférieure au lot consolidé |
| `origin/worker/cvboost-27-1792606659` | même contenu que `agent/spec-sk06-dedup` | mission précédente, non relue | **Reprise** via `agent/spec-sk06-dedup` |

**Décision** : le module de `agent/spec-sk06-dedup` est repris tel quel, et non
réécrit. La seule adaptation a été le **re-portage sur `main` courant** : la
branche d'origine partait d'une base plus ancienne et supprimait 3 342 lignes
de tests de `main` — elle n'était donc pas fusionnable telle quelle. Seuls les
fichiers métier (module, tests, fixtures, point d'intégration) ont été repris.

---

## 2. Ce qui a été livré

```
A career/job_deduplication.py                          # module consolidé (1 917 lignes)
A tests/test_job_deduplication.py                      # 172 tests
A tests/fixtures/job_deduplication/README.md           # documentation du corpus
A tests/fixtures/job_deduplication/pairs.json          # 121 paires étiquetées
A tests/fixtures/job_deduplication/groups.json         # 14 cas de groupe
A tests/fixtures/job_deduplication/truth_corpus.json   # 59 enregistrements / 36 groupes
A scripts/verify_sk06_guards.py                        # preuve exécutable des 9 critères + 7 garde-fous
M career/discovery.py                                  # point d'intégration (28 lignes)
A docs/agent-reports/SPEC-SK06-DEDUP.md                # ce rapport
```

### 2.1 Point d'intégration

`career/discovery.py` expose désormais :

```python
def discover_stage_offers(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], "DedupReport"]:
```

C'est l'étape de fusion déterministe et locale qui s'exécute juste après la
collecte multi-sources. L'import de `job_deduplication` est **paresseux** :
il ne ralentit pas le chargement de `career.discovery` et n'estutile que
lorsque plusieurs sources sont fusionnées. La fonction n'existait pas sur le
`main` courant : c'est le seul code non repris tel quel, réécrit à l'identique
de la version de référence.

---

## 3. Les 9 critères de rapprochement

| # | Critère | Implémentation | Preuve |
|---|---------|----------------|--------|
| 1 | Identifiant externe | `_external_identity()` → clé `ext:<id>` (global) ou `src:<source>:<id>` (namespacé ATS) | `same_external_id` |
| 2 | URL canonique | `canonicalize_url()` : suppression `utm_*`, `gclid`, `fbclid`, `msclkid`, `ref`, `source`, `trackingid`, `www.`, port 443, slash final, fragment, `http`→`https` | `canonical_url_match`, `apply_url_match` |
| 3 | Entreprise canonique | `company_canonical()` : suffixes juridiques (`sa`, `sas`, `ltd`, `inc`, `gmbh`…) et bruit (`group`, `holding`, `international`) | `company_canonical()` |
| 4 | Titre canonique | `title_canonical()` : minuscules, accents, ponctuation, synonymes (`stage`/`intern`→`internship`, `CDI`→`permanent`, `alternance`→`apprenticeship`), marqueurs `H/F` | `title_canonical()` |
| 5 | Lieu | `location_canonical()` : alias de villes, pays normalisés, marqueurs remote | `city_conflict` |
| 6 | Dates | `_freshness()`, `_start_month()`, `_digit_signature()` (cohortes, éditions) | `start_date_conflict`, `cohort_conflict` |
| 7 | Similarité de texte | `jaro_winkler()` + `title_similarity()`, seuil `TITLE_SIMILARITY_THRESHOLD = 0.92`, hook embeddings optionnel | `title_similarity_match` |
| 8 | Traductions | `title_concept()` : concept métier commun FR/EN (`Software Engineer` ≡ `Ingénieur logiciel`) | `same_role_concept` |
| 9 | Alias d'entreprise | `COMPANY_ALIASES` (`Acme Corp` = `Acme Inc.`, `J.P. Morgan`, `Point72`, `Evercore ISI`…) | `company_alias` |

Preuve exécutable : `scripts/verify_sk06_guards.py` rejoue les 9 critères un par
un → **9/9 OK**.

---

## 4. Les 7 garde-fous non négociables

| Garde-fou | Implémentation | Vérification |
|-----------|----------------|--------------|
| Le score de pertinence utilisateur **ne décide jamais** | `USER_SCORE_FIELDS` (`user_score`, `relevance`, `match_score`…) n'est lu par aucun chemin de décision ; `_record_weight()` ne le contient pas | `G1` + `G1b` du script de vérification ; `guard_user_score_never_decides` |
| Toutes les provenances sont conservées | `_provenance()` : chaque source garde son `official_url`, `apply_url`, `trust` et son `record` complet ; `merged_from` liste les sources absorbées | `G2` + `G2b` ; `group_three_sources_one_offer` |
| Les contradictions restent visibles | `_detect_conflicts()` sur `posted_date`, `city`, `country`, `title`, `role_level`, `employment_type`, `duration_months`, `start_date`, `end_date` — une contradiction **ne bloque jamais** une fusion | `G3` ; `group_divergent_dates_stay_visible`, `group_city_contradiction_stays_visible` |
| La source officielle (SK-01 `verified`) reste principale | `_record_weight()` : trust (3) > tier source (page employeur > board) > fraîcheur > priorité source > vérification connecteur > complétude | `G4` ; `group_official_verified_source_stays_primary` |
| Les sources secondaires restent consultables | `provenances` + `sources` + `member_ids` sur chaque cluster ; les sources annexes ne sont jamais écrasées | `G5` ; `group_unknown_feed_is_ranked_between_boards_and_manual` |
| La traduction ne fusionne pas sur quelques mots communs | `_shared_specific_token()` : un mot générique (`data`, `intern`) ne suffit pas | `G6` ; `translated_generic_words_only_refused` |
| Les rôles différents ne sont jamais fusionnés | `_title_decision()` : concept métier + niveau + longueur ; `role_level_conflict` si les niveaux diffèrent | `G7` + `G7b` ; `different_role_*`, `level_junior_vs_senior` |

> Note : le module **lit** le statut de confiance publié par SPEC-SK-01
> (`source_trust`, `trust_status`, `source_trust_status`) et **ne le re-décide
> jamais** : un statut inconnu vaut `missing`. Le contrat de confiance reste la
> propriété de SK-01, la déduplication n'en est qu'un consommateur.

---

## 5. Corpus synthétique

| Fichier | Contenu | Avant | Après |
|---------|---------|-------|-------|
| `pairs.json` | paires étiquetées à la main | 112 (71 fusions / 41 refus) | **121 (78 fusions / 43 refus)** |
| `groups.json` | cas de groupe (provenance, conflits, élection, collision) | 14 | 14 |
| `truth_corpus.json` | enregistrements étiquetés pour précision / rappel | 59 | 59 |

**Total : 194 cas étiquetés** (121 paires + 14 groupes + 59 enregistrements),
au-delà des 100 exigés par la mission.

### 5.1 Catégories couvertes

| Catégorie | Cas |
|-----------|-----|
| `exact_duplicate` | 8 |
| `url_tracking` | 16 |
| `employer_page` | 6 |
| `translation` | 12 |
| `different_role` | 13 |
| `city_conflict` | 12 |
| `company_alias` | 8 |
| `reopening` | 6 |
| `incompatible_dates` | 6 |
| `recycled_identifier` | 6 |
| `role_level` | 8 |
| `title_qualifier` | **9 (ajout)** |
| `guard` | 11 |

### 5.2 Ajout de cette mission : catégorie `title_qualifier`

Le corpus d'origine ne contenait **aucun titre entre parenthèses**, alors que
c'est une forme extremely courante sur les boards (« M&A Intern (Paris) »,
« Ingénieur logiciel (CDI) », « Data Analyst (H/F) »). 9 cas ont été ajoutés
pour verrouiller le comportement réel :

| Cas | Attendu |
|-----|---------|
| `title_qualifier_city_suffix_matches_plain_title` | fusion |
| `title_qualifier_same_business_concept_matches` | fusion |
| `title_qualifier_different_business_concept_refused` | **refus** (`Consultant (M&A)` ≠ `Consultant (Finance)`) |
| `title_qualifier_contract_is_not_a_role_level_duplicate` | **refus** (`(CDI)` ≠ `(Stage)`) |
| `title_qualifier_gender_markers_are_noise` | fusion (`H/F` ≡ `F/H`) |
| `title_qualifier_city_suffix_only_matches` | fusion |
| `title_qualifier_dash_city_suffix_matches` | fusion |
| `title_qualifier_bracket_city_suffix_matches` | fusion |
| `title_qualifier_city_and_gender_suffix_matches` | fusion |

Ces cas **n'ont demandé aucune modification du module** : le comportement était
déjà correct. Le corpus le fige désormais.

### 5.3 Précision / rappel

Sur le corpus de vérité (59 enregistrements, 36 groupes, 24 paires réelles) :

| Indicateur | Valeur |
|------------|--------|
| Précision | **1.0000** |
| Rappel | **1.0000** |
| F1 | **1.0000** |
| Paires d'erreur | **0** |

---

## 6. Preuves exécutables

### 6.1 Tests ciblés

```bash
$ .venv/bin/python -m pytest -q tests/test_job_deduplication.py
172 passed in 1.52s
```

### 6.2 Suite complète

```bash
$ .venv/bin/python -m pytest -q
1596 passed, 1 skipped in 104.41s
```

Le `skip` est pré-existant (`tests/test_offer_summary_exhaustiveness.py` :
script ou base absents). Aucune régression : la base `main` comptait 1 425
tests collectés, la mission en ajoute 172.

### 6.3 Vérification des 9 critères et des 7 garde-fous

```bash
$ .venv/bin/python scripts/verify_sk06_guards.py
[OK  ] 1. identifiant externe            [OK  ] G1. le score utilisateur ne décide jamais
[OK  ] 2. URL canonique                  [OK  ] G1b. le score ne choisit pas le représentant
[OK  ] 2b. fusion par URL canonique      [OK  ] G2. provenances conservées
[OK  ] 3. entreprise canonique           [OK  ] G2b. merged_from trace les sources
[OK  ] 4. titre canonique                [OK  ] G3. contradictions visibles
[OK  ] 5. lieu (Paris != Lyon)           [OK  ] G4. source verified reste principale
[OK  ] 6. dates incompatibles            [OK  ] G5. sources secondaires consultables
[OK  ] 7. similarité Jaro-Winkler ≥0.92  [OK  ] G6. mots communs ne suffisent pas
[OK  ] 8. traduction (concept de rôle)   [OK  ] G7. rôles différents jamais fusionnés
[OK  ] 9. alias d'entreprise              [OK  ] G7b. niveaux différents jamais fusionnés
→ Toutes les vérifications SPEC-SK-06 sont passées.
```

### 6.4 Lint et checklist

```bash
$ .venv/bin/python -m ruff check .
All checks passed!

$ VENV_PY=.../.venv/bin/python ./checklist_codex.sh
✓ main tests passés      ✓ aucun secret tracké     ✓ DevKit vert
✓ lint (ruff)            ✓ rappel affiché
→ TOUT VERT
```

```bash
$ git diff --check
# aucune erreur de whitespace
```

---

## 7. Propriétés du module

| Propriété | État |
|-----------|------|
| Hors ligne | ✅ aucun `urllib`, `socket`, `requests`, `http.client` (test dédié `test_the_module_stays_offline`) |
| Aucun appel modèle | ✅ Python pur, aucun appel réseau |
| Déterministe | ✅ même entrée → même sortie, indépendant de l'ordre des enregistrements (test dédié) |
| Pas d'horloge | ✅ les dates sont lues dans les enregistrements, jamais `now()` |
| Pure | ✅ les dictionnaires reçus ne sont jamais modifiés |
| Borné | ✅ 500 offres dédupliquées en < 200 ms (test de performance) |
| Aucun secret / aucune donnée réelle | ✅ corpus 100 % synthétique |

---

## 8. Limites connues et arbitrages documentés

### 8.1 Réouverture vs. deux offres distinctes

La règle « même entreprise + même rôle + même ville » est considérée comme une
**réouverture** (une offre republiée) et fusionnée, même si les deux
enregistrements portent des URLs et des identifiants différents. C'est le
comportement **exigé** par la mission (« Réouverture ancienne annonce : même
rôle, date de publication différente → fusion »).

Conséquence : deux offres réellement distinctes de la même entreprise, même
rôle, même ville (deux équipes différentes) seraient fusionnées. Le module ne
peut pas distinguer « republié » de « distinct » sans identifiant externe ni
lien commun, et les champs structurés sont alors identiques.

**Mitigation retenue** : le groupe conserve `conflicts` (dates de publication
divergentes) et toutes les `provenances` : l'information n'est pas perdue, elle
est visible. SK-07 (Offer Intelligence Bridge) pourra la transformer en
« à vérifier » plutôt qu'en certitude.

### 8.2 Localité portée par le titre vs. champ structuré

Si deux enregistrements déclarent la **même ville** dans le champ `city` mais
que leur titre porte une ville différente (« Data Analyst (Paris) » vs
« Data Analyst (Lyon) »), la fusion a lieu : le module fait autorité du champ
structuré et ne ré-analyse pas le texte libre du titre. Comportement conservé
tel quel (le lieu du titre n'est pas une source fiable) ; à traiter comme une
« divergence de fait » dans SK-07 si le cas se présente en production.

### 8.3 Pas de colonnes ajoutées

Conformément à la mission, aucune colonne n'a été ajoutée aux offres : la
déduplication enrichit l'enregistrement retourné avec `merged_from`,
`merge_count`, `dedup_id` et `merge_reasons`, et n'écrit rien en base.

---

## 9. Pour la relecture / l'intégration

- **Branche** : `worker/cvboost-27-1792608124` (poussée sur `origin`).
- **Point d'entrée à raccorder** : `career.discovery.discover_stage_offers(jobs)`
  est prête à être appelée par le flux multi-sources de l'Explorer. Elle n'est
  **pas** encore appelée par `career/service.py` : le raccordement au flux
  réel relève de l'intégration (hors périmètre de cette mission, qui porte sur
  le module de déduplication).
- **Dépendance SK-07** : les identifiants de groupe (`dedup_id`) et les
  `provenances` sont déjà stables et déterministes, donc directement
  exploitables comme identifiants d'exigence dans le snapshot SK-07.
- **Aucun appel modèle, aucun réseau, 0 migration, 0 dépendance ajoutée.**

---

## 10. Conclusion

✅ Implémentation consolidée depuis `agent/spec-sk06-dedup` (recherche préalable faite et documentée)
✅ 9 critères de rapprochement implémentés et prouvés
✅ 7 garde-fous respectés et prouvés
✅ 194 cas synthétiques étiquetés (121 paires + 14 groupes + 59 enregistrements), 172 tests
✅ `merged_from` trace toutes les provenances
✅ Contradictions visibles dans le résultat
✅ La source officielle (SK-01 `verified`) reste principale
✅ Corpus enrichi de 9 cas `title_qualifier` (scénario réel non couvert)
✅ Ruff clean, suite complète verte (1 596 tests), `git diff --check` propre
✅ Rapport : `docs/agent-reports/SPEC-SK06-DEDUP.md`

**Prêt pour relecture et intégration.**
