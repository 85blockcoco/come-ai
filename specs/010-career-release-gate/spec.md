# Feature Specification: Career End-to-End Release Gate

## Scenario

A synthetic candidate approves profile facts, explores non-France offers, verifies a source, qualifies and deduplicates it, receives matching actions, prepares a CV and safe letter, creates a dossier, checklist, follow-up and interview preparation, then resets all private data.

## Invariants

- No real network, personal data, submission, invented date, skill or evidence.
- `automatic_submission=false` throughout.
- Every displayed fact links to source provenance.
- France is filtered at connector boundaries and never leads a ranking.
- Reset removes every generated private artifact.

## Acceptance

The scenario and full repository suite pass with Ruff clean and a clean tracked diff.
