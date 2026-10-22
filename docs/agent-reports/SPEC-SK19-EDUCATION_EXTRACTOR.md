# SPEC-SK19 — Extracteur niveau d'études requis

**Mission :** CVBOOST-44 / SK-19
**Worktree :** `AI-Excel-Agent-worker-cvboost-44-1792700051`
**Branche :** `worker/cvboost-44-1792700051`
**Statut :** livré, suite complète verte.

---

## 1. Objectif

Le niveau d'études est souvent écrit dans les offres (`Bac+5`, `Master`, `PhD`,
`Diplôme d'ingénieur`, `Bachelor`) mais restait noyé dans le texte libre.
`role_level` n'est rempli que par certains connecteurs et n'est pas fiable.

SK-19 ajoute un extracteur **local, déterministe et hors ligne** qui transforme
ces passages en faits canoniques, avec rang, champ d'études, citation exacte et
traçabilité des contradictions.

---

## 2. Livrables

| Fichier | Rôle |
|---|---|
| `career/cv_quality/education_extractor.py` | Module d'extraction (`EducationFact`, `extract_education`, `detect_language`) |
| `tests/test_education_extractor.py` | 116 tests (fixtures paramétrées + garanties + intégration) |
| `tests/fixtures/education_extractor/cases.json` | 43 cas synthétiques multilingues (dont 15 du cahier des charges) |
| `career/offer_qualification.py` | Intégration : `provenance["education_required"]` |
| `docs/agent-reports/SPEC-SK19-EDUCATION_EXTRACTOR.md` | Ce rapport |

Aucune migration SQLite, aucun changement de schéma, aucun accès réseau : le
module est fusionnable en parallèle des autres SK.

---

## 3. Contrat public

```python
@dataclass(slots=True)
class EducationFact:
    fact_type: Literal["education_level_required", "education_field_required"]
    level_rank: int          # 3, 4, 5, 6, 8 (0 = champ seul, aucun niveau affirmé)
    level_label: str         # "Bac+5", "Master", "PhD", "Ingénieur", "Bachelor"…
    field: Optional[str]     # "Finance", "Engineering", "Business"…
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]

def extract_education(text: str, lang: str = "auto", *, source_field: str = "text") -> list[EducationFact]
def detect_language(text: str) -> str
```

Garanties testées :

- `text[start_offset:end_offset] == quote` pour **chaque** fait ;
- le pliage d'accents (`é → e`, `’ → '`) **conserve les longueurs**, donc les
  offsets restent valides sur le texte original ;
- aucun diplôme n'est inventé : pas de niveau ⇒ pas de fait de niveau ;
- un champ seul produit `education_field_required` avec `level_rank = 0`
  (jamais un rang arbitraire) ;
- retour vide pour un texte vide ou sans exigence académique ;
- `TypeError` pour un texte non-str, `ValueError` pour une langue inconnue.

---

## 4. Six langues, cinq niveaux

| Rang | Libellés détectés |
|---|---|
| 8 | `doctorat`, `thèse`, `docteur`, `PhD`, `doctorate`, `Promotion`/`Doktorat`/`Dr.` (DE), `dottorato` (IT), `doctorado`/`tesis` (ES), `promotie`/`doctoraat` (NL), `Bac+8` |
| 6 | `Bac+6`, `Master 2`, `Master II`, `M2`, `Master spécialisé`, `mastère`, `grade master`, `Diplom` (DE, hors Diplom-Ingenieur) |
| 5 | `Bac+5`, `Master 1`, `M1`, `Master`/`Master's`, `MSc`, `Masterabschluss`, `diplôme/école d'ingénieur`, `Diplom-Ingenieur`, `grande école`, `PGE`, `laurea magistrale` (IT), `engineering degree` |
| 4 | `Bac+4`, `Bachelor 4`, `bachelor (4 years/4 ans)`, `laurea triennale` (IT), `grado`/`licenciatura` (ES), `HBO` (NL) |
| 3 | `Bac+3`, `licence`, `L3`, `Bachelor`, `BSc`, `BA`, `undergraduate` |

Champs reconnus : **Finance, Engineering, Business, Data Science,
Mathematics, Economics, Law** — dans les six langues (`finanzas`, `financiën`,
`ingegneria`, `wirtschaft`, `derecho`, `rechten`, etc.).

La détection de langue est volontairement utilisée uniquement pour arbitrer les
mots ambigus (`Promotion` = doctorat **seulement** en allemand, `tesis` en
espagnol, `dr.` en allemand). Les niveaux numériques restent multilingues.

---

## 5. Règles d'extraction

1. **Segmentation par clause** en conservant les offsets. Les virgules à
   l'intérieur de parenthèses ne coupent pas (`Bac+5 (Finance, Économie)`), les
   abréviations (`M.Sc.`, `Dr.`) non plus.
2. **Alternatives vs conjonctions** :
   - `A ou B` → le rang **le plus bas** suffit
     (`Diplôme d'ingénieur ou Master 2` → rang 5) ;
   - `A et B` → le rang **le plus haut** est exigé
     (`Bac+3 et Master requis` → rang 5).
3. **Champ** : cherché dans la même clause, sinon dans la fenêtre ±200
   caractères du contrat. En cas de recouvrement (`Wirtschaftsingenieur`), le
   match le plus long gagne ; à span égal, priorité déterministe
   (Data Science, Engineering, Finance, Mathematics, Economics, Law, Business).
4. **Confiance** :
   - `explicit` : niveau directement asserté (`Bac+5 minimum`, `Laurea
     magistrale in Ingegneria`) ;
   - `inferred` : préféré/souhaité (`Doctorat préféré`, `Promotion erwünscht`),
     équivalence vague (`Master ou équivalent`), `grande école` ;
   - `ambiguous` : équivalence par l'expérience (`PhD or equivalent
     experience`, `Bac+5 ou équivalent par l'expérience`).
5. **Required vs preferred** : les deux sont conservés, jamais fusionnés en
   silence. `Bac+3 minimum, Master apprécié` renvoie **deux** faits, avec des
   jetons de contradiction mutuels.
6. **Maximum deux faits** : au-delà, l'exigence requise la plus forte et la
   contradiction la plus haute sont conservées.
7. **Garde-fous** : `master` comme verbe (`master Python`), `licence` de
   conduire (`permis de conduire`) et `Dr.` anglais ne produisent pas de fait.

---

## 6. Jetons de contradiction

Stables et destinés au code appelant :

| Jeton | Sens |
|---|---|
| `preferred_only` | niveau apprécié/souhaité, pas requis (`fact.is_preferred`) |
| `accepted_alternative` | niveau accepté comme alternative |
| `experience_equivalent` | niveau levé par expérience équivalente (`fact.is_experience_equivalent`) |
| `conflict_with_rank_N` | un autre fait affirme un rang différent |

Exemple (`Bac+3 minimum, Master apprécié`) :

```text
rang 3  explicit   ["conflict_with_rank_5"]
rang 5  inferred   ["preferred_only", "conflict_with_rank_3"]
```

---

## 7. Intégration `qualify_offer()`

`qualify_offer()` scanne `role_level`, `requirements`,
`eligibility_requirement`, `description_original` et `description`, déduplique
les faits et expose :

```python
result.provenance["education_required"] = FactEvidence(
    value=[fact.to_dict(), ...],   # 0 à 2 faits sérialisables
    source="education_extractor",
    quote=premier_fait.quote,
)
```

- La clé est **absente** quand aucune exigence académique n'est annoncée.
- L'extraction **ne modifie jamais** `target_status`, `contract_type` ni les
  critères de conformité : c'est une évidence informative, pas un filtre.
- Le vocabulaire de qualification existant reste intact (les 40 tests
  historiques passent).

---

## 8. Validation

| Commande | Résultat |
|---|---|
| `pytest -q tests/test_education_extractor.py` | **116 passed** |
| `pytest -q tests/test_career_offer_qualification.py tests/test_career_configurable_contract_criteria.py tests/test_cv_quality_structure.py` | **114 passed** |
| `pytest -q` (suite complète) | **1540 passed, 1 skipped** |
| `ruff check career/cv_quality/education_extractor.py tests/test_education_extractor.py career/offer_qualification.py` | **All checks passed** |
| `git diff --check` | propre |

Le skip unique (`test_offer_summary_exhaustiveness.py`) est antérieur à la
mission (base ou script absent dans le worktree).

---

## 9. Limites assumées

- Un niveau mentionné dans un paragraphe marketing peut être compté comme
  exigence : le module rapporte une **citation vérifiable**, il ne juge pas
  l'intention de l'annonceur.
- Le champ est un choix unique par fait ; `Finance, Économie` renvoie
  `Finance` (premier champ cité), pas une liste.
- `level_rank = 0` signale explicitement un champ sans niveau : les appelants
  doivent le traiter comme « niveau non affirmé », jamais comme Bac+0.
- Aucune inférence inter-annonces, aucun apprentissage, aucun appel LLM.
