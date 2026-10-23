"""Multi-AI consensus helpers for ATS keywords (SPEC-019 / SPEC-017)."""

from __future__ import annotations

from typing import Any

from .keyword_extract import Keyword, KeywordProfile
from .models import normalized_text


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, dict):
        out: list[Any] = []
        for v in value.values():
            if isinstance(v, (list, tuple, set)):
                out.extend(v)
            else:
                out.append(v)
        return out
    return [value]


def _norm_set(value: Any) -> set[str]:
    terms: set[str] = set()
    for item in _as_list(value):
        if isinstance(item, str):
            terms.add(normalized_text(item))
        elif isinstance(item, dict):
            for key in ("term", "keyword", "skill", "text", "value", "normalized"):
                if key in item and item[key]:
                    terms.add(normalized_text(str(item[key])))
        elif isinstance(item, Keyword):
            terms.add(normalized_text(item.normalized or item.term))
    return {t for t in terms if t}


def _offer_corpus(offer: Any) -> str:
    if offer is None:
        return ""
    if isinstance(offer, str):
        return normalized_text(offer)
    if isinstance(offer, dict):
        return normalized_text(" ".join(str(v) for v in offer.values() if isinstance(v, (str, int, float))))
    return normalized_text(str(offer))


def _has_evidence(kw: Keyword) -> bool:
    refs = kw.evidence_refs or []
    if not refs:
        return False
    # evidence must point to offer/web/extractor, never to invented source
    for ref in refs:
        r = str(ref).lower()
        if r.startswith("offer:") or r.startswith("web:") or r.startswith("extractor") or r.startswith("arena"):
            return True
    return False


def arena_consensus(
    keywords: Any,
    *,
    offer: Any = None,
    offer_text: str | None = None,
    profile: Any = None,
    ai_votes: Any = None,
    web_results: Any = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Run a local, deterministic consensus over ``keywords``.

    Returns a dict with ``keywords`` (approved list), ``approved``,
    ``rejected``, ``boosted`` and ``hallucinations_removed``.
    """
    if isinstance(keywords, KeywordProfile):
        kw_list = list(keywords.keywords)
        offer_id = keywords.offer_id
    elif isinstance(keywords, list):
        kw_list = []
        for item in keywords:
            if isinstance(item, Keyword):
                kw_list.append(item)
            elif isinstance(item, dict):
                kw_list.append(Keyword(**{k: v for k, v in item.items() if k in Keyword.__dataclass_fields__}))
        offer_id = ""
    else:
        kw_list = []
        offer_id = ""

    corpus = _offer_corpus(offer) if offer is not None else ""
    if offer_text:
        corpus = (corpus + " " + normalized_text(offer_text)).strip()
    if not corpus and isinstance(keywords, KeywordProfile):
        # no corpus available; keep all with evidence
        corpus = ""

    web_norm = normalized_text("" if web_results is None else (web_results if isinstance(web_results, str) else str(web_results)))
    votes = _norm_set(ai_votes)

    approved: list[Keyword] = []
    rejected: list[Keyword] = []
    boosted_terms: list[str] = []
    removed: list[str] = []

    for kw in kw_list:
        # hallucination guard: must have evidence or be present in corpus/web
        present_in_corpus = (not corpus) or (kw.normalized in corpus) or (kw.normalized in web_norm)
        if not (_has_evidence(kw) or present_in_corpus):
            removed.append(kw.normalized)
            rejected.append(kw)
            continue
        # consensus: if votes provided, require term in votes OR in corpus/web
        if votes:
            in_votes = kw.normalized in votes
            if not (in_votes or kw.normalized in corpus or kw.normalized in web_norm):
                removed.append(kw.normalized)
                rejected.append(kw)
                continue
            if in_votes:
                boosted_terms.append(kw.normalized)
                kw.evidence_refs = list(kw.evidence_refs) + (["arena:jury_boost"] if "arena:jury_boost" not in kw.evidence_refs else [])
                # bump weight slightly
                kw.weight = round(min(1.0, kw.weight + 0.1), 4)
        # recompute kind
        from .keyword_scorer import classify_kind

        kw.kind = classify_kind(kw.weight, freq_offer=0.5, in_title_or_requirements=("offer:title" in kw.evidence_refs or "offer:requirements" in kw.evidence_refs))  # type: ignore[assignment]
        approved.append(kw)

    return {
        "offer_id": offer_id,
        "keywords": approved,
        "approved": [k.normalized for k in approved],
        "rejected": [k.normalized for k in rejected],
        "boosted": boosted_terms,
        "hallucinations_removed": removed,
        "consensus_threshold": threshold,
    }


def consensus(keywords: Any, **kwargs: Any) -> list[Keyword]:
    """Return the approved keyword list (convenience)."""
    return list(arena_consensus(keywords, **kwargs)["keywords"])


def run_arena(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return arena_consensus(*args, **kwargs)


def validate_keywords(keywords: Any, **kwargs: Any) -> list[Keyword]:
    return list(arena_consensus(keywords, **kwargs)["keywords"])


def jury_boost_terms(ai_votes: Any) -> set[str]:
    return _norm_set(ai_votes)


def filter_hallucinations(keywords: Any, *, offer: Any = None, offer_text: str | None = None) -> list[Keyword]:
    result = arena_consensus(keywords, offer=offer, offer_text=offer_text or "")
    return list(result["keywords"])


# aliases
def consensus_keywords(*args: Any, **kwargs: Any) -> list[Keyword]:
    return consensus(*args, **kwargs)


def arena(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return arena_consensus(*args, **kwargs)


__all__ = [
    "arena_consensus",
    "consensus",
    "run_arena",
    "validate_keywords",
    "jury_boost_terms",
    "filter_hallucinations",
    "consensus_keywords",
    "arena",
]
