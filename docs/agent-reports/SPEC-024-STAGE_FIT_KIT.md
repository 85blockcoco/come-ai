# SPEC-024 — Stage Fit Kit

## Livraison
Modules:
- `career/stage_fit_kit.py` — orchestrateur final (pipeline async, resumable, état JSON)
- `career/stage_fit_scorer.py` — scorecard avant/après (ATS, couverture, gaps, jury, preuves)
- `career/stage_fit_router.py` — routes `/stagefit/kit/...`
- `career_static/js/stage-fit-kit.js` — UI locale
- `tests/test_stage_fit_kit.py`

## Contrats
- `StageFitScorecard`: offer_id, ats_before, ats_after, keyword_coverage_before, keyword_coverage_after, gaps_unresolved, jury_summary, evidence_audit
- `StageFitKit`: kit_id, offer_id, cv_variant_json, letter_draft_id, docx_path, scorecard, pipeline_trace

## Validation
- Pipeline resumable via état JSON par kit.
- Aucun envoi automatique: export manuel uniquement.
- Ruff clean, suite verte, git diff --check.
