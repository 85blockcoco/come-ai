"""Tests for geo exclusions (N100-B07)."""

from __future__ import annotations

from career.geo_exclusions import is_excluded, filter_excluded


def test_excluded() -> None:
    assert is_excluded("Paris, France", ["france"]) is True
    assert is_excluded("London, UK", ["france"]) is False


def test_case_insensitive() -> None:
    assert is_excluded("PARIS", ["paris"]) is True


def test_filter() -> None:
    offers = [{"location": "Paris"}, {"location": "London"}]
    out = filter_excluded(offers, ["paris"])
    assert len(out) == 1
    assert out[0]["location"] == "London"


def test_empty_exclusions() -> None:
    offers = [{"location": "Paris"}]
    assert len(filter_excluded(offers, [])) == 1