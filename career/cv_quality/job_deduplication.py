"""Robust multi-source job deduplication (Mission CVBOOST-07).

The same internship offer is published on several public boards (Greenhouse,
Ashby, Lever, Welcome to the Jungle, JobTeaser, Talent.com, APEC).  This
module merges those true duplicates **without ever fusing two different
roles**.

Everything here is pure, local and deterministic: no network call, no model,
no external dependency, no hidden state.  The same input always produces the
same output and the received records are never modified.

Four key levels are applied, in order:

1. ``external_id`` — identifier published by the connector (primary key).
2. ``canonical_url`` — normalised job URL (https, no ``www.``, no tracking
   query parameters, no fragment, single trailing slash).
3. clustering — ``(company_canonical, title_canonical, location_canonical)``
   with a Jaro-Winkler similarity of at least 0.92 on the title.
4. freshness — the most recent ``posted_date`` / ``discovered_at`` wins.

Each merged offer keeps a ``merged_from`` trace (source names) for audit.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

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

#: Key of the traceability field carried by a deduplicated offer: the names
#: of the sources merged into it (empty when the offer comes from a single
#: source).  The local job table has no column for it — its schema is frozen
#: and no migration is allowed — so the trace travels with the offer
#: dictionary and with the merge report.
MERGED_FROM_FIELD = "merged_from"


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    """Remove diacritics without changing the rest of the string."""
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
    "gh_src", "lever-source", "lever-origin", "origin",
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
    raw = _clean_text(url, 2_000)
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
COMPANY_DROPPED_WORDS = frozenset(LEGAL_COMPANY_SUFFIXES) | {"and"}

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
}


def company_canonical(name: str) -> str:
    """Return the canonical form of a company name.

    Lower-cased, accents removed, punctuation turned into spaces, known
    aliases applied and legal suffixes (``SA``, ``SAS``, ``Ltd``, ``Inc``,
    ``GmbH``, ``AG``, ``SRL``, ``SpA``, ``BV``, ``NV``, ``PLC``, ``Group``,
    ``Groupe``…) removed as whole words.
    """
    text = _strip_accents(_company_text(name)).lower()
    text = _squash(re.sub(r"[^\w\s]", " ", text))
    if not text:
        return ""
    text = COMPANY_ALIASES.get(text, text)
    text = " ".join(word for word in text.split() if word not in COMPANY_DROPPED_WORDS)
    text = _squash(text)
    # A second pass catches the spellings that only match once the legal
    # suffix is gone ("Goldman Sachs Group" -> "Goldman Sachs").
    return COMPANY_ALIASES.get(text, text)


# ---------------------------------------------------------------------------
# 3. Canonical title, business concepts, contracts and seniority
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
     r"|\bgestionnaire de portefeuille\b|\bportfolio management\b|\binvestment research"
     r"|\bequity research\b|\bfixed income\b",
     "asset_management"),
    (r"\bsales and trading\b|\bsales & trading\b|\bglobal markets\b|\bmarkets off cycle"
     r"|\bfixed income sales\b|\bequity sales\b|\btrading\b",
     "sales_trading"),
    (r"\bcorporate finance\b|\bfinance entreprise\b|\bfinancial analysis\b|\banalyse financiere"
     r"|\banalyste financier\b|\bvaluation\b|\btreasury\b|\bstrategic finance\b|\bfp a\b"
     r"|\bplanning analytique\b|\bcontrole de gestion\b|\bbusiness partner\b",
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
     r"|\bdevops\b|\bdata engineer\b|\bml engineer\b|\bmachine learning\b",
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

#: Contract markers of a title (the kind of engagement, not the seniority).
TITLE_CONTRACT_SOURCES = (
    ("intern", r"\b(stage|stages|stagi|stagiaire|stagiaires|intern|interns|internship|trainee"
              r"|traineeship|praktikum|tirocinio)\b"),
    ("apprentice", r"\b(alternance|apprentissage|apprentice|apprenticeship|apprenti|apprentis"
                   r"|working student|werkstudent)\b"),
    ("permanent", r"\b(cdi|permanent)\b"),
    ("fixed_term", r"\b(cdd|fixed term|contractuel|temporaire|temporary)\b"),
    ("freelance", r"\b(freelance|independant)\b"),
)

#: One alternation for every contract marker.
TITLE_CONTRACT_RE = re.compile(
    "|".join(f"(?P<{name}>{source})" for name, source in TITLE_CONTRACT_SOURCES),
    re.IGNORECASE,
)

#: Contract of every group of :data:`TITLE_CONTRACT_RE`.
TITLE_CONTRACT_BY_GROUP = {name: name for name, _source in TITLE_CONTRACT_SOURCES}

#: Seniority markers of a title.
TITLE_SENIORITY_RE = re.compile(
    r"(?P<analyst>\b(analyst|analyste|analystes)\b)"
    r"|(?P<experienced>\b(senior|lead|head|director|directeur|manager|partner|principal|vp|md"
    r"|managing director)\b)",
    re.IGNORECASE,
)

#: Role levels accepted when a connector states them explicitly.
KNOWN_ROLE_LEVELS = frozenset({
    "intern", "apprentice", "analyst", "experienced", "permanent", "fixed_term", "freelance",
})

#: Explicit role levels mapped to the contract dimension.
ROLE_LEVEL_CONTRACTS = {
    "intern": "intern",
    "apprentice": "apprentice",
    "permanent": "permanent",
    "fixed_term": "fixed_term",
    "freelance": "freelance",
}

#: Explicit role levels mapped to the seniority dimension.
ROLE_LEVEL_SENIORITIES = {
    "analyst": "analyst",
    "experienced": "experienced",
}

#: Small words that carry no meaning when two titles are compared.
TITLE_STOPWORDS = frozenset({
    "en", "de", "du", "des", "la", "le", "les", "au", "aux", "un", "une",
    "the", "of", "for", "and", "on", "in", "at", "with", "a",
})


def _strip_title_noise(text: str) -> str:
    """Remove the French ``H/F`` and ``F/H`` gender markers."""
    without_gender = re.sub(r"\b[hf]\s*[/\-]\s*[hf]\b", " ", text)
    return re.sub(r"\bx\s*[hf]\b", " ", without_gender)


def _raw_title_text(title: str) -> str:
    """Return the lower-cased, accent-free title, punctuation preserved."""
    return _strip_accents(_clean_text(title, 300)).lower().replace("’", "'")


def _title_base(title: str) -> str:
    """Return the lower-cased, accent-free title, punctuation turned into spaces."""
    text = _strip_title_noise(_raw_title_text(title))
    text = re.sub(r"[^\w\s]", " ", text)
    return _squash(text)


def _title_canonical_from_base(base: str) -> str:
    """Return the canonical title of an already normalised title."""
    text = base
    for phrase, replacement in TITLE_PHRASE_SYNONYMS:
        if phrase in text:
            text = text.replace(phrase, replacement)
    words = [TITLE_WORD_SYNONYMS.get(word, word) for word in text.split()]
    return _squash(" ".join(words))


def title_canonical(title: str) -> str:
    """Return the canonical form of a job title.

    Lower-cased, accents removed, punctuation turned into spaces and the
    known synonyms applied (``stage``/``intern`` → ``internship``,
    ``CDI``/``permanent`` → ``permanent``,
    ``alternance``/``apprentissage`` → ``apprenticeship``).
    """
    return _title_canonical_from_base(_title_base(title))


def _title_concept_from_raw(raw: str) -> str:
    """Return the business concept of an already normalised title."""
    match = TITLE_CONCEPT_RE.search(raw)
    if match is None:
        return ""
    group = match.lastgroup
    if group is None:
        return ""
    return TITLE_CONCEPT_BY_GROUP.get(group, "")


def title_concept(title: str) -> str:
    """Return the business concept of a title (``""`` when unknown)."""
    return _title_concept_from_raw(_raw_title_text(title))


def _title_contract_from_base(base: str) -> str:
    """Return the contract of an already normalised title."""
    match = TITLE_CONTRACT_RE.search(base)
    if match is not None:
        return TITLE_CONTRACT_BY_GROUP.get(match.lastgroup or "", "")
    # A job title that names a permanent role ("Data Analyst") and no other
    # contract marker describes a permanent position.
    if TITLE_SENIORITY_RE.search(base):
        return "permanent"
    return ""


def _title_seniority_from_base(base: str) -> str:
    """Return the seniority of an already normalised title."""
    match = TITLE_SENIORITY_RE.search(base)
    if match is None:
        return ""
    return match.lastgroup or ""


def title_contract(title: str) -> str:
    """Return the contract of a title ("" when unknown).

    Contract: ``intern``, ``apprentice``, ``permanent``, ``fixed_term`` or
    ``freelance``.
    """
    return _title_contract_from_base(_title_base(title))


def title_seniority(title: str) -> str:
    """Return the seniority of a title ("" when unknown).

    Seniority: ``analyst`` or ``experienced``.
    """
    return _title_seniority_from_base(_title_base(title))


def title_role_level(title: str) -> str:
    """Return the role level of a title ("" when unknown).

    The contract comes first (``intern``, ``apprentice``, ``permanent``,
    ``fixed_term``, ``freelance``); otherwise the seniority (``analyst``,
    ``experienced``) is returned.
    """
    contract = title_contract(title)
    if contract:
        return contract
    return title_seniority(title)


def _sorted_title(canonical_title: str) -> str:
    """Return the canonical title with its words sorted."""
    return " ".join(sorted(canonical_title.split()))


def _content_tokens(canonical_title: str) -> tuple[str, ...]:
    """Return the meaningful words of a canonical title, sorted."""
    return tuple(
        token for token in sorted(canonical_title.split())
        if token not in TITLE_STOPWORDS
    )


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


def _record_role_level(job: Mapping[str, Any], base: str) -> tuple[str, str]:
    """Return the (contract, seniority) of a record.

    The role level stated by the connector wins; otherwise both dimensions
    are read from the title.
    """
    stated = _clean_text(job.get("role_level"), 40).lower().replace(" ", "_").replace("-", "_")
    if stated in KNOWN_ROLE_LEVELS:
        contract = ROLE_LEVEL_CONTRACTS.get(stated, "")
        seniority = ROLE_LEVEL_SENIORITIES.get(stated, "")
        if contract or seniority:
            return contract, seniority
    return _title_contract_from_base(base), _title_seniority_from_base(base)


def _roles_conflict(contract_a: str, seniority_a: str, contract_b: str, seniority_b: str) -> bool:
    """Tell whether two titles describe incompatible roles."""
    if contract_a and contract_b and contract_a != contract_b:
        return True
    return bool(seniority_a and seniority_b and seniority_a != seniority_b)


def _title_similarity_from_parts(
    canonical_a: str,
    canonical_b: str,
    concept_a: str,
    concept_b: str,
    contract_a: str,
    contract_b: str,
    seniority_a: str,
    seniority_b: str,
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
    if _roles_conflict(contract_a, seniority_a, contract_b, seniority_b):
        score = min(score, ROLE_CONFLICT_SIMILARITY)
    return round(score, 6)


def title_similarity(title_a: str, title_b: str) -> float:
    """Return the similarity of two job titles, between 0.0 and 1.0.

    The score combines the Jaro-Winkler similarity of the canonical titles
    with the business concept mapping (a translated title such as
    ``"Analyste de données"`` matches ``"Data Analyst"``).

    Two titles describing incompatible roles (a stage and a permanent
    analyst role) are capped far below the clustering threshold: they are
    two different jobs, never a duplicate.
    """
    raw_a = _raw_title_text(title_a)
    raw_b = _raw_title_text(title_b)
    base_a = _title_base(title_a)
    base_b = _title_base(title_b)
    return _title_similarity_from_parts(
        _title_canonical_from_base(base_a),
        _title_canonical_from_base(base_b),
        _title_concept_from_raw(raw_a),
        _title_concept_from_raw(raw_b),
        _title_contract_from_base(base_a),
        _title_contract_from_base(base_b),
        _title_seniority_from_base(base_a),
        _title_seniority_from_base(base_b),
    )


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
    "geneve": "geneva",
    "new york city": "new york",
    "nyc": "new york",
    "bruxelles": "brussels",
    "zuerich": "zurich",
    "munchen": "munich",
    "lisbonne": "lisbon",
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
    "belgium": "be", "belgique": "be", "be": "be",
    "switzerland": "ch", "suisse": "ch", "ch": "ch",
    "luxembourg": "lu", "lu": "lu",
    "ireland": "ie", "irlande": "ie", "ie": "ie",
    "austria": "at", "autriche": "at", "at": "at",
    "poland": "pl", "pologne": "pl", "pl": "pl",
    "sweden": "se", "suede": "se", "se": "se",
    "denmark": "dk", "danemark": "dk", "dk": "dk",
    "norway": "no", "norvege": "no", "no": "no",
    "finland": "fi", "finlande": "fi", "fi": "fi",
    "canada": "ca", "ca": "ca",
    "australia": "au", "au": "au",
    "singapore": "sg", "sg": "sg",
    "hong kong": "hk", "hk": "hk",
    "china": "cn", "chine": "cn", "cn": "cn",
    "india": "in", "inde": "in", "in": "in",
    "japan": "jp", "japon": "jp", "jp": "jp",
    "brazil": "br", "bresil": "br", "br": "br",
}

#: Markers of a fully remote offer.
REMOTE_MARKERS = (
    "remote", "teletravail", "a distance", "distanciel", "work from home",
    "wfh", "home office", "homeoffice", "full remote", "fully remote",
)


def _is_remote(text: str) -> bool:
    return any(marker in text for marker in REMOTE_MARKERS)


def _canonical_city(city: Any) -> str:
    """Return the normalised city name ("" when unknown)."""
    text = _strip_accents(_clean_text(city, 120)).lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^\w\s-]", " ", text)
    text = _squash(text)
    text = re.sub(r"^\d+\s+", "", text)
    if not text:
        return ""
    if _is_remote(text):
        return "remote"
    return CITY_ALIASES.get(text, text)


def _canonical_country(country: Any) -> str:
    """Return the ISO-2 country code ("" when unknown)."""
    text = _strip_accents(_clean_text(country, 120)).lower()
    text = _squash(text)
    if not text:
        return ""
    if _is_remote(text):
        return ""
    if text in COUNTRY_ISO2:
        return COUNTRY_ISO2[text]
    if len(text) == 2 and text.isalpha():
        return text
    return COUNTRY_ISO2.get(text, text[:2])


def location_canonical(city: str, country: str) -> str:
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

def jaro_winkler(s1: str, s2: str, *, prefix_scale: float = 0.1, max_prefix: int = 4) -> float:
    """Return the Jaro-Winkler similarity of two strings (0.0 to 1.0)."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if not len1 or not len2:
        return 0.0
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
# 6. Source priority (representative selection)
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
    Talent.com > APEC.  An unknown source keeps a neutral priority.
    """
    key = _source_key(source_name)
    if key in SOURCE_PRIORITY:
        return SOURCE_PRIORITY[key]
    if key in MANUAL_SOURCES:
        return 10
    return 20


# ---------------------------------------------------------------------------
# 7. Records
# ---------------------------------------------------------------------------

#: Fields read to date a record; the first parsable one wins.
FRESHNESS_FIELDS = (
    "posted_date", "discovered_at", "published_at", "last_seen_at",
    "last_verified_at", "updated_at",
)


def _parse_timestamp(raw: Any) -> float | None:
    """Parse a connector date into a UTC timestamp (None when unreadable)."""
    text = _clean_text(raw, 64)
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
    contract: str
    seniority: str
    city: str
    country: str
    digits: str
    freshness: float
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
    if record.external_id:
        return f"ext:{record.external_id}"
    if record.source_id:
        return f"source:{record.source_name}:{record.source_id}"
    if record.canonical_url:
        return f"url:{record.canonical_url}"
    digest = hashlib.sha1(
        f"{record.company}|{record.title}|{record.city}".encode("utf-8")
    ).hexdigest()[:16]
    return f"hash:{digest}"


def _build_record(index: int, job: Mapping[str, Any]) -> _Record:
    """Build the deduplication record of a job dictionary."""
    source_name = _clean_text(job.get("source_name"), 80)
    source_id = _clean_text(job.get("source_id"), 240)
    external_id, external_key = _external_identity(job, source_name, source_id)
    raw_title = _clean_text(job.get("title"), 300)
    base = _title_base(raw_title)
    contract, seniority = _record_role_level(job, base)
    canonical_title = _title_canonical_from_base(base)
    record = _Record(
        index=index,
        job=job,
        source_name=source_name,
        source_id=source_id,
        external_id=external_id,
        external_key=external_key,
        canonical_url=canonicalize_url(job.get("official_url") or job.get("url") or ""),
        apply_url=canonicalize_url(job.get("apply_url") or ""),
        company=company_canonical(job.get("company")),
        raw_title=raw_title,
        title=canonical_title,
        concept=_title_concept_from_raw(_raw_title_text(raw_title)),
        contract=contract,
        seniority=seniority,
        city=_canonical_city(job.get("city")),
        country=_canonical_country(job.get("country")),
        digits=_digit_signature(canonical_title),
        freshness=_freshness(job),
        identity="",
    )
    return replace(record, identity=_record_identity(record))


# ---------------------------------------------------------------------------
# 8. Clustering
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


def _roles_conflict_records(left: _Record, right: _Record) -> bool:
    """Tell whether two records describe incompatible roles."""
    return _roles_conflict(left.contract, left.seniority, right.contract, right.seniority)


def _external_conflict(left: _Record, right: _Record) -> bool:
    """Tell whether two records sharing an identifier are recycled ids.

    A recycled identifier means the board reused the same id for two
    different postings: the records must then stay separate.
    """
    if left.company and right.company and left.company != right.company:
        return True
    if _roles_conflict_records(left, right):
        return True
    if not left.title or not right.title:
        return False
    if left.canonical_url and right.canonical_url and left.canonical_url != right.canonical_url:
        # Same identifier, different posting link: the board recycled the id
        # unless both titles still describe the same role.
        return _title_similarity_from_parts(
            left.title, right.title, left.concept, right.concept,
            left.contract, right.contract, left.seniority, right.seniority,
        ) < TITLE_SIMILARITY_THRESHOLD
    return jaro_winkler(left.title, right.title) < 0.5


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
    incompatible roles, different digits (cohort, edition, duration) and
    titles whose lengths make a Jaro-Winkler score of 0.92 unreachable.
    """
    if _roles_conflict_records(left, right):
        return False
    digits_left = left.digits
    digits_right = right.digits
    if digits_left and digits_right and digits_left != digits_right:
        return False
    same_concept = bool(left.concept and right.concept and left.concept == right.concept)
    if not same_concept:
        shortest = min(len(left.title), len(right.title))
        longest = max(len(left.title), len(right.title))
        if not shortest or shortest < MIN_LENGTH_RATIO * longest:
            return False
    return True


def _cluster_records(records: list[_Record]) -> tuple[list[list[int]], dict[int, list[str]]]:
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
            if _external_conflict(records[left], records[right]):
                continue
            merge(left, right, "external_id")

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
            merge(indexes[0], indexes[position], "canonical_url")

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
            similarity = _title_similarity_from_parts(
                records[left].title, records[right].title,
                records[left].concept, records[right].concept,
                records[left].contract, records[right].contract,
                records[left].seniority, records[right].seniority,
            )
            if similarity < TITLE_SIMILARITY_THRESHOLD:
                continue
            merge(left, right, "company_title_location")

    clusters: dict[int, list[int]] = {}
    for record in records:
        clusters.setdefault(union.find(record.index), []).append(record.index)
    ordered = [sorted(indexes) for indexes in clusters.values()]
    ordered.sort(key=lambda indexes: indexes[0])
    return ordered, reasons


# ---------------------------------------------------------------------------
# 9. Public API
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
    """

    merged_count: int
    clusters: list[dict[str, Any]] = field(default_factory=list)
    representatives: list[str] = field(default_factory=list)
    total_count: int = 0
    unique_count: int = 0
    merged_clusters: int = 0


def _representative(records: list[_Record]) -> _Record:
    """Choose the representative of a cluster.

    Priority: an external identifier first, then the source priority
    (Ashby > Greenhouse > Lever > Welcome to the Jungle > JobTeaser >
    Talent.com > APEC), then the most recent ``posted_date`` /
    ``discovered_at``.  The first offer of the input breaks the last ties.
    """
    def sort_key(record: _Record) -> tuple[int, int, float, int]:
        return (1 if record.has_external_id else 0, record.priority, record.freshness, -record.index)

    return max(records, key=sort_key)


def deduplicate_jobs(jobs: Sequence[Mapping[str, Any]]) -> tuple[list[Job], DedupReport]:
    """Merge the duplicate offers of a multi-source collection.

    The function is pure: the received dictionaries are never modified and
    the returned list contains new dictionaries.  The same input always
    produces the same output.

    Args:
        jobs: Offer records collected from every source.

    Returns:
        A tuple with the deduplicated offers and the :class:`DedupReport`
        describing the merges.
    """
    records = [_build_record(index, job) for index, job in enumerate(jobs)]
    if not records:
        return [], DedupReport(merged_count=0, clusters=[], representatives=[], total_count=0, unique_count=0)

    clusters, reasons = _cluster_records(records)
    unique_jobs: list[Job] = []
    report_clusters: list[dict[str, Any]] = []
    representatives: list[str] = []

    for indexes in clusters:
        members = [records[index] for index in indexes]
        chosen = _representative(members)
        merged = [member for member in members if member.index != chosen.index]
        merged_sources: list[str] = []
        for member in sorted(merged, key=lambda item: (-item.priority, item.source_name, item.index)):
            if member.source_name and member.source_name not in merged_sources:
                merged_sources.append(member.source_name)
        merged_job: Job = dict(chosen.job)
        merged_job[MERGED_FROM_FIELD] = merged_sources
        if merged:
            merged_job["merge_count"] = len(merged)
            merged_job["dedup_id"] = chosen.identity
            cluster_reasons: list[str] = []
            for left_index in indexes:
                for reason in reasons.get(left_index, []):
                    if reason not in cluster_reasons:
                        cluster_reasons.append(reason)
            merged_job["merge_reasons"] = cluster_reasons
            report_clusters.append({
                "cluster_id": chosen.identity,
                "representative_id": chosen.identity,
                "member_ids": [member.identity for member in members],
                "sources": sorted({member.source_name for member in members if member.source_name}),
                "reasons": cluster_reasons,
                "size": len(members),
            })
        unique_jobs.append(merged_job)
        representatives.append(chosen.identity)

    merged_count = len(records) - len(unique_jobs)
    report = DedupReport(
        merged_count=merged_count,
        clusters=report_clusters,
        representatives=representatives,
        total_count=len(records),
        unique_count=len(unique_jobs),
        merged_clusters=len(report_clusters),
    )
    return unique_jobs, report


__all__ = [
    "CONCEPT_MATCH_SIMILARITY",
    "DedupReport",
    "Job",
    "MERGED_FROM_FIELD",
    "ROLE_CONFLICT_SIMILARITY",
    "SOURCE_PRIORITY",
    "TITLE_SIMILARITY_THRESHOLD",
    "canonicalize_url",
    "company_canonical",
    "deduplicate_jobs",
    "jaro_winkler",
    "location_canonical",
    "source_priority",
    "title_canonical",
    "title_concept",
    "title_contract",
    "title_role_level",
    "title_seniority",
    "title_similarity",
]
