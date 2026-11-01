"""Regression test registry (N100-J06).

Declares the targeted test files per lot so CI/tooling can run them
selectively.  Running the full suite in parallel is FORBIDDEN by project
rules — this registry lists exactly which files matter for each change.
"""

from __future__ import annotations

REGRESSION_FILES: dict[str, list[str]] = {
    "connectors": [
        "tests/test_uk_sources.py",
        "tests/test_de_sources.py",
        "tests/test_es_sources.py",
        "tests/test_us_sources.py",
    ],
    "qualification": [
        "tests/test_duration_detector.py",
        "tests/test_contract_type.py",
        "tests/test_degree_level.py",
        "tests/test_geo_exclusions.py",
    ],
    "matching": [
        "tests/test_sector_filter.py",
        "tests/test_urgency_shortlist.py",
        "tests/test_offer_rationale.py",
    ],
    "profile": [
        "tests/test_profile_validation.py",
        "tests/test_cv_parser.py",
        "tests/test_cv_pipeline.py",
    ],
    "letters": [
        "tests/test_letter_language.py",
        "tests/test_letter_check.py",
        "tests/test_letter_pipeline.py",
    ],
    "kit": [
        "tests/test_bundle_export.py",
        "tests/test_followup_engine.py",
    ],
    "reliability": [
        "tests/test_recovery.py",
        "tests/test_circuit_breaker.py",
        "tests/test_ai_cache.py",
        "tests/test_model_fallback.py",
    ],
}


def file_paths_for_lots(lots: list[str] | tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for lot in lots:
        out.extend(REGRESSION_FILES.get(str(lot).lower(), []))
    return sorted(set(out))


def all_registry_files() -> list[str]:
    return file_paths_for_lots(list(REGRESSION_FILES))
