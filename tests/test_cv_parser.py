"""Tests for CV parser (N100-D02)."""

from __future__ import annotations

from career.cv_parser import parse_cv_sections, CVSections, to_dict


SAMPLE = """
Education
BBA Finance, ESSEC

Experience
Intern at Acme, 6 months

Skills
Excel, Python

Languages
English, French
"""


def test_parse_sections() -> None:
    s = parse_cv_sections(SAMPLE)
    assert isinstance(s, CVSections)
    assert any("BBA" in x for x in s.education)
    assert any("Intern" in x for x in s.experience)
    assert any("Excel" in x for x in s.skills)
    assert any("English" in x for x in s.languages)


def test_empty() -> None:
    s = parse_cv_sections("")
    assert s.education == []
    assert s.experience == []


def test_to_dict() -> None:
    s = parse_cv_sections(SAMPLE)
    d = to_dict(s)
    assert "education" in d
    assert "experience" in d