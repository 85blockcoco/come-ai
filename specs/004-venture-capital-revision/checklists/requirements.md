# Requirements Quality Checklist: Venture Capital Revision Coach

**Purpose**: Review the specification for completeness, clarity, consistency,
measurability and exam usefulness before implementation.
**Created**: 2026-11-02
**Feature**: [spec.md](../spec.md)

**Review Ownership**: This checklist is reviewer-owned. Mark an item `[x]` only
when the requirement-quality criterion is satisfied. `[x]` does not mean the
implementation is complete.

## Scope and Priorities

- [ ] CHK001 The P1 stories (review, formula lab, case studio) form a usable MVP without P2/P3.
- [ ] CHK002 Every user story has an independent test and a clear value statement.
- [ ] CHK003 The scope excludes Career data, application sending and cloud models.
- [ ] CHK004 The feature is explicitly framed as exam revision, not as a replacement for the course.
- [ ] CHK005 The 20-topic curriculum covers the course outline without claiming to be exhaustive.
- [ ] CHK006 Content licensing is explicit: original content or user notes only.
- [ ] CHK007 The feature works offline and stores data outside the repository.
- [ ] CHK008 The MVP does not require a web UI, a database migration or a new paid dependency.

## Active Recall and Scheduling

- [ ] CHK009 The scheduler states the exact grade values and interval rules.
- [ ] CHK010 Due cards and new cards have a deterministic order.
- [ ] CHK011 An interrupted session resumes with all recorded answers.
- [ ] CHK012 A card is never answered twice in one session.
- [ ] CHK013 The summary reports seen, correct, to-consolidate and due-tomorrow counts.
- [ ] CHK014 The reason for proposing a card is visible to the learner.
- [ ] CHK015 `again` and `hard` are distinguished; both do not silently become `good`.
- [ ] CHK016 The scheduler handles a card with no prior progress and a suspended card.
- [ ] CHK017 The scheduler handles a date change and a clock at midnight.
- [ ] CHK018 Retention at 1/7/30 days is defined from review events, not guessed.

## Formula Lab

- [ ] CHK019 Every drill has a prompt, variables, canonical answer, unit, tolerance and steps.
- [ ] CHK020 The covered formulas include pre/post-money, dilution, option pool, cap table, waterfall, IRR, MOIC, TVPI, DPI and RVPI.
- [ ] CHK021 Unit parsing accepts `€`, `k€`, `M€`, `%`, `x`, spaces and commas.
- [ ] CHK022 Ambiguous or non-numeric input is rejected without losing exercise state.
- [ ] CHK023 Error diagnosis distinguishes formula, order, unit, missing data and convention.
- [ ] CHK024 Alternative conventions are accepted only when declared by the drill.
- [ ] CHK025 The correction shows every step, not only the final number.
- [ ] CHK026 A drill's expected answer is recomputable from its variables and steps.
- [ ] CHK027 A wrong answer never reveals a different drill's answer.
- [ ] CHK028 Rounding rules are explicit and consistent with the tolerance.

## Case Studio

- [ ] CHK029 Every case has a context, facts, questions, rubric, model answer and allowed numbers.
- [ ] CHK030 Each rubric criterion is evaluated separately with a weight.
- [ ] CHK031 Weights sum to 1.0 within tolerance.
- [ ] CHK032 A number absent from the facts and intermediates is flagged as unsupported.
- [ ] CHK033 The model answer is hidden until submission.
- [ ] CHK034 The score is explicitly described as rubric-based, not human grading.
- [ ] CHK035 A down-round case shows the waterfall priority order.
- [ ] CHK036 A case with a missing fact is rejected at content validation, not at grading.
- [ ] CHK037 Case answers are stored locally and are not logged.

## Mock Exam and Oral

- [ ] CHK038 Exam composition is deterministic for the same seed and topic filter.
- [ ] CHK039 Points sum to 100 and every question has a topic.
- [ ] CHK040 Timer expiry preserves entered answers and grades them.
- [ ] CHK041 The score is recomputable from the stored answers.
- [ ] CHK042 Per-topic scores drive the remedial plan.
- [ ] CHK043 Oral follow-ups do not reveal the model answer.
- [ ] CHK044 An exam with fewer available questions than requested fails with a readable message.

## Weakness Radar and Plan

- [ ] CHK045 A topic with zero attempts is `untested`, never `solid`.
- [ ] CHK046 Accuracy is null when there are zero attempts.
- [ ] CHK047 The radar lists due cards and top error categories.
- [ ] CHK048 The plan never exceeds the requested minutes.
- [ ] CHK049 The plan orders activities by exam urgency, weakness and due cards.
- [ ] CHK050 Every activity has a reason the learner can read.
- [ ] CHK051 The plan handles no exam date, no weak topic and a very small capacity.
- [ ] CHK052 The plan does not recommend a topic with no available content.

## Notes Ingestion

- [ ] CHK053 Every proposed card has a source id, locator and exact quote.
- [ ] CHK054 No card is activated without explicit approval.
- [ ] CHK055 An uncertain extraction is `a_completer`, never invented.
- [ ] CHK056 A rejected proposal is not automatically reintroduced.
- [ ] CHK057 A scanned PDF without text is rejected with a clear message.
- [ ] CHK058 Notes are stored outside the repository and never logged.
- [ ] CHK059 A changed source file is flagged, not silently re-ingested.
- [ ] CHK060 Duplicate proposals from the same source are deduplicated.

## Glossary and Term Sheet

- [ ] CHK061 The lexicon covers at least 120 terms at program completion.
- [ ] CHK062 Search is accent-insensitive and matches FR/EN terms.
- [ ] CHK063 An unknown term returns `non documenté`, not a guess.
- [ ] CHK064 Term-sheet decoding explains the economic effect of each clause.
- [ ] CHK065 Liquidation preference, anti-dilution, board, drag-along, tag-along and pro-rata are covered.
- [ ] CHK066 Unknown clauses are listed separately and never invented.

## Progress Report

- [ ] CHK067 Every report number is recomputable from stored data.
- [ ] CHK068 The report lists untested topics separately.
- [ ] CHK069 The report includes coverage, retention, due cards, weak topics and next actions.
- [ ] CHK070 The report is readable offline and contains no raw notes.
- [ ] CHK071 The report period is explicit and handles an empty period.

## Non-Functional Requirements

- [ ] CHK072 Session selection over 1,000 cards is under 300 ms.
- [ ] CHK073 A grade and its persistence are under 20 ms.
- [ ] CHK074 The radar over 10,000 events is under 500 ms.
- [ ] CHK075 All storage writes are atomic and permissions are `0700`/`0600`.
- [ ] CHK076 A corrupt progress file is backed up and does not crash the CLI.
- [ ] CHK077 No network call is made by any P1 command.
- [ ] CHK078 No personal data, key or note content is in the repository.
- [ ] CHK079 Deleting VC data requires the exact confirmation phrase and touches only the VC home.
- [ ] CHK080 The CLI returns exit code 2 for invalid input and 0 for an empty result.

## Consistency and Traceability

- [ ] CHK081 Every FR has at least one task in `tasks.md`.
- [ ] CHK082 Every user story has tests and an independent verification command.
- [ ] CHK083 Every success criterion has a measurement method.
- [ ] CHK084 The data model matches the content-pack schema and the CLI JSON.
- [ ] CHK085 The quickstart commands match the CLI contract.
- [ ] CHK086 The plan's constitution exception is explicit and scoped.
- [ ] CHK087 The tasks distinguish P1 MVP from P2/P3 backlog.
- [ ] CHK088 The content expansion tasks are assigned per topic and measurable.
- [ ] CHK089 The spec avoids copyrighted material and cites user notes.
- [ ] CHK090 The definition of done requires tests, ruff and an inspected diff.

## Notes

- Mark items `[x]` only after review confirms the requirement-quality criterion.
- Leave items unchecked when they require clarification, correction or reviewer
  evaluation.
- `$speckit-implement` reads checklist checkbox state as a gate and must not
  modify markers.
