"""Tests for translated dossier variants (SPEC-033)."""

from __future__ import annotations

from pathlib import Path

from career.translation_variants import (
    LexiconGL,
    VariantReport,
    build_variant,
    detect_offer_lang,
)


def test_detect_offer_lang_basic():
    assert detect_offer_lang("Apply by 15 November for your internship position") == "en"
    assert detect_offer_lang("Candidature pour un stage de six mois") == "fr"
    assert detect_offer_lang("Bewerbungsfrist für das Praktikum") == "de"
    assert detect_offer_lang("Fecha límite para la práctica") == "es"
    assert detect_offer_lang("") == "en"


def test_detect_offer_lang_dict():
    offer = {"title": "Data Analyst Intern", "description_original": "Apply by 15 November"}
    assert detect_offer_lang(offer) == "en"


def test_detect_offer_lang_adversarial_mixed():
    mixed = (
        "Stage M&A Analyst - We are looking for a motivated intern. "
        "Durée 6 mois. Apply by 15 November. Candidature en ligne."
    )
    assert detect_offer_lang(mixed) in {"fr", "en"}


def test_lexicon_load():
    lex = LexiconGL.load("en")
    assert lex.lang == "en"
    assert isinstance(lex.terms, dict)
    assert len(lex.terms) > 0
    # fr -> en
    assert "expérience" in lex.terms or "experience" in lex.terms.values()


def test_lexicon_from_flat_file():
    path = Path("career/lexicons/de.json")
    lex = LexiconGL.from_file(path)
    assert lex.lang == "de"
    assert len(lex.terms) > 0


def test_build_variant_passthrough_fr():
    report = build_variant("Candidature", fields={"cv": "expérience"}, target_lang="fr")
    assert report.offer_lang in {"fr", "en"}
    assert report.mode == "passthrough"
    assert report.translated_fields["cv"] == "expérience"


def test_build_variant_lexicon_en():
    report = build_variant(
        {"title": "Intern", "description_original": "Apply by November"},
        fields={"cv": "expérience en finance", "letter": "Madame, Monsieur"},
        target_lang="en",
    )
    assert report.offer_lang == "en"
    assert report.mode == "lexicon"
    assert report.translated_fields["cv"] == "experience en finance"
    assert isinstance(report.untranslated, list)


def test_build_variant_terms():
    report = build_variant(terms=["expérience", "synergie"], target_lang="de")
    assert isinstance(report.translated_fields, dict)
    assert "expérience" in report.translated_fields
    # synergie exists in de lexicon
    assert isinstance(report.untranslated, list)


def test_build_variant_arena_mode():
    def arena(fields=None, target_lang=None, **kw):
        return {"translated_fields": {"cv": "EXPERIENCE"}, "untranslated": ["x"]}

    report = build_variant(fields={"cv": "expérience"}, target_lang="en", arena=arena)
    assert report.mode == "arena"
    assert report.translated_fields["cv"] == "EXPERIENCE"
    assert report.untranslated == ["x"]


def test_variant_report_dataclass_fields():
    r = VariantReport(offer_lang="fr", mode="passthrough", translated_fields={}, untranslated=[])
    assert r.offer_lang == "fr"
    assert r.mode == "passthrough"
    d = r.__dict__ if hasattr(r, "__dict__") else None
    assert d is not None


def test_lexicon_translate():
    lex = LexiconGL.load("es")
    text, untrans = lex.translate("expérience et gestion")
    assert "experiencia" in text
    assert isinstance(untrans, list)


def test_endpoint_smoke():
    import tempfile
    from pathlib import Path

    from fastapi.testclient import TestClient

    from come_ai_web import create_app

    d = Path(tempfile.mkdtemp())
    app = create_app(base_dir=d)
    with TestClient(app) as client:
        r = client.post(
            "/api/career/translation/variants",
            json={"text": "Apply by November", "fields": {"cv": "expérience"}, "target_lang": "en"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "lexicon"
        assert data["translated_fields"]["cv"] == "experience"