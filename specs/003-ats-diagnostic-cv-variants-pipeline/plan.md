# Implementation Plan: Connect ATS Diagnostics to Targeted CV Variants and Build Complete Offer-to-Application Pipeline

**Branch**: `003-ats-diagnostic-cv-variants-pipeline` | **Date**: 2026-10-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-ats-diagnostic-cv-variants-pipeline/spec.md`

## Summary

Connect three existing pillars — the Application Sprint queue (`application_sprint.py`), the ATS structural diagnostic (`cv_quality/structure.py`), and the Application Studio kit generator (`application_studio.py`) — into a unified pipeline that: (1) classifies each offer into a CV variant (M&A/IB, Markets/Quant, Corporate Finance/FP&A), (2) computes mandatory/preferred requirement coverage against the user's current CV and approved profile, (3) produces a structured "current CV → adapted CV" diff with variant-specific guidance, (4) generates a tailored kit (CV DOCX + cover letter + prep sheet) parameterized by variant, (5) improves Canva PDF experience extraction via reading-order reconstruction, and (6) exposes a unified pipeline view endpoint. All logic remains local-first, deterministic, and consent-gated; zero automatic submission.

## Technical Context

**Language/Version**: Python 3.12+, vanilla ES6 JavaScript (no build step)

**Primary Dependencies**: FastAPI (API), python-docx (DOCX generation), existing `pypdf` visitor API (PDF coordinate extraction), SQLite (FTS5), pytest, Ruff

**Storage**: SQLite (`career_data/career.sqlite3`) — existing tables: `jobs`, `stage_matches`, `applications`, `candidate_profile`, `profile_imports`, `application_drafts`; no schema changes required (pipeline stage derived from existing data)

**Testing**: pytest (unit + integration), existing test suite 1387+ tests must pass; new synthetic Canva PDF fixtures for extraction regression

**Target Platform**: macOS (local-only HTTP server on 127.0.0.1:8765)

**Project Type**: Local-first Career Explorer web application (Python backend + vanilla JS frontend)

**Performance Goals**:
- Sprint queue build: < 500ms for 150 candidates
- Kit generation: < 2s per offer
- Pipeline endpoint: < 200ms for 50 tracked offers
- PDF parsing: < 3s for 2-page Canva PDF

**Constraints**:
- Zero external API calls for core pipeline (Constitution Principle II)
- No personal data leaves machine without consent envelope (Principle III)
- Every displayed fact must carry provenance citation (Principle IV)
- All modifications pass `pytest` then `ruff` before commit (Principle V)
- Work in isolated branch/worktree; no merge to main without explicit approval (Principle VI)
- Prefer pure functions, structured logging, cooperative cancellation (Principle VII)

**Scale/Scope**:
- 3 CV variants, ~150 sprint candidates max, ~30 queue items max
- 10 test offers for variant classification accuracy
- 5 test offers for coverage accuracy
- User's real Canva PDF + 3 synthetic equivalents for extraction recall

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Career-First Priority | ✅ PASS | Every FR directly serves offer→application preparation |
| II. Max Quality, Zero Unapproved Spend | ✅ PASS | All local deterministic; no cloud calls in core pipeline |
| III. Privacy by Design | ✅ PASS | Profile evidence stays local; kit outputs to `output/` only |
| IV. Mandatory Evidence & Provenance | ✅ PASS | FR-013 enforces citations on diff + kit; provenance maps flow through |
| V. Test-First, Proof-Required | ✅ PASS | SC are measurable gates; TDD for parser improvements |
| VI. Git Protected, Supervised Autonomy | ✅ PASS | Branch isolated; spec/plan/tasks contract followed |
| VII. Simplicity & Observability | ✅ PASS | Pure functions for variant classification, diff, coverage; reuse existing types |

**No violations — no Complexity Tracking table needed.**

## Project Structure

### Documentation (this feature)

```text
specs/003-ats-diagnostic-cv-variants-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── variant-classification.md
│   ├── coverage-diff.md
│   ├── kit-generation.md
│   └── pipeline-api.md
└── tasks.md             # Phase 2 output (speckit-tasks)
```

### Source Code (repository root)

```text
career/
├── cv_variants.py              # NEW: Variant definitions (section order, keywords, locale, headers)
├── cv_fit.py                   # NEW: Variant classification, coverage calc, diff generation
├── application_sprint.py       # MODIFY: Integrate variant recommendation + diff into sprint queue items
├── application_studio.py       # MODIFY: Accept variant param; parameterize DOCX template
├── service.py                  # MODIFY: New /api/career/application-pipeline endpoint; wire cv_fit into prep
├── cv_quality/
│   ├── structure.py            # MODIFY: Reading-order reconstruction for Canva PDFs (FR-009, FR-010)
│   ├── models.py               # MODIFY: Extend CVAnalysisResult for diff/citation carrying
│   └── parser.py               # MODIFY: Visual block detection, column association
├── models.py                   # MODIFY: Add PipelineStage enum, FitGap dataclass if needed
career_static/
├── career.js                   # MODIFY: Pipeline view UI; variant selector in kit flow; diff rendering
├── index.html                  # MODIFY: Add pipeline view panel
tests/
├── test_cv_variants.py         # NEW: Variant classification, coverage, diff logic
├── test_cv_fit.py              # NEW: Integration tests for prep diff + kit generation
├── test_application_pipeline.py # NEW: Pipeline endpoint + stage derivation
├── test_canva_pdf_extraction.py # NEW: Reading-order reconstruction regression
└── fixtures/
    └── canva_pdfs/             # NEW: Synthetic Canva PDFs (not committed; generated in test setup)
```

**Structure Decision**: Single-project layout under `career/` (Python) and `career_static/` (JS). The feature extends existing Career modules — no new top-level packages.

## Phase 0: Research

All unknowns from Technical Context are resolved by the spec's Assumptions and existing codebase patterns. No external research needed.

### Research Findings (consolidated in `research.md`)

| Unknown | Decision | Rationale |
|---------|----------|-----------|
| Variant definition format | Pure Python dataclasses in `cv_variants.py` | Matches existing pattern (`models.py`, `scoring.py`); no config files needed |
| Coverage computation | Reuse `cv_coverage` from `application_prep.py` + `qualification.missing_fields` | Already computes supported/to_verify; extend with mandatory vs preferred split |
| Diff representation | List of `FitGap` objects with `current_state`, `adapted_state`, `provenance` | Fits `CVAnalysisResult` extension; serializable for JS |
| Kit template parameterization | Jinja2-like string templates in `application_studio.py` per variant | python-docx uses template docx; variant selects template + injects content |
| Canva PDF reading order | Existing `pypdf` visitor API with x/y coordinates → visual-band reading order | Avoid a new PDF dependency; preserve local parsing and cover multi-column and continuation cases with synthetic fixtures |
| Pipeline stage derivation | Computed from existing tables at query time (no new column) | Assumptions: no schema change; derived from `stage_matches`, `applications`, `application_drafts` |
| JS pipeline view | New panel in `index.html` + `renderApplicationPipeline()` in `career.js` | Consistent with existing sprint/detail/prep panels |

## Phase 1: Design & Contracts

### 1. Data Model (`data-model.md`)

**Entities**

```python
# career/cv_variants.py
@dataclass(frozen=True)
class CVVariant:
    id: Literal["m_a", "markets", "corporate_finance"]
    label: str                           # "M&A / Investment Banking", "Markets / Quant", "Corporate Finance / FP&A"
    locale: Literal["en-GB", "en-US"]    # UK English for M&A, US English for Markets/CorpFin
    section_order: tuple[str, ...]       # e.g., ("Professional Experience", "Transaction Experience", "Education", ...)
    keyword_priorities: dict[str, float] # keyword -> weight for density scoring
    section_headers: dict[str, str]      # canonical -> variant-specific header
    cover_letter_tone: str               # "transaction-focused", "data-driven", "reporting-focused"

# career/cv_fit.py
@dataclass(frozen=True)
class FitGap:
    requirement: str                     # Offer requirement text
    requirement_type: Literal["mandatory", "preferred"]
    current_state: Literal["missing", "weak", "unquantified", "wrong_variant", "wrong_order"]
    adapted_state: str                   # Human-readable recommendation
    provenance: Provenance | None        # Citation to profile evidence or offer qualification
    variant_specific: bool               # True if adaptation differs by variant

@dataclass(frozen=True)
class CoverageResult:
    mandatory_total: int
    mandatory_covered: int
    preferred_total: int
    preferred_covered: int
    mandatory_pct: float
    preferred_pct: float
    gaps: list[FitGap]

# career/models.py (extension)
class PipelineStage(Enum):
    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    SPRINT_QUEUED = "sprint_queued"
    PREP_ANALYZED = "prep_analyzed"
    VARIANT_SELECTED = "variant_selected"
    KIT_GENERATED = "kit_generated"
    TRACKING_CREATED = "tracking_created"

@dataclass(frozen=True)
class PipelineItem:
    job_id: str
    company: str
    title: str
    stage: PipelineStage
    variant: CVVariant | None
    kit_generated_at: str | None
    tracking_stage: str | None
```

**Relationships**
- `CVVariant` → `FitGap` (variant_specific adaptations)
- `CoverageResult` → `FitGap` (gaps list)
- `PipelineItem` → `CVVariant` (variant used for kit)
- `PipelineItem` stage derived from: `stage_matches` (discovered/qualified) → `application_sprint` queue (sprint_queued) → `get_job_prep` (prep_analyzed) → `application_studio` draft (variant_selected/kit_generated) → `applications` (tracking_created)

**Validation Rules**
- Variant classification: job_family exact match > requirements keyword overlap > qualification provenance
- Coverage: mandatory requirements from qualification `missing_fields` + `cv_action_plan` needs_evidence; preferred from `matched_elements` themes
- Diff: max 5 gaps per offer; each gap must have provenance or be marked "no evidence in profile"
- Kit idempotency: same offer+variant+profile → identical DOCX (byte-for-byte)

---

### 2. Contracts

#### `contracts/variant-classification.md`

**Input**: Offer dict (job_family, title, requirements, qualification.provenance), Profile dict (skills, experience, education)

**Output**:
```json
{
  "primary_variant": "m_a",
  "scores": {"m_a": 0.82, "markets": 0.45, "corporate_finance": 0.31},
  "rationale": "job_family 'M&A / Investment Banking' exact match; 4/5 mandatory keywords in requirements; 3 quantified experiences in profile support M&A"
}
```

**Rules**:
- job_family exact match to variant domain = +0.5 base score
- Each mandatory keyword from variant's `keyword_priorities` found in requirements = +0.1
- Each quantified profile experience matching variant theme = +0.05
- Tie-break: higher mandatory coverage wins

---

#### `contracts/coverage-diff.md`

**Input**: Offer qualification + cv_coverage + CVAnalysisResult (from structure.py) + Approved Profile

**Output**:
```json
{
  "coverage": {
    "mandatory_total": 8,
    "mandatory_covered": 3,
    "preferred_total": 12,
    "preferred_covered": 7,
    "mandatory_pct": 37.5,
    "preferred_pct": 58.3
  },
  "gaps": [
    {
      "requirement": "financial modeling",
      "requirement_type": "mandatory",
      "current_state": "missing",
      "adapted_state": "Add 'Built 3-statement LBO model for €500M deal' under Transaction Experience",
      "provenance": {"source": "profile.experience", "quote": "SMBC: financial modeling intern", "offset": 1240},
      "variant_specific": true
    }
  ],
  "recommended_variant": "m_a",
  "variant_rationale": "..."
}
```

**Rules**:
- Missing section (ATS risk MISSING_SECTION) → current_state="missing"
- Experience present but unquantified (UNQUANTIFIED_EXPERIENCE) → current_state="unquantified"
- Keyword present but in wrong variant section → current_state="wrong_variant"
- Section order differs from variant → current_state="wrong_order"

---

#### `contracts/kit-generation.md`

**Input**: Offer, Profile, CVVariant, CoverageResult (with gaps)

**Output**: Three files in `output/career/kits/{job_id}_{variant}/`:
- `cv.docx` — single-column, variant section order, UK/US locale, availability block, placeholders for gaps
- `cover_letter.docx` — references top 3 mandatory requirements with matched evidence/placeholders
- `prep_sheet.md` — verification checklist, evidence gaps, interview talking points, before-submit checklist

**Template Variables per Variant**:
| Variable | M&A | Markets | CorpFin |
|----------|-----|---------|---------|
| `experience_section_header` | "Transaction Experience" | "Quantitative Projects" | "Finance Experience" |
| `skills_section_header` | "Technical & Transaction Skills" | "Technical Skills" | "Financial Analysis Skills" |
| `locale` | en-GB | en-US | en-US |
| `cover_letter_hook` | "deal rationale & valuation" | "data-driven market analysis" | "reporting & variance analysis" |

---

#### `contracts/pipeline-api.md`

**Endpoint**: `GET /api/career/application-pipeline`

**Response**:
```json
{
  "pipeline": [
    {
      "job_id": "jpm-2027-iba",
      "company": "JPMorgan",
      "title": "Investment Banking Analyst Intern",
      "stage": "kit_generated",
      "variant": "m_a",
      "variant_label": "M&A / Investment Banking",
      "kit_generated_at": "2026-10-21T14:30:00Z",
      "tracking_stage": null,
      "readiness": "prepare_now",
      "match_score": 87
    }
  ],
  "automatic_submission": false
}
```

**Stage Derivation Logic** (pure function, no DB write):
- `discovered`: job exists in `jobs` table
- `qualified`: job has `qualification_facts_json` populated
- `sprint_queued`: job appears in current sprint queue
- `prep_analyzed`: `get_job_prep` called for this job (tracked via `application_drafts` or new lightweight log)
- `variant_selected`: user clicked "Créer le kit local" with variant
- `kit_generated`: `application_drafts` row exists for job+variant
- `tracking_created`: `applications` row exists for job

---

### 3. Quickstart Validation Guide (`quickstart.md`)

**Prerequisites**
- Python 3.12+, uv/pip, `.venv` activated
- `career_data/career.sqlite3` with ≥ 10 test offers across 3 job families
- User's real Canva PDF (local path) + 3 synthetic Canva PDFs generated by test fixtures

**Run Commands**
```bash
# 1. Full test suite (must pass on the current candidate; report the exact collected/pass/skip/fail counts)
pytest -q

# 2. New feature integration tests
pytest tests/test_cv_variants.py tests/test_cv_fit.py tests/contract/test_pipeline_api.py tests/integration/test_us3_pipeline.py tests/test_canva_pdf_extraction.py -v

# 3. Manual validation flow
# Start server
python come_ai_web.py
# Open http://127.0.0.1:8765/career
# 1. Run Stage Search → Import 10 test offers → Build Sprint queue
# 2. Click "Préparer" on an M&A offer → Verify variant=M&A, coverage%, diff shows ≥3 gaps
# 3. Click "Créer le kit local" → Select M&A variant → Verify output/career/kits/.../cv.docx opens with single-column, Transaction Experience section, UK English
# 4. Open Pipeline view → Verify all processed offers show correct stage badges

# 4. Canva PDF regression
# Import user's real Canva PDF → Verify diagnostic detects ≥4 experiences
# Run synthetic Canva PDF tests → Verify ≥80% recall
```

**Expected Outcomes**
- SC-001: Variant classification accuracy ≥ 90% on 10 test offers
- SC-002: Coverage accuracy within ±5% of manual audit on 5 offers
- SC-003: Diff identifies ≥ 3 actionable gaps per offer
- SC-004/005: Generated kits pass ATS parse test (0 TABLE, 0 MISSING_SECTION, ≥4 experiences, ≥80% quantified)
- SC-006: Canva PDF recall ≥ 80% (4/5 experiences detected)
- SC-007: Pipeline view shows correct stages for 5 test offers
- SC-008: Zero invented facts in kits (all trace to profile/qualification)
- SC-009: Full test suite green
- SC-010: Zero regression on existing Career features

---

## Phase 2: Implementation Tasks (preview for `speckit-tasks`)

The following task groups will be generated by `speckit-tasks`:

1. **Core variant system** — `cv_variants.py` + `test_cv_variants.py`
2. **Fit analysis engine** — `cv_fit.py` (classification, coverage, diff) + `test_cv_fit.py`
3. **Sprint integration** — Modify `application_sprint.py` to include variant + diff in queue items
4. **Kit generation** — Modify `application_studio.py` for variant parameter + templates
5. **Pipeline API** — New endpoint in `service.py` + `test_application_pipeline.py`
6. **Canva PDF parser** — Modify `structure.py`/`parser.py` for reading-order reconstruction + `test_canva_pdf_extraction.py`
7. **Frontend** — Pipeline view panel in `index.html` + `renderApplicationPipeline()` + variant selector in `career.js`
8. **Integration & regression** — End-to-end test, full suite pass, performance validation

---

*Plan complete. Ready for `$speckit-tasks` to generate actionable, dependency-ordered `tasks.md`.*

---

---

## Validation snapshot (2026-10-26)

This is an evidence snapshot for the isolated candidate, not a claim that every acceptance criterion is complete or that the candidate is ready for `main`. Source code SHA validated in the latest campaign: `43f533cf888ee10c20e89df33d33dfb688189000`.

- **US1 – CV fit and variants**: implementation and API/contract tests are present in the full candidate suite. The international Career browser demo rendered the fit and preparation sections; the synthetic click-through below generated a draft using approved synthetic profile facts, with placeholders for missing personal details.
- **US2 – tailored kit**: kit generation and its synthetic integration tests are present in the full suite. The suite includes application-preparation and explicit kit-language coverage. No personal CV was used or opened.
- **US3 – application pipeline**: pipeline API/UI and persistence tests are present in the full suite. A synthetic Chrome journey on `9c0304da98f3c6eabf10e93cdddd199b21c765be` went from manual offer import through qualification, explicit language selection, local kit creation, application tracking and persistence after process restart. It did not exercise live official-source search, personal file selection or a real CV. A browser rerun on the newest candidate commit was attempted but the browser-control session did not return a usable page; no latest-revision browser pass is claimed.
- **US4 – CV parsing**: coordinate-aware extraction now applies the PDF current transformation matrix; a synthetic top-down PDF regression initially failed and passes after correction. A separate synthetic project-finance title guard prevents a job title from being mistaken for the Projects section. Parser/import targeted validation: 49 tests passed after these changes. No real CV validation was performed.

### Current measurements

Reproducible command: `python scripts/benchmark_career_spec003.py` (synthetic local data only). Latest observed run:

| Measurement | Target | Observed median | Result |
|---|---:|---:|---|
| Sprint build, 150 candidates | <500 ms | 337.5 ms | Pass |
| Application kit | <2,000 ms | 291.9 ms | Pass |
| Pipeline API, 50 offers | <200 ms | 78.7 ms | Pass |
| PDF extraction + CV analysis | <3,000 ms | 12.6 ms | Pass, 4 synthetic experiences detected |

The sprint now shares one scoring/profile snapshot and one CV analysis, loads
the selected offers' full intelligence snapshots in one bounded query, and
reuses serialized offer rows instead of fetching each offer again. It reuses
the qualification already calculated for the same offer and skips the
standalone requirements-fit calculation that the sprint builder does not
consume; the normal individual preparation endpoint keeps that calculation.
Sprint ranking now uses a bounded normalization cache scoped to the operation.
It only retains short strings during that call and clears the cache on exit,
including exceptions; CV and profile text is not retained between requests.
The latest strict synthetic benchmark passed every target. Measurements vary
across runs, so these values are observations, not a stability guarantee.

### Candidate validation

- Full offline suite on the code at `edb624204a372117148e1d523a8971547d2e94d3`: **2,973 passed, 2 skipped, 0 failed in 291.75 s**. The two skipped tests require real nested macOS sandboxes and pytest skipped them inside this already sandboxed runner.
- Full offline suite on `82e5623e2503dea71693f009ed982d68374f4407`: **2,972 passed, 1 failed, 2 skipped in 871.80 s**. The failure was the 500-offer deduplication timing assertion (516 ms vs <200 ms). Repeated isolated measurements were 428–762 ms; the host load average was approximately 386. The two skipped cases require real nested macOS sandboxes.
- A focused Career criteria/search/deduplication matrix passed **282 tests**. The deduplication performance check passed in that run; another full-suite attempt before the optimization had shown variable timings, so the threshold is monitored rather than relaxed.
- After the bounded URL and redundant-pair fast paths, **191 focused Career/Dev Kit correctness tests passed** with the timing assertion deselected; the fast-path URL test passed separately. The complete deduplication module then passed (**163 passed in 3.67 s**, including the <200 ms assertion). Three isolated post-optimization timing runs passed (pytest durations 2.27, 3.06 and 2.45 s including startup); retain a repeat under a stable host load as a follow-up, but the target passed on all three runs.
- On `43f533cf888ee10c20e89df33d33dfb688189000`, the full offline suite passed: **2,974 passed, 2 skipped, 0 failed in 267.59 s**. The two skipped tests require real nested macOS sandboxes.
- The request-scoped normalization cache passed **119 focused Sprint, qualification, Stage Hunter and search UX tests**. `scripts/benchmark_career_spec003.py --strict` passed with medians: Sprint 337.5 ms, kit 291.9 ms, 50-offer pipeline 78.7 ms and PDF extraction/CV analysis 12.6 ms.
- `ruff check .`, `node --check career_static/career.js`, `node --check v5_static/evolution.js`, `node --check v5_static/devkit.js`, `python -m compileall -q career devkit data` and `git diff --check` passed on `43f533c`. `ruff format --check` reports five legacy/touched files would be reformatted; no formatter was run because it would create broad churn unrelated to these changes.

### Remaining acceptance work

- T060: repeat the synthetic end-to-end browser journey on the exact latest candidate; add official-source discovery and local file selection coverage where possible.
- T061: complete; strict synthetic benchmarks and the full deduplication module are green.
- T062: decide whether to accept the existing formatting style in the five files that `ruff format --check` would broadly rewrite, or schedule a dedicated formatting change.
- T065/T066: formal Constitution review and merge-readiness remain open. The full suite has not been rerun on the latest working tree, and the real sandbox scenarios have not been verified on this exact runner.

No personal CV, API key or `.env` file was opened. No real offer search or application submission was performed. The candidate is not yet merge-ready.
