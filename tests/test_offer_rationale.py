"""Tests for offer rationale (N100-C05)."""

from career.offer_rationale import build_rationale, to_dict


def test_build() -> None:
    r = build_rationale("j1", 85.0, [("location", 0.9), ("skills", 0.8)])
    assert r.score == 85.0
    assert "j1" in r.explanation
    assert len(r.factors) == 2


def test_no_factors() -> None:
    r = build_rationale("j2", 50.0)
    assert "aucun" in r.explanation


def test_to_dict() -> None:
    r = build_rationale("j3", 70.0, [("x", 0.5)])
    d = to_dict(r)
    assert d["job_id"] == "j3"