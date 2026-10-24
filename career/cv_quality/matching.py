"""Matching CV ↔ offer requirements into concrete, provable actions (CVBOOST-21).

Pure, deterministic, offline: the same CV and the same offer always produce
the same actions.  No network, no LLM, no clock, no randomness.

THE QUESTION
One question per offer requirement: *what concrete edit should I make to my
CV for this requirement?*  Every answer is backed by a verbatim excerpt of
the CV (exact substring + offset + field) or by the explicit statement that
nothing in the CV proves the requirement.  Nothing is ever invented.

ACTION CODES
``HIGHLIGHT``        the fact is already there — make it more visible.
``REPHRASE``         the fact is there but worded differently — reuse the
                     offer's vocabulary.
``DO_NOT_ADD``       nothing in the CV proves it — do not add it without proof.
``QUANTIFY``         the fact is there but without a figure — add a provable
                     number.
``CONFIRM_LANGUAGE`` the language is mentioned but its level is not proven —
                     confirm it.

INPUT
``cv_result`` is a :class:`~career.cv_quality.models.CVAnalysisResult`
(Mission 01) and ``offer`` is a dict holding the requirements extracted by
Mission 02 (``analyze_offer`` output, or a raw offer dict — in which case
the requirements are extracted on the fly with the very same contract).

PROVENANCE
``cv_evidence_text`` is always an exact substring of the CV source text, and
``cv_evidence_offset`` is its character index in that source.  When the CV
result does not carry its source text, no evidence can be quoted and every
requirement is reported as ``DO_NOT_ADD`` with an explicit warning: guessing
is never an option.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import (
    CVAnalysisResult,
    MatchAction,
    MatchActionCode,
    MatchEvidence,
    MatchResult,
)
from .structure import SECTION_KEYWORDS

__all__ = [
    "match_cv_to_offer",
    "find_evidence_in_cv",
    "extract_keywords",
    "MatchAction",
    "MatchEvidence",
    "MatchResult",
]


# ──────────────────────────────────────────────────────────────────────
# Vocabulary
# ──────────────────────────────────────────────────────────────────────

#: Mission 01 section title → evidence field name.
SECTION_FIELDS: dict[str, str] = {
    "Expérience": "experience",
    "Formation": "education",
    "Compétences": "skills",
    "Langues": "languages",
    "Projets": "projects",
    "Certifications": "certifications",
}

#: Field used when a proof sits outside every detected section.
DOCUMENT_FIELD = "document"

#: Maximum size of the quoted excerpt, in characters.
MAX_EVIDENCE_CHARS = 160

#: Accent folding used for every comparison (no external dependency).
_ACCENTS = str.maketrans(
    {
        "à": "a", "â": "a", "ä": "a", "é": "e", "è": "e", "ê": "e", "ë": "e",
        "î": "i", "ï": "i", "ô": "o", "ö": "o", "ù": "u", "û": "u", "ü": "u",
        "ç": "c", "ñ": "n", "œ": "oe", "æ": "ae",
    }
)

#: Tokens are split on everything but letters, digits, "+" and "#" so that
#: "C++" and "C#" survive as single tokens.
_TOKEN_SPLIT = re.compile(r"[^a-z0-9+#]+")

#: Function words — they never carry the meaning of a requirement.
_STOPWORDS = frozenset(
    {
        # English
        "the", "and", "for", "with", "you", "your", "our", "will", "have",
        "this", "that", "from", "are", "not", "plus", "must", "should", "can",
        "may", "using", "use", "who", "which", "what", "all", "any", "they",
        "has", "had", "was", "were", "good", "strong", "solid", "profile",
        # French
        "de", "du", "des", "la", "le", "les", "et", "ou", "un", "une", "en",
        "au", "aux", "d", "l", "n", "s", "c", "y", "a", "par", "pour", "avec",
        "sur", "dans", "est", "sont", "etre", "son", "sa", "ses", "ce", "cet",
        "cette", "qui", "que", "quoi", "dont", "ainsi", "aussi", "tres", "bien",
        "solide", "bonne", "excellent", "profil", "recherche", "postes",
    }
)

#: Requirement boilerplate — the way an offer asks never identifies a skill.
_REQUIREMENT_NOISE = frozenset(
    {
        "mandatory", "required", "require", "requires", "requiring",
        "obligatoire", "obligatoirement", "requis", "requise", "requisites",
        "exige", "exigee", "exigees", "indispensable", "indispensables",
        "must", "least", "minimum", "at", "souhaite", "souhaitable",
        "apprecie", "appreciee", "atout", "plus", "profil", "candidat",
        "candidature", "poste", "notre", "votre",
        # Section-label-like prefixes: they introduce a list of skills, they
        # never are one.  Left in, they dilute the proof and turn a fully
        # proven requirement into a partial one.
        "technologies", "technology", "techno", "stack",
        "outils", "tools", "outillage",
        "environnement", "environment", "env",
        "contexte", "context", "taches", "tasks",
        "missions", "mission", "secteur", "domaine",
    }
)

#: Capability and level words — they qualify a skill, they never identify it.
_WEAK_TOKENS = frozenset(
    {
        "experience", "experiences", "expertise", "maitrise", "maitrisant",
        "maitrisante", "connaissance", "connaissances", "pratique", "pratiques",
        "utilisation", "utiliser", "niveau", "competence", "competences",
        "skill", "skills", "ability", "abilities", "knowledge", "atleast",
        "annee", "annees", "an", "ans", "year", "years", "mois", "month",
        "months", "jour", "jours", "journee", "journees", "temps",
        "tempsplein", "tempspartiel", "pleintemps", "kenntnis", "kenntnisse",
        "savoirfaire", "masterise", "maitrisable", "langue", "langues",
        "courant", "courante", "fluent", "natif", "native", "professionnel",
        "professional", "avance", "avancee", "excellent", "parfait",
        "c1", "c2", "b2", "b1", "a2", "a1",
    }
)

#: Equivalent terms — a match through one of them is a match, but a weaker
#: one: the wording of the CV differs from the wording of the offer.
_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"gestion", "management", "pilotage"}),
    frozenset({"projet", "project"}),
    frozenset({"equipe", "team", "equipes"}),
    frozenset({"developpement", "development"}),
    frozenset({"automatisation", "automation"}),
    frozenset({"donnees", "data"}),
    frozenset({"vba", "macro", "macros"}),
    frozenset({"stage", "stagiaire", "internship", "intern"}),
    frozenset({"alternance", "apprentissage", "apprenticeship"}),
    frozenset({"client", "clients", "clientele"}),
    frozenset({"vente", "commercial", "sales"}),
    frozenset({"anglais", "english"}),
    frozenset({"francais", "french"}),
    frozenset({"allemand", "german"}),
    frozenset({"espagnol", "spanish"}),
    frozenset({"italien", "italian"}),
    frozenset({"portugais", "portuguese"}),
    frozenset({"chinois", "chinese", "mandarin"}),
    frozenset({"japonais", "japanese"}),
    frozenset({"neerlandais", "dutch"}),
    frozenset({"licence", "bachelor"}),
    frozenset({"master", "mastere"}),
    frozenset({"doctorat", "phd"}),
)

#: Language name → aliases that prove it.
_LANGUAGES: dict[str, tuple[str, ...]] = {
    "anglais": ("anglais", "english"),
    "francais": ("francais", "french"),
    "allemand": ("allemand", "german"),
    "espagnol": ("espagnol", "spanish"),
    "italien": ("italien", "italian"),
    "portugais": ("portugais", "portuguese"),
    "neerlandais": ("neerlandais", "dutch"),
    "chinois": ("chinois", "chinese", "mandarin"),
    "japonais": ("japonais", "japanese"),
    "coreen": ("coreen", "korean"),
    "russe": ("russe", "russian"),
    "arabe": ("arabe", "arabic"),
}

#: Display name of each language, used in the warnings.
_LANGUAGE_LABELS: dict[str, str] = {
    "anglais": "Anglais",
    "francais": "Français",
    "allemand": "Allemand",
    "espagnol": "Espagnol",
    "italien": "Italien",
    "portugais": "Portugais",
    "neerlandais": "Néerlandais",
    "chinois": "Chinois",
    "japonais": "Japonais",
    "coreen": "Coréen",
    "russe": "Russe",
    "arabe": "Arabe",
}

#: Level markers proving that a language level is stated, not only the language.
_LANGUAGE_LEVEL_MARKERS = (
    "courant", "courante", "fluent", "natif", "native", "professionnel",
    "professional", "avance", "avancee", "excellent", "parfait", "maitrise",
    "c1", "c2", "b2", "b1", "a2", "a1",
)

#: Separators that close the "language window" of a line.
_LANGUAGE_SEPARATORS = ",;|/"

#: A requirement carrying one of those is asking for a volume.
_QUANTITY_PATTERN = re.compile(
    r"""
    \d+\s*\+                                   # 10+
    | \d+\s*(?:à|a|-|–|to)\s*\d+               # 3 à 5
    | \d+\s*%                                   # 30%
    | \d+\s*(?:€|eur|euros?|k€|m€)              # 15k€/an
    | \d+\s*(?:ans?|annees?|years?|mois|months?|jours?|semaines?|weeks?)
    | \d+\s*(?:personnes?|people|collaborateurs?|clients?|projets?|postes?)
    | \d+\s*(?:heures?|hours?)
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: A figure anywhere in the excerpt.
_DIGIT_PATTERN = re.compile(r"\d")

#: Dates and phone numbers say *when* (or *who*), never *how much*: they are
#: not provable figures.  A CV line such as "2020-2023 | Chef de projet"
#: must not be read as a quantified achievement.
_DATE_LIKE_PATTERN = re.compile(
    r"""
      \d{1,2}[/.]\d{1,2}[/.]\d{2,4}       # 01/2023, 1/2/2020
    | \d{4}\s*[-–—/]\s*\d{2,4}           # 2020-2023
    | \d{1,2}\s*[-–—/]\s*\d{4}           # 01-2023
    | \+\d[\d\s().-]{7,}\d                # +33 6 12 34 56 78
    """,
    re.VERBOSE,
)

#: A bare year is a date too ("2018 | Stage | X"), not a figure.
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")


def _has_figure(text: str) -> bool:
    """Whether a text holds a provable figure.

    Dates and phone numbers are stripped first: they describe *when*, not
    *how much*.  "Géré équipe" on a line dated "2020-2023" carries no figure.
    """
    stripped = _DATE_LIKE_PATTERN.sub(" ", text)
    stripped = _YEAR_PATTERN.sub(" ", stripped)
    return bool(_DIGIT_PATTERN.search(stripped))

#: Education levels, expressed on the "Bac+X" scale.
#: The specific markers come first (so "Licence professionnelle" is not read
#: as a "Licence", and "Master 1" is not read as a "Master"), then the
#: general ones, from the highest level to the lowest.
_EDUCATION_MARKERS: tuple[tuple[str, int], ...] = (
    ("licence professionnelle", 2),
    ("licence pro", 2),
    ("master 1", 4),
    ("master1", 4),
    ("master 2", 5),
    ("master2", 5),
    ("bac+5", 5),
    ("bac 5", 5),
    ("bac+4", 4),
    ("bac 4", 4),
    ("bac+3", 3),
    ("bac 3", 3),
    ("bac+2", 2),
    ("bac 2", 2),
    ("doctorat", 6),
    ("phd", 6),
    ("master", 5),
    ("mastere", 5),
    ("mba", 5),
    ("m2", 5),
    ("ingenieur", 5),
    ("m1", 4),
    ("licence", 3),
    ("bachelor", 3),
    ("bachelier", 3),
    ("l3", 3),
    ("bts", 2),
    ("dut", 2),
    ("deug", 2),
    ("baccalaureat", 1),
    ("bac", 1),
    ("cap", 1),
    ("bep", 1),
)

#: Label of each education level, used in the warnings.
_EDUCATION_LABELS: dict[int, str] = {
    1: "Bac",
    2: "Bac+2 (BTS/DUT)",
    3: "Bac+3 (Licence)",
    4: "Bac+4 (M1)",
    5: "Bac+5 (Master/M2)",
    6: "Doctorat",
}

#: The reason used whenever the CV proves nothing.
DO_NOT_ADD_REASON = "Aucune preuve dans le CV, ne pas ajouter sans preuve."

#: The reason used when the fact is there but not visible enough.
HIGHLIGHT_REASON = (
    "Le fait existe. Le rendre plus visible (mots-clés, en haut de section, en gras)."
)

#: The reason used when a figure is missing.
QUANTIFY_REASON = (
    "Le fait existe mais sans chiffre. Ajouter un chiffre prouvable "
    "(ex : « géré une équipe de 10 » au lieu de « géré une équipe »)."
)


# ──────────────────────────────────────────────────────────────────────
# Synonym index
# ──────────────────────────────────────────────────────────────────────

_SYNONYM_INDEX: dict[str, frozenset[str]] = {}
for _group in _SYNONYM_GROUPS:
    for _member in _group:
        _SYNONYM_INDEX[_member] = frozenset(_group - {_member})


# ──────────────────────────────────────────────────────────────────────
# Text helpers
# ──────────────────────────────────────────────────────────────────────

def _fold(text: str) -> str:
    """Lowercase + strip accents (comparison only, never displayed)."""
    return text.lower().translate(_ACCENTS)


#: Words of every title a section may carry, per canonical section title.
#: They are used to tell the *label* of a header ("EXPÉRIENCE PROFESSIONNELLE")
#: from the *content* that may follow it on the same line.
_TITLE_VOCABULARY: dict[str, frozenset[str]] = {}
for _title, _title_keywords in SECTION_KEYWORDS.items():
    _words: set[str] = set()
    for _title_keyword in _title_keywords:
        _words.update(_fold(_title_keyword).split())
    _TITLE_VOCABULARY[_title] = frozenset(_words)

#: Single-word titles, used to recognize a section label at the start of a
#: line even when Mission 01 did not detect the section (a header line
#: carrying its content is too long to be detected as a header).
_SINGLE_WORD_TITLES: dict[str, str] = {}
for _title, _title_keywords in SECTION_KEYWORDS.items():
    for _title_keyword in _title_keywords:
        if " " not in _title_keyword:
            _SINGLE_WORD_TITLES.setdefault(_fold(_title_keyword), _title)

#: Characters that close a section label ("COMPETENCES : Python" -> the
#: label is "COMPETENCES").
_LABEL_SEPARATORS = ":;|-–—·,("

#: A word is a run of letters (accents included), digits excluded.
_WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)


def _first_separator(source: str, start: int, end: int) -> int | None:
    """Position of the first label separator in a range, if any."""
    for position in range(start, end):
        if source[position] in _LABEL_SEPARATORS:
            return position
    return None


def _label_span(source: str, start: int, title: str) -> tuple[int, int]:
    """Span of the section label starting at ``start``.

    The label is the leading run of words belonging to the section title
    ("EXPERIENCE PROFESSIONNELLE"); it stops at the first separator or at
    the first word that does not belong to it ("COMPETENCES : Python" keeps
    "Python" out of the label).
    """
    line_end = source.find("\n", start)
    if line_end == -1:
        line_end = len(source)

    vocabulary = _TITLE_VOCABULARY.get(title, frozenset())
    label_end = start
    position = start
    first = True
    while position < line_end:
        match = _WORD_PATTERN.search(source, position, line_end)
        if match is None:
            break
        if not first:
            gap = source[label_end:match.start()]
            if any(separator in gap for separator in _LABEL_SEPARATORS):
                break
        if _fold(match.group()) not in vocabulary:
            if first:
                # Unrecognized label: everything up to the first separator
                # belongs to it, so that a title is never read as a proof.
                separator = _first_separator(source, start, line_end)
                return start, separator if separator is not None else line_end
            break
        label_end = match.end()
        position = match.end()
        first = False
    return start, max(start, label_end)


def _tokenize(text: str) -> list[str]:
    """Split a text into comparable tokens."""
    return [token for token in _TOKEN_SPLIT.split(_fold(text)) if token]


def _word_positions(haystack: str, needle: str) -> list[int]:
    """Every start position of ``needle`` inside ``haystack``, word-bounded."""
    if not needle:
        return []
    pattern = re.compile(r"(?<![a-z0-9+#])" + re.escape(needle) + r"(?![a-z0-9+#])")
    return [match.start() for match in pattern.finditer(haystack)]


def extract_keywords(text: str) -> list[str]:
    """Significant terms of a requirement, in order of appearance.

    Function words and pure capability words ("maitrise", "experience", …)
    are dropped: they qualify a skill, they never identify it.  When nothing
    significant is left, the remaining words are returned so that a generic
    requirement ("3 ans d'expérience") is still matchable.
    """
    tokens = _tokenize(text)
    significant = [
        token
        for token in tokens
        if len(token) >= 3
        and token not in _STOPWORDS
        and token not in _WEAK_TOKENS
        and token not in _REQUIREMENT_NOISE
    ]
    if significant:
        return list(dict.fromkeys(significant))
    return list(
        dict.fromkeys(
            token
            for token in tokens
            if len(token) >= 2
            and token not in _STOPWORDS
            and token not in _REQUIREMENT_NOISE
        )
    )


# ──────────────────────────────────────────────────────────────────────
# Regions of the CV
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class _Region:
    """A part of the CV source that can be searched for a proof."""

    field: str
    start: int
    end: int


def _section_regions(cv_result: CVAnalysisResult, source_length: int) -> list[_Region]:
    """Detected sections, as searchable regions of the source text."""
    regions: list[_Region] = []
    for section in cv_result.sections:
        start = max(0, min(section.start_offset, source_length))
        end = max(start, min(section.end_offset, source_length))
        if end <= start:
            continue
        regions.append(
            _Region(
                field=SECTION_FIELDS.get(section.title, DOCUMENT_FIELD),
                start=start,
                end=end,
            )
        )
    regions.sort(key=lambda region: region.start)
    return regions


def _header_spans(cv_result: CVAnalysisResult, source: str) -> list[tuple[int, int]]:
    """Character ranges of the section titles.

    A section title is a label, not a proof: a "Projets" header never
    proves that the candidate has done projects.  Only the **label** is
    blocked: a header line often carries its content right after the label
    ("COMPETENCES : Python, SQL"), and that content *is* a proof.
    """
    spans: list[tuple[int, int]] = []
    for section in cv_result.sections:
        start = max(0, min(section.start_offset, len(source)))
        spans.append(_label_span(source, start, section.title))
    return spans


def _is_blocked(position: int, spans: list[tuple[int, int]]) -> bool:
    """True when the position sits inside a section title."""
    return any(start <= position < end for start, end in spans)


def _field_for_position(
    position: int, regions: list[_Region], scopes: list[tuple[int, int, str]]
) -> str:
    """Name of the CV field holding the given offset.

    A line that opens with a section label wins over the enclosing region:
    the "LANGUES : Français, Anglais" line holds languages, even when the
    section detection did not isolate it.
    """
    for start, end, field in scopes:
        if start <= position < end:
            return field
    for region in regions:
        if region.start <= position < region.end:
            return region.field
    return DOCUMENT_FIELD


def _label_scopes(source: str) -> list[tuple[int, int, str]]:
    """Lines opening with a section label, with the field they announce."""
    scopes: list[tuple[int, int, str]] = []
    length = len(source)
    position = 0
    while position < length:
        line_end = source.find("\n", position)
        if line_end == -1:
            line_end = length
        first_word = _WORD_PATTERN.search(source, position, line_end)
        if first_word is not None:
            title = _SINGLE_WORD_TITLES.get(_fold(first_word.group()))
            if title is not None:
                scopes.append(
                    (position, line_end, SECTION_FIELDS.get(title, DOCUMENT_FIELD))
                )
        position = line_end + 1
    return scopes


def _snippet_span(source: str, position: int) -> tuple[int, int]:
    """Span of the line holding ``position``, clipped to a readable window."""
    line_start = source.rfind("\n", 0, position) + 1
    line_end = source.find("\n", position)
    if line_end == -1:
        line_end = len(source)
    end = min(line_end, position + MAX_EVIDENCE_CHARS)
    start = max(line_start, end - MAX_EVIDENCE_CHARS)
    return start, end


# ──────────────────────────────────────────────────────────────────────
# Languages
# ──────────────────────────────────────────────────────────────────────

def _language_mentions(text: str) -> list[tuple[int, int, str]]:
    """Every language mention of a text: ``(start, end, language)``."""
    folded = _fold(text)
    mentions: set[tuple[int, int, str]] = set()
    for name, aliases in _LANGUAGES.items():
        for alias in aliases:
            for position in _word_positions(folded, alias):
                mentions.add((position, position + len(alias), name))
    return sorted(mentions)


def _languages_in(text: str) -> list[str]:
    """Every language mentioned by a text, in order of appearance."""
    names: list[str] = []
    for _start, _end, name in _language_mentions(text):
        if name not in names:
            names.append(name)
    return names


def _language_level_proven(text: str, language: str) -> bool:
    """Whether a language level is stated next to that language.

    The level must belong to the language: in "Français (natif), Anglais",
    the level "natif" qualifies the French, not the English.
    """
    folded = _fold(text)
    mentions = _language_mentions(folded)
    target = next((mention for mention in mentions if mention[2] == language), None)
    if target is None:
        return False
    start, end, _name = target

    previous = 0
    for mention_start, mention_end, _other in mentions:
        if mention_end <= start and (mention_start, mention_end) != (start, end):
            previous = max(previous, mention_end)
    for position, character in enumerate(folded[:start]):
        if character in _LANGUAGE_SEPARATORS:
            previous = max(previous, position + 1)

    following = len(folded)
    for mention_start, mention_end, _other in mentions:
        if mention_start >= end and (mention_start, mention_end) != (start, end):
            following = min(following, mention_start)
    for position in range(end, len(folded)):
        if folded[position] in _LANGUAGE_SEPARATORS:
            following = min(following, position)
            break

    window = folded[previous:following]
    return any(_word_positions(window, marker) for marker in _LANGUAGE_LEVEL_MARKERS)


def _requirement_language(text: str, category: str) -> str | None:
    """Language of a requirement, when the requirement is about a language.

    A requirement naming several languages ("Français et espagnol") is not
    handled here: it goes through the generic path, which reports honestly
    that the CV only proves part of it.
    """
    names = _languages_in(text)
    if len(names) != 1:
        return None
    language = names[0]
    if category == "language":
        return language
    keywords = extract_keywords(text)
    aliases = set(_LANGUAGES.get(language, ()))
    if keywords and all(keyword in aliases for keyword in keywords):
        return language
    return None


def _missing_languages(cv_result: CVAnalysisResult, text: str) -> list[str]:
    """Languages a requirement asks for that the CV never mentions."""
    source = cv_result.provenance.source_text
    if not source:
        return []
    folded_source = _fold(source)
    blocked = _header_spans(cv_result, source)
    missing: list[str] = []
    for language in _languages_in(text):
        if language in missing:
            continue
        position, _literal = _language_position(folded_source, language, blocked)
        if position is None:
            missing.append(language)
    return missing


# ──────────────────────────────────────────────────────────────────────
# Evidence search
# ──────────────────────────────────────────────────────────────────────

def _first_position(
    positions: list[int], blocked: list[tuple[int, int]]
) -> int | None:
    """First position that is not inside a section title."""
    for position in positions:
        if not _is_blocked(position, blocked):
            return position
    return None


def _literal_position(
    folded_source: str, token: str, blocked: list[tuple[int, int]]
) -> int | None:
    """First occurrence of the token itself in the CV."""
    return _first_position(_word_positions(folded_source, token), blocked)


def _synonym_position(
    folded_source: str, token: str, blocked: list[tuple[int, int]]
) -> int | None:
    """First occurrence of an equivalent term in the CV."""
    best: int | None = None
    for equivalent in sorted(_SYNONYM_INDEX.get(token, ())):
        position = _literal_position(folded_source, equivalent, blocked)
        if position is not None and (best is None or position < best):
            best = position
    return best


def _language_position(
    folded_source: str, language: str, blocked: list[tuple[int, int]]
) -> tuple[int | None, bool]:
    """Where a language is mentioned, and whether it is the exact wording.

    Returns ``(position, is_literal)``.
    """
    aliases = _LANGUAGES.get(language, ())
    literal = _first_position(_word_positions(folded_source, aliases[0]), blocked)
    if literal is not None:
        return literal, True
    best: int | None = None
    for alias in sorted(aliases[1:]):
        position = _first_position(_word_positions(folded_source, alias), blocked)
        if position is not None and (best is None or position < best):
            best = position
    return best, False


def find_evidence_in_cv(
    cv_result: CVAnalysisResult, requirement: str, category: str = ""
) -> MatchEvidence | None:
    """Find the CV excerpt proving a requirement, if there is one.

    The returned excerpt is an exact substring of the CV source text and
    carries its offset and its field.  ``None`` means nothing in the CV
    proves the requirement — the caller must then say so explicitly instead
    of inventing an evidence.
    """
    source = cv_result.provenance.source_text
    if not source:
        return None

    folded_source = _fold(source)
    blocked = _header_spans(cv_result, source)
    regions = _section_regions(cv_result, len(source))
    scopes = _label_scopes(source)

    language = _requirement_language(requirement, category)
    if language is not None:
        position, _literal = _language_position(folded_source, language, blocked)
        if position is None:
            return None
        start, end = _snippet_span(source, position)
        return MatchEvidence(
            text=source[start:end],
            offset=start,
            field=_field_for_position(position, regions, scopes),
            confidence=0.9,
        )

    keywords = extract_keywords(requirement)
    if not keywords:
        return None

    matched: list[tuple[str, int, bool]] = []
    for token in keywords:
        position = _literal_position(folded_source, token, blocked)
        if position is not None:
            matched.append((token, position, True))
            continue
        position = _synonym_position(folded_source, token, blocked)
        if position is not None:
            matched.append((token, position, False))

    if not matched:
        return None

    position = matched[0][1]
    coverage = len(matched) / len(keywords)
    if all(is_literal for _, _, is_literal in matched):
        confidence = 0.9 if coverage == 1.0 else round(0.6 + 0.2 * coverage, 2)
    else:
        confidence = 0.7

    start, end = _snippet_span(source, position)
    return MatchEvidence(
        text=source[start:end],
        offset=start,
        field=_field_for_position(position, regions, scopes),
        confidence=confidence,
        coverage=round(coverage, 4),
    )


# ──────────────────────────────────────────────────────────────────────
# Requirements
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class _Requirement:
    """One offer requirement, normalized."""

    text: str
    category: str
    mandatory: bool
    modality: str


def _requirement_records(offer: dict[str, Any]) -> list[dict[str, Any]]:
    """Requirement records carried by the offer, whatever their shape."""
    raw = offer.get("requirements")
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("items") or []
    if isinstance(raw, str):
        # A raw offer carries its requirements as a free-text block.
        return [{"text": line} for line in raw.splitlines() if line.strip()]
    records: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, str):
            records.append({"text": item})
        elif isinstance(item, dict):
            records.append(item)
    return records


def _is_mandatory(record: dict[str, Any]) -> bool:
    """Whether a requirement is mandatory.

    Mission 21 speaks of a ``mandatory`` flag, Mission 02 of a ``modality``
    ("required" / "preferred" / "contextual" / "unknown").  Both are read:
    an explicit flag wins, an unknown modality is never guessed mandatory.
    """
    mandatory = record.get("mandatory")
    if isinstance(mandatory, bool):
        return mandatory
    modality = str(record.get("modality") or "").strip().lower()
    if modality:
        return modality == "required"
    return bool(record.get("required", True))


def _normalize_requirements(offer: dict[str, Any]) -> list[_Requirement]:
    """Normalized requirement list of an offer."""
    requirements: list[_Requirement] = []
    for record in _requirement_records(offer):
        text = str(record.get("text") or "").strip()
        category = str(record.get("category") or "skill").strip().lower() or "skill"
        modality = str(record.get("modality") or "").strip().lower()
        requirements.append(
            _Requirement(
                text=text,
                category=category,
                mandatory=_is_mandatory(record),
                modality=modality,
            )
        )
    return requirements


def _requirements_of(offer: dict[str, Any]) -> list[_Requirement]:
    """Requirements of an offer, whatever shape the offer has.

    ``analyze_offer`` output (Mission 02) is used as is.  A raw offer is
    read with the very same contract, so both produce the same actions.
    """
    raw = offer.get("requirements")
    if isinstance(raw, list):
        return _normalize_requirements(offer)
    return _normalize_requirements(_extract_requirements(offer))


# ──────────────────────────────────────────────────────────────────────
# Education level
# ──────────────────────────────────────────────────────────────────────

def _education_level(text: str) -> int | None:
    """Education level mentioned in a text, on the "Bac+X" scale.

    The **highest** level wins: a text mentioning a "Bac+2" and a "Master" is
    a "Master".  A more specific marker shadows the generic one it contains,
    so "licence professionnelle" stays a Bac+2 (not a "licence" Bac+3) and
    "Master 1" stays a Bac+4 (not a "Master" Bac+5).
    """
    folded = _fold(text)
    matches: list[tuple[int, int, int]] = []
    for marker, level in _EDUCATION_MARKERS:
        for start in _word_positions(folded, marker):
            matches.append((start, start + len(marker), level))

    if not matches:
        return None

    # A marker contained in a strictly longer marker is shadowed by it.
    levels = [
        level
        for start, end, level in matches
        if not any(
            other_start <= start
            and end <= other_end
            and (other_end - other_start) > (end - start)
            for other_start, other_end, _other_level in matches
        )
    ]
    return max(levels) if levels else None


def _cv_education_level(cv_result: CVAnalysisResult) -> int | None:
    """Highest education level found in the CV formation section."""
    source = cv_result.provenance.source_text
    if not source:
        return None
    regions = [
        region
        for region in _section_regions(cv_result, len(source))
        if region.field == "education"
    ]
    if not regions:
        return None
    levels = [
        level
        for region in regions
        for level in [_education_level(source[region.start:region.end])]
        if level is not None
    ]
    return max(levels) if levels else None


def _offer_education_level(
    offer: dict[str, Any], requirements: list[_Requirement]
) -> int | None:
    """Highest education level required by the offer."""
    declared = offer.get("education_level")
    if isinstance(declared, bool):
        declared = None
    if isinstance(declared, int):
        return declared
    if isinstance(declared, str) and declared.strip():
        level = _education_level(declared)
        if level is not None:
            return level
    levels = [
        level
        for requirement in requirements
        if requirement.category in ("education", "education_level")
        for level in [_education_level(requirement.text)]
        if level is not None
    ]
    return max(levels) if levels else None


def _education_label(level: int | None) -> str:
    """Readable label of an education level."""
    if level is None:
        return "non précisé"
    return _EDUCATION_LABELS.get(level, f"niveau {level}")


# ──────────────────────────────────────────────────────────────────────
# Warnings
# ──────────────────────────────────────────────────────────────────────

def _offer_mentions_alternance(
    offer: dict[str, Any], requirements: list[_Requirement]
) -> bool:
    """Whether the offer is an alternance/apprenticeship contract."""
    contract = _fold(str(offer.get("contract_type") or ""))
    if contract in ("alternance", "apprentissage", "apprenticeship"):
        return True
    haystacks = [
        _fold(str(offer.get("description_original") or "")),
        _fold(str(offer.get("contract_type") or "")),
    ]
    haystacks.extend(_fold(requirement.text) for requirement in requirements)
    return any(
        _word_positions(haystack, marker)
        for haystack in haystacks
        for marker in ("alternance", "apprentissage")
    )


# ──────────────────────────────────────────────────────────────────────
# Action decision
# ──────────────────────────────────────────────────────────────────────

def _action_code(
    requirement: _Requirement,
    evidence: MatchEvidence | None,
    language: str | None,
) -> tuple[MatchActionCode, str, float]:
    """Decide the action for one requirement.

    Returns ``(code, reason, confidence)``.
    """
    if evidence is None:
        return "DO_NOT_ADD", DO_NOT_ADD_REASON, 1.0

    if language is not None:
        if not _language_level_proven(evidence.text, language):
            return (
                "CONFIRM_LANGUAGE",
                "La langue est mentionnée dans le CV mais le niveau n'est pas "
                "prouvé : à confirmer (ex : niveau C1).",
                evidence.confidence,
            )
        return "HIGHLIGHT", HIGHLIGHT_REASON, evidence.confidence

    if _QUANTITY_PATTERN.search(requirement.text) and not _has_figure(evidence.text):
        return "QUANTIFY", QUANTIFY_REASON, evidence.confidence

    if evidence.confidence < 0.9:
        excerpt = evidence.text.strip()
        if len(excerpt) > 60:
            excerpt = excerpt[:60] + "…"
        if evidence.coverage < 1.0:
            return (
                "REPHRASE",
                f"Le CV ne prouve qu'une partie de l'exigence : « {requirement.text} ». "
                f"Reformuler la ligne avec le vocabulaire de l'offre (extrait : « {excerpt} »).",
                evidence.confidence,
            )
        return (
            "REPHRASE",
            f"Reformuler avec le vocabulaire de l'offre : « {requirement.text} » "
            f"au lieu de « {excerpt} ».",
            evidence.confidence,
        )

    return "HIGHLIGHT", HIGHLIGHT_REASON, evidence.confidence


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def match_cv_to_offer(cv_result: CVAnalysisResult, offer: dict[str, Any]) -> MatchResult:
    """Match an analyzed CV against the requirements of an offer.

    Pure and deterministic: same CV, same offer, same result — always.
    No network, no LLM, no clock.

    Args:
        cv_result: The analyzed CV (Mission 01).
        offer: The offer dict.  It may be the output of
            ``career.offer_requirements.analyze_offer`` (Mission 02) or a raw
            offer dict — the requirements are then extracted with the same
            contract.

    Returns:
        A :class:`MatchResult` with exactly one action per requirement.
    """
    offer = offer or {}
    requirements = _requirements_of(offer)

    actions: list[MatchAction] = []
    missing_critical: list[str] = []
    warnings: list[str] = []

    source_available = bool(cv_result.provenance.source_text)
    if not source_available:
        warnings.append(
            "Texte source du CV indisponible : aucune provenance exacte n'est "
            "possible, aucune exigence ne peut être prouvée."
        )

    for requirement in requirements:
        language = _requirement_language(requirement.text, requirement.category)
        evidence = (
            find_evidence_in_cv(cv_result, requirement.text, requirement.category)
            if source_available
            else None
        )
        code, reason, confidence = _action_code(requirement, evidence, language)
        actions.append(
            MatchAction(
                code=code,
                requirement_text=requirement.text,
                cv_evidence_text=evidence.text if evidence else None,
                cv_evidence_offset=evidence.offset if evidence else None,
                cv_evidence_field=evidence.field if evidence else None,
                reason=reason,
                confidence=confidence,
            )
        )
        if code == "DO_NOT_ADD":
            if requirement.mandatory:
                missing_critical.append(requirement.text)
        elif code == "CONFIRM_LANGUAGE":
            warnings.append(
                f"Langue mentionnée sans niveau démontré : « {requirement.text} » — à confirmer."
            )
        # A language the CV never mentions is reported, whatever category the
        # offer gave the requirement: the warning is about the language, not
        # about the way the offer was written.
        unproven = _missing_languages(cv_result, requirement.text)
        if unproven:
            labels = ", ".join(_LANGUAGE_LABELS.get(name, name) for name in unproven)
            warnings.append(f"Langue requise non prouvée dans le CV : « {labels} ».")

    warnings.extend(_contract_warnings(offer, requirements))
    warnings.extend(_education_warnings(cv_result, offer, requirements))

    matched = sum(1 for action in actions if action.code != "DO_NOT_ADD")
    total = len(requirements)
    missing_critical = list(dict.fromkeys(missing_critical))
    if missing_critical:
        warnings.append(
            f"{len(missing_critical)} exigence(s) obligatoire(s) sans preuve dans le CV."
        )

    return MatchResult(
        overall_score=round(matched / total, 4) if total else 0.0,
        matched_requirements=matched,
        total_requirements=total,
        actions=actions,
        missing_critical=missing_critical,
        warnings=list(dict.fromkeys(warnings)),
    )


def _extract_requirements(offer: dict[str, Any]) -> dict[str, Any]:
    """Extract the requirements of a raw offer with the Mission 02 contract."""
    try:
        from career.offer_requirements import analyze_offer
    except Exception:  # pragma: no cover - defensive: the contract stays optional
        return {"requirements": []}
    try:
        return analyze_offer(offer)
    except Exception:  # pragma: no cover - a broken offer must not break the match
        return {"requirements": []}


def _contract_warnings(
    offer: dict[str, Any], requirements: list[_Requirement]
) -> list[str]:
    """Cross-cutting warnings about the contract of the offer."""
    if _offer_mentions_alternance(offer, requirements):
        return ["Alternance détectée — vérifie que ton brief exclut l'alternance."]
    return []


def _education_warnings(
    cv_result: CVAnalysisResult, offer: dict[str, Any], requirements: list[_Requirement]
) -> list[str]:
    """Warning when the offer asks for a higher degree than the CV shows."""
    offer_level = _offer_education_level(offer, requirements)
    cv_level = _cv_education_level(cv_result)
    if offer_level is None or cv_level is None or cv_level >= offer_level:
        return []
    return [
        f"Niveau d'études requis ({_education_label(offer_level)}) > "
        f"CV ({_education_label(cv_level)})."
    ]
