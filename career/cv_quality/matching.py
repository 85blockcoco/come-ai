"""Matching a CV against one offer — concrete, provable actions (CVBOOST-21).

Pure, deterministic, offline: the same CV and the same offer always produce
the same actions.  No network, no LLM, no clock, no randomness.

THE QUESTION
One question per offer requirement: *what concrete edit should I make to my
CV for this requirement?*  Every answer is backed by a verbatim excerpt of
the CV (exact substring + offset + field) or by the explicit statement that
nothing in the CV proves the requirement.  Nothing is ever invented: when the
CV result does not carry its source text, no excerpt can be quoted and every
requirement is reported as ``DO_NOT_ADD`` with an explicit warning.

ACTION CODES
``HIGHLIGHT``        the fact is already there — make it more visible.
``REPHRASE``         the fact is there but worded differently — reuse the
                     offer's vocabulary.
``DO_NOT_ADD``       nothing in the CV proves it — do not add it without proof.
``QUANTIFY``         the fact is there but without a figure — add a provable
                     number.
``CONFIRM_LANGUAGE`` the language is mentioned but its level is not proven —
                     confirm it before asserting it.

INPUT
``cv_result`` is a :class:`~career.cv_quality.models.CVAnalysisResult`
(Mission 01) and ``offer`` is a dict holding the requirements extracted by
Mission 02.  Three shapes are accepted:

- the Mission 02 contract itself (``analyze_offer(offer)`` output, whose
  ``requirements`` are dicts carrying ``text``/``category``/``modality``),
- a plain ``{"requirements": ["Python", ...]}`` list of strings,
- a raw offer dict without extracted requirements: Mission 02 is then run on
  the fly, with the very same contract.

A requirement is *mandatory* when the offer says so: ``mandatory`` when the
record carries it, otherwise the Mission 02 ``modality`` (``required`` is
mandatory, ``preferred``/``contextual``/``unknown`` are not).  Only
mandatory requirements without evidence end up in ``missing_critical``.
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

__all__ = [
    "match_cv_to_offer",
    "find_evidence_in_cv",
    "extract_keywords",
    "MatchAction",
    "MatchEvidence",
    "MatchResult",
]


# ──────────────────────────────────────────────────────────────────────
# Constants
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

#: Context kept before the match when an excerpt is cut.
EXCERPT_LEAD = 30

#: Width of the window used to gather the keywords of one requirement.
KEYWORD_WINDOW = 200

#: Accent folding used for every comparison (no external dependency).
#: Every mapping is 1 character → 1 character so that the folded text keeps
#: the exact length of the source: offsets never drift.
_ACCENT_MAP: dict[str, str] = {
    "à": "a", "â": "a", "ä": "a", "á": "a", "ã": "a", "å": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o", "ö": "o", "õ": "o",
    "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "ý": "y", "ÿ": "y",
    "ç": "c", "ñ": "n", "š": "s", "ž": "z", "č": "c",
}

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
        "of", "in", "on", "to", "is", "be", "as", "at", "or", "an", "we",
        # French
        "de", "du", "des", "la", "le", "les", "et", "ou", "un", "une", "en",
        "au", "aux", "d", "l", "n", "s", "c", "y", "a", "par", "pour", "avec",
        "sur", "dans", "est", "sont", "etre", "son", "sa", "ses", "ce", "cet",
        "cette", "qui", "que", "quoi", "dont", "ainsi", "aussi", "tres",
        "bien", "solide", "bonne", "excellent", "profil", "recherche",
        "postes", "del", "una", "por", "para", "con", "una",
    }
)

#: Requirement boilerplate — the way an offer asks never identifies a skill.
_REQUIREMENT_NOISE = frozenset(
    {
        "mandatory", "required", "require", "requires", "requiring",
        "obligatoire", "obligatoirement", "requis", "requise", "requisites",
        "exige", "exigee", "exigees", "indispensable", "indispensables",
        "must", "least", "minimum", "at", "souhaite", "souhaitable",
        "apprecie", "appreciee", "atout", "candidat", "candidature",
        "poste", "notre", "votre", "etudes", "experience", "profil",
        "connaissance", "maitrise", "niveau", "competence",
    }
)

#: Capability words — they qualify a skill, they never identify it.
_WEAK_TOKENS = frozenset(
    {
        "experiences", "expertise", "maitrisant", "maitrisante",
        "connaissances", "pratique", "pratiques", "utilisation", "utiliser",
        "competences", "skills", "ability", "abilities", "knowledge",
        "annee", "annees", "ans", "an", "year", "years", "mois", "month",
        "months", "jour", "jours", "journee", "journees", "temps",
        "tempsplein", "tempspartiel", "pleintemps", "kenntnis",
        "kenntnisse", "savoirfaire", "masterise", "maitrisable",
        "langue", "langues", "courant", "courante", "fluent", "natif",
        "native", "professionnel", "professional", "avance", "avancee",
        "parfait", "c1", "c2", "b2", "b1", "a2", "a1",
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
    frozenset({"reporting", "tableau de bord", "dashboard"}),
    frozenset({"base de donnees", "database"}),
    frozenset({"api", "apis", "web service"}),
    frozenset({"veille", "monitoring"}),
    frozenset({"test", "tests", "qa"}),
    frozenset({"securite", "security"}),
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

#: Level markers proving that a language level is stated, not only the name.
_LANGUAGE_LEVEL_MARKERS = (
    "courant", "courante", "fluent", "natif", "native", "professionnel",
    "professional", "avance", "avancee", "excellent", "parfait", "maitrise",
    "c1", "c2", "b2", "b1", "a2", "a1",
)

#: A requirement carrying one of those asks for a volume.
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

#: Education levels on the "Bac+X" scale.  The specific markers come first
#: (so "Licence professionnelle" is not read as a "Licence" and "Master 1" is
#: not read as a "Master"), then the general ones.
_EDUCATION_MARKERS: tuple[tuple[str, int], ...] = (
    ("licence professionnelle", 3),
    ("licence pro", 3),
    ("master 1", 4),
    ("master1", 4),
    ("m1", 4),
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
    ("licence", 3),
    ("bachelor", 3),
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

#: Keywords that identify a category when the offer record carries none.
_CATEGORY_KEYWORDS: dict[str, frozenset[str]] = {
    "language": frozenset(
        {
            "anglais", "english", "francais", "french", "allemand", "german",
            "espagnol", "spanish", "italien", "italian", "portugais",
            "portuguese", "chinois", "mandarin", "japonais", "japanese",
            "coreen", "russe", "arabe", "neerlandais", "dutch",
            "langue", "langues", "language", "languages",
        }
    ),
    "education": frozenset(
        {
            "master", "mastere", "m1", "m2", "licence", "bachelor", "doctorat",
            "phd", "diplome", "diplomes", "universite", "ecole", "formation",
            "bac", "baccalaureat", "bts", "dut", "ingenieur", "mba", "etudes",
            "grade", "diploma", "degree",
        }
    ),
    "experience": frozenset(
        {
            "experience", "experiences", "expositions", "ans", "annees",
            "mois", "years", "month", "months", "parcours",
        }
    ),
    "contract": frozenset(
        {
            "alternance", "apprentissage", "apprenticeship", "stage",
            "stagiaire", "internship", "cdi", "cdd", "vie", "contrat",
            "temps plein", "temps partiel", "freelance",
        }
    ),
    "availability": frozenset(
        {
            "disponible", "disponibilite", "asap", "immediatement",
            "date de debut", "starting", "start date",
        }
    ),
    "mobility": frozenset(
        {
            "mobilite", "relocation", "relocation", "teletravail", "remote",
            "hybride", "hybrid", "permis", "deplacements",
        }
    ),
    "work_authorization": frozenset(
        {
            "autorisation de travail", "visa", "nationalite", "permis de",
            "work permit", "work authorization", "right to work", "citizenship",
        }
    ),
}

#: Contract types that mean "alternance".
_ALTERNANCE_CONTRACTS = frozenset({"alternance", "apprentissage", "apprenticeship"})

#: The reason used whenever the CV proves nothing.
DO_NOT_ADD_REASON = "Aucune preuve dans le CV, ne pas ajouter sans preuve."

#: The reason used when the fact is there but not visible enough.
HIGHLIGHT_REASON = (
    "Le fait existe. Le rendre plus visible (mots-clés, en haut de section, en gras)."
)

#: The reason used when the fact is there but without a figure.
QUANTIFY_REASON = (
    "Le fait existe mais sans chiffre. Ajouter un chiffre prouvable "
    "(ex : « géré une équipe de 10 personnes » au lieu de « géré une équipe »)."
)

#: Warning emitted when the CV source text is not available.
NO_SOURCE_WARNING = (
    "Texte source du CV indisponible : aucune preuve ne peut être citée, "
    "chaque exigence est signalée DO_NOT_ADD."
)

#: Warning emitted for an alternance offer.
ALTERNANCE_WARNING = "Alternance détectée — vérifie que ton brief exclut l'alternance."


# ──────────────────────────────────────────────────────────────────────
# Internal records
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Requirement:
    """One offer requirement, normalized."""

    text: str
    category: str
    mandatory: bool
    negated: bool
    preferred: bool = False


@dataclass(frozen=True, slots=True)
class _Hit:
    """One occurrence of a requirement keyword inside the CV source."""

    offset: int
    length: int
    keyword: str
    synonym: bool


# ──────────────────────────────────────────────────────────────────────
# Text helpers
# ──────────────────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    """Lowercase + strip accents, keeping the length identical to the input.

    The length is preserved on purpose: every offset computed on the folded
    text is an offset of the original text.
    """
    out: list[str] = []
    for char in text:
        lowered = char.lower()
        if len(lowered) != 1:  # pragma: no cover - exotic characters only
            out.append(char)
            continue
        out.append(_ACCENT_MAP.get(lowered, lowered))
    return "".join(out)


def _tokenize(text: str) -> list[str]:
    """Split a text into comparable tokens."""
    return [token for token in _TOKEN_SPLIT.split(_fold(text)) if token]


def _contains_word(haystack: str, needle: str) -> bool:
    """True when ``needle`` appears in ``haystack`` on word boundaries."""
    if not needle:
        return False
    pattern = re.compile(r"(?<![a-z0-9+#])" + re.escape(needle) + r"(?![a-z0-9+#])")
    return pattern.search(haystack) is not None


def _word_positions(haystack: str, needle: str) -> list[int]:
    """Every start position of ``needle`` inside ``haystack``, word-bounded."""
    if not needle:
        return []
    pattern = re.compile(r"(?<![a-z0-9+#])" + re.escape(needle) + r"(?![a-z0-9+#])")
    return [match.start() for match in pattern.finditer(haystack)]


def _slug(text: str) -> str:
    """Lowercase, accent-free slug used as a fallback field name."""
    return "-".join(part for part in _tokenize(text) if part)


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
        if token not in _STOPWORDS
        and token not in _REQUIREMENT_NOISE
        and token not in _WEAK_TOKENS
        and not token.isdigit()
    ]
    if significant:
        return significant
    return [
        token
        for token in tokens
        if token not in _STOPWORDS and token not in _REQUIREMENT_NOISE
    ]


def _synonyms_of(token: str) -> frozenset[str]:
    """Every token equivalent to ``token`` (empty when there is none)."""
    for group in _SYNONYM_GROUPS:
        if token in group:
            return frozenset(group - {token})
    for aliases in _LANGUAGES.values():
        if token in aliases:
            return frozenset(alias for alias in aliases if alias != token)
    return frozenset()


def _detect_category(text: str) -> str:
    """Category of a requirement when the offer record carries none."""
    tokens = set(_tokenize(text))
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if tokens & keywords:
            return category
    return "skill"


def _detect_language(text: str) -> str | None:
    """Canonical language mentioned by a text (``None`` when there is none)."""
    tokens = set(_tokenize(text))
    for language, aliases in _LANGUAGES.items():
        if tokens & set(aliases):
            return language
    return None


# ──────────────────────────────────────────────────────────────────────
# Requirements
# ──────────────────────────────────────────────────────────────────────


def _parse_requirement_record(record: Any) -> _Requirement | None:
    """Normalize one requirement record (dict or string).

    A requirement is mandatory when the offer says so: an explicit
    ``mandatory`` flag wins, then the Mission 02 ``modality`` (``required`` is
    mandatory, ``preferred``/``contextual``/``unknown`` are not), and a
    record that says nothing about it is read as mandatory — a requirement
    nobody qualified is a requirement.
    """
    if isinstance(record, str):
        text = record.strip()
        if not text:
            return None
        return _Requirement(
            text=text,
            category=_detect_category(text),
            mandatory=True,
            negated=False,
        )
    if not isinstance(record, dict):
        return None
    text = str(record.get("text") or "").strip()
    if not text:
        return None
    category = str(record.get("category") or "").strip().lower()
    if not category:
        category = _detect_category(text)
    modality = str(record.get("modality") or "").strip().lower()
    if "mandatory" in record:
        mandatory = bool(record.get("mandatory"))
    elif modality:
        mandatory = modality == "required"
    else:
        mandatory = True
    return _Requirement(
        text=text,
        category=category,
        mandatory=mandatory,
        negated=bool(record.get("negated")),
        preferred=modality == "preferred",
    )


def _requirements_from_offer(offer: dict[str, Any]) -> list[_Requirement]:
    """Every requirement of an offer, in offer order.

    A requirement explicitly negated by the offer ("l'anglais n'est pas
    exigé") is not a requirement: it produces no action and does not enter
    the score.  Nothing is dropped silently — the count of considered
    requirements is always the number of actions returned.
    """
    raw = offer.get("requirements")
    records: list[Any]
    if isinstance(raw, list):
        records = list(raw)
    elif isinstance(raw, str) and raw.strip():
        records = [
            line.strip(" \t•-*–—")
            for line in raw.splitlines()
            if line.strip(" \t•-*–—")
        ]
    else:
        records = _extract_requirements_with_mission_02(offer)

    requirements: list[_Requirement] = []
    for record in records:
        parsed = _parse_requirement_record(record)
        if parsed is None or parsed.negated:
            continue
        requirements.append(parsed)
    return requirements


def _extract_requirements_with_mission_02(offer: dict[str, Any]) -> list[Any]:
    """Extract the requirements of a raw offer with the Mission 02 contract.

    Returns an empty list when Mission 02 is not importable or when the offer
    carries nothing to extract — the matching then reports "no requirement",
    never a guessed one.
    """
    if not any(
        key in offer
        for key in ("description_original", "languages_required", "eligibility_requirement")
    ):
        return []
    try:
        from ..offer_requirements import analyze_offer
    except Exception:  # pragma: no cover - optional dependency
        return []
    analysis = analyze_offer(offer)
    return list(analysis.get("requirements") or [])


# ──────────────────────────────────────────────────────────────────────
# Evidence
# ──────────────────────────────────────────────────────────────────────


def _source_text(cv_result: CVAnalysisResult, override: str | None = None) -> str:
    """The exact text of the analyzed CV (empty when unavailable)."""
    if override is not None:
        return override
    return getattr(cv_result.provenance, "source_text", None) or ""


def _field_at(cv_result: CVAnalysisResult, offset: int) -> str:
    """CV field holding the character at ``offset``."""
    for section in cv_result.sections:
        if section.start_offset <= offset < section.end_offset:
            return SECTION_FIELDS.get(section.title, _slug(section.title) or DOCUMENT_FIELD)
    experiences = cv_result.experiences
    for index, experience in enumerate(experiences):
        end = experiences[index + 1].source_offset if index + 1 < len(experiences) else offset + 1
        if experience.source_offset <= offset < end:
            return "experience"
    return DOCUMENT_FIELD


def _excerpt(source: str, start: int, end: int) -> tuple[str, int]:
    """Trim a source span, keeping it an exact substring of ``source``."""
    chunk = source[start:end]
    stripped = chunk.strip()
    if stripped:
        start += len(chunk) - len(chunk.lstrip())
        chunk = stripped
    return chunk, start


def _quote(source: str, core_start: int, core_end: int) -> tuple[str, int]:
    """Quote the fact that proves a requirement.

    The quote is the source line(s) holding the matched keywords — a fact is
    written on a line, and the line is what tells whether the proof carries
    a figure ("géré une équipe" vs "géré une équipe de 10 personnes").  The
    quote is always an exact substring of the source, and the returned offset
    is its exact position.
    """
    line_start = source.rfind("\n", 0, core_start) + 1
    line_end = source.find("\n", core_end)
    if line_end == -1:
        line_end = len(source)
    if line_end - line_start <= MAX_EVIDENCE_CHARS:
        return _excerpt(source, line_start, line_end)
    start = max(0, core_start - EXCERPT_LEAD)
    return _excerpt(source, start, min(len(source), start + MAX_EVIDENCE_CHARS))


def _collect_hits(folded_source: str, keywords: list[str]) -> list[_Hit]:
    """Every occurrence of every keyword (directly or through a synonym)."""
    hits: list[_Hit] = []
    for keyword in keywords:
        for offset in _word_positions(folded_source, keyword):
            hits.append(_Hit(offset=offset, length=len(keyword), keyword=keyword, synonym=False))
        for synonym in _synonyms_of(keyword):
            for offset in _word_positions(folded_source, synonym):
                hits.append(_Hit(offset=offset, length=len(synonym), keyword=keyword, synonym=True))
    hits.sort(key=lambda hit: (hit.offset, hit.keyword, hit.synonym))
    return hits


def _best_window(hits: list[_Hit], keyword_count: int) -> tuple[list[_Hit], float]:
    """Pick the window of hits proving the most keywords.

    Deterministic: the window with the most distinct keywords wins, then the
    one with the fewest synonym hits, then the earliest one.
    """
    best: list[_Hit] = []
    best_key: tuple[int, int, int] = (0, 0, 0)
    for anchor in hits:
        window = [
            hit
            for hit in hits
            if anchor.offset - KEYWORD_WINDOW <= hit.offset <= anchor.offset + KEYWORD_WINDOW
        ]
        distinct = len({hit.keyword for hit in window})
        synonyms = sum(1 for hit in window if hit.synonym)
        key = (distinct, -synonyms, -anchor.offset)
        if key > best_key:
            best_key = key
            best = window
    coverage = len({hit.keyword for hit in best}) / keyword_count if keyword_count else 0.0
    return best, coverage


def find_evidence_in_cv(
    cv_result: CVAnalysisResult,
    requirement: str,
    *,
    source_text: str | None = None,
) -> MatchEvidence | None:
    """Find the proof of a requirement inside the CV, or ``None``.

    The returned excerpt is always an exact substring of the CV source and
    its offset is its exact position in that source.  Nothing is invented:
    without the source text, no proof can be quoted.
    """
    source = _source_text(cv_result, source_text)
    if not source:
        return None
    keywords = extract_keywords(requirement)
    if not keywords:
        return None
    folded_source = _fold(source)

    # 0. A language: the line that proves the level is the one worth quoting.
    language = _detect_language(requirement)
    if language:
        span = _language_span_with_level(source, folded_source, language)
        if span is not None:
            excerpt, start = _quote(source, span[0], span[1])
            return MatchEvidence(
                text=excerpt,
                offset=start,
                field=_field_at(cv_result, span[0]),
                confidence=0.85,
                coverage=1.0,
            )

    # 1. The requirement is written the same way in the CV — strongest proof.
    phrase = " ".join(_tokenize(requirement))
    if phrase:
        phrase_positions = _word_positions(folded_source, phrase)
        if phrase_positions:
            offset = phrase_positions[0]
            excerpt, start = _quote(source, offset, offset + len(phrase))
            return MatchEvidence(
                text=excerpt,
                offset=start,
                field=_field_at(cv_result, offset),
                confidence=0.95,
                coverage=1.0,
            )

    # 2. The keywords of the requirement are somewhere in the CV.
    hits = _collect_hits(folded_source, keywords)
    if not hits:
        return None
    window, coverage = _best_window(hits, len(keywords))
    if not window:
        return None
    primary = min(window, key=lambda hit: (hit.synonym, hit.offset))
    core_start = min(hit.offset for hit in window)
    core_end = max(hit.offset + hit.length for hit in window)
    excerpt, start = _quote(source, core_start, core_end)

    direct = {hit.keyword for hit in window if not hit.synonym}
    if coverage >= 1.0 and len(direct) == len(keywords):
        confidence = 0.85
    elif coverage >= 1.0:
        confidence = 0.75
    elif coverage >= 0.5:
        confidence = 0.65
    else:
        confidence = 0.55
    return MatchEvidence(
        text=excerpt,
        offset=start,
        field=_field_at(cv_result, primary.offset),
        confidence=confidence,
        coverage=round(coverage, 2),
    )


# ──────────────────────────────────────────────────────────────────────
# Action decision
# ──────────────────────────────────────────────────────────────────────


def _language_level_proven(excerpt: str, language: str | None) -> bool:
    """True when the excerpt proves the level of a language, not only its name."""
    folded = _fold(excerpt)
    aliases = _LANGUAGES.get(language or "", ())
    for alias in aliases:
        for offset in _word_positions(folded, alias):
            line_start = folded.rfind("\n", 0, offset) + 1
            line_end = folded.find("\n", offset)
            if line_end == -1:
                line_end = len(folded)
            line = folded[line_start:line_end]
            if any(_contains_word(line, marker) for marker in _LANGUAGE_LEVEL_MARKERS):
                return True
    return False


def _language_span_with_level(source: str, folded_source: str, language: str) -> tuple[int, int] | None:
    """Span of the language mention whose line also proves the level.

    A CV often mentions the language twice: once in passing, once in the
    "Langues" section with the level.  The line that proves the level is the
    one worth quoting.
    """
    for alias in _LANGUAGES.get(language, ()):
        for offset in _word_positions(folded_source, alias):
            line_end = folded_source.find("\n", offset)
            if line_end == -1:
                line_end = len(folded_source)
            line = folded_source[offset:line_end]
            if any(_contains_word(line, marker) for marker in _LANGUAGE_LEVEL_MARKERS):
                return offset, offset + len(alias)
    return None


def _is_synonym_match(requirement: str, excerpt: str) -> bool:
    """True when the requirement's wording is only present through a synonym."""
    folded_excerpt = _fold(excerpt)
    for keyword in extract_keywords(requirement):
        if _contains_word(folded_excerpt, keyword):
            continue
        if any(_contains_word(folded_excerpt, synonym) for synonym in _synonyms_of(keyword)):
            return True
    return False


def _decide_action(
    requirement: _Requirement,
    evidence: MatchEvidence,
) -> tuple[MatchActionCode, str]:
    """Pick the action and its reason for a requirement backed by evidence."""
    language = _detect_language(requirement.text)
    if requirement.category == "language" or language:
        if not _language_level_proven(evidence.text, language):
            label = _LANGUAGE_LABELS.get(language or "", "la langue")
            return (
                "CONFIRM_LANGUAGE",
                f"La {label.lower()} est mentionnée dans le CV mais son niveau n'y est pas "
                f"prouvé : à confirmer avant de l'affirmer.",
            )
        if _is_synonym_match(requirement.text, evidence.text):
            return (
                "REPHRASE",
                f"Le fait existe dans le CV mais avec un autre vocabulaire. Reformuler avec "
                f"le vocabulaire de l'offre : « {requirement.text} ».",
            )
        return (
            "HIGHLIGHT",
            f"Le fait existe dans le CV (section « {evidence.field} »). Le rendre plus visible : "
            f"reprendre le mot-clé de l'offre « {requirement.text} » en haut de la section, en gras.",
        )

    if _QUANTITY_PATTERN.search(requirement.text) and not _DIGIT_PATTERN.search(evidence.text):
        return (
            "QUANTIFY",
            f"{QUANTIFY_REASON} L'exigence porte le chiffre « {requirement.text} ».",
        )

    if _is_synonym_match(requirement.text, evidence.text):
        return (
            "REPHRASE",
            f"Le fait existe dans le CV mais avec un autre vocabulaire. Reformuler avec "
            f"le vocabulaire de l'offre : « {requirement.text} ».",
        )

    return (
        "HIGHLIGHT",
        f"Le fait existe dans le CV (section « {evidence.field} »). Le rendre plus visible : "
        f"reprendre le mot-clé de l'offre « {requirement.text} » en haut de la section, en gras.",
    )


# ──────────────────────────────────────────────────────────────────────
# Cross-cutting warnings
# ──────────────────────────────────────────────────────────────────────


def _offer_contract_type(offer: dict[str, Any]) -> str:
    """Contract type of an offer (lowercase, free text)."""
    for key in ("contract_type", "contract", "type_of_contract"):
        value = offer.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _education_level(text: str) -> int | None:
    """Highest education level mentioned in a text (``None`` when unknown)."""
    folded = _fold(text)
    claimed: list[tuple[int, int]] = []
    level_found: int | None = None
    for marker, level in _EDUCATION_MARKERS:
        for offset in _word_positions(folded, marker):
            span = (offset, offset + len(marker))
            if any(span[0] < end and start < span[1] for start, end in claimed):
                continue
            claimed.append(span)
            if level_found is None or level > level_found:
                level_found = level
    return level_found


def _cv_education_level(cv_result: CVAnalysisResult, source: str) -> int | None:
    """Highest education level of the CV, read in the Formation section."""
    formation = next(
        (section for section in cv_result.sections if section.title == "Formation"),
        None,
    )
    if formation is not None and 0 <= formation.start_offset < formation.end_offset:
        chunk = source[formation.start_offset:formation.end_offset]
        level = _education_level(chunk)
        if level is not None:
            return level
    return _education_level(source)


def _offer_education_level(offer: dict[str, Any], requirements: list[_Requirement]) -> int | None:
    """Highest education level required by the offer."""
    level: int | None = None
    raw = offer.get("education_level")
    if isinstance(raw, int) and not isinstance(raw, bool):
        level = raw if 1 <= raw <= 6 else None
    elif isinstance(raw, str) and raw.strip():
        level = _education_level(raw)
    for requirement in requirements:
        if requirement.category != "education":
            continue
        required = _education_level(requirement.text)
        if required is not None and (level is None or required > level):
            level = required
    return level


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def match_cv_to_offer(
    cv_result: CVAnalysisResult,
    offer: dict[str, Any],
    *,
    source_text: str | None = None,
) -> MatchResult:
    """Match a CV against one offer and return one action per requirement.

    Pure and deterministic: the same CV and the same offer always return the
    same actions.  No network, no model, no clock.

    Args:
        cv_result: Analysis of the CV (Mission 01).
        offer: Offer dict holding the requirements (Mission 02 contract).
        source_text: Exact CV text, when the result does not carry it.  When
            neither is available, no proof can be quoted: every requirement is
            reported as ``DO_NOT_ADD`` and a warning says so.

    Returns:
        MatchResult with one action per requirement, the missing mandatory
        requirements and the cross-cutting warnings.
    """
    offer = offer or {}
    source = _source_text(cv_result, source_text)
    requirements = _requirements_from_offer(offer)

    actions: list[MatchAction] = []
    missing_critical: list[str] = []
    warnings: list[str] = []

    if not source:
        warnings.append(NO_SOURCE_WARNING)

    for requirement in requirements:
        evidence = find_evidence_in_cv(cv_result, requirement.text, source_text=source)
        if evidence is None:
            actions.append(
                MatchAction(
                    code="DO_NOT_ADD",
                    requirement_text=requirement.text,
                    cv_evidence_text=None,
                    cv_evidence_offset=None,
                    cv_evidence_field=None,
                    reason=DO_NOT_ADD_REASON,
                    confidence=1.0,
                )
            )
            if requirement.mandatory:
                missing_critical.append(requirement.text)
            language = _detect_language(requirement.text)
            if (requirement.category == "language" or language) and not requirement.preferred:
                label = _LANGUAGE_LABELS.get(language or "", requirement.text)
                warnings.append(f"Langue requise non prouvée dans le CV : {label}.")
            continue

        code, reason = _decide_action(requirement, evidence)
        actions.append(
            MatchAction(
                code=code,
                requirement_text=requirement.text,
                cv_evidence_text=evidence.text,
                cv_evidence_offset=evidence.offset,
                cv_evidence_field=evidence.field,
                reason=reason,
                confidence=evidence.confidence,
            )
        )

    contract_type = _offer_contract_type(offer)
    if contract_type in _ALTERNANCE_CONTRACTS:
        warnings.append(ALTERNANCE_WARNING)

    required_level = _offer_education_level(offer, requirements)
    cv_level = _cv_education_level(cv_result, source) if source else None
    if required_level is not None and cv_level is not None and required_level > cv_level:
        warnings.append(
            f"Niveau d'études requis ({_EDUCATION_LABELS.get(required_level, required_level)}) "
            f"> niveau du CV ({_EDUCATION_LABELS.get(cv_level, cv_level)})."
        )

    matched = sum(1 for action in actions if action.code != "DO_NOT_ADD")
    total = len(actions)
    overall_score = matched / total if total else 0.0

    return MatchResult(
        overall_score=overall_score,
        matched_requirements=matched,
        total_requirements=total,
        actions=actions,
        missing_critical=missing_critical,
        warnings=warnings,
    )
