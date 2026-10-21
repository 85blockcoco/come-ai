"""Canonical country vocabulary for source-side geographic filtering.

A public source states its country in many ways: an ISO code (``FR``), a
lower-case code, a three-letter code (``FRA``), a country name in English or
in French, or a location string without any country at all.  Every connector
normalizes its own wording with :func:`canonicalize_country` *before* it
decides to keep or drop an offer, so an excluded country never reaches the
local database and never consumes the person's source quota.

The vocabulary is deliberately explicit.  A country is recognized from an
exact wording, never from a prefix or a substring: ``Frankfurt`` is a city in
Germany, not a ``FR`` posting, and must never be caught by the country code
that happens to spell its first two letters.

A city is never turned into a country either.  A posting published as
``"Paris"`` keeps an unknown country: a missing country is an unknown fact
and never a guessed one, so it is shown to the person as *to verify* instead
of being silently dropped as French.

This module is a pure, local vocabulary: it performs no network request and
invents no fact.  An unknown wording yields an empty result.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .models import clean_text


# The person never wants French postings.  Every connector reads this default
# when no explicit exclusion list is supplied.
DEFAULT_COUNTRIES_EXCLUDE: tuple[str, ...] = ("FR",)

# ISO 3166-1 alpha-2 codes.  A two-letter wording is only a country when it
# belongs to this set, so a stray abbreviation never invents a geography.
_ISO_ALPHA2: frozenset[str] = frozenset({
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT", "AU", "AW", "AX", "AZ",
    "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS",
    "BT", "BV", "BW", "BY", "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
    "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM", "DO", "DZ", "EC", "EE",
    "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK", "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF",
    "GG", "GH", "GI", "GL", "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
    "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR", "IS", "IT", "JE", "JM",
    "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN", "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC",
    "LI", "LK", "LR", "LS", "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
    "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW", "MX", "MY", "MZ", "NA",
    "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP", "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG",
    "PH", "PK", "PL", "PM", "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
    "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM", "SN", "SO", "SR", "SS",
    "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF", "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO",
    "TR", "TT", "TV", "TW", "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
})

# Three-letter codes published by some ATS feeds.
_ALPHA3_TO_ALPHA2: dict[str, str] = {
    "ARG": "AR", "AUS": "AU", "AUT": "AT", "BEL": "BE", "BGD": "BD", "BRA": "BR", "CAN": "CA",
    "CHE": "CH", "CHN": "CN", "CYP": "CY", "CZE": "CZ", "DEU": "DE", "DNK": "DK", "EGY": "EG",
    "ESP": "ES", "EST": "EE", "FIN": "FI", "FRA": "FR", "GBR": "GB", "GRC": "GR", "HKG": "HK",
    "HRV": "HR", "HUN": "HU", "IDN": "ID", "IND": "IN", "IRL": "IE", "ISL": "IS", "ITA": "IT",
    "JPN": "JP", "KOR": "KR", "LUX": "LU", "LVA": "LV", "MEX": "MX", "MLT": "MT", "NLD": "NL",
    "NOR": "NO", "NZL": "NZ", "PHL": "PH", "POL": "PL", "PRT": "PT", "ROU": "RO", "RUS": "RU",
    "SAU": "SA", "SEN": "SN", "SGP": "SG", "SVK": "SK", "SVN": "SI", "SWE": "SE", "THA": "TH",
    "TUR": "TR", "TWN": "TW", "UKR": "UA", "USA": "US", "VNM": "VN", "ZAF": "ZA",
}

# Country names published in English or in French.
_NAMES_TO_ALPHA2: dict[str, str] = {
    "austria": "AT", "autriche": "AT", "oesterreich": "AT",
    "belgium": "BE", "belgique": "BE", "belgien": "BE",
    "brazil": "BR", "bresil": "BR",
    "switzerland": "CH", "suisse": "CH", "schweiz": "CH",
    "czechia": "CZ", "czech republic": "CZ", "republique tcheque": "CZ",
    "germany": "DE", "allemagne": "DE", "deutschland": "DE",
    "denmark": "DK", "danemark": "DK", "danmark": "DK",
    "spain": "ES", "espagne": "ES", "espana": "ES",
    "finland": "FI", "finlande": "FI", "suomi": "FI",
    "france": "FR", "republique francaise": "FR", "republique de france": "FR",
    "french republic": "FR",
    "united kingdom": "GB", "great britain": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "northern ireland": "GB", "royaume uni": "GB", "grande bretagne": "GB",
    "uk": "GB", "great britain and northern ireland": "GB",
    "greece": "GR", "grece": "GR",
    "croatia": "HR", "croatie": "HR",
    "hungary": "HU", "hongrie": "HU",
    "ireland": "IE", "irlande": "IE", "eire": "IE",
    "italy": "IT", "italie": "IT", "italia": "IT",
    "japan": "JP", "japon": "JP",
    "south korea": "KR", "korea": "KR", "coree du sud": "KR",
    "luxembourg": "LU",
    "latvia": "LV", "lettonie": "LV",
    "morocco": "MA", "maroc": "MA",
    "netherlands": "NL", "nederland": "NL", "holland": "NL", "pays bas": "NL",
    "norway": "NO", "norvege": "NO", "norge": "NO",
    "new zealand": "NZ", "nouvelle zelande": "NZ",
    "poland": "PL", "pologne": "PL", "polska": "PL",
    "portugal": "PT",
    "romania": "RO", "roumanie": "RO",
    "sweden": "SE", "suede": "SE", "sverige": "SE",
    "singapore": "SG",
    "slovakia": "SK", "slovaquie": "SK",
    "slovenia": "SI", "slovenie": "SI",
    "turkey": "TR", "turquie": "TR", "turkiye": "TR",
    "ukraine": "UA",
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US",
    "etats unis": "US", "etats unis d amerique": "US",
    "vietnam": "VN", "viet nam": "VN",
    "south africa": "ZA", "afrique du sud": "ZA",
    "canada": "CA",
    "australia": "AU",
    "china": "CN", "chine": "CN",
    "hong kong": "HK", "hong kong sar": "HK",
    "india": "IN", "inde": "IN",
    "israel": "IL",
    "united arab emirates": "AE", "emirats arabes unis": "AE", "uae": "AE", "dubai": "AE",
    "bulgaria": "BG", "bulgarie": "BG",
    "cyprus": "CY", "chypre": "CY",
    "estonia": "EE", "estonie": "EE",
    "lithuania": "LT", "lituanie": "LT",
    "malta": "MT", "malte": "MT",
}


def _fold(value: str) -> str:
    """Lower-case, strip accents and collapse every separator to one space."""
    text = unicodedata.normalize("NFKD", value.lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def canonicalize_country(value: Any) -> str:
    """Return the ISO 3166-1 alpha-2 code of a source country wording.

    ``"FR"``, ``"fr"``, ``"FRA"``, ``"France"`` and ``"République Française"``
    all return ``"FR"``.  A city name such as ``"Frankfurt"`` and any other
    unknown wording return an empty string: an unrecognized wording is never
    turned into a geography.
    """
    text = clean_text(value, limit=120)
    if not text:
        return ""
    folded = _fold(text)
    if not folded:
        return ""
    compact = folded.replace(" ", "")
    if len(compact) == 2 and compact.upper() in _ISO_ALPHA2:
        return compact.upper()
    if len(compact) == 3 and compact.upper() in _ALPHA3_TO_ALPHA2:
        return _ALPHA3_TO_ALPHA2[compact.upper()]
    return _NAMES_TO_ALPHA2.get(folded, "")


def country_from_source(country: Any = None) -> str:
    """Canonical country *stated* by the source.

    The country wording always wins.  A city is never turned into a country:
    a posting published as ``"Paris"`` keeps an unknown country and is shown
    to the person as *to verify*, because a missing country is an unknown
    fact and never a guessed one.  A source that publishes a whole location
    in its country field (``"London, United Kingdom"``) still resolves: the
    explicit country is the last segment of that wording.
    """
    code = canonicalize_country(country)
    if code:
        return code
    text = clean_text(country, limit=160)
    if text:
        for piece in reversed(re.split(r"[,;/|]", text)):
            code = canonicalize_country(piece)
            if code:
                return code
    return ""


def canonical_country_codes(values: Any) -> tuple[str, ...]:
    """Canonical ISO codes of an exclusion list, in order and without repeats.

    A wording that names no known country is dropped: it can never match a
    canonical code, and inventing a geography from it would be a guess.
    """
    if values is None:
        return ()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    codes: list[str] = []
    for value in values:
        code = canonicalize_country(value)
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)
