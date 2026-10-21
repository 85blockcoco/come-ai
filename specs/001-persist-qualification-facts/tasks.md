# Tasks: Persist Qualification Facts

> **Historical task list:** do not execute unchecked tasks without first
> applying the corrections in `REVIEW_AND_AMENDMENT.md`.

**Input**: Design documents from `/specs/001-persist-qualification-facts/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: TDD required per Constitution Principle V. Tests written first, must fail before implementation.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify project structure and dependencies

- [ ] T001 Verify project structure matches plan.md (career/, tests/, career_static/)
- [ ] T002 Verify Python 3.12 and dependencies available (pytest, ruff, sqlite3)
- [ ] T003 [P] Verify Spec Kit constitution at `.specify/memory/constitution.md` is v1.0.0

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Database schema migration and qualification integration foundation — MUST complete before user stories

- [ ] T004 Add qualification citation columns to `jobs` table via idempotent migration in `career/service.py`
  - File: `career/service.py` (add `ensure_qualification_columns()` function)
  - Columns: `start_quote`, `duration_quote`, `contract_quote`, `facts_source`, `qualification_missing` (all TEXT, nullable)
  - Called at module load in `get_db()` or `init_db()`
  - Idempotent: checks `PRAGMA table_info(jobs)` before `ALTER TABLE`

- [ ] T005 [P] Create unit test for migration in `tests/test_qualification_persistence.py`
  - Test: `test_migration_adds_columns_idempotently`
  - Verifies columns exist after one call; second call succeeds silently

- [ ] T006 [P] Create unit test for `qualify_offer()` output structure in `tests/test_qualification_persistence.py`
  - Test: `test_qualified_offer_has_all_required_fields`
  - Verifies provenance dict contains expected keys with FactEvidence objects

---

## Phase 3: User Story 1 - See Complete Offer Details (Priority: P1) 🎯 MVP

**Goal**: Persist qualification facts (start_date, end_date, duration_months, employment_type) to `jobs` table during import/refresh

**Independent Test**: Run exploration → query `jobs` table for non-NULL qualification fields on offers with extractable facts

### Tests for User Story 1 (TDD - write first, ensure they FAIL)

- [ ] T007 [P] [US1] Contract test: `test_qualification_integration_in_import_jobs` in `tests/test_qualification_persistence.py`
  - Mock `qualify_offer()`, verify upsert SQL includes qualification columns with COALESCE

- [ ] T008 [P] [US1] Contract test: `test_qualification_integration_in_refresh_jobs` in `tests/test_qualification_persistence.py`
  - Mock `qualify_offer()`, verify refresh path calls qualification

- [ ] T009 [P] [US1] Integration test: `test_exploration_persists_qualification_facts` in `tests/test_qualification_persistence.py`
  - Run mini-exploration with synthetic offers → verify `jobs` table populated

### Implementation for User Story 1

- [ ] T010 [US1] Integrate `qualify_offer()` call in `import_jobs()` at `career/service.py:2798-2827`
  - Call `qualify_offer(normalized_offer)` for each offer before upsert
  - Extract: `start_date`, `end_date`, `duration_min_months`→`duration_months`, `contract_type`→`employment_type`
  - Extract provenance: `start_quote`, `duration_quote`, `contract_quote`, `facts_source`
  - Extract missing: `missing_fields` → JSON for `qualification_missing`
  - Use `COALESCE(jobs.column, NEW.column)` pattern for all qualification columns

- [ ] T011 [US1] Integrate `qualify_offer()` call in `refresh_jobs()` at `career/service.py:2830-2900`
  - Same qualification extraction as import
  - Preserve existing non-NULL user values via COALESCE

- [ ] T012 [US1] Add qualification audit logging in `career/service.py`
  - Log to `career_audit_log` with action="qualification_update"
  - Include: `job_id`, `fields_updated` (list), `fields_missing` (list), `target_status`

- [ ] T013 [P] [US1] Fix `_common_job()` in `career/discovery.py:427-436` to NOT hardcode empty qualification fields
  - Remove hardcoded `start_date="", end_date="", duration_months=None, employment_type=""`
  - Let import pipeline populate from qualification instead

---

## Phase 4: User Story 2 - Provenance Citations Visible in UI (Priority: P1)

**Goal**: Persist citation quotes and sources so UI can display them

**Independent Test**: Query `jobs` for non-empty `start_quote`, `duration_quote`, `contract_quote`, `facts_source` on qualified offers

### Tests for User Story 2 (TDD)

- [ ] T014 [P] [US2] Unit test: `test_provenance_quotes_extracted_correctly` in `tests/test_qualification_persistence.py`
  - Given `QualifiedOffer` with known provenance → verify quote extraction logic

- [ ] T015 [P] [US2] Unit test: `test_facts_source_normalization` in `tests/test_qualification_persistence.py`
  - Verify `provenance[field].source` maps to allowed `facts_source` values

### Implementation for User Story 2

- [ ] T016 [US2] Implement provenance quote extraction helper in `career/service.py`
  - Function: `_extract_qualification_citations(qo: QualifiedOffer) -> dict`
  - Maps provenance dict to citation columns per data-model.md
  - Handles "ambiguous" contract_type: stores conflicting quotes in `contract_quote`

- [ ] T017 [US2] Wire citation extraction into `import_jobs()` and `refresh_jobs()`
  - Call helper and include results in upsert

---

## Phase 5: User Story 3 - Calendar Status Reflects Real Dates (Priority: P2)

**Goal**: Update `calendar_status` and `calendar_reason` from qualification results

**Independent Test**: Count offers with `calendar_status != 'to_verify'` or specific reason after import

### Tests for User Story 3 (TDD)

- [ ] T018 [P] [US3] Unit test: `test_calendar_status_mapping` in `tests/test_qualification_persistence.py`
  - Map each `target_status` value to `calendar_status`
  - Map first `reason` to `calendar_reason`

- [ ] T019 [P] [US3] Integration test: `test_calendar_status_improves_after_import` in `tests/test_qualification_persistence.py`
  - Before: 121 offers with "Dates and duration not specified"
  - After import: < 60 offers with that reason

### Implementation for User Story 3

- [ ] T020 [US3] Update `calendar_status`/`calendar_reason` in `import_jobs()` and `refresh_jobs()`
  - `calendar_status = qo.target_status`
  - `calendar_reason = qo.reasons[0] if qo.reasons else "Qualified"`
  - Preserve user-overridden status via COALESCE (if UI ever allows manual override)

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Exhaustivity validation, regression testing, documentation

- [ ] T021 [P] Run exhaustivity measurement: `scripts/measure_exhaustiveness.py` on updated DB
  - Target: global fiche_pct ≥ 55% (up from 11.7%)
  - Verify SC-001 through SC-004 from spec.md

- [ ] T022 [P] Run full regression test suite: `.venv/bin/python -m pytest -q`
  - All existing tests must pass (SC-006)

- [ ] T023 [P] Run linting: `.venv/bin/ruff check .`
  - Zero errors (Constitution Principle V)

- [ ] T024 [P] Verify import latency: time exploration run before/after
  - Target: < 10% increase per offer (SC-007)

- [ ] T025 [P] Update `docs/INTEGRATION_STATUS.md` with qualification persistence status

- [ ] T026 [P] Create handoff document for UI team: citation column names and formats

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational — MVP
- **User Story 2 (Phase 4)**: Depends on Foundational — Can parallel US1 after T004-T006
- **User Story 3 (Phase 5)**: Depends on Foundational — Can parallel US1/US2 after T004-T006
- **Polish (Phase 6)**: Depends on all user stories complete

### Within User Story 1 (MVP Critical Path)

```
T007, T008, T009 (tests, parallel)
    → T010 (import_jobs integration)
    → T011 (refresh_jobs integration)
    → T012 (audit logging)
    → T013 (discovery.py fix)
```

### Parallel Opportunities

- **Phase 2**: T005, T006 (different test functions, same file)
- **Phase 3**: T007, T008, T009 (all test tasks, can run in parallel)
- **Phase 4**: T014, T015 (test tasks, parallel)
- **Phase 5**: T018, T019 (test tasks, parallel)
- **Phase 6**: T021-T026 (all independent, fully parallel)

---

## MVP Scope (Stop After Phase 3)

**Minimum Viable Product**: Complete Phase 2 (Foundational) + Phase 3 (User Story 1)
- Schema migration works
- `import_jobs()` and `refresh_jobs()` persist qualification facts
- Audit logging works
- Exhaustivity improves to ≥55% (validated by T021)

User Stories 2 & 3 (citations + calendar status) are P1 but can ship incrementally after MVP validation.

---

## Task Count Summary

| Phase | Tasks | Parallel | Notes |
|-------|-------|----------|-------|
| Setup | 3 | 1 | Quick verification |
| Foundational | 3 | 2 | Migration + tests |
| US1 (P1) | 7 | 3 | MVP core |
| US2 (P1) | 4 | 2 | Citations |
| US3 (P2) | 3 | 2 | Calendar status |
| Polish | 6 | 6 | Validation |
| **Total** | **26** | **16** | **62% parallelizable** |
