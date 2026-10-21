# Contract: qualify_offer() Interface

## Function Signature

```python
def qualify_offer(offer: dict[str, Any], *,
                  minimum_duration_months: int = 6,
                  required_start_month: int | None = None,
                  allowed_contract_types: list[str] | tuple[str, ...] | None = None,
                  allowed_start_months: list[int] | tuple[int, ...] | None = None,
                  minimum_stage_duration_months: int | None = None,
                  as_of: date | None = None) -> QualifiedOffer
```

## Input Contract

**`offer`** (dict): Normalized offer with at minimum:
- `description_original` (str): Full offer text (required for qualification)
- `title` (str): Offer title
- `employment_type` (str): Connector-provided contract type (may be empty)
- `source_name` (str): Connector identifier
- `source_id` (str): Connector-specific offer ID
- `official_url` (str): Canonical offer URL
- `source_verified` (bool): True if connector successfully read official feed
- `posted_date` (str|None): ISO date
- `start_date` (str|None): ISO date
- `end_date` (str|None): ISO date
- `duration_months` (int|None): Connector-provided duration
- `duration_min_months` (int|None): Connector-provided min duration
- `duration_max_months` (int|None): Connector-provided max duration
- `language` (str|None)
- `country` (str|None)
- `city` (str|None)
- `source_status` (str|None): "open", "closed", etc.
- `deadline_date` (str|None): ISO date
- `deadline_status` (str|None): "open", "closed"

**Optional Parameters** (with defaults matching current Career Explorer defaults):
- `minimum_duration_months`: 6 (minimum internship duration)
- `required_start_month`: None (deprecated, use `allowed_start_months`)
- `allowed_contract_types`: ["stage", "cdd", "cdi", "vie"] → mapped to ["internship", "fixed_term", "permanent", "VIE"]
- `allowed_start_months`: [1, 2, 3] (Jan-Mar)
- `minimum_stage_duration_months`: None (defaults to `minimum_duration_months`)
- `as_of`: None (defaults to `date.today()`)

## Output Contract

**Returns**: `QualifiedOffer` dataclass with all fields documented in `data-model.md`.

**Guarantees**:
- Pure function: no I/O, no side effects, deterministic
- All `provenance` values are `FactEvidence` with non-empty `quote` when `value` is not None
- `missing_fields` contains only fields genuinely absent from source
- `target_status` is one of {"conforming", "to_verify", "non_conforming"}
- `reasons` is non-empty tuple explaining the status

## Error Contract

- Raises `TypeError` if `offer` is not a dict
- Raises `ValueError` if duration limits outside 1-24 range
- Raises `ValueError` if `allowed_start_months` contains invalid months

---

# Contract: Import Pipeline Qualification Integration

## Entry Point: `import_jobs(offers: list[dict], ..., db: sqlite3.Connection)`

**Current Behavior**: Upserts offers into `jobs` table, preserving non-NULL existing values.

**New Behavior**: For each offer:
1. Call `qualify_offer(offer)` with Career Explorer defaults
2. Extract qualification fields and citations
3. Include in upsert with `COALESCE(existing, new)` for qualification columns

## Entry Point: `refresh_jobs(job_ids: list[int], ..., db: sqlite3.Connection)`

**Current Behavior**: Re-fetches offers from source, normalizes, upserts.

**New Behavior**: Same qualification integration as `import_jobs()`.

## Database Contract: `jobs` Table Upsert

**Columns Updated** (only when existing is NULL):
- `start_date`, `end_date`, `duration_months`, `employment_type`
- `calendar_status`, `calendar_reason`
- `start_quote`, `duration_quote`, `contract_quote`, `facts_source`, `qualification_missing`

**Preservation Rule**:
```sql
COALESCE(jobs.start_date, NEW.start_date) AS start_date,
COALESCE(jobs.end_date, NEW.end_date) AS end_date,
...
```

**Audit Log Entry**:
```python
log_audit(db, job_id=job_id, action="qualification_update",
          details={"fields_updated": [...], "fields_missing": [...], "target_status": "..."})
```

---

# Contract: Migration Script

## Function Signature

```python
def ensure_qualification_columns(db: sqlite3.Connection) -> None:
    """Ensure all qualification citation columns exist in jobs table.

    Idempotent: no-op if columns already present.
    """
```

## Columns to Ensure

| Column | SQL Type |
|--------|----------|
| `start_quote` | TEXT |
| `duration_quote` | TEXT |
| `contract_quote` | TEXT |
| `facts_source` | TEXT |
| `qualification_missing` | TEXT |

## Implementation

```python
def ensure_qualification_columns(db: sqlite3.Connection) -> None:
    existing = {row[1] for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
    to_add = {
        "start_quote": "TEXT",
        "duration_quote": "TEXT",
        "contract_quote": "TEXT",
        "facts_source": "TEXT",
        "qualification_missing": "TEXT",
    }
    for col, typ in to_add.items():
        if col not in existing:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
    db.commit()
```

Called at module load in `career/service.py` (e.g., in `get_db()` or `init_db()`).
