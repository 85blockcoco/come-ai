# Data Model: Connect ATS Diagnostics to Targeted CV Variants Pipeline

**Feature**: 003-ats-diagnostic-cv-variants-pipeline
**Date**: 2026-10-21

---

## Entities

### 1. CVVariant (`career/cv_variants.py`)

```python
from dataclasses import dataclass
from typing import Literal, tuple

@dataclass(frozen=True, slots=True)
class CVVariant:
    """Immutable variant configuration for targeted CV generation."""
    id: Literal["m_a", "markets", "corporate_finance"]
    label: str                                    # Display label
    locale: Literal["en-GB", "en-US"]             # English variant for spelling/terminology
    section_order: tuple[str, ...]                # Ordered section headers for CV
    keyword_priorities: dict[str, float]          # Keyword -> weight (0.0-1.0) for density
    section_headers: dict[str, str]               # Canonical section -> variant-specific header
    cover_letter_tone: str                        # Tone descriptor for cover letter generation
    mandatory_keywords: tuple[str, ...]           # Keywords that define this variant (for classification)
```

**Instances** (module-level constants):

| Field | M&A (`m_a`) | Markets (`markets`) | Corporate Finance (`corporate_finance`) |
|-------|-------------|---------------------|----------------------------------------|
| `label` | "M&A / Investment Banking" | "Markets / Quant" | "Corporate Finance / FP&A" |
| `locale` | "en-GB" | "en-US" | "en-US" |
| `section_order` | ("Professional Experience", "Transaction Experience", "Education", "Technical Skills", "Projects", "Languages", "Certifications") | ("Technical Skills", "Quantitative Projects", "Professional Experience", "Education", "Projects", "Languages", "Certifications") | ("Finance Experience", "Reporting & Analysis", "Professional Experience", "Education", "Technical Skills", "Projects", "Languages") |
| `keyword_priorities` | {"financial modeling": 1.0, "valuation": 0.9, "LBO": 0.9, "M&A": 0.8, "deal rationale": 0.8, "Excel": 0.7, "PowerPoint": 0.6} | {"Python": 1.0, "statistics": 0.9, "Bloomberg": 0.9, "time series": 0.8, "quantitative research": 0.8, "SQL": 0.7, "pandas": 0.7} | {"financial reporting": 1.0, "variance analysis": 0.9, "budgeting": 0.9, "FP&A": 0.8, "Excel": 0.9, "PowerBI": 0.7, "SAP": 0.6} |
| `section_headers` | {"Experience": "Transaction Experience", "Skills": "Technical & Transaction Skills"} | {"Experience": "Quantitative Projects", "Skills": "Technical Skills"} | {"Experience": "Finance Experience", "Skills": "Financial Analysis Skills"} |
| `cover_letter_tone` | "transaction-focused" | "data-driven" | "reporting-focused" |
| `mandatory_keywords` | ("financial modeling", "valuation", "M&A", "deal") | ("Python", "statistics", "Bloomberg", "quantitative") | ("financial reporting", "variance analysis", "budgeting", "FP&A") |

**Relationships**: Referenced by `FitGap.variant_specific`, `CoverageResult.recommended_variant`, `PipelineItem.variant`, `ApplicationKit.variant`

---

### 2. FitGap (`career/cv_fit.py`)

```python
from dataclasses import dataclass
from typing import Literal, Optional
from cv_quality.models import Provenance

@dataclass(frozen=True, slots=True)
class FitGap:
    """One actionable gap between current CV and offer requirements for a variant."""
    requirement: str                              # Requirement text from offer
    requirement_type: Literal["mandatory", "preferred"]
    current_state: Literal[
        "missing",           # Section/experience/keyword absent (ATS risk MISSING_SECTION)
        "weak",              # Present but below threshold (e.g., keyword once, no evidence)
        "unquantified",      # Experience present but UNQUANTIFIED_EXPERIENCE risk
        "wrong_variant",     # Keyword present but in wrong variant section
        "wrong_order"        # Section order differs from variant template
    ]
    adapted_state: str                            # Human-readable recommendation for adapted CV
    provenance: Optional[Provenance]              # Citation to profile evidence or offer qualification
    variant_specific: bool                        # True if adaptation differs by variant
```

**Validation Rules**:
- `provenance` is `None` iff `current_state == "missing"` AND no profile evidence exists → kit inserts `[AJOUTER PREUVE CHIFFRÉE]`
- `adapted_state` must be specific enough to implement (e.g., "Add 'Built 3-statement LBO model for €500M deal' under Transaction Experience")
- Max 5 gaps per offer (enforced by `cv_fit.generate_diff`)

---

### 3. CoverageResult (`career/cv_fit.py`)

```python
from dataclasses import dataclass
from typing import list

@dataclass(frozen=True, slots=True)
class CoverageResult:
    """Requirement coverage analysis for one offer against current CV + profile."""
    mandatory_total: int
    mandatory_covered: int
    preferred_total: int
    preferred_covered: int
    mandatory_pct: float                          # mandatory_covered / mandatory_total * 100
    preferred_pct: float                          # preferred_covered / preferred_total * 100
    gaps: list[FitGap]                            # Top gaps (max 5), sorted by requirement_type + severity
    recommended_variant: CVVariant
    variant_rationale: str                        # Human-readable classification rationale
```

**Computation**:
- `mandatory_total` = count of requirements in `qualification.missing_fields` + `cv_action_plan` items with `status == "needs_evidence"` that map to variant mandatory keywords
- `mandatory_covered` = count of above where profile has matching evidence (via `matched_elements` + `cv_coverage.supported`)
- `preferred_total` = count of `matched_elements` themes + `qualification` provenance fields not in mandatory
- `preferred_covered` = count of preferred where profile has evidence

---

### 4. PipelineStage (`career/models.py` extension)

```python
from enum import Enum

class PipelineStage(str, Enum):
    DISCOVERED = "discovered"           # Job exists in jobs table
    QUALIFIED = "qualified"             # Job has qualification_facts_json populated
    SPRINT_QUEUED = "sprint_queued"     # Job appears in current application sprint queue
    PREP_ANALYZED = "prep_analyzed"     # get_job_prep() called for this job
    VARIANT_SELECTED = "variant_selected"  # User clicked "Créer le kit local" with variant
    KIT_GENERATED = "kit_generated"     # application_drafts row exists for job+variant
    TRACKING_CREATED = "tracking_created"  # applications row exists for job
```

**Derivation Logic** (pure function `derive_pipeline_stage(job_id, context)`):

```python
def derive_pipeline_stage(job_id: str, ctx: CareerContext) -> PipelineStage:
    has_draft = any(d.job_id == job_id for d in ctx.application_drafts)
    has_app = any(a.job_id == job_id for a in ctx.applications)
    in_sprint = any(item.job_id == job_id for item in ctx.sprint_queue)
    has_qual = ctx.jobs.get(job_id, {}).get("qualification_facts_json")
    has_prep = job_id in ctx.prep_cache  # set when get_job_prep called

    if has_app: return PipelineStage.TRACKING_CREATED
    if has_draft: return PipelineStage.KIT_GENERATED
    if has_prep and ctx.selected_variant.get(job_id): return PipelineStage.VARIANT_SELECTED
    if has_prep: return PipelineStage.PREP_ANALYZED
    if in_sprint: return PipelineStage.SPRINT_QUEUED
    if has_qual: return PipelineStage.QUALIFIED
    return PipelineStage.DISCOVERED
```

---

### 5. PipelineItem (`career/service.py` → `/api/career/application-pipeline`)

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True, slots=True)
class PipelineItem:
    job_id: str
    company: str
    title: str
    stage: PipelineStage
    variant: Optional[CVVariant]           # None if not yet selected
    variant_label: Optional[str]           # Display label
    kit_generated_at: Optional[str]        # ISO timestamp
    tracking_stage: Optional[str]          # From applications.stage
    readiness: str                         # From sprint queue: prepare_now, profile_to_complete, etc.
    match_score: int                       # From sprint queue
```

**Response Schema** (JSON):
```json
{
  "pipeline": [
    {
      "job_id": "str",
      "company": "str",
      "title": "str",
      "stage": "discovered|qualified|sprint_queued|prep_analyzed|variant_selected|kit_generated|tracking_created",
      "variant": "m_a|markets|corporate_finance|null",
      "variant_label": "str|null",
      "kit_generated_at": "ISO8601|null",
      "tracking_stage": "str|null",
      "readiness": "str",
      "match_score": "int"
    }
  ],
  "automatic_submission": false
}
```

---

### 6. ApplicationKit (generated artifacts, not persisted)

**Output Directory**: `output/career/kits/{job_id}_{variant_id}/`

| File | Content | Provenance |
|------|---------|------------|
| `cv.docx` | Single-column CV with variant section order, locale, availability block, quantified bullets from profile, placeholders for gaps | Every bullet cites `Provenance` to profile experience/skill |
| `cover_letter.docx` | Variant-tone letter referencing top 3 mandatory requirements with matched evidence | Each claim cites profile or offer qualification |
| `prep_sheet.md` | Checklist: offer facts to verify, profile evidence gaps, variant interview talking points, before-submit items | Links back to offer qualification + profile |

---

## State Transitions

```
DISCOVERED → QUALIFIED → SPRINT_QUEUED → PREP_ANALYZED → VARIANT_SELECTED → KIT_GENERATED → TRACKING_CREATED
     │            │            │              │                │                  │                │
  job import  qualification  sprint build   prep panel      "Créer le kit"    kit generated   "Créer le suivi"
```

- Transitions are **derived**, not stored — no state machine persistence needed
- User can skip stages (e.g., go straight from sprint to kit generation)
- Re-generating kit stays at `KIT_GENERATED` (idempotent)

---

## Database Schema Impact

**No schema changes required** (per Assumptions).

Existing tables used for derivation:
- `jobs` → `qualification_facts_json` (QUALIFIED), `job_family` (variant classification)
- `stage_matches` → sprint queue membership (SPRINT_QUEUED)
- `application_drafts` → kit generation (VARIANT_SELECTED, KIT_GENERATED) — *add `variant` column if not present*
- `applications` → tracking (TRACKING_CREATED)
- `candidate_profile` + `profile_imports` → approved profile evidence
- `cv_quality` analysis (in-memory) → CVAnalysisResult for coverage/diff

*Note*: `application_drafts` may need a `variant` column added via additive migration (ALLOWED by Constitution Data Integrity: additive schema evolution only).

---

## Serialization

| Entity | Serialization | Used By |
|--------|---------------|---------|
| `CVVariant` | JSON (id, label, locale, section_order, keyword_priorities, section_headers, cover_letter_tone, mandatory_keywords) | API response, JS variant selector |
| `FitGap` | JSON (all fields; provenance as nested object) | Prep panel diff rendering |
| `CoverageResult` | JSON (all fields; gaps as array, recommended_variant as id) | Prep panel coverage display |
| `PipelineItem` | JSON (as response schema above) | Pipeline view rendering |
| `PipelineStage` | String enum value | All JSON responses |

---

*Data model complete. All types map to existing codebase patterns (dataclasses with slots, frozen, Literal enums).*
