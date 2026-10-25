# Quickstart Validation Guide: ATS Diagnostics → CV Variants Pipeline

**Feature**: 003-ats-diagnostic-cv-variants-pipeline
**Reconciled against**: `codex/v3-stable-consolidation` (2026-10-25)

---

## Prerequisites

| Requirement | Version/Details |
|-------------|-----------------|
| Python | 3.12+ |
| Package manager | Existing project virtual environment |
| Virtual environment | Candidate's Python 3.12 environment |
| Database | Tests and benchmarks create isolated temporary databases |
| Test PDFs | Synthetic Canva-equivalent PDF fixtures; do not use a personal CV in automated tests |

**Install/Activate**:
```bash
cd /Users/comedelavenne/Documents/Codex/2026-10-25/codex-op-ration-v3-stable-consolidation/candidate-worktree
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python --version
```

---

## Test Data Setup

The HTTP integration tests and benchmark seed synthetic records inside temporary
directories. They do not create or modify the user's Career database.

---

## Run Commands

### 1. Full Test Suite (Regression Gate)

```bash
COME_AI_DIAGNOSTICS_OFFLINE=1 PATH=/Users/comedelavenne/AI-Excel-Agent/.venv/bin:$PATH \
  /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q -p no:cacheprovider
```

The offline gate deliberately skips the two tests that launch nested macOS
`sandbox-exec` processes. Run those two tests individually outside the offline
runner. Do not describe a full-suite run with failures as green, even if a
timing-sensitive test passes in isolation.

### 2. New Feature Unit Tests

```bash
# Variant classification, coverage, diff
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q \
  tests/test_cv_variants.py tests/test_cv_fit.py \
  tests/contract/test_coverage_diff.py tests/contract/test_variant_classification.py \
  tests/contract/test_kit_generation.py tests/integration/test_us2_kit_generation.py \
  tests/test_canva_pdf_extraction.py tests/contract/test_pipeline_api.py \
  tests/integration/test_us3_pipeline.py tests/test_career_application_sprint.py

# Canva PDF extraction recall
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q \
  tests/test_canva_pdf_extraction.py tests/test_cv_quality_ats.py \
  tests/test_cv_quality_structure.py
```

### 3. Manual End-to-End Validation

**Start the server**:
```bash
python come_ai_web.py
# Serves on http://127.0.0.1:8765
```

**Open Career Explorer** (only when running with a temporary data directory):
```
http://127.0.0.1:8765/career
```

#### Flow 1: Sprint Queue → Variant Recommendation → Diff

1. **Run Stage Search** (Étape A): Configure domains (M&A, Markets, CorpFin), cities, exclusions
2. **Import/Discover Offers** (Étape B): Use public sources only after a user action, or use synthetic offers from the integration fixtures
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
3. **Verify output** in the configured local data directory at `output/career/kits/{job_id}_{variant}/`:
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
2. Upload a synthetic Canva-equivalent fixture. Do not use a personal CV for automated validation.
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
| SC-001 | Variant mapping and classification contracts | `tests/test_cv_variants.py`, `tests/contract/test_variant_classification.py` |
| SC-002 | Coverage and provenance rules | `tests/test_cv_fit.py`, `tests/contract/test_coverage_diff.py` |
| SC-003 | Actionable gap structure | `tests/contract/test_coverage_diff.py`, browser prep panel |
| SC-004/005 | M&A and Markets kit structure / ATS parse | `tests/contract/test_kit_generation.py`, `tests/integration/test_us2_kit_generation.py` |
| SC-006 | Synthetic Canva-equivalent PDF extraction | `tests/test_canva_pdf_extraction.py`; real personal-CV recall remains unverified |
| SC-007 | Pipeline stages and HTTP endpoint | `tests/contract/test_pipeline_api.py`, `tests/integration/test_us3_pipeline.py` |
| SC-008 | No invented profile facts and complete provenance | `tests/contract/test_kit_generation.py`, Career synthetic journey tests |
| SC-009/010 | Full suite and regression gate | Current exact-SHA test result in `tasks.md`; historical test counts are not current evidence |

---

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| `cv_variants.py` not found | Verify the active checkout and candidate branch before diagnosing; this module is present in the consolidation candidate |
| Variant not recommended | Check `job_family` values match `mandatory_keywords` in `cv_variants.py` |
| Kit generation fails | Verify `application_studio.py` has variant templates; check `output/` permissions (0700) |
| Pipeline view empty | Ensure `application_drafts` has `variant` column (run migration if needed) |
| Canva PDF still 1 experience | Run `test_canva_pdf_extraction.py` to debug coordinate extraction |
| Tests fail on CI | Use the project virtual environment and inspect the exact failing test; the current parser uses `pypdf` visitor coordinates |

---

## Performance Benchmarks

Run the reproducible synthetic benchmark from the candidate root:

```bash
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python scripts/benchmark_career_spec003.py
```

It measures sprint construction for 150 candidates, local kit generation,
pipeline HTTP response for 50 offers, and PDF extraction plus CV analysis. It
uses a temporary database and synthetic documents only. Add `--strict` to exit
nonzero for a missed target. Current measurements and the remaining sprint
target miss are recorded in `tasks.md`.

---

*Quickstart complete. All validation paths trace to Success Criteria in spec.md.*
