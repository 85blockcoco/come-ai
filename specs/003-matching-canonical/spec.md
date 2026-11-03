# Feature Specification: Canonical CV Matching

**Status**: Implemented candidate
**Reference commit**: `4b4817e`

## Goal

Keep one deterministic CV-to-offer matcher combining exact UX provenance and the adversarial concept system.

## Requirements

- One action per structured requirement, using only `HIGHLIGHT`, `REPHRASE`, `DO_NOT_ADD`, `QUANTIFY`, or `CONFIRM_LANGUAGE`.
- Every `cv_evidence_text` is an exact CV substring with a valid offset and field.
- Section labels, dates, homonyms, negations, languages, degrees and concepts cannot create false evidence.
- No network, model, clock, mutation or invented fact.

## Acceptance

- `test_cv_matching_actions.py` and `test_cv_matching_adversarial.py`: 1232 passed.
- `py_compile`, Ruff and `git diff --check` pass.
