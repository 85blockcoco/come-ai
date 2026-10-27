# Mission SK-17 — Extracteur de conditions de travail

Date : 22 octobre 2026
Branche : `agent/spec-sk17-conditions-extractor` (commit partagé avec `worker/cvboost-42-1792687288`)
Base : `f5b22f2` (`main`)
Statut : **TERMINÉE — module livré, intégré, testé**

---

## 1. Ce qui est livré

| Fichier | Rôle |
|---------|------|
| `career/cv_quality/conditions_extractor.py` | Module d'extraction (pur, déterministe, hors-ligne) |
| `career/cv_quality/__init__.py` | Export public (`extract_conditions`, `ConditionFact`, …) |
| `career/offer_qualification.py` | Intégration : `qualify_offer()` → `provenance["conditions"]` |
| `tests/test_conditions_extractor.py` | 123 tests (dont 39 fixtures paramétrées) |
| `tests/fixtures/conditions_extractor/conditions_cases.json` | 39 cas synthétiques multilingues |
| `docs/agent-reports/SPEC-SK17-CONDITIONS_EXTRACTOR.md` | Ce rapport |

**Aucun réseau, aucun modèle, aucun accès disque.** Le module ne lit que le texte qu'on
lui donne : même texte → même liste de faits, toujours.

---

## 2. Contrat public

```python
from career.cv_quality import extract_conditions, extract_conditions_from_offer

facts = extract_conditions("Télétravail 2 jours par semaine")
facts[0].condition_type   # 'hybrid'
facts[0].value            # '2 days/week'
facts[0].quote            # 'Télétravail 2 jours'
facts[0].start_offset     # 0
facts[0].confidence       # 'explicit'
facts[0].contradictions   # []
```

```python
@dataclass
class ConditionFact:
    condition_type: ConditionType    # 15 types
    value: bool | str | int | None
    source_field: str                # 'description_original', 'title', …
    quote: str                       # citation exacte
    start_offset: int
    end_offset: int
    confidence: 'explicit' | 'inferred' | 'ambiguous'
    contradictions: list[str]        # jetons ('remote_vs_onsite', …)
```

API complémentaire :

- `extract_conditions(text, lang="auto", *, source_field="description_original")` — un texte.
- `extract_conditions_from_offer(offer, lang="auto")` — tous les champs d'une offre, les
  contradictions **inter-champs** sont tracées.
- `detect_language(text)` — langue principale détectée.
- `summarize_conditions(facts)` — aperçu sérialisable.

---

## 3. Les 15 types de conditions

| Groupe (contrat SK-17) | Types fins | Groupes du contrat |
|---|---|---|
| `work_location` | `remote`, `hybrid`, `onsite` | localisation |
| `schedule` | `flexible_hours`, `part_time` | organisation du temps |
| `benefits` | `meal_vouchers`, `health_insurance`, `transport`, `equipment` | avantages |
| `training` | `training_budget`, `certification_support`, `language_training` | formation |
| `mobility` | `relocation`, `visa_sponsorship`, `mobility_budget` | mobilité |

`CONDITION_GROUPS` fait le lien entre les types fins (implémentation) et les groupes
coarse (contrat SK-17) : `benefits` = 4 types, `training` = 3 types, `mobility` = 3 types.

### Valeurs

| Type | Valeur | Exemple |
|---|---|---|
| `remote` | `True` / `False` | `Pas de télétravail` → `False` |
| `hybrid` | `True` ou `"N days/week"` | `Hybrid: 3 days from home` → `"3 days/week"` |
| `onsite` | `True` | `Présentiel obligatoire` → `True` |
| `flexible_hours` | `True` | `Horaires flexibles` → `True` |
| `part_time` | `True` / `"N h/week"` / `False` | `20 heures par semaine` → `"20 h/week"` |
| `meal_vouchers` … `equipment` | `True` | `tickets resto` → `True` |
| `training_budget` | `True` ou montant `int` | `Fortbildungsbudget 2000€` → `2000` |
| `certification_support`, `language_training` | `True` | `Certification support` → `True` |
| `relocation`, `visa_sponsorship`, `mobility_budget` | `True` | `Relocation package` → `True` |

---

## 4. Décisions de conception (à relire en priorité)

Cinq choix méritent un avis explicite du relecteur.

### 4.1 Un rythme chiffré est un rythme hybride, pas un « télétravail »

`Télétravail 2 jours par semaine` produit **un seul** fait : `hybrid = "2 days/week"`.
Le passage « télétravail » est consommé par le motif plus précis.

Conséquence : le tableau de contradictions du contrat (« Full remote » + « 2 days onsite »
→ 2 faits) est respecté, mais un Pur « télétravail N jours » n'est **pas** doublé d'un
fait `remote`. C'est le prix de la précision : deux faits pour une seule phrase
déformeraient le décompte des conditions.

### 4.2 Un présentiel chiffré devient un rythme hybride

`2 days onsite` → `hybrid = "2 days/week"`, et **pas** de fait `onsite` : le volume
hebdomadaire décrit un aménagement, pas une présence à temps plein.
`Onsite required` (sans volume) reste `onsite = True`.
C'est exactement la ligne « Full remote + 2 days onsite » du contrat.

### 4.3 `40 heures par semaine` n'est **pas** un temps partiel

Le motif contractuel `(\d{1,2})\s*h(eures?)?\s*(par\s+semaine|/sem)` attrape aussi les
temps pleins. Le module applique un garde-fou : au-delà de `PART_TIME_MAX_HOURS = 34`,
le fait est émis avec `value = False` (le texte dit bien un volume, mais ce n'est pas du
temps partiel). `20 heures par semaine` → `"20 h/week"`.

### 4.4 La langue fixe une priorité, elle ne filtre jamais

`lang="auto"` détecte la langue dominante et les motifs correspondants sont essayés en
premier. Les autres langues restent essayées ensuite : une annonce bilingue n'est jamais
tronquée. `lang="fr"` sur un texte anglais renvoie donc quand même le fait remote.
Une langue inconnue lève `ValueError`.

### 4.5 Précision > redondance

- Une mention vague (`hybrid`) est remplacée par la mention précise (`3 days/week`) ;
  la citation la plus longue est conservée.
- Deux mentions de même valeur ne sont comptées qu'une fois.
- Les oppositions (`True` / `False`) ne sont **jamais** fusionnées : elles doivent rester
  visibles pour être signalées.

---

## 5. Motifs multilingues

Les motifs **obligatoires** du contrat sont repris **verbatim** (`_REMOTE_PATTERNS`,
`_HYBRID_PATTERNS`, `_ONSITE_PATTERNS`, `_FLEXIBLE_HOURS_PATTERNS`, `_PART_TIME_PATTERNS`,
`_BENEFITS_PATTERNS`, `_TRAINING_PATTERNS`, `_MOBILITY_PATTERNS`). Ils sont complétés par
des motifs secondaires, listés explicitement dans `_SUPPLEMENTARY_PATTERNS` et dans les
règles de rythme hybride par langue.

| Langue | Télétravail | Hybride | Présentiel | Horaires | Avantages / formation / mobilité |
|---|---|---|---|---|---|
| FR | `télétravail`, `travail à distance` | `hybride`, `télétravail partiel`, `N jours/semaine` | `présentiel`, `sur site` | `horaires flexibles`, `choix des horaires` | `mutuelle`, `tickets resto`, `budget formation`, `aide installation` |
| EN | `remote`, `work from home`, `wfh`, `remote-first` | `hybrid`, `N days/week` | `on-site`, `in office` | `flexible hours`, `choose your hours` | `health insurance`, `meal vouchers`, `training budget`, `relocation`, `visa sponsorship` |
| DE | `homeoffice`, `home office`, `remote arbeit` | `hybrid`, `N tage/woche` | `vor ort`, `büro` | `gleitzeit`, `selbstbestimmte arbeitszeit` | `krankenversicherung`, `jobticket`, `fortbildungsbudget`, `umzugshilfe`, `arbeitserlaubnis` |
| IT | `lavoro da casa`, `smart working` | `ibrido`, `N giorni/settimana` | `in sede`, `in presenza` | `orari flessibili`, `scelta degli orari` | `assicurazione salute`, `buoni pasto`, `budget formazione`, `permesso lavoro` |
| ES | `teletrabajo`, `trabajo remoto` | `híbrido`, `N días/semana` | `presencial`, `en oficina` | `horario flexible` | `seguro médico`, `cheques comida`, `presupuesto formación`, `permiso trabajo` |
| NL | `thuiswerken`, `volledig remote` | `hybride`, `N dagen/week` | `op locatie`, `op kantoor` | `flexibele werkuren` | `ziekteverzekering`, `maaltijdcheques`, `opleidingsbudget`, `verhuizing` |

### Détail d'implémentation : alternatives développées

Python applique une alternative dans l'ordre d'écriture : dans `(?:remote|remote-first)`,
`remote` gagne toujours et `remote-first` ne serait **jamais** cité. Chaque alternative du
premier groupe est donc compilée séparément (`_expand_alternatives`) : la plus longue l'emporte
ensuite, et la citation reste la plus précise (`Remote-first`, pas `Remote`).

---

## 6. Contradictions

| Cas | Résultat | Jetons |
|---|---|---|
| `Full remote` + `2 days onsite` | `remote=True` + `hybrid="2 days/week"` | `remote_vs_hybrid` |
| `Hybrid 3 days` + `Onsite required` | `hybrid="3 days/week"` + `onsite=True` | `onsite_vs_hybrid` |
| `Remote` + `Pas de télétravail` | 2 faits, confiance `ambiguous` | `remote_conflict` |
| `Hybrid 2 days` + `Hybrid 4 days` | 2 faits, confiance `ambiguous` | `hybrid_conflict` |
| `Remote` (description) + `Onsite` (métadonnées) | 2 faits | `remote_vs_onsite` |
| `Remote` + `onsite` | 2 faits | `remote_vs_onsite` |
| `Pas de télétravail` | `remote=False`, confiance `explicit` | — |
| `Flexible` (sans précision) | `flexible_hours=True`, confiance `inferred` | — |

Les contradictions ne sont jamais résolues par une moyenne : les deux faits restent visibles
et portent le jeton. Elles sont **croisées** entre champs (une contradiction entre la
description et les métadonnées est bien tracée).

---

## 7. Fixtures synthétiques

39 cas dans `tests/fixtures/conditions_extractor/conditions_cases.json`, répartis sur les
6 langues (aucune offre réelle, aucune donnée personnelle).

| Langue | Cas | Langue | Cas |
|---|---|---|---|
| FR | 8 | IT | 5 |
| EN | 10 | ES | 5 |
| DE | 6 | NL | 5 |

Les 13 lignes du tableau de validation du contrat SK-17 sont reprises à l'identique, plus
26 cas supplémentaires (montants, équipements, formations, mobilité, cas « sans
condition », cas « flexible » inféré).

Les 39 cas sont rejoués par un test paramétré qui vérifie **exactement** la liste
`(condition_type, value, confidence)`, plus un second test paramétré qui vérifie que
chaque citation est bien un extrait verbatim du texte et que les offsets concordent.

---

## 8. Intégration dans `qualify_offer()`

```python
conditions = extract_conditions_from_offer(offer)
if conditions:
    evidence["conditions"] = FactEvidence(
        value=[fact.to_dict() for fact in conditions],
        source=f"source_field:{conditions[0].source_field}",
        quote=" | ".join(fact.quote for fact in conditions[:3])[:300],
    )
```

Points de conception :

- **Les conditions n'ont aucun pouvoir de décision.** Elles sont recopiées dans la
  provenance, `target_status` et `reasons` sont inchangés. Un test le vérifie
  explicitement (`test_qualify_offer_conditions_do_not_decide_conformity`).
- Une offre sans condition n'ajoute **pas** de clé `conditions` : la provenance ne se
  remplit pas de vide.
- Champs lus : `description_original`, `description`, `title`, `requirements`, `benefits`,
  `conditions`, `working_conditions`, `perks`, `notes` (listes et dicts aplatis).
- Les offsets sont relatifs au champ lu, `source_field` indique lequel.

---

## 9. Validation

```bash
.venv/bin/python -m pytest -q tests/test_conditions_extractor.py
# → 123 passed

.venv/bin/python -m pytest -q
# → 1547 passed, 1 skipped (skip pré-existant : script ou base absents)

.venv/bin/python -m ruff check .
# → All checks passed!

git diff --check
# → propre
```

La suite complète passe de **1425** tests (base `f5b22f2`) à **1547** tests : **+122**
tests, aucune régression.

---

## 10. Limites connues (hors périmètre, assumé)

1. **Pas de normalisation de la mise en page.** Les offsets sont des index de caractères
   dans le champ lu ; aucun parsing HTML n'est fait ici (le nettoyage de texte est fait en
   amont par `clean_text` / `offer_requirements`).
2. **Pas de score de qualité.** Un fait est « explicite » ou « inféré », jamais « fiable à
   80 % » : ce module ne note pas la qualité d'une offre, il rapporte ce que le texte dit.
3. **Les volumes chiffrés hors modèles FR/EN/DE/IT/ES/NL** (ex. « 3 jours par semaine »
   écrit autrement) ne sont pas extraits.
4. **Le nombre de jours hybridé est borné à 2 chiffres** (`\d{1,2}`) : au-delà, le texte
   n'est pas exploitable et n'est pas deviné.
5. **Aucune détection d'imputation** : le module ne sait pas qu'un texte peut être une
   injection (ce travail est fait par `career/offer_requirements`).
6. **La négation est antérieure au terme** uniquement : « remote » suivi de « not
   available » n'est pas lu comme une négation (forme rare et ambiguë).

---

## 11. Points à faire relire

1. Les choix **4.1 à 4.5** de la section 4 (notamment le garde-fou temps plein et la
   consommation du passage « télétravail » par un rythme chiffré).
2. Le fait que les conditions **n'influencent pas** la décision de conformité de
   `qualify_offer()` — c'est volontaire, mais c'est un choix produit.
3. La valeur `False` de `part_time` pour un volume temps plein : sémantique à valider
   côté affichage.
