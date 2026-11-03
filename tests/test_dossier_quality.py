"""Tests for dossier quality audit (SPEC-042)."""

from __future__ import annotations


from career.claim_check import check_claims, ats_keyword_stuffing, ClaimReport, EXAGGERATION_TERMS
from career.dossier_quality import score_dossier, to_dict, QualityReport


def test_check_claims_empty() -> None:
    r = check_claims("", ["proof"])
    assert isinstance(r, ClaimReport)
    assert r.claims == []
    assert r.score == 0.0 or r.score == 100.0  # empty -> total=1 -> score 0 (no supported)


def test_supported_claim() -> None:
    ev = ["Managed a team of 5 engineers at Acme"]
    doc = "I managed a team of 5 engineers at Acme."
    r = check_claims(doc, ev)
    assert r.summary["supported"] >= 1


def test_inflated_claim() -> None:
    ev = ["Worked on data analysis"]
    doc = "I am an expert in data analysis."
    r = check_claims(doc, ev)
    assert r.summary["inflated"] >= 1


def test_invented_claim() -> None:
    ev = ["Worked on data analysis"]
    doc = "I led a team of 100 people."
    r = check_claims(doc, ev)
    assert r.summary["invented"] >= 1 or r.summary["unverifiable"] >= 1


def test_out_of_context_number() -> None:
    ev = ["Increased revenue by 10%"]
    doc = "Increased revenue by 40%."
    r = check_claims(doc, ev)
    assert r.summary["out_of_context"] >= 1 or r.summary["invented"] >= 1


def test_unverifiable_no_evidence() -> None:
    doc = "This is a generic statement."
    r = check_claims(doc, [])
    assert r.summary["unverifiable"] >= 1 or r.summary["invented"] >= 1


def test_score_range() -> None:
    ev = ["Managed a team of 5 engineers"]
    doc = "Managed a team of 5 engineers."
    q = score_dossier(doc, ev)
    assert 0.0 <= q.score <= 100.0


def test_score_high_for_supported() -> None:
    ev = ["Built a dashboard with Python and SQL"]
    doc = "Built a dashboard with Python and SQL."
    q = score_dossier(doc, ev)
    assert q.score >= 50.0


def test_score_low_for_invented() -> None:
    ev = ["Worked on data"]
    doc = "I invented a new programming language and led 1000 people."
    q = score_dossier(doc, ev)
    assert q.score < 80.0


def test_to_dict() -> None:
    q = score_dossier("Hello world.", [])
    d = to_dict(q)
    assert "score" in d
    assert "factors" in d
    assert "claims" in d


def test_ats_stuffing_detected() -> None:
    text = "python python python python python"
    terms = ats_keyword_stuffing(text, threshold=3)
    assert "python" in terms


def test_ats_stuffing_none() -> None:
    text = "python java sql"
    terms = ats_keyword_stuffing(text, threshold=3)
    assert terms == []


def test_exaggeration_terms_keys() -> None:
    assert "expert" in EXAGGERATION_TERMS
    assert "senior" in EXAGGERATION_TERMS


def test_quality_report_dataclass() -> None:
    q = QualityReport(score=50.0, validated_ratio=0.5, exaggeration_density=0.1, evidence_coverage=0.5)
    assert q.score == 50.0


def test_multiple_sentences() -> None:
    ev = ["Managed team", "Built dashboard"]
    doc = "Managed team. Built dashboard. Invented new language."
    r = check_claims(doc, ev)
    assert len(r.claims) == 3


def test_claim_has_suggestion_when_not_supported() -> None:
    ev = ["Worked on data"]
    doc = "I am an expert in quantum computing."
    r = check_claims(doc, ev)
    non_supported = [c for c in r.claims if c.label != "supported"]
    for c in non_supported:
        assert c.suggestion is not None or c.missing is not None


def test_adversarial_number_moved() -> None:
    ev = ["Increased sales by 10 percent"]
    doc = "Increased sales by 90 percent."
    r = check_claims(doc, ev)
    assert r.summary.get("out_of_context", 0) >= 1 or r.summary.get("invented", 0) >= 1


def test_evidence_coverage_factor() -> None:
    ev = ["Built dashboard"]
    doc = "Built dashboard. Unknown fact here."
    q = score_dossier(doc, ev)
    assert 0.0 <= q.evidence_coverage <= 1.0


def test_stuffing_penalty_reduces_score() -> None:
    ev = ["python developer"]
    doc = "python python python python python developer"
    q1 = score_dossier(doc, ev)
    q2 = score_dossier("python developer", ev)
    assert q1.score <= q2.score


def test_empty_document() -> None:
    q = score_dossier("", ["proof"])
    assert q.score >= 0.0
    assert isinstance(q.claims, list)