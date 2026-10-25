# Research Findings: Connect ATS Diagnostics to Targeted CV Variants Pipeline

**Feature**: 003-ats-diagnostic-cv-variants-pipeline
**Date**: 2026-10-21

---

## Unknowns Resolved from Technical Context

| Unknown | Decision | Rationale | Alternatives Considered |
|---------|----------|-----------|-------------------------|
| Variant definition format | Pure Python dataclasses in `career/cv_variants.py` | Matches existing codebase patterns (`models.py`, `scoring.py`, `offer_qualification.py`); no external config files; type-safe, discoverable, testable | YAML/JSON config files (adds parser dependency, less type-safe), Python dict constants (less structured) |
| Coverage computation | Extend existing `cv_coverage` from `application_prep.py` + `qualification.missing_fields` | Already computes `supported`/`to_verify`/`coverage_percent`; adds mandatory vs preferred split using qualification provenance | New coverage engine from scratch (reinvents existing logic), LLM-based (violates Constitution Principle II) |
| Diff representation | `FitGap` dataclasses with `current_state`, `adapted_state`, `provenance` | Fits `CVAnalysisResult` extension pattern; serializable for JS; carries citations per Constitution Principle IV | Plain dicts (loses type safety), string-only descriptions (loses structured provenance) |
| Kit template parameterization | Template DOCX per variant + python-docx programmatic injection | `application_studio.py` already uses python-docx; variant selects template + injects variant-specific content | Jinja2 on XML (complex, fragile), separate code paths per variant (duplication) |
| Canva PDF reading order | pdfplumber `extract_words()` with (x0, top, x1, bottom) → sort by top, then x0 | pdfplumber already in deps; coordinates enable column detection; left-to-right within visual bands | pdfminer.six (lower-level, more complex), OCR-based (overkill, violates local-first) |
| Pipeline stage derivation | Computed at query time from existing tables (no schema change) | Assumptions explicitly state no schema changes; derived from `stage_matches`, `applications`, `application_drafts` | New `pipeline_stage` column (requires migration, violates assumptions), event log table (new table) |
| JS pipeline view | New panel in `index.html` + `renderApplicationPipeline()` in `career.js` | Consistent with existing sprint/detail/prep panels (`renderApplicationSprint`, `renderStagePrep`) | Separate page (breaks SPA pattern), modal (less discoverable) |

---

## Dependency Best Practices

| Dependency | Version | Usage in Feature | Notes |
|------------|---------|------------------|-------|
| pdfplumber | Latest | Canva PDF word extraction with coordinates | Already in `requirements.txt` via `cv_quality` |
| python-docx | Latest | DOCX generation for CV/letter kits | Already used in `application_studio.py` |
| FastAPI | Latest | Pipeline endpoint | Already in `come_ai_web.py` |
| pytest | Latest | All tests | Constitution Principle V |
| Ruff | Latest | Linting | Constitution Principle V |

No new dependencies required — all already present in project.

---

## Integration Patterns (from existing codebase)

| Pattern | Location | Reused For |
|---------|----------|------------|
| Pure function pipeline | `application_sprint.build_application_sprint` | `cv_fit.classify_variant`, `cv_fit.compute_coverage`, `cv_fit.generate_diff` |
| Provenance maps | `offer_qualification.py`, `qualification_persistence.py` | `FitGap.provenance`, kit citations |
| Deterministic ID generation | `service.py` (job IDs, import IDs) | Kit output directory naming |
| Consent-gated cloud calls | `service.py` `get_job_summary` | N/A — feature is fully local |
| SQLite WAL + read-only reporting | `service.py` connections | Pipeline endpoint uses read-only connection |
| Structured logging | `workspace_core.py` | All new modules |

---

## Synthetic Test Fixtures Strategy

**Canva PDF fixtures** (generated in `tests/fixtures/canva_pdfs/` at test runtime, not committed):

1. **Two-column layout**: Left column = dates/locations, Right column = role descriptions (5 experiences)
2. **Floating text boxes**: Each role in separate absolute-positioned text box (4 experiences)
3. **Multi-page experience**: Single role description spans page 1 → page 2 (3 experiences, one split)
4. **Mixed layout**: Columnar header + floating boxes for projects (4 experiences + 2 projects)

Generated via `reportlab` or `fpdf2` in test setup — ensures deterministic, version-controlled fixtures without committing binary PDFs.

---

## Decision Log

| Date | Decision | Author | Linked Spec Section |
|------|----------|--------|---------------------|
| 2026-10-21 | Variant definitions as frozen dataclasses in `cv_variants.py` | Planning | Assumptions, FR-001 |
| 2026-10-21 | Coverage extends `cv_coverage` with mandatory/preferred split | Planning | FR-002 |
| 2026-10-21 | Diff as `FitGap` list with provenance | Planning | FR-003, FR-013 |
| 2026-10-21 | Kit generation uses template DOCX per variant | Planning | FR-005, FR-006, FR-007 |
| 2026-10-21 | Pipeline stage derived, not stored | Planning | FR-011, Assumptions |
| 2026-10-21 | Canva PDF reading order via pdfplumber coordinates | Planning | FR-009, FR-010 |

---

*All NEEDS CLARIFICATION resolved. Ready for Phase 1 design artifacts.*
