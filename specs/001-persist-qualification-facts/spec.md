# Feature Specification: Persist Qualification Facts

> **Reviewed 2026-10-21:** success claims and implementation details are
> amended by `REVIEW_AND_AMENDMENT.md`. In particular, 25% on four synthetic
> offers is not proof of the 55% global target.

**Feature Branch**: `001-persist-qualification-facts`

**Created**: 2026-10-20

**Status**: Draft

**Input**: User description: "Persist the facts already extracted by qualify_offer() (start_date, end_date, duration_months, employment_type) back to the jobs table, with provenance citations, so that offer summaries display complete information without additional API calls."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See Complete Offer Details in Career Explorer (Priority: P1)

As a Career Explorer user, I want to see the start date, end date, duration, and contract type for every offer in the list and detail view, so that I can filter and prioritize applications without manually opening each source page.

**Why this priority**: The AUTO-001 audit shows 424 recoverable fact pairs (56.7% of the gap) are already extracted by `qualify_offer()` but discarded on import. This is the single largest lever to improve exhaustivity from 11.7% to ≥55%.

**Independent Test**: Can be fully tested by running an exploration, then querying the `jobs` table for non-empty `start_date`, `end_date`, `duration_months`, `employment_type` on offers that have these facts in `description_original`, and verifying the UI displays them.

**Acceptance Scenarios**:

1. **Given** an offer in `jobs` with `description_original` containing a clear start month and duration (e.g., "Starting June 2027, 6 months"), **When** the exploration import runs, **Then** `start_date`, `end_date`, `duration_months`, and `employment_type` are populated in `jobs` with values derived from `qualify_offer()`.

2. **Given** an offer already in `jobs` with empty qualification fields, **When** a re-import or refresh runs, **Then** the fields are updated from `qualify_offer()` without overwriting user-entered data.

3. **Given** an offer where `qualify_offer()` cannot determine a fact (returns None), **When** import runs, **Then** the field remains NULL and `missing_fields` in the qualification provenance records the gap.

---

### User Story 2 - Provenance Citations Visible in UI (Priority: P1)

As a Career Explorer user, I want to see a citation link or tooltip for each qualification fact (start date, duration, contract type) showing the exact quote from the source text, so that I can verify the information myself.

**Why this priority**: Constitution Principle IV (Mandatory Evidence & Provenance) requires every displayed fact to carry a verifiable citation. The `qualify_offer()` provenance map already provides this; it must be persisted and rendered.

**Independent Test**: Can be tested by inspecting the `jobs` table for citation columns (`start_quote`, `duration_quote`, `contract_quote`, `facts_source`) and verifying the UI renders them as tooltips or inline citations.

**Acceptance Scenarios**:

1. **Given** an offer with `start_date` populated from `qualify_offer()`, **When** viewing the offer card or detail, **Then** a citation indicator appears next to the start date showing the source quote (e.g., "Starting June 2027").

2. **Given** an offer with `employment_type` = "internship" from description, **When** viewing the offer, **Then** the contract type badge shows a tooltip with the matched phrase (e.g., "Stage", "Internship").

---

### User Story 3 - Calendar Status Reflects Real Dates (Priority: P2)

As a Career Explorer user, I want the `calendar_status` field to reflect actual start dates and durations from the source, so that "Dates and duration not specified" only appears when truly unknown.

**Why this priority**: Currently 121/121 offers show `calendar_status = 'to_verify'` with reason "Dates and duration not specified" even though 44 offers have dates/durations in their text. This misleads prioritization.

**Independent Test**: Can be tested by counting offers with `calendar_status != 'to_verify'` after import, targeting < 60 offers with the "dates" reason (down from 121).

**Acceptance Scenarios**:

1. **Given** an offer with a qualified `start_date` and `duration_months` ≥ minimum, **When** import runs, **Then** `calendar_status` becomes `conforming` or `to_verify` with a specific reason (not the generic "Dates and duration not specified").

2. **Given** an offer with no dates in source text, **When** import runs, **Then** `calendar_status` remains `to_verify` with reason "Dates and duration not specified".

---

### Edge Cases

- What happens when `qualify_offer()` returns `contract_type = "ambiguous"`? → Store `employment_type = "ambiguous"` and include the conflicting quotes in provenance.
- What happens when multiple imports disagree on a fact? → Keep the most recent verified qualification; log the conflict in `career_audit_log`.
- What happens when `description_original` is empty? → All qualification fields stay NULL; provenance records "no description".
- What happens when `source_verified` is False? → Still persist facts but mark `facts_source = "description_passage_unverified"`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST call `qualify_offer()` for each imported/updated offer during the import pipeline.
- **FR-002**: System MUST persist `start_date`, `end_date`, `duration_months`, `employment_type` from `QualifiedOffer` to the `jobs` table.
- **FR-003**: System MUST persist provenance citations: `start_quote`, `duration_quote`, `contract_quote`, `facts_source` (values: "source_field", "description_passage", "title_passage", "source_date_range").
- **FR-004**: System MUST persist `missing_fields` from qualification as a JSON array in `qualification_missing` column.
- **FR-005**: System MUST update `calendar_status` and `calendar_reason` based on `QualifiedOffer.target_status` and `reasons`.
- **FR-006**: System MUST NOT overwrite non-NULL user-entered values in `jobs` (preserve manual corrections).
- **FR-007**: System MUST log qualification outcome (fields updated, missing, status) to `career_audit_log` for traceability.
- **FR-008**: System MUST handle `contract_type = "ambiguous"` by storing the value and all conflicting quotes in provenance.
- **FR-009**: System MUST be idempotent: re-running import on unchanged offers produces identical `jobs` rows.

### Key Entities

- **Offer (jobs table row)**: Represents a discovered internship/graduate role. Key attributes: `source_name`, `source_id`, `official_url`, `description_original`, and now `start_date`, `end_date`, `duration_months`, `employment_type`, `calendar_status`, `calendar_reason`, citation fields.
- **Qualification Provenance**: The `provenance` map from `QualifiedOffer` carrying `FactEvidence` (value, source, quote) for each extracted fact.
- **Import Pipeline**: The code path in `career/service.py` (methods `import_jobs`, `refresh_jobs`) and `career/discovery.py` that normalizes and stores offers.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `posted_date` + `start_date` populated on ≥ 44/121 offers (36.4%, up from 17/121 = 14.0%).
- **SC-002**: `employment_type` populated on ≥ 120/121 offers (99.2%, up from 20/121 = 16.5%).
- **SC-003**: Offers with `calendar_status = 'to_verify'` for reason "Dates and duration not specified" reduced to < 60/121 (down from 121/121).
- **SC-004**: Global exhaustivity (fiche) for dates + contract type ≥ 55% (up from 11.7%).
- **SC-005**: 100% of persisted qualification facts have a non-empty citation quote traceable to `description_original`.
- **SC-006**: Zero regression on existing tests (`pytest -q` passes).
- **SC-007**: Import pipeline latency increase < 10% per offer (qualification is fast, pure Python).

## Assumptions

- The `qualify_offer()` function in `career/offer_qualification.py` is the single source of truth for qualification logic and already returns all needed fields with provenance.
- The `jobs` table schema can be extended with new columns via additive migration (SQLite ALTER TABLE ADD COLUMN).
- The import pipeline in `career/service.py` is the only write path for `jobs` (no other code bypasses it).
- UI rendering in `career_static/career.js` will be updated separately to display the new fields and citations (out of scope for this spec, but required for user value).
- No external API calls are introduced; all qualification remains local and deterministic.
- The `career_data/career.sqlite3` database is the only persistence layer for offers.
