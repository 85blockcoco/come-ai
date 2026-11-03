# MISSION SPEC KIT — SK-02 : Dates, échéances et durées avec preuves

> **Priorité : P0 — Meilleure prochaine mission** — Module indépendant, worktree dédié, peut tourner en parallèle SK-01/SK-03/SK-04

---

## Contexte

Plusieurs connecteurs fournissent des dates vides. L'analyseur existant ne sépare pas publication / deadline / début / fin / durée. Il faut un **analyseur temporel multilingue** avec preuves exactes.

---

## Nouveau module à créer

```
career/offer_dates.py
tests/test_offer_dates.py
tests/fixtures/offer_dates/
```

---

## Langues minimales
- Français
- Anglais
- Allemand
- Italien
- Espagnol

---

## Types de faits à extraire (fact_type)

| fact_type | Sémantique |
|-----------|------------|
| `published` | Date de publication |
| `deadline` | Date limite candidature |
| `start` | Date/mois de début |
| `end` | Date de fin |
| `duration_exact` | Durée exacte |
| `duration_min` | Durée minimale ("at least") |
| `duration_max` | Durée maximale ("up to") |
| `duration_range` | Intervalle ("3 to 6 months") |

---

## Contrat attendu par fait

```json
{
  "fact_type": "start",
  "value": { "month": 1, "year": 2027, "day": null },
  "precision": "month",
  "source_field": "description_original",
  "quote": "Starting January 2027",
  "start_offset": 312,
  "end_offset": 333,
  "confidence": "confirmed",
  "contradictions": []
}
```

- `precision`: `day` | `month` | `year` | `unknown`
- `confidence`: `confirmed` | `inferred` | `ambiguous`
- `contradictions`: liste d'autres faits contradictoires

---

## Pièges obligatoires (ZÉRO tolérance)

| Piège | Règle |
|-------|-------|
| "Apply by 15 November" | **Jamais** date de début → `deadline` |
| "Starting January" | **Jamais** 1er janvier → `start` precision=month, day=null |
| "Up to six months" | **Maximum**, pas durée minimale → `duration_max` |
| "At least six months" | **Minimum** → `duration_min` |
| "Three to six months" | **Intervalle** → `duration_range` |
| "Two years of prior experience" | **Jamais** durée contrat → ignorer ou `contradiction` |
| Date numérique ambiguë (01/02/2025) | `ambiguous`, `contradictions` si jour/mois inversable |
| Publication + échéance même phrase | **Séparées** en deux faits distincts |
| Mois sans année | `precision: "month"`, `value.year: null`, `confidence: "inferred"` |
| Deux sources contradictoires | Les deux faits avec `contradictions` mutuelles |

---

## Mesures obligatoires

- Zéro échéance seule classée comme début
- Zéro borne maximale utilisée comme preuve de durée minimale
- ≥ 95% faits explicitement libellés correctement classés
- Tous autres cas = `unknown` ou `contradictory`
- **Aucun jour inventé** (day=null si non explicite)

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_offer_dates.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `offer_dates.extract_dates(text: str, lang: str, source_field: str) -> list[DateFact]` pure, déterministe
- [ ] 5 langues supportées (FR/EN/DE/IT/ES)
- [ ] 8 fact_type extraits
- [ ] Chaque fait a offsets exacts, quote, precision, confidence, contradictions
- [ ] Fixtures synthétiques: 50+ cas couvrant tous pièges obligatoires
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK02-OFFER_DATES.md`

---

## Squelette minimal

```python
# career/offer_dates.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class DateFact:
    fact_type: Literal["published", "deadline", "start", "end",
                       "duration_exact", "duration_min", "duration_max", "duration_range"]
    value: dict  # selon fact_type: {"day":int,"month":int,"year":int} ou {"months_min":int,"months_max":int}
    precision: Literal["day", "month", "year", "unknown"]
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["confirmed", "inferred", "ambiguous"]
    contradictions: list[str]

def extract_dates(text: str, lang: str, source_field: str = "description_original") -> list[DateFact]:
    # 1. Détecter langue (ou utiliser lang fourni)
    # 2. Patterns regex par langue pour chaque fact_type
    # 3. Pour chaque match: extraire valeur, calculer offsets, déterminer precision/confidence
    # 4. Croiser avec autres faits détectés -> contradictions[]
    # 5. Retourner liste DateFact triée par offset
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk02-offer-dates`, worktree dédié, code, tests (50+ cas multilingues), rapport, push. Je relis et j'intègre. **Mission à plus forte valeur immédiate.**