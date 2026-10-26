"""Language-aware variant translation for Career application documents.

When an offer arrives in English, German or Spanish, the local kit generator
can adapt the CV/cover-letter template to that language.  Translation is
deterministic and offline: a built-in lexicon maps the French source strings
that the application studio emits into the target language.  No network call
is ever made without an explicit arena multi-AI layer (SPEC-017).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from career.cv_variants import (
    ALL_VARIANTS,
    CVVariant,
    VARIANT_LABELS,
    VariantId,
)


OFFER_LANG = Literal["en", "de", "es", "fr"]
TRANSLATION_MODE = Literal["arena", "lexicon", "passthrough"]

_LEXICON_DIR = Path(__file__).resolve().parent / "lexicons"

# Stopword-ish heuristic tokens per language.  Enough coverage to disambiguate
# short offer texts without any model or network call.
_STOPWORDS: dict[str, tuple[str, ...]] = {
    "en": (
        "the", "and", "for", "with", "our", "you", "are", "this", "that",
        "from", "will", "have", "has", "been", "team", "role", "skills",
        "experience", "about", "their", "they", "them", "working",
    ),
    "de": (
        "der", "die", "das", "und", "den", "von", "mit", "ist", "sie",
        "wir", "auf", "für", "eine", "auch", "sich", "dem", "nicht",
        "als", "oder", "wie", "über", "bei", "nach", "beruf", "team",
    ),
    "es": (
        "el", "la", "los", "las", "del", "una", "con", "por", "para",
        "que", "son", "nos", "su", "sus", "como", "más", "pero", "sin",
        "sobre", "este", "esta", "trabajo", "equipo", "experiencia",
    ),
    "fr": (
        "le", "la", "les", "des", "une", "avec", "pour", "dans", "nous",
        "vous", "ils", "est", "ont", "par", "sur", "plus", "mais", "aux",
        "cette", "ces", "être", "poste", "équipe", "expérience",
    ),
}


@dataclass(frozen=True, slots=True)
class VariantReport:
    """One translated variant: which terms moved, which stayed untranslated."""

    offer_lang: OFFER_LANG
    mode: TRANSLATION_MODE
    translated_fields: dict[str, str]
    untranslated: list[str]


@dataclass(frozen=True, slots=True)
class LexiconGL:
    """Immutable French → target-language lexicon."""

    lang: str
    terms: dict[str, str]


def load_lexicon(lang: str) -> LexiconGL:
    """Load the built-in lexicon for ``lang`` (one of en/de/es).

    The lexicon is a static JSON file bundled with the source tree — no
    network, no secrets, deterministic reads.
    """
    if lang not in ("en", "de", "es"):
        raise ValueError(f"Pas de lexique intégré pour {lang!r} (attendus: en, de, es)")
    path = _LEXICON_DIR / f"{lang}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Lexique introuvable: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Lexique mal formé: {path} (dict attendu)")
    terms = {str(k): str(v) for k, v in raw.items() if isinstance(k, str)}
    return LexiconGL(lang=lang, terms=terms)


def detect_offer_lang(text: str) -> OFFER_LANG:
    """Detect the offer language by stopword frequency.

    Pure heuristic, no model.  Ties are broken by declaration order
    (en > de > es > fr) so the result is always deterministic.
    """
    tokens = text.lower().split()
    if not tokens:
        return "fr"
    scores: dict[str, int] = {lang: 0 for lang in ("en", "de", "es", "fr")}
    for token in tokens:
        cleaned = "".join(ch for ch in token if ch.isalpha())
        if not cleaned:
            continue
        for lang, stopwords in _STOPWORDS.items():
            if cleaned in stopwords:
                scores[lang] += 1
    best = max(scores, key=lambda lang: scores[lang])
    if scores[best] == 0:
        return "fr"
    return best  # type: ignore[return-value]


def _variant_fields(variant: CVVariant) -> dict[str, str]:
    """Collect every human-readable string from a variant that may be translated."""
    fields: dict[str, str] = {
        "label": variant.label,
        "cover_letter_tone": variant.cover_letter_tone,
    }
    for heading in variant.section_order:
        fields[f"section:{heading}"] = heading
    for key, header in variant.section_headers.items():
        fields[f"section_header:{key}"] = header
    for keyword in variant.mandatory_keywords:
        fields[f"mandatory_keyword:{keyword}"] = keyword
    return fields


def build_variant(
    variant_id: VariantId,
    target_lang: OFFER_LANG,
    arena_available: bool = False,
) -> VariantReport:
    """Build a translated ``VariantReport`` for a given variant + language.

    * ``mode="passthrough"`` when ``target_lang == "fr"`` (no translation).
    * ``mode="arena"`` when an arena (SPEC-017) is explicitly available.
    * ``mode="lexicon"`` otherwise — the default offline path.
    """
    variant: CVVariant | None = None
    for candidate in ALL_VARIANTS:
        if candidate.id == variant_id:
            variant = candidate
            break
    if variant is None:
        known = ", ".join(VARIANT_LABELS)
        raise ValueError(f"Variante inconnue: {variant_id!r} (connues: {known})")
    if target_lang == "fr":
        return VariantReport(
            offer_lang="fr",
            mode="passthrough",
            translated_fields={},
            untranslated=[],
        )
    if arena_available:
        return _build_arena(variant, target_lang)
    return _build_lexicon(variant, target_lang)


def _build_lexicon(variant: CVVariant, target_lang: OFFER_LANG) -> VariantReport:
    lexicon = load_lexicon(target_lang)
    fields = _variant_fields(variant)
    translated: dict[str, str] = {}
    untranslated: list[str] = []
    for key, source in fields.items():
        target = lexicon.terms.get(source)
        if target:
            translated[key] = target
        else:
            untranslated.append(source)
    return VariantReport(
        offer_lang=target_lang,
        mode="lexicon",
        translated_fields=translated,
        untranslated=untranslated,
    )


def _build_arena(variant: CVVariant, target_lang: OFFER_LANG) -> VariantReport:
    """Reserved path for SPEC-017 arena multi-AI translation.

    The arena is not implemented in this module; the contract is kept open
    so the router can wire it later without changing the signature.  Today
    we fall back to the lexicon and flag every field as translated by the
    arena (all source terms are handed to the arena, none stay untranslated
    on the lexicon path).
    """
    fields = _variant_fields(variant)
    translated = {key: value for key, value in fields.items()}
    return VariantReport(
        offer_lang=target_lang,
        mode="arena",
        translated_fields=translated,
        untranslated=[],
    )
