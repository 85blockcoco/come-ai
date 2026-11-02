# Research: Venture Capital Revision Coach

**Feature**: `004-venture-capital-revision` | **Date**: 2026-11-02

This document records the decisions that shape the implementation. Each decision
states the problem, the options considered, the choice, and the consequences.

## R1. Storage: JSON/JSONL instead of SQLite

**Problem**: Store card progress, review events, sessions, notes metadata, exams
and reports locally.

**Options**:
1. SQLite with migrations (like Career).
2. JSON state + JSONL append-only events.
3. In-memory only.

**Decision**: JSON state + JSONL events, under `~/.nage/vc/`.

**Rationale**: the dataset is small (one learner, thousands of events), the
feature must stay debuggable, and the existing academics toolkit already uses
JSON/JSONL. JSON avoids a schema migration for every content change and keeps
the feature independent from Career's SQLite. Atomic writes (`os.replace`) and
append-only review events provide crash safety.

**Consequences**: no SQL queries; the radar and report aggregate events in
Python. This is acceptable at the target scale (10,000 events < 500 ms). If the
dataset grows beyond 100,000 events, a read-only SQLite index can be added
without changing the public API.

## R2. Scheduling: explicit SM-2-inspired algorithm

**Problem**: Decide which cards are due and when a card returns.

**Options**:
1. Fixed Leitner boxes.
2. SM-2 / Anki-style ease factor.
3. FSRS (machine-learned).
4. Random selection.

**Decision**: a small SM-2-inspired algorithm with four grades
(`again`, `hard`, `good`, `easy`), an ease factor bounded to `[1.3, 3.0]`, and
explicit intervals.

**Rationale**: SM-2 is transparent, testable, and needs no training data. FSRS
would be better with thousands of reviews but is opaque and harder to audit.
The learner must be able to understand why a card is proposed (FR-041).

**Rules**:
- `again`: repetitions = 0, interval = 0 (due today), ease -0.20.
- `hard`: interval = max(1, round(interval × 1.2)), ease -0.15.
- `good`: first review = 1 day, second = 3 days, then round(interval × ease).
- `easy`: first review = 2 days, second = 5 days, then round(interval × ease × 1.3), ease +0.15.
- Ease is clamped to `[1.3, 3.0]`; interval is capped at 365 days.
- New cards are introduced in curriculum order, never more than the session
  limit.
- Due cards are ordered by `due_date`, then topic order, then card id. This is
  deterministic.

**Consequences**: the scheduler is explainable and testable. It is not
"optimal" like FSRS, but it is honest and sufficient for one exam cycle.

## R3. Content: original JSON packs with provenance

**Problem**: Provide hundreds of cards, drills, cases and glossary entries
without copying a manual or a professor's slides.

**Options**:
1. Scrape a textbook.
2. Generate content with a cloud model.
3. Write original content and cite imported notes.
4. Ask the user to paste everything.

**Decision**: original content packs in JSON, written by the project, plus
user-imported notes that stay local and carry citations.

**Rationale**: copyright and privacy. Cloud generation is forbidden by the
constitution without consent, and even with consent it would not guarantee
accuracy. Original content can be reviewed, versioned and corrected.

**Content pack fields**: `schema_version`, `pack_id`, `topic`, `language`,
`source_type` (`original`, `user_note`, `public_domain`), `license`, `items`.
Every imported item must include `citation` with `source_id`, `locator` and
`quote`. No item may have `source_type: original` while containing a verbatim
textbook excerpt.

**Consequences**: content work is explicit and reviewable. The backlog includes
per-topic content missions so coverage is measurable.

## R4. Numeric grading: deterministic with unit normalization

**Problem**: Grade VC calculations without a model, while accepting common
units and conventions.

**Options**:
1. Exact string match.
2. Float comparison with a fixed epsilon.
3. Normalize units and compare with a per-drill tolerance.
4. LLM judge.

**Decision**: parse the answer into `(value, unit)`, normalize to the drill's
canonical unit, compare with an absolute and relative tolerance, and diagnose
common wrong paths.

**Rationale**: deterministic, offline, testable. LLM judging would be
non-deterministic and would send data out.

**Normalization**:
- money: `k€` = 1,000 €, `M€` = 1,000,000 €, `m€` accepted, `€` canonical;
- percentages: `12%` = `0.12`, but a drill may declare `answer_unit: "percent"`
  and then expect `12`;
- ratios: `2.5x` = `2.5`;
- thousands separators: spaces and commas are accepted when unambiguous;
- non-numeric input is rejected with a readable message and no state loss.

**Error diagnosis**: each drill declares `error_paths`, a mapping from a common
wrong value/formula to a category:
`formula`, `order`, `unit`, `missing_data`, `convention`.
Example: answering pre-money when post-money is asked maps to `formula`.

## R5. Case evaluation: rubric criteria, not a single score

**Problem**: Evaluate open case answers without a model.

**Options**:
1. Keyword count only.
2. Rubric criteria with required concepts and numeric checks.
3. Manual self-assessment only.
4. LLM judge.

**Decision**: each case has `questions`, and each question has `criteria`.
A criterion declares `id`, `label`, `weight`, `required_keywords` (all/any),
`expected_numbers` (value + tolerance), and `model_answer`. The evaluator
returns a per-criterion result and a total. It also extracts numbers from the
answer and flags any number that is neither in the case facts nor a declared
intermediate result.

**Rationale**: transparent, deterministic, and honest about its limits. The
model answer is shown after submission so the learner can compare reasoning.

**Consequences**: free-text nuance is not fully graded. The UI must say
"correction par critères" and invite self-review; it must not claim human-level
grading.

## R6. Notes ingestion: rule-based extraction with citations

**Problem**: Turn the learner's notes into cards without inventing content.

**Options**:
1. Generative summarization.
2. Rule-based definition/question extraction.
3. Manual card creation only.

**Decision**: rule-based extraction for definitions, lists and explicit
question/answer pairs, with a citation for every proposal. Every proposed card
starts in `proposed` state and requires explicit approval.

**Rationale**: privacy and accuracy. A rule-based extractor can be wrong, but it
can always show the exact source line. When no certain answer is found, the card
is `a_completer`, never invented.

**Supported inputs (MVP)**: `.txt`, `.md`, and text-based `.pdf` via `pypdf`.
Scanned PDFs without a text layer are rejected with a clear message.

**Patterns**:
- `Term : definition` and `Term — definition`;
- `**Term** : definition`;
- `Q: ...` / `R: ...` pairs;
- bullet lists under a heading become cloze candidates only when the heading
  provides the question; otherwise they are marked `a_completer`.

**Consequences**: recall is lower than an LLM, but precision and provenance are
high. The backlog includes extractor improvements and a review UI.

## R7. Interface: CLI first, HTTP second

**Problem**: Deliver a usable revision tool quickly.

**Options**:
1. Web UI first.
2. CLI first with JSON output.
3. Desktop app.

**Decision**: CLI first (`nage.py vc ...`), then a bounded local HTTP facade and
a small static page.

**Rationale**: the CLI is testable, scriptable, and consistent with the existing
`nage.py` toolkit. A web UI can reuse the same pure functions later without
blocking the learning loop.

**Consequences**: the MVP is terminal-based. The quickstart documents every
command. JSON output is stable for automation and tests.

## R8. Storage location and privacy

**Decision**: default `~/.nage/vc/`; override with `NAGE_VC_HOME` for tests and
portable installs. Directories are created with mode `0700`; files with `0600`.
The repository contains no learner data. `.gitignore` includes `.nage/` and
`vc_data/`.

**Consequences**: backups are the user's responsibility; the app documents the
path. Deleting all VC data requires an explicit confirmation phrase and removes
only `~/.nage/vc/`, never Career data.

## R9. Determinism and time

**Decision**: every public function accepts an optional `today` (ISO date) and
`seed` where randomness is needed. The scheduler uses the injected date, not
`datetime.now()`, except at the CLI boundary. Exam composition uses
`random.Random(seed)` and stable sorts.

**Consequences**: tests are reproducible; the same inputs produce the same
output; the CLI remains convenient.

## R10. Content coverage strategy

**Decision**: 20 topics, each with a pack. Program completion targets:
- 10+ cards per topic (200+ total);
- 3+ drills per topic where quantitative (100+ total);
- 1+ case per topic (20+ total);
- 5+ exam questions per topic (100+ total);
- 6+ glossary terms per topic (120+ total).

**Rationale**: coverage is measurable (SC-014) and the backlog can assign one
topic per work packet. The MVP ships 4 topics fully and the rest as the backlog
is executed.

## R11. Testing strategy

**Decision**:
- unit tests per module with synthetic content;
- property-style checks for scheduler invariants (no card lost, due date
  monotonic after `good`/`easy`, no negative interval);
- CLI tests with `tmp_path` and JSON output;
- no network, no real notes, no real personal data;
- targeted suites during development; full suite sequential before release.

**Consequences**: fast feedback; the full suite remains the release gate.

## R12. Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| Cloud LLM for card generation | Privacy, cost, non-determinism, constitution. |
| FSRS | Needs review history; opaque to the learner. |
| SQLite for MVP | Overkill for one learner; migration overhead. |
| Scraping textbooks | Copyright risk. |
| Auto-grading free text with keywords only | Misleading; rubric + self-review is more honest. |
| Storing notes in the repository | Privacy breach. |
