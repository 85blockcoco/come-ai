"""Tests for letter personalization (N100-F04)."""

from __future__ import annotations

from career.letter_personalization import personalize_letter, to_dict, _PLACEHOLDER


BASE = "Madame, Monsieur,\n\nCandidature pour un stage.\n\nCordialement,\nAlice"


def test_with_facts() -> None:
    r = personalize_letter(BASE, company="Acme", company_facts=["Leader asset management européen"])
    assert "Acme" in r.personalized_body
    assert "Leader asset management" in r.personalized_body
    assert r.uses_placeholder is False
    assert "Cordialement" in r.personalized_body


def test_fact_inserted_before_closing() -> None:
    r = personalize_letter(BASE, company="Acme", company_facts=["Fait X"])
    body = r.personalized_body
    assert body.index("Fait X") < body.index("Cordialement")


def test_no_facts_placeholder() -> None:
    r = personalize_letter(BASE, company="Acme")
    assert _PLACEHOLDER in r.personalized_body
    assert r.uses_placeholder is True
    assert any("aucun fait" in w for w in r.warnings)


def test_empty_body_warning() -> None:
    r = personalize_letter("", company="Acme")
    assert any("vide" in w for w in r.warnings)


def test_no_closing_appends() -> None:
    body = "Lettre sans signature"
    r = personalize_letter(body, company="B", company_facts=["X"])
    assert "X" in r.personalized_body


def test_to_dict() -> None:
    d = to_dict(personalize_letter(BASE))
    assert "personalized_body" in d
