"""Adversarial CV/offer matching (mission CVBOOST-08).

``match_cv_to_offer(cv_result, offer)`` is a **pure, deterministic, offline**
function: same inputs, same outputs, no clock, no randomness, no network, no
model.  It compares the requirements of one offer with the factual content of
one CV and returns an auditable plan:

* every action quotes a **verbatim substring** of the CV — never a paraphrase,
  never an invented sentence;
* a requirement with no proof in the CV yields ``DO_NOT_ADD``: what is absent
  is never added;
* the known lexical traps (Excel ≠ financial analysis, Java ≠ JavaScript, a
  programme taught in English ≠ an English level, a stage ≠ a permanent
  contract, M1 ≠ M2, a negated word, a sector homonym, an acronym, a
  multilingual profile) are detected instead of being matched by accident.

The engine never rewrites the product's business rules: it reads the
requirements through the CVBOOST-02 contract (``analyze_offer``) and only
produces a decision surface for the CV plan.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .models import CVAnalysisResult, MatchAction, MatchActionCode, MatchEvidence, MatchResult
from ..models import normalized_text
from ..offer_requirements.extract import analyze_offer

# ──────────────────────────────────────────────────────────────────────
# Normalisation — keeps a 1:1 map back to the original characters
# ──────────────────────────────────────────────────────────────────────

def _strip_accents(text: str) -> str:
    """Lowercase and drop the accents, one output character per input character."""
    out: list[str] = []
    for char in text:
        if char.isalpha() and ord(char) > 127:
            decomposed = unicodedata.normalize("NFKD", char)
            stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
            out.append(stripped.lower() if stripped else char)
        else:
            out.append(char.lower())
    return "".join(out)


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Return ``(normalized_text, index_map)``.

    ``index_map[i]`` is the offset of ``normalized_text[i]`` in ``text``.
    The normalization is length preserving (one normalized character per
    original character, except ``&`` which becomes ``" and "``), so a match
    found in the normalized text can be mapped back to an exact slice of the
    original text.
    """
    chars: list[str] = []
    index_map: list[int] = []
    for offset, char in enumerate(text):
        if char == "&":
            for expanded in " and ":
                chars.append(expanded)
                index_map.append(offset)
            continue
        lowered = _strip_accents(char)
        if len(lowered) != 1:
            lowered = " "
        chars.append(lowered if lowered.isalnum() else " ")
        index_map.append(offset)
    return "".join(chars), index_map


def _tokens(text: str) -> list[tuple[str, int, int]]:
    """Tokenize into ``(token, start_offset, end_offset)`` over the original text."""
    normalized, index_map = _normalize_with_map(text)
    tokens: list[tuple[str, int, int]] = []
    start = None
    for position, char in enumerate(normalized):
        if char.isalnum():
            if start is None:
                start = position
        elif start is not None:
            tokens.append((normalized[start:position], index_map[start], index_map[position - 1] + 1))
            start = None
    if start is not None:
        tokens.append((normalized[start:len(normalized)], index_map[start], index_map[len(normalized) - 1] + 1))
    return tokens


#: Words that carry no discriminating meaning when comparing an offer and a CV.
STOP_WORDS = frozenset(
    {
        "avec", "ans", "and", "au", "aux", "aout", "ce", "ces", "cette", "dans",
        "de", "des", "du", "elle", "en", "est", "et", "ils", "la", "le", "les",
        "leur", "plus", "ne", "nos", "notre", "ou", "par", "pas", "pour", "qui",
        "sa", "ses", "son", "sur", "the", "to", "tous", "toute", "toutes", "un",
        "une", "vos", "votre", "is", "are", "in", "of", "on", "for", "with",
        "will", "have", "has", "des", "candidat", "candidature", "profil",
    }
)


def _content_tokens(text: str) -> list[str]:
    """Significant tokens of a text, in order of appearance, without duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for token, _, _ in _tokens(text):
        if token in STOP_WORDS or len(token) < 3:
            continue
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def _token_matches(word: str, token: str) -> bool:
    """True when a token satisfies a keyword.

    A crude singular/plural tolerance is accepted for the long words only
    (``projet`` matches ``projets``) — it keeps the English and the French
    CVs comparable without letting a two-letter word match anything.
    """
    if token == word:
        return True
    return len(word) >= 4 and token == word + "s"


def _has_phrase(words: Sequence[str], tokens: Sequence[tuple[str, int, int]]) -> bool:
    """True when the words appear consecutively in the token stream."""
    if not words:
        return False
    count = len(words)
    for index in range(len(tokens) - count + 1):
        if all(_token_matches(words[offset], tokens[index + offset][0]) for offset in range(count)):
            return True
    return False


def _keyword_present(keyword: str, tokens: Sequence[tuple[str, int, int]]) -> bool:
    """True when a keyword (possibly several words) is present in the tokens."""
    words = keyword.split()
    if len(words) == 1:
        return any(token[0] == words[0] for token in tokens)
    return _has_phrase(words, tokens)


def _marker_present(marker: Sequence[str], tokens: Sequence[tuple[str, int, int]]) -> bool:
    """True when a marker sequence is present in the token stream."""
    return _has_phrase(marker, tokens)


# ──────────────────────────────────────────────────────────────────────
# Concepts — synonyms, families (rephrasing) and homonym groups
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class _Concept:
    """One skill concept and the token tuples that prove it.

    Attributes:
        id: Stable identifier of the concept.
        surfaces: Alternative token tuples.  A concept is proved when *one*
            tuple is fully present in the text (order free).
        family: Concepts of the same family describe the same domain with a
            different wording: finding one of them in the CV when another one
            is required is a *rephrasing*, never a proof.
        homonym: Group of concepts that share a word but not a meaning
            (``audit_financier`` vs ``audit_it``).
        strict_case: When true the token must appear uppercase in the source
            (protects the short acronyms ``PE``, ``IB``, ``R``).
        excluded_by: Phrases that cancel the proof when they follow the
            match (``tableaux de bord`` is not the ``Tableau`` tool).
    """

    id: str
    surfaces: tuple[tuple[str, ...], ...]
    family: str | None = None
    homonym: str | None = None
    strict_case: bool = False
    excluded_by: tuple[tuple[str, ...], ...] = ()


def _concept(
    id: str,
    surfaces: Iterable[Iterable[str]],
    family: str | None = None,
    homonym: str | None = None,
    strict_case: bool = False,
    excluded_by: Iterable[Iterable[str]] = (),
) -> _Concept:
    return _Concept(
        id=id,
        surfaces=tuple(tuple(surface) for surface in surfaces),
        family=family,
        homonym=homonym,
        strict_case=strict_case,
        excluded_by=tuple(tuple(phrase) for phrase in excluded_by),
    )


CONCEPTS: tuple[_Concept, ...] = (
    # Office and analysis
    _concept("excel", (("excel",), ("tableur",), ("spreadsheet",))),
    _concept("power_bi", (("power", "bi"),), homonym="bi"),
    _concept("tableau", (("tableau",),), homonym="bi", excluded_by=(("de", "bord"),)),
    _concept("analyse_financiere", (("analyse", "financiere"), ("analyse", "comptable"), ("financial", "analysis")), family="finance"),
    _concept("modelisation_financiere", (("modelisation", "financiere"), ("financial", "modeling")), family="finance"),
    _concept("finance_entreprise", (("finance", "entreprise"),), family="finance"),
    _concept("m&a", (("m", "and", "a"), ("fusion", "acquisition")), family="finance"),
    _concept("pe", (("pe",), ("private", "equity")), family="finance", strict_case=True),
    _concept("ib", (("ib",), ("investment", "banking")), family="finance", strict_case=True),
    # Programming languages
    _concept("java", (("java",),), homonym="java"),
    _concept("javascript", (("javascript",), ("node", "js")), homonym="java"),
    _concept("python", (("python",),)),
    _concept("r_stat", (("r",),), strict_case=True),
    _concept("sql", (("sql",),), homonym="bd"),
    _concept("nosql", (("nosql",), ("mongodb",), ("dynamodb",)), homonym="bd"),
    # Cloud and tools
    _concept("aws", (("aws",), ("amazon", "web", "services")), homonym="cloud"),
    _concept("azure", (("azure",),), homonym="cloud"),
    _concept("gcp", (("gcp",), ("google", "cloud")), homonym="cloud"),
    _concept("erp", (("erp",),), homonym="logiciel"),
    _concept("sap", (("sap",),), homonym="logiciel"),
    _concept("crm", (("crm",),), homonym="logiciel"),
    _concept("kpi", (("kpi",), ("indicateur", "cle", "performance"))),
    # Management
    _concept("gestion_equipe", (("gestion", "equipe"), ("management", "equipe"), ("encadrement", "equipe"), ("team", "management"), ("experience", "management"), ("gere", "equipe")), homonym="gestion"),
    _concept("gestion_projet", (("gestion", "projet"), ("chef", "projet"), ("pilotage", "projet")), homonym="gestion"),
    _concept("gestion_risque", (("gestion", "risques"), ("risk", "management")), homonym="risque"),
    _concept("risque_it", (("risque", "informatique"), ("cybersecurite"), ("ssi")), homonym="risque"),
    # Audit homonyms
    _concept("audit_financier", (("audit", "financier"), ("audit", "comptable"), ("audit", "comptes"), ("financial", "audit")), homonym="audit"),
    _concept("audit_it", (("audit", "it"), ("audit", "si"), ("audit", "informatique"), ("it", "audit"), ("audit", "systeme")), homonym="audit"),
    # Data
    _concept("data_analysis", (("data", "analysis"), ("analyse", "donnees"), ("data", "analyst")), homonym="data"),
    _concept("data_engineering", (("data", "engineering"), ("ingenieur", "data")), homonym="data"),
    _concept("machine_learning", (("machine", "learning"), ("deep", "learning"), ("apprentissage", "automatique")), homonym="data"),
)


# ──────────────────────────────────────────────────────────────────────
# Languages, education levels, contract types
# ──────────────────────────────────────────────────────────────────────

LANGUAGES: dict[str, tuple[str, ...]] = {
    "anglais": ("anglais", "english"),
    "francais": ("francais", "french"),
    "allemand": ("allemand", "german", "deutsch"),
    "espagnol": ("espagnol", "spanish"),
    "italien": ("italien", "italian"),
    "portugais": ("portugais", "portuguese"),
    "neerlandais": ("neerlandais", "dutch"),
    "mandarin": ("mandarin", "chinois"),
}

#: Level -> (keywords, rank), most specific first.  Higher rank is stronger.
LANGUAGE_LEVELS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("natif", ("natif", "native", "maternelle"), 5),
    ("courant", ("courant", "fluent", "c1", "c2", "bilingue", "bilingual", "maitrise"), 4),
    ("professionnel", ("professionnel", "professional", "b2", "avance"), 3),
    ("intermediaire", ("intermediaire", "b1", "intermediate"), 2),
    ("debutant", ("debutant", "a1", "a2", "beginner", "notions"), 1),
    ("lu", ("lu", "lecture", "read", "schriftlich"), 0),
)

#: Contexts where a language is mentioned without declaring a level.
LANGUAGE_PROGRAM_CONTEXTS: tuple[str, ...] = (
    "programme", "program", "cours", "formation", "enseignement", "taught",
    "soutenance", "intervention", "diplome", "etudes", "istudy", "universite",
    "master", "msc", "licence", "bachelor",
)

#: Same idea, applied to the *requirement* side: a programme taught in a
#: language is not a language requirement.
LANGUAGE_PROGRAM_CUES: tuple[str, ...] = (
    "programme", "program", "cours", "enseignement", "taught", "soutenance",
    "intervention", "formation",
)

#: Education level -> (keywords, rank), most specific first.
EDUCATION_LEVELS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("doctorat", ("doctorat", "phd", "these"), 5),
    ("bac+5", ("master 2", "m2", "msc", "mba", "grande ecole", "bac+5", "bac 5"), 4),
    ("bac+4", ("master 1", "m1", "maitrise", "licence professionnelle", "bac+4", "bac 4"), 3),
    ("bac+3", ("bachelor", "licence", "bac+3", "bac 3"), 2),
    ("bac+2", ("bts", "dut", "deust", "bac+2", "bac 2"), 1),
    # Generic fallback: a bare "master" is a Bac+5 unless a more precise
    # level has already been recognised above.
    ("bac+5", ("master",), 4),
)

#: Contract type -> keywords.
CONTRACT_TYPES: dict[str, tuple[str, ...]] = {
    "stage": ("stage", "stagiaire", "internship"),
    "alternance": ("alternance", "apprentissage", "apprenti"),
    "cdd": ("cdd", "contrat a duree determinee", "fixed term"),
    "cdi": ("cdi", "contrat a duree indeterminee", "permanent"),
    "vie": ("vie", "volontariat international"),
    "freelance": ("freelance", "independant", "auto entrepreneur"),
}

#: Words that introduce a declaration of intent in the CV.
DECLARATION_CUES: tuple[str, ...] = (
    "recherche", "objectif", "souhaite", "souhait", "contract", "disponibilite",
    "disponible", "cible", "veut", "pret", "looking", "searching", "target",
    "seeking", "statut", "poste",
)

#: Negation markers, expressed as token sequences.
NEGATION_MARKERS: tuple[tuple[str, ...], ...] = (
    ("pas", "de"),
    ("pas", "d"),
    ("sans",),
    ("aucun",),
    ("aucune",),
    ("exclu",),
    ("exclut",),
    ("ne", "pas"),
    ("n", "est", "pas"),
    ("not", "required"),
    ("not", "mandatory"),
    ("no", "need"),
    ("no", "experience"),
    ("interdit",),
)

#: Negation words that may precede the term they negate.
NEGATION_WORDS = frozenset({"pas", "sans", "aucun", "aucune", "exclu", "exclut", "non", "no", "interdit"})

#: Words that close a clause: the proof never goes past them.
CLAUSE_SEPARATORS = frozenset(
    {
        "et", "ou", "mais", "avec", "ainsi", "puis", "donc", "en", "pour",
        "dans", "sur", "par", "aussi", "dont", "selon", "car", "ni", "ni",
        "chez", "vers", "depuis", "pendant", "malgre", "hormis",
        # English conjunctions: a proof never crosses them either, so an
        # English CV yields the same tight evidence as a French one.
        "and", "or", "but", "with", "then", "also", "while", "whereas",
    }
)

#: How far a proof may be extended around the matched phrase.
MAX_EXTENSION = 40

#: Characters that close a clause.
CLAUSE_DELIMITERS = ",;:|!?("

#: Canonical reason carried by every ``DO_NOT_ADD`` action: what is absent
#: from the CV is never added to it.  The specific cause of the absence is
#: appended to this sentence, never replaces it.
NO_EVIDENCE_REASON = "Aucune preuve dans le CV, ne pas ajouter sans preuve"

#: Words of a requirement that ask for a quantified result.
QUANTIFICATION_CUES: tuple[str, ...] = (
    "equipe", "budget", "chiffre", "effectif", "encadrer", "diriger",
    "manager", "gestion d equipe", "chef d equipe",
)

#: Offer fields the CVBOOST-02 contract reads as structured requirements.
STRUCTURED_REQUIREMENT_FIELDS: tuple[str, ...] = (
    "requirements",
    "languages_required",
    "eligibility_requirement",
    "role_level",
)

#: A quantified result: a number with a unit or a counted noun.
QUANTIFIED_EVIDENCE = re.compile(
    r"(\d+\s*[%€$£])|(\d+\s*[kKmM]\s*[€$£])|(\d+\s*(?:ans?|mois|years?|months?))"
    r"|(x\d+)|(\d+\s*[a-z]{3,})"
    r"|((?:budget|chiffre|revenue|ca|effectif)\D{0,3}\d+)",
    re.IGNORECASE,
)

#: Two tokens further apart than this do not belong to the same phrase.
MAX_PHRASE_SPAN = 60


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _detect_language(text: str) -> tuple[str | None, str | None]:
    """Return ``(language, level)`` mentioned in a text."""
    tokens = _tokens(text)
    language: str | None = None
    for name, keywords in LANGUAGES.items():
        if any(_keyword_present(keyword, tokens) for keyword in keywords):
            language = name
            break
    level: str | None = None
    for name, keywords, _rank in LANGUAGE_LEVELS:
        if any(_keyword_present(keyword, tokens) for keyword in keywords):
            level = name
            break
    return language, level


def _detect_education_level(text: str) -> tuple[str | None, int]:
    """Return ``(level, rank)`` of the education level mentioned in a text."""
    tokens = _tokens(text)
    for name, keywords, rank in EDUCATION_LEVELS:
        if any(_keyword_present(keyword, tokens) for keyword in keywords):
            return name, rank
    return None, 0


def _detect_contract_type(text: str) -> str | None:
    """Return the contract type mentioned in a text."""
    tokens = _tokens(text)
    for name, keywords in CONTRACT_TYPES.items():
        if any(_keyword_present(keyword, tokens) for keyword in keywords):
            return name
    return None


def _is_negated(text: str) -> bool:
    """True when the requirement is a negated statement, not a requirement."""
    tokens = _tokens(text)
    return any(_marker_present(marker, tokens) for marker in NEGATION_MARKERS)


def _is_quantified(text: str) -> bool:
    """True when the text carries a number with a unit."""
    return bool(QUANTIFIED_EVIDENCE.search(text))


def _asks_for_numbers(text: str) -> bool:
    """True when the requirement asks for a quantified result.

    The cues are matched on whole words: ``manager`` does not answer to
    ``management``.  The mission's example — « expérience management » in the
    offer, « gère une équipe de 10 personnes » in the CV — must produce a
    QUANTIFY action, not a plain HIGHLIGHT.
    """
    tokens = _tokens(text)
    return any(_keyword_present(cue, tokens) for cue in QUANTIFICATION_CUES)


def _structured_lines(value: Any) -> list[str]:
    """Return the non-empty lines of a structured offer field."""
    if isinstance(value, str):
        raw_lines: list[Any] = value.splitlines()
    elif isinstance(value, (list, tuple)):
        raw_lines = list(value)
    else:
        return []
    lines: list[str] = []
    for raw in raw_lines:
        line = str(raw).strip().strip("•-–*▪●➤·‣◦ ").strip()
        if line:
            lines.append(line)
    return lines


def _unextracted_requirements(offer: Any, extracted: Sequence[str]) -> list[str]:
    """Return the structured requirement lines the contract did not extract.

    The contract (CVBOOST-02) ignores any statement shorter than four
    characters — ``SQL``, ``VBA``, ``M&A`` — and a requirement that never
    reaches the matcher cannot be covered.  The engine says so instead of
    letting the offer look fully handled.
    """
    if not isinstance(offer, dict):
        return []
    extracted_keys = [normalized_text(text) for text in extracted]
    missing: list[str] = []
    for field in STRUCTURED_REQUIREMENT_FIELDS:
        for line in _structured_lines(offer.get(field)):
            key = normalized_text(line)
            if not key:
                continue
            if any(
                key == other or key.startswith(other) or other.startswith(key)
                for other in extracted_keys
            ):
                continue
            missing.append(line)
    return missing


def _line_bounds(source: str, offset: int) -> tuple[int, int]:
    """Return the ``(start, end)`` offsets of the line holding ``offset``."""
    start = source.rfind("\n", 0, offset) + 1
    end = source.find("\n", offset)
    if end == -1:
        end = len(source)
    return start, end


def _line_tokens(
    tokens: Sequence[tuple[str, int, int]], source: str, offset: int
) -> list[tuple[str, int, int]]:
    """Return the tokens of the line holding ``offset``."""
    start, end = _line_bounds(source, offset)
    return [token for token in tokens if start <= token[1] and token[2] <= end]


def _span(positions: Sequence[tuple[str, int, int]]) -> tuple[int, int]:
    """Return the ``(start, end)`` offsets covering a set of tokens."""
    return min(position[1] for position in positions), max(position[2] for position in positions)


def _phrase_candidates(
    words: Sequence[str],
    tokens: Sequence[tuple[str, int, int]],
    source: str,
    strict_case: bool = False,
) -> list[list[tuple[str, int, int]]]:
    """Return every set of tokens that can prove ``words``.

    The tokens must belong to the same phrase: two occurrences of the same
    word in different parts of the CV never prove the same phrase.
    """
    candidates: list[list[tuple[str, int, int]]] = []
    for word in words:
        found = [
            token
            for token in tokens
            if _token_matches(word, token[0])
            and (not strict_case or source[token[1]:token[2]].isupper())
        ]
        if not found:
            return []
        candidates.append(found[:12])

    found_phrases: list[tuple[int, list[tuple[str, int, int]]]] = []
    for combination in itertools.product(*candidates):
        starts = [position[1] for position in combination]
        if starts != sorted(starts):
            continue
        length = combination[-1][2] - combination[0][1]
        if length > MAX_PHRASE_SPAN:
            continue
        found_phrases.append((length, list(combination)))
    found_phrases.sort(key=lambda item: item[0])
    return [phrase for _length, phrase in found_phrases]


def _phrase_positions(
    words: Sequence[str],
    tokens: Sequence[tuple[str, int, int]],
    source: str,
    strict_case: bool = False,
) -> list[tuple[str, int, int]] | None:
    """Return the tightest set of tokens proving ``words``, or ``None``."""
    phrases = _phrase_candidates(words, tokens, source, strict_case)
    return phrases[0] if phrases else None


def _resolve_concept(text: str) -> tuple[_Concept | None, tuple[str, ...] | None]:
    """Resolve the concept a requirement refers to.

    The biggest surface wins, so ``Analyse financière`` resolves to the
    financial-analysis concept and not to a bare ``finance`` concept.  Every
    token is considered, including the short ones (``R``, ``PE``, ``M&A``).
    """
    tokens = [token for token, _, _ in _tokens(text)]
    if not tokens:
        return None, None
    token_set = set(tokens)
    best: tuple[_Concept | None, tuple[str, ...] | None, int] = (None, None, 0)
    for concept in CONCEPTS:
        for surface in concept.surfaces:
            if len(surface) <= best[2]:
                continue
            if all(any(_token_matches(word, token) for token in token_set) for word in surface):
                best = (concept, surface, len(surface))
    return best[0], best[1]


def _is_excluded(
    concept: _Concept,
    positions: Sequence[tuple[str, int, int]],
    tokens: Sequence[tuple[str, int, int]],
    source: str,
) -> bool:
    """True when a phrase following the match cancels the proof."""
    if not concept.excluded_by:
        return False
    line = _line_tokens(tokens, source, positions[0][1])
    line_words = [word for word, _, _ in line]
    matched = {position[1] for position in positions}
    for index, (word, token_start, _token_end) in enumerate(line):
        if token_start not in matched:
            continue
        following = line_words[index + 1: index + 1 + 2]
        for phrase in concept.excluded_by:
            if len(following) >= len(phrase) and all(
                _token_matches(phrase[position], following[position])
                for position in range(len(phrase))
            ):
                return True
    return False


def _find_concept_evidence(
    concept: _Concept,
    tokens: Sequence[tuple[str, int, int]],
    source: str,
    prefer: set[str] | None = None,
) -> list[tuple[str, int, int]] | None:
    """Find the CV tokens proving a concept.

    When the concept appears several times, the occurrence that shares its
    line with the other words of the requirement wins: the proof must be the
    one that answers the offer, not the first one in the document.
    """
    best: list[tuple[str, int, int]] | None = None
    best_key: tuple[int, int] | None = None
    for surface in concept.surfaces:
        # Only the short acronyms insist on the uppercase ("PE"), never their
        # written form ("Private Equity").
        strict = concept.strict_case and len(surface) == 1 and len(surface[0]) <= 2
        for combination in _phrase_candidates(surface, tokens, source, strict):
            if _is_excluded(concept, combination, tokens, source):
                continue
            line = _line_tokens(tokens, source, combination[0][1])
            line_words = {word for word, _, _ in line}
            overlap = (
                sum(
                    1
                    for word in prefer
                    if any(_token_matches(word, line_word) for line_word in line_words)
                )
                if prefer
                else 0
            )
            length = combination[-1][2] - combination[0][1]
            key = (overlap, -length)
            if best_key is None or key > best_key:
                best_key = key
                best = combination
    return best


def _clause_bounds(source: str, start: int, end: int) -> tuple[int, int]:
    """Return the bounds of the clause holding a span.

    A clause ends on a punctuation mark or on the ``|`` that separates the
    fields of a job title: the proof never leaves it.
    """
    line_start, line_end = _line_bounds(source, start)
    clause_start = line_start
    for index in range(start - 1, line_start - 1, -1):
        if source[index] in CLAUSE_DELIMITERS:
            clause_start = index + 1
            break
    clause_end = line_end
    for index in range(end, line_end):
        if source[index] in CLAUSE_DELIMITERS:
            clause_end = index
            break
    return clause_start, clause_end


def _extend_span(
    span: tuple[int, int],
    tokens: Sequence[tuple[str, int, int]],
    allowed: set[str],
    source: str,
) -> tuple[int, int]:
    """Extend a proof over the phrase that surrounds it.

    The extension never crosses a clause separator (``et``, ``ou``, ``en``…)
    and never leaves the clause: the proof stays one excerpt of the CV, not a
    paragraph and not a whole job title.
    """
    start, end = span
    clause_start, clause_end = _clause_bounds(source, start, end)
    clause_tokens = sorted(
        (token for token in tokens if clause_start <= token[1] and token[2] <= clause_end),
        key=lambda token: token[1],
    )
    for token, token_start, token_end in clause_tokens:
        if token_start >= end:
            if token in CLAUSE_SEPARATORS or token_start - end > MAX_EXTENSION:
                break
            end = token_end
    for token, token_start, token_end in reversed(clause_tokens):
        if token_end <= start:
            if token in CLAUSE_SEPARATORS or start - token_end > MAX_EXTENSION:
                break
            start = token_start
    return start, end


def _tightest_cluster(
    matched: Sequence[tuple[str, int, int]], source: str
) -> list[tuple[str, int, int]]:
    """Keep the matched tokens that are close to each other.

    Two words separated by a line break do not prove each other: the proof
    stays local to the CV.
    """
    if not matched:
        return []
    clusters: list[list[tuple[str, int, int]]] = [[matched[0]]]
    for token in matched[1:]:
        previous = clusters[-1][-1]
        same_line = _line_bounds(source, previous[1]) == _line_bounds(source, token[1])
        if same_line and token[1] - previous[2] <= 40:
            clusters[-1].append(token)
        else:
            clusters.append([token])
    return max(clusters, key=lambda cluster: (len(cluster), -(cluster[-1][2] - cluster[0][1])))


def _declared_contract(cv_text: str) -> tuple[str | None, set[str], tuple[int, int] | None]:
    """Return the contract type declared by the CV, the excluded ones and the proof.

    ``je recherche un CDI, pas d'alternance`` declares ``cdi`` and excludes
    ``alternance``: the two are kept apart, an excluded type never shadows a
    declared one.  The proof is the verbatim span of the declaration.
    """
    tokens = _tokens(cv_text)
    declared: str | None = None
    excluded: set[str] = set()
    proof: tuple[int, int] | None = None
    for token in tokens:
        contract = _detect_contract_type(token[0])
        if contract is None:
            continue
        line = _line_tokens(tokens, cv_text, token[1])
        line_words = [word for word, _, _ in line]
        if token[0] not in line_words:
            continue
        position = line_words.index(token[0])
        preceding = line_words[:position][-4:]
        if any(word in NEGATION_WORDS for word in preceding):
            excluded.add(contract)
            continue
        if any(cue in line_words for cue in DECLARATION_CUES):
            declared = contract
            proof = (token[1], token[2])
    return declared, excluded, proof


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def _section_header_spans(source: str, cv_result: CVAnalysisResult) -> list[tuple[int, int]]:
    """Return the spans of the CV section headers.

    ``EXPERIENCE``, ``FORMATION``, ``LANGUES``… are the structure of the
    document, not a competence: they never prove a requirement.
    """
    spans: list[tuple[int, int]] = []
    for section in getattr(cv_result, "sections", []) or []:
        start = getattr(section, "start_offset", -1)
        if start < 0 or start >= len(source):
            continue
        end = source.find("\n", start)
        if end == -1:
            end = len(source)
        spans.append((start, end))
    return spans


def match_cv_to_offer(
    cv_result: CVAnalysisResult,
    offer: dict[str, Any],
    *,
    cv_text: str | None = None,
) -> MatchResult:
    """Match one CV against the requirements of one offer.

    Pure, deterministic and offline: no network, no model, no clock.

    Args:
        cv_result: Result of :func:`career.cv_quality.analyze_cv`.  The
            analysed text is used to quote verbatim evidence; when the result
            carries no text the engine says so instead of inventing a proof.
        offer: Offer mapping.  The requirements are read through the
            CVBOOST-02 contract (``analyze_offer``).
        cv_text: Optional explicit override of the analysed text.

    Returns:
        A :class:`MatchResult` with one action per requirement, the weighted
        score, the mandatory requirements without proof and the warnings.
    """
    source = cv_text if cv_text is not None else getattr(cv_result, "text", "")
    warnings: list[str] = []
    actions: list[MatchAction] = []

    analysis = analyze_offer(offer)
    requirements = list(analysis.get("requirements", []))

    for missing in _unextracted_requirements(offer, [r["text"] for r in requirements]):
        warnings.append(
            f"Exigence non extraite par le contrat d'exigences : « {missing} » — "
            "elle ne peut pas être couverte (texte trop court pour le contrat ?)."
        )

    if not source.strip():
        warnings.append("Texte du CV indisponible : aucune preuve ne peut être citée.")
        for requirement in requirements:
            actions.append(
                MatchAction(
                    code="DO_NOT_ADD",
                    requirement_text=requirement["text"],
                    cv_evidence_text=None,
                    cv_evidence_offset=None,
                    reason=NO_EVIDENCE_REASON,
                    confidence=0.0,
                )
            )
        return MatchResult(
            overall_score=0.0,
            matched_requirements=0,
            total_requirements=len(requirements),
            actions=actions,
            missing_critical=[
                requirement["text"]
                for requirement in requirements
                if requirement.get("modality") == "required"
            ],
            warnings=warnings,
        )

    tokens = _tokens(source)
    header_spans = _section_header_spans(source, cv_result)
    if header_spans:
        tokens = [
            token
            for token in tokens
            if not any(start <= token[1] and token[2] <= end for start, end in header_spans)
        ]
    answered: list[tuple[MatchAction, dict[str, Any]]] = []

    for requirement in requirements:
        requirement_text = requirement["text"]
        modality = requirement.get("modality", "unknown")
        category = requirement.get("category", "other")

        # ── A negated statement is not a requirement ──────────────────
        if requirement.get("negated") or _is_negated(requirement_text):
            warnings.append(
                f"Exigence niée dans l'offre : « {requirement_text} » — elle n'est pas une exigence à couvrir."
            )
            continue

        action = _match_requirement(
            requirement_text=requirement_text,
            modality=modality,
            category=category,
            source=source,
            tokens=tokens,
            warnings=warnings,
        )
        actions.append(action)
        answered.append((action, requirement))

    weights = {"required": 1.0, "preferred": 0.5, "contextual": 0.3, "unknown": 0.3}
    weighted_total = 0.0
    weighted_matched = 0.0
    for action, requirement in answered:
        weight = weights.get(requirement.get("modality", "unknown"), 0.3)
        weighted_total += weight
        if action.code != "DO_NOT_ADD":
            weighted_matched += weight
    overall_score = round(min(1.0, weighted_matched / weighted_total), 3) if weighted_total else 0.0

    missing_critical = [
        action.requirement_text
        for action, requirement in answered
        if action.code == "DO_NOT_ADD" and requirement.get("modality") == "required"
    ]

    return MatchResult(
        overall_score=overall_score,
        matched_requirements=sum(1 for action in actions if action.code != "DO_NOT_ADD"),
        total_requirements=len(actions),
        actions=actions,
        missing_critical=missing_critical,
        warnings=_dedupe(warnings),
    )


def _dedupe(items: list[str]) -> list[str]:
    """Remove the duplicates while keeping the order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _is_program_requirement(text: str) -> bool:
    """True when the requirement talks about a programme, not about a level.

    ``Programme en anglais`` describes a course taught in English; it is not
    a requirement on the candidate's English level.
    """
    tokens = _tokens(text)
    words = [word for word, _, _ in tokens]
    for index, word in enumerate(words):
        if word not in LANGUAGES.get("anglais", ()) and not any(
            word in keywords for keywords in LANGUAGES.values()
        ):
            continue
        preceding = words[max(0, index - 3): index]
        if any(cue in preceding for cue in LANGUAGE_PROGRAM_CUES):
            return True
    return False


def _match_requirement(
    *,
    requirement_text: str,
    modality: str,
    category: str,
    source: str,
    tokens: list[tuple[str, int, int]],
    warnings: list[str],
) -> MatchAction:
    """Match one requirement against the CV and build its action."""
    # ── Language requirement ─────────────────────────────────────────
    language, required_level = _detect_language(requirement_text)
    if language is not None and (category == "language" or required_level is not None):
        if not _is_program_requirement(requirement_text):
            return _match_language(
                requirement_text=requirement_text,
                language=language,
                required_level=required_level,
                source=source,
                tokens=tokens,
                warnings=warnings,
            )

    # ── Education requirement ────────────────────────────────────────
    if category == "education" or _detect_education_level(requirement_text)[0] is not None:
        return _match_education(
            requirement_text=requirement_text,
            source=source,
            tokens=tokens,
            warnings=warnings,
        )

    # ── Contract requirement ─────────────────────────────────────────
    contract = _detect_contract_type(requirement_text)
    if contract is not None and len(_content_tokens(requirement_text)) <= 3:
        return _match_contract(
            requirement_text=requirement_text,
            contract=contract,
            source=source,
            tokens=tokens,
            warnings=warnings,
        )

    # ── Skill requirement ────────────────────────────────────────────
    return _match_skill(
        requirement_text=requirement_text,
        source=source,
        tokens=tokens,
        warnings=warnings,
    )


def _match_language(
    *,
    requirement_text: str,
    language: str,
    required_level: str | None,
    source: str,
    tokens: list[tuple[str, int, int]],
    warnings: list[str],
) -> MatchAction:
    """Match a language requirement (declared level vs taught programme)."""
    keywords = LANGUAGES[language]
    occurrences = [token for token in tokens if token[0] in keywords]
    if not occurrences:
        warnings.append(f"Langue « {language} » absente du CV.")
        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=f"{NO_EVIDENCE_REASON} : la langue {language} n'y est pas mentionnée",
            confidence=0.9,
        )

    usable: list[tuple[str, int, int]] = []
    for token in occurrences:
        line = _line_tokens(tokens, source, token[1])
        line_words = [word for word, _, _ in line]
        if any(cue in line_words for cue in LANGUAGE_PROGRAM_CONTEXTS):
            continue
        usable.append(token)

    if not usable:
        warnings.append(
            f"« {language.capitalize()} » n'apparaît que dans un contexte d'enseignement "
            f"(programme en {language}) : aucun niveau de langue n'est déclaré."
        )
        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=(
                f"{NO_EVIDENCE_REASON} : la langue {language} est mentionnée dans un contexte "
                "d'enseignement, pas comme niveau déclaré"
            ),
            confidence=0.85,
        )

    evidence_token = usable[0]

    # The declared level is read on the same line, close to the language.
    line = _line_tokens(tokens, source, evidence_token[1])
    line_words = [word for word, _, _ in line]
    position = line_words.index(evidence_token[0])
    neighbourhood = line_words[max(0, position - 2): position + 3]
    declared_level = None
    level_token = None
    for name, level_keywords, _rank in LANGUAGE_LEVELS:
        for keyword in level_keywords:
            if keyword not in neighbourhood:
                continue
            for candidate in line:
                if candidate[0] == keyword:
                    level_token = candidate
                    break
            declared_level = name
            break
        if declared_level:
            break

    # The evidence quotes the declared level when it stands next to the language.
    evidence_start = evidence_token[1]
    evidence_end = evidence_token[2]
    if level_token is not None:
        evidence_start = min(evidence_start, level_token[1])
        evidence_end = max(evidence_end, level_token[2])
    evidence_text = source[evidence_start:evidence_end]

    if required_level is None:
        code: MatchActionCode = "HIGHLIGHT"
        reason = f"Langue {language} déclarée dans le CV"
        confidence = 0.9
    elif declared_level is None:
        code = "CONFIRM_LANGUAGE"
        reason = (
            f"La langue {language} est présente mais le niveau exigé ({required_level}) "
            "n'est pas précisé dans le CV : à confirmer"
        )
        confidence = 0.8
        warnings.append(f"Niveau de langue {required_level} non précisé dans le CV.")
    else:
        required_rank = next(rank for name, _kw, rank in LANGUAGE_LEVELS if name == required_level)
        declared_rank = next(rank for name, _kw, rank in LANGUAGE_LEVELS if name == declared_level)
        if declared_rank >= required_rank:
            code = "HIGHLIGHT"
            reason = f"Niveau de langue {declared_level} conforme à l'exigence {required_level}"
            confidence = 0.9
        else:
            warnings.append(
                f"Niveau de langue insuffisant : {declared_level} déclaré, {required_level} exigé."
            )
            return MatchAction(
                code="DO_NOT_ADD",
                requirement_text=requirement_text,
                cv_evidence_text=None,
                cv_evidence_offset=None,
                reason=(
                    f"{NO_EVIDENCE_REASON} : le CV ne prouve pas le niveau de langue exigé "
                    f"({declared_level} déclaré, {required_level} exigé)"
                ),
                confidence=0.85,
            )

    return MatchAction(
        code=code,
        requirement_text=requirement_text,
        cv_evidence_text=evidence_text,
        cv_evidence_offset=evidence_start,
        reason=reason,
        confidence=confidence,
        evidence=MatchEvidence(
            text=evidence_text,
            offset=evidence_start,
            kind="language",
            field=language,
        ),
    )


def _match_education(
    *,
    requirement_text: str,
    source: str,
    tokens: list[tuple[str, int, int]],
    warnings: list[str],
) -> MatchAction:
    """Match an education requirement with an exact level."""
    required_level, required_rank = _detect_education_level(requirement_text)
    if required_level is None:
        return _match_skill(
            requirement_text=requirement_text,
            source=source,
            tokens=tokens,
            warnings=warnings,
        )

    cv_level, cv_rank = _detect_education_level(source)
    if cv_level is None:
        warnings.append(f"Niveau d'études ({required_level}) non attesté dans le CV.")
        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=f"{NO_EVIDENCE_REASON} : le niveau d'études {required_level} n'est pas attesté",
            confidence=0.8,
        )

    if cv_rank >= required_rank:
        evidence_text = None
        offset = None
        for name, keywords, _rank in EDUCATION_LEVELS:
            if name != cv_level:
                continue
            for keyword in keywords:
                positions = _phrase_positions(
                    keyword.split(), tokens, source
                ) if " " in keyword else [
                    token for token in tokens if token[0] == keyword
                ]
                if not positions:
                    continue
                span = _span(positions)
                evidence_text = source[span[0]: span[1]]
                offset = span[0]
                break
            if evidence_text:
                break
        return MatchAction(
            code="HIGHLIGHT",
            requirement_text=requirement_text,
            cv_evidence_text=evidence_text,
            cv_evidence_offset=offset,
            reason=f"Niveau d'études {cv_level} conforme à l'exigence {required_level}",
            confidence=0.85,
            evidence=MatchEvidence(
                text=evidence_text or "",
                offset=offset or 0,
                kind="education",
                field=cv_level,
            ),
        )

    warnings.append(
        f"Niveau d'études insuffisant : {cv_level} dans le CV, {required_level} exigé."
    )
    return MatchAction(
        code="DO_NOT_ADD",
        requirement_text=requirement_text,
        cv_evidence_text=None,
        cv_evidence_offset=None,
        reason=(
            f"{NO_EVIDENCE_REASON} : le CV ne prouve pas le niveau d'études exigé "
            f"({cv_level} détenu, {required_level} exigé)"
        ),
        confidence=0.9,
    )


def _match_contract(
    *,
    requirement_text: str,
    contract: str,
    source: str,
    tokens: list[tuple[str, int, int]],
    warnings: list[str],
) -> MatchAction:
    """Match a contract type requirement (stage ≠ CDI, alternance exclue…)."""
    declared, excluded, proof = _declared_contract(source)
    if contract in excluded:
        warnings.append(
            f"Le CV exclut explicitement le contrat « {contract} » : l'offre ne correspond pas au brief."
        )
        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=f"{NO_EVIDENCE_REASON} : le CV exclut explicitement le contrat « {contract} »",
            confidence=0.9,
        )
    if declared is None:
        warnings.append(f"Type de contrat « {contract} » non déclaré dans le CV.")
        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=f"{NO_EVIDENCE_REASON} : le type de contrat « {contract} » n'est pas déclaré",
            confidence=0.8,
        )
    if declared != contract:
        warnings.append(
            f"Type de contrat incompatible : le CV vise « {declared} », l'offre propose « {contract} »."
        )
        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=(
                f"{NO_EVIDENCE_REASON} : type de contrat incompatible "
                f"(CV « {declared} », offre « {contract} »)"
            ),
            confidence=0.9,
        )
    evidence_text = source[proof[0]: proof[1]] if proof else None
    return MatchAction(
        code="HIGHLIGHT",
        requirement_text=requirement_text,
        cv_evidence_text=evidence_text,
        cv_evidence_offset=proof[0] if proof else None,
        reason=f"Le CV déclare le contrat « {declared} », conforme à l'offre",
        confidence=0.85,
        evidence=MatchEvidence(
            text=evidence_text or "",
            offset=proof[0] if proof else 0,
            kind="contract",
            field=declared,
        ),
    )


def _match_skill(
    *,
    requirement_text: str,
    source: str,
    tokens: list[tuple[str, int, int]],
    warnings: list[str],
) -> MatchAction:
    """Match a skill requirement (concepts, families, homonyms)."""
    content = _content_tokens(requirement_text)
    if _is_program_requirement(requirement_text):
        # "Programme en anglais" describes a course, not a level: the words
        # naming a language prove nothing here.
        language_words = {
            word for keywords in LANGUAGES.values() for word in keywords
        }
        content = [word for word in content if word not in language_words]
    concept, surface = _resolve_concept(requirement_text)

    if concept is not None and surface is not None:
        positions = _find_concept_evidence(concept, tokens, source, prefer=set(content))
        if positions is not None:
            span = _span(positions)
            span = _extend_span(span, tokens, set(content) | set(surface), source)
            return _skill_action(
                requirement_text=requirement_text,
                evidence_text=source[span[0]: span[1]],
                offset=span[0],
            )

        # Same family, different wording: a faithful rephrasing, never a proof.
        if concept.family:
            for sibling in CONCEPTS:
                if sibling.family != concept.family or sibling.id == concept.id:
                    continue
                sibling_positions = _find_concept_evidence(
                    sibling, tokens, source, prefer=set(content)
                )
                if sibling_positions is None:
                    continue
                span = _span(sibling_positions)
                evidence_text = source[span[0]: span[1]]
                return MatchAction(
                    code="REPHRASE",
                    requirement_text=requirement_text,
                    cv_evidence_text=evidence_text,
                    cv_evidence_offset=span[0],
                    reason=(
                        f"Le CV prouve « {sibling.id} », pas « {concept.id} » : "
                        "reformuler fidèlement avec la preuve du CV"
                    ),
                    confidence=0.75,
                    evidence=MatchEvidence(
                        text=evidence_text,
                        offset=span[0],
                        kind="skill",
                        field=sibling.id,
                    ),
                )

        homonym = _homonym_conflict(concept, tokens, source)
        if homonym is not None:
            warnings.append(
                f"Homonyme sectoriel : le CV prouve « {homonym} », pas « {concept.id} »."
            )
            return MatchAction(
                code="DO_NOT_ADD",
                requirement_text=requirement_text,
                cv_evidence_text=None,
                cv_evidence_offset=None,
                reason=(
                f"{NO_EVIDENCE_REASON} : homonyme détecté "
                f"(le CV mentionne « {homonym} », pas « {concept.id} »)"
            ),
                confidence=0.85,
            )

        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=NO_EVIDENCE_REASON,
            confidence=0.95,
        )

    # ── Generic requirement: token comparison ────────────────────────
    if not content:
        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=NO_EVIDENCE_REASON,
            confidence=0.9,
        )

    content_set = set(content)
    matched_tokens = [token for token in tokens if token[0] in content_set]
    if not matched_tokens:
        return MatchAction(
            code="DO_NOT_ADD",
            requirement_text=requirement_text,
            cv_evidence_text=None,
            cv_evidence_offset=None,
            reason=NO_EVIDENCE_REASON,
            confidence=0.95,
        )

    # The ratio is measured on the best *local* group of matched tokens: two
    # words found in two different places do not prove each other.
    cluster = _tightest_cluster(matched_tokens, source)
    matched_words = {token[0] for token in cluster}
    ratio = len(matched_words) / len(content)

    if ratio == 1.0:
        span = _extend_span(_span(cluster), tokens, content_set, source)
        return _skill_action(
            requirement_text=requirement_text,
            evidence_text=source[span[0]: span[1]],
            offset=span[0],
        )

    if ratio >= 0.5:
        span = _span(cluster)
        evidence_text = source[span[0]: span[1]]
        return MatchAction(
            code="REPHRASE",
            requirement_text=requirement_text,
            cv_evidence_text=evidence_text,
            cv_evidence_offset=span[0],
            reason=(
                "Preuve partielle dans le CV : reformuler avec la preuve exacte "
                "plutôt qu'avec le vocabulaire de l'offre"
            ),
            confidence=0.6,
            evidence=MatchEvidence(text=evidence_text, offset=span[0], kind="skill"),
        )

    return MatchAction(
        code="DO_NOT_ADD",
        requirement_text=requirement_text,
        cv_evidence_text=None,
        cv_evidence_offset=None,
        reason=NO_EVIDENCE_REASON,
        confidence=0.95,
    )


def _skill_action(
    *,
    requirement_text: str,
    evidence_text: str,
    offset: int,
) -> MatchAction:
    """Build the action of a proved skill (HIGHLIGHT or QUANTIFY)."""
    asks_for_numbers = _asks_for_numbers(requirement_text)
    has_numbers = _is_quantified(evidence_text)

    if asks_for_numbers and not has_numbers:
        return MatchAction(
            code="QUANTIFY",
            requirement_text=requirement_text,
            cv_evidence_text=evidence_text,
            cv_evidence_offset=offset,
            reason="Preuve trouvée mais non chiffrée : quantifier le résultat",
            confidence=0.8,
            evidence=MatchEvidence(text=evidence_text, offset=offset, kind="skill"),
        )
    if has_numbers and not asks_for_numbers:
        return MatchAction(
            code="QUANTIFY",
            requirement_text=requirement_text,
            cv_evidence_text=evidence_text,
            cv_evidence_offset=offset,
            reason="Le CV contient un chiffre : le reprendre explicitement dans la preuve",
            confidence=0.75,
            evidence=MatchEvidence(text=evidence_text, offset=offset, kind="skill"),
        )
    return MatchAction(
        code="HIGHLIGHT",
        requirement_text=requirement_text,
        cv_evidence_text=evidence_text,
        cv_evidence_offset=offset,
        reason="Preuve verbatim trouvée dans le CV",
        confidence=0.9,
        evidence=MatchEvidence(text=evidence_text, offset=offset, kind="skill"),
    )


def _homonym_conflict(
    concept: _Concept,
    tokens: list[tuple[str, int, int]],
    source: str,
) -> str | None:
    """Return the id of a homonymous concept proved by the CV, if any."""
    if concept.homonym is None:
        return None
    for sibling in CONCEPTS:
        if sibling.homonym != concept.homonym or sibling.id == concept.id:
            continue
        if _find_concept_evidence(sibling, tokens, source) is not None:
            return sibling.id
    return None


__all__ = ["match_cv_to_offer"]
