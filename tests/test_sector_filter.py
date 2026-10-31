"""Tests for sector filter (N100-C06)."""

from __future__ import annotations

import pytest

from career.sector_filter import classify_sector, filter_by_sector, SECTORS


CASES = [
    ("Stage finance M&A", "finance"),
    ("Software developer backend", "tech"),
    ("Consulting strategy", "consulting"),
    ("Marketing digital", "marketing"),
    ("Stage cuisine", "other"),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_classify(text, expected) -> None:
    assert classify_sector(text) == expected


def test_filter() -> None:
    offers = [
        {"title": "Stage finance", "sector": "finance"},
        {"title": "Dev backend", "sector": "tech"},
    ]
    out = filter_by_sector(offers, "finance")
    assert len(out) == 1
    assert out[0]["title"] == "Stage finance"


def test_filter_all() -> None:
    offers = [{"title": "a"}, {"title": "b"}]
    assert len(filter_by_sector(offers, "all")) == 2
    assert len(filter_by_sector(offers, "*")) == 2
    assert len(filter_by_sector(offers, "")) == 2


def test_sectors_tuple() -> None:
    assert "other" in SECTORS