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
from dataclasses import dataclass
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


# Separators a source uses between a city and its country: a comma, a
# parenthesis, a slash, a pipe, or a dash written with spaces around it.
# A dash without spaces belongs to the word itself ("Le-Mans") and is never
# a separator.
_LOCATION_SEPARATORS = r"[,;(/|]|\s+[-\u2013\u2014]\s+"


def split_location(value: Any) -> list[str]:
    """Split a published location into its parts.

    A source writes a city and its country with a comma, a parenthesis, a
    slash, a pipe or a spaced dash.  Each part is read on its own, so the
    country is found wherever the source puts it.
    """
    text = clean_text(value, limit=300)
    if not text:
        return []
    return [part.strip() for part in re.split(_LOCATION_SEPARATORS, text) if part.strip()]


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

    A location written with a spaced dash (``"Paris - France"``) is read the
    same way: the dash separates the city from the country, exactly like a
    comma does.
    """
    code = canonicalize_country(country)
    if code:
        return code
    text = clean_text(country, limit=160)
    if text:
        for piece in reversed(re.split(_LOCATION_SEPARATORS, text)):
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


# Wordings that are a city, not a country name.  A source that publishes
# "Dubai" publishes a city: the country stays unknown unless the source
# publishes it too.
_CITY_NAMES = frozenset({"dubai"})

# US state postal abbreviations that are also ISO 3166-1 alpha-2 codes.  In a
# prose location they publish a state, not a country: "Chicago, IL" is
# Illinois, not Israel.  They are only read when the source publishes them in
# a structural country field, where the code is a published fact.
_STATE_CODES = frozenset({
    "AL", "AR", "CA", "CO", "DE", "GA", "ID", "IL", "IN", "LA", "MA", "MD",
    "ME", "MN", "MO", "MS", "MT", "NE", "SC", "SD",
})


def _country_slot_code(location: Any) -> str:
    """The country the last part of a location publishes, when it publishes one.

    A source writes the country last (``"Paris, FR"``).  A code that is
    also a US state abbreviation is never read here: it publishes a state.
    """
    text = clean_text(location, limit=300)
    if not text:
        return ""
    parts = [part.strip() for part in re.split(_LOCATION_SEPARATORS, text) if part.strip()]
    if len(parts) < 2:
        return ""
    code = canonicalize_country(parts[-1])
    if code in _STATE_CODES:
        return ""
    return code


def _country_name_code(piece: Any) -> str:
    """The country a single location part names, on country names only."""
    text = clean_text(piece, limit=120)
    if not text:
        return ""
    folded = _fold(text)
    if not folded or folded in _CITY_NAMES:
        return ""
    return _NAMES_TO_ALPHA2.get(folded, "")


def countries_named_in_location(value: Any) -> tuple[str, ...]:
    """Every country a published location names, in the order it writes them.

    A location is read on country **names** only.  A two-letter wording is
    ambiguous in a prose location — ``"Chicago, IL"`` publishes an American
    state, not Israel — so it is never turned into a geography here.  The
    structural country fields of the sources (Greenhouse
    ``office.country_code``, Ashby ``addressCountry``) are read elsewhere,
    where the code is a published fact.

    ``"London, Greater London, England, United Kingdom, Paris, France"``
    names two countries; ``"Paris"`` names none at all.
    """
    text = clean_text(value, limit=300)
    if not text:
        return ()
    codes: list[str] = []
    for piece in re.split(_LOCATION_SEPARATORS, text):
        code = _country_name_code(piece)
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


def country_from_location(value: Any) -> str:
    """The first country a published location names, when it names one.

    A location is read on country **names** only.  A two-letter wording is
    ambiguous in a prose location — ``"Chicago, IL"`` publishes an American
    state, not Israel — so it is never turned into a geography here.  The
    structural country fields of the sources (Greenhouse ``office.country_code``,
    Ashby ``addressCountry``) are read elsewhere, where the code is a fact.

    The first country wins: a source writes its main location first, and
    ``"Paris"`` names no country at all.
    """
    codes = countries_named_in_location(value)
    return codes[0] if codes else ""


def resolve_published_country(explicit: Any, location: Any, geo: GeoFilter) -> tuple[str, str]:
    """Resolve the country of one published posting.

    The structural country of the source wins when it publishes one: it is a
    published fact, not a reading of a prose.  Otherwise the location is
    read:

    * the countries it **names** (``"Paris, France"``, ``"France"``) are read
      first, because a name is never ambiguous;
    * a posting that names several countries is kept as soon as one of them
      is allowed — a London role published next to Paris is still a London
      role — and it is dropped only when every country it names is excluded;
    * a location that publishes a bare code in its country slot
      (``"Paris, FR"``) is read on that code, unless the code is also a US
      state abbreviation: ``"Chicago, IL"`` publishes Illinois, not Israel.

    The answer is the pair ``(canonical code, excluded code)``:

    * the canonical code is the first country the posting publishes that the
      filter keeps, and is empty when the posting publishes none;
    * the excluded code is the country that caused the drop, and is empty
      when the posting is kept.
    """
    code = canonicalize_country(explicit)
    if code:
        return ("", code) if geo.rejects(code) else (code, "")
    named = countries_named_in_location(location)
    if len(named) > 1:
        allowed = [item for item in named if not geo.rejects(item)]
        if allowed:
            return allowed[0], ""
        return named[0], named[0]
    if named:
        code = named[0]
        return ("", code) if geo.rejects(code) else (code, "")
    slot = _country_slot_code(location)
    if slot:
        return ("", slot) if geo.rejects(slot) else (slot, "")
    return "", ""


@dataclass(frozen=True)
class GeoFilter:
    """The geographic filter a connector applies on its own side.

    Two lists are read:

    * ``exclude`` — the countries the person never wants.  France is the
      default and is always excluded unless the person explicitly empties
      the list.
    * ``include`` — the countries a source is allowed to publish.  It is
      empty by default (every country is allowed) and is meant for the
      sources that only publish a targeted geography.

    An offer whose country is unknown is never dropped: a missing country
    is an unknown fact, and the product shows it to the person as *to
    verify* instead of guessing a geography for it.
    """

    exclude: frozenset[str] = frozenset()
    include: frozenset[str] = frozenset()

    def rejects(self, code: str) -> bool:
        """True when an offer published in ``code`` must be dropped."""
        if not code:
            return False
        if code in self.exclude:
            return True
        if self.include and code not in self.include:
            return True
        return False

    def rejects_wording(self, country: Any) -> str:
        """Canonical country of a wording when it is rejected, else ``""``."""
        code = country_from_source(country)
        return code if self.rejects(code) else ""


def geo_filter(
    countries_exclude: Any = None,
    countries_include: Any = None,
    brief: dict[str, Any] | None = None,
) -> GeoFilter:
    """Build the filter a connector must apply.

    The explicit parameters win; the brief is the fallback.  An explicit
    empty list is a real choice and disables that side of the filter: it is
    the only way a French posting reaches the person again.
    """
    payload = brief or {}
    exclude = countries_exclude if countries_exclude is not None else payload.get("countries_exclude")
    include = countries_include if countries_include is not None else payload.get("countries_include")
    return GeoFilter(
        exclude=frozenset(canonical_country_codes(exclude)),
        include=frozenset(canonical_country_codes(include)),
    )
