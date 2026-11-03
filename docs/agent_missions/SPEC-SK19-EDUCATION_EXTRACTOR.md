# MISSION SPEC KIT — SK-19 : Extracteur niveau d'études requis

> **Priorité : P1** — Après SK-16/SK-17/SK-18. Module indépendant, worktree dédié.

---

## Contexte

Le niveau d'études requis est souvent présent dans les offres ("Bac+5", "Master", "PhD", "Diplôme d'ingénieur", "Bachelor") mais **non extrait** structurellement. `role_level` parfois remplit, mais pas fiable.

**Objectif** : Extracteur regex multilingue → niveau canonique (rank 3-8) + evidence.

---

## Module à créer

```
career/cv_quality/education_extractor.py
tests/test_education_extractor.py
tests/fixtures/education_extractor/
```

---

## Contract attendu

```python
@dataclass
class EducationFact:
    fact_type: Literal["education_level_required", "education_field_required"]
    level_rank: int                    # 3=Bac+3, 4=Bac+4, 5=Bac+5/M1, 6=Bac+6/M2, 8=PhD
    level_label: str                   # "Bac+5", "Master", "PhD", "Ingénieur", "Bachelor"
    field: str | None                  # "Finance", "Engineering", "Business", "Data Science", etc.
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]
```

---

## Patterns obligatoires (multilingues)

### Niveaux (rank → patterns)

```python
_EDUCATION_LEVEL_PATTERNS = {
    8: [  # PhD / Doctorat
        # FR
        r"\b(?:doctorat|phd|thèse|doctorate)\b",
        # EN
        r"\b(?:phd|ph\.?d\.?|doctorate|doctoral\s+degree)\b",
        # DE
        r"\b(?:promotion|doktorat|dr\.)\b",
        # IT
        r"\b(?:dottorato|phd|dottore\s+di\s+ricerca)\b",
        # ES
        r"\b(?:doctorado|phd|tesis)\b",
        # NL
        r"\b(?:promotie|phd|doctoraat)\b",
    ],
    6: [  # Bac+6 / Master 2 / M2 / Master Spécialisé
        # FR
        r"\b(?:bac\s*[+]?\s*6|master\s*2|m2|master\s+spécialisé?|ms|mastère|grade\s+master)\b",
        # EN
        r"\b(?:master'?s?\s+degree|m\.?sc\.?|m\.?a\.?|master\s+of\s+science|master\s+of\s+arts)\b",
        # DE
        r"\b(?:master|diplom|master\s+abschluss)\b",
        # IT
        r"\b(?:laurea\s+magistrale|master|laurea\s+specialistica)\b",
        # ES
        r"\b(?:máster|master|máster\s+universitario)\b",
        # NL
        r"\b(?:master|master'?s)\b",
    ],
    5: [  # Bac+5 / Master 1 / M1 / École d'ingénieur / Grande École
        # FR
        r"\b(?:bac\s*[+]?\s*5|master\s*1|m1|école\s+d'?ingénieur|grande\s+école|diplôme\s+d'?ingénieur|pge|programme\s+grande\s+école)\b",
        # EN
        r"\b(?:master'?s|m\.?sc|engineering\s+degree|grande\s+ecole|french\s+engineering)\b",
        # DE
        r"\b(?:diplom\s+ingenieur|fh\s+master|university\s+master)\b",
        # IT
        r"\b(?:laurea\s+magistrale|ingegnere|laurea\s+quinquennale)\b",
        # ES
        r"\b(?:máster|ingeniero|título\s+de\s+ingeniero)\b",
        # NL
        r"\b(?:master|ingenieur|wo\s+master)\b",
    ],
    4: [  # Bac+4 / M1 / Bachelor 4 ans
        # FR
        r"\b(?:bac\s*[+]?\s*4|master\s*1|m1|licence\s*3|bachelor\s*4)\b",
        # EN
        r"\b(?:bachelor'?s?\s+degree|b\.?sc\.?|b\.?a\.?|undergraduate|4th\s+year)\b",
        # DE
        r"\b(?:bachelor|fh\s+bachelor|bakalaus)\b",
        # IT
        r"\b(?:laurea\s+triennale|laurea\b|bachelor)\b",
        # ES
        r"\b(?:grado|bachelor|licenciatura)\b",
        # NL
        r"\b(?:bachelor|hbo|hoger\s+beroepsonderwijs)\b",
    ],
    3: [  # Bac+3 / Licence / Bachelor 3 ans
        # FR
        r"\b(?:bac\s*[+]?\s*3|licence|l3|bachelor\s*3)\b",
        # EN
        r"\b(?:bachelor|b\.?sc|b\.?a|3rd\s+year|undergraduate)\b",
        # DE
        r"\b(?:bachelor|bakalaus)\b",
    ],
}
```

### Champs d'études (field)

```python
_EDUCATION_FIELD_PATTERNS = {
    "Finance": [
        r"\b(?:finance|finances|financial|banking|banque|corporate\s+finance)\b",
    ],
    "Engineering": [
        r"\b(?:ingénieur|engineering|ingenieur|ingegnere|ingeniero|technisch)\b",
    ],
    "Business": [
        r"\b(?:business|management|gestion|commerce|wirtschaft|economia|bedrijfskunde)\b",
    ],
    "Data Science": [
        r"\b(?:data\s+science|data\s+analysis|analyse\s+de\s+données|datenanalyse|analisi\s+dati|análisis\s+de\s+datos|dataanalyse)\b",
    ],
    "Mathematics": [
        r"\b(?:mathématiques|mathematics|matematica|matemáticas|wiskunde|math)\b",
    ],
    "Economics": [
        r"\b(?:économie|economics|wirtschaft|economia|economie)\b",
    ],
    "Law": [
        r"\b(?:droit|law|recht|giurisprudenza|derecho|rechten)\b",
    ],
}
```

---

## Logique d'extraction

```python
def extract_education(text: str, lang: str = "auto") -> list[EducationFact]:
    # 1. Détecter langue
    # 2. Pour chaque level_rank (8→3), tester patterns
    # 3. Premier match = niveau requis (le plus haut trouvé)
    # 4. Chercher field dans même phrase/paragraphe (±200 chars)
    # 5. Si patterns contradictoires (ex: "Bac+3" ET "Master") → contradictions[]
    # 6. Retourner liste EducationFact (généralement 1, max 2 si contradictoire)
```

---

## Gestion cas particuliers

| Cas | Résultat |
|-----|----------|
| "Master ou équivalent" | level_rank=5, confidence="inferred" |
| "Bac+5 (école d'ingénieur ou Master)" | level_rank=5, field="Engineering" ou "Finance" |
| "PhD preferred" | level_rank=8, confidence="inferred" (preferred ≠ required) |
| "Bac+3 minimum, Master apprécié" | 2 faits: required=3, preferred=5, contradictions mutuelles |
| "Diplôme d'ingénieur" | level_rank=5, field="Engineering" |
| "Grande école" | level_rank=5, confidence="inferred" |
| "Équivalent par l'expérience" | confidence="ambiguous", contradictions=["experience_equivalent"] |

---

## Validation

### Fixtures synthétiques (minimum 25)

| Langue | Texte | Attendu |
|--------|-------|---------|
| FR | "Diplôme d'ingénieur ou Master 2 requis" | level_rank=5, field="Engineering" |
| FR | "Bac+5 minimum (Finance, Économie)" | level_rank=5, field="Finance" |
| FR | "Doctorat préféré" | level_rank=8, confidence="inferred" |
| FR | "Bac+3 minimum, Master apprécié" | 2 faits: required=3, preferred=5 |
| EN | "Master's degree in Finance required" | level_rank=5, field="Finance" |
| EN | "PhD or equivalent experience" | level_rank=8, confidence="ambiguous" |
| EN | "Bachelor's degree (4 years)" | level_rank=4 |
| DE | "Masterabschluss (Wirtschaftsingenieur)" | level_rank=5, field="Engineering" |
| DE | "Promotion erwünscht" | level_rank=8, confidence="inferred" |
| IT | "Laurea magistrale in Ingegneria" | level_rank=5, field="Engineering" |
| ES | "Máster en Finanzas requerido" | level_rank=5, field="Finance" |
| NL | "Master diploma (Financiën)" | level_rank=5, field="Finance" |
| FR | "École de commerce (Bac+5)" | level_rank=5, field="Business" |
| FR | "Niveau Bac+4 validé" | level_rank=4 |
| MULTI | "Master required" + "Bachelor accepted" metadata | 2 faits avec contradictions |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_education_extractor.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `extract_education(text: str, lang: str = "auto") -> list[EducationFact]`
- [ ] 6 langues supportées
- [ ] 5 niveaux (3,4,5,6,8) + fields détectés
- [ ] Contradictions required/preferred tracées
- [ ] "Équivalent expérience" géré (ambiguous)
- [ ] 25+ fixtures synthétiques
- [ ] Intégré dans `qualify_offer()` → `evidence["education_required"]`
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK19-EDUCATION_EXTRACTOR.md`

---

## Squelette minimal

```python
# career/cv_quality/education_extractor.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional
import re

@dataclass
class EducationFact:
    fact_type: Literal["education_level_required", "education_field_required"]
    level_rank: int
    level_label: str
    field: Optional[str]
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]

def extract_education(text: str, lang: str = "auto") -> list[EducationFact]:
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk19-education-extractor`, worktree dédié, code, tests (25+ cas multilingues), rapport, push. Je relis et j'intègre.