"""Scoring / weighting helpers for ATS keywords (SPEC-019)."""

from __future__ import annotations

from typing import Any

from .keyword_extract import Keyword, KeywordProfile, extract_keywords
from .models import normalized_text


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def compute_weight(
    freq_offer: float = 0.0,
    in_title_or_requirements: bool | int = False,
    web_stack_confirm: bool | int = False,
    jury_boost: bool | int = False,
) -> float:
    """Apply the SPEC-019 weighting formula."""
    weight = (
        0.5 * float(freq_offer)
        + 0.2 * (1.0 if in_title_or_requirements else 0.0)
        + 0.2 * (1.0 if web_stack_confirm else 0.0)
        + 0.1 * (1.0 if jury_boost else 0.0)
    )
    return round(_clamp(weight), 4)


def classify_kind(
    weight: float,
    *,
    freq_offer: float = 0.0,
    in_title_or_requirements: bool = False,
) -> str:
    w = float(weight)
    if w >= 0.6 or (freq_offer >= 0.5 and in_title_or_requirements):
        return "must"
    if w >= 0.3:
        return "nice"
    return "implicit"


def score_keyword(
    keyword: Keyword | dict[str, Any],
    *,
    freq_offer: float | None = None,
    in_title_or_requirements: bool | None = None,
    web_stack_confirm: bool | None = None,
    jury_boost: bool | None = None,
) -> Keyword:
    """Return a copy of ``keyword`` with recomputed weight/kind."""
    if isinstance(keyword, dict):
        kw = Keyword(**{k: v for k, v in keyword.items() if k in Keyword.__dataclass_fields__})
    else:
        kw = Keyword(
            term=keyword.term,
            normalized=keyword.normalized,
            category=keyword.category,
            weight=keyword.weight,
            kind=keyword.kind,
            evidence_refs=list(keyword.evidence_refs),
            synonyms=list(keyword.synonyms),
        )
    if freq_offer is None:
        # infer from weight? keep
        freq_offer = 0.0
    f = freq_offer
    t = in_title_or_requirements if in_title_or_requirements is not None else ("offer:title" in kw.evidence_refs or "offer:requirements" in kw.evidence_refs)
    w = web_stack_confirm if web_stack_confirm is not None else ("web:confirmed" in kw.evidence_refs)
    j = jury_boost if jury_boost is not None else ("arena:jury_boost" in kw.evidence_refs)
    kw.weight = compute_weight(f, bool(t), bool(w), bool(j))
    kw.kind = classify_kind(kw.weight, freq_offer=f, in_title_or_requirements=bool(t))  # type: ignore[arg-type]
    return kw


def compute_coverage(keywords: Any, profile: Any = None) -> dict[str, Any]:
    """Compute per-category coverage of ``keywords`` against ``profile``."""
    if isinstance(keywords, KeywordProfile):
        kw_list = keywords.keywords
    elif isinstance(keywords, list):
        kw_list = keywords
    else:
        kw_list = []

    profile_text = ""
    if isinstance(profile, dict):
        profile_text = " ".join(str(profile.get(f, "")) for f in ("skills", "experience", "projects", "education", "languages", "notes"))
    elif isinstance(profile, str):
        profile_text = profile
    profile_norm = normalized_text(profile_text)

    totals: dict[str, int] = {}
    covered_map: dict[str, int] = {}
    covered_terms: list[str] = []
    for kw in kw_list:
        k = kw if isinstance(kw, Keyword) else Keyword(**{x: kw[x] for x in kw if x in Keyword.__dataclass_fields__})
        totals[k.category] = totals.get(k.category, 0) + 1
        is_covered = k.normalized in profile_norm or any(s in profile_norm for s in k.synonyms)
        if is_covered:
            covered_map[k.category] = covered_map.get(k.category, 0) + 1
            covered_terms.append(k.normalized)

    result: dict[str, Any] = {}
    for cat in sorted(set(totals)):
        total = totals[cat]
        covered = covered_map.get(cat, 0)
        result[cat] = {
            "total": total,
            "covered": covered,
            "missing": total - covered,
            "coverage_pct": round((covered / total * 100) if total else 0.0, 1),
        }
    total_all = len(kw_list)
    covered_all = len(covered_terms)
    result["overall"] = {
        "total": total_all,
        "covered": covered_all,
        "missing": total_all - covered_all,
        "coverage_pct": round((covered_all / total_all * 100) if total_all else 0.0, 1),
    }
    return result


def find_gaps(keywords: Any, profile: Any = None) -> list[Keyword]:
    """Return keywords absent from ``profile``."""
    if isinstance(keywords, KeywordProfile):
        kw_list = keywords.keywords
    elif isinstance(keywords, list):
        kw_list = keywords
    else:
        kw_list = []

    profile_text = ""
    if isinstance(profile, dict):
        profile_text = " ".join(str(profile.get(f, "")) for f in ("skills", "experience", "projects", "education", "languages", "notes"))
    elif isinstance(profile, str):
        profile_text = profile
    profile_norm = normalized_text(profile_text)

    gaps: list[Keyword] = []
    for kw in kw_list:
        k = kw if isinstance(kw, Keyword) else Keyword(**{x: kw[x] for x in kw if x in Keyword.__dataclass_fields__})
        if not (k.normalized in profile_norm or any(s in profile_norm for s in k.synonyms)):
            gaps.append(k)
    return gaps


def score_keywords(
    keywords_or_profile: Any,
    *,
    profile: Any = None,
    web_results: Any = None,
    arena_results: Any = None,
    offer: Any = None,
) -> KeywordProfile:
    """Score a list/profile of keywords and return a KeywordProfile."""
    if isinstance(keywords_or_profile, KeywordProfile):
        profile_obj = keywords_or_profile
        kw_list = profile_obj.keywords
        offer_id = profile_obj.offer_id
    elif isinstance(keywords_or_profile, list):
        kw_list = keywords_or_profile
        offer_id = ""
        if isinstance(offer, dict):
            offer_id = str(offer.get("id") or offer.get("offer_id") or "")
    else:
        # maybe an offer passed directly
        return extract_keywords(keywords_or_profile, profile=profile, web_results=web_results, arena_results=arena_results)

    # if offer provided, re-extract to get scoring context is expensive; instead apply coverage
    coverage_profile = profile
    if coverage_profile is None and isinstance(offer, dict):
        coverage_profile = offer  # fallback

    # recompute coverage
    cov = compute_coverage(kw_list, coverage_profile)
    gaps = find_gaps(kw_list, coverage_profile)

    # apply web/arena boost to weights if provided
    web_text = normalized_text("" if web_results is None else (web_results if isinstance(web_results, str) else str(web_results)))
    arena_text = normalized_text("" if arena_results is None else (arena_results if isinstance(arena_results, str) else str(arena_results)))
    scored: list[Keyword] = []
    for kw in kw_list:
        k = kw if isinstance(kw, Keyword) else Keyword(**{x: kw[x] for x in kw if x in Keyword.__dataclass_fields__})
        web_confirm = k.normalized in web_text or "web:confirmed" in k.evidence_refs
        jury = k.normalized in arena_text or "arena:jury_boost" in k.evidence_refs
        # freq unknown here; keep relative by using current weight as freq proxy? Recompute minimal:
        k.weight = compute_weight(
            freq_offer=0.5,  # neutral if not provided
            in_title_or_requirements=("offer:title" in k.evidence_refs or "offer:requirements" in k.evidence_refs),
            web_stack_confirm=web_confirm,
            jury_boost=jury,
        )
        # blend with original weight to avoid losing freq info
        k.weight = round((k.weight + (kw.weight if isinstance(kw, Keyword) else 0.0)) / 2, 4)
        k.kind = classify_kind(k.weight, freq_offer=0.5, in_title_or_requirements=("offer:title" in k.evidence_refs or "offer:requirements" in k.evidence_refs))
        scored.append(k)

    return KeywordProfile(
        offer_id=offer_id,
        keywords=scored,
        score_coverage=cov,
        gaps=gaps,
        generated_at=(profile_obj.generated_at if isinstance(keywords_or_profile, KeywordProfile) else ""),
    )


def apply_weights(profile: KeywordProfile, **kwargs: Any) -> KeywordProfile:
    return score_keywords(profile, **kwargs)


def weight_keyword(*args: Any, **kwargs: Any) -> float:
    return compute_weight(*args, **kwargs)


# aliases
def score(*args: Any, **kwargs: Any) -> KeywordProfile:
    return score_keywords(*args, **kwargs)


def score_profile(*args: Any, **kwargs: Any) -> KeywordProfile:
    return score_keywords(*args, **kwargs)


def compute_score(*args: Any, **kwargs: Any) -> KeywordProfile:
    return score_keywords(*args, **kwargs)


def coverage(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return compute_coverage(*args, **kwargs)


def gaps(*args: Any, **kwargs: Any) -> list[Keyword]:
    return find_gaps(*args, **kwargs)


__all__ = [
    "compute_weight",
    "classify_kind",
    "score_keyword",
    "compute_coverage",
    "find_gaps",
    "score_keywords",
    "apply_weights",
    "weight_keyword",
    "score",
    "score_profile",
    "compute_score",
    "coverage",
    "gaps",
]
