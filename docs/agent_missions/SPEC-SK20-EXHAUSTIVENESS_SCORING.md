# MISSION SPEC KIT — SK-20 : Score exhaustivité par offre

> **Priorité : P1** — Après SK-16/SK-17/SK-18/SK-19. Agrège les 4 extracteurs en score unique affiché dans Stage Hunter.

---

## Contexte

Aujourd'hui : exhaustivité moyenne offres ~11.7%. Objectif : >60%.
Chaque offre doit avoir un badge "Exhaustivité XX%" + détails manquants.

---

## Module à créer

```
career/offer_exhaustiveness.py
tests/test_offer_exhaustiveness.py
tests/fixtures/offer_exhaustiveness/
```

---

## Contract attendu

```python
@dataclass
class ExhaustivenessScore:
    overall_score: int              # 0-100
    breakdown: dict[str, int]       # {"salary": 25, "conditions": 20, "missions": 30, "education": 15, "dates": 10}
    missing: list[str]              # ["salary", "conditions", "education_level"]
    present: list[str]              # ["missions", "dates", "contract_type"]
    badge_label: str                # "Exhaustivité 85%" / "Rémunération : non communiquée"
    badge_color: Literal["green", "orange", "red", "gray"]
```

### Pondération (somme = 100)

| Composant | Poids | Critère "present" |
|-----------|-------|-------------------|
| **Missions** | 30 | ≥1 mission extraite (SK-18) |
| **Rémunération** | 25 | ≥1 salary_fact (SK-16) |
| **Conditions** | 20 | ≥1 condition_fact (SK-17) |
| **Niveau études** | 15 | ≥1 education_fact (SK-19) |
| **Dates/Durée** | 10 | start_date OU duration_min OU deadline (SK-02) |

---

## Logique de scoring

```python
def compute_exhaustiveness(job: dict[str, Any]) -> ExhaustivenessScore:
    # 1. Vérifier chaque composant via evidence dans job["qualification"]["provenance"]
    #    OU relancer extracteurs si pas encore fait
    
    breakdown = {}
    missing = []
    present = []
    
    # Missions (30)
    missions = job.get("qualification", {}).get("provenance", {}).get("missions")
    if missions and missions.value:
        breakdown["missions"] = 30
        present.append("missions")
    else:
        breakdown["missions"] = 0
        missing.append("missions")
    
    # Salaire (25)
    salary = job.get("qualification", {}).get("provenance", {}).get("salary")
    if salary and salary.value:
        breakdown["salary"] = 25
        present.append("salary")
    else:
        breakdown["salary"] = 0
        missing.append("salary")
    
    # Conditions (20)
    conditions = job.get("qualification", {}).get("provenance", {}).get("conditions")
    if conditions and conditions.value:
        breakdown["conditions"] = 20
        present.append("conditions")
    else:
        breakdown["conditions"] = 0
        missing.append("conditions")
    
    # Education (15)
    education = job.get("qualification", {}).get("provenance", {}).get("education_required")
    if education and education.value:
        breakdown["education"] = 15
        present.append("education")
    else:
        breakdown["education"] = 0
        missing.append("education")
    
    # Dates (10)
    has_dates = any([
        job.get("start_date"),
        job.get("qualification", {}).get("duration_min_months"),
        job.get("deadline_date"),
    ])
    if has_dates:
        breakdown["dates"] = 10
        present.append("dates")
    else:
        breakdown["dates"] = 0
        missing.append("dates")
    
    overall = sum(breakdown.values())
    
    # Badge
    if overall >= 70:
        badge_label = f"Exhaustivité {overall}%"
        badge_color = "green"
    elif overall >= 40:
        badge_label = f"Exhaustivité {overall}%"
        badge_color = "orange"
    elif overall > 0:
        badge_label = f"Exhaustivité {overall}%"
        badge_color = "red"
    else:
        badge_label = "Exhaustivité 0% — offre vide"
        badge_color = "gray"
    
    # Complément : si salaire manquant, mention spécifique
    if "salary" in missing:
        badge_label += " | Rémunération : non communiquée"
    
    return ExhaustivenessScore(
        overall_score=overall,
        breakdown=breakdown,
        missing=missing,
        present=present,
        badge_label=badge_label,
        badge_color=badge_color,
    )
```

---

## Intégration dans `offer_qualification.py`

```python
# Dans qualify_offer(), après tous les extracteurs:
from career.offer_exhaustiveness import compute_exhaustiveness

exhaustiveness = compute_exhaustiveness(job_with_all_evidence)
evidence["exhaustiveness"] = FactEvidence(
    exhaustiveness.overall_score, "exhaustiveness_scorer", 
    f"Missions:{breakdown['missions']} Salaire:{breakdown['salary']} Conditions:{breakdown['conditions']} Education:{breakdown['education']} Dates:{breakdown['dates']}"
)

# Ajouter au QualifiedOffer
return QualifiedOffer(
    ...,
    exhaustiveness_score=exhaustiveness.overall_score,
    exhaustiveness_breakdown=exhaustiveness.breakdown,
    exhaustiveness_missing=exhaustiveness.missing,
    exhaustiveness_badge=exhaustiveness.badge_label,
    exhaustiveness_badge_color=exhaustiveness.badge_color,
)
```

---

## UI Stage Hunter (badge)

```javascript
// career_static/career.js
function renderExhaustivenessBadge(score) {
    const colors = {
        green: "bg-green-100 text-green-800 border-green-300",
        orange: "bg-orange-100 text-orange-800 border-orange-300",
        red: "bg-red-100 text-red-800 border-red-300",
        gray: "bg-gray-100 text-gray-600 border-gray-300",
    };
    return `<span class="px-2 py-1 rounded text-xs font-medium border ${colors[score.badge_color]}">
        ${score.badge_label}
    </span>`;
}
```

---

## Validation

### Fixtures synthétiques (minimum 15)

| Offre type | Missions | Salaire | Conditions | Education | Dates | Score | Badge |
|------------|----------|---------|------------|-----------|-------|-------|-------|
| Complète | ✅ | ✅ | ✅ | ✅ | ✅ | 100 | Vert "100%" |
| Standard finance | ✅ | ❌ | ✅ | ✅ | ✅ | 75 | Vert "75% | Rémunération: non communiquée" |
| Greenhouse brute | ❌ | ❌ | ❌ | ❌ | ❌ | 0 | Gris "0% — offre vide" |
| Description riche | ✅ | ✅ | ❌ | ❌ | ✅ | 65 | Orange "65%" |
| Seulement titre | ❌ | ❌ | ❌ | ❌ | ❌ | 0 | Gris |
| Missions + dates | ✅ | ❌ | ❌ | ❌ | ✅ | 40 | Orange "40%" |

### Test mesure globale

```python
def test_measure_exhaustiveness():
    # Charger 100 offres réelles
    # Calculer score pour chacune
    # Assert moyenne > 60
    scores = [compute_exhaustiveness(job).overall_score for job in real_jobs]
    avg = sum(scores) / len(scores)
    assert avg > 60, f"Exhaustivité moyenne {avg:.1f}% < 60%"
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_offer_exhaustiveness.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `compute_exhaustiveness(job) -> ExhaustivenessScore`
- [ ] Pondération exacte : missions=30, salaire=25, conditions=20, education=15, dates=10
- [ ] Badge label + couleur selon seuils (70/40/0)
- [ ] Mention "Rémunération : non communiquée" si salaire manquant
- [ ] Intégré dans `QualifiedOffer` + `provenance`
- [ ] 15+ fixtures synthétiques
- [ ] Script `measure_exhaustiveness.py` valide > 60% sur corpus réel
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK20-EXHAUSTIVENESS_SCORING.md`

---

## Squelette minimal

```python
# career/offer_exhaustiveness.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass
class ExhaustivenessScore:
    overall_score: int
    breakdown: dict[str, int]
    missing: list[str]
    present: list[str]
    badge_label: str
    badge_color: Literal["green", "orange", "red", "gray"]

def compute_exhaustiveness(job: dict[str, Any]) -> ExhaustivenessScore:
    ...

def measure_corpus_exhaustiveness(jobs: list[dict[str, Any]]) -> float:
    """Retourne score moyen sur corpus."""
    if not jobs:
        return 0.0
    return sum(compute_exhaustiveness(j).overall_score for j in jobs) / len(jobs)
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk20-exhaustiveness-scoring`, worktree dédié, code, tests (15+ fixtures + mesure corpus), rapport, push. Je relis et j'intègre.