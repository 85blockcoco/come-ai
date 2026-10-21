"""Multi-source job deduplication with proof retention (SPEC-SK-06).

The same internship offer is published on several public boards (Greenhouse,
Ashby, Lever, Welcome to the Jungle, JobTeaser, Talent.com, APEC) and on the
employer career page.  This module merges those true duplicates **without ever
fusing two different roles**, and it keeps every proof of the merge:

* every provenance of a merged offer stays consultable (``provenances``);
* every contradiction between the merged records stays visible (``conflicts``);
* the official source stays the primary one (``source_trust`` drives the
  election of the representative);
* the user relevance score never takes part in the decision;
* a shared link never merges two different roles (a careers landing page
  hosts several postings).

Everything here is pure, local and deterministic: no network call, no model,
no external dependency, no hidden state, no clock.  The same input always
produces the same output and the received dictionaries are never modified.

Rapprochement rules, applied in this order:

1. external identifier published by the connector (``external_id``);
2. canonical URL (official link, then application link);
3. canonical company (normalised name, legal suffixes, known aliases);
4. canonical title (lower-case, stopwords, synonyms, business concept);
5. canonical location (city, region, country, remote);
6. dates (publication, start, freshness);
7. text similarity (Jaro-Winkler >= 0.92, optional embedding hook);
8. translations (the same offer written in French and in English);
9. company aliases (Acme Corp = Acme Inc.).

This module consolidates the two existing implementations found in the
repository (CVBOOST-07: ``career/cv_quality/job_deduplication.py`` and the
unmerged work-in-progress ``career/job_deduplication.py``) and keeps the
strongest part of each: the title model, the blocking keys and the audit
report of the first, the pair-level decision, the provenance model, the
conflict detection and the precision/recall evaluation of the second.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence

#: A job record is the plain dictionary produced by the connectors.
Job = dict[str, Any]

#: Minimum title similarity (Jaro-Winkler) to consider two offers identical.
TITLE_SIMILARITY_THRESHOLD = 0.92

#: Similarity granted to two titles mapped to the same business concept
#: ("Data Analyst" and "Analyste de données" describe the same job).
CONCEPT_MATCH_SIMILARITY = 0.95

#: Similarity ceiling applied when two titles describe incompatible roles
#: (a stage and a permanent analyst role are never the same offer).
ROLE_CONFLICT_SIMILARITY = 0.5

#: Minimum ratio between the lengths of two titles for a Jaro-Winkler score
#: of 0.92 to be reachable at all (derived from the Jaro upper bound).
MIN_LENGTH_RATIO = 0.76

#: Key of the traceability field carried by a deduplicated offer.
MERGED_FROM_FIELD = "merged_from"

#: Key of the detailed traceability field carried by a deduplicated offer:
#: one entry per source of the offer, so that a secondary source stays
#: consultable (its link, its identifier and its trust) from the offer
#: itself.
MERGED_PROVENANCES_FIELD = "merged_provenances"

#: Trust statuses published by SPEC-SK-01 (``career.source_trust``).
TRUST_STATUSES: tuple[str, ...] = ("verified", "unverified", "contradictory", "missing")

#: Rank of a trust status when the representative of a group is elected.
#: A verified official source always wins, a contradictory one never does.
TRUST_RANK: dict[str, int] = {
    "verified": 3,
    "unverified": 2,
    "missing": 1,
    "contradictory": 0,
}

#: Fields that carry a user-side relevance judgement.  They are read by the
#: search and never by the deduplication: the relevance of an offer for one
#: person says nothing about whether two records describe the same posting.
USER_SCORE_FIELDS: frozenset[str] = frozenset({
    "user_score", "relevance", "match_score", "score", "relevance_score",
    "user_relevance", "fit_score",
})

#: Fields that carry the personal state of the offer for one person (a note,
#: a shortlist, an application).  Like the relevance score, they say nothing
#: about the offer itself: they must never decide which version of a merged
#: offer is elected, nor how complete it is considered.
USER_STATE_FIELDS: frozenset[str] = frozenset({
    "notes", "note", "user_notes", "comment", "comments",
    "shortlisted", "shortlist", "favorite", "favourite", "bookmarked",
    "saved", "archived", "applied", "application_status", "application_id",
    "status_label",
})

#: Every field that belongs to the reader, not to the offer.
USER_SIDE_FIELDS: frozenset[str] = USER_SCORE_FIELDS | USER_STATE_FIELDS


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    """Remove diacritics without changing the rest of the string.

    The result is memoised: the same title, company or city is normalised
    again and again when a collection of offers is deduplicated.
    """
    return _strip_accents_cached(text)


@lru_cache(maxsize=8192)
def _strip_accents_cached(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def _squash(text: str) -> str:
    """Collapse every whitespace run into a single space."""
    return re.sub(r"\s+", " ", text).strip()


def _clean_text(value: Any, limit: int = 500) -> str:
    """Return a bounded, stripped text version of any connector value."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).replace("\x00", "").strip()[:limit]


def _company_text(value: Any) -> str:
    """Read a company name from a string or from a connector payload."""
    if isinstance(value, Mapping):
        for key in ("company", "name", "company_name", "label"):
            text = _clean_text(value.get(key), 240)
            if text:
                return text
        return ""
    return _clean_text(value, 240)


# ---------------------------------------------------------------------------
# 1. Canonical URL
# ---------------------------------------------------------------------------

#: Query parameters that only carry marketing or tracking information.
TRACKING_QUERY_PARAMETERS = frozenset({
    "ref", "source", "sourceid", "source_id", "src", "gclid", "fbclid",
    "msclkid", "mc_cid", "mc_eid", "trk", "trackingid", "referrer",
    "gh_src", "lever-source", "lever-origin", "origin", "campaign_id",
    "campaignid", "hiring_source", "tracking",
})


def _is_tracking_parameter(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith("utm_") or lowered in TRACKING_QUERY_PARAMETERS


def canonicalize_url(url: str) -> str:
    """Return the canonical form of a job URL.

    - scheme forced to ``https``
    - ``www.`` removed from the host, host lower-cased
    - default ports (80/443) removed, other ports kept
    - tracking query parameters (``utm_*``, ``ref``, ``source``…) removed,
      the remaining parameters sorted for a stable key
    - fragment removed
    - trailing slash removed (the root path keeps its single slash)

    A value that is not an http(s) URL is returned unchanged (trimmed): it is
    not a canonicalisable job link and must never create a false duplicate.
    """
    return _canonicalize_url_cached(_clean_text(url, 2_000))


@lru_cache(maxsize=8192)
def _canonicalize_url_cached(raw: str) -> str:
    """Canonicalise an already cleaned URL (memoised)."""
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return raw
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if not hostname:
        return raw
    try:
        port = parsed.port
    except ValueError:
        port = None
    port_suffix = f":{port}" if port and port not in {80, 443} else ""
    kept_query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_parameter(key)
    ]
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return urllib.parse.urlunsplit((
        "https",
        hostname + port_suffix,
        path,
        urllib.parse.urlencode(sorted(kept_query)),
        "",
    ))


def _canonical_path(url: str) -> str:
    """Return the path of a canonical URL, without its query string.

    Two links that only differ by their query parameters point at the same
    posting; two links with two different paths point at two postings.
    """
    canonical = canonicalize_url(url)
    if not canonical:
        return ""
    parsed = urllib.parse.urlsplit(canonical)
    if parsed.scheme not in {"http", "https"}:
        return canonical
    return parsed.path or "/"


# ---------------------------------------------------------------------------
# 2. Canonical company
# ---------------------------------------------------------------------------

#: Legal forms and generic group suffixes removed from a company name.
LEGAL_COMPANY_SUFFIXES = (
    "sa", "sas", "sasu", "sarl", "eurl", "scs", "snc", "scp",
    "ltd", "limited", "inc", "incorporated", "gmbh", "mbh", "ag", "kg",
    "srl", "spa", "bv", "nv", "plc", "llc", "llp", "lp", "oy", "ab", "as",
    "group", "groupe", "holding", "holdings", "company", "co", "corp",
    "corporation",
)

#: Words dropped from a company name, whatever their position.
COMPANY_DROPPED_WORDS = frozenset(LEGAL_COMPANY_SUFFIXES) | {"and", "et"}

#: Known employer spellings that must resolve to the same canonical name.
COMPANY_ALIASES = {
    "j p morgan": "jpmorgan",
    "jp morgan": "jpmorgan",
    "jpmorgan": "jpmorgan",
    "jpmorgan chase": "jpmorgan",
    "jpmorgan chase and co": "jpmorgan",
    "morgan stanley": "morganstanley",
    "goldman sachs": "goldmansachs",
    "goldman sachs international": "goldmansachs",
    "goldman sachs group": "goldmansachs",
    "rothschild and co": "rothschild",
    "rothschild co": "rothschild",
    "rothschild freres": "rothschild",
    "lazard freres": "lazard",
    "bnp paribas": "bnpparibas",
    "barclays bank": "barclays",
    "hsbc holdings": "hsbc",
    "ubs group": "ubs",
    "credit suisse": "creditsuisse",
    "deutsche bank": "deutschebank",
    "bank of america": "bankofamerica",
    "citigroup": "citi",
    "citi group": "citi",
    "point 72": "point72",
    "point72 asset management": "point72",
    "natixis wealth management": "natixis",
    "societe generale": "societegenerale",
    "evercore inc": "evercore",
    "evercore isi": "evercore",
}


def company_canonical(name: Any) -> str:
    """Return the canonical form of a company name.

    Lower-cased, accents removed, punctuation turned into spaces, known
    aliases applied and legal suffixes (``SA``, ``SAS``, ``Ltd``, ``Inc``,
    ``GmbH``, ``AG``, ``SRL``, ``SpA``, ``BV``, ``NV``, ``PLC``, ``Group``,
    ``Groupe``…) removed as whole words.
    """
    return _company_canonical_cached(_company_text(name))


@lru_cache(maxsize=8192)
def _company_canonical_cached(text: str) -> str:
    """Canonicalise an already extracted company name (memoised)."""
    text = _strip_accents(text).lower()
    text = _squash(re.sub(r"[^\w\s]", " ", text))
    if not text:
        return ""
    text = COMPANY_ALIASES.get(text, text)
    text = " ".join(word for word in text.split() if word not in COMPANY_DROPPED_WORDS)
    text = _squash(text)
    # A second pass catches the spellings that only match once the legal
    # suffix is gone ("Goldman Sachs Group" -> "Goldman Sachs").
    return COMPANY_ALIASES.get(text, text)


def canonical_company(company: Any) -> str:
    """Canonical company name (alias of :func:`company_canonical`)."""
    return company_canonical(company)


# ---------------------------------------------------------------------------
# 3. Canonical title, business concepts and role levels
# ---------------------------------------------------------------------------

#: Multi-word title synonyms applied before the word level mapping.
TITLE_PHRASE_SYNONYMS = (
    ("summer internship", "internship"),
    ("winter internship", "internship"),
    ("spring internship", "internship"),
    ("stage de fin d etudes", "internship"),
    ("working student", "working student"),
    ("werkstudent", "working student"),
    ("full time", "permanent"),
    ("temps plein", "permanent"),
    ("off cycle", "off cycle"),
)

#: Word level title synonyms (French and English).
TITLE_WORD_SYNONYMS = {
    "stage": "internship",
    "stages": "internship",
    "stagi": "internship",
    "stagiaire": "internship",
    "stagiaires": "internship",
    "intern": "internship",
    "interns": "internship",
    "internship": "internship",
    "trainee": "internship",
    "traineeship": "internship",
    "praktikum": "internship",
    "tirocinio": "internship",
    "alternance": "apprenticeship",
    "apprentissage": "apprenticeship",
    "apprenticeship": "apprenticeship",
    "apprentice": "apprenticeship",
    "apprenti": "apprenticeship",
    "apprentis": "apprenticeship",
    "cdi": "permanent",
    "permanent": "permanent",
    "cdd": "fixed term",
    "freelance": "freelance",
    "independant": "freelance",
}

#: Business concepts used to match a translated or reworded title.
TITLE_CONCEPT_SOURCES = (
    (r"\bm\s*&\s*a\b|\bm\s+and\s+a\b|\bmergers?\s+(?:and|&)\s+acquisitions?\b|\bfusion[\s-]?acquisition[s]?\b"
     r"|\binvestment banking\b|\bbanque\s+d[' ]?affaires?\b|\bconseil\s+en\s+(?:fusions?|transactions?)"
     r"|\btransaction[s]?\s+advisory\b|\bglobal advisory\b|\bcorporate finance advisory\b",
     "investment_banking"),
    (r"\bprivate equity\b|\bcapital investissement\b|\bcapital developpement\b|\bfonds d investissement"
     r"|\bfonds investissement\b|\bbuyout\b|\bgrowth equity\b|\blbo\b",
     "private_equity"),
    (r"\basset management\b|\bgestion d actifs\b|\bsociete de gestion"
     r"|\bgestionnaire de portefeuille\b|\bgestion de portefeuille\b|\bportfolio management\b|\binvestment research"
     r"|\brecherche d investissement\b|\bequity research\b|\bfixed income\b",
     "asset_management"),
    (r"\bsales and trading\b|\bsales & trading\b|\bglobal markets\b|\bmarkets off cycle"
     r"|\bfixed income sales\b|\bequity sales\b|\btrading\b",
     "sales_trading"),
    (r"\bcorporate finance\b|\bfinance entreprise\b|\bfinance d entreprise\b|\bfinancial analysis\b"
     r"|\bfinancial analyst\b|\banalyse financiere\b|\banalyste financier\b|\bvaluation\b|\btreasury\b"
     r"|\bstrategic finance\b|\bfp a\b|\bplanning analytique\b|\bcontrole de gestion\b|\bbusiness partner\b",
     "corporate_finance"),
    (r"\bconsulting\b|\bconseil\b|\bstrategy consulting\b|\btransaction services\b"
     r"|\bdeals advisory\b|\bdue diligence\b|\bfdd\b",
     "consulting"),
    (r"\baudit\b|\baudit financier\b|\bfinancial audit\b|\bstatutory audit\b|\bcontrole externe"
     r"|\bcommissariat aux comptes\b",
     "audit"),
    (r"\bquant\b|\bquantitative research\b|\bquant developer\b|\bquant dev\b",
     "quantitative_research"),
    (r"\bsoftware engineering\b|\bsoftware engineer\b|\bbackend\b|\bfrontend\b|\bfull stack\b"
     r"|\bdevops\b|\bdata engineer\b|\bml engineer\b|\bmachine learning\b"
     r"|\bdeveloppeur\b|\bdeveloppement logiciel\b|\bingenieur logiciel\b",
     "software_engineering"),
    (r"\bdata analyst\b|\banalyste de donnees\b|\bdata analytics\b|\bbusiness analyst"
     r"|\banalyste business\b|\bbusiness intelligence\b|\bbi analyst\b",
     "data_analyst"),
)

#: One alternation for every business concept (a single pass per title).
TITLE_CONCEPT_RE = re.compile(
    "|".join(f"(?P<c{index}>{source})" for index, (source, _concept) in enumerate(TITLE_CONCEPT_SOURCES)),
    re.IGNORECASE,
)

#: Concept of every group of :data:`TITLE_CONCEPT_RE`.
TITLE_CONCEPT_BY_GROUP = {
    f"c{index}": concept for index, (_source, concept) in enumerate(TITLE_CONCEPT_SOURCES)
}

#: Small words that carry no meaning when two titles are compared.
TITLE_STOPWORDS = frozenset({
    "en", "de", "du", "des", "la", "le", "les", "au", "aux", "un", "une",
    "the", "of", "for", "and", "on", "in", "at", "with", "a",
})

#: Words that describe a family of jobs rather than a precise role.  Two
#: titles that only share such words do not prove that they are the same
#: posting: "Stage" and "Intern" are the same word, not the same offer.
GENERIC_TITLE_WORDS = frozenset({
    "internship", "intern", "stage", "stagiaire", "permanent", "freelance",
    "apprenticeship", "cdi", "cdd", "fixed", "term", "manager", "sales",
    "marketing", "analyst", "analyste", "consultant", "assistant", "associate",
    "specialist", "officer", "executive", "business", "development",
    "operations", "team", "group", "global", "full", "time", "part", "m",
    "a", "and", "or", "de", "du", "des", "la", "le", "les", "en", "the",
    "of", "for", "and", "on", "in", "at", "with",
})

#: Words that only appear in a French title.
FRENCH_TITLE_WORDS = frozenset({
    "stage", "stagiaire", "alternance", "apprentissage", "poste", "emploi",
    "ingenieur", "charge", "missions", "profil", "teletravail", "duree",
    "debut", "periode", "temps", "plein", "cdi", "cdd", "france",
    "recherche", "clientele", "secteur", "equipe", "programme", "analyste",
    "finance", "gestion", "vente", "developpement", "stage",
})

#: Words that only appear in an English title.
ENGLISH_TITLE_WORDS = frozenset({
    "intern", "internship", "graduate", "hiring", "apply", "team", "job",
    "role", "position", "full-time", "part-time", "engineer", "developer",
    "recruiter", "candidate", "skills", "our", "we", "join", "analyst",
    "software", "research", "development", "management", "trading",
})


def _strip_title_noise(text: str) -> str:
    """Remove the French ``H/F`` and ``F/H`` gender markers."""
    without_gender = re.sub(r"\b[hf]\s*[/\-]\s*[hf]\b", " ", text)
    return re.sub(r"\bx\s*[hf]\b", " ", without_gender)


def _raw_title_text(title: Any) -> str:
    """Return the lower-cased, accent-free title, punctuation preserved."""
    if isinstance(title, Mapping):
        title = title.get("title", "")
    return _raw_title_text_cached(_clean_text(title, 300))


@lru_cache(maxsize=8192)
def _raw_title_text_cached(text: str) -> str:
    """Normalise an already cleaned title (memoised)."""
    return _strip_accents(text).lower().replace("’", "'")


def _title_base(title: Any) -> str:
    """Return the lower-cased, accent-free title, punctuation turned into spaces."""
    if isinstance(title, Mapping):
        title = title.get("title", "")
    return _title_base_cached(_clean_text(title, 300))


@lru_cache(maxsize=8192)
def _title_base_cached(text: str) -> str:
    """Normalise an already cleaned title into its comparable form."""
    normalised = _strip_title_noise(_raw_title_text_cached(text))
    normalised = re.sub(r"[^\w\s]", " ", normalised)
    return _squash(normalised)


@lru_cache(maxsize=8192)
def _title_canonical_from_base(base: str) -> str:
    """Return the canonical title of an already normalised title."""
    text = base
    for phrase, replacement in TITLE_PHRASE_SYNONYMS:
        if phrase in text:
            text = text.replace(phrase, replacement)
    words = [TITLE_WORD_SYNONYMS.get(word, word) for word in text.split()]
    return _squash(" ".join(words))


def title_canonical(title: Any) -> str:
    """Return the canonical form of a job title.

    Lower-cased, accents removed, punctuation turned into spaces and the
    known synonyms applied (``stage``/``intern`` → ``internship``,
    ``CDI``/``permanent`` → ``permanent``,
    ``alternance``/``apprentissage`` → ``apprenticeship``).
    """
    return _title_canonical_from_base(_title_base(title))


@lru_cache(maxsize=8192)
def _title_concept_from_raw(raw: str) -> str:
    """Return the business concept of an already normalised title.

    The title is read twice: as it was written (``"M&A"``, ``"d'actifs"``)
    and with its punctuation turned into spaces (``"m a"``, ``"d actifs"``),
    so that a hyphen or an apostrophe never hides a business concept.
    """
    match = TITLE_CONCEPT_RE.search(raw)
    if match is None:
        spaced = re.sub(r"[^\w\s]", " ", raw)
        if spaced != raw:
            match = TITLE_CONCEPT_RE.search(spaced)
    if match is None:
        return ""
    group = match.lastgroup
    if group is None:
        return ""
    return TITLE_CONCEPT_BY_GROUP.get(group, "")


def title_concept(title: Any) -> str:
    """Return the business concept of a title (``""`` when unknown)."""
    return _title_concept_from_raw(_raw_title_text(title))


def canonical_title_concept(title: Any) -> str:
    """Return the business concept of a title, or its most meaningful words.

    The known concepts (``investment_banking``, ``private_equity``…) are
    returned when the title matches one of them.  Otherwise the first
    meaningful words of the title are returned, so that two titles written
    differently but naming the same job still share a comparable key.
    """
    concept = title_concept(title)
    if concept:
        return concept
    words = [
        word for word in _title_base(title).split()
        if word not in TITLE_WORD_SYNONYMS and len(word) > 2
    ]
    return " ".join(words[:3])


#: Role levels accepted when a connector states them explicitly.
KNOWN_ROLE_LEVELS = frozenset({
    "intern", "apprentice", "junior", "analyst", "experienced", "permanent",
    "fixed_term", "freelance",
})

#: Spellings of a role level that resolve to the known vocabulary.
ROLE_LEVEL_ALIASES = {
    "intern": "intern", "internship": "intern", "stage": "intern",
    "stagiaire": "intern", "trainee": "intern", "traineeship": "intern",
    "praktikum": "intern", "tirocinio": "intern",
    "apprentice": "apprentice", "apprenticeship": "apprentice",
    "alternance": "apprentice", "apprentissage": "apprentice",
    "working_student": "apprentice", "werkstudent": "apprentice",
    "junior": "junior", "jr": "junior",
    "analyst": "analyst", "analyste": "analyst", "off_cycle": "analyst",
    "experienced": "experienced", "senior": "experienced", "sr": "experienced",
    "lead": "experienced", "head": "experienced", "director": "experienced",
    "manager": "experienced", "partner": "experienced", "principal": "experienced",
    "vp": "experienced", "md": "experienced", "expert": "experienced",
    "permanent": "permanent", "cdi": "permanent",
    "fixed_term": "fixed_term", "cdd": "fixed_term",
    "freelance": "freelance", "independant": "freelance",
}

#: Role level markers, applied in this order: the first match wins.  The
#: seniority markers come before the analyst marker so that a "Financial
#: Analyst Director" is an experienced role and not an analyst one.
ROLE_LEVEL_PATTERNS = (
    ("intern", re.compile(
        r"\b(stage|stages|stagi|stagiaire|stagiaires|intern|interns|internship"
        r"|trainee|traineeship|praktikum|tirocinio)\b")),
    ("apprentice", re.compile(
        r"\b(alternance|apprentissage|apprentice|apprenticeship|apprenti|apprentis"
        r"|working student|werkstudent)\b")),
    ("fixed_term", re.compile(
        r"\b(cdd|fixed term|contractuel|contractuelle|temporaire|temporary)\b")),
    ("freelance", re.compile(r"\b(freelance|independant)\b")),
    ("junior", re.compile(r"\b(junior|jr)\b")),
    ("experienced", re.compile(
        r"\b(senior|sr|lead|head|director|directeur|directrice|manager|partner"
        r"|principal|vp|md|managing director|expert|confirmed)\b")),
    ("analyst", re.compile(r"\b(analyst|analyste|analystes|off cycle|off-cycle)\b")),
    ("permanent", re.compile(r"\b(cdi|permanent|full time|temps plein)\b")),
)


def _declared_role_level(job: Mapping[str, Any]) -> str:
    """Return the role level stated by the connector (``""`` when unknown)."""
    stated = _clean_text(job.get("role_level"), 40).lower()
    stated = stated.replace(" ", "_").replace("-", "_")
    return ROLE_LEVEL_ALIASES.get(stated, "")


def _role_level_from_base(base: str) -> str:
    """Return the role level carried by an already normalised title."""
    for level, pattern in ROLE_LEVEL_PATTERNS:
        if pattern.search(base):
            return level
    return ""


def title_role_level(title: Any) -> str:
    """Return the role level of a title or of a record (``""`` when unknown).

    The level states the kind of position: ``intern``, ``apprentice``,
    ``junior``, ``analyst``, ``experienced``, ``permanent``, ``fixed_term``
    or ``freelance``.  Two records whose levels are both known and differ
    describe two different jobs: they are never merged.
    """
    if isinstance(title, Mapping):
        declared = _declared_role_level(title)
        if declared:
            return declared
        return _role_level_from_base(_title_base(title.get("title", "")))
    return _role_level_from_base(_title_base(title))


def title_contract(title: Any) -> str:
    """Return the contract of a title (``""`` when unknown).

    Contract: ``intern``, ``apprentice``, ``permanent``, ``fixed_term`` or
    ``freelance``.
    """
    level = title_role_level(title)
    if level in {"intern", "apprentice", "permanent", "fixed_term", "freelance"}:
        return level
    return ""


def title_seniority(title: Any) -> str:
    """Return the seniority of a title (``""`` when unknown).

    Seniority: ``junior``, ``analyst`` or ``experienced``.
    """
    level = title_role_level(title)
    if level in {"junior", "analyst", "experienced"}:
        return level
    return ""


def _sorted_title(canonical_title: str) -> str:
    """Return the canonical title with its words sorted."""
    return " ".join(sorted(canonical_title.split()))


def _content_tokens(canonical_title: str) -> tuple[str, ...]:
    """Return the meaningful words of a canonical title, sorted."""
    return tuple(
        token for token in sorted(canonical_title.split())
        if token not in TITLE_STOPWORDS
    )


def _specific_tokens(canonical_title: str) -> set[str]:
    """Return the tokens that actually describe the job of a title.

    Stopwords and generic family words (``intern``, ``manager``…) are removed:
    two titles that only share those words do not describe the same job.
    """
    return {
        token for token in canonical_title.split()
        if token not in TITLE_STOPWORDS
        and token not in GENERIC_TITLE_WORDS
        and len(token) > 1
    }


def _digit_signature(title: str) -> str:
    """Return the digits carried by a title ("2027", "h1 2027"…).

    Two titles that carry different digits describe different cohorts,
    editions or durations: they are never the same offer.
    """
    tokens = sorted({
        token
        for token in title.split()
        if any(character.isdigit() for character in token)
    })
    return "|".join(tokens)


@lru_cache(maxsize=16384)
def _title_similarity_from_parts(
    canonical_a: str,
    canonical_b: str,
    concept_a: str,
    concept_b: str,
    level_a: str,
    level_b: str,
) -> float:
    """Return the similarity of two already normalised titles."""
    if not canonical_a or not canonical_b:
        return 0.0
    score = jaro_winkler(canonical_a, canonical_b)
    if score < TITLE_SIMILARITY_THRESHOLD:
        # The same words in another order describe the same job
        # ("Stage en finance" and "Finance Internship").
        tokens_a = _content_tokens(canonical_a)
        tokens_b = _content_tokens(canonical_b)
        if tokens_a and tokens_a == tokens_b:
            score = 1.0
        else:
            score = max(
                score,
                jaro_winkler(_sorted_title(canonical_a), _sorted_title(canonical_b)),
            )
    if concept_a and concept_b and concept_a == concept_b:
        score = max(score, CONCEPT_MATCH_SIMILARITY)
    if level_a and level_b and level_a != level_b:
        score = min(score, ROLE_CONFLICT_SIMILARITY)
    return round(score, 6)


def title_similarity(title_a: Any, title_b: Any) -> float:
    """Return the similarity of two job titles, between 0.0 and 1.0.

    The score combines the Jaro-Winkler similarity of the canonical titles
    with the business concept mapping (a translated title such as
    ``"Analyste de données"`` matches ``"Data Analyst"``).

    Two titles describing incompatible roles (a stage and a permanent
    analyst role) are capped far below the clustering threshold: they are
    two different jobs, never a duplicate.
    """
    base_a = _title_base(title_a)
    base_b = _title_base(title_b)
    return _title_similarity_from_parts(
        _title_canonical_from_base(base_a),
        _title_canonical_from_base(base_b),
        _title_concept_from_raw(_raw_title_text(title_a)),
        _title_concept_from_raw(_raw_title_text(title_b)),
        _role_level_from_base(base_a),
        _role_level_from_base(base_b),
    )


def _title_language(title: Any) -> str:
    """Return the language of a title (``"fr"``, ``"en"`` or ``""``)."""
    words = set(_title_base(title).split())
    french = bool(words & FRENCH_TITLE_WORDS)
    english = bool(words & ENGLISH_TITLE_WORDS)
    if french and not english:
        return "fr"
    if english and not french:
        return "en"
    return ""


# ---------------------------------------------------------------------------
# 4. Canonical location
# ---------------------------------------------------------------------------

#: Cities that are the same place under two spellings.
CITY_ALIASES = {
    "paris la defense": "paris",
    "la defense": "paris",
    "paris 8": "paris",
    "londres": "london",
    "milano": "milan",
    "francfort": "frankfurt",
    "frankfurt am main": "frankfurt",
    "francfort am main": "frankfurt",
    "geneve": "geneva",
    "new york city": "new york",
    "nyc": "new york",
    "bruxelles": "brussels",
    "zuerich": "zurich",
    "munchen": "munich",
    "lisbonne": "lisbon",
    "hamburg": "hamburg",
}

#: Countries mapped to their ISO-2 code.
COUNTRY_ISO2 = {
    "france": "fr", "fr": "fr",
    "united kingdom": "gb", "uk": "gb", "gb": "gb", "royaume uni": "gb",
    "united states": "us", "usa": "us", "us": "us", "etats unis": "us",
    "germany": "de", "deutschland": "de", "de": "de", "allemagne": "de",
    "italy": "it", "italia": "it", "it": "it",
    "spain": "es", "espana": "es", "es": "es", "espagne": "es",
    "netherlands": "nl", "holland": "nl", "nl": "nl", "pays bas": "nl",
    "nederland": "nl", "huelanda": "nl",
    "belgium": "be", "belgique": "be", "be": "be",
    "switzerland": "ch", "suisse": "ch", "ch": "ch",
    "luxembourg": "lu", "lu": "lu",
    "ireland": "ie", "irlande": "ie", "ie": "ie",
    "austria": "at", "autriche": "at", "at": "at", "osterreich": "at",
    "poland": "pl", "pologne": "pl", "pl": "pl",
    "sweden": "se", "suede": "se", "se": "se",
    "denmark": "dk", "danemark": "dk", "dk": "dk",
    "norway": "no", "norvege": "no", "no": "no",
    "finland": "fi", "finlande": "fi", "fi": "fi", "suomi": "fi",
    "canada": "ca", "ca": "ca",
    "australia": "au", "au": "au",
    "singapore": "sg", "singapour": "sg", "sg": "sg",
    "hong kong": "hk", "hk": "hk",
    "china": "cn", "chine": "cn", "cn": "cn",
    "india": "in", "inde": "in", "in": "in",
    "japan": "jp", "japon": "jp", "jp": "jp",
    "brazil": "br", "bresil": "br", "brasil": "br",
    "mexico": "mx", "mexique": "mx", "mx": "mx",
    "south korea": "kr", "coree du sud": "kr", "kr": "kr",
    "new zealand": "nz", "nouvelle zelande": "nz", "nz": "nz",
    "israel": "il", "il": "il",
    "portugal": "pt", "pt": "pt",
    "greece": "gr", "grece": "gr", "gr": "gr",
    "turkey": "tr", "turquie": "tr", "tr": "tr",
    "romania": "ro", "roumanie": "ro", "ro": "ro",
    "hungary": "hu", "hongrie": "hu", "hu": "hu",
    "czech republic": "cz", "republique tcheque": "cz", "cz": "cz",
    "great britain": "gb",
    "saudi arabia": "sa", "arabie saoudite": "sa", "sa": "sa",
    "united arab emirates": "ae", "emirats arabes unis": "ae", "ae": "ae",
    "netherlands antilles": "nl",
}

#: Markers of a fully remote offer.
REMOTE_MARKERS = (
    "remote", "teletravail", "a distance", "distanciel", "work from home",
    "wfh", "home office", "homeoffice", "full remote", "fully remote",
)

#: Country names that a city field often carries at its end ("Berlin
#: Germany").  Only the long spellings are used, so that a place whose name
#: ends with a short word ("Little Italy") is never truncated.
TRAILING_COUNTRY_NAMES = frozenset({
    "france", "germany", "spain", "italy", "netherlands", "switzerland",
    "austria", "poland", "sweden", "denmark", "norway", "finland", "canada",
    "australia", "singapore", "portugal", "belgium", "india", "israel",
    "turkey", "romania", "hungary", "ireland", "greece", "mexico", "brazil",
    "united kingdom", "united states", "great britain", "south korea",
    "new zealand", "saudi arabia", "united arab emirates", "czech republic",
    "deutschland", "italia", "espana", "espagne", "nederland", "osterreich",
    "suomi", "belgique", "suisse", "royaume uni", "etats unis", "allemagne",
    "pays bas", "suede", "danemark", "norvege", "finlande", "pologne",
    "autriche", "hong kong", "coree du sud", "nouvelle zelande",
})

#: Words that keep a place name from being cut when a country follows it
#: ("Northern Ireland" is not "Northern").
COUNTRY_QUALIFIERS = frozenset({
    "northern", "southern", "eastern", "western", "new", "republic", "of",
})

#: Words that tell a street address from a city name ("10 rue de Rivoli,
#: Paris" is an offer in Paris).
ADDRESS_MARKERS = frozenset({
    "rue", "street", "avenue", "av", "boulevard", "bd", "impasse", "allee",
    "quai", "chemin", "route", "place", "square", "cours", "voie", "passage",
    "level", "floor", "etage", "batiment", "building", "suite", "unit",
    "workspace", "pobox",
})


def _looks_like_an_address(text: str) -> bool:
    """Tell a street address from a city name."""
    return any(token in ADDRESS_MARKERS for token in text.split())


def _is_remote(text: str) -> bool:
    return any(marker in text for marker in REMOTE_MARKERS)


def _strip_trailing_country(text: str) -> str:
    """Remove the country name a city field sometimes carries at its end.

    ``"Berlin Germany"`` becomes ``"berlin"``.  The city is kept untouched
    when what is left would be empty or would end with a qualifier
    (``"Northern Ireland"``).
    """
    for name in sorted(TRAILING_COUNTRY_NAMES, key=len, reverse=True):
        if not text.endswith(" " + name):
            continue
        remainder = text[: -(len(name) + 1)].strip()
        if not remainder:
            return text
        if remainder.split()[-1] in COUNTRY_QUALIFIERS:
            return text
        return remainder
    return text


def _canonical_city(city: Any) -> str:
    """Return the normalised city name ("" when unknown).

    A city field often carries more than the name of the city: the region or
    the country of the offer (``"Paris, Île-de-France"``, ``"Berlin,
    Germany"``), sometimes the street address (``"10 rue de Rivoli, Paris"``).
    Only the city itself identifies the place: the rest never contradicts
    another source, so it is dropped instead of becoming a false conflict.
    """
    return _canonical_city_cached(_clean_text(city, 120))


@lru_cache(maxsize=8192)
def _canonical_city_cached(raw: str) -> str:
    """Normalise an already cleaned city (memoised)."""
    raw = _strip_accents(raw).lower()
    raw = re.sub(r"\([^)]*\)", " ", raw)
    raw = re.sub(r"[|/]+", " ", raw)
    candidates: list[str] = []
    for part in raw.split(","):
        candidate = re.sub(r"[^\w\s-]", " ", part)
        candidate = _squash(candidate)
        candidate = re.sub(r"^\d+\s+", "", candidate)
        if candidate:
            candidates.append(candidate)
    for candidate in candidates:
        # A street address is not a city: the city is the other part.
        if len(candidates) > 1 and _looks_like_an_address(candidate):
            continue
        candidate = _strip_trailing_country(candidate)
        if not candidate:
            continue
        if _is_remote(candidate):
            return "remote"
        return CITY_ALIASES.get(candidate, candidate)
    return ""


def _canonical_country(country: Any) -> str:
    """Return the ISO-2 country code ("" when unknown).

    An unknown country stays **unknown**: it is never reduced to a truncated
    prefix, because a prefix never equals the real code of another country
    (``"Nederland"`` is not ``"ne"``).
    """
    return _canonical_country_cached(_clean_text(country, 120))


@lru_cache(maxsize=8192)
def _canonical_country_cached(text: str) -> str:
    """Normalise an already cleaned country (memoised)."""
    text = _strip_accents(text).lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = _squash(text)
    if not text:
        return ""
    if _is_remote(text):
        return ""
    if text in COUNTRY_ISO2:
        return COUNTRY_ISO2[text]
    if len(text) == 2 and text.isalpha():
        return text
    for token in text.split():
        if token in COUNTRY_ISO2:
            return COUNTRY_ISO2[token]
    return ""


def location_canonical(city: Any, country: Any) -> str:
    """Return the canonical form of a location.

    The city is normalised (accents, hyphens, common aliases) and the country
    is reduced to its ISO-2 code when it is known.  A fully remote offer is
    normalised to the single token ``"remote"``.
    """
    canonical_city = _canonical_city(city)
    if canonical_city == "remote":
        return "remote"
    canonical_country = _canonical_country(country)
    if canonical_city and canonical_country:
        return f"{canonical_city},{canonical_country}"
    return canonical_city or canonical_country


def canonical_city(city: Any) -> str:
    """Return the normalised city name ("" when unknown)."""
    if isinstance(city, Mapping):
        city = city.get("city", "")
    return _canonical_city(city)


def _same_location(city_a: str, country_a: str, city_b: str, country_b: str) -> bool:
    """Tell whether two locations describe the same place.

    An unknown country on one side only does not prevent a match (a board may
    omit it); two different known countries do.
    """
    if city_a == city_b and country_a == country_b:
        return True
    if "remote" in {city_a, city_b}:
        return city_a == city_b
    if not city_a or not city_b or city_a != city_b:
        return False
    return not country_a or not country_b or country_a == country_b


# ---------------------------------------------------------------------------
# 5. Jaro-Winkler similarity (pure Python, no external dependency)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=16384)
def jaro_winkler(s1: str, s2: str, *, prefix_scale: float = 0.1, max_prefix: int = 4) -> float:
    """Return the Jaro-Winkler similarity of two strings (0.0 to 1.0).

    An empty string carries no evidence: it is never similar to anything,
    not even to another empty string.
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    match_window = max(max(len1, len2) // 2 - 1, 0)
    matches_first = [False] * len1
    matches_second = [False] * len2
    matches = 0
    for index in range(len1):
        start = max(0, index - match_window)
        end = min(index + match_window + 1, len2)
        for other in range(start, end):
            if matches_second[other] or s1[index] != s2[other]:
                continue
            matches_first[index] = True
            matches_second[other] = True
            matches += 1
            break
    if not matches:
        return 0.0
    transpositions = 0
    cursor = 0
    for index in range(len1):
        if not matches_first[index]:
            continue
        while not matches_second[cursor]:
            cursor += 1
        if s1[index] != s2[cursor]:
            transpositions += 1
        cursor += 1
    transpositions //= 2
    jaro = (
        matches / len1
        + matches / len2
        + (matches - transpositions) / matches
    ) / 3
    prefix = 0
    for index in range(min(len1, len2, max_prefix)):
        if s1[index] != s2[index]:
            break
        prefix += 1
    score = jaro + prefix * prefix_scale * (1 - jaro)
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# 6. Source priority and trust
# ---------------------------------------------------------------------------

#: Priority per source: the first row wins when two offers are identical.
SOURCE_PRIORITY = {
    "ashby": 100,
    "greenhouse": 90,
    "lever": 80,
    "welcometothejungle": 70,
    "jobteaser": 60,
    "talentcom": 50,
    "apec": 40,
}

#: Spellings of a source that must resolve to the same priority key.
SOURCE_ALIASES = {
    "welcomejungle": "welcometothejungle",
    "talentdotcom": "talentcom",
}

#: Sources whose identifier is not globally unique.
MANUAL_SOURCES = frozenset({"", "manual", "import manuel", "import", "unknown"})

#: Sources that publish an official employer page.
EMPLOYER_SOURCES = frozenset({"employer_sites", "employer_official", "employer", "careers_page"})


def _source_key(source_name: str) -> str:
    """Return the comparable key of a source name."""
    lowered = _clean_text(source_name, 80).lower()
    key = re.sub(r"[^a-z0-9]", "", lowered)
    if key in SOURCE_ALIASES:
        return SOURCE_ALIASES[key]
    if key in SOURCE_PRIORITY:
        return key
    for known in sorted(SOURCE_PRIORITY, key=len, reverse=True):
        if key.startswith(known):
            return known
    return key


def source_priority(source_name: str) -> int:
    """Return the priority of a source (higher wins).

    Ashby > Greenhouse > Lever > Welcome to the Jungle > JobTeaser >
    Talent.com > APEC.  An unknown source keeps a neutral priority and a
    manual source the lowest one.
    """
    key = _source_key(source_name)
    if key in SOURCE_PRIORITY:
        return SOURCE_PRIORITY[key]
    if key in MANUAL_SOURCES:
        return 10
    return 20


def _source_tier(source_name: str, job: Mapping[str, Any]) -> int:
    """Return the tier of a source: an employer page beats a board."""
    declared = _clean_text(job.get("source_tier"), 40).lower()
    if declared == "employer":
        return 3
    if declared:
        return 1
    key = _source_key(source_name)
    if key in EMPLOYER_SOURCES:
        return 3
    if key in SOURCE_PRIORITY:
        return 2
    if key in {"campuschannel", "campus"}:
        return 1
    return 0


def _record_trust(job: Mapping[str, Any]) -> str:
    """Return the trust status declared by the record (SPEC-SK-01).

    The status is read from the record: the trust contract of SPEC-SK-01
    fills it, the deduplication never re-decides it.  An unknown status is
    ``"missing"``.
    """
    for key in ("source_trust", "trust_status", "source_trust_status"):
        value = _clean_text(job.get(key), 40).lower()
        if value in TRUST_STATUSES:
            return value
    return "missing"


# ---------------------------------------------------------------------------
# 7. Records
# ---------------------------------------------------------------------------

#: Fields read to date a record; the first parsable one wins.
FRESHNESS_FIELDS = (
    "last_verified_at", "seen_at", "last_seen_at", "discovered_at",
    "published_at", "posted_date", "updated_at",
)


def _parse_timestamp(raw: Any) -> float | None:
    """Parse a connector date into a UTC timestamp (None when unreadable)."""
    return _parse_timestamp_cached(_clean_text(raw, 64))


@lru_cache(maxsize=8192)
def _parse_timestamp_cached(text: str) -> float | None:
    """Parse an already cleaned date (memoised)."""
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment: datetime | None = None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                moment = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _freshness(job: Mapping[str, Any]) -> float:
    """Return the freshness of a record (0.0 when no date is known)."""
    for field_name in FRESHNESS_FIELDS:
        parsed = _parse_timestamp(job.get(field_name, ""))
        if parsed is not None:
            return parsed
    return 0.0


@dataclass(frozen=True)
class _Record:
    """One offer, with every key used by the deduplication algorithm."""

    index: int
    job: Mapping[str, Any]
    source_name: str
    source_id: str
    external_id: str
    external_key: str
    canonical_url: str
    apply_url: str
    company: str
    raw_title: str
    title: str
    concept: str
    level: str
    city: str
    country: str
    digits: str
    freshness: float
    trust: str
    identity: str

    @property
    def priority(self) -> int:
        return source_priority(self.source_name)

    @property
    def has_external_id(self) -> bool:
        return bool(self.external_key)


def _external_identity(job: Mapping[str, Any], source_name: str, source_id: str) -> tuple[str, str]:
    """Return the external identifier of a record and its clustering key.

    An explicit ``external_id`` is global (``gh_jid_123``).  The connector
    ``source_id`` is namespaced by the source, because an ATS identifier is
    only unique inside its own board.
    """
    external_id = _clean_text(job.get("external_id") or job.get("externalId"), 240)
    if external_id:
        return external_id, f"ext:{external_id}"
    if source_id and _source_key(source_name) not in MANUAL_SOURCES:
        return source_id, f"src:{_source_key(source_name)}:{source_id}"
    return "", ""


def _record_identity(record: _Record) -> str:
    """Return a stable identity of a record (used in the audit report)."""
    return _identity_from_values(
        record.external_id,
        record.source_id,
        record.source_name,
        record.canonical_url,
        record.company,
        record.title,
        record.city,
    )


def _identity_from_values(
    external_id: str,
    source_id: str,
    source_name: str,
    canonical_url: str,
    company: str,
    title: str,
    city: str,
) -> str:
    """Return the stable identity of a record from its normalised values."""
    if external_id:
        return f"ext:{external_id}"
    if source_id:
        return f"source:{source_name}:{source_id}"
    if canonical_url:
        return f"url:{canonical_url}"
    digest = hashlib.sha1(
        f"{company}|{title}|{city}".encode("utf-8")
    ).hexdigest()[:16]
    return f"hash:{digest}"


def _build_record(index: int, job: Mapping[str, Any]) -> _Record:
    """Build the deduplication record of a job dictionary."""
    source_name = _clean_text(job.get("source_name"), 80)
    source_id = _clean_text(job.get("source_id"), 240)
    external_id, external_key = _external_identity(job, source_name, source_id)
    raw_title = _clean_text(job.get("title"), 300)
    base = _title_base(raw_title)
    declared_level = _declared_role_level(job)
    canonical_title = _title_canonical_from_base(base)
    canonical_url = canonicalize_url(job.get("official_url") or job.get("url") or "")
    company = company_canonical(job.get("company"))
    city = _canonical_city(job.get("city"))
    identity = _identity_from_values(
        external_id, source_id, source_name, canonical_url, company, canonical_title, city,
    )
    return _Record(
        index=index,
        job=job,
        source_name=source_name,
        source_id=source_id,
        external_id=external_id,
        external_key=external_key,
        canonical_url=canonical_url,
        apply_url=canonicalize_url(job.get("apply_url") or ""),
        company=company,
        raw_title=raw_title,
        title=canonical_title,
        concept=_title_concept_from_raw(_raw_title_text(raw_title)),
        level=declared_level or _role_level_from_base(base),
        city=city,
        country=_canonical_country(job.get("country")),
        digits=_digit_signature(canonical_title),
        freshness=_freshness(job),
        trust=_record_trust(job),
        identity=identity,
    )


# ---------------------------------------------------------------------------
# 8. Pairwise decision
# ---------------------------------------------------------------------------

#: Reason codes of a merge.
REASON_EXTERNAL_ID = "same_external_id"
REASON_CANONICAL_URL = "canonical_url_match"
REASON_APPLY_URL = "apply_url_match"
REASON_CONCEPT = "same_role_concept"
REASON_TITLE_SIMILARITY = "title_similarity_match"
REASON_CLUSTER = "company_title_location_cluster"

#: Reason codes of a refusal.
REASON_RECYCLED_ID = "recycled_identifier_conflict"
REASON_COMPANY = "company_conflict"
REASON_ROLE_LEVEL = "role_level_conflict"
REASON_COHORT = "cohort_conflict"
REASON_START_DATE = "start_date_conflict"
REASON_CITY = "city_conflict"
REASON_NO_IDENTITY = "no_shared_identity"
REASON_DIFFERENT_ROLE = "different_role_same_employer"
REASON_TRANSLATION = "translation_common_words_only"


def _start_month(value: Any) -> str:
    """Return the ``YYYY-MM`` month of a date ("" when unknown)."""
    text = _clean_text(value, 32)
    if not text:
        return ""
    if len(text) >= 7 and text[4] == "-":
        return text[:7]
    parsed = _parse_timestamp(text)
    if parsed is None:
        return ""
    return datetime.fromtimestamp(parsed, tz=timezone.utc).strftime("%Y-%m")


def _same_title_pair(left: _Record, right: _Record) -> bool:
    """Tell whether two titles name the same job."""
    if left.title and left.title == right.title:
        return True
    tokens_left = _content_tokens(left.title)
    tokens_right = _content_tokens(right.title)
    return bool(tokens_left) and tokens_left == tokens_right


def _title_decision(
    left: _Record,
    right: _Record,
    text_similarity: Callable[[str, str], float] | None = None,
) -> tuple[bool, str]:
    """Decide whether two titles describe the same job.

    Returns the decision and the reason of the decision.
    """
    if left.concept and right.concept and left.concept == right.concept:
        return True, REASON_CONCEPT
    if not left.title or not right.title:
        return False, REASON_NO_IDENTITY
    similarity = _title_similarity_from_parts(
        left.title, right.title, left.concept, right.concept, left.level, right.level,
    )
    if text_similarity is not None and left.raw_title and right.raw_title:
        similarity = max(similarity, float(text_similarity(left.raw_title, right.raw_title)))
    cross_language = _cross_language(left, right)
    if similarity >= TITLE_SIMILARITY_THRESHOLD:
        # A translated title is only merged when it carries a real proof:
        # the same business concept, or at least one specific word in
        # common.  "Stage" and "Intern" alone never merge two offers.
        if cross_language and not _shared_specific_token(left, right):
            return False, REASON_TRANSLATION
        return True, REASON_TITLE_SIMILARITY
    if cross_language and not _shared_specific_token(left, right):
        return False, REASON_TRANSLATION
    if not left.concept and not right.concept and _shared_specific_token(left, right):
        # The two titles share a word but no business concept: they are too
        # close to be told apart and too far to be merged.
        return False, REASON_NO_IDENTITY
    return False, REASON_DIFFERENT_ROLE


def _cross_language(left: _Record, right: _Record) -> bool:
    """Tell whether two titles are written in two different known languages."""
    language_left = _title_language(left.raw_title)
    language_right = _title_language(right.raw_title)
    if not language_left or not language_right:
        return False
    return language_left != language_right


def _shared_specific_token(left: _Record, right: _Record) -> bool:
    """Tell whether two titles share at least one word that names a job."""
    return bool(_specific_tokens(left.title) & _specific_tokens(right.title))


def _titles_are_compatible(left: _Record, right: _Record) -> bool:
    """Tell whether two titles can describe the same posting.

    Two known business concepts that differ describe two different jobs
    (``"Software Engineer"`` and ``"Product Manager"``).  When the concept
    of one of the titles is unknown, the lexical similarity decides.

    A missing title is **not** a contradiction: a board may publish a
    posting without its title, and the other evidence then carries the
    decision.
    """
    if not left.title or not right.title:
        return True
    if left.concept and right.concept:
        return left.concept == right.concept
    similarity = _title_similarity_from_parts(
        left.title, right.title, left.concept, right.concept, left.level, right.level,
    )
    return similarity >= TITLE_SIMILARITY_THRESHOLD


def match_records(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """Determine if two records represent the same job posting.

    The decision is pure and deterministic: the same two records always give
    the same answer, whatever the order in which they are given.

    Returns a dictionary with:

    - ``matches``: whether the two records describe the same offer;
    - ``reasons``: the reason of the decision (a match reason, or the
      conflict that refused the merge);
    - ``conflicts``: the conflicts that refused the merge (empty on a match).
    """
    left = _build_record(0, a)
    right = _build_record(1, b)
    return _match_records(left, right)


def _match_records(
    left: _Record,
    right: _Record,
    text_similarity: Callable[[str, str], float] | None = None,
) -> dict[str, Any]:
    """Decide whether two records describe the same offer."""
    def refuse(reason: str) -> dict[str, Any]:
        return {"matches": False, "reasons": [reason], "conflicts": [reason]}

    def accept(reasons: list[str]) -> dict[str, Any]:
        return {"matches": True, "reasons": reasons, "conflicts": []}

    # 1. External identifier.  A board that reuses its identifier for two
    #    different postings keeps the two offers apart.
    shared_source_id = (
        bool(left.source_id)
        and left.source_id == right.source_id
        and left.source_name == right.source_name
    )
    if shared_source_id and (
        left.title != right.title
        or (
            left.canonical_url
            and right.canonical_url
            and _canonical_path(left.canonical_url) != _canonical_path(right.canonical_url)
        )
    ):
        return refuse(REASON_RECYCLED_ID)
    shared_external_id = (
        bool(left.external_id)
        and left.external_id == right.external_id
        and not shared_source_id
    )

    # 2. Company.  Two different employers are never the same offer.
    if left.company and right.company and left.company != right.company:
        return refuse(REASON_COMPANY)

    # 3. Role level.  A stage and a permanent analyst role are two jobs.
    if left.level and right.level and left.level != right.level:
        return refuse(REASON_ROLE_LEVEL)

    # 4. Cohort.  Two titles carrying different digits describe two
    #    different editions of the same programme.
    if left.digits and right.digits and left.digits != right.digits:
        return refuse(REASON_COHORT)

    # 5. Start date.  Two offers that start in two different months are two
    #    different editions of the same programme.
    start_left = _start_month(left.job.get("start_date"))
    start_right = _start_month(right.job.get("start_date"))
    if start_left and start_right and start_left != start_right:
        return refuse(REASON_START_DATE)

    # 6. Identifiers and links: they prove the two records describe the
    #    same posting.  A contradiction on the city or on the dates stays
    #    visible in the group, it does not refuse the merge.
    proofs: list[str] = []
    if shared_external_id or shared_source_id:
        proofs.append(REASON_EXTERNAL_ID)
    link_proofs: list[str] = []
    if left.canonical_url and left.canonical_url == right.canonical_url:
        link_proofs.append(REASON_CANONICAL_URL)
    if left.apply_url and left.apply_url == right.apply_url:
        link_proofs.append(REASON_APPLY_URL)
    if link_proofs and not _titles_are_compatible(left, right):
        # The two records share a link but name two different roles.  One
        # link can host several postings (a careers landing page), so the
        # link is not a proof on its own: the decision continues with the
        # location and the title, which refuse the merge when they must.
        link_proofs = []
    proofs.extend(link_proofs)
    if proofs:
        return accept(proofs)

    # 7. Location.  Two different cities are two different offers, except
    #    for a fully remote offer, which has no city at all.
    if not _same_location(left.city, left.country, right.city, right.country):
        return refuse(REASON_CITY)

    # 8. Title.  The business concept, then the text similarity.
    same_title, reason = _title_decision(left, right, text_similarity)
    if not same_title:
        return refuse(reason)
    if reason == REASON_CONCEPT:
        return accept([REASON_CONCEPT])
    return accept([REASON_CLUSTER])


# ---------------------------------------------------------------------------
# 9. Clustering
# ---------------------------------------------------------------------------

class _UnionFind:
    """Minimal union-find used to build the clusters deterministically."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        # The lowest index always wins so the result never depends on the
        # order in which the pairs were compared.
        if left_root < right_root:
            self._parent[right_root] = left_root
        else:
            self._parent[left_root] = right_root


def _blocking_keys(record: _Record) -> set[str]:
    """Return the keys used to find the candidate duplicates of a record.

    Two titles that are very similar share a word, a prefix or a business
    concept; blocking on those keys keeps the comparison count low even on
    several hundred offers.
    """
    keys: set[str] = set()
    for token in record.title.split():
        if len(token) >= 3:
            keys.add(f"word:{token}")
    letters = re.sub(r"[^a-z0-9]", "", record.title)
    if len(letters) >= 5:
        keys.add(f"prefix:{letters[:5]}")
    if record.concept:
        keys.add(f"concept:{record.concept}")
    return keys


def _candidate_pairs(indexes: list[int], records: list[_Record]) -> list[tuple[int, int]]:
    """Return the pairs of records that may describe the same offer."""
    postings: dict[str, list[int]] = {}
    for index in indexes:
        for key in _blocking_keys(records[index]):
            postings.setdefault(key, []).append(index)
    pairs: set[tuple[int, int]] = set()

    def add_pair(left: int, right: int) -> None:
        # Records sharing the same canonical title are merged by the
        # pre-pass of the clustering: they never need a pairwise comparison.
        if records[left].title == records[right].title:
            return
        pairs.add((left, right) if left < right else (right, left))

    for key in sorted(postings):
        members = postings[key]
        if len(members) < 2:
            continue
        if len(members) <= 40:
            for position in range(1, len(members)):
                for other in range(position):
                    add_pair(members[other], members[position])
            continue
        # A very common key carries little information: the members are split
        # on the digits they carry so different cohorts never compare.
        groups: dict[str, list[int]] = {}
        for index in members:
            groups.setdefault(records[index].digits, []).append(index)
        signatures = sorted(groups)
        for position, signature in enumerate(signatures):
            group = groups[signature]
            for member in range(1, len(group)):
                for other in range(member):
                    add_pair(group[other], group[member])
            for other_signature in signatures[position + 1:]:
                if signature and other_signature:
                    continue
                for left in groups[signature]:
                    for right in groups[other_signature]:
                        add_pair(left, right)
    return sorted(pairs)


def _titles_can_match(left: _Record, right: _Record) -> bool:
    """Cheap checks run before the costly title similarity.

    They only remove pairs that can never reach the clustering threshold:
    incompatible roles, different digits (cohort, edition, duration),
    different start months (two editions of the same programme) and titles
    whose lengths make a Jaro-Winkler score of 0.92 unreachable.
    """
    if left.level and right.level and left.level != right.level:
        return False
    if left.digits and right.digits and left.digits != right.digits:
        return False
    start_left = _start_month(left.job.get("start_date"))
    start_right = _start_month(right.job.get("start_date"))
    if start_left and start_right and start_left != start_right:
        return False
    same_concept = bool(left.concept and right.concept and left.concept == right.concept)
    if not same_concept:
        shortest = min(len(left.title), len(right.title))
        longest = max(len(left.title), len(right.title))
        if not shortest or shortest < MIN_LENGTH_RATIO * longest:
            return False
    return True


def _cluster_records(
    records: list[_Record],
    text_similarity: Callable[[str, str], float] | None = None,
) -> tuple[list[list[int]], dict[int, list[str]]]:
    """Group the records that describe the same offer.

    Returns the clusters (list of record indexes) and the match reason of
    every merged pair.
    """
    union = _UnionFind(len(records))
    reasons: dict[int, list[str]] = {}

    def merge(left: int, right: int, reason: str) -> None:
        union.union(left, right)
        bucket = reasons.setdefault(min(left, right), [])
        if reason not in bucket:
            bucket.append(reason)

    # Level 1 — external identifier published by the connector.
    by_external: dict[str, list[int]] = {}
    for record in records:
        if record.external_key:
            by_external.setdefault(record.external_key, []).append(record.index)
    for key in sorted(by_external):
        indexes = by_external[key]
        for position in range(1, len(indexes)):
            left, right = indexes[0], indexes[position]
            if _match_records(records[left], records[right], text_similarity)["matches"]:
                merge(left, right, REASON_EXTERNAL_ID)

    # Level 2 — canonical URL (official link first, application link second).
    by_url: dict[str, list[int]] = {}
    for record in records:
        for url in (record.canonical_url, record.apply_url):
            if url:
                by_url.setdefault(url, []).append(record.index)
                break
    for key in sorted(by_url):
        indexes = by_url[key]
        for position in range(1, len(indexes)):
            left, right = indexes[0], indexes[position]
            # The link proves the two records describe the same posting.  A
            # recycled identifier, another employer or another role still
            # keeps them apart.
            if not _match_records(records[left], records[right], text_similarity)["matches"]:
                continue
            merge(left, right, REASON_CANONICAL_URL)

    # Level 3 — company + title + location clustering.
    buckets: dict[tuple[str, str], list[int]] = {}
    for record in records:
        if not record.company or not record.title:
            continue
        buckets.setdefault((record.company, record.city), []).append(record.index)
    for bucket_key in sorted(buckets):
        indexes = buckets[bucket_key]
        # Same company, same location and same canonical title: the same
        # offer.  This pre-pass keeps the pairwise comparisons bounded when a
        # board publishes hundreds of identical postings.
        by_title: dict[str, list[int]] = {}
        for index in indexes:
            by_title.setdefault(records[index].title, []).append(index)
        for title_key in sorted(by_title):
            members = by_title[title_key]
            for position in range(1, len(members)):
                left, right = members[0], members[position]
                if not _titles_can_match(records[left], records[right]):
                    continue
                if not _same_location(
                    records[left].city, records[left].country,
                    records[right].city, records[right].country,
                ):
                    continue
                merge(left, right, "identical_title")
        for left, right in _candidate_pairs(indexes, records):
            if union.find(left) == union.find(right):
                continue
            if records[left].title == records[right].title:
                # Already handled by the pre-pass above.
                continue
            if not _same_location(
                records[left].city, records[left].country,
                records[right].city, records[right].country,
            ):
                continue
            if not _titles_can_match(records[left], records[right]):
                continue
            decision = _match_records(records[left], records[right], text_similarity)
            if not decision["matches"]:
                continue
            merge(left, right, decision["reasons"][0])

    clusters: dict[int, list[int]] = {}
    for record in records:
        clusters.setdefault(union.find(record.index), []).append(record.index)
    ordered = [sorted(indexes) for indexes in clusters.values()]
    ordered.sort(key=lambda indexes: indexes[0])
    return ordered, reasons


# ---------------------------------------------------------------------------
# 10. Election of the representative and contradictions
# ---------------------------------------------------------------------------

#: Fields compared to detect a contradiction between the merged records.
CONFLICT_FIELDS = (
    "posted_date", "city", "country", "title", "role_level",
    "employment_type", "duration_months", "start_date", "end_date",
)


def _record_completeness(record: Mapping[str, Any]) -> int:
    """Return the number of facts the record carries about the offer.

    The fields that belong to the reader (the relevance score, a personal
    note, a shortlist, an application) are **excluded**: they say nothing
    about the offer, so they must never make one version of a merged offer
    look better than another one.
    """
    return sum(
        1
        for key, value in record.items()
        if key.lower() not in USER_SIDE_FIELDS and value not in (None, "", [], {})
    )


def _record_weight(record: Mapping[str, Any]) -> tuple[int, int, float, int, int, int]:
    """Return the election weight of a record (the highest one wins).

    The order is: trust of the source (SPEC-SK-01), tier of the source
    (employer page before board), freshness, priority of the source,
    connector verification and completeness of the record.

    The relevance score of the user never appears here: how well an offer
    matches one person says nothing about whether two records describe the
    same posting.
    """
    source_name = _clean_text(record.get("source_name"), 80)
    trust = TRUST_RANK.get(_record_trust(record), TRUST_RANK["missing"])
    tier = _source_tier(source_name, record)
    freshness = _freshness(record)
    priority = source_priority(source_name)
    verified = 1 if record.get("source_verified") else 0
    completeness = _record_completeness(record)
    return (trust, tier, freshness, priority, verified, completeness)


def choose_best(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Choose the record that represents a merged group.

    The official source stays the primary one: a record whose source is
    verified (SPEC-SK-01) wins before anything else, then the employer page
    before the boards, then the freshest record, then the source priority.

    The user relevance score is never read: it cannot decide which view of
    the offer survives.
    """
    if not records:
        raise ValueError("choose_best() needs at least one record.")
    return max(records, key=_record_weight)


def _detect_conflicts(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """Detect the contradictory facts between the records of a group.

    A contradiction never prevents a merge: it stays visible so that the
    person can see that two sources disagree on the date or on the city.
    """
    conflicts: dict[str, dict[str, str]] = {}
    for field_name in CONFLICT_FIELDS:
        values: dict[str, str] = {}
        seen_keys: dict[str, int] = {}
        for record in records:
            value = record.get(field_name)
            if value in (None, "", [], {}):
                continue
            base_key = f"{record.get('source_name', '')}:{record.get('source_id', '')}"
            if base_key in seen_keys:
                seen_keys[base_key] += 1
                key = f"{base_key}#{seen_keys[base_key] + 1}"
            else:
                key = base_key
                seen_keys[base_key] = 0
            values[key] = str(value)
        if len(set(values.values())) > 1:
            conflicts[field_name] = values
    return conflicts


# ---------------------------------------------------------------------------
# 11. Groups
# ---------------------------------------------------------------------------

def _dedup_id(record: Mapping[str, Any]) -> str:
    """Return the stable storage identity of a record."""
    source_name = _clean_text(record.get("source_name"), 80)
    source_id = _clean_text(record.get("source_id"), 240)
    official_url = _clean_text(record.get("official_url") or record.get("url"), 2_000)
    if source_id and _source_key(source_name) not in MANUAL_SOURCES:
        return f"source:{_source_key(source_name)}:{source_id}"
    if official_url:
        return f"url:{canonicalize_url(official_url)}"
    pieces = (
        _strip_accents(_clean_text(record.get("company"), 240)).lower(),
        _strip_accents(_clean_text(record.get("title"), 300)).lower(),
        _strip_accents(_clean_text(record.get("city"), 120)).lower(),
    )
    return "manual:" + "|".join(re.sub(r"[^\w\s]+", " ", piece).strip() for piece in pieces)


def _provenance(record: Mapping[str, Any], weight: int, is_representative: bool) -> dict[str, Any]:
    """Return the trace of one source of a merged group."""
    return {
        "source_name": _clean_text(record.get("source_name"), 80),
        "source_id": _clean_text(record.get("source_id"), 240),
        "official_url": _clean_text(record.get("official_url") or record.get("url"), 2_000),
        "apply_url": _clean_text(record.get("apply_url"), 2_000),
        "trust": _record_trust(record),
        "weight": weight,
        "is_representative": is_representative,
        "record": record,
    }


def _build_groups(
    records: list[_Record],
    text_similarity: Callable[[str, str], float] | None = None,
) -> list[dict[str, Any]]:
    """Build the deduplicated groups of a collection of offers."""
    clusters, reasons = _cluster_records(records, text_similarity)
    groups: list[dict[str, Any]] = []
    for indexes in clusters:
        members = [records[index] for index in indexes]
        best = choose_best([member.job for member in members])
        best_record = next(member for member in members if member.job is best)
        provenances = [
            _provenance(member.job, member.priority, member.index == best_record.index)
            for member in members
        ]
        # The trace starts with the elected representative (the official
        # source stays the primary one), then the trusted sources, then the
        # source priority.
        provenances.sort(key=lambda view: (
            not view["is_representative"],
            -TRUST_RANK.get(view["trust"], TRUST_RANK["missing"]),
            -view["weight"],
            view["source_name"],
            view["source_id"],
        ))
        merged_from: list[str] = []
        for member in members:
            if member.index == best_record.index:
                continue
            name = member.source_name
            if name and name not in merged_from:
                merged_from.append(name)
        cluster_reasons: list[str] = []
        for index in indexes:
            for reason in reasons.get(index, []):
                if reason not in cluster_reasons:
                    cluster_reasons.append(reason)
        for left_index in indexes:
            for right_index in indexes:
                if left_index >= right_index:
                    continue
                decision = _match_records(records[left_index], records[right_index], text_similarity)
                if decision["matches"]:
                    for reason in decision["reasons"]:
                        if reason not in cluster_reasons:
                            cluster_reasons.append(reason)
        groups.append({
            "dedup_id": _dedup_id(best),
            "merged": len(members) > 1,
            "best": best,
            "provenances": provenances,
            "conflicts": _detect_conflicts([member.job for member in members]),
            "match_reasons": cluster_reasons,
            "merged_from": merged_from,
            "sources": sorted({member.source_name for member in members if member.source_name}),
            "identifier_collision": False,
            "member_indexes": list(indexes),
        })
    _flag_identifier_collisions(groups)
    return groups


def _flag_identifier_collisions(groups: list[dict[str, Any]]) -> None:
    """Flag the groups whose identifier was recycled by its source.

    A recycled identifier means the board reused the same id for two
    different postings: the two offers stay apart and the groups are
    flagged so that the reader knows why.
    """
    seen: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    for group_index, group in enumerate(groups):
        for view in group["provenances"]:
            source_id = view["source_id"]
            if not source_id:
                continue
            key = f"{view['source_name']}:{source_id}"
            record = view["record"]
            content = (
                _clean_text(record.get("title"), 300),
                _clean_text(record.get("city"), 120),
            )
            seen.setdefault(key, []).append((group_index, content))
    for entries in seen.values():
        group_indexes = {group_index for group_index, _content in entries}
        if len(group_indexes) < 2:
            continue
        if len({content for _group, content in entries}) < 2:
            continue
        for group_index in sorted(group_indexes):
            groups[group_index]["identifier_collision"] = True


# ---------------------------------------------------------------------------
# 12. Public API
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DedupReport:
    """Audit report of a deduplication run.

    Attributes:
        merged_count: Number of duplicate offers merged away (received
            offers minus unique offers).
        clusters: One entry per merge (only the clusters of two offers or
            more) with the representative, its members, the sources and the
            reasons of the merge.
        representatives: Identity of the representative of every unique
            offer.
        total_count: Number of offers received.
        unique_count: Number of offers returned.
        merged_clusters: Number of clusters that contained several offers.
        conflicts: Number of groups that keep a visible contradiction.
    """

    merged_count: int
    clusters: list[dict[str, Any]] = field(default_factory=list)
    representatives: list[str] = field(default_factory=list)
    total_count: int = 0
    unique_count: int = 0
    merged_clusters: int = 0
    conflicts: int = 0


def deduplicate_jobs(
    jobs: Sequence[Mapping[str, Any]],
    *,
    text_similarity: Callable[[str, str], float] | None = None,
) -> list[dict[str, Any]]:
    """Deduplicate the offers collected from every source.

    The function is pure: the received dictionaries are never modified and
    the groups keep the original records so that every source stays
    consultable.

    Args:
        jobs: Offer records collected from every source.
        text_similarity: Optional callable returning the similarity of two
            titles (an embedding model, for instance).  It is only used as an
            additional signal; the default decision stays lexical.

    Returns:
        One group per unique offer.  A group carries the elected
        representative (``best``), every provenance (``provenances``), the
        contradictions between the sources (``conflicts``) and the reasons of
        the merge (``match_reasons``).
    """
    if not jobs:
        return []
    records = [_build_record(index, job) for index, job in enumerate(jobs)]
    return _build_groups(records, text_similarity)


def deduplicate_offers(
    jobs: Sequence[Mapping[str, Any]],
    *,
    text_similarity: Callable[[str, str], float] | None = None,
) -> tuple[list[Job], DedupReport]:
    """Merge the duplicate offers and return the merged offers with a report.

    Every returned offer is a new dictionary: the records received are never
    modified.  A merged offer carries the trace of its sources in
    ``merged_from`` (the name of every absorbed source) and in
    ``merged_provenances`` (one entry per source, with its link, its
    identifier and its trust, so that a secondary source stays consultable).

    Args:
        jobs: Offer records collected from every source.
        text_similarity: Optional callable returning the similarity of two
            titles (an embedding model, for instance).  It is only used as an
            additional signal; the default decision stays lexical.

    Returns:
        A tuple with the deduplicated offers and the :class:`DedupReport`
        describing the merges.
    """
    groups = deduplicate_jobs(jobs, text_similarity=text_similarity)

    unique_jobs: list[Job] = []
    report_clusters: list[dict[str, Any]] = []
    representatives: list[str] = []
    conflicts = 0

    for group in groups:
        best = group["best"]
        merged_job: Job = dict(best)
        merged_job[MERGED_FROM_FIELD] = list(group["merged_from"])
        merged_job[MERGED_PROVENANCES_FIELD] = [
            {
                "source_name": view["source_name"],
                "source_id": view["source_id"],
                "official_url": view["official_url"],
                "apply_url": view["apply_url"],
                "trust": view["trust"],
                "is_representative": view["is_representative"],
            }
            for view in group["provenances"]
        ]
        if group["merged"]:
            merged_job["merge_count"] = len(group["provenances"]) - 1
            merged_job["dedup_id"] = group["dedup_id"]
            merged_job["merge_reasons"] = list(group["match_reasons"])
            report_clusters.append({
                "cluster_id": group["dedup_id"],
                "representative_id": group["dedup_id"],
                "member_ids": [view["source_id"] or view["official_url"] for view in group["provenances"]],
                "sources": list(group["sources"]),
                "reasons": list(group["match_reasons"]),
                "size": len(group["provenances"]),
                "conflicts": list(group["conflicts"]),
            })
        if group["conflicts"]:
            conflicts += 1
        unique_jobs.append(merged_job)
        representatives.append(group["dedup_id"])

    report = DedupReport(
        merged_count=len(jobs) - len(unique_jobs),
        clusters=report_clusters,
        representatives=representatives,
        total_count=len(jobs),
        unique_count=len(unique_jobs),
        merged_clusters=len(report_clusters),
        conflicts=conflicts,
    )
    return unique_jobs, report


def evaluate_deduplication(
    records: Sequence[Mapping[str, Any]],
    truth: Mapping[int, str],
) -> dict[str, float]:
    """Evaluate the deduplication against a ground truth.

    Args:
        records: The offers to group.
        truth: The expected group of every record, by index.

    Returns:
        A dictionary with the precision, the recall, the F1 score, the
        number of true pairs and the number of wrong pairs.
    """
    groups = deduplicate_jobs(records)

    predicted_pairs: set[tuple[int, int]] = set()
    for group in groups:
        indexes = group["member_indexes"]
        for position in range(len(indexes)):
            for other in range(position + 1, len(indexes)):
                predicted_pairs.add(tuple(sorted((indexes[position], indexes[other]))))

    true_pairs: set[tuple[int, int]] = set()
    for first in truth:
        for second in truth:
            if first < second and truth[first] == truth[second]:
                true_pairs.add((first, second))

    true_positive = len(predicted_pairs & true_pairs)
    false_positive = len(predicted_pairs - true_pairs)
    false_negative = len(true_pairs - predicted_pairs)

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 1.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_pairs": float(true_positive),
        "error_pairs": float(false_positive + false_negative),
    }


__all__ = [
    "CONCEPT_MATCH_SIMILARITY",
    "CONFLICT_FIELDS",
    "DedupReport",
    "Job",
    "MERGED_FROM_FIELD",
    "MERGED_PROVENANCES_FIELD",
    "ROLE_CONFLICT_SIMILARITY",
    "SOURCE_PRIORITY",
    "TITLE_SIMILARITY_THRESHOLD",
    "TRUST_RANK",
    "TRUST_STATUSES",
    "USER_SCORE_FIELDS",
    "USER_SIDE_FIELDS",
    "USER_STATE_FIELDS",
    "canonical_city",
    "canonical_company",
    "canonical_title_concept",
    "canonicalize_url",
    "choose_best",
    "company_canonical",
    "deduplicate_jobs",
    "deduplicate_offers",
    "evaluate_deduplication",
    "jaro_winkler",
    "location_canonical",
    "match_records",
    "source_priority",
    "title_canonical",
    "title_concept",
    "title_contract",
    "title_role_level",
    "title_seniority",
    "title_similarity",
]
