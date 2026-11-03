# Contract: CV Coverage Analysis & Diff Generation

**Feature**: 003-ats-diagnostic-cv-variants-pipeline
**Version**: 1.0
**Date**: 2026-10-21

---

## Function Signatures

```python
def compute_coverage(
    job: dict,                                    # Offer with qualification + cv_coverage
    cv_analysis: CVAnalysisResult,                # From structure.py (current CV state)
    profile: dict,                                # Approved candidate_profile
    variant: CVVariant                            # Selected/recommended variant
) -> CoverageResult:

def generate_diff(
    coverage: CoverageResult,
    cv_analysis: CVAnalysisResult,
    profile: dict,
    variant: CVVariant,
    max_gaps: int = 5
) -> list[FitGap]:
```

---

## Input: `job` dict (extends variant-classification input)

```json
{
  "id": "str",
  "cv_coverage": {                                // From application_prep.py
    "requirements_total": 15,
    "supported": 6,
    "to_verify": 4,
    "coverage_percent": 40,
    "target_language": "en"
  },
  "cv_action_plan": [                             // Per-requirement actions
    {
      "requirement": "financial modeling",
      "status": "needs_evidence",
      "missing_keywords": ["financial modeling"],
      "suggested_change": "Ne pas ajouter sans preuve."
    }
  ],
  "matched_elements": [                           // Requirements with profile evidence
    {
      "requirement": "Excel",
      "matched_on": ["Advanced Excel", "VBA"],
      "evidence": "Advanced Excel, VBA macros"
    }
  ],
  "unverified_elements": [                        // Requirements without evidence
    {"requirement": "financial modeling", "note": "Non trouvé dans ton profil."}
  ],
  "uncertainty": ["Durée du stage à confirmer"]
}
```

---

## Input: `cv_analysis` (CVAnalysisResult from structure.py)

```python
@dataclass
class CVAnalysisResult:
    findings: list[Finding]                       # CV_TOO_LONG, MISSING_SECTION, UNQUANTIFIED_EXPERIENCE, LONG_BLOCK, TABLE_DETECTED, REPETITION, LOW_TEXT_RATIO
    sections: list[SectionReading]                # Detected sections with offsets
    experiences: list[ExperienceEntry]            # Parsed experiences with has_quantified_result
    readability: ReadabilityScore
    provenance: Provenance
```

---

## Output: `CoverageResult`

```python
@dataclass(frozen=True)
class CoverageResult:
    mandatory_total: int
    mandatory_covered: int
    preferred_total: int
    preferred_covered: int
    mandatory_pct: float
    preferred_pct: float
    gaps: list[FitGap]                            # Top gaps (max 5)
    recommended_variant: CVVariant
    variant_rationale: str
```

---

## Coverage Computation Rules

### Mandatory Requirements
```python
# Source 1: qualification.missing_fields (offer facts not verified)
# Source 2: cv_action_plan items with status="needs_evidence"
# Source 3: variant.mandatory_keywords NOT found in matched_elements

mandatory_requirements = set()

# From qualification
for field in job["qualification"].get("missing_fields", []):
    mandatory_requirements.add(("offer_fact", field))

# From cv_action_plan
for action in job.get("cv_action_plan", []):
    if action.get("status") == "needs_evidence":
        mandatory_requirements.add(("profile_skill", action["requirement"]))

# From variant mandatory keywords not in matched_elements
matched_keywords = {m["requirement"].lower() for m in job.get("matched_elements", [])}
for kw in variant.mandatory_keywords:
    if kw.lower() not in matched_keywords:
        mandatory_requirements.add(("variant_keyword", kw))

mandatory_total = len(mandatory_requirements)
```

### Mandatory Covered
```python
mandatory_covered = 0
for source, req in mandatory_requirements:
    if source == "offer_fact":
        # Covered if qualification has provenance for this field
        if req in job["qualification"].get("provenance", {}):
            mandatory_covered += 1
    elif source == "profile_skill":
        # Covered if profile has evidence (matched_elements or cv_coverage.supported)
        if any(req.lower() in m["requirement"].lower() for m in job.get("matched_elements", [])):
            mandatory_covered += 1
    elif source == "variant_keyword":
        # Covered if profile experience/skills contain keyword
        profile_text = " ".join([profile.get("experience", ""), profile.get("skills", ""), profile.get("projects", "")])
        if req.lower() in profile_text.lower():
            mandatory_covered += 1
```

### Preferred Requirements
```python
# Source 1: matched_elements themes (already have evidence)
# Source 2: qualification provenance fields (verified facts)
# Source 3: variant keyword_priorities (weighted)

preferred_requirements = set()

# From matched_elements
for m in job.get("matched_elements", []):
    preferred_requirements.add(("matched", m["requirement"]))

# From qualification provenance (verified facts)
for field, evidence in job["qualification"].get("provenance", {}).items():
    preferred_requirements.add(("verified_fact", field))

# From variant keyword priorities (top 10 by weight)
for kw, weight in sorted(variant.keyword_priorities.items(), key=lambda x: -x[1])[:10]:
    preferred_requirements.add(("variant_preferred", kw))

preferred_total = len(preferred_requirements)
```

### Preferred Covered
```python
preferred_covered = 0
for source, req in preferred_requirements:
    if source == "matched":
        preferred_covered += 1  # By definition has evidence
    elif source == "verified_fact":
        preferred_covered += 1  # By definition has provenance
    elif source == "variant_preferred":
        profile_text = " ".join([profile.get("experience", ""), profile.get("skills", ""), profile.get("projects", "")])
        if req.lower() in profile_text.lower():
            preferred_covered += 1
```

---

## Diff Generation Rules

### FitGap.current_state Mapping

| CVAnalysis Finding | current_state | Condition |
|--------------------|---------------|-----------|
| `MISSING_SECTION` (section in REQUIRED_SECTIONS) | `"missing"` | Section not detected in CV |
| `UNQUANTIFIED_EXPERIENCE` | `"unquantified"` | Experience exists but `has_quantified_result == False` |
| Keyword in `variant.mandatory_keywords` but in wrong section | `"wrong_variant"` | Keyword found in CV but section != variant section_headers |
| Section order != variant.section_order | `"wrong_order"` | Detected section order differs from variant template |
| Requirement in `cv_action_plan.needs_evidence` + no profile evidence | `"missing"` | No matched_element, no profile text match |
| Requirement in `matched_elements` but weak evidence | `"weak"` | Single mention, no quantification |

### FitGap.adapted_state Templates

| current_state | adapted_state Template |
|---------------|------------------------|
| `"missing"` (section) | `f"Add {variant.section_headers.get(section, section)} section with {variant-specific examples}"` |
| `"missing"` (skill) | `f"Add '{requirement}' with quantified evidence: {profile_example or '[AJOUTER PREUVE CHIFFRÉE]'}"` |
| `"unquantified"` | `f"Quantify {experience.company} — {experience.role}: add metrics (€, %, count, duration)"` |
| `"wrong_variant"` | `f"Move '{requirement}' from {current_section} to {variant.section_headers.get(target_section, target_section)}"` |
| `"wrong_order"` | `f"Reorder sections to match {variant.label} template: {' → '.join(variant.section_order[:4])}..."` |
| `"weak"` | `f"Strengthen '{requirement}': add specific example with measurable outcome"` |

### Provenance Attachment

```python
def attach_provenance(gap: FitGap, cv_analysis: CVAnalysisResult, profile: dict, job: dict) -> FitGap:
    if gap.current_state == "missing" and gap.requirement_type == "mandatory":
        # Check profile for any evidence
        profile_text = " ".join(profile.values())
        if gap.requirement.lower() in profile_text.lower():
            # Find offset in profile
            return replace(gap, provenance=Provenance(source="profile", quote=..., offset=...))
        # Check offer qualification provenance
        if gap.requirement in job["qualification"].get("provenance", {}):
            return replace(gap, provenance=job["qualification"]["provenance"][gap.requirement])
    elif gap.current_state == "unquantified":
        # Find the experience in cv_analysis.experiences
        for exp in cv_analysis.experiences:
            if exp.company in gap.requirement or exp.role in gap.requirement:
                return replace(gap, provenance=Provenance(source="cv_experience", quote=exp.description[:100], offset=exp.source_offset))
    return gap  # provenance stays None → kit inserts placeholder
```

---

## Output: `FitGap` (serialized for API)

```json
{
  "requirement": "financial modeling",
  "requirement_type": "mandatory",
  "current_state": "missing",
  "adapted_state": "Add 'Built 3-statement LBO model for €500M deal' under Transaction Experience",
  "provenance": {
    "source": "profile.experience",
    "quote": "SMBC: financial modeling internship",
    "offset": 1240
  },
  "variant_specific": true
}
```

---

## Test Contract

```python
def test_coverage_mandatory_split():
    job = {...}  # 5 missing_fields, 3 needs_evidence, 2 variant keywords not in profile
    cv_analysis = make_cv_analysis(sections=["Experience", "Education"], experiences=[...])
    profile = {"experience": "SMBC modeling", "skills": "Excel"}
    variant = MA_VARIANT

    result = compute_coverage(job, cv_analysis, profile, variant)

    assert result.mandatory_total == 10
    assert result.mandatory_covered == 3  # 2 from profile + 1 from qualification provenance
    assert result.mandatory_pct == 30.0

def test_diff_generates_actionable_gaps():
    result = compute_coverage(...)
    gaps = generate_diff(result, cv_analysis, profile, variant)

    assert len(gaps) <= 5
    assert all(g.adapted_state for g in gaps)
    assert all(g.provenance or g.current_state == "missing" for g in gaps)
    # At least 3 gaps where profile has evidence but CV doesn't
    actionable = [g for g in gaps if g.provenance and g.current_state in ("missing", "unquantified")]
    assert len(actionable) >= 3
```

---

*Contract complete. Implementation in `career/cv_fit.py::compute_coverage` and `generate_diff`.*
