# Feature Specification: Connect ATS Diagnostics to Targeted CV Variants and Build Complete Offer-to-Application Pipeline

**Feature Branch**: `003-ats-diagnostic-cv-variants-pipeline`

**Created**: 2026-10-21

**Status**: Draft

**Input**: User description: "Build on the delivered Application Sprint queue and ATS diagnostic to connect structural CV risks to targeted CV variants (M&A/Investment Banking, Markets/Quant, Corporate Finance/FP&A), produce a clear 'current CV → adapted CV for this offer' comparison, measure CV coverage against mandatory and preferred requirements, improve experience recognition in Canva PDFs, and validate a real end-to-end cycle: official ad → qualification → adapted CV → letter → tracking — all without automatic submission."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See CV Fit Gaps for a Specific Offer with Targeted Variant Guidance (Priority: P1)

As a Career Explorer user, after building my Application Sprint queue and selecting an offer to prepare, I want to see exactly how my current CV falls short against that offer's mandatory and preferred requirements, mapped to the relevant CV variant (M&A, Markets, or Corporate Finance), so I know precisely which experiences to highlight, quantify, or restructure.

**Why this priority**: The Application Sprint queue now surfaces readiness states and grouped verifications, and the ATS diagnostic identifies structural risks. But the user still lacks the critical link: which variant of their CV to use for *this* offer, and what specific changes close the gap. This is the highest-leverage addition to turn preparation into action.

**Independent Test**: Can be tested by selecting an offer in the sprint queue, clicking "Préparer", and verifying the prep panel shows: (a) mandatory/preferred requirement coverage percentage, (b) recommended CV variant with rationale, (c) side-by-side "current CV section → adapted CV section" diff for the top 3 gaps, (d) quantified evidence suggestions tied to the user's approved profile.

**Acceptance Scenarios**:

1. **Given** an M&A offer requiring "financial modeling", "valuation", "transaction rationale", **When** the user opens the prep panel, **Then** the recommended variant is "M&A / Investment Banking", mandatory coverage shows < 60%, and the diff suggests adding a quantified "Built 3-statement LBO model for X deal" bullet under the relevant experience.

2. **Given** a Markets offer requiring "Python", "statistical analysis", "Bloomberg", **When** the user opens the prep panel, **Then** the recommended variant is "Markets / Quant", the diff highlights missing Python project quantification, and the advice references the user's approved profile evidence (e.g., "SMBC automation: 500+ files processed").

3. **Given** an offer where the user's CV has no detected "Projects" section (ATS risk: MISSING_SECTION), **When** the prep panel loads, **Then** the diff shows "Projects: absent → add quantified project entries aligned to variant keywords" with variant-specific examples.

---

### User Story 2 - Generate a Targeted CV Kit for One Offer in One Click (Priority: P1)

As a Career Explorer user, once I've reviewed the fit gaps and variant recommendation for an offer, I want to generate a complete, editable local application kit (CV + cover letter + prep sheet) pre-populated with the adapted content for that variant, so I can review, finalize, and submit manually without starting from a blank page.

**Why this priority**: Application Studio already exists but doesn't yet consume the variant-aware gap analysis. Connecting them closes the loop: sprint queue → prep analysis → variant selection → kit generation → tracking. No automatic submission, ever.

**Independent Test**: Can be tested by clicking "Créer le kit local" from the sprint card or prep panel, selecting the recommended variant, and verifying the generated CV DOCX contains: (a) single-column ATS-safe structure, (b) variant-tailored section ordering and keywords, (c) quantified bullets drawn from approved profile evidence, (d) explicit availability and graduation timeline, (e) cover letter referencing the offer's specific requirements.

**Acceptance Scenarios**:

1. **Given** an M&A offer and the M&A variant selected, **When** the kit is generated, **Then** the CV leads with "Professional Experience" (reverse chronological), includes a "Transaction Experience" or "Valuation Projects" subsection, uses UK English spelling, and the cover letter cites "financial modeling" and "deal rationale" with the user's quantified examples.

2. **Given** a Markets offer and the Markets variant selected, **When** the kit is generated, **Then** the CV leads with "Technical Skills" and "Quantitative Projects", includes Python/Bloomberg/statistics keywords, uses US English spelling, and the cover letter emphasizes data-driven analysis and automation results.

3. **Given** the user has not yet added quantified evidence for a mandatory requirement, **When** the kit is generated, **Then** the affected bullet shows a placeholder tag `[AJOUTER PREUVE CHIFFRÉE]` and the prep sheet lists it as a blocking action.

---

### User Story 3 - Track the Complete Cycle from Offer to Submission-Ready Kit (Priority: P2)

As a Career Explorer user, I want a single dashboard view showing every offer I've processed through the full cycle — discovered → qualified → sprint-queued → prep-analyzed → variant-selected → kit-generated → tracking-created — so I can see end-to-end progress without switching tabs.

**Why this priority**: The sprint queue, prep panel, application studio, and tracker exist but aren't visually unified. A consolidated "pipeline" view reinforces the disciplined workflow and makes it obvious where each offer stands.

**Independent Test**: Can be tested by completing the flow for 3+ offers and verifying a new "Pipeline" or "Cycle complet" view shows each offer with its current stage badge (discovered / qualified / sprint / prep / kit / tracked), variant used, kit generation timestamp, and tracking stage.

**Acceptance Scenarios**:

1. **Given** 3 offers at different pipeline stages, **When** the user opens the pipeline view, **Then** all 3 appear with correct stage badges and variant labels.

2. **Given** an offer whose kit was generated but tracking not yet created, **When** viewing the pipeline, **Then** a "Créer le suivi" action is prominent for that row.

---

### User Story 4 - Improved Experience Extraction from Canva/Complex PDFs (Priority: P2)

As a Career Explorer user importing my CV, I want the ATS diagnostic to correctly identify *all* my experiences (not just 1 out of 5+) even when the PDF comes from Canva with columns, text boxes, or non-linear layout, so the downstream variant adaptation has complete source material.

**Why this priority**: The current diagnostic detected only 1 experience from the user's real Canva PDF despite multiple roles. This upstream gap propagates: missing experiences → lower coverage → weaker variant adaptation → weaker kit. Fixing extraction quality amplifies all downstream value.

**Independent Test**: Can be tested by importing the user's actual Canva PDF (or a synthetic equivalent with multi-column layout) and verifying the diagnostic detects ≥ 4 distinct experiences with company, role, dates, and at least 2 quantified bullets each.

**Acceptance Scenarios**:

1. **Given** a Canva PDF with 2-column layout (left: dates/locations, right: role descriptions), **When** imported, **Then** the parser correctly associates left-column dates with right-column descriptions for each experience.

2. **Given** a PDF with floating text boxes for each role, **When** imported, **Then** the reading order reconstruction groups each box's content into a coherent experience entry.

3. **Given** a PDF where experience descriptions span multiple pages, **When** imported, **Then** the parser stitches contiguous blocks belonging to the same role.

---

### Edge Cases

- What happens when an offer matches *two* variants equally (e.g., M&A + Markets hybrid)? → Present both variants with coverage scores; let user choose; default to the variant with higher mandatory coverage.
- What happens when the user has *zero* approved profile evidence for a mandatory requirement? → Show requirement as "blocked: no evidence in profile"; kit generation inserts placeholder; prep sheet lists "Ajouter preuve au profil" as prerequisite action.
- What happens when the ATS diagnostic finds TABLE_DETECTED but the user insists on keeping their Canva layout? → Still generate the single-column variant kit; show a warning that the visual CV may parse poorly; never modify the user's original file.
- What happens when qualification missing_fields includes "start_date" but the user's availability window is already in profile? → Pre-fill availability in the kit; flag the offer's missing start_date as "to verify on official page" in verification_summary.
- What happens when the user edits the generated kit locally? → Changes stay local only; re-generating the kit for the same offer/variant re-applies the variant template (user edits are not auto-merged — by design, to keep the template deterministic).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST classify each offer in the sprint queue into a primary CV variant (M&A/IB, Markets/Quant, Corporate Finance/FP&A) based on its job_family, requirements text, and qualification provenance.
- **FR-002**: System MUST compute mandatory vs. preferred requirement coverage for the user's *current* CV against the selected offer, using the ATS diagnostic's detected sections, experiences, and the approved profile's evidence.
- **FR-003**: System MUST produce a structured diff: for each top gap (max 5), show "current CV state" (missing section, unquantified experience, wrong keyword, wrong order) → "adapted CV state" (variant-specific section, quantified bullet template, keyword placement, single-column order).
- **FR-004**: System MUST recommend the optimal CV variant with a rationale (e.g., "M&A variant: 4/5 mandatory keywords match job_family 'M&A / Investment Banking'; 3 quantified experiences in profile support this").
- **FR-005**: Application Studio MUST accept a `variant` parameter (m_a | markets | corporate_finance) and generate a CV DOCX with: single-column layout, variant-tailored section ordering, variant keyword density, UK/US English per variant, explicit availability/graduation block, and placeholder tags for missing evidence.
- **FR-006**: Application Studio MUST generate a cover letter referencing the offer's top 3 mandatory requirements with the user's matched quantified evidence (or placeholders).
- **FR-007**: Application Studio MUST generate a prep sheet listing: offer facts to verify, profile evidence gaps, variant-specific interview talking points, and a checklist of "before you submit" items.
- **FR-008**: System MUST persist the variant used for each generated kit and expose it in the pipeline/tracking view.
- **FR-009**: The CV parser (structure.py) MUST improve experience detection recall on multi-column/Canva PDFs by implementing reading-order reconstruction (left-to-right, top-to-bottom within visual blocks) and heading-proximity grouping.
- **FR-010**: The CV parser MUST detect and normalize date ranges in Canva PDFs where dates are in a separate visual column from descriptions.
- **FR-011**: System MUST expose a new `/api/career/application-pipeline` endpoint returning the unified pipeline view for all tracked offers.
- **FR-012**: System MUST NOT send any CV, letter, or application automatically. All generation is local; submission remains manual.
- **FR-013**: All new facts displayed in the prep diff and generated kit MUST carry provenance citations to the approved profile or offer qualification (Constitution Principle IV).
- **FR-014**: System MUST be idempotent: re-generating a kit for the same offer+variant produces identical output (given unchanged profile/offer).

### Key Entities

- **CV Variant**: A named template configuration (m_a, markets, corporate_finance) defining section order, keyword priorities, English locale, section headers, and cover letter tone.
- **Fit Gap**: A structured record linking an offer requirement to the user's current CV state (missing, weak, unquantified, wrong variant) and the adapted recommendation (add section, quantify bullet, swap keyword, reorder).
- **Application Kit**: A generated artifact bundle (cv.docx, cover_letter.docx, prep_sheet.md) for a specific offer+variant, with provenance metadata.
- **Pipeline Stage**: An enum (discovered, qualified, sprint_queued, prep_analyzed, variant_selected, kit_generated, tracking_created) tracking end-to-end progress per offer.
- **Approved Profile Evidence**: The user-verified profile fields (education, experience, skills, languages, projects) that serve as the *only* source for CV content — no invention allowed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 10 test offers spanning the 3 job families, the variant recommendation matches the job_family in ≥ 9/10 cases.
- **SC-002**: Mandatory requirement coverage calculation is accurate: for 5 offers with known ground truth, the computed coverage % matches manual audit within ±5%.
- **SC-003**: The "current → adapted" diff identifies ≥ 3 actionable gaps per offer where the user has approved profile evidence but the CV lacks it.
- **SC-004**: Generated M&A kit passes a local ATS parse test (structure.py) with: 0 TABLE_DETECTED, 0 MISSING_SECTION for required sections, ≥ 4 detected experiences, ≥ 80% quantified experiences.
- **SC-005**: Generated Markets kit passes the same ATS parse test with Technical Skills and Quantitative Projects sections detected.
- **SC-006**: Canva PDF experience detection recall improves from 1/5 (20%) to ≥ 4/5 (80%) on the user's real CV and 3 synthetic Canva-equivalent PDFs.
- **SC-007**: Pipeline view displays all offers with correct stage for 5 test offers processed through the full cycle.
- **SC-008**: 100% of generated kit content traces to approved profile evidence or offer qualification (zero invented facts).
- **SC-009**: Full test suite passes (1387+ tests), including new integration tests for the pipeline.
- **SC-010**: Zero regression on existing Career features (application sprint, qualification persistence, ATS diagnostic).

## Assumptions

- The `career/application_sprint.py` queue, `career/cv_quality/structure.py` diagnostic, and `career/application_studio.py` kit generator are the three pillars to connect — no new major modules needed.
- The approved profile (`candidate_profile` table) remains the single source of truth for user evidence; kit generation never invents facts.
- Variant definitions (section order, keywords, locale) can be expressed as pure Python data structures in a new `career/cv_variants.py` module.
- The existing `DocumentInput` / `CVAnalysisResult` types in `cv_quality/models.py` are sufficient to carry the diff data; no schema changes needed.
- The `application_studio.py` already produces DOCX; we only need to parameterize its template by variant.
- The user's real Canva PDF is available for regression testing (not committed to repo; tested locally).
- All work remains local-first, deterministic, and consent-gated for any cloud enhancement (Constitution Principles II, III).
- No changes to the `jobs` table schema required; pipeline stage is derived from existing tables (stage_matches, applications, profile_imports, application_drafts).

---

*This specification defines WHAT the user needs and WHY. Implementation details (HOW) will be determined in the planning phase (`$speckit-plan`).*
