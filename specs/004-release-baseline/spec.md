# Feature Specification: Reproducible Release Baseline

## Goal

Provide one fail-closed command reporting SHA, branch, dirty state, Python, targeted gates, full tests, Ruff, compilation and diff hygiene.

## Requirements

- Shell pipelines use `pipefail` and preserve the real exit status.
- Output is both readable and saved as JSON.
- Skips carry explicit reasons; unavailable optional checks are distinct from success.
- The final verdict is `PASS` only when every mandatory gate passes.

## Acceptance

Running `scripts/career_release_gate.sh` creates `artifacts/career-release-gate.json` and returns nonzero on any mandatory failure.
