# MISSION SPEC KIT — SK-17 : Extracteur conditions de travail

> **Priorité : P1** — Après SK-16. Module indépendant, worktree dédié, peut tourner en parallèle SK-16/SK-18/SK-19.

---

## Contexte

**0% conditions** extraites aujourd'hui. Pourtant critiques pour décision candidat : télétravail, horaires, flexibilité, avantages, formation, mobilité.

---

## Module à créer

```
career/cv_quality/conditions_extractor.py
tests/test_conditions_extractor.py
tests/fixtures/conditions_extractor/
```

---

## Contract attendu

```python
@dataclass
class ConditionFact:
    condition_type: Literal[
        "remote",           # télétravail
        "hybrid",           # hybride
        "onsite",           # présentiel
        "flexible_hours",   # horaires flexibles
        "part_time",        # temps partiel
        "benefits",         # avantages (tickets resto, mutuelle, etc.)
        "training",         # formation/budget formation
        "mobility",         # mobilité (vélo, transport, relocation)
        "relocation",       # aide installation
        "visa_sponsorship", # sponsoring visa
    ]
    value: bool | str | int | None  # True/False, "2 days/week", "full", montant, etc.
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]
```

---

## Patterns obligatoires (multilingues FR/EN/DE/IT/ES/NL)

### Télétravail / Remote
```python
_REMOTE_PATTERNS = {
    "remote": [
        # FR
        r"\b(?:télétravail|travail\s+à\s+distance|full\s*remote|100%\s*remote|entièrement\s+à\s+distance)\b",
        # EN
        r"\b(?:remote|work\s+from\s+home|wfh|fully\s+remote|remote-first)\b",
        # DE
        r"\b(?:homeoffice|home\s*office|remote\s*arbeit|vollständig\s+remote)\b",
        # IT
        r"\b(?:lavoro\s+da\s+casa|smart\s*working|full\s*remote|lavoro\s+agile)\b",
        # ES
        r"\b(?:teletrabajo|trabajo\s+remoto|totalmente\s+remoto)\b",
        # NL
        r"\b(?:thuiswerken|volledig\s+remote|remote\s*werken)\b",
    ],
    "hybrid": [
        # FR
        r"\b(?:hybride|télétravail\s+partiel|(\d)\s*jours?\s*(?:par\s+semaine|/semaine)\s*(?:de\s+télétravail|à\s+distance))\b",
        # EN
        r"\b(?:hybrid|(\d)\s*days?\s*(?:per\s+week|/week)\s*(?:remote|wfh|from\s+home))\b",
        # DE
        r"\b(?:hybrid|(\d)\s*tage\s*(?:pro\s+woche|/woche)\s*(?:homeoffice|remote))\b",
        # IT
        r"\b(?:ibrido|(\d)\s*giorni?\s*(?:a\s+settimana|/sett)\s*(?:smart\s*working|da\s+casa))\b",
        # ES
        r"\b(?:híbrido|(\d)\s*días?\s*(?:por\s+semana|/sem)\s*(?:teletrabajo|en\s+remoto))\b",
        # NL
        r"\b(?:hybride|(\d)\s*dagen?\s*(?:per\s+week|/week)\s*(?:thuiswerken|remote))\b",
    ],
    "onsite": [
        r"\b(?:présentiel|on.?site|sur\s+site|büro|in\s+office|in\s+sede|en\s+oficina|op\s+locatie)\b",
    ],
}
```

### Horaires flexibles
```python
_FLEXIBLE_HOURS_PATTERNS = {
    "flexible_hours": [
        r"\b(?:horaires?\s+flexibles?|flexible\s+(?:working\s+)?hours?|flexitime|gleitzeit|orari?\s+flessibili|horario\s+flexible|flexibele\s+werkuren)\b",
        r"\b(?:choix\s+(?:des\s+)?horaires?|choose\s+(?:your\s+)?hours?|selbstbestimmte\s+arbeitszeit)\b",
    ],
    "part_time": [
        r"\b(?:temps\s+partiel|part.?time|teilzeit|part.?time|tijdsdeeltijd)\b",
        r"\b(?:(\d{1,2})\s*h(?:eures?)?\s*(?:par\s+semaine|/sem))\b",
    ],
}
```

### Avantages (Benefits)
```python
_BENEFITS_PATTERNS = {
    "meal_vouchers": [
        r"\b(?:tickets?\s+resto|tickets?\s+restaurant|meal\s+vouchers?|essenszuschuss|buoni\s+pasto|cheques?\s+comida|maaltijdcheques)\b",
    ],
    "health_insurance": [
        r"\b(?:mutuelle|assurance\s+santé|health\s+insurance|krankenversicherung|assicurazione\s+salute|seguro\s+médico|ziekteverzekering)\b",
    ],
    "transport": [
        r"\b(?:remboursement\s+transport|transport\s+allowance|jobticket|fahrtkostenzuschuss|rimborso\s+trasporti|transporte\s+público|vergoeding\s+openbaar\s+vervoer)\b",
    ],
    "equipment": [
        r"\b(?:matériel\s+fourni|equipment\s+provided|arbeitsmittel|attrezzatura\s+fornita|equipo\s+proporcionado|apparatuur\s+geleverd)\b",
    ],
}
```

### Formation / Training
```python
_TRAINING_PATTERNS = {
    "training_budget": [
        r"\b(?:budget\s+formation|training\s+budget|fortbildungsbudget|budget\s+formazione|presupuesto\s+formación|opleidingsbudget)\s*(?:de|:)?\s*(\d+(?:[.,]\d{3})*)\s*[€$£]",
        r"\b(?:formation\s+(?:prise\s+en\s+charge|financée)|paid\s+training|bezahlte\s+fortbildung)\b",
    ],
    "certification_support": [
        r"\b(?:certification\s+(?:payée|financée|sponsorisée)|certification\s+support|zertifizierung|certificazione)\b",
    ],
    "language_training": [
        r"\b(?:cours?\s+de?\s+langues?|language\s+(?:classes?|training)|sprachkurs|corsi?\s+di\s+lingua|clases?\s+de\s+idiomas|taalcursus)\b",
    ],
}
```

### Mobilité / Relocation / Visa
```python
_MOBILITY_PATTERNS = {
    "relocation": [
        r"\b(?:relocation|aide\s+installation|relocation\s+package|umzugshilfe|trasloco|reubicación|verhuizing)\b",
    ],
    "visa_sponsorship": [
        r"\b(?:visa\s+sponsor(?:ship|ed)|sponsor\s+visa|visa\s+support|arbeitserlaubnis|permesso\s+lavoro|permiso\s+trabajo|visum\s+sponsoring)\b",
    ],
    "mobility_budget": [
        r"\b(?:budget\s+mobilité|mobility\s+budget|mobilitätsbudget|budget\s+mobilità|presupuesto\s+movilidad|mobiliteitsbudget)\b",
    ],
}
```

---

## Logique d'extraction

```python
def extract_conditions(text: str, lang: str = "auto") -> list[ConditionFact]:
    # 1. Détecter langue
    # 2. Pour chaque condition_type, tester patterns dans l'ordre priorité
    # 3. Pour hybrid: extraire nombre de jours si pattern capture group
    # 4. Pour benefits: identifier type précis (meal, health, transport, equipment)
    # 5. Calculer offsets, confidence
    # 6. Croiser → contradictions (ex: "remote" ET "onsite" dans même texte)
    # 7. Retourner liste triée par offset
```

---

## Gestion contradictions

| Cas | Résultat |
|-----|----------|
| "Full remote" + "2 days onsite" | 2 faits: remote=True + hybrid=2, contradictions mutuelles |
| "Hybrid 3 days" + "Onsite required" | hybrid=3 + onsite=True, contradictions |
| "Pas de télétravail" | remote=False (explicit) |
| "Flexible" sans précision | flexible_hours=True, confidence="inferred" |

---

## Validation

### Fixtures synthétiques (minimum 25)

| Langue | Texte | Attendu |
|--------|-------|---------|
| FR | "Télétravail 2 jours par semaine" | hybrid=True, value="2 days/week" |
| FR | "Full remote possible" | remote=True |
| FR | "Présentiel obligatoire" | onsite=True |
| FR | "Horaires flexibles, tickets resto, mutuelle" | flexible_hours + meal_vouchers + health_insurance |
| EN | "Hybrid: 3 days from home" | hybrid=True, value="3 days/week" |
| EN | "Remote-first culture" | remote=True |
| EN | "Flexible hours, health insurance, relocation package" | flexible_hours + health_insurance + relocation |
| DE | "Hybrid: 2 Tage Homeoffice" | hybrid=True, value="2 days/week" |
| DE | "Gleitzeit, Jobticket, Fortbildungsbudget 2000€" | flexible_hours + transport + training_budget=2000 |
| IT | "Smart working 3 giorni, buoni pasto" | hybrid=3 + meal_vouchers |
| ES | "Teletrabajo total, horario flexible" | remote=True + flexible_hours |
| NL | "Thuiswerken 1 dag, maaltijdcheques" | hybrid=1 + meal_vouchers |
| FR | "Pas de télétravail, sur site 5j/7" | remote=False + onsite=True |
| MULTI | "Remote" dans description, "Onsite" dans metadata | 2 faits avec contradictions |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_conditions_extractor.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `extract_conditions(text: str, lang: str = "auto") -> list[ConditionFact]`
- [ ] 6 langues supportées
- [ ] 10+ condition_type extraits
- [ ] Hybrid extrait nombre de jours
- [ ] Benefits typés (meal, health, transport, equipment)
- [ ] Formation : budget + certification + langues
- [ ] Mobilité : relocation, visa, budget mobilité
- [ ] Contradictions détectées et tracées
- [ ] 25+ fixtures synthétiques
- [ ] Intégré dans `qualify_offer()` → `evidence["conditions"]`
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK17-CONDITIONS_EXTRACTOR.md`

---

## Squelette minimal

```python
# career/cv_quality/conditions_extractor.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional
import re

@dataclass
class ConditionFact:
    condition_type: Literal[
        "remote", "hybrid", "onsite", "flexible_hours", "part_time",
        "meal_vouchers", "health_insurance", "transport", "equipment",
        "training_budget", "certification_support", "language_training",
        "relocation", "visa_sponsorship", "mobility_budget"
    ]
    value: Optional[bool | str | int]
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]

def extract_conditions(text: str, lang: str = "auto") -> list[ConditionFact]:
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk17-conditions-extractor`, worktree dédié, code, tests (25+ cas multilingues), rapport, push. Je relis et j'intègre.