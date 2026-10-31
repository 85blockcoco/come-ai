"""Tests for duration detection (N100-B02)."""

from __future__ import annotations


from career.duration_detector import parse_duration_months, detect_duration


def test_months() -> None:
    assert parse_duration_months("stage de 6 mois") == 6
    assert parse_duration_months("6-month internship") == 6


def test_weeks() -> None:
    assert parse_duration_months("24 weeks") == 6


def test_none() -> None:
    assert parse_duration_months("no duration") is None


def test_min_six() -> None:
    r = detect_duration("stage de 6 mois", "2027-01-15")
    assert r.min_six_months is True
    assert r.months == 6


def test_less_than_six() -> None:
    r = detect_duration("stage de 3 mois", "2027-01-15")
    assert r.min_six_months is False


def test_end_date() -> None:
    r = detect_duration("6 months", "2027-01-15")
    assert r.end_date is not None
    assert r.end_date.startswith("2027-07")


def test_no_end_date() -> None:
    r = detect_duration("6 months", "")
    assert r.end_date is None


def test_empty() -> None:
    r = detect_duration("", "")
    assert r.months is None
    assert r.min_six_months is False