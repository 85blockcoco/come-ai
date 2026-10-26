"""Tests for the sector FAQ mining module (SPEC-031)."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from career.faq_mining import (
    SectorFaq,
    cluster_intents,
    expected_questions,
    mine_sector_faq,
)

FIXTURES = Path(__file__).parent / "fixtures" / "faq_offers_synthetic.json"


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network is forbidden")
    monkeypatch.setattr(socket, "create_connection", blocked)
    if hasattr(socket, "getaddrinfo"):
        monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def offers():
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def test_cluster_intents_groups_by_sector(offers):
    clusters = cluster_intents(offers)
    assert isinstance(clusters, dict)
    assert "M&A / Investment Banking" in clusters
    assert len(clusters["M&A / Investment Banking"]) == 2
    assert "Sales & Trading" in clusters
    assert "Corporate Finance" in clusters


def test_top_terms_frequencies_are_deterministic(offers):
    result = mine_sector_faq(offers)
    faqs = [result] if isinstance(result, SectorFaq) else list(result)
    ma = next(f for f in faqs if "M&A" in f.sector)
    terms = dict(ma.top_terms)
    assert terms.get("valuation", 0) >= 2 or terms.get("excel", 0) >= 2
    assert ma.top_terms == sorted(ma.top_terms, key=lambda x: (-x[1], x[0]))


def test_mine_sector_faq_returns_sector_faq(offers):
    result = mine_sector_faq(offers)
    assert result is not None
    faqs = [result] if isinstance(result, SectorFaq) else list(result)
    assert all(isinstance(f, SectorFaq) for f in faqs)
    assert all(f.likely_questions for f in faqs)
    assert all(isinstance(f.profile_answers, dict) for f in faqs)


def test_expected_questions_returns_list(offers):
    questions = expected_questions("M&A / Investment Banking", offers=[o for o in offers if "M&A" in o["sector"]])
    assert isinstance(questions, list)
    assert all(isinstance(q, str) for q in questions)
    assert len(questions) >= 3


def test_profile_answers_use_profile_evidence(offers):
    profile = {"skills": "Financial modeling, Excel, valuation", "experience": "M&A internship valuation"}
    result = mine_sector_faq(offers, profile)
    faqs = [result] if isinstance(result, SectorFaq) else list(result)
    ma = next(f for f in faqs if "M&A" in f.sector)
    assert any(ma.profile_answers.get(q) for q in ma.likely_questions)


def test_determinism(offers):
    a = mine_sector_faq(offers)
    b = mine_sector_faq(offers)
    def serialize(x):
        if isinstance(x, SectorFaq):
            return x.to_dict()
        return [i.to_dict() for i in x]
    assert serialize(a) == serialize(b)


def test_sector_filter(offers):
    result = mine_sector_faq(offers, sector="Corporate Finance")
    assert isinstance(result, SectorFaq)
    assert result.sector == "Corporate Finance"


def test_adversarial_empty_offers():
    result = mine_sector_faq([])
    assert result is not None


def test_adversarial_missing_fields():
    offers = [{"id": "x"}, {"title": 123, "requirements": None}]
    result = mine_sector_faq(offers)
    assert result is not None


def test_expected_questions_with_top_terms():
    qs = expected_questions(top_terms=[("excel", 5), ("valuation", 3)])
    assert isinstance(qs, list)
    assert any("excel" in q.lower() or "valuation" in q.lower() for q in qs)


def test_top_terms_is_list_of_tuples(offers):
    result = mine_sector_faq(offers)
    faqs = [result] if isinstance(result, SectorFaq) else list(result)
    for f in faqs:
        for term in f.top_terms:
            assert isinstance(term, tuple) and len(term) == 2
            assert isinstance(term[1], int)


def test_rest_smoke(tmp_path):
    from fastapi.testclient import TestClient
    from come_ai_web import create_app
    client = TestClient(create_app(tmp_path))
    offers = json.loads(FIXTURES.read_text(encoding="utf-8"))
    resp = client.post("/api/career/faq-mine", json={"offers": offers})
    assert resp.status_code == 200
    resp2 = client.get("/api/career/faq-mine")
    assert resp2.status_code == 200