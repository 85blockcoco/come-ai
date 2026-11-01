"""Tests for multilingual letter rendering (N100-F02, N100-F03)."""

from __future__ import annotations

from career.letter_language import (
    LETTER_LANGS, TONES, render_multilingual_letter, to_dict,
)


def test_french_default() -> None:
    r = render_multilingual_letter(candidate_name="Alice", role="Stage", company="Acme", evidence=["Effectif: BBA"])
    assert r.language == "fr"
    assert "Madame, Monsieur" in r.body
    assert "- Effectif: BBA" in r.body
    assert "Alice" in r.body


def test_each_language() -> None:
    for lang in LETTER_LANGS:
        r = render_multilingual_letter(candidate_name="A", role="R", language=lang, evidence=["x"])
        assert r.language == lang
        assert r.body.splitlines()[0] and r.body.endswith("A")


def test_unknown_language_falls_back() -> None:
    r = render_multilingual_letter(language="jap")
    assert r.language == "fr"
    assert any("langue" in w for w in r.warnings)


def test_tone_dynamic_adds_availability() -> None:
    base = render_multilingual_letter(tone="formal")
    dyn = render_multilingual_letter(tone="dynamic")
    assert len(dyn.body) > len(base.body)
    assert dyn.tone == "dynamic"


def test_concise_removes_extra() -> None:
    r = render_multilingual_letter(tone="concise")
    assert "disponib" not in r.body.lower()


def test_unknown_tone_falls_back() -> None:
    r = render_multilingual_letter(tone="festif")
    assert r.tone == "formal"
    assert any("ton" in w for w in r.warnings)


def test_no_evidence_placeholder() -> None:
    r = render_multilingual_letter()
    assert "COMPLÉTER" in r.body or "COMPLETAR" in r.body or "AUSZUFÜLLEN" in r.body
    assert any("preuve" in w or "manquant" in w for w in r.warnings)


def test_to_dict() -> None:
    d = to_dict(render_multilingual_letter())
    assert d["language"] == "fr"
    assert isinstance(d, dict)


def test_constants() -> None:
    assert len(LETTER_LANGS) == 4
    assert "concise" in TONES
