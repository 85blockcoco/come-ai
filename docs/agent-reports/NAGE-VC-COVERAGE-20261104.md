# VC coverage audit - 4 November 2026

## Evidence inspected

The local authorised course folder contains 29 non-hidden files: 26 PDFs and 3 XLSX workbooks. The PDFs contain 1,494 pages; 1,478 pages have extractable text and 16 pages require visual review because text extraction is empty. The three workbooks contain 14 sheets and 249 formula cells.

The indexed study library contains 20 PDFs and 2,381,571 extracted characters. `7017_69368.pdf` is a 14-page scan with seven printed exam pages and seven blank reverse sides; visual comparison confirms that its seven exam pages duplicate the 2024 paper already represented by `paper_2024.json`. `Team project 2027.pdf` is a two-page pitchbook brief; it is now represented by a rubric-based case rather than being treated as a single-answer exam.

The primary course maps the five lecture decks to 5 chapters and 28 lessons. The application content pack contains 21 topics, 189 active cards, 44 static drills, 15 graded cases (including 11 workbook-derived/rubric cases), 32 deterministic mock questions and past-paper packs for 2023, 2024 and 2025.

## Coverage by topic

| Topic | Cards | Drills | Cases | Mock questions | Past-paper questions | Assessment |
|---|---:|---:|---:|---:|---:|---|
| VC01 ecosystem | 8 | generated | 0 | 3 | 4 | partial |
| VC02 fund economics | 8 | 0 | 0 | 0 | 2 | thin |
| VC03 stages/instruments | 10 | generated | 3 | 4 | 7 | full |
| VC04 valuation/ownership | 10 | 11 + generated | 3 | 10 | 13 | full |
| VC05 cap table/option pool | 10 | 6 + generated | 3 | 9 | 3 | full |
| VC06 term sheet | 8 | 0 | 0 | 6 | 5 | partial |
| VC07 liquidation/waterfall | 10 | 8 + generated | 2 | 7 | 2 | full |
| VC08 anti-dilution | 8 | 8 | 0 | 2 | 2 | partial |
| VC09 return metrics | 10 | 6 + generated | 0 | 7 | 3 | full |
| VC10 fundraising/due diligence | 8 | 0 | 0 | 0 | 1 | thin |
| VC11 portfolio/reserves | 8 | 0 | 0 | 0 | 0 | thin |
| VC12 governance/boards | 8 | 0 | 0 | 0 | 0 | thin |
| VC13 exits | 8 | 0 | 1 | 10 | 10 | full |
| VC14 metrics/unit economics | 8 | 0 | 1 | 2 | 3 | partial |
| VC15 modelling/scenarios | 8 | 0 | 0 | 0 | 0 | thin |
| VC16 legal instruments | 8 | 0 | 1 | 2 | 2 | partial |
| VC17 European context | 8 | 0 | 0 | 1 | 1 | partial |
| VC18 investment memo/thesis | 8 | 0 | 1 | 0 | 0 | partial |
| VC19 venture debt | 10 | 5 | 0 | 0 | 0 | partial |
| VC20 exam/case method | 8 | 0 | 0 | 0 | 0 | thin |
| VC21 advanced products/governance | 17 | 0 | 0 | 0 | 0 | thin |

“Generated” means a fresh-number exercise is available at runtime and is not a claim that a static source exercise exists for every topic. The levels above are a planning signal, not a claim that the exam will contain every topic equally.

## What was added in this audit lot

- Fresh-number drills now count in the progress radar for VC03, VC04, VC05, VC07 and VC09.
- The Practice selector exposes those generated drills even when there is no static JSON drill for the topic.
- The audit preserves a distinction between official past-paper material, course-grounded content and synthetic practice.

## Verification added on 4 November

The regression test `tests/test_vc_pastpaper_coverage.py` now loads the three
official packs and checks the complete assessment inventory: 67 top-level
questions plus 33 nested case parts (100 assessed units). It also submits the
answer key through the same grader used by the application and verifies that
every MCQ, numeric item and case part reaches either an automatic `correct`
result or an explicit `self_assess` path for open responses. The targeted run
was green: **2 passed in 0.14 s**. Ruff and `git diff --check` are also clean
for the changed files.

The API smoke check on the running candidate reports all three papers and their
real pack sizes: 2023 (22 questions, 60 points), 2024 (24 questions, 50 points)
and 2025 (21 questions, 60 points). This proves ingestion and grading paths;
it does not prove that a learner has mastered the material.

The workbook audit identified the exercise families that needed a dedicated
in-app graded representation. They are now covered by `cases_workbooks.json`:
staged-financing survival and expected profit (PhD student), risk-sensitive
term-sheet choice (TriplexGo and TrafalgarTech), cap tables and staged rounds
(Aliboy), venture-capital method and comparables (NextBigThing), common equity
versus convertible note (Hadupower), expected founder wealth and option-pool
dilution (Docklane), seed/VC ownership (Vale), IPO pricing, greenshoe and
underpricing (Meridian), Venture Evaluation Matrix weighted scoring, and the
Team Project pitchbook rubric. Each case exposes `workbook_derived` provenance
and its source reference; it is not presented as an official exam answer.

## Gaps requiring caution

- The 7017 scan has been visually checked and is a duplicate of 2024; its handwritten student code is not copied into the repository.
- The Team Project is qualitative by design, so its rubric is graded by criteria and cannot be reduced to one numerical answer.
- Thin topics need additional course-grounded cards and exercises if time permits, especially fund economics, fundraising/due diligence, portfolio construction, governance, financial modelling, investment memo and exam method.
- Empty-text PDF pages may contain scanned figures or tables that text-only indexing cannot prove.

## Interpretation

The five lecture decks, three past-paper packs and workbook-derived cases now form a strong exam path. It would still be inaccurate to say that every page has been semantically certified: the remaining 16 empty-text pages in other PDFs need visual/OCR review, and thin non-exam topics may need more cards. All newly added workbook exercises are explicitly labelled as adaptations, while official past-paper material remains separate.
