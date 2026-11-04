# VC coverage audit - 4 November 2026

## Evidence inspected

The local authorised course folder contains 29 non-hidden files: 26 PDFs and 3 XLSX workbooks. The PDFs contain 1,494 pages; 1,478 pages have extractable text and 16 pages require visual review because text extraction is empty. The three workbooks contain 14 sheets and 249 formula cells.

The indexed study library contains 20 PDFs and 2,381,571 extracted characters. It does not yet contain two files from the folder: `7017_69368.pdf` (14 pages, all pages without extractable text) and `Team project 2027.pdf` (2 pages). These are not silently treated as covered.

The primary course maps the five lecture decks to 5 chapters and 28 lessons. The application content pack contains 21 topics, 189 active cards, 44 static drills, 4 cases, 32 deterministic mock questions and past-paper packs for 2023, 2024 and 2025.

## Coverage by topic

| Topic | Cards | Drills | Cases | Mock questions | Past-paper questions | Assessment |
|---|---:|---:|---:|---:|---:|---|
| VC01 ecosystem | 8 | generated | 0 | 3 | 4 | partial |
| VC02 fund economics | 8 | 0 | 0 | 0 | 2 | thin |
| VC03 stages/instruments | 10 | generated | 1 | 4 | 7 | full |
| VC04 valuation/ownership | 10 | 11 + generated | 1 | 10 | 13 | full |
| VC05 cap table/option pool | 10 | 6 + generated | 1 | 9 | 3 | full |
| VC06 term sheet | 8 | 0 | 0 | 6 | 5 | partial |
| VC07 liquidation/waterfall | 10 | 8 + generated | 1 | 7 | 2 | full |
| VC08 anti-dilution | 8 | 8 | 0 | 2 | 2 | partial |
| VC09 return metrics | 10 | 6 + generated | 0 | 7 | 3 | full |
| VC10 fundraising/due diligence | 8 | 0 | 0 | 0 | 1 | thin |
| VC11 portfolio/reserves | 8 | 0 | 0 | 0 | 0 | thin |
| VC12 governance/boards | 8 | 0 | 0 | 0 | 0 | thin |
| VC13 exits | 8 | 0 | 0 | 10 | 10 | full |
| VC14 metrics/unit economics | 8 | 0 | 0 | 2 | 3 | partial |
| VC15 modelling/scenarios | 8 | 0 | 0 | 0 | 0 | thin |
| VC16 legal instruments | 8 | 0 | 0 | 2 | 2 | partial |
| VC17 European context | 8 | 0 | 0 | 1 | 1 | partial |
| VC18 investment memo/thesis | 8 | 0 | 0 | 0 | 0 | thin |
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

The workbook audit also identified the exercise families that still need a
dedicated in-app graded representation: staged-financing survival and expected
profit (PhD student), risk-sensitive term-sheet choice (TriplexGo and
TrafalgarTech), cap tables and staged rounds (Aliboy), venture-capital method
and comparables (NextBigThing and Sky-π), common equity versus convertible note
(Hadupower), expected founder wealth and threshold probabilities (Docklane),
seed/VC ownership (Vale), IPO pricing, greenshoe and underpricing (Meridian),
and the Venture Evaluation Matrix weighted scoring tool. The source workbooks
remain available and are not silently counted as graded exercises yet.

## Gaps requiring caution

- The two unindexed PDFs need manual visual review before their content can be called covered.
- The workbooks are available in the library, but their exercise logic is not yet fully converted into graded in-app exercises.
- Thin topics need additional course-grounded cards and exercises if time permits, especially fund economics, fundraising/due diligence, portfolio construction, governance, financial modelling, investment memo and exam method.
- Empty-text PDF pages may contain scanned figures or tables that text-only indexing cannot prove.

## Interpretation

The five lecture decks and the three past-paper packs have a strong core path. It would be inaccurate to say that every file and every notion is already represented by a lesson and a graded exercise. The next safe additions should be generated exercises tied to the workbook methods and an explicit visual review of the 16 empty-text pages, with every new item labelled as course-grounded, official past-paper derived or synthetic.
