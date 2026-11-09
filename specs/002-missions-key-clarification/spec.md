# Spec Cycle 002 — Missions Key Clarification

## Feature
Clarify the confusion between "requirements" and "missions" on job offers where the missions panel is empty.

## Problem
On 9 job offers, the "missions" panel was incorrectly populated with text from other sections (especially "Description du poste"), creating ambiguity between:
- **Requirements**: qualifications, skills, and experience stated in the offer (handled by `extract_requirements`)
- **Missions**: actual tasks, responsibilities, and deliverables the user will perform (handled by `extract_missions`)

The `extract_missions` function was extracting mission-like items from descriptions even when no explicit "Missions" section was present, blurring the distinction between the two categories.

## Root Cause
The `_scan` function in `career/cv_quality/missions_extractor.py` considers `"description du poste"` as a recognized missions heading (for French language offers). When this heading was present, the function collected all subsequent bulleted items as missions, even when they were not actually mission statements (e.g., "Nous recherchons un développeur...").

## Specification
Modify `extract_missions` to only extract missions when an explicit "Missions" section heading is detected. If no "Missions" section is found, return an empty list, clarifying the distinction from requirements.

### Change Location
`career/cv_quality/missions_extractor.py`, function `extract_missions`

### Expected Behavior
- **Before**: `extract_missions` could return facts from descriptions without an explicit "Missions" section
- **After**: `extract_missions` returns `[]` when no explicit "Missions" section heading is detected
- **Side effect**: The distinction between "requirements" (section `requirements`) and "missions" (section `missions`) is now clear at the extraction level

## Acceptance Criteria
- [ ] When `extract_missions` is called on a description without an explicit "Missions" section, it returns `[]`
- [ ] When `extract_missions` is called on a description with an explicit "Missions:" section, it extracts missions as before
- [ ] All existing tests pass (147 tests in `test_missions_extractor.py`)
- [ ] The `summarize_offer` function correctly shows no missions when there's no "Missions" section