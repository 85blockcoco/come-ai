"""Tests for finance family classifier (N100-C07)."""

from __future__ import annotations

import pytest

from career.finance_family import classify_finance_family, FAMILIES


CASES = [
    ("Stage M&A fusion acquisition", "m&a"),
    ("Investment banking advisory", "cib"),
    ("Corporate finance valuation DCF", "corporate finance"),
    ("Trading markets sales", "markets"),
    ("Risk compliance", "risk"),
    ("Audit comptabilité", "audit"),
    ("Consulting strategy", "consulting"),
    ("Stage marketing", "other"),
    ("", "other"),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_classify(text, expected) -> None:
    assert classify_finance_family(text) == expected


def test_families_tuple() -> None:
    assert "other" in FAMILIES
    assert len(FAMILIES) == 8


def test_case_insensitive() -> None:
    assert classify_finance_family("M&A FUSION") == "m&a"