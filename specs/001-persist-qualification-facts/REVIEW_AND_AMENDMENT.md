# Review and amendment — 001 Persist Qualification Facts

This file is the binding review of the Nemotron delivery.  Where it conflicts
with the original plan, data model, tasks or integration summary, this review
wins.

## Verified defects in the original implementation

1. The claimed 55% global exhaustivity target was not measured.  The reported
   result was 25% on four synthetic offers and cannot be extrapolated.
2. The exhaustivity pytest was skipped because it referenced a script and
   database in another checkout.  It was not an active CI gate.
3. Three of the four full-suite failures were introduced by schema v8 because
   migration-version and backup guarantees were not updated.  The fourth was
   pre-existing on the old base and is fixed on current `main`.
4. Creating an exact first day from a month/year and an exact last day from a
   duration invented source facts.
5. One `facts_source` value collapsed field-level provenance.  `COALESCE` on
   citations also retained stale evidence after a changed source import.
6. `payload.pop("qualification")` mutated the caller's object.

## Accepted architecture

- Raw and user-edited columns in `jobs` remain untouched by derived
  qualification.
- One additive `job_qualification_snapshots` table stores bounded JSON facts,
  field-level provenance, missing fields, reasons, a source fingerprint and a
  timestamp.
- A supplied qualification replaces the previous derived snapshot.  An import
  without qualification preserves the last snapshot.  This makes repeated
  imports deterministic while allowing changed source evidence to refresh.
- Deleting a job cascades to its snapshot.
- Application summaries read the snapshot and keep missing values explicit.
- No exact date is synthesized from a month-only observation.

## Revised success criteria

- Migration from every supported schema version creates a private consistent
  backup and preserves existing data.
- Imports do not mutate their input and do not overwrite raw/user fields with
  derived facts.
- Repeated imports refresh changed provenance and preserve a snapshot when no
  new qualification was supplied.
- Targeted and full test suites pass on the current V3 base.
- Measurements report the exact corpus size and observed percentages.  A
  four-offer result is never described as a global 121-offer result.
- A product-wide 55% summary target remains a future objective because this
  feature only addresses contract, start and duration; it cannot honestly
  supply education, remuneration, missions or conditions.

## Rollback

Revert the feature commit.  The additive snapshot table may remain unused; no
raw `jobs` value depends on it.  Removing a populated table requires separate
human approval and a backup.
