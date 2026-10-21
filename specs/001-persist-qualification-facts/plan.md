# Implementation Plan: Persist Qualification Facts

> **Superseded implementation design:** see `REVIEW_AND_AMENDMENT.md`. The RC
> uses a separate additive snapshot table and never synthesizes exact dates.

**Branch**: `001-persist-qualification-facts` | **Date**: 2026-10-20 | **Spec**: specs/001-persist-qualification-facts/spec.md

**Input**: Feature specification from `/specs/001-persist-qualification-facts/spec.md`

## Summary

Persist the qualification facts already extracted by `qualify_offer()` (start_date, end_date, duration_months, employment_type, calendar_status, calendar_reason) back to the `jobs` table during import, along with provenance citations (quotes, source). This closes the largest gap identified in AUTO-001 (424 recoverable pairs, 56.7% of exhaustivity gap) without any new API calls or external dependencies.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: SQLite (stdlib), existing `career` package modules (`offer_qualification`, `service`, `discovery`, `models`)

**Storage**: SQLite database at `career_data/career.sqlite3` (WAL mode), `jobs` table

**Testing**: pytest (existing suite in `tests/`), synthetic truth corpus for qualification exhaustivity

**Target Platform**: Local-only HTTP server on macOS (127.0.0.1:8765)

**Project Type**: Local-first web application (Python backend + vanilla JS frontend)

**Performance Goals**: Import pipeline latency increase < 10% per offer; qualification is pure Python, no I/O

**Constraints**:
- Zero API spend (Constitution Principle II)
- All facts must carry provenance citations (Constitution Principle IV)
- No overwrite of user-entered data (Constitution Principle VII)
- Idempotent imports (Constitution Principle VII)
- Must pass `pytest -q` and `ruff check .` (Constitution Principle V)

**Scale/Scope**: 121 current offers; ~6,000 raw postings per exploration run; single-user local deployment

## Constitution Check

| Principle | Check | Result |
|-----------|-------|--------|
| I. Career-First | Feature directly improves offer discovery/qualification | ✅ PASS |
| II. Max Quality, Zero API Spend | No external calls; pure local qualification | ✅ PASS |
| III. Privacy by Design | No data leaves Mac; only local DB writes | ✅ PASS |
| IV. Mandatory Evidence | Provenance quotes persisted and rendered | ✅ PASS |
| V. Test-First | TDD required; synthetic truth for qualification | ✅ PASS |
| VI. Git Protected | Work in isolated worktree/branch | ✅ PASS |
| VII. Simplicity | Pure functions, additive schema, honest progress | ✅ PASS |

No violations. All gates pass.

## Project Structure

### Documentation (this feature)

```text
specs/001-persist-qualification-facts/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (internal interfaces)
└── tasks.md             # Phase 2 output ($speckit-tasks command)
```

### Source Code (repository root)

```text
career/
├── offer_qualification.py   # qualify_offer() - source of truth
├── service.py               # import_jobs(), refresh_jobs() - write path
├── discovery.py             # normalize_and_store() - connector pipeline
├── models.py                # DB schema helpers (dedup_key, etc.)
└── connectors/
    └── public_ats.py        # _common_job() - current hardcoded empties

tests/
├── test_career_job_deduplication.py
├── test_offer_summary_exhaustiveness.py
└── (new) test_qualification_persistence.py
```

**Structure Decision**: Single-project layout. All changes confined to `career/` package and `tests/`.

## Complexity Tracking

No constitution violations. No additional complexity justified.

---

## Phase 0: Outline & Research

### Unknowns from Technical Context

1. **Schema migration strategy** for adding columns to `jobs` table in SQLite
2. **Exact import pipeline entry points** where `qualify_offer()` should be called
3. **Provenance column design**: separate columns vs. JSON blob
4. **Interaction with existing `calendar_status`/`calendar_reason` logic** in `service.py`

### Research Tasks

- [x] Inspect `jobs` table schema and current import code paths
- [x] Review `qualify_offer()` return type (`QualifiedOffer`) for all needed fields
- [x] Check existing `calendar_status` logic in `service.py`
- [x] Determine SQLite ALTER TABLE approach for additive migration

### Findings (consolidated in research.md)

See `research.md` for detailed decisions.

---

## Phase 1: Design & Contracts

### Data Model (data-model.md)

See `data-model.md` for entity definitions, field types, validation rules, and state transitions.

### Contracts (contracts/)

Internal interfaces only (no external API):
- `qualify_offer()` input/output contract
- Import pipeline qualification integration point
- DB schema migration script interface

### Quickstart Validation Guide (quickstart.md)

See `quickstart.md` for runnable validation scenarios.

---

## Phase 2: Tasks (preview for $speckit-tasks)

1. **Schema Migration**: Add columns to `jobs` table via idempotent migration script
2. **Qualification Integration**: Call `qualify_offer()` in import pipeline (`service.py` + `discovery.py`)
3. **Provenance Persistence**: Write qualification facts + citations to `jobs`
4. **Calendar Status Update**: Derive `calendar_status`/`calendar_reason` from `QualifiedOffer.target_status`
5. **Preservation Logic**: Skip overwrite of non-NULL user values
6. **Audit Logging**: Log qualification outcome to `career_audit_log`
7. **Tests**: Unit tests for qualification persistence; exhaustivity regression test
8. **Verification**: Run full exploration + measure exhaustivity (target ≥55%)

---

*Plan generated by Spec Kit planning workflow. Ready for Phase 0 research consolidation.*
