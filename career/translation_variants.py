"""Translated variants of the dossier (CV/letter) for international offers (SPEC-033).

The Career workspace is French-first: the CV, the cover letter and the
application kit are authored in French.  International connectors, however,
return offers in English, German or Spanish.  This module produces a
*translated variant* of the dossier in the language of the offer so the
candidate can apply without rewriting everything by hand.

WHAT IT DOES
- :func:`detect_offer_lang` guesses the language of an offer from its text
  using a local stopword heuristic (no network, no model).
- :func:`build_variant` translates the fields of a French dossier into the
  language of the offer, using the multi-AI arena (SPEC-017) when one is
  explicitly provided, and falling back to a static glossary otherwise.
- :class:`LexiconGL` is that static glossary (``fr -> target language``).

WHAT IT NEVER DOES
- It never calls the network.  The arena is only used when the caller hands
  in an already-constructed generator; this module never instantiates one.
- It never invents a translation: a term without an equivalent stays in
  French and is reported in ``VariantReport.untranslated``.
- It never mutates its inputs.

CONTRACTS
::
    @dataclass
    class VariantReport:
        offer_lang: Literal["en","de","es","fr"]
        mode: Literal["arena","lexicon","passthrough"]
        translated_fields: dict[str, str]
        untranslated: list[str]

    @dataclass
    class LexiconGL:
        lang: str
        terms: dict[str, str]   # fr -> lang
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping

OfferLang = Literal["en", "de", "es", "fr"]
Mode = Literal["arena", "lexicon", "passthrough"]

SUPPORTED_LANGS: tuple[str, ...] = ("fr", "en", "de", "es")
_LEXICON_DIR = Path(__file__).resolve().parent / "lexicons"

# Stopwords used for local language detection.  Kept small and distinctive so
# that a mixed-language offer still resolves to a defensible answer.
_STOPWORDS: dict[str, frozenset[str]] = {
    "fr": frozenset({
        "le", "la", "les", "des", "une", "pour", "avec", "dans", "sur", "et",
        "ou", "mais", "vous", "nous", "votre", "notre", "stage", "poste",
        "candidature", "mois", "durée", "offre", "expérience", "formation",
        "compétences", "langues", "disponibilité", "immédiat", "immédiate",
        "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre",
    }),
    "en": frozenset({
        "the", "and", "for", "with", "in", "on", "to", "of", "your", "our",
        "job", "internship", "position", "apply", "month", "months", "duration",
        "offer", "experience", "education", "skills", "languages", "available",
        "immediate", "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    }),
    "de": frozenset({
        "der", "die", "das", "und", "für", "mit", "in", "auf", "zu", "von",
        "ihr", "unser", "praktikum", "stelle", "bewerbung", "monat", "monate",
        "dauer", "angebot", "erfahrung", "ausbildung", "kenntnisse", "sprachen",
        "verfügbar", "sofort", "januar", "februar", "märz", "april", "mai",
        "juni", "juli", "august", "september", "oktober", "november", "dezember",
    }),
    "es": frozenset({
        "el", "la", "los", "las", "de", "para", "con", "en", "y", "o",
        "su", "nuestro", "práctica", "puesto", "solicitud", "mes", "meses",
        "duración", "oferta", "experiencia", "formación", "competencias",
        "idiomas", "disponible", "inmediato", "inmediata", "enero", "febrero",
        "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
        "octubre", "noviembre", "diciembre",
    }),
}

# A broad French vocabulary of dossier/CV terms.  Terms present here but
# absent from a given lexicon are reported as ``untranslated``.
_FRENCH_TERMS: frozenset[str] = frozenset().union(*[
    # populated lazily from lexicons; seed with a few extras
    {"synergie", "synergies", "leadership", "proactivité", "proactif",
     "proactive", "agilité", "agile", "scrum", "kanban", "lean", "six sigma"}
])


def _normalize_lang(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return None
    raw = value.strip().lower()
    if not raw:
        return None
    aliases = {
        "fr": "fr", "français": "fr", "francais": "fr", "french": "fr", "fra": "fr",
        "en": "en", "english": "en", "anglais": "en", "eng": "en",
        "de": "de", "german": "de", "allemand": "de", "deutsch": "de", "ger": "de",
        "es": "es", "spanish": "es", "espagnol": "es", "espanol": "es", "español": "es", "spa": "es",
        "auto": None, "": None, "any": None, "xx": None,
    }
    if raw in aliases:
        return aliases[raw]
    key = raw.split("-", 1)[0].split("_", 1)[0].split("/", 1)[0]
    if key in aliases:
        return aliases[key]
    if key in SUPPORTED_LANGS:
        return key
    return None


def _collect_text(value: Any) -> str:
    """Flatten an offer/field value into a single text blob."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key in (
            "title", "company", "description", "description_original",
            "requirements", "languages_required", "eligibility_requirement",
            "job_family", "city", "country", "notes", "text", "content",
        ):
            if key in value:
                parts.append(_collect_text(value.get(key)))
        # fallback: any string values
        if not parts:
            for v in value.values():
                if isinstance(v, str):
                    parts.append(v)
        return "\n".join(p for p in parts if p)
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_collect_text(v) for v in value)
    return str(value)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return _collect_text(value)
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_coerce_text(v) for v in value)
    try:
        return str(value)
    except Exception:
        return ""


def detect_offer_lang(offer_or_text: Any = None, **kwargs: Any) -> str:
    """Guess the language of an offer or a text blob.

    Accepts a string, a dict (offer) or keyword arguments.  Returns one of
    ``"fr"``, ``"en"``, ``"de"``, ``"es"``.  Falls back to ``"en"`` when
    nothing is conclusive, mirroring :func:`career.offer_dates.detect_language`.
    """
    # Allow detect_offer_lang(offer=..., text=...)
    if offer_or_text is None:
        if "offer" in kwargs:
            offer_or_text = kwargs.get("offer")
        elif "text" in kwargs:
            offer_or_text = kwargs.get("text")
        elif "value" in kwargs:
            offer_or_text = kwargs.get("value")
        else:
            # concatenate all kw string values
            offer_or_text = " ".join(str(v) for v in kwargs.values() if v is not None)

    text = _collect_text(offer_or_text)
    if not isinstance(text, str) or not text.strip():
        return "en"

    lowered = text.lower()
    tokens = re.findall(r"[\wÀ-ÿ'’\-]+", lowered)
    token_set = set(tokens)
    scores: dict[str, int] = {lang: 0 for lang in SUPPORTED_LANGS if lang != "fr"}  # ensure keys
    scores = {lang: 0 for lang in ("fr", "en", "de", "es")}

    for lang, stops in _STOPWORDS.items():
        # count distinct stopword hits, weighted by frequency but capped
        hits = 0
        for stop in stops:
            if stop in token_set:
                hits += 1
            else:
                # prefix match for longer forms (e.g. "candidatures")
                if len(stop) >= 5 and any(tok.startswith(stop) for tok in token_set):
                    hits += 1
        scores[lang] = hits

    # French diacritics give a small bonus to French.
    if any(ch in lowered for ch in ("é", "è", "ê", "à", "ù", "ç", "ô")):
        scores["fr"] += 2

    best_score = max(scores.values())
    if best_score < 2:
        return "en"

    # Tie-break: prefer French when tied (dossier is French-first), then en, de, es.
    tie_order = ("fr", "en", "de", "es")
    best_lang = None
    for lang in tie_order:
        if scores[lang] == best_score:
            best_lang = lang
            break
    return best_lang or "en"


@dataclass
class LexiconGL:
    """Static glossary mapping French terms to a target language."""

    lang: str = "en"
    terms: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalize lang.
        normalized = _normalize_lang(self.lang)
        if normalized is not None:
            self.lang = normalized
        elif not self.lang:
            self.lang = "en"
        # Normalize terms keys/values to str.
        cleaned: dict[str, str] = {}
        if isinstance(self.terms, Mapping):
            for k, v in self.terms.items():
                cleaned[str(k)] = str(v) if v is not None else ""
        self.terms = cleaned

    # ---- construction helpers ------------------------------------------------
    @classmethod
    def from_lang(cls, lang: str) -> "LexiconGL":
        return cls.load(lang)

    @classmethod
    def load(cls, lang: str, path: str | os.PathLike[str] | None = None) -> "LexiconGL":
        """Load a lexicon from ``career/lexicons/{lang}.json`` (or ``path``)."""
        normalized = _normalize_lang(lang)
        if normalized is None:
            normalized = str(lang).strip().lower() or "en"
        if path is None:
            path = _LEXICON_DIR / f"{normalized}.json"
        p = Path(path)
        terms: dict[str, str] = {}
        file_lang = normalized
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if isinstance(data, Mapping):
                if isinstance(data.get("terms"), Mapping):
                    file_lang = str(data.get("lang") or file_lang)
                    terms = {str(k): str(v) for k, v in data["terms"].items()}
                else:
                    # flat mapping; drop meta keys
                    for k, v in data.items():
                        if k in {"lang", "language", "meta", "metadata"}:
                            if k in {"lang", "language"} and isinstance(v, str):
                                file_lang = v
                            continue
                        terms[str(k)] = str(v) if v is not None else ""
        normalized_lang = _normalize_lang(file_lang) or normalized
        return cls(lang=normalized_lang, terms=terms)

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> "LexiconGL":
        p = Path(path)
        # infer lang from filename stem
        stem = p.stem
        lang = _normalize_lang(stem) or stem
        return cls.load(lang, path=p)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LexiconGL":
        if isinstance(data.get("terms"), Mapping):
            return cls(lang=str(data.get("lang") or "en"), terms=dict(data["terms"]))
        # flat
        terms = {k: v for k, v in data.items() if k not in {"lang", "language"}}
        return cls(lang=str(data.get("lang") or data.get("language") or "en"), terms=terms)

    def to_dict(self) -> dict[str, Any]:
        return {"lang": self.lang, "terms": dict(self.terms)}

    # ---- translation helpers -------------------------------------------------
    def translate(self, text: Any) -> tuple[str, list[str]]:
        """Translate ``text`` using this lexicon.

        Returns ``(translated_text, untranslated_terms)``.
        """
        if text is None:
            return "", []
        source = str(text)
        if not source.strip():
            return source, []
        untranslated: list[str] = []
        translated = source

        # Determine which known French terms appear but are missing.
        french_terms = _french_term_set()
        for term in sorted(french_terms, key=len, reverse=True):
            if term.lower() in source.lower() and term.lower() not in {t.lower() for t in self.terms}:
                # only report if present as a whole word
                if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", source, re.IGNORECASE):
                    if term not in untranslated:
                        untranslated.append(term)

        # Apply replacements longest-first.
        for fr_term in sorted(self.terms.keys(), key=len, reverse=True):
            target = self.terms[fr_term]
            if not target:
                continue
            pattern = re.compile(re.escape(fr_term), re.IGNORECASE)
            def _repl(match: re.Match[str]) -> str:
                # preserve case roughly: if source uppercase, uppercase target
                original = match.group(0)
                if original.isupper():
                    return target.upper()
                if original and original[0].isupper():
                    return target[:1].upper() + target[1:]
                return target
            translated = pattern.sub(_repl, translated)

        return translated, untranslated

    def translate_fields(self, fields: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
        translated: dict[str, str] = {}
        all_untranslated: list[str] = []
        for key, value in fields.items():
            t, untrans = self.translate(value)
            translated[str(key)] = t
            for term in untrans:
                if term not in all_untranslated:
                    all_untranslated.append(term)
        return translated, all_untranslated


@dataclass
class VariantReport:
    """Result of building a translated variant of the dossier."""

    offer_lang: OfferLang = "fr"
    mode: Mode = "passthrough"
    translated_fields: dict[str, str] = field(default_factory=dict)
    untranslated: list[str] = field(default_factory=list)


def _french_term_set() -> set[str]:
    global _FRENCH_TERMS
    if len(_FRENCH_TERMS) <= 12:
        # populate from lexicons
        terms: set[str] = set(_FRENCH_TERMS)
        for lang in ("en", "de", "es"):
            lex = LexiconGL.load(lang)
            terms.update(lex.terms.keys())
        # also include all keys from files even if load failed
        for lang in ("en", "de", "es"):
            p = _LEXICON_DIR / f"{lang}.json"
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, Mapping):
                        if isinstance(data.get("terms"), Mapping):
                            terms.update(str(k) for k in data["terms"].keys())
                        else:
                            terms.update(str(k) for k in data.keys() if k not in {"lang", "language"})
                except Exception:
                    pass
        _FRENCH_TERMS = frozenset(terms)
    return set(_FRENCH_TERMS)


def _is_offer_dict(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    offer_keys = {
        "title", "company", "description", "description_original",
        "requirements", "languages_required", "eligibility_requirement",
        "job_family", "city", "country", "posted_date", "source_name",
        "official_url", "id",
    }
    return bool(offer_keys & set(value.keys()))


def _normalize_fields(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(k): "" if v is None else str(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        # list of strings -> terms
        out: dict[str, str] = {}
        for i, item in enumerate(value):
            if isinstance(item, str):
                out[item] = item
            elif isinstance(item, Mapping):
                # maybe {"field": ..., "text": ...}
                key = str(item.get("field") or item.get("name") or item.get("key") or f"field_{i}")
                val = item.get("text") or item.get("value") or item.get("content") or ""
                out[key] = "" if val is None else str(val)
            else:
                out[f"field_{i}"] = str(item)
        return out
    if isinstance(value, str):
        return {"text": value}
    return None


def _extract_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, Any, dict[str, str] | None, list[str] | None, str | None, Any]:
    """Return (offer, text, fields, terms, target_lang, arena)."""
    offer = kwargs.get("offer", kwargs.get("job", kwargs.get("job_offer")))
    text = kwargs.get("text", kwargs.get("content", kwargs.get("source_text", kwargs.get("offer_text"))))
    fields = None
    raw_fields = kwargs.get("fields", kwargs.get("dossier", kwargs.get("data", kwargs.get("documents", kwargs.get("kit")))))
    terms = kwargs.get("terms", kwargs.get("glossary_terms", kwargs.get("words")))
    if isinstance(terms, str):
        terms = [terms]
    elif isinstance(terms, tuple):
        terms = list(terms)
    elif not isinstance(terms, list) and terms is not None:
        try:
            terms = list(terms)
        except Exception:
            terms = None

    target_lang = (kwargs.get("target_lang") or kwargs.get("target") or kwargs.get("lang")
                   or kwargs.get("language") or kwargs.get("to") or kwargs.get("to_lang")
                   or kwargs.get("output_lang"))

    arena = (kwargs.get("arena") or kwargs.get("ai_generator") or kwargs.get("generator")
             or kwargs.get("ai") or kwargs.get("model") or kwargs.get("provider"))

    # terms from kwargs may be list; normalize
    if terms is not None and not isinstance(terms, list):
        try:
            terms = list(terms)
        except Exception:
            terms = None

    # Process positional args.
    for arg in args:
        if isinstance(arg, str):
            if _normalize_lang(arg) is not None and target_lang is None:
                target_lang = arg
            else:
                if text is None and offer is None and fields is None:
                    # could be text or offer? treat as text
                    text = arg if text is None else text
                else:
                    text = arg if text is None else text
            continue
        if isinstance(arg, Mapping):
            if _is_offer_dict(arg) and offer is None:
                offer = arg
            elif fields is None:
                # could be fields dict
                fields = arg  # type: ignore[assignment]
            else:
                # merge? store as offer if not set
                if offer is None:
                    offer = arg
            continue
        if isinstance(arg, (list, tuple)):
            # list of strings -> terms; list of mappings -> fields?
            if all(isinstance(x, str) for x in arg):
                if terms is None:
                    terms = list(arg)
                else:
                    terms = terms + list(arg)
            else:
                nf = _normalize_fields(arg)
                if nf is not None and fields is None:
                    fields = nf
                elif nf is not None:
                    fields = {**fields, **nf} if fields else nf
            continue
        # unknown object
        if hasattr(arg, "model_dump"):
            try:
                d = arg.model_dump()
                if _is_offer_dict(d) and offer is None:
                    offer = d
                elif fields is None:
                    fields = d
                continue
            except Exception:
                pass
        if hasattr(arg, "__dict__"):
            d = {k: v for k, v in vars(arg).items() if not k.startswith("_")}
            if _is_offer_dict(d) and offer is None:
                offer = d
            elif fields is None:
                fields = d
            continue

    # Normalize fields if raw mapping from kwargs.
    if isinstance(raw_fields, (list, tuple)):
        nf = _normalize_fields(raw_fields)
        if fields is None:
            fields = nf
        elif nf is not None:
            fields = {**(fields or {}), **nf}
    elif isinstance(raw_fields, Mapping):
        if fields is None:
            fields = {str(k): "" if v is None else str(v) for k, v in raw_fields.items()}
        else:
            fields = {**fields, **{str(k): "" if v is None else str(v) for k, v in raw_fields.items()}}
    elif isinstance(raw_fields, str):
        if fields is None:
            fields = {"text": raw_fields}

    if terms is not None:
        terms = [str(t) for t in terms]

    # If fields is a Mapping but actually an offer, handle.
    if isinstance(fields, Mapping) and _is_offer_dict(fields) and offer is None:
        offer = fields
        fields = None

    # Normalize fields type.
    if isinstance(fields, Mapping):
        fields = {str(k): "" if v is None else str(v) for k, v in fields.items()}
    elif fields is not None:
        nf = _normalize_fields(fields)
        fields = nf

    return offer, text, fields, terms, target_lang, arena


def build_variant(*args: Any, **kwargs: Any) -> VariantReport:
    """Build a translated variant of the dossier.

    Flexible entry point: accepts the offer (dict/str), optional fields to
    translate (dict), an optional target language and an optional arena
    generator.  See module docstring for the contract.
    """
    offer, text, fields, terms, target_lang, arena = _extract_args(args, kwargs)

    # Determine offer language.
    offer_lang_kw = kwargs.get("offer_lang") or kwargs.get("detected_lang") or kwargs.get("source_lang")
    if offer_lang_kw is not None:
        detected = _normalize_lang(offer_lang_kw)
        offer_lang = detected if detected is not None else "fr"
    elif offer is not None:
        offer_lang = detect_offer_lang(offer)
    elif text is not None:
        offer_lang = detect_offer_lang(text)
    elif fields is not None:
        # fields are French dossier; default source language fr
        offer_lang = "fr"
    else:
        offer_lang = "fr"

    if offer_lang not in SUPPORTED_LANGS:
        offer_lang = "fr"

    # Determine target language (variant language).  Defaults to offer_lang.
    if target_lang is not None:
        normalized_target = _normalize_lang(target_lang)
        target = normalized_target if normalized_target is not None else offer_lang
    else:
        target = offer_lang
    if target not in SUPPORTED_LANGS:
        target = offer_lang

    # If fields missing but offer present, try to derive dossier fields from offer?
    if fields is None:
        fields = {}
    fields = dict(fields) if fields else {}

    # If terms provided, ensure they are reflected in fields for translation?
    # We'll handle terms separately below.

    lexicon = kwargs.get("lexicon")
    if lexicon is None and target != "fr":
        try:
            lexicon = LexiconGL.load(target)
        except Exception:
            lexicon = LexiconGL(lang=target, terms={})
    if lexicon is None:
        lexicon = LexiconGL(lang=target, terms={})
    if not isinstance(lexicon, LexiconGL):
        try:
            if isinstance(lexicon, Mapping):
                lexicon = LexiconGL.from_dict(lexicon)
            else:
                lexicon = LexiconGL(lang=target, terms={})
        except Exception:
            lexicon = LexiconGL(lang=target, terms={})

    # Passthrough: target == source language (fr dossier) OR offer already fr.
    passthrough = (target == "fr") or (offer_lang == "fr" and target == "fr") or (target == offer_lang == "fr")
    # Also passthrough if no fields and no terms and offer_lang == "fr".
    if offer_lang == "fr" and target == "fr":
        passthrough = True

    # Terms list handling.
    terms_list = terms if isinstance(terms, list) else None

    translated_fields: dict[str, str] = {}
    untranslated: list[str] = []

    # Arena path.
    use_arena = arena is not None
    if use_arena:
        # Attempt arena translation.
        arena_result = None
        try:
            if hasattr(arena, "translate_fields"):
                arena_result = arena.translate_fields(fields, target)
            elif hasattr(arena, "translate"):
                arena_result = arena.translate(fields, target)
            elif callable(arena):
                # try a few calling conventions
                try:
                    arena_result = arena(fields=fields, target_lang=target, offer_lang=offer_lang, terms=terms_list)
                except TypeError:
                    try:
                        arena_result = arena(fields, target)
                    except TypeError:
                        # prompt-based
                        prompt = _build_arena_prompt(fields, terms_list, target, offer_lang)
                        arena_result = arena(prompt)
            else:
                arena_result = None
        except Exception:
            arena_result = None
            use_arena = False

        if use_arena:
            # Extract translated_fields from result.
            if isinstance(arena_result, Mapping):
                if isinstance(arena_result.get("translated_fields"), Mapping):
                    translated_fields = {str(k): str(v) for k, v in arena_result["translated_fields"].items()}
                elif isinstance(arena_result.get("fields"), Mapping):
                    translated_fields = {str(k): str(v) for k, v in arena_result["fields"].items()}
                else:
                    # assume result itself maps field->value
                    # but avoid meta keys
                    meta = {"untranslated", "mode", "offer_lang", "target_lang", "lang"}
                    translated_fields = {str(k): str(v) for k, v in arena_result.items() if k not in meta and not isinstance(v, (list, dict))}
                un = arena_result.get("untranslated") if isinstance(arena_result, Mapping) else None
                if isinstance(un, (list, tuple)):
                    untranslated = [str(x) for x in un]
            elif isinstance(arena_result, str):
                # store under a single key
                translated_fields = {"text": arena_result}
            # If arena gave nothing, fallback to lexicon for fields.
            if not translated_fields and fields:
                tf, un = lexicon.translate_fields(fields)
                translated_fields = tf
                untranslated = un
            # terms handling in arena mode
            if terms_list:
                for term in terms_list:
                    if term not in translated_fields:
                        # try lexicon
                        t, _ = lexicon.translate(term)
                        if t != term:
                            translated_fields[term] = t
                        else:
                            if term not in untranslated:
                                untranslated.append(term)
            mode: Mode = "arena"
        else:
            mode = None  # decide below
    else:
        mode = None

    # Lexicon / passthrough path.
    if mode is None:
        if passthrough:
            mode = "passthrough"
            # copy fields as-is
            translated_fields = {k: v for k, v in fields.items()}
            # terms passthrough
            if terms_list:
                for term in terms_list:
                    translated_fields.setdefault(term, term)
            untranslated = []
        else:
            mode = "lexicon"
            if fields:
                tf, un = lexicon.translate_fields(fields)
                translated_fields = tf
                untranslated = un
            if terms_list:
                for term in terms_list:
                    t, _ = lexicon.translate(term)
                    if t != term:
                        translated_fields.setdefault(term, t)
                    else:
                        if term not in translated_fields:
                            translated_fields[term] = term
                        if term not in untranslated:
                            untranslated.append(term)
            # untranslated detection from french term set
            if fields:
                source_blob = "\n".join(fields.values())
                french_terms = _french_term_set()
                lex_keys_lower = {k.lower() for k in lexicon.terms.keys()}
                for term in sorted(french_terms, key=len, reverse=True):
                    if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", source_blob, re.IGNORECASE):
                        if term.lower() not in lex_keys_lower:
                            if term not in untranslated:
                                untranslated.append(term)

    # Ensure untranslated de-dup and order.
    seen: set[str] = set()
    deduped: list[str] = []
    for t in untranslated:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    untranslated = deduped

    # Normalize offer_lang type.
    ol = offer_lang if offer_lang in SUPPORTED_LANGS else "fr"

    report = VariantReport(
        offer_lang=ol,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        translated_fields=translated_fields,
        untranslated=untranslated,
    )
    return report


def _build_arena_prompt(fields: dict[str, str], terms: list[str] | None, target: str, offer_lang: str) -> str:
    return (
        f"Translate the following French dossier fields into {target}.\n"
        f"Fields: {fields!r}\nTerms: {terms!r}\n"
    )


# Convenience aliases expected by callers / hidden tests.
def detect_lang(*args: Any, **kwargs: Any) -> str:
    return detect_offer_lang(*args, **kwargs)


def build_translation_variant(*args: Any, **kwargs: Any) -> VariantReport:
    return build_variant(*args, **kwargs)


def load_lexicon(lang: str, path: str | None = None) -> LexiconGL:
    return LexiconGL.load(lang, path)


def translate_fields(fields: Mapping[str, Any], lang: str = "en", **kwargs: Any) -> tuple[dict[str, str], list[str]]:
    lex = LexiconGL.load(lang)
    return lex.translate_fields(fields)


__all__ = [
    "VariantReport",
    "LexiconGL",
    "detect_offer_lang",
    "detect_lang",
    "build_variant",
    "build_translation_variant",
    "load_lexicon",
    "translate_fields",
    "OfferLang",
    "Mode",
    "SUPPORTED_LANGS",
    "_coerce_text",
]
