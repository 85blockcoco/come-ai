"""Tests for profile validation (N100-D03)."""

from __future__ import annotations


from career.profile_validation import validate_profile, REQUIRED_FIELDS


def test_valid_profile() -> None:
    p = {"display_name": "Alice", "contact_email": "a@b.com", "education": "BBA", "experience": "Intern"}
    r = validate_profile(p)
    assert r.ok is True
    assert r.missing == []
    assert r.errors == []


def test_missing_fields() -> None:
    r = validate_profile({})
    assert r.ok is False
    assert set(r.missing) == set(REQUIRED_FIELDS)


def test_invalid_email() -> None:
    p = {"display_name": "A", "contact_email": "notanemail", "education": "BBA", "experience": "X"}
    r = validate_profile(p)
    assert r.ok is False
    assert any("format invalide" in e for e in r.errors)


def test_partial() -> None:
    p = {"display_name": "A", "contact_email": "a@b.com"}
    r = validate_profile(p)
    assert r.ok is False
    assert "education" in r.missing
    assert "experience" in r.missing