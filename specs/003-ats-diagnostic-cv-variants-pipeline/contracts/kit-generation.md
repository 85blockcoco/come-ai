# Contract: Application Kit Generation (CV + Cover Letter + Prep Sheet)

**Feature**: 003-ats-diagnostic-cv-variants-pipeline
**Version**: 1.0
**Date**: 2026-10-21

---

## Function Signature

```python
def generate_application_kit(
    job: dict,                                    # Offer with full qualification
    profile: dict,                                # Approved candidate_profile
    variant: CVVariant,                           # Selected variant
    coverage: CoverageResult,                     # From compute_coverage()
    cv_analysis: CVAnalysisResult,                # Current CV state
    output_dir: Path                              # output/career/kits/{job_id}_{variant.id}/
) -> ApplicationKitResult:
```

---

## Output: `ApplicationKitResult`

```python
@dataclass(frozen=True)
class ApplicationKitResult:
    cv_path: Path                                 # cv.docx
    cover_letter_path: Path                       # cover_letter.docx
    prep_sheet_path: Path                         # prep_sheet.md
    variant: CVVariant
    generated_at: str                             # ISO timestamp
    provenance_map: dict[str, Provenance]         # Every bullet/claim → citation
```

---

## CV DOCX Specification (`cv.docx`)

### Structure (Single-Column, ATS-Safe)

| Order | Section | Variant M&A | Variant Markets | Variant CorpFin |
|-------|---------|-------------|-----------------|-----------------|
| 1 | Header | Name, Contacts, **Availability Block** | Same | Same |
| 2 | Professional Summary | 2 lines: target role + top 3 quantified wins | 2 lines: quant focus + tech stack | 2 lines: FP&A scope + reporting wins |
| 3 | **Transaction Experience** | **Quantitative Projects** | **Finance Experience** |
| 4 | Education | Education | Education |
| 5 | **Technical & Transaction Skills** | **Technical Skills** | **Financial Analysis Skills** |
| 6 | Projects | Projects | Projects |
| 7 | Languages | Languages | Languages |
| 8 | Certifications | Certifications | Certifications |

### Availability Block (Required, all variants)

```
Available for a 6-month international internship starting between January and March 2027
Graduation: December 2026 (eligible for 2027 programs)
Work authorization: EU citizen / [visa status from profile]
```

### Section Content Rules

**Experience Section** (variant-specific header):
- Reverse chronological
- Each experience: Company | Role | Dates | Location
- Bullets: **Action verb + quantified result + context**
  - Good: "Automated 500+ file processing workflow, reducing manual time by 80% (2 weeks → 2 days)"
  - Bad: "Responsible for file processing"
- Missing quantification → insert placeholder: `[AJOUTER PREUVE CHIFFRÉE: specific metric]`
- Provenance: each bullet cites `Provenance` to profile experience/skill

**Skills Section** (variant-specific header):
- Grouped by variant keyword_priorities (high weight first)
- Format: `Skill — Proficiency — Evidence quote`
  - Example: `Financial Modeling — Advanced — "Built 3-statement LBO for €500M deal at SMBC"`
- Missing evidence → `Skill — [AJOUTER PREUVE CHIFFRÉE]`

**Projects Section**:
- Only projects with quantified outcomes
- Variant-aligned: M&A → valuation projects; Markets → data/quant projects; CorpFin → reporting/automation projects

### Locale Rules

| Variant | Locale | Spelling Examples | Terminology |
|---------|--------|-------------------|-------------|
| M&A | en-GB | modelling, optimisation, analyse, programme | "Internship", "Graduate Programme", "Analyst" |
| Markets | en-US | modeling, optimization, analyze, program | "Internship", "Summer Analyst", "Quant" |
| CorpFin | en-US | modeling, optimization, analyze, program | "Internship", "FP&A Analyst", "Financial Analyst" |

### Idempotency

```python
# Same inputs → byte-for-byte identical DOCX
def test_kit_idempotent():
    kit1 = generate_application_kit(job, profile, variant, coverage, cv_analysis, dir1)
    kit2 = generate_application_kit(job, profile, variant, coverage, cv_analysis, dir2)
    assert kit1.cv_path.read_bytes() == kit2.cv_path.read_bytes()
```

---

## Cover Letter DOCX Specification (`cover_letter.docx`)

### Structure

```
[Date]
[Recruiter Name / Hiring Team]
[Company]
[Address]

Objet : Candidature — [Job Title] — [Job ID]

Madame, Monsieur,

[Hook paragraph: 2-3 lines referencing company + role + variant-specific angle]

[Body paragraph 1: Top mandatory requirement #1 + matched evidence]
[Body paragraph 2: Top mandatory requirement #2 + matched evidence]
[Body paragraph 3: Top mandatory requirement #3 + matched evidence]

[Closing paragraph: Availability + graduation + work authorization + call to action]

Cordialement,
[Name]
[Phone] | [Email] | [LinkedIn]
```

### Variant-Specific Hooks

| Variant | Hook Template |
|---------|---------------|
| M&A | "Votre programme [Programme Name] attire mon attention par son exposition directe aux transactions M&A et à la modélisation financière — deux piliers que j'ai consolidés via [quantified experience]." |
| Markets | "L'approche quantitative de [Company] sur les marchés [asset class] résonne avec mon parcours en analyse de données financières et programmation — notamment [quantified project]." |
| CorpFin | "La rigueur du reporting financier et de l'analyse d'écarts chez [Company] correspond à mon expérience en FP&A où j'ai [quantified achievement]." |

### Evidence Integration

```python
top_3_mandatory = sorted(
    [g for g in coverage.gaps if g.requirement_type == "mandatory"],
    key=lambda g: g.provenance is not None,  # Prioritize those with evidence
    reverse=True
)[:3]

for req in top_3_mandatory:
    if req.provenance:
        evidence = req.provenance.quote
    else:
        evidence = "[AJOUTER PREUVE CHIFFRÉE]"
    # Inject into body paragraph
```

---

## Prep Sheet Markdown Specification (`prep_sheet.md`)

```markdown
# Prep Sheet — [Company] — [Job Title] — [Variant Label]

**Generated**: 2026-10-21T14:30:00Z
**Variant**: M&A / Investment Banking (en-GB)
**Job ID**: jpm-2027-iba

---

## 1. Offer Facts to Verify (on official page)

| Fact | Current Value | Source | Action |
|------|---------------|--------|--------|
| Start date | January 2027 | qualification.provenance.start_date.quote | ✅ Confirm on careers.jpmorgan.com |
| Duration | 6 months | qualification.provenance.duration_months.quote | ✅ Confirm |
| Language | English | qualification.provenance.language.quote | ✅ Confirm |
| Location | London, UK | job.city + job.country | ✅ Confirm |
| Contract type | Stage / Internship | qualification.provenance.contract_type.quote | ✅ Confirm |

---

## 2. Profile Evidence Gaps

| Requirement | Type | Status | Action |
|-------------|------|--------|--------|
| Financial modeling | Mandatory | ❌ Missing in CV | Add quantified LBO example to Transaction Experience |
| Valuation | Mandatory | ⚠️ Weak (mentioned once) | Add specific deal: "Valued €500M target using DCF/comps" |
| Transaction rationale | Mandatory | ❌ Missing | Add "Presented investment thesis to MD committee" |
| Bloomberg | Preferred | ✅ Covered | — |
| Excel/VBA | Preferred | ✅ Covered | — |

---

## 3. Variant-Specific Interview Talking Points (M&A)

- **Walk me through your LBO model**: Structure, assumptions, sensitivity analysis
- **Recent M&A deal you followed**: Strategic rationale, valuation approach, outcome
- **How would you value a private company with no comparables?**: DCF, precedent transactions, sum-of-parts
- **Excel modeling test readiness**: INDEX/MATCH, data tables, circularity handles

---

## 4. Before You Submit Checklist

- [ ] CV opens correctly in Word/LibreOffice (single column, no tables)
- [ ] All `[AJOUTER PREUVE CHIFFRÉE]` placeholders replaced with real metrics
- [ ] Availability block matches your actual window (Jan-Mar 2027)
- [ ] Graduation date (Dec 2026) doesn't conflict with program eligibility
- [ ] Cover letter addresses hiring manager / team by name if known
- [ ] No mixed en-GB/en-US spelling (all en-GB for M&A)
- [ ] File names: `CV_Come_Delavenne_JPM_IB_2027.docx`, `CL_Come_Delavenne_JPM_IB_2027.docx`
- [ ] Official application URL bookmarked: https://careers.jpmorgan.com/...
- [ ] Tracking row created in Career Explorer after manual submission

---

## 5. Provenance Index (for your reference)

Every bullet in CV and claim in cover letter traces to:
- `profile.experience` offset XXXX: "SMBC: financial modeling internship"
- `profile.projects` offset YYYY: "Automated 500+ files..."
- `qualification.provenance.start_date`: "Starting January 2027"
- ...
```

---

## Template Variables per Variant

| Variable | M&A (`m_a`) | Markets (`markets`) | CorpFin (`corporate_finance`) |
|----------|-------------|---------------------|-------------------------------|
| `experience_section_header` | "Transaction Experience" | "Quantitative Projects" | "Finance Experience" |
| `skills_section_header` | "Technical & Transaction Skills" | "Technical Skills" | "Financial Analysis Skills" |
| `locale` | "en-GB" | "en-US" | "en-US" |
| `cover_letter_hook` | "deal rationale & valuation" | "data-driven market analysis" | "reporting & variance analysis" |
| `interview_talking_points` | [M&A list above] | [Quant list: Python, stats, Bloomberg, time series] | [FP&A list: reporting, budgeting, variance, SAP] |

---

## Error Handling

| Condition | Behavior |
|-----------|----------|
| `output_dir` not writable | Raise `KitError("Impossible d'écrire dans output/career/kits/")` |
| `variant` not in `ALL_VARIANTS` | Raise `ValueError("Variante inconnue")` |
| `coverage.gaps` empty | Still generate kit (perfect fit) — prep sheet shows "Aucun gap détecté" |
| `profile` missing required fields (availability, graduation) | Use defaults from intake; flag in prep sheet |

---

## Test Contract

```python
def test_ma_kit_structure():
    result = generate_application_kit(ma_job, profile, MA_VARIANT, coverage, cv_analysis, tmp_path)

    # CV structure
    cv_doc = Document(result.cv_path)
    section_headers = [p.text for p in cv_doc.paragraphs if p.style.name.startswith('Heading')]
    assert section_headers[:3] == ["Professional Summary", "Transaction Experience", "Education"]

    # Locale
    cv_text = "\n".join(p.text for p in cv_doc.paragraphs)
    assert "modelling" in cv_text  # en-GB
    assert "modeling" not in cv_text

    # Availability block
    assert "Available for a 6-month international internship" in cv_text

    # Placeholders for gaps
    assert "[AJOUTER PREUVE CHIFFRÉE]" in cv_text

def test_kit_idempotent():
    result1 = generate_application_kit(job, profile, variant, coverage, cv_analysis, dir1)
    result2 = generate_application_kit(job, profile, variant, coverage, cv_analysis, dir2)
    assert result1.cv_path.read_bytes() == result2.cv_path.read_bytes()
    assert result1.cover_letter_path.read_bytes() == result2.cover_letter_path.read_bytes()

def test_provenance_map_complete():
    result = generate_application_kit(...)
    # Every bullet in CV has provenance entry
    assert len(result.provenance_map) > 0
    for bullet, prov in result.provenance_map.items():
        assert prov.source in ("profile", "qualification")
        assert prov.quote
```

---

*Contract complete. Implementation in `career/application_studio.py::generate_application_kit`.*
