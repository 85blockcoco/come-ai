"""Tests for degree level detection (N100-B05)."""

from __future__ import annotations

import pytest

from career.degree_level import detect_degree_level, is_accessible_bba_bac4


CASES = [
    ("Requires a PhD in Finance", "phd"),
    ("MBA preferred", "mba"),
    ("Master 2 (M2) in Finance", "m2"),
    ("Master 1 (M1)", "m1"),
    ("Bachelor's degree (Bac+4)", "bac+4"),
    ("BBA required", "bba"),
    ("Open to all", "unknown"),
    ("", "unknown"),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_detect(text, expected) -> None:
    assert detect_degree_level(text) == expected


def test_accessible() -> None:
    assert is_accessible_bba_bac4("bba") is True
    assert is_accessible_bba_bac4("bac+4") is True
    assert is_accessible_bba_bac4("m1") is True
    assert is_accessible_bba_bac4("mba") is False
    assert is_accessible_bba_bac4("phd") is False


def test_case_insensitive() -> None:
    assert detect_degree_level("MBA REQUIRED") == "mba"


def test_bba_alone() -> None:
    assert detect_degree_level("BBA graduate") == "bba"