---
description: "Task list for Connect ATS Diagnostics to Targeted CV Variants Pipeline"
---

# Tasks: Connect ATS Diagnostics to Targeted CV Variants Pipeline

**Input**: Design documents from `/specs/003-ats-diagnostic-cv-variants-pipeline/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Organization**: Tasks grouped by user story to enable independent implementation and testing. Each user story delivers an independently testable increment.

## Progress reconciled in the consolidation candidate (2026-10-25)

The original checklist was generated for `AI-Excel-Agent-application-sprint`; the feature implementation is already present in the isolated release-candidate branch `codex/v3-stable-consolidation`. The eleven Spec Kit documents were copied from the untracked source-checkout directory into this candidate, with trailing whitespace removed; the source checkout remains untouched. Checkmarks below reflect code and tests found in this candidate, not work on the original sprint branch.

- T005-T044 are implemented and covered by the existing variant, coverage, kit, API, UI and pipeline tests.
- T045, T047-T057 are implemented/adapted and covered with synthetic Canva-equivalent PDFs, including a split experience continued on page two. Coordinate extraction uses the existing `pypdf` visitor API rather than adding `pdfplumber`; no dependency was added.
- T046 remains open for a real personal CV; synthetic fixtures were used instead. No personal CV was read.
- T058 current exact candidate run at `2bb5d9221afc21efbd90c1aa6d691b46e21a0baa` (the full suite ran on the byte-identical worktree immediately before commit): **2,971 passed, 2 skipped, 0 failed in 204.65 s** (`COME_AI_DIAGNOSTICS_OFFLINE=1`, full suite). The two skipped macOS nested-sandbox tests were invoked separately on this SHA but remained skipped because the runner detects an already active sandbox. Earlier sandbox passes were on `6a8f02f`, not this exact SHA. The previous load-sensitive deduplication failure is historical and did not recur in this full run.
- T059 current targeted criteria matrix on `2bb5d92`: **187 passed** across contract defaults, explicit contract choices, qualification, Stage Hunter and exploration. The focused UX/integration matrix also passed **19 tests** (Career stale-exploration, profile imports, Dev Kit integration and active-run resume); the full suite covers Spec 003 feature tests.
- T060 has verified synthetic Career browser flow through exploration, prep, explicit language, kit and persisted tracking after restart. The profile-import review UI was separately exercised in Chrome from an API-seeded synthetic PDF. Browser file selection itself remains unverified because the Chrome extension cannot access local file URLs in this setup; end-to-end quickstart remains open.
- T061 has a repeatable offline harness at `scripts/benchmark_career_spec003.py`. Latest candidate run: sprint 150 median 1,407.4 ms (target <500 ms, **miss**); kit median 213.0 ms (target <2,000 ms, pass); pipeline with 50 offers median 90.4 ms (target <200 ms, pass); PDF extraction plus CV analysis median 14.6 ms (target <3,000 ms, pass; 4 synthetic experiences detected). Timing varies under machine load; sprint threshold remains open.
- T063 is complete for this feature: this Quickstart now uses current test paths, the actual local data contract and a reproducible benchmark command; implementation modules contain their interface/local-only docstrings.
- T065 (formal Constitution checklist) and T066 (merge readiness) remain open.
- `ruff check .`, `git diff --check`, and JavaScript syntax checks pass. `ruff format --check .` reports 221 pre-existing files would be reformatted; no repository-wide formatting was applied. The changed Python files pass `ruff format --check`.

## Format: `[ID] [P?] [Story?] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Setup/Foundational/Polish phases: NO story label

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Verify Python 3.12+ environment and existing dependencies (pypdf, python-docx, FastAPI, pytest, Ruff) in the isolated candidate environment
- [x] T002 Confirm existing test suite passes (1387+ tests) with `pytest -q` in project root
- [x] T003 [P] Create feature branch `003-ats-diagnostic-cv-variants-pipeline` from `main` (worktree: `/Users/comedelavenne/AI-Excel-Agent-application-sprint`)
- [x] T004 [P] Create directory for new module: `career/cv_variants.py` (will hold variant definitions)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

⚠️ **CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 [P] **CVVariant dataclass** — Create `career/cv_variants.py` with frozen dataclass `CVVariant` (id, label, locale, section_order, keyword_priorities, section_headers, cover_letter_tone, mandatory_keywords) per `data-model.md` and `contracts/variant-classification.md`
- [x] T006 [P] **Variant constants** — Define three module-level constants in `career/cv_variants.py`: `MA_VARIANT`, `MARKETS_VARIANT`, `CORPFIN_VARIANT` with exact values from `data-model.md` (section_order, keyword_priorities, section_headers, cover_letter_tone, mandatory_keywords, locale en-GB/en-US)
- [x] T007 [P] **ALL_VARIANTS tuple** — Export `ALL_VARIANTS = (MA_VARIANT, MARKETS_VARIANT, CORPFIN_VARIANT)` and `VARIANT_LABELS = {"m_a": "...", "markets": "...", "corporate_finance": "..."}` in `career/cv_variants.py`
- [x] T008 [P] **JOB_FAMILY_TO_VARIANT mapping** — Add `JOB_FAMILY_TO_VARIANT` dict in `career/cv_variants.py` per `contracts/variant-classification.md` (maps job_family strings to variant IDs)
- [x] T009 **FitGap & CoverageResult dataclasses** — Create `career/cv_fit.py` with frozen dataclasses `FitGap` (requirement, requirement_type, current_state, adapted_state, provenance, variant_specific) and `CoverageResult` (mandatory_total, mandatory_covered, preferred_total, preferred_covered, mandatory_pct, preferred_pct, gaps, recommended_variant, variant_rationale) per `data-model.md` and `contracts/coverage-diff.md`
- [x] T010 **PipelineStage enum** — Add `PipelineStage` enum (DISCOVERED, QUALIFIED, SPRINT_QUEUED, PREP_ANALYZED, VARIANT_SELECTED, KIT_GENERATED, TRACKING_CREATED) to `career/models.py` per `data-model.md`
- [x] T011 [P] **PipelineItem dataclass** — Add `PipelineItem` dataclass to `career/models.py` or `career/cv_fit.py` per `data-model.md` (job_id, company, title, stage, variant, variant_label, kit_generated_at, tracking_stage, readiness, match_score)
- [x] T012 [P] **Unit tests for cv_variants** — Create `tests/test_cv_variants.py` with tests for variant constants, JOB_FAMILY_TO_VARIANT mapping, and ALL_VARIANTS export (tests MUST fail before implementation, per Constitution Principle V)
- [x] T013 [P] **Unit tests for cv_fit dataclasses** — Create `tests/test_cv_fit.py` with tests for FitGap and CoverageResult instantiation, serialization, and provenance attachment (tests MUST fail before implementation)
- [x] T014 [P] **Unit tests for PipelineStage/PipelineItem** — Add tests in `tests/test_cv_fit.py` for enum values and dataclass serialization

**Checkpoint**: Foundation ready — all dataclasses, constants, and failing tests in place. User story implementation can now begin.

---

## Phase 3: User Story 1 - See CV Fit Gaps with Variant Guidance (Priority: P1) 🎯 MVP

**Goal**: Prep panel shows variant recommendation, mandatory/preferred coverage %, and structured diff with provenance citations

**Independent Test**: Select offer in sprint queue → click "Préparer" → verify panel shows (a) recommended variant with rationale, (b) coverage percentages, (c) diff with ≥3 gaps, (d) provenance-linked evidence suggestions

### Tests for User Story 1 (OPTIONAL - only if tests requested) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T015 [P] [US1] **Contract test: variant classification** — `tests/contract/test_variant_classification.py` testing `classify_variant()` against `contracts/variant-classification.md` (M&A exact match, Markets keywords, tie-break by coverage)
- [x] T016 [P] [US1] **Contract test: coverage computation** — `tests/contract/test_coverage_diff.py` testing `compute_coverage()` against `contracts/coverage-diff.md` (mandatory split, preferred split, covered logic)
- [x] T017 [P] [US1] **Contract test: diff generation** — `tests/contract/test_coverage_diff.py` testing `generate_diff()` against `contracts/coverage-diff.md` (current_state mapping, adapted_state templates, provenance attachment, max 5 gaps)
- [x] T018 [P] [US1] **Integration test: prep panel with variant** — `tests/integration/test_us1_prep_panel.py` simulating sprint queue → prep panel flow, asserting variant displayed, coverage%, diff rendered

### Implementation for User Story 1

- [x] T019 [P] [US1] **classify_variant()** — Implement in `career/cv_fit.py` per `contracts/variant-classification.md` (job_family exact match +0.50, mandatory keyword hits +0.10 each max 0.40, profile theme hits +0.05 each max 0.15, provenance alignment +0.05, cap 1.0, tie-break rules)
- [x] T020 [P] [US1] **compute_coverage()** — Implement in `career/cv_fit.py` per `contracts/coverage-diff.md` (mandatory from qualification.missing_fields + cv_action_plan.needs_evidence + variant mandatory_keywords not matched; preferred from matched_elements + qualification provenance + variant keyword_priorities top 10; covered logic with provenance/profile text matching)
- [x] T021 [P] [US1] **generate_diff()** — Implement in `career/cv_fit.py` per `contracts/coverage-diff.md` (current_state mapping from CVAnalysisResult findings + cv_action_plan, adapted_state templates per state type, attach_provenance() for profile/qualification citations, max 5 gaps sorted by severity)
- [x] T022 [US1] **Integrate into application_sprint.py** — Modify `build_application_sprint()` in `career/application_sprint.py` to call `classify_variant()` and `compute_coverage()` for each queue item, add `recommended_variant`, `variant_rationale`, `coverage` (mandatory_pct, preferred_pct), `gaps` (FitGap list) to each queue item output
- [x] T023 [US1] **Extend service.py get_job_prep()** — Modify `get_job_prep()` in `career/service.py` to compute and return `CoverageResult` + `FitGap` list for the selected offer, using user's profile and current CV analysis
- [x] T024 [US1] **Frontend: render diff in prep panel** — Modify `renderStagePrep()` in `career_static/career.js` to display variant recommendation badge, coverage percentages (mandatory/preferred), and structured diff table (requirement | current state | adapted state | provenance | variant-specific)
- [x] T025 [US1] **Frontend: variant selector in kit flow** — Modify `startApplicationKitFlow()` in `career_static/career.js` to pre-select recommended variant, show rationale tooltip, allow manual override with coverage score comparison

**Checkpoint**: User Story 1 complete — prep panel shows variant, coverage, diff. Can be tested independently via sprint queue → "Préparer".

---

## Phase 4: User Story 2 - Generate Targeted CV Kit (Priority: P1)

**Goal**: One-click kit generation (CV + cover letter + prep sheet) parameterized by variant, with placeholders for missing evidence

**Independent Test**: Click "Créer le kit local" → select variant → verify output/career/kits/{job_id}_{variant}/ contains cv.docx (single-column, variant sections, locale, availability block, placeholders), cover_letter.docx (top 3 mandatory reqs + evidence), prep_sheet.md (verification checklist, gaps, talking points, before-submit)

### Tests for User Story 2 (OPTIONAL - only if tests requested) ⚠️

- [x] T026 [P] [US2] **Contract test: kit generation** — `tests/contract/test_kit_generation.py` testing `generate_application_kit()` against `contracts/kit-generation.md` (CV structure per variant, locale spelling, availability block, placeholders, cover letter hooks, prep sheet sections, provenance map completeness, idempotency)
- [x] T027 [P] [US2] **Integration test: kit generation flow** — `tests/integration/test_us2_kit_generation.py` simulating sprint → prep → kit generation, asserting output files exist and pass ATS parse test (structure.py)
- [x] T028 [P] [US2] **ATS parse regression test** — `tests/integration/test_us2_ats_parse.py` generating M&A and Markets kits, running through `structure.py` analyzer, asserting 0 TABLE_DETECTED, 0 MISSING_SECTION for required sections, ≥4 experiences, ≥80% quantified (SC-004, SC-005)

### Implementation for User Story 2

- [x] T029 [P] [US2] **generate_application_kit()** — Implement in `career/application_studio.py` per `contracts/kit-generation.md` (accepts job, profile, variant, coverage, cv_analysis, output_dir; generates cv.docx, cover_letter.docx, prep_sheet.md; returns ApplicationKitResult with paths, variant, timestamp, provenance_map)
- [x] T030 [P] [US2] **CV DOCX template per variant** — Implement single-column CV generation in `application_studio.py` using python-docx: variant-specific section_order, section_headers, locale (en-GB/en-US spelling), availability block, quantified bullets from profile with provenance, placeholders for gaps with `[AJOUTER PREUVE CHIFFRÉE]`
- [x] T031 [P] [US2] **Cover letter generator** — Implement in `application_studio.py`: variant-specific hook (deal rationale / data-driven / reporting), top 3 mandatory requirements with matched evidence/placeholders, professional closing with availability/graduation/visa
- [x] T032 [P] [US2] **Prep sheet generator** — Implement in `application_studio.py`: offer facts table (from qualification.provenance), profile evidence gaps table, variant-specific interview talking points (per `contracts/kit-generation.md`), before-submit checklist
- [x] T033 [US2] **Persist variant in application_drafts** — Ensure `application_drafts` table has `variant` column (additive migration if needed: `ALTER TABLE application_drafts ADD COLUMN variant TEXT;`), store variant on kit generation
- [x] T034 [US2] **Wire kit generation in service.py** — Add `generate_application_kit()` call to `career/service.py` (new method or extend existing), exposed via API endpoint for frontend
- [x] T035 [US2] **Frontend: kit generation API call** — Modify `startApplicationKitFlow()` in `career_static/career.js` to POST to new endpoint, poll/show progress, on success open output folder or show download links
- [x] T036 [US2] **Frontend: show placeholders warning** — In kit generation success UI, highlight any `[AJOUTER PREUVE CHIFFRÉE]` placeholders with "Ajouter preuve au profil" action linking to profile edit

**Checkpoint**: User Story 2 complete — kit generation works end-to-end. Can be tested independently via sprint → prep → "Créer le kit local".

---

## Phase 5: User Story 3 - Pipeline View (Priority: P2)

**Goal**: Unified dashboard showing all offers with stage badges, variant labels, kit timestamps, tracking stages, and actions

**Independent Test**: Process 3+ offers through full cycle → open Pipeline view → verify all appear with correct stage badges, variant labels, kit timestamps, tracking stages, and "Créer le suivi" action where appropriate

### Tests for User Story 3 (OPTIONAL - only if tests requested) ⚠️

- [x] T037 [P] [US3] **Contract test: pipeline API** — `tests/contract/test_pipeline_api.py` testing `GET /api/career/application-pipeline` against `contracts/pipeline-api.md` (response schema, stage derivation logic, sort order, automatic_submission: false)
- [x] T038 [P] [US3] **Integration test: pipeline stages** — `tests/integration/test_us3_pipeline.py` creating jobs at each stage, calling endpoint, asserting correct stage derivation (discovered → qualified → sprint_queued → prep_analyzed → variant_selected → kit_generated → tracking_created)

### Implementation for User Story 3

- [x] T039 [P] [US3] **get_application_pipeline()** — Implement in `career/service.py` per `contracts/pipeline-api.md` (reads jobs, stage_matches, sprint_queue, prep_cache, application_drafts, applications; derives stage via pure function; returns sorted PipelineItem list)
- [x] T040 [P] [US3] **derive_pipeline_stage() pure function** — Implement in `career/cv_fit.py` or `career/service.py` per `contracts/pipeline-api.md` (priority order: tracking_created > kit_generated > variant_selected > prep_analyzed > sprint_queued > qualified > discovered)
- [x] T041 [US3] **API endpoint** — Add `GET /api/career/application-pipeline` route in `come_ai_web.py` or `career/router.py` calling `service.get_application_pipeline()`
- [x] T042 [US3] **Frontend: Pipeline panel HTML** — Add pipeline panel to `career_static/index.html` per `contracts/pipeline-api.md` (panel with refresh button, hidden div for content)
- [x] T043 [US3] **Frontend: renderApplicationPipeline()** — Implement in `career_static/career.js` per `contracts/pipeline-api.md` (table with columns: Entreprise, Intitulé, Stade, Variante CV, Kit généré, Suivi, Prêt, Score, Actions; stage badges, variant labels, action buttons per stage)
- [x] T044 [US3] **Frontend: pipeline actions** — Wire "Créer le suivi" (POST /api/career/applications), "Préparer" (loadStagePrep), "Voir le kit" (open output folder) buttons in pipeline table

**Checkpoint**: User Story 3 complete — pipeline view shows unified cycle. Can be tested independently after processing offers.

---

## Phase 6: User Story 4 - Canva PDF Parser Improvement (Priority: P2)

**Goal**: Experience detection recall ≥80% on Canva PDFs (2-column, floating boxes, multi-page) via reading-order reconstruction

**Independent Test**: Import user's real Canva PDF (or synthetic fixtures) → verify diagnostic detects ≥4 experiences with company, role, dates, ≥2 quantified bullets each; no TABLE_DETECTED risk

### Tests for User Story 4 (OPTIONAL - only if tests requested) ⚠️

- [x] T045 [P] [US4] **Synthetic Canva PDF fixtures** — Create `tests/fixtures/canva_pdfs/` generation script in `tests/test_canva_pdf_extraction.py::test_generate_canva_fixtures()` using reportlab/fpdf2: two_column.pdf (5 experiences), floating_boxes.pdf (4 experiences), multi_page.pdf (3 experiences, one split), mixed_layout.pdf (4 experiences + 2 projects)
- [ ] T046 [P] [US4] **Experience recall test** — `tests/test_canva_pdf_extraction.py::test_experience_recall()` importing all 4 fixtures + user's real PDF, asserting ≥4 experiences detected per PDF with company, role, dates, ≥2 bullets (SC-006)
- [x] T047 [P] [US4] **Reading order test** — `tests/test_canva_pdf_extraction.py::test_reading_order_reconstruction()` verifying left-to-right, top-to-bottom coordinate sorting correctly associates date column with description column
- [x] T048 [P] [US4] **No TABLE_DETECTED regression** — Assert improved parser does not emit TABLE_DETECTED on Canva PDFs (single-column logical reconstruction)

### Implementation for User Story 4

- [x] T049 [P] [US4] **PDF coordinate extraction** — Use the existing `pypdf` visitor API in `career/cv_quality/parser.py` for visual reading-order reconstruction; no new PDF dependency was added
- [x] T050 [P] [US4] **Visual block detection** — Add `detect_visual_blocks(words: list) -> list[VisualBlock]` in `parser.py`: cluster words by vertical proximity (same line/band), then sort blocks top-to-bottom, within band sort left-to-right by x0
- [x] T051 [P] [US4] **Column association** — In `parser.py`, detect 2-column layouts: if words cluster into two distinct x0 bands (left narrow, right wide), associate left-band words (dates/locations) with right-band words (descriptions) by vertical overlap
- [x] T052 [P] [US4] **Floating box grouping** — In `parser.py`, detect absolute-positioned text boxes: group words by proximity in both x and y, treat each cluster as a potential experience entry
- [x] T053 [P] [US4] **Multi-page stitching** — `structure.py::detect_experiences()` already retained no-date continuation lines in the preceding experience. Added a synthetic regression in `tests/test_canva_pdf_extraction.py` proving that the first paragraph at page two stays with the correct experience.
- [x] T054 [US4] **Heading-proximity grouping** — In `structure.py`, associate section headers with subsequent content by vertical distance (not just line order), so Canva's non-linear layout still maps content to correct sections
- [x] T055 [US4] **Date normalization in columns** — In `structure.py`, when dates detected in left column, parse and normalize (handle "Jan 2027", "01/2027", "2027-01", "January 2027") and attach to right-column experience entry
- [x] T056 [US4] **Update detect_experiences()** — Modify `career/cv_quality/structure.py::detect_experiences()` to use new parser coordinate-based logic, fallback to existing line-based logic for non-Canva PDFs
- [x] T057 [US4] **Preserve existing behavior** — Ensure all existing CV quality tests still pass (no regression on standard PDFs, DOCX, TXT)

**Checkpoint**: User Story 4 complete — Canva PDF experience detection improved. Can be tested independently via CV import → diagnostic.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements affecting multiple user stories, validation, and delivery readiness

- [x] T058 [P] **Full test suite pass** — Latest exact candidate run: 2,971 passed, 2 skipped, 0 failed; two sandbox checks remain environment-skipped on this SHA.
- [x] T059 [P] **New feature integration tests** — Feature and integration suites are included in the 2,971-pass full candidate run; the latest additional UX/API matrix passed 19 tests.
- [ ] T060 [P] **Quickstart validation** — Execute manual validation per `quickstart.md`: sprint queue → prep → kit → pipeline → Canva import, verify all SC-001 through SC-010
- [ ] T061 [P] **Performance benchmarks** — Reproducible results are logged above; sprint build remains above its 500 ms target at 150 candidates
- [ ] T062 [P] **Linting & formatting** — Global Ruff check and targeted formatting validation still required; no repository-wide format churn
- [x] T063 [P] **Documentation updates** — Reconcile this Quickstart and the local parser/design record with the implemented pypdf, CV kit, pipeline and benchmark contracts
- [x] T064 **End-to-end regression test** — Added `test_full_career_http_journey_explore_to_persisted_manual_kit` in `tests/test_career_explorer_web.py`: synthetic offer discovery → prep → explicit English CV variant kit → persisted tracking after service restart, with automatic submission asserted false
- [ ] T065 **Constitution compliance check** — Verify: no cloud calls in core pipeline (Principle II), provenance on all displayed facts (Principle IV), tests pass before commit (Principle V), work in isolated branch (Principle VI), pure functions preferred (Principle VII)
- [ ] T066 **Prepare merge request** — Ensure `git diff --check` clean, no uncommitted changes in worktree, all tests green, ready for `GO merge application sprint` approval

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — **BLOCKS all user stories**
- **User Stories (Phases 3-6)**: All depend on Foundational phase completion
  - US1 and US2 can proceed in parallel after Foundational (both P1)
  - US3 and US4 can proceed in parallel after Foundational (both P2)
  - US2 depends on US1 for variant recommendation in prep panel (soft dependency — can use default variant if US1 not done)
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational (Phase 2) — No dependencies on other stories
- **US2 (P1)**: Can start after Foundational (Phase 2) — Uses US1's variant recommendation; if US1 incomplete, defaults to M&A variant
- **US3 (P2)**: Can start after Foundational (Phase 2) — Reads from application_drafts (populated by US2) and sprint queue (US1)
- **US4 (P2)**: Can start after Foundational (Phase 2) — Independent parser improvement; feeds into all stories via better CV analysis

### Within Each User Story

- Tests (if included) MUST be written and FAIL before implementation (TDD per Constitution Principle V)
- Models/dataclasses before services
- Services before API endpoints
- Core implementation before frontend integration
- Story complete and independently testable before considering next priority

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel (T003, T004)
- All Foundational tasks marked [P] can run in parallel (T005-T008, T012-T014)
- Once Foundational phase completes:
  - US1 tasks T019-T021 (core logic) can run in parallel
  - US2 tasks T029-T032 (kit generators) can run in parallel
  - US3 tasks T039-T040 (pipeline logic) can run in parallel
  - US4 tasks T049-T053 (parser improvements) can run in parallel
- All contract tests marked [P] can run in parallel
- All integration tests marked [P] can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all contract tests for US1 together:
Task: "Contract test: variant classification in tests/contract/test_variant_classification.py"
Task: "Contract test: coverage computation in tests/contract/test_coverage_diff.py"
Task: "Contract test: diff generation in tests/contract/test_coverage_diff.py"

# Launch all core logic for US1 together:
Task: "classify_variant() in career/cv_fit.py"
Task: "compute_coverage() in career/cv_fit.py"
Task: "generate_diff() in career/cv_fit.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test User Story 1 independently (sprint → prep panel shows variant, coverage, diff)
5. Demo/validate with real CV and offers

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 → Test independently → Deploy/Demo
4. Add User Story 3 → Test independently → Deploy/Demo
5. Add User Story 4 → Test independently → Deploy/Demo
6. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (P1)
   - Developer B: User Story 2 (P1)
   - Developer C: User Story 3 (P2)
   - Developer D: User Story 4 (P2)
3. Stories complete and integrate independently

---

## Task Summary

| Phase | Tasks | User Story | Parallel Tasks |
|-------|-------|------------|----------------|
| 1: Setup | T001-T004 | — | T003, T004 |
| 2: Foundational | T005-T014 | — | T005-T008, T012-T014 |
| 3: US1 (P1) | T015-T025 | US1 | T015-T018, T019-T021 |
| 4: US2 (P1) | T026-T036 | US2 | T026-T028, T029-T032 |
| 5: US3 (P2) | T037-T044 | US3 | T037-T038, T039-T040 |
| 6: US4 (P2) | T045-T057 | US4 | T045-T048, T049-T053 |
| 7: Polish | T058-T066 | — | T058-T063 |

**Total**: 66 tasks across 7 phases

---

*Tasks generated from spec.md, plan.md, data-model.md, contracts/, research.md. Each task is specific, file-pathed, and independently actionable.*
