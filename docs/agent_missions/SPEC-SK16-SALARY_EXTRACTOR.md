# MISSION SPEC KIT — SK-16 : Extracteur rémunération offres

> **Priorité : P1** — Après SK-11/SK-13/SK-14. Module indépendant, worktree dédié.

---

## Contexte

`summarize_offer()` dans `application_prep.py` n'a que 7 champs → **0% rémunération**. Les offres Greenhouse n'ont souvent pas de champ `salary` structuré, mais le texte contient souvent "€45k", "package 55k€", "rémunération 40-50k€", "£35k per annum".

**Objectif** : Extracteur regex multilingue + evidence excerpt, réutilisant `cv_quality.parser`.

---

## Module à créer

```
career/cv_quality/salary_extractor.py
tests/test_salary_extractor.py
tests/fixtures/salary_extractor/
```

---

## Règles non négociables

1. **Réutilise `cv_quality.parser`** — pas de duplication logique
2. **Patterns multilingues** : FR, EN, DE, IT, ES, NL
3. **Sortie structurée** : min, max, currency, period, confidence, quote, offsets
4. **Zéro invention** : si pas trouvé → `None`, jamais de default
5. **Différencier** : salaire brut/net, package (avec bonus), fourchette, plafond
6. **Confidence** : `explicit` (champ structuré), `inferred` (description), `ambiguous` (contradictoire)

---

## Contract attendu

```python
@dataclass
class SalaryFact:
    fact_type: Literal["salary_min", "salary_max", "salary_range", "salary_package"]
    currency: Literal["EUR", "GBP", "USD", "CHF", "PLN", "CZK", "HUF", "RON", "SEK", "NOK", "DKK"]
    period: Literal["annual", "monthly", "hourly", "unknown"]
    gross_net: Literal["gross", "net", "unknown"]
    value_min: int | None      # en unités de base (ex: 45000 pour 45k€ annuel)
    value_max: int | None
    value_exact: int | None
    source_field: str          # "description_original", "requirements", "metadata.salary"
    quote: str                 # excerpt verbatim
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]
```

---

## Patterns obligatoires (multilingues)

### Français
```python
_SALARY_PATTERNS_FR = [
    # Explicite annuel
    (r"(?:rémunération|salaire|package|rémunération\s+annuelle?)\s*(?:de|:)?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*[kK]?\s*[€$£]", "annual"),
    # Fourchette
    (r"(?:entre|de)\s*(\d{1,3}(?:[.,]\d{3})*)\s*(?:à|et|-|–)\s*(\d{1,3}(?:[.,]\d{3})*)\s*[kK]?\s*[€$£]", "annual"),
    # k€ notation
    (r"(\d{1,2}(?:[.,]\d)?)\s*[kK]\s*[€$£]", "annual_k"),
    # Mensuel
    (r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*[€$£]\s*(?:par\s+mois|/mois|mensuel)", "monthly"),
]
```

### Anglais
```python
_SALARY_PATTERNS_EN = [
    (r"(?:salary|compensation|package|base\s+pay)\s*(?:of|:)?\s*(?:£|€|\$)?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*[kK]?(?:\s*(?:per\s+year|per\s+annum|annually|pa))?", "annual"),
    (r"(?:£|€|\$)\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*[kK]?(?:\s*(?:per\s+year|pa))?", "annual"),
    (r"(\d{1,2}(?:[.,]\d)?)\s*[kK]\s*(?:£|€|\$)", "annual_k"),
    (r"(?:from|up\s+to)\s*(?:£|€|\$)?\s*(\d{1,3}(?:[.,]\d{3})*)\s*[kK]?", "range"),
]
```

### Allemand / Italien / Espagnol / Néerlandais
```python
# DE: "Gehalt", "Vergütung", "Jahresgehalt", "Monatsgehalt", "k€", "Tsd. €"
# IT: "retribuzione", "stipendio", "RAL", "package", "k€"
# ES: "salario", "remuneración", "paquete", "bruto anual", "k€"
# NL: "salaris", "beloning", "jaarsalaris", "maandsalaris", "k€"
```

---

## Normalisation valeurs

```python
def _normalize_salary_value(raw: str, notation: str) -> int:
    """Convertit '45', '45.5', '45,5', '45k' → entier en unités de base."""
    raw = raw.replace(",", ".")
    val = float(raw)
    if notation == "annual_k":
        return int(val * 1000)
    return int(val)
```

---

## Gestion contradictions

```python
# Si description dit "45k€" et metadata dit "55k€" → les deux faits avec contradictions[]
# Si "up to 60k" + "at least 40k" → salary_min=40000, salary_max=60000
# Si "package 70k" (inclut bonus) → fact_type="salary_package", gross_net="unknown"
```

---

## Intégration dans `offer_qualification.py`

```python
# Dans qualify_offer(), après extraction dates/durée:
from career.cv_quality.salary_extractor import extract_salary

salary_facts = extract_salary(job.get("description_original", ""), job.get("requirements", ""))
if salary_facts:
    evidence["salary"] = FactEvidence(salary_facts, "salary_extractor", salary_facts[0].quote)
    # Ajouter aux missing_fields si absent
```

---

## Validation

### Fixtures synthétiques (minimum 30)

| Langue | Texte source | Attendu |
|--------|--------------|---------|
| FR | "Rémunération : 45k€ brut annuel" | salary_min=45000, currency=EUR, period=annual, gross_net=gross |
| FR | "Package 55k€ (fixe + variable)" | salary_package=55000, gross_net=unknown |
| FR | "Entre 40k€ et 50k€ selon profil" | salary_min=40000, salary_max=50000 |
| FR | "Salaire : 3500€ brut/mois" | salary_min=42000 (annualisé), period=monthly |
| EN | "Salary: £35,000 per annum" | salary_min=35000, currency=GBP |
| EN | "Compensation package: $60k base + bonus" | salary_package=60000, currency=USD |
| EN | "Up to €55k annually" | salary_max=55000 |
| EN | "At least £40k pa" | salary_min=40000 |
| DE | "Jahresgehalt: 50.000 € brutto" | salary_min=50000, currency=EUR, gross_net=gross |
| DE | "Vergütung: 4.200 € monatlich" | salary_min=50400 (annualisé) |
| IT | "RAL: 42k€" | salary_min=42000 |
| ES | "Salario bruto anual: 38.000 €" | salary_min=38000 |
| NL | "Jaarsalaris: € 45.000" | salary_min=45000 |
| FR | "Rémunération non communiquée" | None |
| FR | "Selon profil et expérience" | None |
| MULTI | "45k€ (description) vs 55k€ (metadata)" | 2 faits avec contradictions mutuelles |

### Pièges obligatoires (ZÉRO tolérance)

| Piège | Règle |
|-------|-------|
| "2 ans d'expérience" | **Jamais** salary → ignorer |
| "Négociable" | `confidence="ambiguous"`, value=None |
| "Selon profil" | `confidence="ambiguous"`, value=None |
| "Package complet" sans chiffre | None |
| "k" sans devise | `currency="unknown"` |
| Contradictoire structuré vs description | Les deux faits, `contradictions` mutuelles |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_salary_extractor.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `extract_salary(text: str, lang: str = "auto") -> list[SalaryFact]`
- [ ] 6 langues supportées (FR/EN/DE/IT/ES/NL)
- [ ] 6 pattern types (min, max, range, package, monthly, hourly)
- [ ] Chaque fait a offsets exacts, quote, confidence, contradictions
- [ ] 30+ fixtures synthétiques couvrant tous patterns + pièges
- [ ] Intégré dans `qualify_offer()` → `evidence["salary"]`
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK16-SALARY_EXTRACTOR.md`

---

## Squelette minimal

```python
# career/cv_quality/salary_extractor.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional
import re

@dataclass
class SalaryFact:
    fact_type: Literal["salary_min", "salary_max", "salary_range", "salary_package"]
    currency: Literal["EUR", "GBP", "USD", "CHF", "PLN", "CZK", "HUF", "RON", "SEK", "NOK", "DKK", "unknown"]
    period: Literal["annual", "monthly", "hourly", "unknown"]
    gross_net: Literal["gross", "net", "unknown"]
    value_min: Optional[int]
    value_max: Optional[int]
    value_exact: Optional[int]
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]

def extract_salary(text: str, requirements: str = "", lang: str = "auto") -> list[SalaryFact]:
    # 1. Détecter langue (ou utiliser lang fourni)
    # 2. Concaténer text + requirements
    # 3. Patterns regex par langue
    # 4. Pour chaque match: normaliser, calculer offsets, déterminer confidence
    # 5. Croiser faits → contradictions[]
    # 6. Retourner liste SalaryFact triée par offset
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk16-salary-extractor`, worktree dédié, code, tests (30+ cas multilingues), rapport, push. Je relis et j'intègre.