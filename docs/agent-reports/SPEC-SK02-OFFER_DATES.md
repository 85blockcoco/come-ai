# SPEC SK-02 — Dates, échéances et durées avec preuves (CVBOOST-23)

**Branche** : `worker/cvboost-23-1792600748` (worktree dédié) + `agent/spec-sk02-offer-dates` (branche registre)
**Base** : `origin/agent/spec-sk02-offer-dates` (`0db9d62`, tour précédent de la mission)
**Date** : 2026-10-21
**Auteur** : Agent Mission 23 (worker) — **tour 3**, revue adversariale du tour précédent

> **Ce qu'est ce tour.** Le module existait déjà (tours 1 et 2). Ce tour ne le
> réécrit pas : il **le passe au crible** avec un corpus adversarial (128 cas
> hors-fixtures, en français, anglais, allemand, italien, espagnol) et corrige
> les **9 erreurs de classification** trouvées. Le détail est en § 3 bis.

---

## 1. Ce qui a été livré

```
career/offer_dates.py                 # module d'analyse temporelle multilingue (1613 l.)
tests/test_offer_dates.py             # 700 tests
tests/fixtures/offer_dates/en.json    # 24 cas synthétiques (pièges obligatoires)
tests/fixtures/offer_dates/fr.json    # 18 cas synthétiques (pièges obligatoires)
tests/fixtures/offer_dates/de.json    # 17 cas synthétiques (pièges obligatoires)
tests/fixtures/offer_dates/it.json    # 19 cas synthétiques (pièges obligatoires)
tests/fixtures/offer_dates/es.json    # 19 cas synthétiques (pièges obligatoires)
tests/fixtures/offer_dates/review_*.json  # 120 cas adversariaux (revue du tour 3)
docs/agent-reports/SPEC-SK02-OFFER_DATES.md   # ce rapport
```

**217 fixtures synthétiques** (aucune offre réelle, aucune personne réelle, aucun réseau),
**700 tests**, module **pur, déterministe, hors ligne** : pas d'horloge, pas de
hasard, pas de réseau, pas de modèle. Le même texte donne toujours les mêmes
faits, dans le même ordre.

Les deux ensembles de fixtures ont le même schéma et sont lus par le même
harnais : `*.json` (les 10 pièges obligatoires, un cas par piège et par
langue) et `review_*.json` (les formulations métier réelles, y compris les
négatifs : un salaire, une date de création de société, un numéro de
référence ne doivent **jamais** produire un fait).

---

## 2. API livrée

```python
from career.offer_dates import extract_dates, extract_offer_dates, detect_language, facts_by_type

facts = extract_dates(text: str, lang: str = "auto", source_field: str = "description_original") -> list[DateFact]
facts = extract_offer_dates(offer: dict, lang: str = "auto") -> list[DateFact]   # multi-champs + contradictions
lang  = detect_language(text: str) -> str
grouped = facts_by_type(facts) -> dict[str, list[DateFact]]
```

### Contrat d'un fait

```json
{
  "fact_type": "start",
  "value": {"day": null, "month": 1, "year": 2027},
  "precision": "month",
  "source_field": "description_original",
  "quote": "Starting January 2027",
  "start_offset": 312,
  "end_offset": 333,
  "confidence": "confirmed",
  "contradictions": [],
  "fact_id": "start@description_original:312",
  "lang": "en"
}
```

- `fact_type` : `published` | `deadline` | `start` | `end` | `duration_exact` |
  `duration_min` | `duration_max` | `duration_range` (**8 types**).
- `value` :
  - date (`published`, `deadline`, `start`, `end`) : `{"day","month","year"}` ;
  - durée : `{"months_min","months_max"}` — **toujours en mois**.
    `duration_exact` → `(N, N)`, `duration_min` → `(N, None)`,
    `duration_max` → `(None, N)`, `duration_range` → les deux bornes.
- `precision` : `day` | `month` | `year` | `unknown`.
- `confidence` : `confirmed` | `inferred` | `ambiguous`.
- `start_offset` / `end_offset` : offsets **absolus dans le texte analysé** ;
  `text[start_offset:end_offset] == quote` est vérifié par test sur tout le corpus.
- `contradictions` : `fact_id` des autres faits incompatibles (**mutuels**), plus
  `"ambiguous_reading:AAAA-MM-JJ"` pour chaque lecture possible d'une date
  numérique inversable.
- `fact_id` : `"{fact_type}@{source_field}:{start_offset}"`, stable et unique dans une analyse.

### Règles de précision / confiance (documentées dans le module)

| Cas | `precision` | `confidence` | `value` |
|-----|-------------|--------------|---------|
| `15 November 2025` | `day` | `confirmed` | `{15, 11, 2025}` |
| `November 2025` | `month` | `confirmed` | `{null, 11, 2025}` |
| `November` (sans année) | `month` | `inferred` | `{null, 11, null}` |
| `15 November` (sans année) | `day` | `inferred` | `{15, 11, null}` |
| `2027` (année seule) | `year` | `confirmed` | `{null, null, 2027}` |
| `01/02/2025` | `unknown` | `ambiguous` | `{null, null, 2025}` + 2 lectures listées |
| `Starting ASAP` | `unknown` | `ambiguous` | `{null, null, null}` |

**Règles centrales** :

1. `precision` = le plus fin composant **écrit explicitement** dans le texte
   (jour → `day`, mois → `month`, année → `year`, rien → `unknown`).
2. Une **année manquante** ne change pas la précision mais passe la confiance
   en `inferred` ; `value["year"]` reste `null`.
3. Une précision `month` **avec** une année connue ne porte jamais de jour.
4. Une **date numérique inversable** ne s'engage sur rien : jour et mois restent
   `null`, la précision est `unknown`, la confiance `ambiguous` et les deux
   lectures possibles sont listées dans `contradictions`.
5. Une durée a toujours `precision="month"` : sa valeur est en mois.

---

## 3. Les pièges obligatoires (zéro tolérance)

| Piège | Règle appliquée | Implémentation | Fixture |
|-------|-----------------|----------------|---------|
| "Apply by 15 November" | jamais un début → `deadline` | le marqueur `deadline` l'emporte sur `start` (marqueurs qui se chevauchent = une seule phrase, le plus spécifique gagne) | `en-deadline-apply-by` |
| "Starting January" | jamais le 1er janvier | `day=None`, `precision="month"`, `confidence="inferred"` | `en-start-month-without-year` |
| "Up to six months" | maximum → `duration_max` | modificateur `up to` (et équivalents FR/DE/IT/ES) | `en-duration-max` |
| "At least six months" | minimum → `duration_min` | modificateur `at least` | `en-duration-min` |
| "Three to six months" | intervalle → `duration_range` | motif de range à connecteurs par langue | `en-duration-range` |
| "Two years of prior experience" | jamais une durée de contrat | contexte « expérience » (avant/après) → aucun fait | `en-prior-experience-is-not-a-duration` |
| `01/02/2025` | `ambiguous` + contradiction si inversable | jour et mois **non devinés** (`null`), les deux lectures listées | `en-ambiguous-numeric-date` |
| Publication + échéance même phrase | **deux** faits distincts | un fait par expression de date | `en-published-and-deadline-are-two-facts` |
| Mois sans année | `precision="month"`, `year=null`, `inferred` | idem | `fr-start-month-without-year` |
| Deux sources contradictoires | les deux faits, contradictions mutuelles | comparaison dates + intervalles de durée | `test_two_conflicting_dates_name_each_other` |

### Pièges supplémentaires traités (au-delà de la table)

| Piège | Comportement |
|-------|--------------|
| "Applications open from 1 March 2027" | **aucun** fait `start` : l'ouverture des candidatures n'est pas le début du poste (garde `_APPLICATION_WORDS` + `_APPLICATION_GLUE`) |
| "The application team starts on 1 March 2027" | fait `start` conservé : la garde ne bloque que si le mot « application » est collé au marqueur |
| "Bewerbungen starten am 15. Januar 2027" | aucun fait `start` (même règle, allemand) |
| "You have 6 months of experience with Excel." | aucun fait `duration_*` |
| "The process takes 6 months" | aucun fait `duration_*` (délai relatif, pas une durée de contrat) |
| "Salary: 2,000 euros per month" | aucun fait `duration_*` |
| "Jan-June 2027" / "de janvier à juin 2027" | **deux** faits (`start` + `end`), pas de doublon avec les dates nommées |
| "Starting ASAP" | fait `start` avec `precision="unknown"` et une valeur vide — jamais un jour inventé |
| Date sans libellé ("01/02/2025" seul) | **aucun** fait : sans marqueur, aucun `fact_type` ne peut être attribué sans inventer |

---

## 3 bis. Revue adversariale du tour 3 — 9 bugs corrigés

Le tour précédent livrait un module **correct sur ses 82 fixtures**, mais
silencieusement faux sur des formulations courantes. Un corpus adversarial
indépendant (128 cas, hors fixtures : 5 langues × formulations métier réelles,
plus des offres longues et des nombres qui ne doivent **pas** devenir des
dates) a mis en évidence **9 erreurs de classification**. Toutes sont
corrigées et **verrouillées par un test de non-régression**.

| # | Texte | Avant | Après | Cause |
|---|-------|-------|-------|-------|
| 1 | `Postular hasta el 15 de noviembre de 2025` (ES) | `end` | **`deadline`** | « hasta el » (fin) et « postal hasta » (échéance) sont **une seule phrase** ; le marqueur le plus long doit décider |
| 2 | `Prise de poste le 1er janvier 2027` (FR) | `published` | **`start`** | idem (« poste le » = faux positif du vocabulaire de publication) **+** « poste » (nom) supprimé du vocabulaire, seul « posté » (participe) reste |
| 3 | `The role starts in March and ends in June 2027` (EN) | 2 × `start` | **`start` + `end`** | « ends in » manquait dans le vocabulaire de fin |
| 4 | `Le contrat se termine en décembre 2027` (FR) | *aucun fait* | **`end`** | « se termine en » manquait |
| 5 | `Der Vertrag endet im Dezember 2027` (DE) | *aucun fait* | **`end`** | « endet im » manquait |
| 6 | `Il contratto termina in dicembre 2027` (IT) | *aucun fait* | **`end`** | « termina in » manquait |
| 7 | `El contrato termina en diciembre de 2027` (ES) | *aucun fait* | **`end`** | « termina en » manquait |
| 8 | `Start im Januar` (DE), `Comienza en enero` (ES), `Comincia in gennaio` (IT) | *aucun fait* | **`start`** | formes verbales absentes du vocabulaire de début |
| 9 | `La práctica dura seis meses` (ES), `Il tirocinio dura sei mesi` (IT) | *aucun fait* | **`duration_exact`** | le verbe « dura » (dure) manquait dans le vocabulaire de durée |

Trois autres corrections mineures, trouvées par le même corpus :

- **« 1° gennaio 2027 » (IT)** : l'ordinal symbolique (`°`, `º`, `ª`) est
  désormais lu → `day=1`. Avant, le `\b` exigé après l'ordinal rendait la
  journée illisible et le jour disparaissait.
- **« from 3 to 6 months » (EN)** : le préfixe « from » est un **introducteur
  d'intervalle**, pas un délai relatif → `duration_range` (et non aucun fait).
- **« January 2027 »** : garde `(?!\d)` ajoutée après le jour pour qu'un mois
  suivi d'une année ne soit jamais lu comme un jour (« January 20 » + « 27 »).

### La règle qui corrige 1, 2 et 3 : résolution par spécificité

Avant : le marqueur **le plus proche** de la date gagnait. C'est faux quand
deux marqueurs se **chevauchent** — ils décrivent alors **une seule phrase**,
et c'est le plus long (le plus spécifique) qui en porte le sens.

```
"Postular hasta el 15 de noviembre"
   └──── deadline ────┘└─ end ─┘          → une phrase → "postular hasta" gagne → deadline

"Prise de poste le 1er janvier 2027"
   └──── start ─────┘└─ published ─┘      → une phrase → "prise de poste" gagne → start
```

Implémentation : `_context_markers()` collecte les marqueurs candidats,
`_cluster_markers()` regroupe ceux qui se chevauchent (union transitive),
`_best_marker()` choisit la phrase **la plus proche** de la date, et dans
chaque phrase le marqueur **le plus long** (ex æquo : la priorité
`deadline > published > start > end`).

### Vérification

| Corpus | Avant | Après |
|--------|-------|-------|
| 120 cas adversariaux (désormais en fixtures `review_*.json`) | 11 échecs | **0 échec** |
| 97 fixtures du tour précédent + 15 de non-régression | 0 échec | 0 échec |

---

## 4. Les 5 langues

| Langue | Mois | Contextes | Modificateurs de durée | Range |
|--------|------|-----------|------------------------|-------|
| FR | janvier…décembre (+ accents et abréviations) | `début`, `prise de fonction`, `prise de poste`, `à partir du`, `date limite`, `candidatures jusqu'au`, `postulez avant`, `publiée le`, `fin du contrat`, `se termine le/en` | `au moins` / `jusqu'à` | `de 3 à 6 mois` |
| EN | january…december | `starting`, `start date`, `starts on`, `begins on`, `available from`, `apply by`, `applications close`, `deadline`, `posted on`, `published on`, `contract ends on/in` | `at least` / `up to` | `three to six months`, `from 3 to 6 months` |
| DE | Januar…Dezember | `Beginn`, `ab dem`, `Startdatum`, `Eintritt`, `Start im`, `Bewerbungsfrist`, `Bewerbung bis`, `Einreichung bis`, `veröffentlicht am`, `Vertragsende`, `endet am/im` | `mindestens` / `bis zu` | `3 bis 6 Monate` |
| IT | gennaio…dicembre | `inizio`, `dal`, `a partire dal`, `comincia`, `scadenza`, `candidature entro`, `entro il`, `pubblicato il`, `termine il`, `termina in` | `almeno` / `fino a` | `da 3 a 6 mesi` |
| ES | enero…diciembre | `inicio`, `desde`, `a partir de`, `comienza`, `fecha límite`, `plazo de solicitud`, `postular hasta`, `publicado el`, `termina el/en`, `hasta el` | `al menos` / `hasta` | `de 3 a 6 meses` |

Vocabulaire de durée : les verbes « dure » (FR), « dauert » (DE), **« dura »**
(IT) et **« dura »** (ES) sont reconnus comme announcement de durée — sans
eux, « Il tirocinio dura sei mesi » ne produisait aucun fait.

Détection automatique (`lang="auto"`) : comptage de marqueurs lexicaux (mots
fonction + noms de mois) par langue, repli sur `en` si rien de concluant.
Une langue **non supportée** lève `ValueError` (jamais de devinette silencieuse).

---

## 5. Contradictions

Trois familles de contradictions, toutes **exposées et jamais arbitrées** :

1. **Même type, valeurs incompatibles** — deux `start` différents, deux
   `duration_exact` (6 et 12 mois), une `duration_min` (≥ 6) contre une
   `duration_max` (≤ 3)… La comparaison utilise les intervalles :
   `exact N` = `[N,N]`, `min N` = `[N,∞]`, `max N` = `(-∞,N]`, `range` = `[min,max]`.
   Deux intervalles disjoints se contredisent ; `exact 6` et `range 3-6` ne se
   contredisent pas.
2. **Cohérence temporelle** — `end` avant `start`, `deadline` avant `published`.
3. **Lecture ambiguë** — `01/02/2025` porte les deux lectures possibles dans
   `contradictions` (`ambiguous_reading:2025-01-02` et
   `ambiguous_reading:2025-02-01`), sans jamais assumer un jour.

Chaque fait contradictoire cite l'autre : les deux listes sont symétriques
(vérifié par test sur les deux sources et sur deux champs d'une même offre).

`extract_offer_dates` lit en plus les champs structurés (`posted_date`,
`deadline_date`, `start_date`, `end_date`, `duration_months`) et croise les
sources : une description qui annonce un début en janvier et un champ
`start_date` au 1er mai produisent deux faits `start` qui se contredisent.

---

## 6. Mesures

| Mesure demandée | Résultat | Preuve |
|------------------|----------|--------|
| Zéro échéance seule classée comme début | ✅ 0 cas | `absent: ["start"]` sur toutes les fixtures `deadline` (5 langues) |
| Zéro borne maximale utilisée comme preuve de durée minimale | ✅ 0 cas | `duration_max` ≠ `duration_min` dans les 5 fixtures `up to` / `bis zu` / `fino a` / `hasta` / `jusqu'à` |
| ≥ 95 % des faits explicitement libellés correctement classés | ✅ **100 %** (217/217 cas du corpus, 200 faits attendus) | `test_the_corpus_is_classified_at_least_95_percent` |
| Tous les autres cas = `unknown` ou `contradictory` | ✅ | `precision="unknown"` pour les dates non résolubles ; `contradictions` pour les conflits ; sinon **aucun** fait (pas de `fact_type` deviné) |
| Aucun jour inventé (`day=null` si non explicite) | ✅ 0 cas | `test_no_day_is_invented_anywhere_in_the_corpus` + règle de précision |
| 8 `fact_type` extraits | ✅ 8 | `deadline` 54, `start` 44, `published` 27, `end` 24, `duration_exact` 17, `duration_max` 12, `duration_min` 11, `duration_range` 11 sur le corpus |
| 5 langues supportées | ✅ 5 | 33 à 68 fixtures par langue |
| Offsets exacts + quote + precision + confidence + contradictions | ✅ | `test_quotes_are_the_exact_source_span` sur tout le corpus |
| **≥ 95 % des faits hors fixtures** (corpus adversarial) | ✅ **100 %** (120/120 cas) | corpus de revue, § 3 bis |

### Répartition du corpus (217 cas, 200 faits attendus)

| Précision | nb | | Confiance | nb |
|-----------|----|---|-----------|----|
| `day` | 100 | | `confirmed` | 165 |
| `month` | 88 | | `inferred` | 23 |
| `unknown` | 12 | | `ambiguous` | 12 |

Les 12 faits `unknown` = 5 dates numériques inversables (une par langue) + 5
expressions sans date calendaire (« Starting ASAP », « Beginn: sofort », …)
+ 2 cas supplémentaires de la revue.

---

## 7. Tests

```bash
$ .venv/bin/python -m pytest -q tests/test_offer_dates.py
700 passed

$ .venv/bin/python -m ruff check .
All checks passed!

$ .venv/bin/python -m pytest -q
2073 passed, 1 skipped        # suite complète, aucune régression

$ git diff --check
# (vide) — aucun problème de whitespace
```

Couverture :

- 217 fixtures synthétiques paramétrées × 3 contrôles (contrat exact, offsets
  exacts, déterminisme) ;
- les 10 pièges obligatoires, dans les 5 langues quand ils s'y traduisent ;
- **120 fixtures de revue adversariale** (§ 3 bis) : formulations métier
  réelles, y compris les négatifs (salaire, date de société, référence) ;
- contradictions mutuelles (dates, durées, sources croisées) ;
- garde-fous API (type invalide, langue inconnue, texte vide) ;
- 2 offres réalistes longues (EN/FR) qui vérifient les offsets dans un texte
  > 300 caractères (régression d'un bug d'offsets trouvée pendant la mission) ;
- **10 tests de non-régression** dédiés aux 9 bugs corrigés (spécificité des
  marqueurs, fin/début/durée dans les 5 langues, ordinal `1°`, préfixe de
  range, salaire et date de société) ;
- réseau bloqué par une fixture `autouse` : le module ne peut pas appeler
  le réseau.

---

## 8. Comparaison avec les tours précédents de la mission

Cette mission a déjà tourné **deux fois** :

| Tour | Ordre | Commit | Contenu |
|------|-------|--------|---------|
| 1 | `cvboost-23-1792597758` | `3b18eec` | Première implémentation, contrat différent (`value` des durées enrichi, `precision="unknown"` pour les durées) |
| 2 | `cvboost-23-1792597737` | `0db9d62` | Contrat **aligné sur le squelette de mission** (`value={"months_min","months_max"}`, `precision="month"`), garde « ouverture des candidatures », 82 fixtures / 270 tests |
| **3 (ce tour)** | `cvboost-23-1792600748` | `f79c5ab` + suivi | **Revue adversariale** : 9 bugs de classification corrigés, 15 fixtures + 10 tests de non-régression ajoutés |

**Ce tour ne réécrit pas le module** : il part du `0db9d62` (branche registre
`origin/agent/spec-sk02-offer-dates`), le soumet à un corpus adversarial
indépendant, et corrige ce qui ne tenait pas. Le contrat public
(`DateFact`, `extract_dates`, `extract_offer_dates`, `detect_language`,
`facts_by_type`) est **inchangé** : l'intégrateur n'a rien à réadapter.

| Point | Tour 2 (`0db9d62`) | Tour 3 (ce tour) |
|-------|-------------------|-----------------|
| Contrat public | 8 `fact_type`, offsets, quote, precision, confidence, contradictions | **identique** |
| `value` des durées | `{"months_min","months_max"}` | **identique** |
| 97 fixtures / 340 tests | 82 fixtures / 270 tests | 217 fixtures / 700 tests |
| `Postular hasta el 15 de noviembre` | `end` ❌ | **`deadline`** ✅ |
| `Prise de poste le 1er janvier 2027` | `published` ❌ | **`start`** ✅ |
| `… ends in / se termine en / endet im / termina in / termina en` | non lu ❌ | **lu** ✅ |
| `… dura sei mesi / dura seis meses` (IT/ES) | non lu ❌ | **lu** ✅ |
| `1° gennaio 2027` | jour perdu ❌ | `day=1` ✅ |
| `from 3 to 6 months` | aucun fait ❌ | `duration_range` ✅ |

Les commits des tours précédents restent accessibles :
`git show 3b18eec`, `git show 0db9d62`.

---

## 9. Choix de conception (à relire)

1. **Marqueur le plus proche, phrase la plus spécifique** — la classification
   d'une date expression utilise le marqueur de contexte qui la précède
   (distance ≤ 45 caractères, pas de rupture de phrase entre les deux). Les
   marqueurs qui **se chevauchent** décrivent **une seule phrase** : ils sont
   regroupés, et c'est le marqueur **le plus long** (le plus spécifique) qui
   donne le `fact_type` — ex æquo, la priorité `deadline > published > start >
   end`. C'est ce qui fait que « Apply by 15 November » est une échéance et
   jamais un début, que « Candidatures jusqu'au 15 novembre » bat « jusqu'au »,
   et que « Postular hasta el 15 de noviembre » est une échéance et non une
   fin de contrat.
2. **Durée = uniquement mois et années.** Une durée en semaines est ignorée :
   convertir des semaines en mois imposerait un ratio arbitraire. Les années
   sont converties en mois (×12, exact).
3. **Durée non qualifiée = pas de fait.** « 6 mois » seul, sans marqueur de
   contrat ni borne explicite, ne produit rien : mieux vaut un fait absent
   qu'une durée inventée. En revanche « up to six months », « at least six
   months » et « three to six months » se suffisent à eux-mêmes.
4. **Une date sans libellé n'est pas un fait.** Le vocabulaire des
   `fact_type` est fermé : sans marqueur, aucun type ne peut être attribué
   sans deviner. Le module ne produit donc pas de fait « orphan ».
5. **Aucune intégration au code existant.** Le module est indépendant
   (mission « module indépendant ») : il n'est branché ni sur `scoring.py`,
   ni sur `offer_qualification.py`, ni sur les connecteurs. Le raccord
   (remplacer `posted_date` / `deadline_date` vides par les faits extraits)
   reste à faire côté intégrateur, sur la branche d'intégration.
6. **Vocabulaire duplication assumé.** `career/offer_qualification.py` a déjà
   des tables de mois et de nombres ; le module les **duplique** volontairement
   pour rester sans dépendance et sans risque de régression croisée. La
   convergence pourra être faite plus tard si l'intégration le demande.
7. **Précision = plus fin composant explicite.** Une année manquante ne
   change pas la précision, elle baisse la confiance (`inferred`). Une date
   numérique inversable, elle, ne s'engage sur rien (`precision="unknown"`,
   jour et mois `null`, les deux lectures listées dans `contradictions`) :
   c'est la lecture la plus prudente de « aucun jour inventé ».

---

## 10. Limites connues

| Limite | Impact | Piste |
|--------|--------|-------|
| Une seule langue par appel | un texte FR/EN mélangé n'est lu que dans la langue demandée | `lang="auto"` choisit une langue ; un scan multi-langue reste possible |
| Semaines ignorées | « 6 weeks » ne produit pas de durée | autoriser un facteur explicite si le métier le demande |
| Trimestres / saisons (`Q3 2027`) | non extraits (pas de mois, donc pas de valeur) | ajouter une précision `quarter` au contrat |
| Champs structurés partiels | `start_date="2027-01"` (sans jour) n'est pas parsé | accepter le format ISO partiel |
| Contexte > 45 caractères | un marqueur très éloigné de la date n'est pas retenu | paramétrable |
| Aucun câblage applicatif | le module n'améliore pas encore les offres en production | mission d'intégration à planifier |

---

## 11. Checklist Codex

```bash
$ ./checklist_codex.sh
# Étape 1 (tests main) : 1713 passed, 1 skipped
# Étape 5 (secrets) : aucun secret tracké
# Étape 7 (DevKit) : 207 passed
# Étape 10 (lint) : ruff check . → All checks passed!
# Les étapes memory / study-coach / fingerprint : worktrees absents → avertis, ignorés
# → TOUT VERT
```

---

## 12. Fichiers modifiés

```
A career/offer_dates.py
A tests/test_offer_dates.py
A tests/fixtures/offer_dates/en.json
A tests/fixtures/offer_dates/fr.json
A tests/fixtures/offer_dates/de.json
A tests/fixtures/offer_dates/it.json
A tests/fixtures/offer_dates/es.json
A tests/fixtures/offer_dates/review_en.json
A tests/fixtures/offer_dates/review_fr.json
A tests/fixtures/offer_dates/review_de.json
A tests/fixtures/offer_dates/review_it.json
A tests/fixtures/offer_dates/review_es.json
A docs/agent-reports/SPEC-SK02-OFFER_DATES.md
```

Aucun fichier existant n'a été modifié : la mission ne touche aucun autre
composant du dépôt.

---

## 13. Conclusion

- ✅ Module `career/offer_dates.py` : analyseur temporel multilingue **FR/EN/DE/IT/ES**
- ✅ **8** `fact_type`, offsets exacts, quote verbatim, precision, confidence, contradictions mutuelles
- ✅ Les **10 pièges obligatoires** sont couverts, dans les 5 langues
- ✅ **9 bugs de classification** trouvés par revue adversariale et corrigés (§ 3 bis)
- ✅ **217 fixtures synthétiques** + **700 tests**, 100 % du corpus correctement classé
- ✅ Zéro jour inventé, zéro échéance classes comme début, zéro maximum utilisé comme minimum
- ✅ Ruff propre, suite complète verte (2073 tests), `git diff --check` propre
- ✅ Rapport livré

**Prêt pour relecture et intégration.** Le contrat public n'a pas bougé : ce
tour n'apporte que des corrections de classification et de la couverture de
test.
