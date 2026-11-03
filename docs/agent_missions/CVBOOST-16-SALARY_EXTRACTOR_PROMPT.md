# MISSION AGENT — Mission 16 : Extracteur rémunération offres (Parser CV/Offres)

> **Contexte** : Les résumés d'offres n'affichent **jamais** la rémunération (0% actuellement). Il faut extraire le salaire/package depuis `description_original` avec provenance exacte.
> Base : `main` (1469 tests verts). **Dépendance : Mission 01** (`cv_quality.parser`) — **satisfaite**.

---

## Périmètre autorisé

| Fichier | Rôle |
|---|---|
| `career/cv_quality/parser.py` | **Étendre** — ajouter `extract_salary(text) -> list[SalaryEvidence]` |
| `career/cv_quality/models.py` | **Étendre** — `SalaryEvidence`, `Currency`, `SalaryType` |
| `career/cv_quality/__init__.py` | Exporter `extract_salary` |
| `tests/test_salary_extractor.py` | **Nouveau** — tests synthétiques (≥ 15 cas) |
| `docs/agent-reports/CVBOOST-16-SALARY.md` | Rapport obligatoire |

**Interdit** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`.

---

## Contraintes produit (non négociables)

1. **Fonction pure** : `extract_salary(text: str) -> list[SalaryEvidence]` — déterministe, sans réseau, sans LLM.
2. **Provenance EXACTE** : chaque `SalaryEvidence` porte `source_offset` (index dans le texte) + `source_excerpt` (50 chars autour).
3. **Patterns couverts** (FR/EN) :
   - Montants : `45 000 €`, `45k€`, `45K`, `50 000 EUR`, `$60,000`, `£40,000`, `¥6,000,000`
   - Fourchettes : `45-55k€`, `50k-60k €`, `entre 40k et 50k`, `40k–60k`
   - Types : `brut annuel`, `net mensuel`, `package`, `total compensation`, `CTC`, `base salary`, `variable`, `bonus`, `stock options`, `RSU`, `equity`
   - Périodicité : `par an`, `par an / an`, `/an`, `/année`, `mensuel`, `par mois`, `/mois`
   - Mots-clés : `salaire`, `rémunération`, `rémunération annuelle`, `package`, `compensation`, `package complet`, `salary`, `compensation`, `package`, `base`, `variable`, `bonus`, `stock`, `equity`, `RSU`
4. **Zéro invention** : si rien trouvé → liste vide. JAMAIS de valeur par défaut.
5. **Normalisation** : sortie en `SalaryEvidence` normalisée (montant min/max en EUR annuel, type, périodicité, devise).
6. **Performance** : ≤ 5 ms par texte (≤ 50k chars).

---

## Modèles de données

```python
# career/cv_quality/models.py — AJOUT
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class SalaryEvidence:
    raw_text: str                    # Extrait exact du texte (ex: "45 000 € brut annuel")
    source_offset: int               # Position dans le texte source
    source_excerpt: str              # 50 chars autour
    min_annual_eur: Optional[float]  # Minimum normalisé en EUR/an
    max_annual_eur: Optional[float]  # Maximum normalisé en EUR/an
    currency: str                    # "EUR", "USD", "GBP", "JPY", etc.
    salary_type: Literal["base", "variable", "bonus", "stock", "equity", "rsu", "package", "total", "unknown"]
    periodicity: Literal["annual", "monthly", "hourly", "unknown"]
    raw_amount_text: str             # "45 000 €", "50k", "$60,000", etc.
    raw_period_text: str             # "brut annuel", "par an", "mensuel", etc.
    confidence: float                # 0.0-1.0
```

---

## Patterns regex de base (à affiner)

```python
SALARY_PATTERN = re.compile(
    r"""
    (?:
        (?P<amount>\d{1,3}(?:[ ,\.]\d{3})*(?:[,\.]\d+)?)\s*
        (?P<unit>k|K|m|M)?\s*
        (?P<currency>€|EUR|eur|\$|USD|£|GBP|¥|JPY|CHF|CHF)
    |
        (?P<currency_symbol>[€$£¥])\s*
        (?P<amount2>\d{1,3}(?:[ ,\.]\d{3})*(?:[,\.]\d+)?)\s*
        (?P<unit2>k|K|m|M)?
    )
    \s*
    (?P<period>(?:brut\s+)?(?:an(?:nuel)?|an|année|an|mensuel|mois|/an|/an|/année|/mois|par\s+an|par\s+année|per\s+year|per\s+annum|/yr|/year|/month|mensuel))?
    \s*
    (?P<type>(?:brut|net|base|variable|bonus|stock|equity|rsu|package|total|compensation|compensation\s+package|ctc))?
    """,
    re.IGNORECASE | re.VERBOSE
)

# Normalisation devise
CURRENCY_MAP = {
    "€": "EUR", "eur": "EUR", "EUR": "EUR",
    "$": "USD", "usd": "USD", "USD": "USD",
    "£": "GBP", "gbp": "GBP", "GBP": "GBP",
    "¥": "JPY", "jpy": "JPY", "JPY": "JPY",
    "CHF": "CHF", "chf": "CHF",
}

# Conversion k/M
def normalize_amount(amount_str: str, unit: str | None) -> float:
    val = float(amount_str.replace(" ", "").replace(",", "."))
    if unit and unit.upper() == "K":
        val *= 1_000
    elif unit and unit.upper() == "M":
        val *= 1_000_000
    return val

# Annualisation
def to_annual(amount: float, periodicity: str) -> float:
    if periodicity in ("monthly", "mensuel", "/mois", "per month"):
        return amount * 12
    return amount  # déjà annuel par défaut
```

---

## Tests obligatoires (≥ 20)

| Test | Description |
|---|---|
| `test_salary_simple_eur` | "45 000 € brut annuel" → min=45000, max=45000, EUR, annual |
| `test_salary_k_eur` | "55k€" → min=55000, max=55000, EUR, annual |
| `test_salary_range` | "45-55k€" → min=45000, max=55000 |
| `test_salary_range_spaces` | "50 k - 60 k €" → min=50000, max=60000 |
| `test_salary_usd` | "$80,000 per year" → min=80000, max=80000, USD |
| `test_salary_gbp` | "£45,000 per annum" → min=45000, max=45000, GBP |
| `test_salary_monthly` | "4 500 € mensuel" → min=54000, max=54000 (annualisé) |
| `test_salary_k` | "50k" → min=50000, max=50000 |
| `test_salary_package` | "Package 70k€ brut annuel" → type="package" |
| `test_salary_bonus` | "Bonus 10k€" → type="bonus" |
| `test_salary_equity` | "RSU 5000 units" → type="rsu" / "equity" |
| `test_salary_variable` | "Variable 20%" → type="variable" |
| `test_french_expressions` | "entre 40k et 50k€" → min=40000, max=50000 |
| `test_english_expressions` | "between 50k and 60k" → min=50000, max=60000 |
| `test_no_salary` | "Pas de salaire mentionné" → [] |
| `test_multiple_salaries` | "Base 50k€ + bonus 10k€" → 2 evidences |
| `test_k_m_suffix` | "1.5M€" → 1_500_000 |
| `test_stock_options` | "Stock options 1000 shares" → type="stock" |
| `test_rsu` | "RSU 2000 units vesting 4 ans" → type="rsu" |
| `test_confidence_scoring` | Match clair → confidence > 0.8 ; ambigu → < 0.5 |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_salary_extractor.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de validation (relecteur)

- [ ] `extract_salary()` pure, déterministe, sans réseau
- [ ] ≥ 20 tests passent (précision/rappel sur corpus synthétique)
- [ ] Provenance exacte (`source_offset`, `source_excerpt`) sur chaque evidence
- [ ] Normalisation EUR annuel correcte (k, M, mensuel→annuel, devises)
- [ ] Types détectés : base, variable, bonus, stock, equity, rsu, package
- [ ] Zéro invention (liste vide si rien trouvé)
- [ ] Ruff clean, 1469+ tests passent, `git diff --check` propre
- [ ] Rapport `CVBOOST-16-SALARY.md` avec exemples extraction

---

## Squelette minimal (copier-coller)

```python
# career/cv_quality/parser.py — AJOUT
import re
from career.cv_quality.models import SalaryEvidence

SALARY_PATTERN = re.compile(r"...", re.IGNORECASE | re.VERBOSE)

def extract_salary(text: str) -> list[SalaryEvidence]:
    evidences = []
    for match in SALARY_PATTERN.finditer(text):
        # extraire groupes, normaliser, créer SalaryEvidence
        evidences.append(SalaryEvidence(...))
    return evidences
```

---

**Tu as tout. Lance-toi.** Branche `agent/cvboost-16-salary-extractor`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre. **Mission critique pour l'exhaustivité des offres (R2).**