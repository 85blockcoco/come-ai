# SPEC-SK19 — Extracteur de niveau d'études requis

- **Mission** : CVBOOST-44 / SK-19 (priorité P1, après SK-16/SK-17/SK-18).
- **Exécutant** : worker `cvboost-44-1792698963`, worktree dédié
  `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-44-1792698963`
  (branche de travail `worker/cvboost-44-1792698963`, livraison
  `agent/spec-sk19-education-extractor`, base `f5b22f2`).
- **Date** : 22 octobre 2026.
- **Nature** : module pur, local, déterministe — aucun réseau, aucun modèle,
  aucune horloge, aucun fichier existant modifié hors l'intégration demandée.

## Ce qui a été livré

| Fichier | Rôle |
|---|---|
| `career/cv_quality/education_extractor.py` | Extracteur multilingue (nouveau) |
| `tests/test_education_extractor.py` | 84 tests (36 fixtures ×2 + contrat) |
| `tests/fixtures/education_extractor/synthetic_education_cases.json` | 36 fixtures synthétiques multilingues |
| `tests/test_career_offer_qualification.py` | +3 tests d'intégration `qualify_offer()` |
| `career/offer_qualification.py` | Intégration : `evidence["education_required"]` |
| `career/cv_quality/__init__.py` | Export API publique `extract_education` / `EducationFact` |

## Contrat livré

```python
extract_education(text: str, lang: str = "auto") -> list[EducationFact]
```

`EducationFact` (dataclass gelée, conforme au squelette SK-19) porte
`fact_type`, `level_rank` (3/4/5/6/8, 0 = niveau indéterminé), `level_label`,
`field`, `source_field`, `quote`, `start_offset`, `end_offset`, `confidence`
(`explicit`/`inferred`/`ambiguous`), `contradictions`.

**Garantie de citation exacte** : `text[fact.start_offset:fact.end_offset] == fact.quote`
sur chaque fait — vérifié pour les 36 fixtures et en document long (offsets absolus).

Six langues : FR, EN, DE, IT, ES, NL. Cinq niveaux : 3, 4, 5, 6, 8.
Sept champs : Finance, Engineering, Business, Data Science, Mathematics,
Economics, Law (fenêtre : phrase ± 200 caractères autour du niveau).

## Décisions d'arbitrage (exposition, jamais d'invention)

1. **Préférence ≠ exigence** : « PhD preferred », « Doctorat préféré »,
   « Promotion erwünscht » → `confidence="inferred"`, jamais `explicit`.
2. **Alternative = un seul fait** : « Diplôme d'ingénieur ou Master 2 requis »
   → 1 fait rank=5 (premier niveau cité, donc le plancher), l'alternative
   reste visible : `contradictions=["Niveau alternatif : Bac+6 (« Master 2 »)"]`.
3. **Conflit = deux faits qui se citent** : « Bac+3 minimum, Master apprécié »
   → 2 faits (rank 5 `inferred` + rank 3 `explicit`), chacun citant l'autre
   dans `contradictions`. Plafond dur : 2 faits de niveau (`MAX_LEVEL_FACTS`).
4. **Équivalence par l'expérience** : « PhD or equivalent experience » →
   `ambiguous` + marqueur canonique `experience_equivalent` ; « Équivalent par
   l'expérience » seul → fait rank=0 `ambiguous` (aucun niveau inventé).
5. **Négations ignorées** : « sans diplôme d'ingénieur », « keinen
   Masterabschluss » → zéro fait, y compris pour le champ d'études.
6. **Synonymes fusionnés** : « Doctorat (PhD) exigé » → 1 fait (première
   occurrence), pas de conflit artificiel entre deux motifs d'un même rang.
7. **Champ seul** : « Formation en Finance exigée » → fait
   `education_field_required`, rank=0, si aucun niveau n'est détectable.
8. **Défaut conservateur** : sans marqueur de requête ni de préférence, la
   confiance est `inferred` — le module ne surestime jamais une exigence.

## Écarts assumés par rapport aux motifs du cahier des charges

Les motifs « obligatoires » du spec ont été repris **avec durcissements ciblés**,
tous documentés et testés :

- `m.a.` / `b.a.` (lettre seule) rejetés : `\bm\.?a\.?\b` matchait « ma » (pronom
  français) — seules les formes pointées (`m.sc.`, `b.a.`) et les expansions
  complètes restent.
- `Dr.` retiré (DE rank 8) : titre de politesse (« Dr. Müller ») → faux
  positif systématique ; `promotion`/`doktorat` couvrent le doctorat allemand.
- `thèse` : la variante `[èe]se` matchait « these » en anglais → `thèse` accentué
  uniquement.
- Frontières de mots ajoutées aux motifs alphabétiques sans `\b` : `ingenieur`
  (NL) matchait **dans** « Wirtschaftsingenieur », créant un second fait
  conflit ; idem `ingeniero` (ES), `ingegnere` (IT).
- Rank 6 = mention **explicite** du 2ᵉ niveau uniquement (« Master 2 », « M2 »,
  « M.Sc. », « mastère ») — les formes génériques (« Master's degree »,
  « Máster », « Masterabschluss », « laurea magistrale ») descendent en rank 5,
  ce qui est la seule lecture cohérente avec le **tableau de validation** du
  spec (ex. « Master's degree in Finance required » → level_rank=5).
- Ajouts terminologiques requis par le tableau de validation : `masterabschluss`
  (DE→5), `wirtschaftsingenieur` (champ Engineering), `finanzas` (ES) et
  `financiën` (NL) dans Finance, `ingegneria` (IT) dans Engineering.
- Conventions du spec conservées telles quelles malgré leur singularité :
  « Licence 3 » → rank 4 ; `laurea triennale` → rank 4.
- Un `lang` explicite filtre les motifs linguistiques ; `auto` balaie les six
  langues (une mention « master » peut être FR ou EN — le rang canonical
  identique rend le filtre inutile pour l'essentiel).

## Intégration `qualify_offer()`

Ajout minimal et non intrusif dans `career/offer_qualification.py` :

```python
if description:
    for fact in extract_education(description):
        if fact.fact_type == "education_level_required" and fact.level_rank > 0:
            evidence["education_required"] = FactEvidence(fact.level_rank, "description_passage", fact.quote)
            break
```

- **Exposition seule** : ni `target_status`, ni `reasons`, ni `missing_fields`
  ne dépendent de l'éducation — la qualification existante est inchangée
  (les 22 tests existants de `test_career_offer_qualification.py` passent sans
  modification).
- `value` = rang canonique (int), `source` = `description_passage`, `quote` =
  citation exacte de l'offre.

## Validation

| Commande | Résultat |
|---|---|
| `pytest -q tests/test_education_extractor.py` | **84 passed** (36 fixtures ×2 + 12 tests de contrat) |
| `pytest -q tests/test_career_offer_qualification.py` | **43 passed** (existant + 3 tests d'intégration) |
| `pytest -q` (suite complète) | **vert** — aucun échec, aucune régression |
| `ruff check` | **clean** (ligne ≤ 140, config projet) |
| `git diff --check` | **propre** |
| `./checklist_codex.sh` | **vert** |

## Hors périmètre

- Aucune modification de `service.py`, du routeur, ni de la base SQLite.
- Aucun fichier existant modifié en dehors de l'intégration `qualify_offer()`
  (3 lignes) et des exports `cv_quality/__init__.py`.
- SK-16/17/18 ne sont pas fusionnés sur `main` : ce module n'en dépend pas
  (vérifié : imports uniquement stdlib + `dataclasses`).
