# Implementation Plan: Venture Capital Revision Coach

**Branch**: `004-venture-capital-revision` | **Date**: 2026-11-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-venture-capital-revision/spec.md`

## Summary

Build a local-first Venture Capital revision coach inside NAGE. The feature
turns the existing deterministic academics toolkit into a complete exam
preparation system:

- active-recall sessions with a transparent spaced-repetition scheduler;
- a formula lab covering pre/post-money, dilution, option pool, cap table,
  liquidation waterfall, IRR, MOIC, TVPI, DPI and RVPI;
- original case studies with rubric-based correction and unsupported-fact
  detection;
- mock exams and oral-defense prompts;
- a weakness radar and a minute-bounded study plan;
- notes ingestion with exact citations and explicit approval;
- a FR/EN VC lexicon and term-sheet decoder;
- an offline progress report.

Delivery is CLI-first (`nage.py vc ...`) with JSON output, then a bounded local
HTTP facade. All learning data lives outside the repository, under
`~/.nage/vc/` (override: `NAGE_VC_HOME`). No network call, no cloud model, no
personal data in the repository, no copied copyrighted material.

The P1 MVP is User Stories 1-3: daily review, formula lab and case studio.
Stories 4-8 follow in priority order.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: standard library (`dataclasses`, `json`, `pathlib`,
`datetime`, `random`, `hashlib`, `re`, `decimal`); existing FastAPI/Pydantic for
the optional HTTP facade; existing `pypdf` for text-based PDF notes. No new
runtime dependency is required for the MVP.

**Storage**: local JSON and JSONL under `~/.nage/vc/`:
`progress.json`, `reviews.jsonl`, `sessions/`, `notes/`, `deck.json`,
`exams/`, `reports/`. Atomic writes (temporary file + `os.replace`), directory
mode `0700`, file mode `0600`. Built-in content packs live in the repository as
original JSON under `academics/vc/content/`.

**Testing**: pytest. Deterministic seeds and injected dates. No network. Every
test uses `tmp_path` and `NAGE_VC_HOME`. Targeted suites are run during
development; the full suite is run sequentially only before release.

**Target Platform**: macOS local machine; CLI and `127.0.0.1` HTTP server.
Fully offline after installation.

**Project Type**: single project, library + CLI + optional local web facade.

**Performance Goals**:
- session selection over 1,000 cards: < 300 ms;
- one answer grade and persistence: < 20 ms;
- radar/plan over 10,000 review events: < 500 ms;
- report generation over one year of events: < 1 s;
- memory footprint for the MVP content pack: < 50 MB.

**Constraints**:
- no network, no API key, no paid fallback;
- no personal data or notes in the repository;
- original content only; imported notes remain local and cited;
- deterministic output for the same content, answers, date and seed;
- honest states: "non testé" is never displayed as "maîtrisé";
- French interface by default, English VC terms preserved;
- all destructive actions require explicit confirmation.

**Scale/Scope**:
- 20 curriculum topics;
- 200+ flashcards at program completion (MVP: 60+);
- 100+ formula drills (MVP: 24+);
- 20+ original cases (MVP: 4);
- 120+ glossary terms (MVP: 40);
- 100+ exam questions (MVP: 20);
- one learner, multiple local profiles not required.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| I. Career-First Priority | Feature must serve the Career Explorer mission. | **Exception recorded.** This is a user-directed education feature for finance/VC exam revision and interview preparation. It does not modify Career data, ranking, qualification or application flows. The exception is explicit, scoped to `academics/vc/`, and must not weaken Career invariants. |
| II. Maximum Quality, Zero Unapproved Spend | Deterministic local code by default; no paid fallback. | PASS. Pure local computation; no model call; no network. |
| III. Privacy by Design | No private data leaves the Mac; local storage permissions; no real data in tests. | PASS. `~/.nage/vc/` is outside the repository, mode `0700`; tests use synthetic notes and `tmp_path`. |
| IV. Mandatory Evidence & Provenance | Every displayed fact carries a citation; unknown over inferred. | PASS. Imported cards carry source file, line/offset and quote; uncertain cards are marked `a_completer`; glossary entries carry an origin. |
| V. Test-First, Proof-Required | Red-Green-Refactor; pytest then ruff. | PASS. Tests are written before each P1 module; targeted suites and ruff are the commit gate. |
| VI. Git Protected, Supervised Autonomy | No work on `main`; no push without approval. | PASS. Work stays on `agent/n100-G05-bundle-export`; delivery branch is `agent/n100-carrier-20261101`; no force-push. |
| VII. Simplicity & Observability | Pure functions, text I/O, honest progress. | PASS. Dataclasses and pure functions; JSON/JSONL; no hidden state. |

**Post-design re-check**: the design keeps all data local, uses deterministic
grading, and does not introduce a cloud dependency. The only constitutional
exception remains Principle I, explicitly accepted for this user-requested
education feature.

## Project Structure

### Documentation (this feature)

```text
specs/004-venture-capital-revision/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   ├── python-api.md
│   ├── storage.md
│   └── content-pack.schema.json
├── checklists/
│   └── requirements.md
├── spec.md
└── tasks.md
```

### Source Code (repository root)

```text
academics/
├── vc/
│   ├── __init__.py          # public exports
│   ├── models.py            # dataclasses and enums
│   ├── storage.py           # local paths, atomic JSON, JSONL, permissions
│   ├── content.py           # content-pack loading and validation
│   ├── scheduler.py         # spaced repetition + session lifecycle
│   ├── drills.py            # VC formulas, unit parsing, error diagnosis
│   ├── cases.py             # case rubric evaluation, unsupported facts
│   ├── exams.py             # mock exam composition and grading
│   ├── mastery.py           # weakness radar and minute-bounded plan
│   ├── notes.py             # notes ingestion with citations and approval
│   ├── glossary.py          # lexicon and term-sheet decoder
│   ├── report.py            # offline progress report
│   ├── cli.py               # command handlers used by nage.py
│   └── content/
│       ├── topics.json
│       ├── cards_core.json
│       ├── drills_core.json
│       ├── cases_core.json
│       ├── exams_core.json
│       └── glossary_core.json
├── router.py                # optional local HTTP facade
└── daily_toolkit.py         # existing SM-2-like primitives, reused where useful

nage.py                      # `vc` subcommands
tests/
├── test_vc_storage.py
├── test_vc_content.py
├── test_vc_scheduler.py
├── test_vc_drills.py
├── test_vc_cases.py
├── test_vc_exams.py
├── test_vc_mastery.py
├── test_vc_notes.py
├── test_vc_glossary.py
├── test_vc_report.py
└── test_vc_cli.py
docs/
└── VC_REVISION_GUIDE.md
```

**Structure Decision**: a dedicated `academics/vc/` package keeps the feature
isolated from Career and from the existing finance/maths routers. Content is
data, not code, so hundreds of cards/drills/cases can be added without touching
the scheduler. The CLI is the primary interface; the HTTP facade is optional and
reuses the same pure functions.

## Implementation Phases

### Phase 0 — Research

See [research.md](./research.md). Decisions cover storage, scheduling,
deterministic grading, content licensing, notes ingestion and offline operation.

### Phase 1 — Design

See [data-model.md](./data-model.md), [contracts/](./contracts/) and
[quickstart.md](./quickstart.md).

### Phase 2 — Tasks

See [tasks.md](./tasks.md). The backlog is organized by user story so each P1
story is an independently testable increment.

## MVP Delivery Strategy

1. **Foundation**: models, storage, content loader, unit parser, error types.
2. **US1**: review scheduler, session persistence, `nage.py vc review`.
3. **US2**: formula drills, step-by-step correction, `nage.py vc drill`.
4. **US3**: case studio, rubric evaluation, `nage.py vc case`.
5. **Proof**: targeted pytest, ruff, CLI smoke, then commit.

Stories 4-8 are implemented only after the P1 proof is green. Content expansion
tasks are independent and can run in parallel by topic.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Content becomes a copied manual | Legal and ethical risk | Original wording, `source_type` field, review checklist, no pasted slides. |
| Scheduler hides weak topics | False confidence | Radar separates "non testé" from "maîtrisé"; due counts and retention windows are explicit. |
| Numeric grading is too strict | False negatives | Unit normalization, tolerance per drill, alternative conventions, explicit diagnostic. |
| Case grading is shallow | Misleading score | Rubric criteria are separate; unsupported numeric facts are flagged; model answer is shown after submission. |
| Personal notes leak into git | Privacy breach | `~/.nage/vc/notes/` outside repo; `.gitignore` guard; tests use synthetic notes; no note content in logs. |
| Feature sprawl | Unfinished backlog | P1 stories ship first; P2/P3 tasks remain unchecked until proven. |
| Full suite under load | Flaky perf test | Targeted suites during development; full suite sequential and alone before release. |

## Definition of Done

A task is done only when:

- the code exists on the delivery branch and the diff was inspected;
- the targeted tests were written first and pass;
- `ruff check` passes on modified files;
- no personal data, key or copied copyrighted content is in the diff;
- the CLI or API behavior is reproducible from the quickstart;
- the task checkbox is updated only with evidence in the commit or report.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Constitution Principle I exception | User explicitly requested a VC revision coach for exam preparation. | Rejecting the feature would ignore the user's direct priority; folding it into Career would pollute Career data and invariants. |
| Separate `academics/vc/` package | 20 topics and hundreds of content items need isolation and testability. | A single `venture_capital.py` would become a 5,000-line module and slow every content change. |
| JSON content packs | Non-developers can add cards/drills/cases; diffs are reviewable. | Hard-coded Python content would mix data and logic and make review harder. |
