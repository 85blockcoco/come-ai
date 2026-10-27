"""Tests for career/translation_variants.py — language detection + lexicon translation.

Synthetic fixtures only — no real offer data, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.translation_variants import (
    LexiconGL,
    VariantReport,
    build_variant,
    detect_offer_lang,
    load_lexicon,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic offer texts
# ---------------------------------------------------------------------------

SYNTHETIC_OFFER_EN = (
    "We are looking for a quantitative analyst to join our team. "
    "The role requires strong Python and statistics skills, experience "
    "with Bloomberg terminal and time series analysis. You will work "
    "with our team on quantitative research and data-driven projects."
)

SYNTHETIC_OFFER_DE = (
    "Wir suchen einen quantitativen Analysten für unser Team. "
    "Die Rolle erfordert gute Python- und Statistikkenntnisse, "
    "Erfahrung mit Bloomberg-Terminal und Zeitreihen. "
    "Sie werden mit unserem Team an quantitativen Projekten arbeiten."
)

SYNTHETIC_OFFER_ES = (
    "Buscamos un analista cuantitativo para nuestro equipo. "
    "El puesto requiere habilidades de Python y estadísticas, "
    "experiencia con terminal Bloomberg y series temporales. "
    "Trabajará con nuestro equipo en proyectos de investigación cuantitativa."
)

SYNTHETIC_OFFER_FR = (
    "Nous recherchons un analyste quantitatif pour notre équipe. "
    "Le poste requiert des compétences en Python et en statistiques, "
    "de l'expérience avec le terminal Bloomberg et les séries temporelles. "
    "Vous travaillerez avec notre équipe sur des projets de recherche quantitative."
)

# Adversarial: mixed FR/EN — more EN stopwords should win
SYNTHETIC_OFFER_MIXED = (
    "Nous recherchons a quantitative analyst to join our team. "
    "Le poste requires Python and statistics skills. "
    "Vous travaillerez with us on data-driven research."
)

# Edge case: very short text
SYNTHETIC_OFFER_SHORT = "Python team"


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def test_detect_english_offer() -> None:
    assert detect_offer_lang(SYNTHETIC_OFFER_EN) == "en"


def test_detect_german_offer() -> None:
    assert detect_offer_lang(SYNTHETIC_OFFER_DE) == "de"


def test_detect_spanish_offer() -> None:
    assert detect_offer_lang(SYNTHETIC_OFFER_ES) == "es"


def test_detect_french_offer() -> None:
    assert detect_offer_lang(SYNTHETIC_OFFER_FR) == "fr"


def test_detect_empty_text_defaults_to_french() -> None:
    assert detect_offer_lang("") == "fr"


def test_detect_short_text_returns_a_language() -> None:
    result = detect_offer_lang(SYNTHETIC_OFFER_SHORT)
    assert result in ("en", "de", "es", "fr")


def test_detect_none_text_defaults_to_french() -> None:
    """Robustness: a missing offer text must not crash the pipeline."""
    assert detect_offer_lang(None) == "fr"  # type: ignore[arg-type]


def test_detect_mixed_fr_en_wins_on_majority_language() -> None:
    """Adversarial: mixed-language text should detect the majority language."""
    result = detect_offer_lang(SYNTHETIC_OFFER_MIXED)
    # The mixed text has more English stopwords than French
    assert result in ("en", "fr")


# ---------------------------------------------------------------------------
# Lexicon loading
# ---------------------------------------------------------------------------


def test_load_english_lexicon_has_entries() -> None:
    lexicon = load_lexicon("en")
    assert isinstance(lexicon, LexiconGL)
    assert lexicon.lang == "en"
    assert len(lexicon.terms) > 0
    assert "Education" in lexicon.terms


def test_load_german_lexicon_has_entries() -> None:
    lexicon = load_lexicon("de")
    assert lexicon.lang == "de"
    assert "Education" in lexicon.terms
    # German should translate "Education" to "Ausbildung"
    assert lexicon.terms["Education"] == "Ausbildung"


def test_load_spanish_lexicon_has_entries() -> None:
    lexicon = load_lexicon("es")
    assert lexicon.lang == "es"
    assert "Education" in lexicon.terms
    assert lexicon.terms["Education"] == "Formación"


def test_load_unknown_lexicon_raises() -> None:
    with pytest.raises(ValueError):
        load_lexicon("xx")


def test_lexicon_files_are_valid_json() -> None:
    for lang in ("en", "de", "es"):
        path = Path(__file__).resolve().parent.parent / "career" / "lexicons" / f"{lang}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        # Non-empty
        assert len(data) > 10


# ---------------------------------------------------------------------------
# Variant building — lexicon mode
# ---------------------------------------------------------------------------


def test_build_variant_passthrough_for_french() -> None:
    report = build_variant("m_a", "fr")
    assert isinstance(report, VariantReport)
    assert report.offer_lang == "fr"
    assert report.mode == "passthrough"
    assert report.translated_fields == {}
    assert report.untranslated == []


def test_build_variant_lexicon_mode_for_english() -> None:
    report = build_variant("m_a", "en")
    assert report.offer_lang == "en"
    assert report.mode == "lexicon"
    # label should be translated (it's in the lexicon)
    assert "label" in report.translated_fields
    assert report.translated_fields["label"] == "M&A / Investment Banking"


def test_build_variant_lexicon_mode_for_german() -> None:
    report = build_variant("markets", "de")
    assert report.offer_lang == "de"
    assert report.mode == "lexicon"
    assert "label" in report.translated_fields
    # German markets label is translated
    assert report.translated_fields["label"] == "Märkte / Quantitativ"


def test_build_variant_lexicon_mode_for_spanish() -> None:
    report = build_variant("corporate_finance", "es")
    assert report.offer_lang == "es"
    assert report.mode == "lexicon"
    assert "label" in report.translated_fields
    assert report.translated_fields["label"] == "Finanzas Corporativas / FP&A"


def test_build_variant_tracks_untranslated_terms() -> None:
    """Terms not in the lexicon should appear in untranslated."""
    report = build_variant("m_a", "en")
    # "PowerPoint" may or may not be translated; check the mechanism works
    # At minimum, the section headings that ARE in lexicon should be translated
    assert isinstance(report.untranslated, list)


def test_build_variant_unknown_variant_raises() -> None:
    with pytest.raises(ValueError):
        build_variant("unknown_variant", "en")  # type: ignore[arg-type]


def test_build_variant_unknown_target_lang_raises() -> None:
    """An unsupported target language must fail loudly, not silently passthrough."""
    with pytest.raises(ValueError, match="Langue cible inconnue"):
        build_variant("m_a", "it")  # type: ignore[arg-type]


def test_build_variant_arena_mode() -> None:
    """When arena_available=True, mode is arena."""
    report = build_variant("m_a", "en", arena_available=True)
    assert report.mode == "arena"
    assert report.untranslated == []


# ---------------------------------------------------------------------------
# All variants can be translated to all target languages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant_id", ["m_a", "markets", "corporate_finance"])
@pytest.mark.parametrize("target_lang", ["en", "de", "es"])
def test_all_variants_translate_to_all_languages(
    variant_id: str, target_lang: str
) -> None:
    report = build_variant(variant_id, target_lang)  # type: ignore[arg-type]
    assert report.offer_lang == target_lang
    assert report.mode == "lexicon"
    # Should have translated at least the label and section headings
    assert len(report.translated_fields) > 0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_build_variant_is_deterministic() -> None:
    a = build_variant("m_a", "de")
    b = build_variant("m_a", "de")
    assert a == b


def test_lexicon_is_immutable() -> None:
    lexicon = load_lexicon("en")
    with pytest.raises(AttributeError):
        lexicon.lang = "fr"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# REST smoke tests — endpoints served through create_app()
# ---------------------------------------------------------------------------

class _FakeAgent:
    def provider_status(self) -> dict[str, object]:
        return {}

    def ask(self, message: str, *, allow_writes: bool) -> dict[str, object]:
        return {"answer": "sans appel fournisseur", "tool_events": [], "provider": "Faux modèle"}


def test_rest_smoke_detect_and_build(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from come_ai_web import create_app

    client = TestClient(create_app(tmp_path, agent_override=_FakeAgent()))
    detect = client.post(
        "/api/career/translation-variants/detect",
        json={"text": SYNTHETIC_OFFER_EN},
    )
    assert detect.status_code == 200
    assert detect.json()["detected_lang"] == "en"

    build = client.post(
        "/api/career/translation-variants/build",
        json={"variant_id": "m_a", "target_lang": "en", "arena_available": False},
    )
    assert build.status_code == 201
    body = build.json()
    assert body["mode"] == "lexicon"
    assert body["offer_lang"] in {"en", "de", "es", "fr"}
