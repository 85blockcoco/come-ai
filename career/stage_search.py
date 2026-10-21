"""Deterministic stage-search criteria and explainable matching for Career.

This module is a pure, local logic layer.  It never performs a network
request, never calls a model, and never invents an offer, a company or a
date: it only compares facts a person entered (their search brief) with
facts already stored locally for an offer.  Every score component carries
the reason that produced it so the ranking stays auditable.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .models import JOB_FAMILIES, clean_text, normalized_text, parse_date
from .sources import SEARCH_TERMS
from .education_access import assess_education_access
from workspace_core import UserFacingError


# The finance domains a person actually hunts for.  These are finer-grained
# than ``JOB_FAMILIES`` (which drive preferences) and deliberately lexical:
# an offer matches only through words its own posting contains.
STAGE_DOMAINS: dict[str, tuple[str, ...]] = {
    "M&A": (
        "m a",
        "mergers",
        "acquisitions",
        "fusion acquisition",
        "fusions acquisitions",
        "investment banking",
        "banque d affaires",
        "corporate finance advisory",
    ),
    "Corporate Finance": (
        "corporate finance",
        "finance d entreprise",
        "finance intern",
        "finance analyst",
        "financial analysis",
        "analyse financiere",
        "valuation",
        "treasury",
        "strategic finance",
    ),
    "Private Equity": (
        "private equity",
        "capital investissement",
        "capital developpement",
        "fonds d investissement",
        "buyout",
        "growth equity",
        "lbo",
    ),
    "Transaction Services": (
        "transaction services",
        "transaction advisory",
        "deals advisory",
        "due diligence",
        "financial due diligence",
        "fdd",
    ),
    "Audit financier": (
        "audit",
        "audit financier",
        "financial audit",
        "statutory audit",
        "controle externe",
        "commissariat aux comptes",
    ),
    "Asset Management": (
        "asset management",
        "gestion d actifs",
        "societe de gestion",
        "gestionnaire de portefeuille",
        "portfolio management",
        "investment research",
        "equity research",
        "fixed income",
    ),
    "FP&A": (
        "fp a",
        "financial planning",
        "planning analytique",
        "controle de gestion",
        "business partner",
        "business partnering",
    ),
    # A catch-all the person selects explicitly; it is resolved after the
    # specific domains so a precise match is always reported first.
    "Autres métiers financiers": (),
}

# Source-faithful vocabulary the person can type into a public board search.
# These are search hints, never offers and never deadlines.
_DOMAIN_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "M&A": SEARCH_TERMS["M&A / Investment Banking"],
    "Corporate Finance": SEARCH_TERMS["Corporate Finance"],
    "Private Equity": SEARCH_TERMS["Private Equity"],
    "Transaction Services": (
        "Transaction Services Intern",
        "Deals Advisory Intern",
        "Financial Due Diligence Intern",
        "Stage Transaction Services",
    ),
    "Audit financier": (
        "Audit Intern",
        "Financial Audit Intern",
        "Statutory Audit Intern",
        "Stage Audit Financier",
    ),
    "Asset Management": SEARCH_TERMS["Asset Management"],
    "FP&A": (
        "FP&A Intern",
        "Financial Planning Analyst Intern",
        "Strategic Finance Intern",
        "Stage FP&A",
    ),
    "Autres métiers financiers": SEARCH_TERMS["Sales & Trading"],
}

RANKING_CRITERIA: dict[str, str] = {
    "domaine": "Domaine recherché",
    "metier": "Intitulé du métier",
    "localisation": "Pays ou ville",
    "dates": "Date de début",
    "duree": "Durée du stage",
    "niveau": "Niveau d’études",
    "langues": "Langues",
}
RANKING_MIN_MULTIPLIER = 0.5
RANKING_MAX_MULTIPLIER = 2.0

_LANGUAGE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("français", ("francais", "french")),
    ("anglais", ("anglais", "english")),
    ("italien", ("italien", "italian", "italiano")),
    ("allemand", ("allemand", "german", "deutsch")),
    ("espagnol", ("espagnol", "spanish", "espanol")),
)

# Ordered from the lowest to the highest common student level.  A requirement
# is satisfied when the offer asks for no more than the declared level.
_STUDY_LEVEL_RANKS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (3, ("bac 3", "bac +3", "bac+3", "licence", "l3", "bachelor", "3rd year")),
    (4, ("bac 4", "bac +4", "bac+4", "m1", "master 1", "4th year")),
    (5, ("bac 5", "bac +5", "bac+5", "m2", "master 2", "master s", "5th year", "mastere")),
    (6, ("bac 6", "bac +6", "bac+6", "m3", "master 3", "6th year")),
    (8, ("doctorat", "phd", "doctorate")),
)

# Unambiguous permanent-contract markers only: "temps plein" alone is
# deliberately excluded because a full-time internship is still an internship.
_PERMANENT_CONTRACT_PATTERNS: tuple[str, ...] = ("cdi", "permanent")

MAX_COMPONENTS = 8
CONTRACT_TYPES: dict[str, str] = {"stage": "Stage", "cdd": "CDD", "cdi": "CDI", "vie": "VIE"}
MONTHS: tuple[tuple[int, str], ...] = (
    (1, "janvier"), (2, "février"), (3, "mars"), (4, "avril"), (5, "mai"), (6, "juin"),
    (7, "juillet"), (8, "août"), (9, "septembre"), (10, "octobre"), (11, "novembre"), (12, "décembre"),
)


# ---------------------------------------------------------------------------
# Geographic vocabulary — the country exclusion applied by the connectors
# ---------------------------------------------------------------------------
#
# The exclusion is a *source-side* decision: a connector never returns an
# offer located in an unwanted country, so a rejected posting never reaches
# the database and never consumes source quota.  The rules below only read
# what the source itself states.  They never guess a country from a company
# name, a job title or a salary.

# The person never wants French offers unless they explicitly reopen the list.
DEFAULT_COUNTRIES_EXCLUDE: tuple[str, ...] = ("FR",)

# ISO 3166-1 alpha-2 codes.  A two-letter token is only read as a country
# when the source wrote it in capitals, so "am" in "Frankfurt am Main" stays
# an ordinary word and never becomes Armenia.
_ISO_ALPHA2: frozenset[str] = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL
BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV
CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD
GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM
IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK
LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW
MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR
PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS
ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY
UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())

# A readable selection of ISO 3166-1 alpha-3 codes.
_ISO_ALPHA3: dict[str, str] = {
    "AFG": "AF", "ALB": "AL", "DZA": "DZ", "AGO": "AO", "ARG": "AR", "ARM": "AM", "AUS": "AU",
    "AUT": "AT", "AZE": "AZ", "BHR": "BH", "BGD": "BD", "BEL": "BE", "BOL": "BO", "BIH": "BA",
    "BWA": "BW", "BRA": "BR", "BGR": "BG", "BFA": "BF", "BDI": "BI", "KHM": "KH", "CMR": "CM",
    "CAN": "CA", "CPV": "CV", "CAF": "CF", "TCD": "TD", "CHL": "CL", "CHN": "CN", "COL": "CO",
    "CIV": "CI", "HRV": "HR", "CUB": "CU", "CYP": "CY", "CZE": "CZ", "DNK": "DK", "DJI": "DJ",
    "DOM": "DO", "ECU": "EC", "EGY": "EG", "SLV": "SV", "EST": "EE", "ETH": "ET", "FIN": "FI",
    "FRA": "FR", "GAB": "GA", "GEO": "GE", "DEU": "DE", "GHA": "GH", "GRC": "GR", "GRD": "GD",
    "GTM": "GT", "HND": "HN", "HKG": "HK", "HUN": "HU", "ISL": "IS", "IND": "IN", "IDN": "ID",
    "IRN": "IR", "IRQ": "IQ", "IRL": "IE", "ISR": "IL", "ITA": "IT", "JPN": "JP", "JOR": "JO",
    "KAZ": "KZ", "KEN": "KE", "PRK": "KP", "KOR": "KR", "KWT": "KW", "LVA": "LV", "LBN": "LB",
    "LBY": "LY", "LTU": "LT", "LUX": "LU", "MAC": "MO", "MDG": "MG", "MYS": "MY", "MLT": "MT",
    "MEX": "MX", "MDA": "MD", "MCO": "MC", "MNG": "MN", "MAR": "MA", "MMR": "MM", "NLD": "NL",
    "NZL": "NZ", "NGA": "NG", "NOR": "NO", "OMN": "OM", "PAK": "PK", "PAN": "PA", "PRY": "PY",
    "PER": "PE", "PHL": "PH", "POL": "PL", "PRT": "PT", "QAT": "QA", "ROU": "RO", "RUS": "RU",
    "RWA": "RW", "SAU": "SA", "SEN": "SN", "SRB": "RS", "SGP": "SG", "SVK": "SK", "SVN": "SI",
    "ZAF": "ZA", "ESP": "ES", "LKA": "LK", "SDN": "SD", "SWE": "SE", "CHE": "CH", "SYR": "SY",
    "TWN": "TW", "TZA": "TZ", "THA": "TH", "TUN": "TN", "TUR": "TR", "UGA": "UG", "UKR": "UA",
    "ARE": "AE", "GBR": "GB", "USA": "US", "URY": "UY", "UZB": "UZ", "VEN": "VE", "VNM": "VN",
}

# Country names as a source may write them, in English and in French.
# The key is the accent-free, lowercase phrase; the value is the alpha-2 code.
_COUNTRY_NAMES: dict[str, str] = {
    "france": "FR", "french republic": "FR", "republique francaise": "FR",
    "republique de france": "FR", "fra": "FR",
    "united kingdom": "GB", "great britain": "GB", "britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "northern ireland": "GB", "uk": "GB",
    "royaume uni": "GB", "grande bretagne": "GB", "angleterre": "GB",
    "germany": "DE", "deutschland": "DE", "allemagne": "DE",
    "netherlands": "NL", "the netherlands": "NL", "holland": "NL", "pays bas": "NL",
    "belgium": "BE", "belgique": "BE", "luxembourg": "LU",
    "switzerland": "CH", "suisse": "CH", "schweiz": "CH",
    "ireland": "IE", "irlande": "IE", "austria": "AT", "autriche": "AT",
    "spain": "ES", "espagne": "ES", "italy": "IT", "italie": "IT", "italia": "IT",
    "portugal": "PT", "greece": "GR", "grece": "GR", "sweden": "SE", "suede": "SE",
    "norway": "NO", "norvege": "NO", "denmark": "DK", "danemark": "DK",
    "finland": "FI", "finlande": "FI", "poland": "PL", "pologne": "PL",
    "czech republic": "CZ", "czechia": "CZ", "republique tcheque": "CZ",
    "hungary": "HU", "hongrie": "HU", "romania": "RO", "roumanie": "RO",
    "bulgaria": "BG", "bulgarie": "BG", "croatia": "HR", "croatie": "HR",
    "slovenia": "SI", "slovenie": "SI", "slovakia": "SK", "slovaquie": "SK",
    "estonia": "EE", "estonie": "EE", "latvia": "LV", "lettonie": "LV",
    "lithuania": "LT", "lituanie": "LT", "cyprus": "CY", "chypre": "CY",
    "malta": "MT", "malte": "MT", "iceland": "IS", "islande": "IS",
    "serbia": "RS", "serbie": "RS", "albania": "AL", "albanie": "AL",
    "moldova": "MD", "moldavie": "MD", "montenegro": "ME", "ukraine": "UA",
    "belarus": "BY", "kazakhstan": "KZ", "russia": "RU", "russie": "RU", "turkey": "TR",
    "turquie": "TR", "georgia": "GE", "armenia": "AM", "azerbaijan": "AZ",
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US",
    "etats unis": "US", "etats unis d amerique": "US", "america": "US",
    "canada": "CA", "mexico": "MX", "brazil": "BR", "bresil": "BR", "argentina": "AR",
    "chile": "CL", "colombia": "CO", "peru": "PE", "venezuela": "VE", "uruguay": "UY",
    "paraguay": "PY", "bolivia": "BO", "ecuador": "EC", "costa rica": "CR",
    "el salvador": "SV", "guatemala": "GT", "honduras": "HN", "nicaragua": "NI",
    "panama": "PA", "cuba": "CU", "jamaica": "JM", "trinidad and tobago": "TT",
    "australia": "AU", "australie": "AU", "new zealand": "NZ", "nouvelle zelande": "NZ",
    "singapore": "SG", "singapour": "SG", "hong kong": "HK", "china": "CN", "chine": "CN",
    "japan": "JP", "japon": "JP", "south korea": "KR", "coree du sud": "KR",
    "north korea": "KP", "coree du nord": "KP", "taiwan": "TW",
    "india": "IN", "inde": "IN", "indonesia": "ID", "indonesie": "ID",
    "malaysia": "MY", "malaisie": "MY", "philippines": "PH", "vietnam": "VN",
    "thailand": "TH", "thailande": "TH", "myanmar": "MM", "cambodia": "KH",
    "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK", "nepal": "NP",
    "united arab emirates": "AE", "emirats arabes unis": "AE", "uae": "AE",
    "saudi arabia": "SA", "arabie saoudite": "SA", "qatar": "QA", "kuwait": "KW",
    "bahrain": "BH", "oman": "OM", "jordan": "JO", "israel": "IL", "lebanon": "LB",
    "egypt": "EG", "egypte": "EG", "morocco": "MA", "maroc": "MA", "tunisia": "TN",
    "algeria": "DZ", "algerie": "DZ", "south africa": "ZA", "afrique du sud": "ZA",
    "kenya": "KE", "nigeria": "NG", "ghana": "GH", "senegal": "SN",
}

# Known cities per country.  They are a *fallback* used only when the source
# states no country at all: a posting located in "Paris" and located nowhere
# else is treated as French, while "London, Paris" stays a mixed posting that
# a person can still judge.
_COUNTRY_CITY_HINTS: dict[str, tuple[str, ...]] = {
    "FR": (
        "paris", "lyon", "marseille", "toulouse", "nice", "nantes", "strasbourg",
        "montpellier", "bordeaux", "lille", "rennes", "reims", "le havre",
        "saint etienne", "toulon", "grenoble", "dijon", "angers",
        "villeurbanne", "nanterre", "creteil", "aubervilliers", "asnieres",
        "colombes", "courbevoie", "levallois perret", "neuilly sur seine",
        "ile de france", "provence", "alsace", "aquitaine", "bretagne",
        "normandie", "occitanie", "pays de la loire", "hauts de france",
        "grand est", "nouvelle aquitaine", "auvergne rhone alpes",
        "bourgogne franche comte", "centre val de loire", "corse",
    ),
    "GB": (
        "london", "manchester", "birmingham", "edinburgh", "glasgow", "bristol",
        "leeds", "cambridge", "oxford", "reading", "aberdeen", "cardiff", "belfast",
    ),
    "DE": (
        "frankfurt", "berlin", "munich", "hamburg", "cologne", "dusseldorf",
        "stuttgart", "dresden", "leipzig", "hannover", "duisburg", "nuremberg",
    ),
    "NL": ("amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague", "amersfoort"),
    "BE": ("brussels", "antwerp", "ghent", "bruges", "charleroi", "liege"),
    "LU": ("luxembourg", "esch sur alzette", "differdange"),
    "CH": ("zurich", "geneva", "basel", "bern", "lausanne", "lugano", "zug"),
    "IE": ("dublin", "cork", "galway", "limerick", "waterford"),
}

# Longest phrase first so "northern ireland" is not also read as "ireland".
_MAX_COUNTRY_NAME_WORDS = 5
_COUNTRY_TOKEN_RE = re.compile(r"[A-Za-z]+")


def _strip_accents(text: str) -> str:
    """Remove diacritics while keeping the case of every letter.

    "République française" must read like "Republique francaise", and an
    uppercase ISO code must stay uppercase to be read as a code.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _country_tokens(text: str) -> list[tuple[str, str]]:
    """Split a source value into ``(original, folded)`` letter tokens."""
    return [(token, token.casefold()) for token in _COUNTRY_TOKEN_RE.findall(_strip_accents(text))]


def canonicalize_country(value: Any) -> str:
    """Canonical ISO 3166-1 alpha-2 code for a dedicated country field.

    ``""`` means the source stated no country we can read.  A city name is
    never turned into a country here: "Frankfurt" is not Germany and not
    France, it is simply unknown.
    """
    text = clean_text(value, limit=160)
    if not text:
        return ""
    tokens = _country_tokens(text)
    if not tokens:
        return ""
    if len(tokens) == 1:
        folded = tokens[0][1]
        if len(folded) == 2 and folded.upper() in _ISO_ALPHA2:
            return folded.upper()
        if len(folded) == 3 and folded.upper() in _ISO_ALPHA3:
            return _ISO_ALPHA3[folded.upper()]
    phrase = " ".join(folded for _, folded in tokens)
    code = _COUNTRY_NAMES.get(phrase)
    if code:
        return code
    for size in range(min(len(tokens), _MAX_COUNTRY_NAME_WORDS), 0, -1):
        code = _COUNTRY_NAMES.get(" ".join(folded for _, folded in tokens[-size:]))
        if code:
            return code
    return ""


def resolve_countries(*values: Any) -> tuple[str, ...]:
    """Every country a source explicitly states in the given free-form values.

    Country names are read anywhere in the text ("Paris, France", "France -
    Paris").  ISO codes are read only when the source wrote them in capitals,
    so an ordinary word is never mistaken for a country.
    """
    found: list[str] = []

    def remember(code: str) -> None:
        if code and code not in found:
            found.append(code)

    for value in values:
        text = clean_text(value, limit=300)
        if not text:
            continue
        tokens = _country_tokens(text)
        if not tokens:
            continue
        index = 0
        while index < len(tokens):
            matched = False
            for size in range(min(_MAX_COUNTRY_NAME_WORDS, len(tokens) - index), 0, -1):
                phrase = " ".join(folded for _, folded in tokens[index:index + size])
                code = _COUNTRY_NAMES.get(phrase)
                if code:
                    remember(code)
                    index += size
                    matched = True
                    break
            if not matched:
                index += 1
        for token, folded in tokens:
            if not token.isupper():
                continue
            if len(folded) == 2 and folded.upper() in _ISO_ALPHA2:
                remember(folded.upper())
            elif len(folded) == 3 and folded.upper() in _ISO_ALPHA3:
                remember(_ISO_ALPHA3[folded.upper()])
    return tuple(found)


def city_hint_countries(*values: Any) -> tuple[str, ...]:
    """Countries whose known cities appear in the given text.

    Only used as a fallback when the source states no country at all.
    """
    found: list[str] = []
    for value in values:
        text = normalized_text(value)
        if not text:
            continue
        padded = f" {text} "
        for code, cities in _COUNTRY_CITY_HINTS.items():
            if code in found:
                continue
            if any(f" {city} " in padded for city in cities):
                found.append(code)
    return tuple(found)


def canonical_country_codes(values: Any, label: str = "Les pays exclus") -> list[str]:
    """Canonicalize the person's country choices into sorted unique codes."""
    if values is None:
        return list(DEFAULT_COUNTRIES_EXCLUDE)
    if not isinstance(values, list):
        raise UserFacingError(f"{label} doivent être une liste.")
    if len(values) > 20:
        raise UserFacingError(f"{label} contiennent trop d’éléments (maximum 20).")
    codes: list[str] = []
    for item in values:
        text = clean_text(item, limit=120)
        if not text:
            continue
        code = canonicalize_country(text)
        if not code:
            raise UserFacingError(
                f"Le pays « {text} » n’est pas reconnu. Utilise un code ISO "
                "(FR, GB, DE…) ou le nom du pays en anglais ou en français."
            )
        if code not in codes:
            codes.append(code)
    return sorted(codes)


def default_brief() -> dict[str, Any]:
    """Default search criteria; optional personal preferences remain empty."""
    return {
        "domains": [],
        "other_domains": [],
        "roles": [],
        "countries": [],
        "cities": [],
        "excluded_countries": [],
        "excluded_cities": [],
        "countries_exclude": list(DEFAULT_COUNTRIES_EXCLUDE),
        "require_known_location": False,
        "start_date": "",
        "duration_months": None,
        "contract_types": ["stage", "cdd", "cdi", "vie"],
        "start_months": [1, 2, 3],
        "minimum_stage_duration_months": 6,
        "education_preference": "bachelor_m1_then_m2",
        "study_level": "",
        "languages": [],
        "constraints": "",
        "ranking": {},
    }


def _contains(haystack: str, needle: str) -> bool:
    return f" {needle} " in f" {haystack} "


def _string_list(value: Any, label: str, *, max_items: int, max_length: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise UserFacingError(f"{label} doivent être une liste.")
    if len(value) > max_items:
        raise UserFacingError(f"{label} contiennent trop d’éléments (maximum {max_items}).")
    result: list[str] = []
    for item in value:
        text = clean_text(item, limit=max_length)
        if text and text not in result:
            result.append(text)
    return result


def _ranking_values(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UserFacingError("Les préférences de classement sont invalides.")
    ranking: dict[str, float] = {}
    for key, raw in value.items():
        criterion = clean_text(key, limit=40)
        if criterion not in RANKING_CRITERIA:
            raise UserFacingError(f"La pondération « {criterion or 'vide'} » concerne un critère inconnu.")
        try:
            multiplier = float(raw)
        except (TypeError, ValueError) as error:
            raise UserFacingError("Chaque pondération doit être un nombre entre 0.5 et 2.") from error
        if not RANKING_MIN_MULTIPLIER <= multiplier <= RANKING_MAX_MULTIPLIER:
            raise UserFacingError(
                f"La pondération de « {RANKING_CRITERIA[criterion]} » doit rester entre "
                f"{RANKING_MIN_MULTIPLIER} et {RANKING_MAX_MULTIPLIER}."
            )
        ranking[criterion] = round(multiplier, 2)
    return ranking


def validate_brief(payload: Any) -> dict[str, Any]:
    """Validate and normalize a stage-search brief once, without presumption."""
    if payload is None:
        return default_brief()
    if not isinstance(payload, dict):
        raise UserFacingError("Le stage recherché est invalide.")
    domain_lookup = {normalized_text(label): label for label in STAGE_DOMAINS}
    domains: list[str] = []
    for item in _string_list(payload.get("domains"), "Les domaines", max_items=12, max_length=80):
        canonical = domain_lookup.get(normalized_text(item))
        if not canonical:
            raise UserFacingError(
                f"Le domaine « {item} » n’existe pas. Domaines disponibles : {', '.join(STAGE_DOMAINS)}."
            )
        if canonical not in domains:
            domains.append(canonical)
    start = payload.get("start_date", "")
    start_text = clean_text(start, limit=32)
    if start_text:
        parse_date(start_text, "La date de début recherchée")
    duration_raw = payload.get("duration_months")
    duration: int | None = None
    if clean_text(duration_raw):
        try:
            duration = int(str(duration_raw).strip())
        except ValueError as error:
            raise UserFacingError("La durée recherchée doit être un nombre de mois entier.") from error
        if not 1 <= duration <= 24:
            raise UserFacingError("La durée recherchée doit être comprise entre 1 et 24 mois.")
    contract_types: list[str] = []
    for item in _string_list(payload.get("contract_types", ["stage", "cdd", "cdi", "vie"]),
                             "Les types de contrat", max_items=4, max_length=20):
        canonical = item.strip().casefold()
        if canonical not in CONTRACT_TYPES:
            raise UserFacingError("Type de contrat inconnu. Choisis Stage, CDD, CDI ou VIE.")
        if canonical not in contract_types:
            contract_types.append(canonical)
    if not contract_types:
        raise UserFacingError("Sélectionne au moins un type de contrat.")
    month_values = payload.get("start_months", [1, 2, 3])
    if not isinstance(month_values, list) or len(month_values) > 12:
        raise UserFacingError("Les mois de début doivent être une liste de 1 à 12.")
    start_months: list[int] = []
    for item in month_values:
        if type(item) is not int or not 1 <= item <= 12:
            raise UserFacingError("Chaque mois de début doit être compris entre janvier et décembre.")
        if item not in start_months:
            start_months.append(item)
    start_months.sort()
    if not start_months:
        raise UserFacingError("Sélectionne au moins un mois de début.")
    minimum_stage_duration = payload.get("minimum_stage_duration_months", 6)
    if type(minimum_stage_duration) is not int or not 1 <= minimum_stage_duration <= 24:
        raise UserFacingError("La durée minimale du stage doit être comprise entre 1 et 24 mois.")
    education_preference = payload.get("education_preference", "bachelor_m1_then_m2")
    if education_preference not in {"bachelor_m1_then_m2", "any"}:
        raise UserFacingError("Préférence de niveau d’études inconnue.")
    require_known_location = payload.get("require_known_location", False)
    if type(require_known_location) is not bool:
        raise UserFacingError("Le contrôle de localisation doit être activé ou désactivé explicitement.")
    return {
        "domains": domains,
        "other_domains": _string_list(payload.get("other_domains"), "Les autres métiers", max_items=12, max_length=120),
        "roles": _string_list(payload.get("roles"), "Les métiers", max_items=20, max_length=120),
        "countries": _string_list(payload.get("countries"), "Les pays", max_items=20, max_length=120),
        "cities": _string_list(payload.get("cities"), "Les villes", max_items=20, max_length=120),
        "excluded_countries": _string_list(
            payload.get("excluded_countries", []), "Les pays exclus", max_items=20, max_length=120
        ),
        "excluded_cities": _string_list(
            payload.get("excluded_cities", []), "Les villes exclues", max_items=20, max_length=120
        ),
        # The source-side country exclusion: applied by the connectors, never
        # as a post-filter.  Absent means the default (France is excluded);
        # an explicit empty list reopens every country.
        "countries_exclude": canonical_country_codes(
            payload.get("countries_exclude"), "Les pays exclus à la source"
        ),
        "require_known_location": require_known_location,
        "start_date": start_text,
        "duration_months": duration,
        "contract_types": contract_types,
        "start_months": start_months,
        "minimum_stage_duration_months": minimum_stage_duration,
        "education_preference": education_preference,
        "study_level": clean_text(payload.get("study_level"), limit=120),
        "languages": _string_list(payload.get("languages"), "Les langues", max_items=10, max_length=60),
        "constraints": clean_text(payload.get("constraints"), limit=2_000),
        "ranking": _ranking_values(payload.get("ranking")),
    }


def brief_is_configured(brief: dict[str, Any]) -> bool:
    """Whether the person asked for at least one concrete criterion."""
    return any(
        [
            brief.get("domains"),
            brief.get("other_domains"),
            brief.get("roles"),
            brief.get("countries"),
            brief.get("cities"),
            brief.get("excluded_countries"),
            brief.get("excluded_cities"),
            brief.get("require_known_location") is True,
            clean_text(brief.get("start_date"), limit=32),
            clean_text(brief.get("duration_months")),
            clean_text(brief.get("study_level"), limit=120),
            brief.get("languages"),
            brief.get("contract_types", ["stage", "cdd", "cdi", "vie"]) != ["stage", "cdd", "cdi", "vie"],
            brief.get("start_months", [1, 2, 3]) != [1, 2, 3],
            brief.get("minimum_stage_duration_months", 6) != 6,
        ]
    )


def vocabulary() -> dict[str, Any]:
    """Everything the interface needs to render the brief form."""
    return {
        "domains": list(STAGE_DOMAINS),
        "contract_types": [{"key": key, "label": label} for key, label in CONTRACT_TYPES.items()],
        "months": [{"value": value, "label": label} for value, label in MONTHS],
        "quarter_months": [1, 2, 3],
        "ranking_criteria": [
            {"key": key, "label": label} for key, label in RANKING_CRITERIA.items()
        ],
        "ranking_min": RANKING_MIN_MULTIPLIER,
        "ranking_max": RANKING_MAX_MULTIPLIER,
        # The source-side country exclusion the connectors apply.
        "countries_exclude": {
            "default": list(DEFAULT_COUNTRIES_EXCLUDE),
            "available": sorted({*_ISO_ALPHA2, *_COUNTRY_NAMES.values()}),
        },
    }


def search_terms_for(domains: list[str]) -> list[dict[str, Any]]:
    """Local query vocabulary for the selected domains (no browsing here)."""
    return [
        {"domain": domain, "terms": list(_DOMAIN_SEARCH_TERMS.get(domain, ()))}
        for domain in domains
        if domain in _DOMAIN_SEARCH_TERMS
    ]


def _component(key: str, points: int, maximum: int, *, status: str, reason: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": RANKING_CRITERIA[key],
        "points": int(points),
        "maximum": int(maximum),
        "status": status,
        "reason": clean_text(reason, limit=400),
    }


def _matched_domains(text: str, job_family: str, brief: dict[str, Any]) -> list[tuple[str, str]]:
    matched: list[tuple[str, str]] = []
    for domain in brief.get("domains", []):
        if domain == "Autres métiers financiers":
            continue
        term = next((pattern for pattern in STAGE_DOMAINS.get(domain, ()) if _contains(text, pattern)), "")
        if term:
            matched.append((domain, term))
    if not matched and "Autres métiers financiers" in brief.get("domains", []):
        if job_family in JOB_FAMILIES:
            matched.append(("Autres métiers financiers", job_family))
    for custom in brief.get("other_domains", []):
        pattern = normalized_text(custom)
        if pattern and _contains(text, pattern):
            matched.append((custom, pattern))
    return matched


def _language_names(value: Any) -> set[str]:
    text = normalized_text(value)
    return {
        canonical
        for canonical, patterns in _LANGUAGE_ALIASES
        if any(_contains(text, pattern) for pattern in patterns)
    }


def _study_rank(value: Any) -> int | None:
    text = normalized_text(value)
    rank: int | None = None
    for candidate, patterns in _STUDY_LEVEL_RANKS:
        if any(_contains(text, pattern) for pattern in patterns):
            rank = candidate if rank is None else max(rank, candidate)
    return rank


def score_brief_match(brief: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Compare one stored offer with the search brief; every point is explained.

    Only requested criteria take part in the score.  A criterion whose value
    is unknown on the offer earns no point but stays visible as a review item,
    which keeps an incomplete posting from looking like a confident match.
    """
    components: list[dict[str, Any]] = []
    reasons: list[str] = []
    unknowns: list[str] = []
    warnings: list[str] = []

    text = normalized_text(
        f"{clean_text(job.get('title'), limit=300)} "
        f"{clean_text(job.get('description_original'), limit=30_000)} "
        f"{clean_text(job.get('requirements'), limit=12_000)}"
    )
    job_family = clean_text(job.get("job_family"), limit=160)

    if brief.get("domains") or brief.get("other_domains"):
        matched = _matched_domains(text, job_family, brief)
        if matched:
            detail = ", ".join(f"{domain} (« {term} »)" for domain, term in matched[:4])
            components.append(_component("domaine", 30, 30, status="match", reason=f"Domaines repérés : {detail}."))
            reasons.append(f"Domaines repérés : {detail}.")
        elif text:
            components.append(
                _component(
                    "domaine",
                    0,
                    30,
                    status="no_match",
                    reason="Aucun domaine recherché n’apparaît dans le texte de cette offre.",
                )
            )
        else:
            components.append(
                _component("domaine", 0, 30, status="unknown", reason="Le texte de l’offre est insuffisant pour vérifier le domaine.")
            )
            unknowns.append("Domaine non vérifiable faute de texte source.")

    if brief.get("roles"):
        title = normalized_text(job.get("title"))
        role = next((item for item in brief["roles"] if _contains(title, normalized_text(item))), "")
        if title and role:
            components.append(_component("metier", 15, 15, status="match", reason=f"L’intitulé contient « {role} »."))  # noqa: E501 - short reason
            reasons.append(f"L’intitulé contient « {role} ».")
        elif title:
            components.append(
                _component("metier", 0, 15, status="no_match", reason="L’intitulé ne correspond à aucun métier recherché.")
            )
        else:
            components.append(_component("metier", 0, 15, status="unknown", reason="Intitulé absent."))
            unknowns.append("Métier non vérifiable faute d’intitulé.")

    if brief.get("cities") or brief.get("countries"):
        city = normalized_text(job.get("city"))
        country = normalized_text(job.get("country"))
        wanted_cities = [normalized_text(item) for item in brief.get("cities", [])]
        wanted_countries = [normalized_text(item) for item in brief.get("countries", [])]
        city_match = next(
            (item for item in wanted_cities if item and (item in city or city in item) and city),
            "",
        )
        country_match = next(
            (item for item in wanted_countries if item and (item in country or country in item) and country),
            "",
        )
        if city_match:
            components.append(_component("localisation", 20, 20, status="match", reason=f"Ville correspondante : {job.get('city')}."))
            reasons.append(f"Ville correspondante : {job.get('city')}.")
        elif country_match:
            components.append(
                _component("localisation", 12, 20, status="match", reason=f"Pays correspondant : {job.get('country')}.")
            )
            reasons.append(f"Pays correspondant : {job.get('country')}.")
        elif city or country:
            components.append(
                _component(
                    "localisation",
                    0,
                    20,
                    status="no_match",
                    reason="La localisation de l’offre ne correspond à aucun pays ni ville recherché.",
                )
            )
        else:
            components.append(
                _component("localisation", 0, 20, status="unknown", reason="Localisation absente de l’offre.")
            )
            unknowns.append("Localisation non renseignée par la source.")

    start_text = clean_text(brief.get("start_date"), limit=32)
    if start_text:
        wanted_start = parse_date(start_text, "La date de début recherchée")
        job_start = parse_date(job.get("start_date"), "La date de début de l’offre")
        job_end = parse_date(job.get("end_date"), "La date de fin de l’offre")
        if job_start and wanted_start:
            if job_start >= wanted_start:
                components.append(
                    _component("dates", 15, 15, status="match", reason=f"Début annoncé le {job_start.isoformat()}.")
                )
                reasons.append(f"Début annoncé le {job_start.isoformat()}.")
            elif job_end and job_end >= wanted_start:
                components.append(
                    _component(
                        "dates",
                        8,
                        15,
                        status="review",
                        reason=f"Début annoncé avant ta date ({job_start.isoformat()}) : à vérifier.",
                    )
                )
            else:
                components.append(
                    _component("dates", 0, 15, status="no_match", reason="Le stage se termine avant ta date de début.")
                )
        elif job_end and wanted_start:
            status = "review" if job_end >= wanted_start else "no_match"
            points = 8 if status == "review" else 0
            components.append(
                _component(
                    "dates",
                    points,
                    15,
                    status=status,
                    reason=f"Seule la fin est connue ({job_end.isoformat()}) : début à vérifier.",
                )
            )
            if status != "review":
                unknowns.append("La fin annoncée précède ta date de début.")
        else:
            components.append(
                _component("dates", 0, 15, status="unknown", reason="Les dates du stage ne sont pas renseignées.")
            )
            unknowns.append("Dates non renseignées par la source.")

    wanted_duration = brief.get("duration_months")
    if wanted_duration:
        job_duration = job.get("duration_months")
        try:
            job_duration = int(job_duration) if clean_text(job_duration) else None
        except (TypeError, ValueError):
            job_duration = None
        if job_duration:
            if job_duration >= int(wanted_duration):
                components.append(
                    _component("duree", 10, 10, status="match", reason=f"Durée annoncée : {job_duration} mois.")
                )
                reasons.append(f"Durée annoncée : {job_duration} mois.")
            else:
                components.append(
                    _component(
                        "duree",
                        0,
                        10,
                        status="no_match",
                        reason=f"Durée annoncée ({job_duration} mois) inférieure à {wanted_duration} mois.",
                    )
                )
        else:
            components.append(_component("duree", 0, 10, status="unknown", reason="Durée non renseignée par la source."))
            unknowns.append("Durée non renseignée par la source.")

    study_level = clean_text(brief.get("study_level"), limit=120)
    if study_level:
        wanted_rank = _study_rank(study_level)
        offer_text = normalized_text(
            f"{clean_text(job.get('role_level'), limit=120)} {clean_text(job.get('requirements'), limit=12_000)}"
        )
        offer_rank = _study_rank(offer_text)
        if wanted_rank and offer_rank:
            if offer_rank <= wanted_rank:
                components.append(
                    _component("niveau", 5, 5, status="match", reason="Le niveau demandé est compatible avec ton niveau déclaré.")
                )
                reasons.append("Le niveau demandé est compatible avec ton niveau déclaré.")
            else:
                components.append(
                    _component(
                        "niveau",
                        0,
                        5,
                        status="no_match",
                        reason="Le niveau demandé est supérieur au niveau déclaré dans tes critères.",
                    )
                )
        elif wanted_rank and not offer_text:
            components.append(_component("niveau", 0, 5, status="unknown", reason="Le niveau demandé n’est pas indiqué."))
            unknowns.append("Niveau d’études non renseigné par la source.")
        else:
            components.append(
                _component("niveau", 0, 5, status="unknown", reason="Ton niveau déclaré n’a pu être comparé à aucune exigence explicite.")
            )
            unknowns.append("Comparaison de niveau non déterministe : vérifie la page officielle.")

    if brief.get("languages"):
        wanted_languages = _language_names(" ".join(brief["languages"]))
        required = _language_names(job.get("languages_required"))
        if required:
            if required.issubset(wanted_languages):
                components.append(
                    _component("langues", 5, 5, status="match", reason=f"Langues demandées déclarées : {', '.join(sorted(required))}.")
                )
                reasons.append(f"Langues demandées déclarées : {', '.join(sorted(required))}.")
            else:
                missing = ", ".join(sorted(required - wanted_languages))
                components.append(
                    _component("langues", 0, 5, status="no_match", reason=f"Langues demandées non déclarées : {missing}.")
                )
        else:
            components.append(
                _component("langues", 0, 5, status="unknown", reason="La source ne précise pas les langues requises.")
            )
            unknowns.append("Langues non renseignées par la source.")

    ranking = brief.get("ranking", {})
    weighted_points = 0.0
    weighted_maximum = 0.0
    applied: dict[str, float] = {}
    for component in components[:MAX_COMPONENTS]:
        multiplier = float(ranking.get(component["key"], 1.0))
        applied[component["key"]] = multiplier
        weighted_points += component["points"] * multiplier
        weighted_maximum += component["maximum"] * multiplier

    score = round(100 * weighted_points / weighted_maximum) if weighted_maximum else None
    if score is None:
        label = "Aucun critère renseigné : classement neutre"
    elif score >= 70:
        label = "Correspondance forte"
    elif score >= 45:
        label = "Correspondance à examiner"
    else:
        label = "Correspondance faible ou incomplète"

    source_status = clean_text(job.get("source_status"), limit=40) or "unknown"
    if source_status != "open":
        warnings.append(
            "Le statut de cette annonce n’est pas confirmé ouvert par la source ; elle a peut-être été pourvue."
        )
    deadline_status = clean_text(job.get("deadline_status"), limit=40)
    if deadline_status == "closed":
        warnings.append("La date limite connue est dépassée ou l’annonce est indiquée fermée.")
    # Warn only when a permanent contract falls outside the selected types.
    employment = normalized_text(job.get("employment_type"))
    if ("cdi" not in brief.get("contract_types", ["stage", "cdd", "cdi", "vie"])
            and employment and any(_contains(employment, pattern) for pattern in _PERMANENT_CONTRACT_PATTERNS)):
        warnings.append(
            f"Contrat permanent annoncé (« {clean_text(job.get('employment_type'), limit=120)} ») : "
            "cette offre n’est probablement pas un stage."
        )
    if not clean_text(job.get("official_url"), limit=2_000):
        warnings.append("Aucune URL officielle n’est conservée pour cette offre : vérifie la source avant toute action.")

    return {
        "score": score,
        "education_access": assess_education_access(job, brief.get("education_preference", "bachelor_m1_then_m2")),
        "label": label,
        "components": components[:MAX_COMPONENTS],
        "weights_applied": applied,
        "reasons": reasons[:8],
        "unknowns": unknowns[:8],
        "warnings": warnings[:6],
        "disclaimer": "Comparaison locale déterministe entre tes critères et les faits enregistrés de l’offre ; ce n’est ni une prédiction, ni une vérification du site de l’entreprise.",
    }
