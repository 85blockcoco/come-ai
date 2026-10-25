# Quickstart Validation Guide: ATS Diagnostics → CV Variants Pipeline

**Feature**: 003-ats-diagnostic-cv-variants-pipeline
**Date**: 2026-10-21

---

## Prerequisites

| Requirement | Version/Details |
|-------------|-----------------|
| Python | 3.12+ |
| Package manager | `uv` (preferred) or `pip` |
| Virtual environment | `.venv` activated with project dependencies |
| Database | `career_data/career.sqlite3` with test data |
| Test PDFs | User's real Canva PDF (local path) + synthetic fixtures (auto-generated) |

**Install/Activate**:
```bash
cd /Users/comedelavenne/AI-Excel-Agent-application-sprint
uv sync  # or: pip install -e .
source .venv/bin/activate
```

---

## Test Data Setup

### 1. Seed Career Database with 10 Test Offers

```bash
# Option A: Use existing test fixtures
pytest tests/test_career_application_sprint.py::test_application_sprint_http_uses_real_local_service_path -v

# Option B: Run exploration to populate jobs table
python -c "
from career.service import CareerService
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    svc = CareerService(Path(tmp))
    # Import 10 offers across M&A, Markets, CorpFin job_families
    # (use test_career_application_sprint.py import pattern)
"
```

### 2. Generate Synthetic Canva PDF Fixtures

```bash
# Run once to create tests/fixtures/canva_pdfs/*.pdf
pytest tests/test_canva_pdf_extraction.py::test_generate_canva_fixtures -v -s
# Creates 4 PDFs: two_column.pdf, floating_boxes.pdf, multi_page.pdf, mixed_layout.pdf
```

---

## Run Commands

### 1. Full Test Suite (Regression Gate)

```bash
# Must pass 1387+ tests, zero regressions
pytest -q --tb=short

# Expected: 1387 passed, 0 failed, 1 skipped (exhaustiveness test)
```

### 2. New Feature Unit Tests

```bash
# Variant classification, coverage, diff
pytest tests/test_cv_variants.py tests/test_cv_fit.py -v

# Canva PDF extraction recall
pytest tests/test_canva_pdf_extraction.py -v

# Pipeline endpoint + stage derivation
pytest tests/test_application_pipeline.py -v
```

### 3. Manual End-to-End Validation

**Start the server**:
```bash
python come_ai_web.py
# Serves on http://127.0.0.1:8765
```

**Open Career Explorer**:
```
http://127.0.0.1:8765/career
```

#### Flow 1: Sprint Queue → Variant Recommendation → Diff

1. **Run Stage Search** (Étape A): Configure domains (M&A, Markets, CorpFin), cities, exclusions
2. **Import/Discover Offers** (Étape B): Add ≥ 3 offers per job family
3. **Build Sprint Queue**: Click **"Construire ma liste express"**
4. **Verify Sprint Cards Show**:
   - ✅ Readiness badge (Prête à préparer / Profil à compléter / Offre à vérifier / Compatibilité à vérifier)
   - ✅ Match score, CV coverage %, language, location
   - ✅ Candidate warnings (PhD, MBA, Italian Speaker, Summer mismatch)
   - ✅ Next actions list
5. **Click "Préparer" on an M&A offer** → Verify prep panel shows:
   - ✅ **Recommended variant**: "M&A / Investment Banking" with rationale
   - ✅ **Coverage**: Mandatory X/Y (XX%), Preferred A/B (YY%)
   - ✅ **Diff** (≥ 3 gaps): Current state → Adapted state with provenance citations
   - ✅ Gap examples: "Missing: financial modeling → Add 'Built 3-statement LBO model...'"

#### Flow 2: Kit Generation (CV + Letter + Prep Sheet)

1. From sprint card or prep panel, click **"Créer le kit local"**
2. **Select variant** (should default to recommended) → Click **Générer**
3. **Verify output** in `output/career/kits/{job_id}_{variant}/`:
   - ✅ `cv.docx` opens in Word/LibreOffice:
     - Single-column layout (no tables/columns)
     - Section order matches variant (M&A: Transaction Experience first)
     - UK English spelling (en-GB: "modelling", "optimisation")
     - Availability block: "Available for 6-month internship from January 2027"
     - Quantified bullets from profile (e.g., "Automated 500+ files at SMBC")
     - Placeholders for gaps: `[AJOUTER PREUVE CHIFFRÉE: financial modeling]`
   - ✅ `cover_letter.docx`:
     - References top 3 mandatory requirements
     - Uses variant tone (M&A: "deal rationale & valuation")
     - Evidence cited or placeholdered
   - ✅ `prep_sheet.md`:
     - Offer facts to verify (dates, duration, language)
     - Profile evidence gaps with "Ajouter preuve au profil" actions
     - Variant interview talking points (M&A: "Walk me through your LBO model")
     - Before-submit checklist

#### Flow 3: Pipeline View

1. Navigate to **Pipeline** panel (new tab in Career)
2. **Verify all processed offers show**:
   - ✅ Correct stage badge (discovered → qualified → sprint_queued → prep_analyzed → variant_selected → kit_generated → tracking_created)
   - ✅ Variant label (M&A / Investment Banking, etc.)
   - ✅ Kit generation timestamp
   - ✅ Tracking stage (or "Créer le suivi" action if not yet tracked)
3. Click **"Créer le suivi"** on a kit-generated offer → Verify tracking created, stage updates

#### Flow 4: Canva PDF Import Regression

1. Go to **Profil** → **Importer un CV**
2. Upload **user's real Canva PDF** (or synthetic fixture)
3. Open **Diagnostic CV local** on review screen
4. **Verify**:
   - ✅ ≥ 4 experiences detected (was 1)
   - ✅ Each experience has company, role, dates, ≥ 2 bullets
   - ✅ Quantified bullets detected (UNQUANTIFIED_EXPERIENCE only where truly missing)
   - ✅ Sections detected: Experience, Education, Skills, Languages, Projects, Certifications
   - ✅ No TABLE_DETECTED risk (single-column parsing)

---

## Expected Outcomes (Success Criteria)

| SC | Metric | Validation Method |
|----|--------|-------------------|
| SC-001 | Variant classification ≥ 90% | `test_cv_variants.py::test_classification_accuracy` |
| SC-002 | Coverage accuracy ±5% | `test_cv_fit.py::test_coverage_accuracy` (5 ground-truth offers) |
| SC-003 | Diff ≥ 3 gaps/offer | Manual prep panel + `test_cv_fit.py::test_diff_actionable_gaps` |
| SC-004 | M&A kit passes ATS parse | `test_cv_fit.py::test_ma_kit_ats_parse` |
| SC-005 | Markets kit passes ATS parse | `test_cv_fit.py::test_markets_kit_ats_parse` |
| SC-006 | Canva PDF recall ≥ 80% | `test_canva_pdf_extraction.py::test_experience_recall` |
| SC-007 | Pipeline stages correct | `test_application_pipeline.py::test_pipeline_stages` |
| SC-008 | Zero invented facts | `test_cv_fit.py::test_kit_provenance_completeness` |
| SC-009 | Full suite green | `pytest -q` → 1387+ passed |
| SC-010 | Zero regression | Existing Career tests all pass |

---

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| `cv_variants.py` not found | Run `speckit-tasks` → implement task group 1 first |
| Variant not recommended | Check `job_family` values match `mandatory_keywords` in `cv_variants.py` |
| Kit generation fails | Verify `application_studio.py` has variant templates; check `output/` permissions (0700) |
| Pipeline view empty | Ensure `application_drafts` has `variant` column (run migration if needed) |
| Canva PDF still 1 experience | Run `test_canva_pdf_extraction.py` to debug coordinate extraction |
| Tests fail on CI | Ensure `pdfplumber` version matches local; check fixture PDF generation |

---

## Performance Benchmarks (Manual)

```bash
# Sprint queue build (150 candidates)
python -c "
import time
from career.service import CareerService
svc = CareerService(Path('career_data'))
start = time.perf_counter()
result = svc.get_application_sprint(limit=30)
print(f'Sprint build: {(time.perf_counter()-start)*1000:.0f}ms')
assert (time.perf_counter()-start) < 0.5
"

# Kit generation
python -c "
import time
from career.application_studio import generate_application_kit
start = time.perf_counter()
kit = generate_application_kit(job_id='test', variant='m_a', ...)
print(f'Kit generation: {(time.perf_counter()-start)*1000:.0f}ms')
assert (time.perf_counter()-start) < 2.0
"

# Pipeline endpoint
python -c "
import time
import requests
start = time.perf_counter()
r = requests.get('http://127.0.0.1:8765/api/career/application-pipeline')
print(f'Pipeline API: {(time.perf_counter()-start)*1000:.0f}ms')
assert (time.perf_counter()-start) < 0.2
"
```

---

*Quickstart complete. All validation paths trace to Success Criteria in spec.md.*
