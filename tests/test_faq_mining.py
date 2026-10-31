"""Tests for sector FAQ mining (SPEC-031)."""

from __future__ import annotations

import json
from pathlib import Path


from career.faq_mining import (
    cluster_intents,
    mine_sector_faq,
    expected_questions,
    _tokenize,
)


FIXTURE = Path(__file__).parent / "fixtures" / "faq_offers_synthetic.json"


def _offers():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["offers"]


def test_cluster_groups_by_sector() -> None:
    offers = _offers()
    groups = cluster_intents(offers)
    assert "finance" in groups
    assert "tech" in groups
    assert len(groups["finance"]) == 2
    assert len(groups["tech"]) == 1


def test_cluster_unknown_sector_general() -> None:
    groups = cluster_intents([{"description": "x"}])
    assert "general" in groups


def test_mine_returns_one_per_sector() -> None:
    faqs = mine_sector_faq(_offers())
    sectors = [f.sector for f in faqs]
    assert sectors == sorted(sectors)
    assert "finance" in sectors
    assert "tech" in sectors


def test_top_terms_frequencies() -> None:
    faqs = mine_sector_faq(_offers())
    fin = next(f for f in faqs if f.sector == "finance")
    terms = dict(fin.top_terms)
    assert "excel" in terms
    assert terms["excel"] >= 2


def test_likely_questions_non_empty() -> None:
    faqs = mine_sector_faq(_offers())
    for f in faqs:
        assert len(f.likely_questions) >= 1
        assert len(f.likely_questions) <= 5


def test_profile_answers_subset_of_top_terms() -> None:
    faqs = mine_sector_faq(_offers(), profile_terms=["excel", "python"])
    fin = next(f for f in faqs if f.sector == "finance")
    for q, ans in fin.profile_answers.items():
        for a in ans:
            assert a in {t[0] for t in fin.top_terms}


def test_empty_offers() -> None:
    faqs = mine_sector_faq([])
    assert faqs == []


def test_tokenize_filters_stopwords() -> None:
    toks = _tokenize("Le stage en finance et le reporting Excel")
    assert "finance" in toks
    assert "excel" in toks
    assert "le" not in toks
    assert "et" not in toks


def test_expected_questions_helper() -> None:
    faqs = mine_sector_faq(_offers())
    qs = expected_questions(faqs[0])
    assert isinstance(qs, list)
    assert qs == faqs[0].likely_questions


def test_top_n_parameter() -> None:
    faqs = mine_sector_faq(_offers(), top_n=3)
    for f in faqs:
        assert len(f.top_terms) <= 3


def test_deterministic() -> None:
    a = mine_sector_faq(_offers())
    b = mine_sector_faq(_offers())
    assert [f.top_terms for f in a] == [f.top_terms for f in b]


def test_adversarial_empty_description() -> None:
    offers = [{"sector": "finance", "description": ""}, {"sector": "finance", "description": None}]
    faqs = mine_sector_faq(offers)
    assert len(faqs) == 1
    assert faqs[0].top_terms == [] or isinstance(faqs[0].top_terms, list)


def test_to_dict_roundtrip() -> None:
    from dataclasses import asdict
    faqs = mine_sector_faq(_offers())
    d = asdict(faqs[0])
    assert "sector" in d
    assert "top_terms" in d