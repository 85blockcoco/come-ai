# Research: Persist Qualification Facts

## Decision: Schema Migration Strategy

**Decision**: Use additive SQLite `ALTER TABLE ADD COLUMN` statements in an idempotent migration function called at application startup (in `career/service.py` initialization). No migration framework needed.

**Rationale**:
- SQLite supports `ADD COLUMN` with default values
- Only 7 new columns needed; all nullable
- Idempotent: `IF NOT EXISTS` not supported for columns, so check `PRAGMA table_info(jobs)` first
- Runs once at startup; zero downtime for local-only app

**Alternatives Considered**:
- Full migration framework (alembic) — overkill for 7 columns, adds dependency
- Manual SQL file — requires user to run manually, not autonomous
- ORM-based migration — no ORM used in project

---

## Decision: Import Pipeline Integration Points

**Decision**: Call `qualify_offer()` in two locations:
1. `career/service.py:import_jobs()` — main import path for exploration results
2. `career/service.py:refresh_jobs()` — re-import/refresh path for existing offers

**Rationale**:
- `import_jobs()` is the single write path for new offers from exploration (called by `run_exploration()` in `service.py`)
- `refresh_jobs()` handles re-fetching and updating existing offers
- Both already construct normalized offer dicts before `INSERT`/`UPDATE`
- `discovery.py:normalize_and_store()` is called by connectors but ultimately feeds into `import_jobs()`

**Code Locations**:
- `career/service.py:2798-2827` — `import_jobs()` upsert logic (preserves existing non-NULL values)
- `career/service.py:2830-2900` — `refresh_jobs()` logic
- `career/discovery.py:427-436` — `_common_job()` returns hardcoded empty qualification fields (source of the bug)

---

## Decision: QualifiedOffer Fields to Persist

**Decision**: Persist these fields from `QualifiedOffer` to `jobs` table:

| QualifiedOffer Field | jobs Column | Type | Notes |
|---------------------|-------------|------|-------|
| `start_date` | `start_date` | TEXT (ISO date) | May be None |
| `end_date` | `end_date` | TEXT (ISO date) | May be None |
| `duration_min_months` | `duration_months` | INTEGER | Use min as canonical; max in provenance |
| `contract_type` | `employment_type` | TEXT | "internship", "fixed_term", etc. |
| `target_status` | `calendar_status` | TEXT | "conforming", "to_verify", "non_conforming" |
| `reasons[0]` | `calendar_reason` | TEXT | First reason as summary |
| `provenance["start_month"].quote` | `start_quote` | TEXT | Citation quote |
| `provenance["duration_min_months"].quote` | `duration_quote` | TEXT | Citation quote |
| `provenance["contract_type"].quote` | `contract_quote` | TEXT | Citation quote |
| `provenance["start_month"].source` | `facts_source` | TEXT | "source_field", "description_passage", etc. |
| `missing_fields` | `qualification_missing` | TEXT (JSON) | JSON array of missing field names |

**Rationale**:
- All fields directly available from `QualifiedOffer` dataclass
- Min duration used as canonical (conservative); max in provenance for completeness
- First reason sufficient for UI summary; full reasons in provenance if needed
- JSON for missing_fields keeps schema simple

---

## Decision: Provenance Column Design

**Decision**: Separate columns for each citation (not JSON blob).

**Rationale**:
- Easier to query and index in SQLite
- UI can read individual columns without JSON parsing
- Schema remains explicit and self-documenting
- Only 4 citation columns + 1 source column = 5 total

---

## Decision: Preservation of User-Entered Data

**Decision**: In `import_jobs()` upsert, only update qualification columns if the existing value is NULL. Use `COALESCE(existing, new)` pattern in SQL.

**Rationale**:
- Constitution Principle VII: "No overwrite of user-entered data"
- Current `import_jobs()` already uses this pattern for other fields (lines 2810-2827)
- Extend the same pattern to new qualification columns

---

## Decision: Calendar Status Mapping

**Decision**: Map `QualifiedOffer.target_status` directly to `jobs.calendar_status`:
- "conforming" → "conforming"
- "to_verify" → "to_verify"
- "non_conforming" → "non_conforming"

Map `QualifiedOffer.reasons[0]` (first reason) to `jobs.calendar_reason`.

**Rationale**:
- Direct 1:1 mapping; no translation layer needed
- `calendar_status` already exists in schema with these exact values
- First reason is the most specific (ordered by priority in `qualify_offer()`)

---

## Decision: Test Strategy

**Decision**:
1. Unit tests for qualification persistence logic (mock `qualify_offer()`, verify DB writes)
2. Integration test: full exploration run → measure exhaustivity via existing `test_offer_summary_exhaustiveness.py`
3. Synthetic truth: reuse `test_career_job_deduplication.py` patterns for qualification accuracy

**Rationale**:
- Constitution Principle V: Test-First, Proof-Required
- Existing exhaustivity test (`test_offer_summary_exhaustiveness.py`) is the acceptance gate
- Unit tests ensure logic correctness; integration test ensures end-to-end value

---

## Decision: Audit Logging

**Decision**: Log qualification outcome to `career_audit_log` with action="qualification_update", including `job_id`, fields_updated (list), fields_missing (list), `target_status`.

**Rationale**:
- Traceability for debugging and compliance
- `career_audit_log` already used for import/refresh events
- Structured logging enables future analytics
