# Plan Cycle 002 — Missions Key Clarification

## Objective
Modify `extract_missions` to clarify the distinction between "requirements" and "missions" by only extracting missions from explicit "Missions" section headings.

## Phase 1: Code Modification
- [x] Modify `career/cv_quality/missions_extractor.py`:
  - Add check for `heading_found` in `extract_missions`
  - Return `[]` when no explicit "Missions" section is detected
  - Add secondary check for recognized mission types to avoid extractions from "Description du poste"

## Phase 2: Validation
- [ ] Run existing test suite: `python3 -m pytest tests/test_missions_extractor.py -v`
- [ ] Verify behavior:
  - Description without "Missions" section -> returns `[]`
  - Description with explicit "Missions:" section -> extracts missions
  - All 147 tests pass

## Phase 3: Integration
- [ ] Run broader test suite to ensure no regressions
- [ ] Verify `summarize_offer` behavior with the fix
- [ ] Prepare PR with specification and code changes

## Dependencies
- Cycle 001 (Persist qualification facts) — completed ✅
- No new dependencies