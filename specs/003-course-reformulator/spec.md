# Specification: Course & Education Reformulator

## Feature Overview
Reformulate and prioritize courses, formations, and certifications to align with specific internship requirements. This module aims to highlight the relevance of academic background without inventing information.

## Actors
- Internship Candidate (User)
- AI Reformulator (System)

## User Scenarios
1. User provides a target internship profile.
2. System extracts and reformulates courses/formations/certifications based on relevance to the internship's required skills.
3. System presents a ranked list of reformulated academic entries.
4. User reviews and applies the changes to their CV.

## Functional Requirements
- Link each course/formation/certification to specific internship requirements (based on SPEC-018 and SPEC-019).
- Ensure original course titles remain visible (e.g., as tooltips).
- Reject fake course assertions.
- Do not boost expired certifications unless marked as such.
- Implement an arena-style consensus mechanism (2-3 reformulations).
- Generate `EducationPlan` dataclass.

## Success Criteria
- 100% traceability between reformulated entries and proof refs.
- Realistic re-prioritization that boosts relevancy.
- No invented academic data.
- Successful pass of `tests/test_course_reformulator.py`.

## Assumptions
- Internship profiles are provided in a structured format (JSON/dataclass).
- The system has access to the user's validated academic history.
