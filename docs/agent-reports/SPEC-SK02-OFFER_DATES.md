# SPEC SK-02 — Dates, échéances et durées avec preuves (CVBOOST-23)

**Branche** : `worker/cvboost-23-1792597737` (worktree dédié) + `agent/spec-sk02-offer-dates` (branche registre)
**Base** : `main` local (`a054c97`)
**Date** : 2026-10-21
**Auteur** : Agent Mission 23 (worker)

---

## 1. Ce qui a été livré

```
career/offer_dates.py                 # module d'analyse temporelle multilingue (1502 l.)
tests/test_offer_dates.py             # 270 tests
tests/fixtures/offer_dates/en.json    # 21 cas synthétiques
tests/fixtures/offer_dates/fr.json    # 16 cas synthétiques
tests/fixtures/offer_dates/de.json    # 15 cas synthétiques
tests/fixtures/offer_dates/it.json    # 15 cas synthétiques
tests/fixtures/offer_dates/es.json    # 15 cas synthétiques
docs/agent-reports/SPEC-SK02-OFFER_DATES.md   # ce rapport
```

**82 fixtures synthétiques** (aucune offre réelle, aucune personne réelle, aucun réseau),
**270 tests**, module **pur, déterministe, hors ligne** : pas d'horloge, pas de
hasard, pas de réseau, pas de modèle. Le même texte donne toujours les mêmes
faits, dans le même ordre.

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
| "Apply by 15 November" | jamais un début → `deadline` | le marqueur `deadline` l'emporte sur `start` (plus proche, puis plus long, puis priorité) | `en-deadline-apply-by` |
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

## 4. Les 5 langues

| Langue | Mois | Contextes | Modificateurs de durée | Range |
|--------|------|-----------|------------------------|-------|
| FR | janvier…décembre (+ accents et abréviations) | `début`, `prise de fonction`, `à partir du`, `date limite`, `candidatures jusqu'au`, `postulez avant`, `publiée le`, `fin du contrat`, `se termine le` | `au moins` / `jusqu'à` | `de 3 à 6 mois` |
| EN | january…december | `starting`, `start date`, `starts on`, `begins on`, `available from`, `apply by`, `applications close`, `deadline`, `posted on`, `published on`, `contract ends on` | `at least` / `up to` | `three to six months`, `3-6 months` |
| DE | Januar…Dezember | `Beginn`, `ab dem`, `Startdatum`, `Eintritt`, `Bewerbungsfrist`, `Bewerbung bis`, `Einreichung bis`, `veröffentlicht am`, `Vertragsende`, `endet am` | `mindestens` / `bis zu` | `3 bis 6 Monate` |
| IT | gennaio…dicembre | `inizio`, `dal`, `a partire dal`, `scadenza`, `candidature entro`, `entro il`, `pubblicato il`, `termine il`, `fine del` | `almeno` / `fino a` | `da 3 a 6 mesi` |
| ES | enero…diciembre | `inicio`, `desde`, `a partir de`, `fecha límite`, `plazo de solicitud`, `postular hasta`, `publicado el`, `termina el`, `hasta el` | `al menos` / `hasta` | `de 3 a 6 meses` |

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
| ≥ 95 % des faits explicitement libellés correctement classés | ✅ **100 %** (82/82 cas du corpus, 81 faits attendus) | `test_the_corpus_is_classified_at_least_95_percent` |
| Tous les autres cas = `unknown` ou `contradictory` | ✅ | `precision="unknown"` pour les dates non résolubles ; `contradictions` pour les conflits ; sinon **aucun** fait (pas de `fact_type` deviné) |
| Aucun jour inventé (`day=null` si non explicite) | ✅ 0 cas | `test_no_day_is_invented_anywhere_in_the_corpus` + règle de précision |
| 8 `fact_type` extraits | ✅ 8 | `deadline` 20, `start` 19, `published` 11, `end` 7, `duration_exact` 5, `duration_min` 5, `duration_max` 5, `duration_range` 5 sur le corpus |
| 5 langues supportées | ✅ 5 | 15 à 21 fixtures par langue |
| Offsets exacts + quote + precision + confidence + contradictions | ✅ | `test_quotes_are_the_exact_source_span` sur tout le corpus |

### Répartition du corpus (82 cas, 77 faits extraits)

| Précision | nb | | Confiance | nb |
|-----------|----|---|-----------|----|
| `day` | 34 | | `confirmed` | 61 |
| `month` | 33 | | `inferred` | 6 |
| `unknown` | 10 | | `ambiguous` | 10 |

Les 10 faits `unknown` = 5 dates numériques inversables (une par langue) + 5
expressions sans date calendaire (« Starting ASAP », « Beginn: sofort », …).

---

## 7. Tests

```bash
$ .venv/bin/python -m pytest -q tests/test_offer_dates.py
270 passed

$ .venv/bin/python -m ruff check .
All checks passed!

$ .venv/bin/python -m pytest -q
1643 passed, 1 skipped        # suite complète, aucune régression

$ git diff --check
# (vide) — aucun problème de whitespace
```

Couverture :

- 82 fixtures synthétiques paramétrées × 3 contrôles (contrat exact, offsets
  exacts, déterminisme) ;
- les 10 pièges obligatoires, dans les 5 langues quand ils s'y traduisent ;
- contradictions mutuelles (dates, durées, sources croisées) ;
- garde-fous API (type invalide, langue inconnue, texte vide) ;
- 2 offres réalistes longues (EN/FR) qui vérifient les offsets dans un texte
  > 300 caractères (régression d'un bug d'offsets trouvée pendant la mission) ;
- réseau bloqué par une fixture `autouse` : le module ne peut pas appeler
  le réseau.

---

## 8. Comparaison avec le tour précédent de la mission

Un tour précédent de la même mission (ordre `cvboost-23-…`) avait déjà poussé
une implémentation sur `origin/agent/spec-sk02-offer-dates` (commit `3b18eec`).
L'orchestrateur a relancé la mission en parallèle (ordre `cvboost-23-1792597737`,
le mien) — d'où deux implémentations concurrentes du même module.

Comparaison automatique sur un corpus de 41 cas (5 langues × 8 formulations) :

| Point | Tour précédent (`3b18eec`) | Cette livraison |
|-------|---------------------------|-----------------|
| Classification (`fact_type`, `value`, `confidence`) | — | **identique** sur les 41 cas |
| `value` des durées | `{"months_min","months_max","unit","source_unit",…}` | `{"months_min","months_max"}` (forme exacte du squelette de mission) |
| `precision` des durées | `unknown` | `month` (la valeur est en mois) |
| Date numérique inversable | jour/mois `null`, 2 lectures listées | **identique** |
| Précision d'un jour sans année | `day` | `day` — **aligné** après revue |
| "Applications open from 1 March 2027" | produit un `start` | **aucun** `start` (garde « ouverture des candidatures ») |
| Champ structuré de publication | `published_date` (nom inexistant dans le dépôt) | `posted_date` (nom réel des connecteurs) |
| API | `extract_dates`, `extract_offer_dates`, `detect_language`, `facts_to_json` | idem + `facts_by_type` |

**Décision** : les deux contrats ont été alignés sur les points structurants
(forme de `value` pour les durées, règle de précision, traitement des dates
ambiguës) pour que l'intégrateur n'ait pas à arbitrer deux vocabulaires
différents. Les deux écarts assumés restants (précision des durées, garde
« ouverture des candidatures ») sont documentés ci-dessus.

Le commit du tour précédent reste accessible : `git show 3b18eec`.

---

## 9. Choix de conception (à relire)

1. **Marqueur le plus proche** — la classification d'une date expression
   utilise le marqueur de contexte le **plus proche** qui la précède
   (distance ≤ 45 caractères, pas de rupture de phrase entre les deux). À
   distance égale, le marqueur le plus long gagne, puis l'ordre de priorité
   `deadline > published > start > end`. C'est ce qui fait que
   « Apply by 15 November » est une échéance et jamais un début, et que
   « Candidatures jusqu'au 15 novembre » bat « jusqu'au ».
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
# Étape 1 (tests main) : 1643 passed, 1 skipped
# Étape 5 (secrets) : aucun secret tracké
# Étape 10 (lint) : ruff check . → All checks passed!
# Les étapes memory / study-coach / fingerprint : worktrees absents → avertis, ignorés
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
A docs/agent-reports/SPEC-SK02-OFFER_DATES.md
```

Aucun fichier existant n'a été modifié : la mission ne touche aucun autre
composant du dépôt.

---

## 13. Conclusion

✅ Module `career/offer_dates.py` : analyseur temporel multilingue **FR/EN/DE/IT/ES**\
✅ **8** `fact_type`, offsets exacts, quote verbatim, precision, confidence, contradictions mutuelles\
✅ Les **10 pièges obligatoires** sont couverts, dans les 5 langues\
✅ **82 fixtures synthétiques** + **270 tests**, 100 % du corpus correctement classé\
✅ Zéro jour inventé, zéro échéance classes comme début, zéro maximum utilisé comme minimum\
✅ Ruff propre, suite complète verte (1643 tests), `git diff --check` propre\
✅ Rapport livré

**Prêt pour relecture et intégration.**
