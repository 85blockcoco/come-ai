# SPEC-021 — Course & Education Reformulator

## Modules
- `career/course_reformulate.py` — academic pipeline (courses, mixins, certifications)
- `career/course_ranker.py` — reorder education sections for the offer
- `career/course_router.py` — FastAPI router
- `career_static/js/course-reformulator.js` — UI helper

## Contracts
- `ReformulatedCourse(course_id, original_title, adapted_title, link_to_stage, evidence_refs, rank_delta, jury_score)`
- `EducationPlan(courses, reordered_list, certifications_boosted)`

## Rules enforced
- Original course title remains visible (tooltip "cours réel: X").
- No course absent from the approved profile is included (anti-invention).
- Expired certifications are not boosted unless expiration is mentioned.
- Arena: 2-3 reformulations generated per course; jury score selects best-of-consensus; diff sheet provided.

## API
- `POST /reformulate/education/{offer_id}` → `EducationPlan`
- `POST /reformulate/education/apply` → applies order + adapted titles, returns diff.

## Validation
- `ruff` clean, full pytest suite green, `git diff --check`.
