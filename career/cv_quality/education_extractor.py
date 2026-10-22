"""Deterministic extraction of advertised education requirements.

The extractor reads an offer text (typically the description, the requirements
field or ``role_level``) and returns canonical, source-attributed education
facts. It never guesses a diploma that is not written in the text, never pads a
level with an assumed field, and keeps contradictions visible.

Design constraints:

* pure, local and offline — no network, no LLM, no clock;
* every ``quote`` is an exact substring of the supplied text and
  ``text[start_offset:end_offset] == quote`` always holds;
* accent folding is length-preserving, so offsets stay valid on the original
  text;
* required and preferred statements are both reported, with mutual
  ``contradictions`` tokens instead of silently picking one.

Canonical ranks follow the mission contract: 3 = Bac+3, 4 = Bac+4,
5 = Bac+5/M1, 6 = Bac+6/M2 and 8 = PhD/doctorate.

Contradiction tokens are stable and documented in
``docs/agent-reports/SPEC-SK19-EDUCATION_EXTRACTOR.md``:

* ``preferred_only`` — the level is explicitly appreciated/desired, not required;
* ``accepted_alternative`` — the level is explicitly accepted as an alternative;
* ``experience_equivalent`` — the level is waived by equivalent experience;
* ``conflict_with_rank_N`` — another fact states a different canonical rank.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field as dataclass_field
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES = ("fr", "en", "de", "it", "es", "nl")
CONFIDENCE_LEVELS = ("explicit", "inferred", "ambiguous")


@dataclass(slots=True)
class EducationFact:
    """One canonical education requirement found in a text.

    ``level_rank`` is 3, 4, 5, 6 or 8. It is ``0`` only for a
    ``education_field_required`` fact, which names a field without asserting any
    level (the text must not be padded with an invented diploma).

    ``contradictions`` carries stable tokens (see module docstring) rather than
    free text, so callers can decide which branch to trust.
    """

    fact_type: Literal["education_level_required", "education_field_required"]
    level_rank: int
    level_label: str
    field: Optional[str]
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str] = dataclass_field(default_factory=list)

    @property
    def is_preferred(self) -> bool:
        """True when the level is stated as appreciated/desired, not required."""
        return "preferred_only" in self.contradictions

    @property
    def is_experience_equivalent(self) -> bool:
        """True when equivalent experience may waive the stated level."""
        return "experience_equivalent" in self.contradictions

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Text folding and language detection
# ---------------------------------------------------------------------------


def _fold_char(char: str) -> str:
    """Fold one character to one lowercase ASCII-ish character.

    The result always has length 1 so ``_fold(text)`` and ``text`` share their
    indices; this is what keeps offsets exact.
    """
    if char in "’‘`´":
        return "'"
    if char in "–—−":
        return "-"
    if char == "\u00a0":
        return " "
    decomposed = unicodedata.normalize("NFKD", char)
    base = "".join(part for part in decomposed if not unicodedata.combining(part))
    lowered = base.lower()
    return lowered[0] if lowered else char.lower()


def _fold(text: str) -> str:
    """Accent- and quote-insensitive, length-preserving lowercase text."""
    return "".join(_fold_char(char) for char in text)


_LANGUAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "fr": (
        "le", "les", "des", "une", "pour", "avec", "niveau", "diplome", "ecole",
        "formation", "requis", "requise", "exige", "exigee", "apprecie",
        "prefere", "ou", "et", "dans", "cette", "offre", "poste", "valide",
        "specialise", "grande", "licence", "droit",
    ),
    "en": (
        "the", "and", "with", "for", "required", "requirement", "degree",
        "preferred", "experience", "years", "you", "will", "our", "team",
        "accepted", "equivalent", "office",
    ),
    "de": (
        "und", "oder", "mit", "der", "die", "das", "fur", "erforderlich",
        "erwunscht", "abschluss", "doktorat", "promotion", "wirtschaft",
        "betriebswirtschaft", "gleichwertige", "erfahrung", "von", "vorteil",
        "masterabschluss", "wirtschaftsingenieur",
    ),
    "it": (
        "laurea", "magistrale", "triennale", "ingegneria", "economia",
        "richiesto", "preferibile", "dottorato", "ricerca", "con", "per",
        "esperienza", "equivalente",
    ),
    "es": (
        "el", "los", "con", "para", "requerido", "deseable", "grado",
        "derecho", "doctorado", "master", "finanzas", "ingeniero", "experiencia",
        "equivalente", "titulo",
    ),
    "nl": (
        "met", "voor", "gevraagd", "gewenst", "master", "diploma", "financien",
        "hbo", "wo", "promotie", "doctoraat", "ervaring", "gelijkwaardig",
    ),
}
_SPECIAL_CHARS = {
    "fr": "àâçéèêëîïôùûüœ",
    "de": "äöüß",
    "es": "ñ¿¡",
    "it": "ìòù",
    "nl": "ëïé",
}


def detect_language(text: str) -> str:
    """Best-effort ISO 639-1 detection for the six supported languages.

    Returns ``"unknown"`` when no marker dominates. Detection is only used to
    gate a few ambiguous words (``promotion``, ``tesis``, ``dr.``); numeric
    levels such as ``Bac+5`` are matched in every language.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    folded = _fold(text)
    tokens = re.findall(r"[a-z']+", folded)
    if not tokens:
        return "unknown"
    counts: dict[str, int] = {}
    for language, markers in _LANGUAGE_MARKERS.items():
        marker_set = set(markers)
        counts[language] = sum(1 for token in tokens if token in marker_set)
        counts[language] += sum(2 for char in _SPECIAL_CHARS.get(language, "") if char in text.lower())
    best_language, best_score = max(counts.items(), key=lambda item: (item[1], -SUPPORTED_LANGUAGES.index(item[0])))
    if best_score == 0:
        return "unknown"
    # A single shared marker ("master", "in") is not enough to decide.
    if best_score < 2 and len(text.split()) > 2:
        return "unknown"
    return best_language


# ---------------------------------------------------------------------------
# Level patterns
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _LevelPattern:
    rank: int
    label: str
    pattern: re.Pattern[str]
    languages: tuple[str, ...] | None = None
    requires_education_context: bool = False
    generic_master: bool = False


def _compile(regex: str) -> re.Pattern[str]:
    return re.compile(regex, re.IGNORECASE)


_GENERIC_MASTER = _compile(r"\bmaster(?:'s)?\b(?!\s*(?:[12]\b|i{1,2}\b|specialise\b))")

# Ordered by specificity; overlapping matches are resolved by longest span, so
# "Laurea magistrale" wins over "Laurea" and "Master 2" over "Master".
_LEVEL_PATTERNS: tuple[_LevelPattern, ...] = (
    # 8 — PhD / doctorate
    _LevelPattern(8, "PhD", _compile(r"\bph\.?\s?d\.?(?![a-z0-9])")),
    _LevelPattern(8, "Doctorat", _compile(r"\bdoctorat\b")),
    _LevelPattern(8, "Docteur", _compile(r"\bdocteur\b"), languages=("fr",)),
    _LevelPattern(8, "Bac+8", _compile(r"\bbac\s*\+?\s*8\b")),
    _LevelPattern(8, "Doctorate", _compile(r"\bdoctorate\b")),
    _LevelPattern(8, "Doctorate", _compile(r"\bdoctoral\s+degree\b")),
    _LevelPattern(8, "Doctorat", _compile(r"\bthese\b"), languages=("fr",)),
    _LevelPattern(8, "Doktorat", _compile(r"\bdoktorat\b"), languages=("de",)),
    _LevelPattern(8, "Promotion", _compile(r"\bpromotion\b"), languages=("de",)),
    _LevelPattern(8, "Dr.", _compile(r"\bdr\."), languages=("de",)),
    _LevelPattern(8, "Dottorato", _compile(r"\bdottorato(?:\s+di\s+ricerca)?\b"), languages=("it",)),
    _LevelPattern(8, "Dottorato", _compile(r"\bdottore\s+di\s+ricerca\b"), languages=("it",)),
    _LevelPattern(8, "Doctorado", _compile(r"\bdoctorado\b"), languages=("es",)),
    _LevelPattern(8, "Doctorado", _compile(r"\btesis\b"), languages=("es",)),
    _LevelPattern(8, "Promotie", _compile(r"\bpromotie\b"), languages=("nl",)),
    _LevelPattern(8, "Doctoraat", _compile(r"\bdoctoraat\b"), languages=("nl",)),
    # 6 — Bac+6 / Master 2 / M2 / Master spécialisé
    _LevelPattern(6, "Bac+6", _compile(r"\bbac\s*\+?\s*6\b")),
    _LevelPattern(6, "Master 2", _compile(r"\bmaster\s*(?:2|ii)\b")),
    _LevelPattern(6, "M2", _compile(r"\bm2\b")),
    _LevelPattern(6, "Master spécialisé", _compile(r"\bmaster\s+specialise\b")),
    _LevelPattern(6, "Mastère", _compile(r"\bmastere\b")),
    _LevelPattern(6, "Grade master", _compile(r"\bgrade\s+master\b")),
    _LevelPattern(6, "Diplom", _compile(r"\bdiplom(?!\s*-?\s*ingenieur)\b"), languages=("de",)),
    # 5 — Bac+5 / Master / école d'ingénieur / grande école
    _LevelPattern(5, "Bac+5", _compile(r"\bbac\s*\+?\s*5\b")),
    _LevelPattern(5, "Master 1", _compile(r"\bmaster\s*(?:1|i)\b")),
    _LevelPattern(5, "M1", _compile(r"\bm1\b")),
    _LevelPattern(5, "Master", _GENERIC_MASTER, generic_master=True),
    _LevelPattern(5, "Master", _compile(r"\bmaster'?s\s+degree\b")),
    _LevelPattern(5, "Master", _compile(r"\bmaster\s+of\s+(?:science|arts|engineering|business)\b")),
    _LevelPattern(5, "Master", _compile(r"\bmasterabschluss\b"), languages=("de",)),
    _LevelPattern(5, "Master", _compile(r"\bmaster\s+abschluss\b"), languages=("de",)),
    _LevelPattern(5, "Master", _compile(r"\bfh\s+master\b"), languages=("de",)),
    _LevelPattern(5, "Master", _compile(r"\buniversity\s+master\b")),
    _LevelPattern(5, "Master", _compile(r"\bwo\s+master\b"), languages=("nl",)),
    _LevelPattern(5, "Master", _compile(r"\bmaster\s+(?:in|en|di)\b")),
    _LevelPattern(5, "MSc", _compile(r"\bm\.?\s?sc\.?(?![a-z0-9])")),
    _LevelPattern(5, "MA", _compile(r"\bm\.?\s?a\.?(?![a-z0-9])"), languages=("en",), requires_education_context=True),
    _LevelPattern(5, "Ingénieur", _compile(r"\b(?:diplome|titre|grade)\s+(?:d')?ingenieur\b")),
    _LevelPattern(5, "Ingénieur", _compile(r"\becole\s+(?:d')?ingenieur\b")),
    _LevelPattern(5, "Ingénieur", _compile(r"\bingenieur\s+diplome\b")),
    _LevelPattern(5, "Ingénieur", _compile(r"\bdiplom\s*-?\s*ingenieur\b"), languages=("de",)),
    _LevelPattern(5, "Ingénieur", _compile(r"\bingenieur\b"), requires_education_context=True),
    _LevelPattern(5, "Ingénieur", _compile(r"\bingegnere\b"), languages=("it",), requires_education_context=True),
    _LevelPattern(5, "Ingénieur", _compile(r"\b(?:titulo\s+de\s+)?ingeniero\b"), languages=("es",), requires_education_context=True),
    _LevelPattern(5, "Grande école", _compile(r"\bgrande\s+ecole\b")),
    _LevelPattern(5, "Grande école", _compile(r"\bprogramme\s+grande\s+ecole\b")),
    _LevelPattern(5, "Grande école", _compile(r"\bpge\b"), languages=("fr",)),
    _LevelPattern(5, "Laurea magistrale", _compile(r"\blaurea\s+(?:magistrale|specialistica|quinquennale)\b"), languages=("it",)),
    _LevelPattern(5, "Engineering degree", _compile(r"\bengineering\s+degree\b"), languages=("en",)),
    # 4 — Bac+4 / Bachelor 4 ans / laurea triennale / grado / HBO
    _LevelPattern(4, "Bac+4", _compile(r"\bbac\s*\+?\s*4\b")),
    _LevelPattern(4, "Bachelor", _compile(r"\bbachelor\s*4\b")),
    _LevelPattern(4, "Laurea", _compile(r"\blaurea\s+triennale\b"), languages=("it",)),
    _LevelPattern(4, "Laurea", _compile(r"\blaurea\b"), languages=("it",)),
    _LevelPattern(4, "Grado", _compile(r"\bgrado\b"), languages=("es",)),
    _LevelPattern(4, "Licenciatura", _compile(r"\blicenciatura\b"), languages=("es",)),
    _LevelPattern(4, "HBO", _compile(r"\bhbo\b"), languages=("nl",)),
    _LevelPattern(4, "HBO", _compile(r"\bhoger\s+beroepsonderwijs\b"), languages=("nl",)),
    # 3 — Bac+3 / licence / bachelor
    _LevelPattern(3, "Bac+3", _compile(r"\bbac\s*\+?\s*3\b")),
    _LevelPattern(3, "Licence", _compile(r"\blicence\b"), languages=("fr",)),
    _LevelPattern(3, "L3", _compile(r"\bl3\b"), languages=("fr",)),
    _LevelPattern(3, "Bachelor", _compile(r"\bbachelor\b")),
    _LevelPattern(3, "Bachelor", _compile(r"\bbakalaus\b"), languages=("de",)),
    _LevelPattern(3, "BSc", _compile(r"\bb\.?\s?sc\.?(?![a-z0-9])"), languages=("en",)),
    _LevelPattern(3, "BA", _compile(r"\bb\.?\s?a\.?(?![a-z0-9])"), languages=("en",), requires_education_context=True),
    _LevelPattern(3, "Undergraduate", _compile(r"\bundergraduate\b"), languages=("en",)),
)

_EDUCATION_CONTEXT = _compile(
    r"\b(?:diplome|diploma|degree|titre|niveau|formation|education|studies|study|"
    r"etudes|abschluss|titulo|laurea|graduation|qualification|ausbildung|opleiding|"
    r"studie)\b"
)
_MASTER_DEGREE_PHRASE = _compile(
    r"\bmaster(?:'s)?\s+(?:degree|of|in|en|di|abschluss|diploma|required|requis|exige|"
    r"preferred|prefere|apprecie|souhaite)\b"
)
_DRIVING_LICENCE = _compile(
    r"\b(?:permis\s+de\s+conduire|driving\s+licen[cs]e|driver'?s\s+licen[cs]e|fhrerschein)\b"
)
_FOUR_YEAR_HINT = _compile(
    r"\b(?:4\s*(?:years?|ans?|jahre)|4th\s+year|four\s+years|quatre\s+ans|4-jahrig)\b"
)

# Preferred / accepted / equivalent markers (folded).
_PREFERRED_MARKER = _compile(
    r"\b(?:preferred|prefere|preferee|apprecie|appreciee|souhaite|souhaitee|un\s+plus|"
    r"atout|desired|desirable|a\s+plus|erwunscht|erwunschte|von\s+vorteil|preferibile|"
    r"gradito|deseable|preferido|gewenst|plus)\b"
)
_ACCEPTED_MARKER = _compile(
    r"\b(?:accepted|accepte|acceptee|akzeptiert|accettato|aceptado|geaccepteerd)\b"
)
_EXPERIENCE_EQUIVALENT = _compile(
    r"\b(?:equivalent\s+experience|experience\s+equivalent|equivalente\s+esperienza|"
    r"experiencia\s+equivalente|gleichwertige\s+erfahrung|gelijkwaardige\s+ervaring)\b"
    r"|\bequivalent\s+par\s+l'?experience\b"
)
_VAGUE_EQUIVALENT = _compile(
    r"\b(?:ou\s+equivalent|or\s+equivalent|oder\s+gleichwertig|o\s+equivalente|"
    r"of\s+gelijkwaardig|equivalence|equivalent\b)"
)


# ---------------------------------------------------------------------------
# Field patterns
# ---------------------------------------------------------------------------

# Order is the deterministic tie-break when two fields share the same span
# (Italian/Spanish "economia" is Economics before Business).
_FIELD_ORDER: tuple[str, ...] = (
    "Data Science",
    "Engineering",
    "Finance",
    "Mathematics",
    "Economics",
    "Law",
    "Business",
)

_EDUCATION_FIELD_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Finance": tuple(_compile(regex) for regex in (
        r"\bfinance[s]?\b",
        r"\bfinancial\b",
        r"\bbanking\b",
        r"\bbanque\b",
        r"\bcorporate\s+finance\b",
        r"\bfinanzas?\b",
        r"\bfinanz(?:en)?\b",
        r"\bfinancien\b",
    )),
    "Engineering": tuple(_compile(regex) for regex in (
        r"\bingenieur\w*\b",
        r"\bengineering\b",
        r"\bingegnere\b",
        r"\bingegneria\b",
        r"\bingeniero\b",
        r"\bingenieria\b",
        r"\btechnisch\b",
        r"\bwirtschaftsingenieur\w*\b",
        r"\bdiplom\s*-?\s*ingenieur\b",
    )),
    "Business": tuple(_compile(regex) for regex in (
        r"\bbusiness\b",
        r"\bmanagement\b",
        r"\bgestion\b",
        r"\bcommerce\b",
        r"\bwirtschaft\w*\b",
        r"\beconomia\b",
        r"\bbedrijfskunde\b",
        r"\bbetriebswirtschaft\w*\b",
        r"\bhandel\b",
    )),
    "Data Science": tuple(_compile(regex) for regex in (
        r"\bdata\s+science\b",
        r"\bdata\s+analysis\b",
        r"\bdata\s+analytics\b",
        r"\banalyse\s+de\s+donnees\b",
        r"\bdatenanalyse\b",
        r"\banalisi\s+dati\b",
        r"\banalisis\s+de\s+datos\b",
        r"\bdataanalyse\b",
    )),
    "Mathematics": tuple(_compile(regex) for regex in (
        r"\bmathematiques\b",
        r"\bmathematics\b",
        r"\bmatematica\b",
        r"\bmatematicas\b",
        r"\bwiskunde\b",
        r"\bmath\b",
    )),
    "Economics": tuple(_compile(regex) for regex in (
        r"\beconomie\b",
        r"\beconomics\b",
        r"\bwirtschaft\b",
        r"\beconomia\b",
        r"\bvolkswirtschaft\w*\b",
        r"\beconometrie\b",
        r"\beconometrics\b",
    )),
    "Law": tuple(_compile(regex) for regex in (
        r"\bdroit\b",
        r"\blaw\b",
        r"\brecht\b",
        r"\bgiurisprudenza\b",
        r"\bderecho\b",
        r"\brechten\b",
    )),
}


def _field_priority(name: str) -> int:
    return _FIELD_ORDER.index(name)


@dataclass(slots=True)
class _FieldMatch:
    field: str
    start: int
    end: int


def _field_matches(folded: str, *, offset: int = 0) -> list[_FieldMatch]:
    found: list[_FieldMatch] = []
    for name, patterns in _EDUCATION_FIELD_PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(folded):
                found.append(_FieldMatch(name, offset + match.start(), offset + match.end()))
    found.sort(key=lambda item: (item.start, -(item.end - item.start), _field_priority(item.field)))
    return found


def _pick_field(folded_clause: str) -> str | None:
    matches = _field_matches(folded_clause)
    return matches[0].field if matches else None


# ---------------------------------------------------------------------------
# Clause segmentation (offset preserving)
# ---------------------------------------------------------------------------

_CLAUSE_BREAKS = set("\n;•|")
_SENTENCE_ENDS = set(".!?")


def _split_clauses(text: str) -> list[tuple[int, int]]:
    """Split text into offset-preserving clauses.

    Commas split clauses at bracket depth 0 (so ``(Finance, Économie)`` stays
    whole); sentence-ending dots split only when they do not close a short
    abbreviation (``M.Sc.``, ``Dr.``).
    """
    spans: list[tuple[int, int]] = []
    depth = 0
    start = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and (char in _CLAUSE_BREAKS or char == ","):
            spans.append((start, index))
            start = index + 1
        elif depth == 0 and char in _SENTENCE_ENDS:
            nxt = text[index + 1] if index + 1 < length else ""
            previous = re.search(r"[A-Za-z.]+$", text[start:index])
            token = previous.group(0) if previous else ""
            is_abbreviation = 0 < len(token) <= 3 and not token[-1].isdigit()
            if (not nxt or nxt.isspace()) and not is_abbreviation:
                spans.append((start, index))
                start = index + 1
        index += 1
    spans.append((start, length))

    cleaned: list[tuple[int, int]] = []
    for begin, end in spans:
        while begin < end and text[begin].isspace():
            begin += 1
        while end > begin and text[end - 1].isspace():
            end -= 1
        if begin < end:
            cleaned.append((begin, end))
    return cleaned


# ---------------------------------------------------------------------------
# Level matching
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _LevelMatch:
    rank: int
    label: str
    start: int
    end: int


def _language_allows(pattern: _LevelPattern, language: str) -> bool:
    if pattern.languages is None or language == "unknown":
        return True
    return language in pattern.languages


def _level_matches(folded_clause: str, *, offset: int, language: str) -> list[_LevelMatch]:
    candidates: list[_LevelMatch] = []
    for spec in _LEVEL_PATTERNS:
        if not _language_allows(spec, language):
            continue
        if spec.requires_education_context and not _EDUCATION_CONTEXT.search(folded_clause):
            continue
        if spec.label == "Licence" and _DRIVING_LICENCE.search(folded_clause):
            # A driving licence is not a French academic "licence".
            continue
        if spec.generic_master and not (_EDUCATION_CONTEXT.search(folded_clause)
                                        or _MASTER_DEGREE_PHRASE.search(folded_clause)
                                        or _VAGUE_EQUIVALENT.search(folded_clause)):
            continue
        for match in spec.pattern.finditer(folded_clause):
            candidates.append(_LevelMatch(spec.rank, spec.label, offset + match.start(), offset + match.end()))

    if not candidates:
        return []

    # Keep the longest match at each position (Laurea magistrale > Laurea,
    # Master 2 > Master, Diplôme d'ingénieur > ingénieur).
    candidates.sort(key=lambda item: (item.start, -(item.end - item.start), -item.rank))
    selected: list[_LevelMatch] = []
    for candidate in candidates:
        if selected and candidate.start < selected[-1].end:
            continue
        selected.append(candidate)
    return selected


_ALTERNATIVE = _compile(r"\b(?:ou|or|oder|oppure|o|of|albo)\b")
_CONJUNCTION = _compile(r"\b(?:et|and|und|e|y|en|sowie)\b")


def _refine_clauses(text: str, folded: str, clause: tuple[int, int], language: str) -> list[tuple[int, int]]:
    """Split ``A required and B accepted`` into two reportable clauses.

    A conjunction is only split when both sides independently state a level and
    at least one side is marked as preferred/accepted; otherwise
    ``Bac+3 et Master`` keeps its conjunction semantics (highest rank).
    """
    begin, end = clause
    folded_clause = folded[begin:end]
    preferred = bool(_PREFERRED_MARKER.search(folded_clause) or _ACCEPTED_MARKER.search(folded_clause))
    if not preferred:
        return [clause]
    for match in _CONJUNCTION.finditer(folded_clause):
        split_at = match.start()
        resume_at = match.end()
        left = _trim_span(text, begin, begin + split_at)
        right = _trim_span(text, begin + resume_at, end)
        if left is None or right is None:
            continue
        left_matches = _level_matches(folded[left[0]:left[1]], offset=left[0], language=language)
        right_matches = _level_matches(folded[right[0]:right[1]], offset=right[0], language=language)
        if left_matches and right_matches:
            return _refine_clauses(text, folded, left, language) + _refine_clauses(text, folded, right, language)
    return [clause]


def _trim_span(text: str, begin: int, end: int) -> tuple[int, int] | None:
    while begin < end and text[begin].isspace():
        begin += 1
    while end > begin and text[end - 1].isspace():
        end -= 1
    return (begin, end) if begin < end else None


def _connector(folded: str, left: _LevelMatch, right: _LevelMatch) -> str:
    between = folded[left.end:right.start]
    if _ALTERNATIVE.search(between):
        return "alternative"
    if _CONJUNCTION.search(between):
        return "conjunction"
    return "none"


def _required_rank(matches: list[_LevelMatch], folded_clause: str) -> _LevelMatch:
    """Return the match that best represents the clause requirement.

    Alternatives (``Bac+5 ou Bac+3``) lower the requirement to the easiest
    branch; conjunctions (``Bac+3 et Master``) and plain lists keep the highest
    stated level, as the mission contract requires.
    """
    if len(matches) == 1:
        return matches[0]
    kinds = {
        _connector(folded_clause, matches[index], matches[index + 1])
        for index in range(len(matches) - 1)
    }
    chosen_rank = min(item.rank for item in matches) if "alternative" in kinds else max(item.rank for item in matches)
    selected = [item for item in matches if item.rank == chosen_rank]
    # Prefer the most specific label (Ingénieur over a bare Master) then the
    # earliest occurrence.
    selected.sort(key=lambda item: (item.start, -(item.end - item.start)))
    return selected[0]


# ---------------------------------------------------------------------------
# Fact construction
# ---------------------------------------------------------------------------


def _quote_bounds(text: str, clause: tuple[int, int], match: _LevelMatch) -> tuple[str, int, int]:
    begin, end = clause
    if end - begin <= 320:
        return text[begin:end], begin, end
    begin = max(begin, match.start - 160)
    end = min(end, match.end + 160)
    return text[begin:end], begin, end


def _confidence_and_tokens(folded_clause: str) -> tuple[str, list[str]]:
    if _EXPERIENCE_EQUIVALENT.search(folded_clause):
        return "ambiguous", ["experience_equivalent"]
    if _PREFERRED_MARKER.search(folded_clause):
        return "inferred", ["preferred_only"]
    if _ACCEPTED_MARKER.search(folded_clause):
        return "explicit", ["accepted_alternative"]
    if re.search(r"\bgrande\s+ecole\b|\bpge\b", folded_clause) and \
            not re.search(r"\bbac\s*\+?\s*[3-8]\b", folded_clause):
        return "inferred", []
    if _VAGUE_EQUIVALENT.search(folded_clause):
        return "inferred", []
    return "explicit", []


def _fact_from_clause(text: str, folded: str, clause: tuple[int, int], language: str,
                      source_field: str) -> EducationFact | None:
    begin, end = clause
    folded_clause = folded[begin:end]
    matches = _level_matches(folded_clause, offset=begin, language=language)
    if not matches:
        return None
    chosen = _required_rank(matches, folded_clause)
    rank = chosen.rank
    label = chosen.label

    # "Bachelor's degree (4 years)" is a 4-year bachelor; the bare word alone
    # stays at rank 3.
    if rank == 3 and label == "Bachelor" and _FOUR_YEAR_HINT.search(folded_clause):
        rank = 4

    confidence, tokens = _confidence_and_tokens(folded_clause)
    education_field = _pick_field(folded_clause)
    quote, start_offset, end_offset = _quote_bounds(text, clause, chosen)
    return EducationFact(
        fact_type="education_level_required",
        level_rank=rank,
        level_label=label,
        field=education_field,
        source_field=source_field,
        quote=quote,
        start_offset=start_offset,
        end_offset=end_offset,
        confidence=confidence,  # type: ignore[arg-type]
        contradictions=tokens,
    )


def _field_only_fact(text: str, folded: str, clause: tuple[int, int], source_field: str) -> EducationFact | None:
    begin, end = clause
    folded_clause = folded[begin:end]
    education_field = _pick_field(folded_clause)
    if not education_field or not _EDUCATION_CONTEXT.search(folded_clause):
        return None
    quote = text[begin:end]
    return EducationFact(
        fact_type="education_field_required",
        level_rank=0,
        level_label="",
        field=education_field,
        source_field=source_field,
        quote=quote,
        start_offset=begin,
        end_offset=end,
        confidence="inferred",
        contradictions=[],
    )


def _merge_duplicates(facts: list[EducationFact]) -> list[EducationFact]:
    merged: list[EducationFact] = []
    seen: dict[tuple, EducationFact] = {}
    for fact in facts:
        key = (fact.fact_type, fact.level_rank, fact.level_label, fact.field, fact.confidence)
        if key in seen:
            existing = seen[key]
            for token in fact.contradictions:
                if token not in existing.contradictions:
                    existing.contradictions.append(token)
            continue
        seen[key] = fact
        merged.append(fact)
    return merged


def _limit_and_annotate(facts: list[EducationFact]) -> list[EducationFact]:
    facts.sort(key=lambda item: (item.start_offset, item.end_offset))
    if len(facts) > 2:
        # Keep the strongest required statement and the highest conflicting one.
        required = next((item for item in facts if not item.is_preferred), facts[0])
        others = [item for item in facts if item is not required]
        others.sort(key=lambda item: (-item.level_rank, item.start_offset))
        facts = sorted([required, others[0]], key=lambda item: item.start_offset)

    for index, fact in enumerate(facts):
        for other_index, other in enumerate(facts):
            if index == other_index:
                continue
            if fact.level_rank == 0 or other.level_rank == 0:
                continue
            if fact.level_rank == other.level_rank:
                continue
            token = f"conflict_with_rank_{other.level_rank}"
            if token not in fact.contradictions:
                fact.contradictions.append(token)
    return facts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_education(text: str, lang: str = "auto", *, source_field: str = "text") -> list[EducationFact]:
    """Extract canonical education requirements from ``text``.

    Args:
        text: Raw offer text. Offsets in the returned facts refer to this string.
        lang: ``"auto"`` for detection or one of ``fr, en, de, it, es, nl``.
        source_field: Name of the offer field the text came from, copied into
            every fact (default ``"text"``).

    Returns:
        Zero, one or two facts, ordered by position. More than two clauses is
        impossible to report without noise, so the required statement and the
        highest conflicting one are kept.

    Raises:
        TypeError: if ``text`` is not a string.
        ValueError: if ``lang`` is not supported.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if lang == "auto":
        language = detect_language(text)
    elif lang in (*SUPPORTED_LANGUAGES, "unknown"):
        language = lang
    else:
        raise ValueError(f"unsupported language: {lang!r}")

    if not text.strip():
        return []

    folded = _fold(text)
    clauses: list[tuple[int, int]] = []
    for clause in _split_clauses(text):
        clauses.extend(_refine_clauses(text, folded, clause, language))
    facts: list[EducationFact] = []
    for clause in clauses:
        fact = _fact_from_clause(text, folded, clause, language, source_field)
        if fact is not None:
            facts.append(fact)

    if not facts:
        for clause in clauses:
            field_fact = _field_only_fact(text, folded, clause, source_field)
            if field_fact is not None:
                facts.append(field_fact)
                break

    return _limit_and_annotate(_merge_duplicates(facts))


__all__ = [
    "EducationFact",
    "SUPPORTED_LANGUAGES",
    "CONFIDENCE_LEVELS",
    "detect_language",
    "extract_education",
]
