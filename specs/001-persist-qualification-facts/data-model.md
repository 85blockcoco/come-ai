# Data Model: Persist Qualification Facts

> **Superseded:** the reviewed data model is the separate
> `job_qualification_snapshots` table described in `REVIEW_AND_AMENDMENT.md`.
> The denormalized citation columns below are retained only as historical
> context and must not be implemented.

## Entity: Offer (jobs table)

### Current Schema (partial)

```sql
CREATE TABLE jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_id TEXT NOT NULL,
    official_url TEXT,
    apply_url TEXT,
    company TEXT,
    title TEXT,
    city TEXT,
    country TEXT,
    posted_date TEXT,           -- ISO date
    deadline_date TEXT,         -- ISO date
    start_date TEXT,            -- ISO date (NEW - currently exists but empty)
    end_date TEXT,              -- ISO date (NEW - currently exists but empty)
    duration_months INTEGER,    -- (NEW - currently exists but empty)
    employment_type TEXT,       -- (NEW - currently exists but empty)
    role_level TEXT,
    requirements TEXT,
    languages_required TEXT,
    eligibility_requirement TEXT,
    description_original TEXT,
    job_family TEXT,
    source_status TEXT,
    source_verified INTEGER,
    calendar_status TEXT,       -- "conforming" | "to_verify" | "non_conforming"
    calendar_reason TEXT,
    last_verified_at TEXT,      -- ISO datetime
    seen_at TEXT,               -- ISO datetime
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_name, source_id)
);
```

### New Columns to Add

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `start_quote` | TEXT | YES | NULL | Verbatim quote from source for start_date |
| `duration_quote` | TEXT | YES | NULL | Verbatim quote from source for duration_months |
| `contract_quote` | TEXT | YES | NULL | Verbatim quote from source for employment_type |
| `facts_source` | TEXT | YES | NULL | Provenance source: "source_field", "description_passage", "title_passage", "source_date_range", "description_passage_unverified" |
| `qualification_missing` | TEXT | YES | NULL | JSON array of missing field names from qualification |

### Column Details

#### `start_quote`
- **Source**: `QualifiedOffer.provenance["start_month"].quote` or `provenance["start_year"].quote`
- **Format**: Exact substring from `description_original` or `title`
- **Example**: "Starting June 2027", "June 2027 - July 2027"
- **Validation**: Must be non-empty if `start_date` is non-NULL

#### `duration_quote`
- **Source**: `QualifiedOffer.provenance["duration_min_months"].quote` or `provenance["duration_max_months"].quote`
- **Format**: Exact substring from `description_original`
- **Example**: "6 months", "6-12 months", "12 weeks"
- **Validation**: Must be non-empty if `duration_months` is non-NULL

#### `contract_quote`
- **Source**: `QualifiedOffer.provenance["contract_type"].quote`
- **Format**: Exact matched phrase from `employment_type` or `title` or `description_original`
- **Example**: "Stage", "Internship", "CDD", "Alternance"
- **Validation**: Must be non-empty if `employment_type` is non-NULL and not "unknown"/"ambiguous"

#### `facts_source`
- **Source**: `QualifiedOffer.provenance[field].source` (normalized)
- **Values**:
  - "source_field" — from structured connector field
  - "description_passage" — from regex extraction in description
  - "title_passage" — from regex extraction in title
  - "source_date_range" — computed from start_date + end_date fields
  - "description_passage_unverified" — from description but source_verified=False
- **Validation**: Must be non-empty if any qualification fact is non-NULL

#### `qualification_missing`
- **Source**: `QualifiedOffer.missing_fields` (tuple → JSON array)
- **Format**: `["publication", "début", "durée", "lien officiel valide", ...]`
- **Validation**: Valid JSON array of strings; empty array if no missing fields

---

## Entity: Qualification Provenance (QualifiedOffer)

### Input to Persistence

```python
@dataclass(frozen=True)
class QualifiedOffer:
    contract_type: str                    # → employment_type
    contract_status: str                  # "confirmed" | "excluded" | "unknown" (informational)
    posted_date: str | None               # → posted_date (if not already set)
    start_date: str | None                # → start_date
    end_date: str | None                  # → end_date
    start_month: int | None               # Used for quote extraction
    duration_min_months: int | None       # → duration_months (canonical min)
    duration_max_months: int | None       # Provenance only
    language: str | None
    country: str | None
    city: str | None
    source_name: str
    source_id: str
    official_url: str
    verification_status: str              # "verified" | "unverified"
    target_status: str                    # → calendar_status
    missing_fields: tuple[str, ...]       # → qualification_missing (JSON)
    provenance: dict[str, FactEvidence]   # → citation columns
    reasons: tuple[str, ...]              # → calendar_reason (first)
```

### FactEvidence

```python
@dataclass(frozen=True)
class FactEvidence:
    value: Any
    source: str          # "source_field:field_name" | "description_passage" | "title_passage" | "source_date_range"
    quote: str           # Verbatim source text
```

---

## Validation Rules

1. **Start Date Consistency**: If `start_date` is set, `start_quote` MUST be non-empty and `facts_source` MUST be non-empty.

2. **Duration Consistency**: If `duration_months` is set, `duration_quote` MUST be non-empty and `facts_source` MUST be non-empty.

3. **Contract Type Consistency**: If `employment_type` is set and not in {"unknown", "ambiguous"}, `contract_quote` MUST be non-empty and `facts_source` MUST be non-empty.

4. **Calendar Status Validity**: `calendar_status` MUST be one of {"conforming", "to_verify", "non_conforming"}.

5. **Missing Fields Format**: `qualification_missing` MUST be valid JSON array of strings.

6. **Idempotency**: Re-running qualification on unchanged `description_original` produces identical column values.

7. **Preservation**: Non-NULL existing values in `jobs` for qualification columns are never overwritten by import/refresh.

---

## State Transitions

### Offer Import (New Offer)

```
Raw Offer → normalize_and_store() → qualify_offer() → INSERT with all qualification columns
```

### Offer Refresh (Existing Offer)

```
Existing Offer → re-fetch → normalize → qualify_offer() → UPDATE with COALESCE(existing, new) for qualification columns
```

### User Correction

```
User edits field in UI → UPDATE jobs SET field = user_value → Subsequent refresh preserves user_value (COALESCE)
```

---

## Relationships

- **Offer ↔ Audit Log**: One-to-many (`career_audit_log.job_id` → `jobs.job_id`)
- **Offer ↔ Provenance**: Embedded in offer row (denormalized for read performance)
- **Offer ↔ Deduplication**: `dedup_id` computed from best record (unchanged by this feature)

---

## Migration Script Interface

```python
def migrate_qualification_columns(db_path: str) -> None:
    """Add qualification citation columns to jobs table if not present.

    Idempotent: safe to call multiple times.
    """
    # Check PRAGMA table_info(jobs) for each column
    # ALTER TABLE jobs ADD COLUMN column_name TYPE for missing columns
    # No data migration needed (all nullable)
```

Called from `career/service.py` initialization (e.g., in `get_db()` or module load).
