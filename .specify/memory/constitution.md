# Côme AI Constitution

## Core Principles

### I. Career-First Priority
Every feature, fix, and architectural decision must serve the Career Explorer mission: helping the user find, qualify, and apply to relevant internships and graduate roles. No generic feature work that doesn't directly improve offer discovery, qualification, deduplication, profile matching, or application preparation.

### II. Maximum Quality, Zero Unapproved Spend
Deterministic local code remains the default for extraction, qualification,
deduplication and matching. Public, documented job sources may be queried with
bounded rate limits, timeouts, an identifiable User-Agent and honest health
reporting. Local models may be used without cloud consent. Cloud models are
allowed only after explicit consent for the exact transmitted content and
purpose, and only when the selected route is verified free or has a zero-cost
policy. Unknown pricing, paid fallback and automatic credit purchases are
forbidden.

### III. Privacy by Design
- No private or personal data leaves this Mac without a signed consent envelope
  (`consent_guard/`) for the exact provider, model, purpose and content.
- Public job-search requests and official public job postings are not private
  data; they may use the bounded public-source connectors above without a
  personal-data consent envelope.
- Source files are never overwritten; outputs go to `output/` only.
- SQLite stores extracted text and metadata only; original file paths are never persisted.
- Secure deletion for personal data; permissions `0700` on `data/`, `output/`, `logs/`, `memory_data/`, `career_data/`, `state/`.
- No real personal data in fixtures, tests, or repository.

### IV. Mandatory Evidence & Provenance
Every fact displayed to the user must carry a verifiable citation: source field, quote, and offset in the original text. `qualify_offer()`, `deduplicate_jobs()`, and all extractors return `provenance` maps. UI renders citations inline. "Unknown" is preferred over inferred.

### V. Test-First, Proof-Required (NON-NEGOTIABLE)
- TDD mandatory for demonstrated defects: test written → failure reproduced →
  implementation → green regression test. Isolated, reversible work does not
  require a human pause between these local steps.
- Red-Green-Refactor cycle strictly enforced.
- Every modification passes `pytest` then `ruff` before commit.
- Synthetic truth corpora for deduplication, qualification, and exhaustivity; precision/recall/F1 measured and gatekept.
- No "trust me" — every claim has a test or a measurable report.

### VI. Git Protected, Supervised Autonomy
- `main` branch is protected; all work happens in isolated branches/worktrees.
- No merge to `main`, no push, no release without explicit user approval.
- Agents operate in controlled worktrees with documented handoffs.
- Spec Kit specifications, plans, and tasks are the contract between human intent and agent execution.

### VII. Simplicity & Observability
- Start simple (YAGNI); prefer pure functions over classes; text I/O for debuggability.
- Structured logging required; progress is honest (real steps, not fake estimates).
- Cooperative cancellation at checkpoints; bounded results and secret scrubbing.

## Additional Constraints

### Technology Stack
- Python 3.12+, SQLite (FTS5), vanilla JS/CSS (no build step), local-only HTTP server on `127.0.0.1:8765`.
- Dependencies: `uv`/`pip` for Python; no `npm`, no Docker, no cloud services.
- Ruff for linting; pytest for testing; `rich` for CLI output.

### Data Integrity
- Idempotent imports (content-hash deduplication).
- WAL mode SQLite; read-only connections for reporting.
- Additive schema evolution only, with a private consistent backup before every
  versioned SQLite migration and an explicit rollback path.

### Career-Specific Rules
- Offer qualification uses only facts present in the source payload. Public web
  research may verify or enrich an offer only when the resulting fact retains
  its own URL, retrieval date and quoted evidence; it never silently replaces
  the official source.
- Deduplication conserves all provenances; contradictions stay visible; user relevance scores never decide merges.
- Profile matching is explainable: every score component has a traceable rule.
- Application Studio produces complete, citation-backed kits (CV, letter, prep sheet) in one click.

## Governance

Constitution supersedes all other practices. Amendments require:
1. Written specification via `/speckit-specify`
2. Plan via `/speckit-plan`
3. Tasks via `/speckit-tasks`
4. Implementation + convergence
5. User approval of test results and measurable improvement

**Version**: 1.1.0 | **Ratified**: 2026-10-20 | **Last Amended**: 2026-10-21
