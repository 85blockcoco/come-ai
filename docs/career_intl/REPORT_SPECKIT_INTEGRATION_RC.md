# Spec Kit / Nemotron integration — release candidate

## Status

Release candidate isolated on `integration/speckit-career-rc`, based on
`main@c2e731d63b2cea36260d379a4b2a0adc42870341`.  `main`, the original Spec
Kit worktree and the dirty primary checkout were not modified.

## State recovered

- `AI-Excel-Agent-speckit` is on `speckit-init@d6e29857efb5b83479329ef1dc1bfc33405b4b77`.
- It contains no feature commit: its implementation, integrations, specs and
  tests are uncommitted.
- The primary checkout contains an untracked copy of
  `SPECKIT_INTEGRATION_SUMMARY.md`.  Its SHA-1 is identical to the worktree
  copy (`e1e1bf16b8913666704222fda82c736b62a7f69f`).  It was preserved.

## Four reported failures

Reproduced on the delivered worktree: `4 failed, 1266 passed, 1 skipped`.

- Three migration tests passed on clean `d6e2985` and failed only after the
  proposed schema v8 change.  They were regressions introduced by the lot.
- The clipboard fallback test already failed on clean `d6e2985`; it passes on
  current `main@c2e731d`.  It was genuinely pre-existing relative to Nemotron's
  base and already corrected upstream.
- The advertised exhaustivity test was the skipped test: it hard-coded paths
  to another checkout and therefore did not validate the Spec Kit worktree.
- That test also inserted the primary checkout at the front of `sys.path` and
  opened its private Career database.  This made a full RC test run import old
  code from another checkout.  It now resolves only the current worktree and
  explicitly skips when that isolated worktree has no measurable local corpus.

## Corrected cycle 001

The denormalized five-column design was rejected because it synthesized exact
dates, collapsed field provenance, retained stale citations with `COALESCE`,
and mutated the caller with `payload.pop`.

The RC instead adds an additive `job_qualification_snapshots` table.  Derived
facts, per-field evidence, missing fields, reasons, a source fingerprint and a
schema version are stored separately from raw/user-edited job fields.  A new
qualification replaces its previous snapshot; an import without one preserves
it.  Job deletion cascades.  Month-only evidence never creates an invented day
or end date.  Application summaries expose the snapshot and its uncertainty.

Migration tests now use the actual schema version and verify private backups.
The reviewed contract is in
`specs/001-persist-qualification-facts/REVIEW_AND_AMENDMENT.md`.

## Honest corpus measurement

The real local Career database was opened read-only and copied with SQLite's
backup API to an isolated temporary directory.  No title, company, profile or
description was printed or committed.  On exactly 121 stored offers, rebuilding
derived qualification in the copy produced:

- 121 snapshots;
- 112 offers with a contract fact;
- 35 with a minimum duration fact;
- 12 with a start-month fact;
- 43.8% coverage across those three qualification summary slots.

This is an exact aggregate for that copied corpus, not a quality score and not
proof of 55% global product-summary exhaustivity.  The original 25% on four
synthetic offers did not satisfy SC-004 and was incorrectly extrapolated.

## Spec Kit operation

- `specify 1.2.2` is installed.
- Ten Codex skills and ten OpenCode commands are present; both manifests match
  their file hashes.
- All bundled shell scripts pass `bash -n`; JSON manifests parse.
- `check-prerequisites.sh` resolves both feature 001 and feature 002 with their
  spec/plan/tasks paths.
- `opencode v2.0.32` is installed and `opencode debug config` detects this
  worktree's `.opencode` directory.
- No model invocation was made merely to prove command discovery.  Therefore
  the filesystem/configuration integration is verified; an interactive
  `$speckit-*` Codex invocation and `/speckit.*` OpenCode model run remain to be
  confirmed in a newly opened session rooted at this RC.

## Constitution correction

Version 1.1 permits bounded queries to documented public job sources and local
models.  Cloud remains opt-in for exact provider/model/purpose/content and must
be verified zero-cost; unknown pricing and paid fallbacks are forbidden.
Private data cannot leave the Mac without a consent envelope.  SQLite evolution
is additive and backed up, rather than misleadingly described as migration-free.

## Second Spec Kit cycle

`002-international-geographic-exclusions` is implemented:

- France and Paris are visible editable exclusions on first use;
- missing or mixed geography stays `to_verify`;
- excluded places are `non_conforming` before ranking;
- saved empty exclusions remain empty;
- the policy reaches Greenhouse, public ATS connectors, stored matching and
  the Career UI;
- tests and real local HTTP responses verify the contract.

HTTP smoke evidence on port 8964: `/career` = 200, `/v5` = 200; the API returned
France, Paris, `require_known_location=true`, Stage/CDD/CDI/VIE and January to
March, and the three new controls were present in the served HTML.

## Validation

- Combined Career, qualification, migration, Explorer and application-eval
  targeted suite: 184 passed.
- Isolated real-handler evaluation: 22 passed; its Career evidence imports a
  synthetic job, reads it through the production HTTP router and applies the
  production qualifier under explicit criteria.
- Static checks: Python compile, `node --check`, Ruff and `git diff --check`
  pass.
- Full-suite final result: 1283 passed, 1 skipped, 0 failed in 106.58 seconds.
  The skip is the private-corpus exhaustivity guard described above; the real
  121-offer aggregate was measured separately from an isolated SQLite backup.

## Delegation

Four independent, non-overlapping OpenCode Go missions are ready in
`docs/career_intl/SPECKIT_OPENCODE_QUEUE.md`: official-source trust, date and
deadline evidence, prerequisite/profile fit, and coverage/health evidence.

## Rollback

Revert the RC commit(s).  Because derived qualification is stored separately,
the `jobs` source facts and user corrections do not depend on the snapshot
table.  Do not drop a populated table without a private backup and explicit
human approval.
