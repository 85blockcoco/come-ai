"""Tests for SPEC-019 ATS Keywords Intelligence."""

from __future__ import annotations


from career.keyword_extract import (
    Keyword,
    KeywordProfile,
    extract_keywords,
)
from career.keyword_scorer import compute_weight, compute_coverage, find_gaps
from career.keyword_arena import arena_consensus
from career.keyword_report import build_report, render_json


def _offer():
    return {
        "id": "OFF-KW-01",
        "title": "Data Analyst (Trading)",
        "requirements": "Required: advanced Excel.\nGerman would be a bonus.\nPython, SQL",
    }


def test_extract_returns_profile():
    profile = extract_keywords(_offer())
    assert isinstance(profile, KeywordProfile)
    assert profile.offer_id == "OFF-KW-01"
    assert isinstance(profile.keywords, list)
    assert all(isinstance(k, Keyword) for k in profile.keywords)
    assert profile.generated_at


def test_expected_terms_present():
    profile = extract_keywords(_offer())
    terms = {k.normalized for k in profile.keywords}
    for expected in ("excel", "german", "python", "sql"):
        assert expected in terms, f"{expected} missing from {terms}"


def test_no_term_outside_offer():
    offer = _offer()
    profile = extract_keywords(offer)
    corpus = " ".join(str(v) for v in offer.values()).lower()
    for kw in profile.keywords:
        assert kw.normalized in corpus or kw.normalized.replace(" ", "") in corpus.replace(" ", ""), (
            f"{kw.normalized} not found in offer"
        )


def test_weights_bounded():
    profile = extract_keywords(_offer(), web_results="python", arena_results="excel")
    for kw in profile.keywords:
        assert 0.0 <= kw.weight <= 1.0
        assert kw.kind in {"must", "nice", "implicit"}


def test_weight_formula():
    assert compute_weight(1.0, True, True, True) == 1.0
    assert compute_weight(0.0, False, False, False) == 0.0
    assert compute_weight(0.5, True, False, False) == 0.45


def test_coverage_and_gaps():
    profile = extract_keywords(_offer(), profile={"skills": "Python, Excel"})
    cov = compute_coverage(profile.keywords, {"skills": "Python, Excel"})
    assert "overall" in cov
    assert cov["overall"]["total"] == len(profile.keywords)
    gaps = find_gaps(profile.keywords, {"skills": "Python, Excel"})
    assert all(isinstance(g, Keyword) for g in gaps)
    # german and sql should be gaps
    gap_terms = {g.normalized for g in gaps}
    assert "german" in gap_terms


def test_arena_does_not_hallucinate():
    profile = extract_keywords(_offer())
    res = arena_consensus(profile.keywords, offer=_offer(), ai_votes=["rust", "cobol"])
    approved_terms = {k.normalized for k in res["keywords"]}
    # hallucinated votes not in offer must not be added
    assert "rust" not in approved_terms
    assert "cobol" not in approved_terms
    # all original offer terms remain
    for kw in profile.keywords:
        assert kw.normalized in approved_terms


def test_arena_boosts_votes_in_offer():
    profile = extract_keywords(_offer())
    res = arena_consensus(profile.keywords, offer=_offer(), ai_votes=["python"])
    boosted = res["boosted"]
    assert "python" in boosted


def test_report():
    profile = extract_keywords(_offer())
    report = build_report(profile)
    assert report["summary"]["total_keywords"] == len(profile.keywords)
    assert "keywords" in report
    json_str = render_json(profile)
    assert "OFF-KW-01" in json_str


def test_determinism():
    a = extract_keywords(_offer())
    b = extract_keywords(_offer())
    assert [k.normalized for k in a.keywords] == [k.normalized for k in b.keywords]
    assert [k.weight for k in a.keywords] == [k.weight for k in b.keywords]


def test_empty_offer():
    profile = extract_keywords({})
    assert profile.keywords == []
    assert profile.gaps == []
    assert profile.score_coverage["overall"]["total"] == 0


def test_str_input():
    profile = extract_keywords("Python and SQL required")
    terms = {k.normalized for k in profile.keywords}
    assert "python" in terms
    assert "sql" in terms


def test_web_confirmation_boosts_weight():
    base = extract_keywords(_offer())
    boosted = extract_keywords(_offer(), web_results="python sql")
    base_w = {k.normalized: k.weight for k in base.keywords}
    boosted_w = {k.normalized: k.weight for k in boosted.keywords}
    assert boosted_w["python"] >= base_w["python"]
    assert boosted_w["sql"] >= base_w["sql"]


def test_category_values():
    profile = extract_keywords(_offer())
    allowed = {"hard_skill", "soft_skill", "tool", "method", "domain", "language", "certification"}
    for kw in profile.keywords:
        assert kw.category in allowed


def test_evidence_refs_nonempty():
    profile = extract_keywords(_offer())
    for kw in profile.keywords:
        assert isinstance(kw.evidence_refs, list)
        assert len(kw.evidence_refs) >= 1


def test_synonyms_list():
    profile = extract_keywords(_offer())
    for kw in profile.keywords:
        assert isinstance(kw.synonyms, list)


def test_keyword_dataclass_defaults():
    kw = Keyword()
    assert kw.term == ""
    assert kw.evidence_refs == []
    assert kw.synonyms == []

