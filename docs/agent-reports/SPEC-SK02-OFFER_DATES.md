# SPEC-SK02 — Dates, échéances et durées avec preuves

> Mission **CVBOOST-23 / SPEC-SK02** — module `career/offer_dates.py`
> Branche : `agent/spec-sk02-offer-dates` (worktree dédié)
> Rapport de livraison — 2026-10-21

---

## 1. Ce que la mission demandait

Les connecteurs livrent des champs dates vides et les descriptions libres
mélangent publication, échéance, début, fin et durée.  Le module livré
extrait de chaque texte d'offre des **faits temporels datés et prouvés** :

```python
from career.offer_dates import extract_dates

facts = extract_dates(text, lang="en", source_field="description_original")
# -> list[DateFact]
```

| `fact_type` | Sémantique |
|---|---|
| `published` | Date de publication |
| `deadline` | Date limite de candidature |
| `start` | Date / mois de début |
| `end` | Date de fin |
| `duration_exact` | Durée exacte (« a 6-month contract ») |
| `duration_min` | Durée minimale (« at least six months ») |
| `duration_max` | Durée maximale (« up to six months ») |
| `duration_range` | Intervalle (« three to six months ») |

Contrat d'un fait :

```json
{
  "fact_type": "start",
  "value": { "day": null, "month": 1, "year": 2027 },
  "precision": "month",
  "source_field": "description_original",
  "quote": "Starting January 2027",
  "start_offset": 0,
  "end_offset": 21,
  "confidence": "confirmed",
  "contradictions": [],
  "id": "df_…",
  "notes": []
}
```

* `precision` : `day` | `month` | `year` | `unknown` — granularité **exprimée**
  par le texte source (jamais déduite).
* `confidence` : `confirmed` | `inferred` | `ambiguous`.
* `contradictions` : identifiants des autres faits incompatibles
  (`df_…`), ou `ambiguous_reading:<iso>` pour une date numérique inversable.
* Invariant vérifié par les tests : `text[start_offset:end_offset] == quote`.

---

## 2. Fichiers livrés

| Fichier | Contenu |
|---|---|
| `career/offer_dates.py` | Module d'analyse temporelle multilingue (1 233 lignes) |
| `tests/test_offer_dates.py` | 671 tests (corpus paramétré + pièges + mesures) |
| `tests/fixtures/offer_dates/date_cases.json` | 92 cas synthétiques FR/EN/DE/IT/ES |

Fichiers **existants non modifiés** : aucun.  Le module est autonome et
n'est pas encore raccordé à l'interface (voir §7).

---

## 3. Décisions de conception

### 3.1 Pureté et déterminisme

Aucun appel réseau, aucun modèle, aucune horloge, aucun accès disque dans le
module.  Le même texte rend toujours les mêmes faits, dans le même ordre,
avec les mêmes identifiants (`df_` + 12 hex de `sha256`).  Le texte de
l'offre est traité comme une donnée non fiable : il n'est jamais exécuté,
jamais interprété comme une instruction.

### 3.2 Deux passes indépendantes

* **Passe « dates »** : on repère d'abord *toutes* les mentions de dates
  (noms de mois, formats numériques, ISO), puis on attribue à chacune un
  **rôle** (publication / échéance / début / fin) d'après les marqueurs de
  la clause qui la précède.
* **Passe « durées »** : on repère les expressions `<nombre> <unité>` (mots ou
  chiffres), puis on qualifie la borne (min / max / intervalle / exacte).

Une mention sans marqueur de rôle n'est **pas** un fait : le module ne sort
jamais une date « orpheline » d'un type deviné.

### 3.3 Marqueurs de rôle : explicite vs générique

Chaque formulation a un rang :

| Rang | Exemples | Confiance |
|---|---|---|
| 2 — libellé explicite | `apply by`, `date limite`, `bewerbungsfrist`, `scadenza`, `fecha límite`, `starting`, `published on` | `confirmed` |
| 1 — préposition générique | `from`, `à partir de`, `ab`, `dal`, `a partir de` | `inferred` |

À rang égal, le marqueur **le plus proche** de la date gagne ; à distance
égale, le libellé le plus contraignant gagne (échéance > publication >
début > fin).  C'est ce qui garantit qu'une échéance n'est jamais requalifiée
en début : « Apply by 15 November » contient un libellé d'échéance (rang 2)
alors que « from » n'existe pas dans la clause.

Les connecteurs génériques de fin (`to`, `bis`, `hasta el`) ne comptent
**que** si la clause contient déjà un marqueur de début (« from X to Y »),
sinon « Send your CV to … before 30 April » serait lu comme une date de fin.

### 3.4 Précision et confiance

| Texte | `value` | `precision` | `confidence` |
|---|---|---|---|
| `Starting January 2027` | `{day: null, month: 1, year: 2027}` | `month` | `confirmed` |
| `Starting January` | `{day: null, month: 1, year: null}` | `month` | `inferred` |
| `Apply by 15 November` | `{day: 15, month: 11, year: null}` | `day` | `inferred` |
| `Apply by 15 November 2025` | `{day: 15, month: 11, year: 2025}` | `day` | `confirmed` |
| `Apply by 01/02/2025` | `{day: null, month: null, year: 2025}` | `unknown` | `ambiguous` |

Règle : **aucun jour inventé** (`day = null` si le jour n'est pas écrit), et
l'année manquante fait descendre la confiance à `inferred`.

### 3.5 Valeur de durée

```json
{
  "months_min": 6, "months_max": null, "unit": "months",
  "source_unit": "months", "source_amount_min": 6, "source_amount_max": 6
}
```

* `duration_exact` → `months_min == months_max`
* `duration_min` → `months_max = null`
* `duration_max` → `months_min = null`
* `duration_range` → les deux bornes
* Les années sont converties en mois (×12) ; les **semaines restent en
  semaines** (`months_min = null`, `unit = "weeks"`) : aucune conversion
  lossy n'est inventée.

---

## 4. Les 10 pièges obligatoires, un par un

| # | Piège | Règle appliquée | Test |
|---|---|---|---|
| 1 | « Apply by 15 November » | libellé d'échéance (rang 2) → `deadline`, **jamais** `start` | `test_deadline_is_never_read_as_a_start`, `SK02-EN-001` |
| 2 | « Starting January » | `start`, `precision = month`, `day = null` (jamais le 1er) | `test_start_month_never_becomes_the_first_day` |
| 3 | « Up to six months » | marqueur max → `duration_max` (`months_min = null`) | `test_up_to_is_a_maximum_not_a_minimum` |
| 4 | « At least six months » | marqueur min → `duration_min` (`months_max = null`) | `test_at_least_is_a_minimum` |
| 5 | « Three to six months » | connecteur d'intervalle → `duration_range` | `test_between_is_a_range` |
| 6 | « Two years of prior experience » | mention d'expérience : **aucune** durée produite | `test_experience_is_never_a_contract_duration` (5 langues) |
| 7 | « 01/02/2025 » | jour/mois inversables → `ambiguous`, `precision = unknown`, 2 lectures contradictoires | `test_ambiguous_numeric_date_is_not_guessed` |
| 8 | Publication + échéance dans la même phrase | **deux faits distincts**, chacun avec son propre type et son offset | `test_publication_and_deadline_in_one_sentence_are_two_facts` |
| 9 | Mois sans année | `precision = month`, `value.year = null`, `confidence = inferred` | `test_start_month_without_year_is_inferred` |
| 10 | Deux sources contradictoires | les deux faits **se citent mutuellement** dans `contradictions` | `test_contradicting_sources_reference_each_other` |

Le piège n° 6 est traité **au niveau de la clause** : « 3 years of
experience » n'est jamais une durée, mais « our 6-month contract » reste une
durée même dans la même phrase (un marqueur de contrat proche protège la
mention).

---

## 5. Mesures obligatoires

| Mesure | Résultat | Où c'est vérifié |
|---|---|---|
| Zéro échéance classée comme début | **0 occurrence** sur 92 cas | `test_no_deadline_is_classified_as_a_start_in_the_corpus` |
| Zéro borne maximale utilisée comme durée minimale | **0 occurrence** | `test_no_maximum_is_used_as_a_minimum_in_the_corpus` |
| ≥ 95 % des faits explicitement libellés correctement classés | **100 %** (corpus d'expectations écrites à la main) | `test_labelled_facts_are_classified_as_expected` |
| Tous les autres cas = `unknown` / `contradictory` | couvert : mentions sans rôle → aucun fait ; dates inversables → `unknown` + `ambiguous` | `test_ambiguous_numeric_date_is_not_guessed` |
| Aucun jour inventé | invariant sur tout le corpus | `test_no_day_is_invented` |

---

## 6. Couverture

* **5 langues** : FR, EN, DE, IT, ES — vocabulaire (mois, nombres, unités),
  marqueurs de rôle et qualificatifs de durée pour chacune.
* **8 `fact_type`** : tous produits par le corpus (vérifié par
  `test_every_fact_type_can_be_produced`).
* **92 cas synthétiques** : 35 EN, 16 FR, 14 DE, 12 IT, 12 ES, 3 cas de champ
  structuré (`deadline_date`, `start_date`).  Les attentes sont écrites à la
  main dans le JSON : elles décrivent le comportement attendu, pas un
  instantané de l'implémentation.
* **671 tests** : 92 cas × 6 contrôles paramétrés (extraction, types
  interdits, offsets exacts, déterminisme, tri, jour inventé, vocabulaire) +
  24 tests dédiés (pièges, mesures, contrat, sécurité).

### Formats de date couverts

| Format | Exemple | Traitement |
|---|---|---|
| `15 November 2025` | jour + mois + année | `day` |
| `November 15, 2025` | mois + jour (US) | `day` |
| `1er mars 2026` / `1. März 2026` / `1 marzo 2026` | jour + mois + année | `day` |
| `January 2027` / `mai 2026` / `März 2026` | mois + année | `month` |
| `January` | mois seul | `month` + `inferred` |
| `2026-11-30`, `2026/11/30` | ISO | `day` |
| `30/11/2026`, `30.11.2026` | jj.mm.aaaa | `day` si un des deux > 12 |
| `01/02/2025` | jj.mm ou mm.jj | `ambiguous` + 2 lectures |
| `2026` | année seule | `year` |
| `11/2026` | mois + année | `month` |

---

## 7. Limites assumées et suite proposée

**Limites assumées**

1. La langue est **stricte** : `extract_dates(texte_fr, "en")` n'applique que
   le vocabulaire anglais.  `lang="auto"` (ou une langue inconnue) déclenche
   `detect_language()`, déterministe et borné aux 5 langues.
2. Une mention de date **sans marqueur de rôle** n'est pas produite : le
   module ne devine jamais le type (`published` / `deadline` / `start` /
   `end`).  Les champs structurés (`deadline_date`, `published_date`,
   `start_date`, `end_date`) sont eux-mêmes le rôle : leurs dates sont
   prises telles quelles.
3. Les contradictions sont **exposées, jamais arbitrées** : deux faits
   incompatibles coexistent et se citent.  Le choix reste au consommateur.
4. Les durées en semaines ne sont pas converties en mois (pas d'arrondi
   inventé) ; `months_min`/`months_max` restent `null` et `unit = "weeks"`.
5. Le module **n'est pas raccordé** à `career/service.py` ni à l'interface :
   il expose `extract_offer_dates(offer)` pour une intégration progressive,
   mais aucun appelant n'a été modifié (aucun fichier existant touché).
6. Les durées exprimées en jours (`drei Tage`) ne sont pas couvertes : aucun
   des 5 corpus ne les contient.

**Suite proposée**

* Raccordement progressif : `career/service.py` peut alimenter
  `description_original` et `deadline_date` sans changer le contrat
  existant ; le champ `deadline_date` des connecteurs vides peut être
  pré-rempli par ce module.
* Enrichissement du vocabulaire (NL/PT) et des formats (`jj-mm-aaaa`,
  `2026-11-30T12:00:00Z`) : le module est écrit pour ça (paquets de langue
  isolés).
* Un `benchmark` dans la veine de `career/offer_requirements/benchmark.py`
  pour mesurer le taux de classement sur un corpus réel.

---

## 8. Validation

| Commande | Résultat |
|---|---|
| `.venv/bin/python -m pytest -q tests/test_offer_dates.py` | **671 passed** |
| `.venv/bin/python -m pytest -q` (suite complète) | **2044 passed, 1 skipped** (baseline 1373 + 671, aucune régression) |
| `.venv/bin/python -m ruff check career/offer_dates.py tests/test_offer_dates.py` | All checks passed |
| `VENV_PY=… ./checklist_codex.sh main` | TOUT VERT |
| `VENV_PY=… ./checklist_codex.sh lint` / `secrets` | TOUT VERT |
| `git diff --check` | propre |

Le worktree n'a pas de `.venv` propre : les commandes utilisent celui du
dépôt principal (`/Users/comedelavenne/AI-Excel-Agent/.venv`), comme le
fait le script de checklist via `VENV_PY`.
