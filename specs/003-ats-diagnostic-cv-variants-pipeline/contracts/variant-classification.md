# Contract: CV Variant Classification

**Feature**: 003-ats-diagnostic-cv-variants-pipeline
**Version**: 1.0
**Date**: 2026-10-21

---

## Function Signature

```python
def classify_variant(
    job: dict,                                    # Offer from jobs table + qualification
    profile: dict,                                # Approved candidate_profile
    variants: tuple[CVVariant, ...]               # All defined variants
) -> VariantClassificationResult:
```

---

## Input: `job` dict

```json
{
  "id": "str",
  "job_family": "str",                            // e.g., "M&A / Investment Banking", "Markets / Quant", "Corporate Finance / FP&A"
  "title": "str",                                 // Offer title
  "requirements": "str",                          // Raw requirements text
  "qualification": {                              // From qualify_offer()
    "target_status": "str",
    "missing_fields": ["str", ...],
    "provenance": {                               // FactEvidence per field
      "contract_type": {"value": "internship", "source": "description_passage", "quote": "Stage de 6 mois"},
      "start_date": {"value": "2027-01-01", "source": "description_passage", "quote": "Début janvier 2027"}
    }
  }
}
```

---

## Input: `profile` dict

```json
{
  "skills": "str",                                // Free text
  "experience": "str",                            // Free text (chronological)
  "education": "str",
  "languages": "str",
  "projects": "str"
}
```

---

## Output: `VariantClassificationResult`

```python
@dataclass(frozen=True)
class VariantClassificationResult:
    primary_variant: CVVariant                    # Best-match variant
    scores: dict[str, float]                      # variant_id -> 0.0-1.0 score
    rationale: str                                # Human-readable explanation
```

**JSON Serialization**:
```json
{
  "primary_variant": "m_a",
  "scores": {"m_a": 0.82, "markets": 0.45, "corporate_finance": 0.31},
  "rationale": "job_family 'M&A / Investment Banking' exact match (+0.50); 4/5 mandatory keywords in requirements (+0.40); 3 quantified experiences match M&A themes (+0.15); total 1.05 → capped at 1.0"
}
```

---

## Scoring Algorithm (Deterministic)

```python
def score_variant(variant: CVVariant, job: dict, profile: dict) -> float:
    score = 0.0

    # 1. Job family exact match (highest signal)
    if variant.id in JOB_FAMILY_TO_VARIANT.get(job.get("job_family", ""), []):
        score += 0.50

    # 2. Mandatory keyword overlap in requirements
    req_text = (job.get("requirements") or "").lower()
    kw_hits = sum(1 for kw in variant.mandatory_keywords if kw.lower() in req_text)
    score += min(0.40, kw_hits * 0.10)            # Max 0.40 for 4+ keywords

    # 3. Quantified profile experience matching variant themes
    exp_text = (profile.get("experience") or "").lower()
    theme_hits = sum(1 for kw in variant.mandatory_keywords if kw.lower() in exp_text)
    score += min(0.15, theme_hits * 0.05)         # Max 0.15 for 3+ themes

    # 4. Qualification provenance alignment
    prov = job.get("qualification", {}).get("provenance", {})
    if any(variant.id in str(v).lower() for v in prov.values()):
        score += 0.05

    return min(1.0, score)
```

**JOB_FAMILY_TO_VARIANT Mapping**:
```python
JOB_FAMILY_TO_VARIANT = {
    "M&A / Investment Banking": ["m_a"],
    "Investment Banking": ["m_a"],
    "M&A": ["m_a"],
    "Markets / Quant": ["markets"],
    "Sales & Trading": ["markets"],
    "Quantitative Research": ["markets"],
    "Corporate Finance / FP&A": ["corporate_finance"],
    "FP&A": ["corporate_finance"],
    "Financial Planning": ["corporate_finance"],
    "Treasury": ["corporate_finance"],
}
```

---

## Tie-Breaking Rules

1. Higher score wins
2. If scores equal within 0.01: prefer variant with higher **mandatory coverage** (computed separately)
3. If still tied: prefer `m_a` > `markets` > `corporate_finance` (deterministic default)

---

## Error Handling

| Condition | Behavior |
|-----------|----------|
| `job` missing `job_family` | Score all variants on keywords only (no 0.50 bonus) |
| `job` missing `requirements` | Score on job_family + profile only |
| `profile` empty | Score on job_family + requirements only |
| All scores == 0.0 | Return `m_a` with rationale "Aucun signal fort ; défaut M&A" |

---

## Test Contract (Pytest)

```python
def test_classification_ma_exact_match():
    job = {"job_family": "M&A / Investment Banking", "requirements": "financial modeling valuation LBO M&A", "qualification": {"provenance": {}}}
    profile = {"experience": "Built LBO models at SMBC", "skills": "Excel valuation"}
    result = classify_variant(job, profile, ALL_VARIANTS)
    assert result.primary_variant.id == "m_a"
    assert result.scores["m_a"] > 0.8

def test_classification_markets_keywords():
    job = {"job_family": "Other", "requirements": "Python statistics Bloomberg quantitative research", "qualification": {"provenance": {}}}
    profile = {"experience": "Python pandas time series analysis", "skills": "Python statistics"}
    result = classify_variant(job, profile, ALL_VARIANTS)
    assert result.primary_variant.id == "markets"

def test_classification_tie_break_coverage():
    # Two variants with equal score → higher mandatory coverage wins
    pass
```

---

*Contract complete. Implementation in `career/cv_fit.py::classify_variant`.*
