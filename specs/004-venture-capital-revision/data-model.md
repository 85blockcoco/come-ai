# Data Model: Venture Capital Revision Coach

**Feature**: `004-venture-capital-revision` | **Date**: 2026-11-02

All learner data is stored outside the repository, under `~/.nage/vc/`
(override: `NAGE_VC_HOME`). Built-in content packs are read-only repository
files. The model below is the contract for the CLI, the Python API and the
optional HTTP facade.

## Storage Layout

```text
~/.nage/vc/
├── progress.json          # card scheduling state, one record per card
├── reviews.jsonl          # append-only review events
├── sessions/
│   ├── active.json        # current interrupted session (if any)
│   └── history.jsonl      # completed session summaries
├── deck.json              # user-approved imported cards (proposed/rejected/active)
├── notes/
│   ├── index.json         # imported note sources and citations
│   └── <source_id>.txt    # normalized text snapshot (local only)
├── exams/
│   ├── active.json        # current mock exam
│   └── history.jsonl      # completed exam summaries
├── reports/
│   └── <date>-progress.md # generated reports
└── settings.json          # language, exam date, daily capacity
```

Atomic write protocol: write to `<name>.tmp` in the same directory, `fsync`,
then `os.replace`. Append-only JSONL files are opened with `O_APPEND`.

## Entities

### CourseTopic

A curriculum theme.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Stable code, e.g. `VC04`. |
| `code` | string | yes | Display code. |
| `title_fr` | string | yes | French title. |
| `title_en` | string | yes | English title. |
| `order` | integer | yes | Curriculum order. |
| `prerequisites` | list[string] | no | Topic ids. |
| `exam_weight` | number | yes | 0..1, used by the planner. |
| `description` | string | yes | Original summary. |

Invariants: ids unique; `order` unique; prerequisites exist; `exam_weight` in
`[0, 1]`.

### Concept

An atomic notion inside a topic.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Stable. |
| `topic_id` | string | yes | FK CourseTopic. |
| `term_fr` | string | yes | French term. |
| `term_en` | string | yes | English term. |
| `definition` | string | yes | Original wording. |
| `source_type` | enum | yes | `original`, `user_note`, `public_domain`. |
| `citation` | object | conditional | Required when `source_type != original`. |

### Flashcard

A question/answer pair used in active recall.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Stable, e.g. `VC04-C03`. |
| `topic_id` | string | yes | FK CourseTopic. |
| `question` | string | yes | Must be answerable from the course. |
| `answer` | string | yes | Expected answer. |
| `explanation` | string | no | Why it matters. |
| `source_type` | enum | yes | `original`, `user_note`, `public_domain`. |
| `citation` | object | conditional | `source_id`, `locator`, `quote`. |
| `status` | enum | yes | `proposed`, `active`, `rejected`, `a_completer`, `suspended`. |
| `version` | integer | yes | Starts at 1. |
| `tags` | list[string] | no | Free tags. |

Invariants: `a_completer` cards cannot be `active` without an explicit answer;
a card with `source_type: user_note` must have a citation; a rejected card is
never reintroduced automatically.

### CardProgress

Scheduling state for one card.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `card_id` | string | yes | FK Flashcard. |
| `ease` | number | yes | Default 2.5, clamped `[1.3, 3.0]`. |
| `interval_days` | integer | yes | Default 0. |
| `repetitions` | integer | yes | Default 0. |
| `due_date` | string | yes | ISO date. |
| `last_grade` | enum | no | `again`, `hard`, `good`, `easy`. |
| `last_review` | string | no | ISO date. |
| `lapses` | integer | yes | Default 0. |
| `suspended` | boolean | yes | Default false. |

Invariants: `interval_days >= 0`; `due_date` is a valid ISO date; a suspended
card is never selected.

### ReviewEvent

Append-only record of one answer.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `event_id` | string | yes | UUID or hash. |
| `session_id` | string | yes | FK session. |
| `card_id` | string | yes | FK Flashcard. |
| `topic_id` | string | yes | Denormalized for fast aggregation. |
| `grade` | enum | yes | `again`, `hard`, `good`, `easy`. |
| `correct` | boolean | yes | `good`/`easy` = true; `again`/`hard` = false. |
| `duration_seconds` | integer | no | Time spent. |
| `reviewed_at` | string | yes | ISO datetime, local. |
| `due_before` | string | yes | Due date before the answer. |
| `due_after` | string | yes | Due date after the answer. |
| `ease_after` | number | yes | For audit. |

Invariants: append-only; `due_after >= reviewed_at` date; no personal note
content in the event.

### ReviewSession

A resumable review session.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `session_id` | string | yes | Stable. |
| `mode` | enum | yes | `quick`, `long`, `exam_eve`, `custom`. |
| `started_at` | string | yes | ISO datetime. |
| `target_minutes` | integer | yes | 10, 45, or user value. |
| `today` | string | yes | ISO date used by the scheduler. |
| `card_ids` | list[string] | yes | Ordered queue. |
| `cursor` | integer | yes | Next card index. |
| `answered` | list[ReviewEvent] | yes | Persisted after each answer. |
| `status` | enum | yes | `active`, `completed`, `abandoned`. |
| `completed_at` | string | no | ISO datetime. |

Invariants: resuming an active session restores `cursor` and `answered`; a card
is never answered twice in the same session; completing a session appends a
summary to `history.jsonl`.

### FormulaDrill

A numeric exercise.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Stable. |
| `topic_id` | string | yes | FK CourseTopic. |
| `prompt` | string | yes | Original statement. |
| `variables` | object | yes | Named inputs. |
| `answer` | number | yes | Canonical answer. |
| `answer_unit` | enum | yes | `eur`, `k_eur`, `m_eur`, `percent`, `ratio`, `years`. |
| `tolerance` | number | yes | Absolute tolerance in canonical unit. |
| `steps` | list[object] | yes | `{label, expression, result}`. |
| `error_paths` | list[object] | no | `{value, category, message}`. |
| `alternative_conventions` | list[object] | no | Accepted answer + explanation. |
| `difficulty` | integer | yes | 1..5. |

Invariants: `steps` non-empty; `tolerance > 0`; every error path has a category
from `formula`, `order`, `unit`, `missing_data`, `convention`.

### CaseStudy

An original VC case.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Stable. |
| `topic_id` | string | yes | FK CourseTopic. |
| `title` | string | yes | Original. |
| `context` | string | yes | Facts only. |
| `facts` | list[object] | yes | `{id, label, value, unit}`. |
| `questions` | list[object] | yes | Each with `id`, `prompt`, `criteria`. |
| `model_answer` | string | yes | Reasoning model. |
| `allowed_numbers` | list[number] | yes | Facts plus declared intermediates. |
| `difficulty` | integer | yes | 1..5. |
| `source_type` | enum | yes | `original` or `user_note`. |

Criterion fields: `id`, `label`, `weight`, `required_keywords` (list),
`any_keywords` (list), `expected_numbers` (list of `{value, tolerance}`),
`model_answer`.

Invariants: weights sum to 1.0 ± 0.001; every question has at least one
criterion; every expected number is in `allowed_numbers`; no fact is invented
outside `context`.

### CaseAttempt

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `attempt_id` | string | yes | Stable. |
| `case_id` | string | yes | FK CaseStudy. |
| `answers` | object | yes | question id -> text. |
| `criteria_results` | list[object] | yes | Per criterion. |
| `score` | number | yes | 0..1. |
| `unsupported_numbers` | list[number] | yes | Numbers absent from facts. |
| `submitted_at` | string | yes | ISO datetime. |

### ExamSession

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `exam_id` | string | yes | Stable. |
| `seed` | integer | yes | Deterministic composition. |
| `questions` | list[object] | yes | `{kind, ref_id, points}`. |
| `started_at` | string | yes | ISO datetime. |
| `duration_minutes` | integer | yes | Timer. |
| `answers` | object | yes | question id -> answer. |
| `score` | number | no | 0..1 after grading. |
| `per_topic` | object | no | topic -> score. |
| `status` | enum | yes | `active`, `submitted`, `expired`. |

Invariants: expired exams keep all entered answers; score is recomputable from
answers and questions; points sum to 100.

### MasteryRecord

Aggregated per topic.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `topic_id` | string | yes | FK CourseTopic. |
| `attempts` | integer | yes | Review + drill + case + exam. |
| `correct` | integer | yes | Weighted by activity. |
| `accuracy` | number | no | `correct / attempts`; null if 0 attempts. |
| `last_activity` | string | no | ISO date. |
| `status` | enum | yes | `untested`, `fragile`, `developing`, `solid`. |
| `due_cards` | integer | yes | Due today. |
| `top_errors` | list[string] | yes | Error categories, most frequent first. |

Invariant: `attempts == 0` implies `status == untested` and `accuracy == null`.

### StudyPlan

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `date` | string | yes | ISO date. |
| `capacity_minutes` | integer | yes | User constraint. |
| `activities` | list[object] | yes | `{kind, ref_id, topic_id, minutes, reason}`. |
| `total_minutes` | integer | yes | Must be <= capacity. |
| `exam_date` | string | no | Used for urgency. |

Invariant: `total_minutes <= capacity_minutes`; every activity has a reason.

### NoteSource

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `source_id` | string | yes | Content hash. |
| `filename` | string | yes | Original name, local only. |
| `kind` | enum | yes | `txt`, `md`, `pdf`. |
| `imported_at` | string | yes | ISO datetime. |
| `sha256` | string | yes | Content hash. |
| `line_count` | integer | yes | For citations. |
| `status` | enum | yes | `imported`, `reviewed`, `rejected`. |

### ProposedCard

A card extracted from notes.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `proposal_id` | string | yes | Stable. |
| `source_id` | string | yes | FK NoteSource. |
| `topic_id` | string | yes | FK CourseTopic. |
| `question` | string | yes | Extracted. |
| `answer` | string | no | Null if uncertain. |
| `citation` | object | yes | `{locator, quote}`. |
| `status` | enum | yes | `proposed`, `approved`, `rejected`, `a_completer`. |

Invariant: every proposal has a citation; approval moves it to `deck.json` with
`source_type: user_note`.

### GlossaryEntry

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `term_fr` | string | yes | French term. |
| `term_en` | string | yes | English term. |
| `definition` | string | yes | Original. |
| `example` | string | no | Original example. |
| `topic_id` | string | yes | FK CourseTopic. |
| `source_type` | enum | yes | `original` or `user_note`. |

### ProgressReport

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `generated_at` | string | yes | ISO datetime. |
| `period_start` | string | yes | ISO date. |
| `period_end` | string | yes | ISO date. |
| `coverage` | object | yes | topics seen / total. |
| `retention` | object | yes | 1-day, 7-day, 30-day windows. |
| `due_cards` | integer | yes | Today. |
| `weak_topics` | list[string] | yes | With reasons. |
| `recent_errors` | list[object] | yes | Category counts. |
| `next_actions` | list[object] | yes | Bounded activities. |
| `markdown_path` | string | yes | Local path. |

## State Transitions

### Flashcard

```text
proposed ──approve──> active ──suspend──> suspended
    │                    │
    └──reject──> rejected └──edit──> active (version + 1)

a_completer ──complete answer──> proposed ──approve──> active
```

Rules:
- rejected cards are not re-proposed automatically;
- editing an active card increments `version` and preserves the previous
  version in `deck.json` history;
- a card from a note whose source changed is flagged `a_verifier`, not silently
  updated.

### ReviewSession

```text
active ──answer all──> completed
   │
   ├──resume──> active (same cursor)
   └──abandon──> abandoned (events kept)
```

### ExamSession

```text
active ──submit──> submitted
   │
   └──timer expires──> expired (answers kept, then graded)
```

### ProposedCard

```text
proposed ──approve──> approved
    │
    ├──reject──> rejected
    └──uncertain──> a_completer
```

## Aggregation Rules

- **Accuracy**: `correct / attempts` per topic; reviews count 1, drills count 1,
  cases count by criteria, exams count by question.
- **Retention windows**: for each review event, look at the next event for the
  same card. A card is retained at `N` days if the next grade is `good`/`easy`
  and the gap is at least `N` days. Windows: 1, 7, 30.
- **Due cards**: `due_date <= today` and not suspended.
- **Weak topic**: `attempts >= 3` and `accuracy < 0.6`, or `top_errors` contains
  `formula`/`order` more than twice.
- **Untested**: `attempts == 0`; never displayed as mastered.
- **Plan priority**: exam urgency × topic weakness × due cards, with a
  deterministic tie-break on topic order.

## Content Pack Schema

See [contracts/content-pack.schema.json](./contracts/content-pack.schema.json).
Every pack has a `schema_version`; the loader rejects unknown major versions and
reports a readable error instead of crashing.

## Migration and Compatibility

- `progress.json` has `schema_version`; a missing version is treated as `1`.
- Additive fields are ignored by older readers.
- A future migration must create a backup `progress.json.bak` before rewriting.
- Content pack ids are stable; renaming a card id requires an alias map.
