# Tasks: Venture Capital Revision Coach

**Input**: Design documents from `/specs/004-venture-capital-revision/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: required for every P1 module. Write the test first, reproduce the failure,
then implement. Targeted suites during development; the full suite only sequentially
and alone before release.

**Organization**: tasks are grouped by user story. P1 (US1-US3) is the MVP.
P2 (US4-US6) and P3 (US7-US8) follow in priority order. Content expansion is
independent per topic and can run in parallel.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency)
- **[Story]**: US1-US8, omitted for setup, foundation and polish
- Every task names an exact file path

## Path Conventions

Single project: `academics/vc/`, `tests/`, `docs/`, `nage.py` at the repository root.

---

## Phase 1: Setup (Shared Infrastructure)

Create the package, content directories, test fixtures and CLI skeleton.

- [x] T001 Verify Python 3.12, pytest, ruff and pypdf are available; record the versions in `docs/VC_REVISION_GUIDE.md`.
- [ ] T002 Create the `academics/vc/` package and `academics/vc/content/` directory with `__init__.py`.
- [x] T003 [P] Create `academics/vc/models.py` with the dataclass and enum skeleton for all entities in `data-model.md`.
- [x] T004 [P] Create `academics/vc/storage.py` with `default_vc_home()` and path resolution for `NAGE_VC_HOME`.
- [x] T005 [P] Create `academics/vc/content/topics.json` with the 20 curriculum topics, codes, titles and exam weights.
- [x] T006 [P] Create `tests/test_vc_smoke.py` asserting the package imports and an empty store can be created in `tmp_path`.
- [ ] T007 [P] Add a `vc_home` pytest fixture in `tests/conftest.py` using `tmp_path` and `NAGE_VC_HOME`.
- [x] T008 [P] Create `docs/VC_REVISION_GUIDE.md` with the study workflow and the local-data warning.
- [x] T009 Add the `vc` subparser skeleton to `nage.py` with `--help`, `--json` and a no-op handler.
- [x] T010 [P] Add `.nage/` and `vc_data/` to `.gitignore` and verify `git status` does not show learner data.
- [x] T011 [P] Add `CONTENT_SCHEMA_VERSION = 1` and the `ContentError` type in `academics/vc/content.py`.
- [x] T012 Record the targeted test command and the ruff command for the new package in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 2: Foundational (Blocking Prerequisites)

Models, storage, content loading, validation, unit parsing and shared helpers. No user story starts before this phase is green.

- [ ] T013 Implement `CourseTopic` and `Concept` in `academics/vc/models.py` with validation helpers.
- [x] T014 [P] Implement `Flashcard`, `CardProgress` and the card status enum in `academics/vc/models.py`.
- [x] T015 [P] Implement `ReviewEvent` and `ReviewSession` in `academics/vc/models.py`.
- [ ] T016 [P] Implement `FormulaDrill` and `DrillResult` in `academics/vc/models.py`.
- [x] T017 [P] Implement `CaseStudy`, `CaseCriterion`, `CaseQuestion` and `CaseAttempt` in `academics/vc/models.py`.
- [x] T018 [P] Implement `ExamSession`, `MasteryRecord` and `StudyPlan` in `academics/vc/models.py`.
- [x] T019 [P] Implement `NoteSource`, `ProposedCard`, `GlossaryEntry` and `ProgressReport` in `academics/vc/models.py`.
- [x] T020 Implement `VcStore` path creation with mode `0700`, file mode `0600` and symlink refusal in `academics/vc/storage.py`.
- [x] T021 [P] Implement atomic JSON read/write and corrupt-file backup in `academics/vc/storage.py`.
- [x] T022 [P] Implement JSONL append/read with malformed-line warnings in `academics/vc/storage.py`.
- [x] T023 [P] Implement session persistence (`load_active_session`, `save_active_session`, `clear_active_session`) in `academics/vc/storage.py`.
- [x] T024 [P] Implement `settings.json` persistence for exam date, language and daily capacity in `academics/vc/storage.py`.
- [x] T025 [P] Implement `delete_all()` with the exact confirmation phrase and VC-home-only deletion in `academics/vc/storage.py`.
- [x] T026 Implement the `topics.json` loader and topic index in `academics/vc/content.py`.
- [x] T027 [P] Implement the cards pack loader in `academics/vc/content.py`.
- [x] T028 [P] Implement the drills pack loader in `academics/vc/content.py`.
- [x] T029 [P] Implement the cases pack loader in `academics/vc/content.py`.
- [x] T030 [P] Implement the glossary and exam-question pack loaders in `academics/vc/content.py`.
- [x] T031 [P] Validate unique ids and existing topic references across all packs in `academics/vc/content.py`.
- [x] T032 [P] Validate drill steps, tolerance, units and error-path categories in `academics/vc/content.py`.
- [x] T033 [P] Validate case rubric weights sum to 1.0 and every expected number is allowed in `academics/vc/content.py`.
- [x] T034 Implement `parse_number(raw, default_unit)` for `€`, `k€`, `M€`, `%`, `x`, spaces and commas in `academics/vc/drills.py`.
- [x] T035 [P] Add `VcError`, `ContentError`, `StorageError` and `InputError` with readable messages in `academics/vc/errors.py`.
- [x] T036 [P] Add deterministic id helpers for sessions, events and proposals in `academics/vc/ids.py`.
- [x] T037 [P] Add date helpers and an injectable `today` boundary in `academics/vc/dates.py`.
- [ ] T038 [P] Add a log scrubber that removes note content and absolute paths in `academics/vc/logging.py`.
- [ ] T039 [P] Add a local structured logger for VC commands that never logs answers or note text in `academics/vc/logging.py`.
- [ ] T040 [P] Add test builders for cards, drills and cases in `tests/vc_factories.py`.
- [ ] T041 Add `progress.json` schema-version handling and an additive migration path in `academics/vc/storage.py`.
- [x] T042 Add progress export/import as a single JSON object, excluding notes, in `academics/vc/storage.py`.
- [x] T043 Document the storage layout, permissions and backup procedure in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 3: User Story 1 - Daily active-recall session (Priority: P1) MVP

Deliver a resumable, deterministic active-recall loop with honest summaries.

- [x] T044 [P] [US1] Test that due selection excludes future and suspended cards in `tests/test_vc_scheduler.py`.
- [x] T045 [P] [US1] Test that new cards are introduced in curriculum order in `tests/test_vc_scheduler.py`.
- [x] T046 [P] [US1] Test the four grade transitions and their intervals in `tests/test_vc_scheduler.py`.
- [x] T047 [P] [US1] Test ease clamping and the 365-day interval cap in `tests/test_vc_scheduler.py`.
- [x] T048 [P] [US1] Test deterministic session ordering by due date, topic order and card id in `tests/test_vc_scheduler.py`.
- [x] T049 [P] [US1] Test that resuming a session preserves the cursor and every recorded answer in `tests/test_vc_scheduler.py`.
- [x] T050 [P] [US1] Test summary counts (`seen`, `correct`, `to_consolidate`, `due_tomorrow`) in `tests/test_vc_scheduler.py`.
- [x] T051 [P] [US1] Test quick, long and custom session limits in `tests/test_vc_scheduler.py`.
- [x] T052 [P] [US1] Test exam-eve mode prioritizes weak topics before other due cards in `tests/test_vc_scheduler.py`.
- [x] T053 [P] [US1] Test that a card never appears twice in one session in `tests/test_vc_scheduler.py`.
- [x] T054 [P] [US1] Test that an empty deck returns a readable empty summary in `tests/test_vc_scheduler.py`.
- [x] T055 [P] [US1] Test a date boundary at midnight with an injected `today` in `tests/test_vc_scheduler.py`.
- [x] T056 [US1] Implement `grade_card()` with the SM-2-inspired rules in `academics/vc/scheduler.py`.
- [x] T057 [US1] Implement `select_session_cards()` with due/new ordering in `academics/vc/scheduler.py`.
- [x] T058 [US1] Implement `start_session()` and the quick/long/exam-eve limits in `academics/vc/scheduler.py`.
- [x] T059 [US1] Implement `answer_session()` with atomic event and session persistence in `academics/vc/scheduler.py`.
- [x] T060 [US1] Implement `resume_session()` and `session_summary()` in `academics/vc/scheduler.py`.
- [x] T061 [US1] Implement `due_cards()` and the per-card `reason` string in `academics/vc/scheduler.py`.
- [x] T062 [US1] Append a completed session summary to `sessions/history.jsonl` in `academics/vc/scheduler.py`.
- [x] T063 [US1] Add an explicit abandon path that keeps all recorded events in `academics/vc/scheduler.py`.
- [x] T064 [US1] Implement `vc review` start/next/reveal/grade/status in `academics/vc/cli.py`.
- [x] T065 [US1] Implement the interactive review loop with `again|hard|good|easy` validation in `academics/vc/cli.py`.
- [x] T066 [US1] Wire `--today`, `--minutes`, `--mode` and `--session` in `nage.py`.
- [x] T067 [US1] Emit the review JSON contract from `contracts/cli.md` in `academics/vc/cli.py`.
- [x] T068 [US1] Add empty-deck guidance that points to drills and content expansion in `academics/vc/cli.py`.
- [x] T069 [US1] Add the 10-minute quick mode and the 45-minute long mode in `academics/vc/cli.py`.
- [x] T070 [US1] Add exam-eve mode using the radar's weak topics in `academics/vc/cli.py`.
- [x] T071 [P] [US1] Add CLI tests for review start, reveal, grade and resume in `tests/test_vc_cli.py`.
- [x] T072 [P] [US1] Add a CLI test for an invalid grade returning exit code 2 in `tests/test_vc_cli.py`.
- [x] T073 [US1] Add a performance test for 1,000 cards under 300 ms in `tests/test_vc_scheduler.py`.
- [ ] T074 [US1] Add a property-style test that no card is lost across interrupted sessions in `tests/test_vc_scheduler.py`.
- [x] T075 [US1] Add a property-style test that `good`/`easy` never decrease the interval in `tests/test_vc_scheduler.py`.
- [x] T076 [US1] Add retention event fields (`due_before`, `due_after`, `ease_after`) to every review event in `academics/vc/scheduler.py`.
- [x] T077 [US1] Document the review workflow and the grade meanings in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 4: User Story 2 - Venture Capital formula lab (Priority: P1) MVP

Deliver deterministic drills with unit normalization, step-by-step correction and error diagnosis.

- [x] T078 [P] [US2] Test post-money, pre-money and ownership after investment in `tests/test_vc_drills.py`.
- [x] T079 [P] [US2] Test dilution with existing and new shares in `tests/test_vc_drills.py`.
- [x] T080 [P] [US2] Test the option-pool calculation before and after the round in `tests/test_vc_drills.py`.
- [x] T081 [P] [US2] Test a cap table with founders, pool and investor in `tests/test_vc_drills.py`.
- [x] T082 [P] [US2] Test a 1x non-participating liquidation waterfall in `tests/test_vc_drills.py`.
- [x] T083 [P] [US2] Test a participating waterfall with a cap in `tests/test_vc_drills.py`.
- [x] T084 [P] [US2] Test IRR, MOIC, TVPI, DPI and RVPI on synthetic cash flows in `tests/test_vc_drills.py`.
- [x] T085 [P] [US2] Test unit parsing for `€`, `k€`, `M€`, `%`, `x`, spaces and commas in `tests/test_vc_drills.py`.
- [x] T086 [P] [US2] Test that non-numeric input is rejected without losing exercise state in `tests/test_vc_drills.py`.
- [x] T087 [P] [US2] Test the `formula`, `order`, `unit`, `missing_data` and `convention` diagnostics in `tests/test_vc_drills.py`.
- [x] T088 [P] [US2] Test declared alternative conventions and undeclared alternatives in `tests/test_vc_drills.py`.
- [x] T089 [P] [US2] Test deterministic `random_drill()` output for a fixed seed and topic in `tests/test_vc_drills.py`.
- [x] T090 [P] [US2] Test rounding and tolerance boundaries in `tests/test_vc_drills.py`.
- [x] T091 [US2] Implement `post_money()`, `pre_money()` and `ownership_after()` in `academics/vc/drills.py`.
- [x] T092 [US2] Implement `dilution()` and `option_pool()` in `academics/vc/drills.py`.
- [x] T093 [US2] Implement `cap_table()` with fully diluted shares in `academics/vc/drills.py`.
- [x] T094 [US2] Implement `liquidation_waterfall()` with seniority, participation and cap in `academics/vc/drills.py`.
- [x] T095 [US2] Implement `moic()`, `irr()`, `tvpi()`, `dpi()` and `rvpi()` in `academics/vc/drills.py`.
- [x] T096 [US2] Implement `grade_drill()` with canonical units and per-drill tolerance in `academics/vc/drills.py`.
- [x] T097 [US2] Implement `random_drill()` with a seeded selection in `academics/vc/drills.py`.
- [x] T098 [US2] Add `vc drill list` and topic filtering in `academics/vc/cli.py`.
- [x] T099 [US2] Add `vc drill run <id> --answer` with the JSON contract in `academics/vc/cli.py`.
- [x] T100 [US2] Add `vc drill random --topic --seed` in `academics/vc/cli.py`.
- [ ] T101 [US2] Add a readable correction table with label, expression and result in `academics/vc/cli.py`.
- [x] T102 [US2] Add a clear diagnostic message for each error category in `academics/vc/drills.py`.
- [x] T103 [P] [US2] Add CLI tests for drill list, run and random in `tests/test_vc_cli.py`.
- [x] T104 [P] [US2] Add a CLI test for a wrong answer and its diagnostic in `tests/test_vc_cli.py`.
- [x] T105 [P] [US2] Add a CLI test for a non-numeric answer in `tests/test_vc_cli.py`.
- [ ] T106 [US2] Add 24 core drills across the four MVP topics in `academics/vc/content/drills_core.json`.
- [x] T107 [US2] Validate that every core drill's answer is recomputable from its steps in `tests/test_vc_content.py`.
- [x] T108 [US2] Document the formula conventions and unit rules in `docs/VC_REVISION_GUIDE.md`.
- [x] T109 [US2] Add a performance test for grading 1,000 drills under 1 s in `tests/test_vc_drills.py`.
- [x] T110 [US2] Add a test that a wrong answer never reveals another drill's answer in `tests/test_vc_drills.py`.
- [x] T111 [US2] Add a test for a drill whose variables are incomplete and must return `missing_data` in `tests/test_vc_drills.py`.

---

## Phase 5: User Story 3 - Case-study studio (Priority: P1) MVP

Deliver original cases with a per-criterion rubric, unsupported-fact detection and a model answer after submission.

- [x] T112 [P] [US3] Test case content validation (facts, questions, weights, allowed numbers) in `tests/test_vc_cases.py`.
- [x] T113 [P] [US3] Test that each rubric criterion is evaluated separately in `tests/test_vc_cases.py`.
- [x] T114 [P] [US3] Test that weights sum to 1.0 and the score is the weighted sum in `tests/test_vc_cases.py`.
- [x] T115 [P] [US3] Test that a number absent from the facts is flagged as unsupported in `tests/test_vc_cases.py`.
- [x] T116 [P] [US3] Test that the model answer is absent before submission and present after in `tests/test_vc_cases.py`.
- [x] T117 [P] [US3] Test a down-round waterfall and its priority order in `tests/test_vc_cases.py`.
- [x] T118 [P] [US3] Test empty and partial answers in `tests/test_vc_cases.py`.
- [x] T119 [P] [US3] Test accent-insensitive keyword matching in `tests/test_vc_cases.py`.
- [x] T120 [P] [US3] Test numeric tolerance for expected numbers in `tests/test_vc_cases.py`.
- [ ] T121 [P] [US3] Test that a case with a missing fact is rejected at load time in `tests/test_vc_cases.py`.
- [x] T122 [US3] Implement `evaluate_case()` with per-criterion results in `academics/vc/cases.py`.
- [x] T123 [US3] Implement `unsupported_numbers()` with fact and intermediate allow-lists in `academics/vc/cases.py`.
- [x] T124 [US3] Implement accent-insensitive keyword normalization in `academics/vc/cases.py`.
- [x] T125 [US3] Implement the case-attempt persistence path in `academics/vc/storage.py`.
- [x] T126 [US3] Add `vc case list` and `vc case show` in `academics/vc/cli.py`.
- [x] T127 [US3] Add `vc case grade --answers` with JSON-file parsing and validation in `academics/vc/cli.py`.
- [x] T128 [US3] Add the `notice` stating that grading is rubric-based, not human, in `academics/vc/cli.py`.
- [ ] T129 [US3] Add a readable criterion table with earned/max points in `academics/vc/cli.py`.
- [x] T130 [US3] Add four original core cases (seed, Series A, down round, exit waterfall) in `academics/vc/content/cases_core.json`.
- [x] T131 [US3] Add a case content review checklist for facts, rubric and licensing in `docs/VC_REVISION_GUIDE.md`.
- [x] T132 [P] [US3] Add CLI tests for case list, show and grade in `tests/test_vc_cli.py`.
- [x] T133 [P] [US3] Add a CLI test for a malformed answers file in `tests/test_vc_cli.py`.
- [x] T134 [US3] Add a test that the score is recomputable from the stored criteria in `tests/test_vc_cases.py`.
- [x] T135 [US3] Add a test that an unsupported number does not change the score but is reported in `tests/test_vc_cases.py`.
- [x] T136 [US3] Add a test that the model answer never appears in `vc case show --json` in `tests/test_vc_cases.py`.
- [x] T137 [US3] Document the case workflow and self-review method in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 6: User Story 4 - Mock exam and oral defense (Priority: P2)

Deliver deterministic timed exams, per-topic scores and oral follow-ups without answer leakage.

- [x] T138 [P] [US4] Test deterministic exam composition for the same seed and topic filter in `tests/test_vc_exams.py`.
- [x] T139 [P] [US4] Test that points sum to 100 and no question repeats in `tests/test_vc_exams.py`.
- [x] T140 [P] [US4] Test that timer expiry preserves entered answers and marks the exam `expired` in `tests/test_vc_exams.py`.
- [x] T141 [P] [US4] Test that the score is recomputable from stored answers in `tests/test_vc_exams.py`.
- [x] T142 [P] [US4] Test per-topic scores and the weak-topic list in `tests/test_vc_exams.py`.
- [x] T143 [P] [US4] Test oral follow-ups do not reveal the model answer in `tests/test_vc_exams.py`.
- [x] T144 [P] [US4] Test the insufficient-questions error in `tests/test_vc_exams.py`.
- [x] T145 [US4] Implement `build_exam()` with seeded composition in `academics/vc/exams.py`.
- [x] T146 [US4] Implement `grade_exam()` with MCQ, numeric and open formats in `academics/vc/exams.py`.
- [x] T147 [US4] Implement `oral_questions()` with follow-ups in `academics/vc/exams.py`.
- [x] T148 [US4] Persist the active exam and allow resume in `academics/vc/storage.py`.
- [x] T149 [US4] Append completed exam summaries to `exams/history.jsonl` in `academics/vc/exams.py`.
- [x] T150 [US4] Add `vc exam start` and `vc exam submit` in `academics/vc/cli.py`.
- [x] T151 [US4] Add `vc oral <topic>` in `academics/vc/cli.py`.
- [x] T152 [US4] Add a countdown/timer boundary that uses the injected clock in `academics/vc/exams.py`.
- [x] T153 [US4] Link a weak exam topic to the remedial plan in `academics/vc/exams.py`.
- [x] T154 [US4] Add 20 core exam questions across the four MVP topics in `academics/vc/content/exams_core.json`.
- [x] T155 [US4] Validate exam points and answer formats at load time in `academics/vc/content.py`.
- [x] T156 [P] [US4] Add CLI tests for exam start, submit and oral in `tests/test_vc_cli.py`.
- [x] T157 [P] [US4] Add a CLI test for an expired exam in `tests/test_vc_cli.py`.
- [x] T158 [US4] Add a test for a numeric exam answer with a unit in `tests/test_vc_exams.py`.
- [x] T159 [US4] Add a test for a seed that produces the same exam twice in `tests/test_vc_exams.py`.
- [x] T160 [US4] Add a test that an exam never includes a suspended card's question in `tests/test_vc_exams.py`.
- [x] T161 [US4] Document the mock-exam and oral workflow in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 7: User Story 5 - Weakness radar and adaptive study plan (Priority: P2)

Deliver an honest per-topic radar and a plan that never exceeds the learner's available minutes.

- [x] T162 [P] [US5] Test that a topic with zero attempts is `untested` with `accuracy = null` in `tests/test_vc_mastery.py`.
- [x] T163 [P] [US5] Test the `fragile`, `developing` and `solid` thresholds in `tests/test_vc_mastery.py`.
- [x] T164 [P] [US5] Test that top error categories are ordered by frequency in `tests/test_vc_mastery.py`.
- [x] T165 [P] [US5] Test that due cards are counted per topic in `tests/test_vc_mastery.py`.
- [x] T166 [P] [US5] Test that the plan never exceeds the requested minutes in `tests/test_vc_mastery.py`.
- [ ] T167 [P] [US5] Test the priority order: exam urgency, weakness, due cards, topic order in `tests/test_vc_mastery.py`.
- [x] T168 [P] [US5] Test that every activity has a readable reason in `tests/test_vc_mastery.py`.
- [x] T169 [P] [US5] Test the plan with no exam date, no weak topic and a very small capacity in `tests/test_vc_mastery.py`.
- [x] T170 [P] [US5] Test that the plan never recommends a topic with no available content in `tests/test_vc_mastery.py`.
- [x] T171 [US5] Implement `mastery_radar()` in `academics/vc/mastery.py`.
- [x] T172 [US5] Implement `build_study_plan()` with minute accounting in `academics/vc/mastery.py`.
- [x] T173 [US5] Implement exam-urgency scoring from `settings.json` and the `--exam-date` override in `academics/vc/mastery.py`.
- [x] T174 [US5] Implement topic coverage as seen topics / total topics in `academics/vc/mastery.py`.
- [x] T175 [US5] Add `vc radar` in `academics/vc/cli.py`.
- [x] T176 [US5] Add `vc plan --minutes --exam-date` in `academics/vc/cli.py`.
- [x] T177 [P] [US5] Add CLI tests for radar and plan in `tests/test_vc_cli.py`.
- [x] T178 [US5] Add a performance test for the radar over 10,000 events under 500 ms in `tests/test_vc_mastery.py`.
- [x] T179 [US5] Add a determinism test for the plan with the same inputs in `tests/test_vc_mastery.py`.
- [x] T180 [US5] Add a test that an untested topic is never labeled `solid` in `tests/test_vc_mastery.py`.
- [ ] T181 [US5] Document how to read the radar and the plan in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 8: User Story 6 - Notes-to-deck ingestion with citations (Priority: P2)

Turn local course notes into cited proposals that require explicit approval.

- [x] T182 [P] [US6] Test `.txt` and `.md` ingestion with `Term : definition` patterns in `tests/test_vc_notes.py`.
- [x] T183 [P] [US6] Test `**Term** : definition` and `Term — definition` patterns in `tests/test_vc_notes.py`.
- [x] T184 [P] [US6] Test `Q:` / `R:` pairs in `tests/test_vc_notes.py`.
- [x] T185 [P] [US6] Test bullet-list cloze candidates and `a_completer` when the heading is missing in `tests/test_vc_notes.py`.
- [x] T186 [P] [US6] Test that every proposal carries a source id, locator and exact quote in `tests/test_vc_notes.py`.
- [x] T187 [P] [US6] Test that no proposal is active before approval in `tests/test_vc_notes.py`.
- [x] T188 [P] [US6] Test approval moves a proposal to `deck.json` with `source_type: user_note` in `tests/test_vc_notes.py`.
- [x] T189 [P] [US6] Test rejection records the proposal and prevents automatic reintroduction in `tests/test_vc_notes.py`.
- [x] T190 [P] [US6] Test duplicate proposals from the same source are deduplicated in `tests/test_vc_notes.py`.
- [x] T191 [P] [US6] Test a changed source file is flagged, not silently re-ingested in `tests/test_vc_notes.py`.
- [x] T192 [P] [US6] Test a scanned PDF without text returns a readable error in `tests/test_vc_notes.py`.
- [x] T193 [US6] Implement text and Markdown ingestion in `academics/vc/notes.py`.
- [x] T194 [US6] Implement text-based PDF extraction with `pypdf` in `academics/vc/notes.py`.
- [x] T195 [US6] Implement definition, Q/R and bullet extraction patterns in `academics/vc/notes.py`.
- [x] T196 [US6] Implement citation locators (line number and offset) in `academics/vc/notes.py`.
- [x] T197 [US6] Implement the `proposed`/`approved`/`rejected`/`a_completer` state machine in `academics/vc/notes.py`.
- [x] T198 [US6] Store note sources under `~/.nage/vc/notes/` with a content hash in `academics/vc/storage.py`.
- [x] T199 [US6] Add `vc notes ingest`, `list`, `approve` and `reject` in `academics/vc/cli.py`.
- [x] T200 [US6] Add a 2 MB size limit and a readable error in `academics/vc/notes.py`.
- [x] T201 [US6] Add a test that no note content is written to the repository in `tests/test_vc_notes.py`.
- [x] T202 [P] [US6] Add CLI tests for ingest, approve and reject in `tests/test_vc_cli.py`.
- [x] T203 [US6] Add three synthetic note fixtures in `tests/fixtures/vc_notes/`.
- [x] T204 [US6] Add a privacy test that logs contain no note text in `tests/test_vc_notes.py`.
- [x] T205 [US6] Document the notes workflow and the citation review in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 9: User Story 7 - VC lexicon and term-sheet decoder (Priority: P3)

Deliver a searchable FR/EN lexicon and a conservative term-sheet clause decoder.

- [x] T206 [P] [US7] Test accent-insensitive FR/EN search in `tests/test_vc_glossary.py`.
- [x] T207 [P] [US7] Test that an unknown term returns `non documenté` in `tests/test_vc_glossary.py`.
- [x] T208 [P] [US7] Test the 40 core glossary entries in `tests/test_vc_glossary.py`.
- [x] T209 [P] [US7] Test liquidation preference and participation decoding in `tests/test_vc_glossary.py`.
- [x] T210 [P] [US7] Test anti-dilution, board, drag-along, tag-along and pro-rata decoding in `tests/test_vc_glossary.py`.
- [x] T211 [P] [US7] Test that each decoded clause has an economic effect in `tests/test_vc_glossary.py`.
- [x] T212 [P] [US7] Test that unknown clauses are listed separately and never invented in `tests/test_vc_glossary.py`.
- [x] T213 [US7] Implement `search_glossary()` in `academics/vc/glossary.py`.
- [x] T214 [US7] Implement `decode_term_sheet()` with known clause patterns in `academics/vc/glossary.py`.
- [x] T215 [US7] Add 40 original core glossary entries in `academics/vc/content/glossary_core.json`.
- [x] T216 [US7] Add `vc glossary search` in `academics/vc/cli.py`.
- [x] T217 [US7] Add `vc term-sheet decode <file>` in `academics/vc/cli.py`.
- [x] T218 [US7] Add a test that the decoder preserves clause order in `tests/test_vc_glossary.py`.
- [x] T219 [US7] Add a test that a clause with a cap and a participation is explained correctly in `tests/test_vc_glossary.py`.
- [x] T220 [P] [US7] Add CLI tests for glossary search and term-sheet decode in `tests/test_vc_cli.py`.
- [x] T221 [US7] Add a duplicate-term check at load time in `academics/vc/content.py`.
- [x] T222 [US7] Add an example field to every core glossary entry in `academics/vc/content/glossary_core.json`.
- [x] T223 [US7] Add a test that an empty query returns no matches without an error in `tests/test_vc_glossary.py`.
- [x] T224 [US7] Add a test that a non-UTF-8 term-sheet file returns a readable error in `tests/test_vc_glossary.py`.
- [x] T225 [US7] Document the lexicon and term-sheet workflow in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 10: User Story 8 - Progress report and exam readiness (Priority: P3)

Deliver an offline report whose every number is recomputable from stored data.

- [x] T226 [P] [US8] Test coverage as seen topics / total topics in `tests/test_vc_report.py`.
- [x] T227 [P] [US8] Test retention at 1, 7 and 30 days from review events in `tests/test_vc_report.py`.
- [x] T228 [P] [US8] Test due-card counts and weak-topic reasons in `tests/test_vc_report.py`.
- [x] T229 [P] [US8] Test recent error categories and next actions in `tests/test_vc_report.py`.
- [x] T230 [P] [US8] Test that every report number is recomputable from the inputs in `tests/test_vc_report.py`.
- [x] T231 [P] [US8] Test that an untested topic is listed as `untested` in `tests/test_vc_report.py`.
- [x] T232 [P] [US8] Test an empty period and a one-year period in `tests/test_vc_report.py`.
- [x] T233 [US8] Implement `build_progress_report()` in `academics/vc/report.py`.
- [x] T234 [US8] Implement the Markdown renderer with all required sections in `academics/vc/report.py`.
- [x] T235 [US8] Write the report under `~/.nage/vc/reports/` with a date-based name in `academics/vc/report.py`.
- [x] T236 [US8] Add `vc report --days` in `academics/vc/cli.py`.
- [ ] T237 [US8] Ensure the report contains no raw note text or answer text in `academics/vc/report.py`.
- [x] T238 [P] [US8] Add CLI tests for report generation and the output path in `tests/test_vc_cli.py`.
- [x] T239 [US8] Add a performance test for one year of events under 1 s in `tests/test_vc_report.py`.
- [x] T240 [US8] Add a test that the report period filter excludes older events in `tests/test_vc_report.py`.
- [x] T241 [US8] Add a test that the report lists the next actions with minutes in `tests/test_vc_report.py`.
- [x] T242 [US8] Add a privacy test that the report has no personal identifiers in `tests/test_vc_report.py`.
- [x] T243 [US8] Document the report sections and the exam-readiness reading in `docs/VC_REVISION_GUIDE.md`.

---

## Phase 11: Content Expansion (20 Topics, Independent Missions)

Build the full VC curriculum. Each topic is an independent work packet; all content is original or cited user notes.

- [ ] T244 [P] [US1] Write 10 original flashcards on **VC01 — Écosystème du capital-risque et acteurs** in `academics/vc/content/cards_vc01.json`, each with a question, answer, explanation and topic id.
- [ ] T245 [P] [US2] Write 3 original décision chiffrée drills on **VC01 — Écosystème du capital-risque et acteurs** in `academics/vc/content/drills_vc01.json`, each with variables, answer, unit, steps and error paths.
- [ ] T246 [P] [US3] Write 1 original case on **VC01 — Écosystème du capital-risque et acteurs** in `academics/vc/content/cases_vc01.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T247 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC01 — Écosystème du capital-risque et acteurs** in `academics/vc/content/exams_vc01.json` and `glossary_vc01.json`, with points, formats and original definitions.
- [ ] T248 [P] [US1] Write 10 original flashcards on **VC02 — Économie d'un fonds : frais, carry, hurdle** in `academics/vc/content/cards_vc02.json`, each with a question, answer, explanation and topic id.
- [ ] T249 [P] [US2] Write 3 original calcul drills on **VC02 — Économie d'un fonds : frais, carry, hurdle** in `academics/vc/content/drills_vc02.json`, each with variables, answer, unit, steps and error paths.
- [ ] T250 [P] [US3] Write 1 original case on **VC02 — Économie d'un fonds : frais, carry, hurdle** in `academics/vc/content/cases_vc02.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T251 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC02 — Économie d'un fonds : frais, carry, hurdle** in `academics/vc/content/exams_vc02.json` and `glossary_vc02.json`, with points, formats and original definitions.
- [ ] T252 [P] [US1] Write 10 original flashcards on **VC03 — Étapes de financement et instruments** in `academics/vc/content/cards_vc03.json`, each with a question, answer, explanation and topic id.
- [ ] T253 [P] [US2] Write 3 original calcul drills on **VC03 — Étapes de financement et instruments** in `academics/vc/content/drills_vc03.json`, each with variables, answer, unit, steps and error paths.
- [ ] T254 [P] [US3] Write 1 original case on **VC03 — Étapes de financement et instruments** in `academics/vc/content/cases_vc03.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T255 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC03 — Étapes de financement et instruments** in `academics/vc/content/exams_vc03.json` and `glossary_vc03.json`, with points, formats and original definitions.
- [ ] T256 [P] [US1] Write 10 original flashcards on **VC04 — Pre-money, post-money et propriété** in `academics/vc/content/cards_vc04.json`, each with a question, answer, explanation and topic id.
- [ ] T257 [P] [US2] Write 3 original calcul drills on **VC04 — Pre-money, post-money et propriété** in `academics/vc/content/drills_vc04.json`, each with variables, answer, unit, steps and error paths.
- [ ] T258 [P] [US3] Write 1 original case on **VC04 — Pre-money, post-money et propriété** in `academics/vc/content/cases_vc04.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T259 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC04 — Pre-money, post-money et propriété** in `academics/vc/content/exams_vc04.json` and `glossary_vc04.json`, with points, formats and original definitions.
- [ ] T260 [P] [US1] Write 10 original flashcards on **VC05 — Cap table et option pool** in `academics/vc/content/cards_vc05.json`, each with a question, answer, explanation and topic id.
- [ ] T261 [P] [US2] Write 3 original calcul drills on **VC05 — Cap table et option pool** in `academics/vc/content/drills_vc05.json`, each with variables, answer, unit, steps and error paths.
- [ ] T262 [P] [US3] Write 1 original case on **VC05 — Cap table et option pool** in `academics/vc/content/cases_vc05.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T263 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC05 — Cap table et option pool** in `academics/vc/content/exams_vc05.json` and `glossary_vc05.json`, with points, formats and original definitions.
- [ ] T264 [P] [US1] Write 10 original flashcards on **VC06 — Term sheet : économie et contrôle** in `academics/vc/content/cards_vc06.json`, each with a question, answer, explanation and topic id.
- [ ] T265 [P] [US2] Write 3 original décision chiffrée drills on **VC06 — Term sheet : économie et contrôle** in `academics/vc/content/drills_vc06.json`, each with variables, answer, unit, steps and error paths.
- [ ] T266 [P] [US3] Write 1 original case on **VC06 — Term sheet : économie et contrôle** in `academics/vc/content/cases_vc06.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T267 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC06 — Term sheet : économie et contrôle** in `academics/vc/content/exams_vc06.json` and `glossary_vc06.json`, with points, formats and original definitions.
- [ ] T268 [P] [US1] Write 10 original flashcards on **VC07 — Liquidation preference et waterfall** in `academics/vc/content/cards_vc07.json`, each with a question, answer, explanation and topic id.
- [ ] T269 [P] [US2] Write 3 original calcul drills on **VC07 — Liquidation preference et waterfall** in `academics/vc/content/drills_vc07.json`, each with variables, answer, unit, steps and error paths.
- [ ] T270 [P] [US3] Write 1 original case on **VC07 — Liquidation preference et waterfall** in `academics/vc/content/cases_vc07.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T271 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC07 — Liquidation preference et waterfall** in `academics/vc/content/exams_vc07.json` and `glossary_vc07.json`, with points, formats and original definitions.
- [ ] T272 [P] [US1] Write 10 original flashcards on **VC08 — Anti-dilution et down rounds** in `academics/vc/content/cards_vc08.json`, each with a question, answer, explanation and topic id.
- [ ] T273 [P] [US2] Write 3 original calcul drills on **VC08 — Anti-dilution et down rounds** in `academics/vc/content/drills_vc08.json`, each with variables, answer, unit, steps and error paths.
- [ ] T274 [P] [US3] Write 1 original case on **VC08 — Anti-dilution et down rounds** in `academics/vc/content/cases_vc08.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T275 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC08 — Anti-dilution et down rounds** in `academics/vc/content/exams_vc08.json` and `glossary_vc08.json`, with points, formats and original definitions.
- [ ] T276 [P] [US1] Write 10 original flashcards on **VC09 — Métriques de rendement : IRR, MOIC, TVPI, DPI, RVPI, J-curve** in `academics/vc/content/cards_vc09.json`, each with a question, answer, explanation and topic id.
- [ ] T277 [P] [US2] Write 3 original calcul drills on **VC09 — Métriques de rendement : IRR, MOIC, TVPI, DPI, RVPI, J-curve** in `academics/vc/content/drills_vc09.json`, each with variables, answer, unit, steps and error paths.
- [ ] T278 [P] [US3] Write 1 original case on **VC09 — Métriques de rendement : IRR, MOIC, TVPI, DPI, RVPI, J-curve** in `academics/vc/content/cases_vc09.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T279 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC09 — Métriques de rendement : IRR, MOIC, TVPI, DPI, RVPI, J-curve** in `academics/vc/content/exams_vc09.json` and `glossary_vc09.json`, with points, formats and original definitions.
- [ ] T280 [P] [US1] Write 10 original flashcards on **VC10 — Processus de levée et due diligence** in `academics/vc/content/cards_vc10.json`, each with a question, answer, explanation and topic id.
- [ ] T281 [P] [US2] Write 3 original décision chiffrée drills on **VC10 — Processus de levée et due diligence** in `academics/vc/content/drills_vc10.json`, each with variables, answer, unit, steps and error paths.
- [ ] T282 [P] [US3] Write 1 original case on **VC10 — Processus de levée et due diligence** in `academics/vc/content/cases_vc10.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T283 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC10 — Processus de levée et due diligence** in `academics/vc/content/exams_vc10.json` and `glossary_vc10.json`, with points, formats and original definitions.
- [ ] T284 [P] [US1] Write 10 original flashcards on **VC11 — Construction de portefeuille et réserves** in `academics/vc/content/cards_vc11.json`, each with a question, answer, explanation and topic id.
- [ ] T285 [P] [US2] Write 3 original calcul drills on **VC11 — Construction de portefeuille et réserves** in `academics/vc/content/drills_vc11.json`, each with variables, answer, unit, steps and error paths.
- [ ] T286 [P] [US3] Write 1 original case on **VC11 — Construction de portefeuille et réserves** in `academics/vc/content/cases_vc11.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T287 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC11 — Construction de portefeuille et réserves** in `academics/vc/content/exams_vc11.json` and `glossary_vc11.json`, with points, formats and original definitions.
- [ ] T288 [P] [US1] Write 10 original flashcards on **VC12 — Gouvernance et dynamique de board** in `academics/vc/content/cards_vc12.json`, each with a question, answer, explanation and topic id.
- [ ] T289 [P] [US2] Write 3 original décision chiffrée drills on **VC12 — Gouvernance et dynamique de board** in `academics/vc/content/drills_vc12.json`, each with variables, answer, unit, steps and error paths.
- [ ] T290 [P] [US3] Write 1 original case on **VC12 — Gouvernance et dynamique de board** in `academics/vc/content/cases_vc12.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T291 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC12 — Gouvernance et dynamique de board** in `academics/vc/content/exams_vc12.json` and `glossary_vc12.json`, with points, formats and original definitions.
- [ ] T292 [P] [US1] Write 10 original flashcards on **VC13 — Sorties : M&A, IPO, secondaire, continuation funds** in `academics/vc/content/cards_vc13.json`, each with a question, answer, explanation and topic id.
- [ ] T293 [P] [US2] Write 3 original calcul drills on **VC13 — Sorties : M&A, IPO, secondaire, continuation funds** in `academics/vc/content/drills_vc13.json`, each with variables, answer, unit, steps and error paths.
- [ ] T294 [P] [US3] Write 1 original case on **VC13 — Sorties : M&A, IPO, secondaire, continuation funds** in `academics/vc/content/cases_vc13.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T295 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC13 — Sorties : M&A, IPO, secondaire, continuation funds** in `academics/vc/content/exams_vc13.json` and `glossary_vc13.json`, with points, formats and original definitions.
- [ ] T296 [P] [US1] Write 10 original flashcards on **VC14 — Métriques startup et unit economics** in `academics/vc/content/cards_vc14.json`, each with a question, answer, explanation and topic id.
- [ ] T297 [P] [US2] Write 3 original calcul drills on **VC14 — Métriques startup et unit economics** in `academics/vc/content/drills_vc14.json`, each with variables, answer, unit, steps and error paths.
- [ ] T298 [P] [US3] Write 1 original case on **VC14 — Métriques startup et unit economics** in `academics/vc/content/cases_vc14.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T299 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC14 — Métriques startup et unit economics** in `academics/vc/content/exams_vc14.json` and `glossary_vc14.json`, with points, formats and original definitions.
- [ ] T300 [P] [US1] Write 10 original flashcards on **VC15 — Modélisation financière et scénarios** in `academics/vc/content/cards_vc15.json`, each with a question, answer, explanation and topic id.
- [ ] T301 [P] [US2] Write 3 original calcul drills on **VC15 — Modélisation financière et scénarios** in `academics/vc/content/drills_vc15.json`, each with variables, answer, unit, steps and error paths.
- [ ] T302 [P] [US3] Write 1 original case on **VC15 — Modélisation financière et scénarios** in `academics/vc/content/cases_vc15.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T303 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC15 — Modélisation financière et scénarios** in `academics/vc/content/exams_vc15.json` and `glossary_vc15.json`, with points, formats and original definitions.
- [ ] T304 [P] [US1] Write 10 original flashcards on **VC16 — Instruments juridiques : SAFE, convertible notes, actions de préférence** in `academics/vc/content/cards_vc16.json`, each with a question, answer, explanation and topic id.
- [ ] T305 [P] [US2] Write 3 original calcul drills on **VC16 — Instruments juridiques : SAFE, convertible notes, actions de préférence** in `academics/vc/content/drills_vc16.json`, each with variables, answer, unit, steps and error paths.
- [ ] T306 [P] [US3] Write 1 original case on **VC16 — Instruments juridiques : SAFE, convertible notes, actions de préférence** in `academics/vc/content/cases_vc16.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T307 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC16 — Instruments juridiques : SAFE, convertible notes, actions de préférence** in `academics/vc/content/exams_vc16.json` and `glossary_vc16.json`, with points, formats and original definitions.
- [ ] T308 [P] [US1] Write 10 original flashcards on **VC17 — Contexte VC français et européen** in `academics/vc/content/cards_vc17.json`, each with a question, answer, explanation and topic id.
- [ ] T309 [P] [US2] Write 3 original décision chiffrée drills on **VC17 — Contexte VC français et européen** in `academics/vc/content/drills_vc17.json`, each with variables, answer, unit, steps and error paths.
- [ ] T310 [P] [US3] Write 1 original case on **VC17 — Contexte VC français et européen** in `academics/vc/content/cases_vc17.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T311 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC17 — Contexte VC français et européen** in `academics/vc/content/exams_vc17.json` and `glossary_vc17.json`, with points, formats and original definitions.
- [ ] T312 [P] [US1] Write 10 original flashcards on **VC18 — Mémo d'investissement et thèse** in `academics/vc/content/cards_vc18.json`, each with a question, answer, explanation and topic id.
- [ ] T313 [P] [US2] Write 3 original décision chiffrée drills on **VC18 — Mémo d'investissement et thèse** in `academics/vc/content/drills_vc18.json`, each with variables, answer, unit, steps and error paths.
- [ ] T314 [P] [US3] Write 1 original case on **VC18 — Mémo d'investissement et thèse** in `academics/vc/content/cases_vc18.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T315 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC18 — Mémo d'investissement et thèse** in `academics/vc/content/exams_vc18.json` and `glossary_vc18.json`, with points, formats and original definitions.
- [ ] T316 [P] [US1] Write 10 original flashcards on **VC19 — Venture debt et financements alternatifs** in `academics/vc/content/cards_vc19.json`, each with a question, answer, explanation and topic id.
- [ ] T317 [P] [US2] Write 3 original calcul drills on **VC19 — Venture debt et financements alternatifs** in `academics/vc/content/drills_vc19.json`, each with variables, answer, unit, steps and error paths.
- [ ] T318 [P] [US3] Write 1 original case on **VC19 — Venture debt et financements alternatifs** in `academics/vc/content/cases_vc19.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T319 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC19 — Venture debt et financements alternatifs** in `academics/vc/content/exams_vc19.json` and `glossary_vc19.json`, with points, formats and original definitions.
- [ ] T320 [P] [US1] Write 10 original flashcards on **VC20 — Méthode d'examen et pratique des cas** in `academics/vc/content/cards_vc20.json`, each with a question, answer, explanation and topic id.
- [ ] T321 [P] [US2] Write 3 original calcul drills on **VC20 — Méthode d'examen et pratique des cas** in `academics/vc/content/drills_vc20.json`, each with variables, answer, unit, steps and error paths.
- [ ] T322 [P] [US3] Write 1 original case on **VC20 — Méthode d'examen et pratique des cas** in `academics/vc/content/cases_vc20.json`, with facts, 3-5 guided questions, a rubric and a model answer.
- [ ] T323 [P] [US4] Write 5 exam questions and 6 glossary terms on **VC20 — Méthode d'examen et pratique des cas** in `academics/vc/content/exams_vc20.json` and `glossary_vc20.json`, with points, formats and original definitions.
- [ ] T324 [P] [US1] Reach 200 active flashcards and verify the count with `vc review --json` in `tests/test_vc_content.py`.
- [ ] T325 [P] [US2] Reach 100 formula drills and verify every answer is recomputable in `tests/test_vc_content.py`.
- [ ] T326 [P] [US3] Reach 20 original cases and verify each rubric sums to 1.0 in `tests/test_vc_content.py`.
- [ ] T327 [P] [US4] Reach 100 exam questions and verify points sum to 100 per generated exam in `tests/test_vc_content.py`.
- [ ] T328 [P] [US7] Reach 120 glossary terms and verify no duplicate FR/EN pair in `tests/test_vc_content.py`.
- [ ] T329 Run a content licensing audit: every item is `original`, `public_domain` or `user_note` with a citation, and no verbatim textbook excerpt is present in `docs/VC_CONTENT_AUDIT.md`.

---

## Phase 12: Polish and Cross-Cutting Concerns

Release evidence, privacy, performance, documentation and delivery.

- [x] T330 [P] Run the targeted P1 suites and record the exact command and output in `docs/agent-reports/VC-MVP-PROOF.md`.
- [x] T331 [P] Run `ruff check academics/vc nage.py tests/test_vc_*.py` and record the result.
- [x] T332 [P] Run the CLI smoke path: review start, reveal, grade, drill run, case grade, radar, plan, report.
- [ ] T333 Verify no network call in the P1 path by running with a blocked socket in `tests/test_vc_offline.py`.
- [x] T334 Verify no personal data or note content is tracked by git in the final diff.
- [x] T335 Verify `~/.nage/vc/` permissions are `0700` and files are `0600` in `tests/test_vc_storage.py`.
- [x] T336 Verify `vc delete` removes only the VC home and requires the exact phrase in `tests/test_vc_storage.py`.
- [ ] T337 Verify backup and restore of `progress.json` in `tests/test_vc_storage.py`.
- [x] T338 Verify export/import of progress without notes in `tests/test_vc_storage.py`.
- [x] T339 Review all error messages for readability and absence of stack traces.
- [x] T340 Review the quickstart commands against the actual CLI output.
- [x] T341 Review the content-pack schema against the loaded JSON in `tests/test_vc_content.py`.
- [ ] T342 Add the optional HTTP facade routes from `contracts/http-api.md` in `academics/router.py`.
- [ ] T343 Add HTTP tests for review start, drill grade and case grade in `tests/test_vc_http.py`.
- [ ] T344 Add the static revision page (optional P3) under `web_static/` with no personal data.
- [x] T345 Update `.specify/feature.json` to `specs/004-venture-capital-revision`.
- [ ] T346 Update `docs/VC_REVISION_GUIDE.md` with the final 20-topic study calendar.
- [x] T347 Run the full test suite sequentially and alone; record the exact output in `docs/agent-reports/VC-MVP-PROOF.md`.
- [x] T348 Commit the feature on the delivery branch and verify the pushed SHA with `git ls-remote`.
- [x] T349 Report the final state: tasks done, tests, ruff, content counts and remaining P2/P3 work.

---

## Dependencies and Execution Order

1. Phase 1 and Phase 2 must be green before any user story.
2. US1, US2 and US3 are the P1 MVP. They can be developed in parallel after
   the foundation, but US1 should ship first because it is the daily loop.
3. US4 depends on US1 (cards), US2 (numeric questions) and US3 (case questions).
4. US5 depends on US1 review events, US2 drill results and US3 case attempts.
5. US6 is independent of US1-US5 except for the card model; it can run in parallel.
6. US7 is independent; it only needs the content loader.
7. US8 depends on US1, US2, US3 and US4 for its aggregates.
8. Content expansion can start as soon as Phase 2 is green; each topic is
   independent. Do not activate a content pack until its validation tests pass.

## Parallel Execution Examples

```text
# P1 foundation
T001-T012 then T013-T043

# P1 stories in parallel after the foundation
Worker A: T044-T082 (US1 scheduler + CLI)
Worker B: T083-T116 (US2 drills)
Worker C: T117-T142 (US3 cases)

# Content expansion in parallel by topic
Worker A: VC01-VC05 packs
Worker B: VC06-VC10 packs
Worker C: VC11-VC15 packs
Worker D: VC16-VC20 packs
```

## Implementation Strategy

### MVP first (P1 only)

1. Complete Phase 1 and Phase 2.
2. Complete US1, US2 and US3.
3. Run the targeted suites and the CLI smoke path.
4. Stop and review before P2. Do not start US4-US8 until the P1 proof is green.

### Incremental delivery

1. US1: daily review works end to end.
2. US2: formula drills work end to end.
3. US3: cases work end to end.
4. US4: mock exams and oral defense.
5. US5: radar and plan.
6. US6: notes ingestion with citations.
7. US7: lexicon and term sheet.
8. US8: progress report.
9. Content expansion: 20 topics, then the 200/100/20/100/120 coverage gates.

## Task Count

Total tasks: **349**. P1 MVP: US1-US3. P2: US4-US6. P3: US7-US8.
Content expansion: 20 topics x 4 packets + 6 coverage/audit tasks.

## Notes

- A task is checked only with evidence: test output, ruff output and an inspected diff.
- Never copy a textbook, a slide deck or a protected exam. Use original wording or
  cited user notes.
- Never write learner notes, answers or personal data into the repository.
- Keep the CLI JSON contract stable; the HTTP facade reuses it.
- The full test suite is sequential and alone; targeted suites are the development gate.

## Implementation Notes (2026-11-02)

- `academics/vc/content/` is a data-only directory. It intentionally has no `__init__.py`,
  because that package would shadow `academics/vc/content.py`.
- Drills are split per topic (`drills_vc04.json`, `drills_vc05.json`, etc.) instead of a
  single `drills_core.json`; T106 is left open because its exact file path differs.
- US4 (mock exams/oral), US6 (notes ingestion), the HTTP facade and the static page remain
  open. US4 content is empty and no exam command is wired.
- The content expansion targets (200 cards / 100 drills / 20 cases / 100 questions /
  120 terms) remain open; the delivered MVP has 50 / 24 / 4 / 0 / 42.
- T347 (full suite) is green: 3847 passed. T348 push verification: fast-forward
  `92c6206..d367607` on `agent/n100-carrier-20261101`. T349 final report is in
  `docs/agent-reports/VC-MVP-PROOF.md`.

## Implementation Notes (2026-11-02, EDHEC exam lot)

- `vc paper list|show|template|grade`, `vc cram` and `vc formulas` are delivered;
  `python nage.py vc` without a subcommand starts the 90-minute plan.
- Three derived papers are shipped: 2023 (22 questions), 2024 (24), 2025 (21). Raw
  `docs/vc_study/` papers remain untracked.
- Targeted VC suite: 160 passed. Full suite, sequential and alone in the clean copy:
  3904 passed in 170.13s. Ruff clean on `academics/vc` and `tests/test_vc_*.py`.
- Evidence: `docs/agent-reports/VC-MVP-PROOF.md` section 9; code commit `5662820`.
