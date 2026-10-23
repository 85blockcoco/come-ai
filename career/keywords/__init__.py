"""Convenience package re-exporting SPEC-019 keyword modules."""

from ..keyword_extract import (
    Keyword,
    KeywordProfile,
    extract_keywords,
    build_keyword_profile,
    analyze_keywords,
    extract,
    extract_keyword_profile,
    keywords_from_offer,
)
from ..keyword_scorer import (
    compute_weight,
    classify_kind,
    score_keyword,
    compute_coverage,
    find_gaps,
    score_keywords,
    apply_weights,
    weight_keyword,
)
from ..keyword_arena import (
    arena_consensus,
    consensus,
    run_arena,
    validate_keywords,
    filter_hallucinations,
)
from ..keyword_report import (
    build_report,
    render_json,
    render_html,
    generate_report,
)

__all__ = [
    "Keyword", "KeywordProfile", "extract_keywords", "build_keyword_profile",
    "analyze_keywords", "extract", "extract_keyword_profile", "keywords_from_offer",
    "compute_weight", "classify_kind", "score_keyword", "compute_coverage",
    "find_gaps", "score_keywords", "apply_weights", "weight_keyword",
    "arena_consensus", "consensus", "run_arena", "validate_keywords",
    "filter_hallucinations", "build_report", "render_json", "render_html",
    "generate_report",
]
