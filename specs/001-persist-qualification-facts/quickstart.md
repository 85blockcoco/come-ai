# Quickstart Validation: Persist Qualification Facts

## Prerequisites

- Python 3.12+ with project dependencies (`.venv` activated)
- `career_data/career.sqlite3` database exists (from previous exploration)
- Spec Kit initialized with Codex + OpenCode integrations

## Setup

```bash
cd /Users/comedelavenne/AI-Excel-Agent-speckit
source .venv/bin/activate
```

## Validation Scenarios

### Scenario 1: Unit Test - Qualification Persistence Logic

**Purpose**: Verify that `qualify_offer()` results are correctly mapped to `jobs` columns.

**Run**:
```bash
.venv/bin/python -m pytest tests/test_qualification_persistence.py -v
```

**Expected**: All tests pass, including:
- `test_qualification_maps_to_columns`: Each `QualifiedOffer` field maps to correct column
- `test_provenance_citations_persisted`: Quotes and sources stored correctly
- `test_preservation_skips_user_values`: Non-NULL existing values not overwritten
- `test_calendar_status_from_target_status`: Status mapping works
- `test_idempotent_qualification`: Re-run produces identical results

### Scenario 2: Integration Test - Full Exploration + Exhaustivity

**Purpose**: Verify end-to-end improvement in offer summary exhaustivity.

**Run**:
```bash
# 1. Run exploration (uses existing career_data/career.sqlite3)
.venv/bin/python -c "
from career.service import run_exploration
run_exploration()
"

# 2. Measure exhaustivity (existing test)
.venv/bin/python -m pytest tests/test_offer_summary_exhaustiveness.py -v
```

**Expected**:
- Exploration completes without errors
- Exhaustivity test passes with `fiche_pct >= 55%` (up from baseline 11.7%)
- Specifically: `posted_date` + `start_date` ≥ 44/121, `employment_type` ≥ 120/121
- `calendar_status` "Dates and duration not specified" reason < 60/121

### Scenario 3: Migration Test - Schema Upgrade

**Purpose**: Verify migration adds columns idempotently.

**Run**:
```bash
.venv/bin/python -c "
import sqlite3
from career.service import ensure_qualification_columns
db = sqlite3.connect('career_data/career.sqlite3')
ensure_qualification_columns(db)
cols = {row[1] for row in db.execute('PRAGMA table_info(jobs)').fetchall()}
required = {'start_quote', 'duration_quote', 'contract_quote', 'facts_source', 'qualification_missing'}
assert required.issubset(cols), f'Missing: {required - cols}'
print('Migration OK:', required)
# Run again to verify idempotency
ensure_qualification_columns(db)
print('Idempotent OK')
"
```

**Expected**: No errors; all 5 columns present; second run succeeds silently.

### Scenario 4: Manual Verification - UI Display

**Purpose**: Verify new fields appear in Career Explorer UI.

**Run**:
```bash
# Start the server
./Lancer\ Côme\ AI\ V3.command

# Open browser to http://127.0.0.1:8765/career
# Navigate to Offers list and detail view
```

**Expected**:
- Offer cards show contract type badge (from `employment_type`)
- Offer detail shows start date, end date, duration with citation tooltips
- Calendar status reflects real dates (not generic "Dates and duration not specified")
- No console errors

### Scenario 5: Regression Test - Full Suite

**Purpose**: Ensure no regressions in existing functionality.

**Run**:
```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

**Expected**: All tests pass; no linting errors.

## Success Criteria Checklist

- [ ] **SC-001**: `posted_date` + `start_date` ≥ 44/121 (36.4%)
- [ ] **SC-002**: `employment_type` ≥ 120/121 (99.2%)
- [ ] **SC-003**: `calendar_status` "dates" reason < 60/121
- [ ] **SC-004**: Global exhaustivity (fiche) ≥ 55%
- [ ] **SC-005**: 100% of persisted facts have non-empty citation quotes
- [ ] **SC-006**: `pytest -q` passes (zero regressions)
- [ ] **SC-007**: Import latency increase < 10% per offer

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| Migration fails: column exists | Migration is idempotent; check `PRAGMA table_info(jobs)` |
| Qualification returns None for dates | Check `description_original` has content; verify `qualify_offer()` logic |
| Exhaustivity test fails | Run `scripts/measure_exhaustiveness.py` manually to debug field-by-field |
| UI doesn't show new fields | Clear browser cache; check `career_static/career.js` reads new columns |
| `calendar_status` not updating | Verify `refresh_jobs()` calls qualification; check `COALESCE` logic |

## Rollback

If critical issues found:
```bash
git stash  # or reset to pre-feature commit
# Database schema: columns are additive, no data loss
# Simply don't call qualification in import pipeline
```
