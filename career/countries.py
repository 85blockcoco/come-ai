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


def resolve_hinted_country(location: Any, geo: GeoFilter,
                           hints: dict[str, str] | None = None) -> str:
    """The country a city wording suggests, when the filter excludes it.

    A hint may only **exclude** an offer: it never proves where an offer is
    located and never turns an unknown country into a known one.  Only a
    location that names a single place is read this way — a posting
    published in several unnamed places is never excluded by a hint.
    """
    codes = hinted_country_codes(location, hints)
    for code in codes:
        if geo.rejects(code):
            return code
    return ""


# --------------------------------------------------------------------------
# City hints
# --------------------------------------------------------------------------
#
# A source that scrapes a result page publishes a free-text location, often
# without any country ("Paris", "Nantes").  The tables below associate a city
# wording with the country it belongs to.  A hint may only **exclude** an
# offer: it never proves where an offer is located, and it never turns an
# unknown country into a known one.  An offer whose location names several
# places is never excluded by a hint — it is not possible to prove that every
# one of them is excluded.
#
# The vocabulary is factual: a city belongs to the country it belongs to.

_CITY_HINTS: dict[str, str] = {
    # France
    "paris": "FR", "lyon": "FR", "marseille": "FR", "toulouse": "FR", "nice": "FR",
    "nantes": "FR", "strasbourg": "FR", "montpellier": "FR", "bordeaux": "FR",
    "lille": "FR", "rennes": "FR", "reims": "FR", "le havre": "FR",
    "saint etienne": "FR", "toulon": "FR", "grenoble": "FR", "dijon": "FR",
    "angers": "FR", "villeurbanne": "FR", "nanterre": "FR", "creteil": "FR",
    "aubervilliers": "FR", "asnieres": "FR", "colombes": "FR", "courbevoie": "FR",
    "levallois perret": "FR", "neuilly sur seine": "FR", "brest": "FR",
    "tours": "FR", "amiens": "FR", "limoges": "FR", "annecy": "FR",
    "perpignan": "FR", "besancon": "FR", "metz": "FR", "orleans": "FR",
    "rouen": "FR", "mulhouse": "FR", "caen": "FR", "nancy": "FR",
    "clichy": "FR", "clichy billancourt": "FR", "boulogne billancourt": "FR",
    "saint denis": "FR", "issy les moulineaux": "FR", "malakoff": "FR",
    "montrouge": "FR", "vanves": "FR", "meudon": "FR", "sevres": "FR",
    "chatillon": "FR", "bagneux": "FR", "arcueil": "FR", "gentilly": "FR",
    "kremlin bicetre": "FR", "ivry sur seine": "FR", "drancy": "FR",
    "pantin": "FR", "saint ouen": "FR", "les lilas": "FR", "romainville": "FR",
    "noisy le grand": "FR", "joinville le pont": "FR", "fontenay sous bois": "FR",
    "saint mande": "FR", "vincennes": "FR", "charenton le pont": "FR",
    "maisons alfort": "FR", "alfortville": "FR", "antony": "FR", "clamart": "FR",
    "l hay les roses": "FR", "fresnes": "FR", "cachan": "FR", "evry": "FR",
    "evry courcouronnes": "FR", "cergy": "FR", "poissy": "FR", "sarcelles": "FR",
    "le mans": "FR", "quimper": "FR", "la rochelle": "FR", "cholet": "FR",
    "valence": "FR", "avignon": "FR", "pau": "FR", "bayonne": "FR",
    "calais": "FR", "dunkerque": "FR", "arles": "FR",
    # United Kingdom
    "london": "GB", "manchester": "GB", "birmingham": "GB", "glasgow": "GB",
    "edinburgh": "GB", "bristol": "GB", "leeds": "GB", "liverpool": "GB",
    "cambridge": "GB", "oxford": "GB", "brighton": "GB", "nottingham": "GB",
    "leicester": "GB", "sheffield": "GB", "york": "GB", "norwich": "GB",
    "exeter": "GB", "plymouth": "GB", "portsmouth": "GB", "cardiff": "GB",
    "belfast": "GB", "newcastle": "GB", "sunderland": "GB", "aberdeen": "GB",
    "dundee": "GB", "swansea": "GB", "bath": "GB",
    # Germany
    "berlin": "DE", "munich": "DE", "hamburg": "DE", "frankfurt": "DE",
    "cologne": "DE", "koln": "DE", "stuttgart": "DE", "dusseldorf": "DE",
    "dortmund": "DE", "essen": "DE", "leipzig": "DE", "bremen": "DE",
    "dresden": "DE", "hannover": "DE", "nuremberg": "DE", "nurnberg": "DE",
    "duisburg": "DE", "bochum": "DE", "wuppertal": "DE", "bielefeld": "DE",
    "bonn": "DE", "munster": "DE", "karlsruhe": "DE", "mannheim": "DE",
    "augsburg": "DE", "wiesbaden": "DE", "monchengladbach": "DE",
    "gelsenkirchen": "DE", "aachen": "DE", "braunschweig": "DE", "chemnitz": "DE",
    "halle": "DE", "magdeburg": "DE", "freiburg": "DE", "kiel": "DE", "mainz": "DE",
    "lubeck": "DE", "erfurt": "DE", "potsdam": "DE", "heidelberg": "DE",
    "regensburg": "DE", "saarbrucken": "DE",
    # Spain
    "madrid": "ES", "barcelona": "ES", "valencia": "ES", "seville": "ES",
    "zaragoza": "ES", "malaga": "ES", "bilbao": "ES", "granada": "ES",
    "alicante": "ES", "cordoba": "ES", "valladolid": "ES", "murcia": "ES",
    "palma": "ES", "palma de mallorca": "ES", "san sebastian": "ES",
    "coruna": "ES", "vigo": "ES", "pontevedra": "ES", "santander": "ES",
    "gijon": "ES", "bilbo": "ES",
    # Italy
    "rome": "IT", "milan": "IT", "naples": "IT", "turin": "IT", "palermo": "IT",
    "genoa": "IT", "bologna": "IT", "florence": "IT", "bari": "IT",
    "catania": "IT", "venice": "IT", "verona": "IT", "messina": "IT",
    "padua": "IT", "trieste": "IT", "brescia": "IT", "parma": "IT",
    "modena": "IT", "perugia": "IT", "ravenna": "IT", "livorno": "IT",
    "cagliari": "IT", "salerno": "IT", "ferrara": "IT", "bergamo": "IT",
    "trento": "IT", "bolzano": "IT", "novara": "IT", "como": "IT", "pisa": "IT",
    # Netherlands, Belgium, Luxembourg
    "amsterdam": "NL", "rotterdam": "NL", "the hague": "NL", "utrecht": "NL",
    "eindhoven": "NL", "groningen": "NL", "tilburg": "NL", "alkmaar": "NL",
    "nijmegen": "NL", "breda": "NL", "maastricht": "NL", "zwolle": "NL",
    "leiden": "NL", "delft": "NL", "haarlem": "NL", "amersfoort": "NL",
    "apeldoorn": "NL", "den haag": "NL",
    "brussels": "BE", "antwerp": "BE", "ghent": "BE", "charloi": "BE",
    "liege": "BE", "bruges": "BE", "namur": "BE", "leuven": "BE", "hasselt": "BE",
    "genk": "BE", "mons": "BE", "kortrijk": "BE", "mechelen": "BE",
    "tournai": "BE", "aalst": "BE", "sint niklaas": "BE", "ostend": "BE",
    "roeselare": "BE", "gand": "BE", "anvers": "BE",
    "luxembourg": "LU", "esch sur alzette": "LU", "dudelange": "LU",
    "differdange": "LU", "ettelbruck": "LU",
    # Switzerland
    "zurich": "CH", "geneva": "CH", "geneve": "CH", "basel": "CH",
    "bern": "CH", "lausanne": "CH", "winterthur": "CH", "lucerne": "CH",
    "lugano": "CH", "biel": "CH", "thun": "CH", "koenzliken": "CH",
    "fribourg": "CH", "schaffhausen": "CH", "zug": "CH", "sion": "CH",
    "aarau": "CH", "chur": "CH", "davos": "CH", "verbier": "CH",
    # Austria, Ireland, Portugal
    "vienna": "AT", "wien": "AT", "graz": "AT", "linz": "AT", "salzburg": "AT",
    "innsbruck": "AT", "klagenfurt": "AT", "villach": "AT", "wels": "AT",
    "sankt polten": "AT", "st pölten": "AT", "dornbirn": "AT",
    "dublin": "IE", "cork": "IE", "galway": "IE", "limerick": "IE",
    "waterford": "IE", "killarney": "IE", "wexford": "IE", "drogheda": "IE",
    "dundalk": "IE", "tralee": "IE", "carlow": "IE", "kilkenny": "IE",
    "sligo": "IE", "tipperary": "IE", "donegal": "IE", "mayo": "IE",
    "lisbon": "PT", "lisboa": "PT", "porto": "PT", "braga": "PT",
    "coimbra": "PT", "aveiro": "PT", "faro": "PT", "setubal": "PT",
    "guimaraes": "PT", "leiria": "PT", "viseu": "PT", "evora": "PT",
    "funchal": "PT", "sintra": "PT", "cascais": "PT", "madeira": "PT",
    "azores": "PT",
    # Nordics
    "stockholm": "SE", "gothenburg": "SE", "malmo": "SE", "uppsala": "SE",
    "vasteras": "SE", "orebro": "SE", "linkoping": "SE", "helsingborg": "SE",
    "jonkoping": "SE", "norrkoping": "SE", "lulea": "SE", "umea": "SE",
    "oslo": "NO", "bergen": "NO", "trondheim": "NO", "stavanger": "NO",
    "drammen": "NO", "kristiansand": "NO", "sandnes": "NO", "tromso": "NO",
    "bodo": "NO", "harstad": "NO", "narvik": "NO", "fredrikstad": "NO",
    "copenhagen": "DK", "kobenhavn": "DK", "aarhus": "DK", "odense": "DK",
    "aalborg": "DK", "esbjerg": "DK", "randers": "DK", "kolding": "DK",
    "horsens": "DK", "vejle": "DK", "roskilde": "DK", "silkeborg": "DK",
    "helsinki": "FI", "espoo": "FI", "tampere": "FI", "vantaa": "FI",
    "oulu": "FI", "turku": "FI", "jyvaskyla": "FI", "kuopio": "FI",
    "lahti": "FI", "pori": "FI", "kouvola": "FI", "joensuu": "FI",
    "lappeenranta": "FI", "hameenlinna": "FI", "vaasa": "FI", "rovaniemi": "FI",
    "reykjavik": "IS", "akureyri": "IS",
    # Central and Eastern Europe
    "warsaw": "PL", "warszawa": "PL", "krakow": "PL",
    "wroclaw": "PL", "poznan": "PL", "lodz": "PL", "katowice": "PL",
    "gdansk": "PL", "szczecin": "PL", "bydgoszcz": "PL", "lublin": "PL",
    "bialystok": "PL", "torun": "PL", "kielce": "PL", "gliwice": "PL",
    "zabrze": "PL", "olsztyn": "PL", "rzeszow": "PL", "gdynia": "PL",
    "prague": "CZ", "praha": "CZ", "brno": "CZ", "ostrava": "CZ",
    "plzen": "CZ", "olomouc": "CZ", "liberec": "CZ", "ceske budejovice": "CZ",
    "hradec kralove": "CZ", "zlin": "CZ", "pardubice": "CZ",
    "budapest": "HU", "debrecen": "HU", "szeged": "HU", "miskolc": "HU",
    "pecs": "HU", "gyor": "HU", "nyiregyhaza": "HU", "kecskemet": "HU",
    "szekesfehervar": "HU", "szombathely": "HU", "szolnok": "HU",
    "tatabanya": "HU", "kaposvar": "HU",
    "bucharest": "RO", "cluj napoca": "RO", "timisoara": "RO", "iasi": "RO",
    "constanta": "RO", "craiova": "RO", "brasov": "RO", "galati": "RO",
    "ploiesti": "RO", "oradea": "RO", "brad": "RO", "arad": "RO", "sibiu": "RO",
    "baia mare": "RO", "buziau": "RO", "resita": "RO", "slatina": "RO",
    "pitesti": "RO", "athens": "GR", "thessaloniki": "GR", "patras": "GR",
    "heraklion": "GR", "larissa": "GR", "volos": "GR", "ioannina": "GR",
    "chania": "GR", "kavala": "GR", "rhodes": "GR", "corfu": "GR",
    "xanthi": "GR", "komotini": "GR", "agrinio": "GR", "katerini": "GR",
    "tallinn": "EE", "tartu": "EE", "narva": "EE", "viljandi": "EE",
    "rakvere": "EE", "kohtla jarve": "EE",
    "riga": "LV", "daugavpils": "LV", "liepaja": "LV", "jelgava": "LV",
    "jurmala": "LV", "rezekne": "LV", "valmiera": "LV", "ventspils": "LV",
    "salacgriva": "LV", "kraslava": "LV",
    "vilnius": "LT", "kaunas": "LT", "klaipeda": "LT", "siauliai": "LT",
    "panevezys": "LT", "alytus": "LT", "marijampole": "LT", "mazeikiai": "LT",
    "jonava": "LT", "ukmerge": "LT",
    "bratislava": "SK", "kosice": "SK", "presov": "SK", "zilina": "SK",
    "nitra": "SK", "banska bystrica": "SK", "trnava": "SK", "martin": "SK",
    "poprad": "SK", "zvolen": "SK", "povazska bystrica": "SK",
    "nove zamky": "SK", "michalovce": "SK", "spisska nova ves": "SK",
    "komarno": "SK", "levice": "SK", "dubnica": "SK",
    "ljubljana": "SI", "maribor": "SI", "celje": "SI", "kranj": "SI",
    "velika gorica": "SI", "novo mesto": "SI", "ptuj": "SI", "trbovlje": "SI",
    "kamnik": "SI", "jesenice": "SI",
    "zagreb": "HR", "rijeka": "HR", "osijek": "HR", "zadar": "HR",
    "pula": "HR", "varazdin": "HR", "sibenik": "HR", "dubrovnik": "HR",
    # North America, Asia, Oceania, rest of the world
    "toronto": "CA", "montreal": "CA", "vancouver": "CA", "calgary": "CA",
    "ottawa": "CA", "edmonton": "CA", "winnipeg": "CA", "quebec city": "CA",
    "hamilton": "CA", "halifax": "CA", "victoria": "CA", "saskatoon": "CA",
    "regina": "CA", "kelowna": "CA", "laval": "CA", "guelph": "CA",
    "new york": "US", "nyc": "US", "san francisco": "US", "los angeles": "US",
    "chicago": "US", "boston": "US", "seattle": "US", "austin": "US",
    "denver": "US", "washington": "US", "miami": "US", "atlanta": "US",
    "san diego": "US", "portland": "US", "dallas": "US", "houston": "US",
    "philadelphia": "US", "phoenix": "US", "san jose": "US", "pittsburgh": "US",
    "minneapolis": "US", "detroit": "US", "nashville": "US", "raleigh": "US",
    "charlotte": "US", "cleveland": "US", "columbus": "US", "indianapolis": "US",
    "hong kong": "HK", "kowloon": "HK",
    "singapore": "SG", "tokyo": "JP", "osaka": "JP", "kyoto": "JP",
    "yokohama": "JP", "nagoya": "JP", "sapporo": "JP", "fukuoka": "JP",
    "kobe": "JP", "hiroshima": "JP", "sendai": "JP",
    "shanghai": "CN", "beijing": "CN", "shenzhen": "CN", "guangzhou": "CN",
    "hangzhou": "CN", "chengdu": "CN", "nanjing": "CN", "wuhan": "CN",
    "xian": "CN", "suzhou": "CN", "seoul": "KR", "busan": "KR", "incheon": "KR",
    "daegu": "KR", "daejeon": "KR", "gwangju": "KR", "suwon": "KR",
    "mumbai": "IN", "delhi": "IN", "bangalore": "IN", "hyderabad": "IN",
    "chennai": "IN", "pune": "IN", "kolkata": "IN", "ahmedabad": "IN",
    "jaipur": "IN", "gurgaon": "IN", "noida": "IN",
    "sydney": "AU", "melbourne": "AU", "brisbane": "AU", "perth": "AU",
    "adelaide": "AU", "canberra": "AU", "gold coast": "AU", "hobart": "AU",
    "darwin": "AU", "auckland": "NZ", "wellington": "NZ", "christchurch": "NZ",
    "sao paulo": "BR", "rio de janeiro": "BR", "brasilia": "BR",
    "salvador": "BR", "fortaleza": "BR", "belo horizonte": "BR", "curitiba": "BR",
    "recife": "BR", "porto alegre": "BR", "manaus": "BR", "campinas": "BR",
    "mexico city": "MX", "guadalajara": "MX", "monterrey": "MX", "puebla": "MX",
    "queretaro": "MX", "tijuana": "MX", "cancun": "MX",
    "johannesburg": "ZA", "cape town": "ZA", "pretoria": "ZA", "durban": "ZA",
    "port elizabeth": "ZA", "bloemfontein": "ZA",
    "tel aviv": "IL", "jerusalem": "IL", "haifa": "IL", "netanya": "IL",
    "dubai": "AE", "abu dhabi": "AE", "sharjah": "AE", "al ain": "AE",
    "istanbul": "TR", "ankara": "TR", "izmir": "TR", "antalya": "TR",
    "bursa": "TR", "adana": "TR", "konya": "TR", "gaziantep": "TR",
    "moscow": "RU", "saint petersburg": "RU", "novosibirsk": "RU",
    "yekaterinburg": "RU", "kazan": "RU", "kyiv": "UA", "kiev": "UA",
    "kharkiv": "UA", "odessa": "UA", "lviv": "UA",
    "riyadh": "SA", "jeddah": "SA", "dammam": "SA", "doha": "QA", "cairo": "EG",
    "alexandria": "EG", "giza": "EG", "casablanca": "MA", "rabat": "MA",
    "marrakech": "MA", "tangier": "MA", "agadir": "MA",
}

# French regions APEC publishes on its own postings.
_FRANCE_REGION_HINTS: dict[str, str] = {
    "ile de france": "FR", "provence": "FR", "alsace": "FR", "aquitaine": "FR",
    "bretagne": "FR", "normandie": "FR", "occitanie": "FR",
    "pays de la loire": "FR", "hauts de france": "FR", "grand est": "FR",
    "nouvelle aquitaine": "FR", "auvergne rhone alpes": "FR",
    "bourgogne franche comte": "FR", "centre val de loire": "FR", "corse": "FR",
}


def _build_hint_index(hints: dict[str, str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for name, code in hints.items():
        key = _fold(name)
        if key:
            index.setdefault(key, code)
    return index


CITY_HINT_INDEX: dict[str, str] = _build_hint_index(_CITY_HINTS)
FRANCE_REGION_HINT_INDEX: dict[str, str] = _build_hint_index(_FRANCE_REGION_HINTS)
APEC_HINT_INDEX: dict[str, str] = {**CITY_HINT_INDEX, **FRANCE_REGION_HINT_INDEX}


def hinted_country_codes(location: Any, hints: dict[str, str] | None = None) -> tuple[str, ...]:
    """The countries a city wording suggests.

    The hint is read on the whole location when it names one place, and on
    its words otherwise.  An empty result means the wording suggests no
    country: the offer then stays visible.
    """
    text = clean_text(location, limit=300)
    vocabulary = CITY_HINT_INDEX if hints is None else hints
    if not text or not vocabulary:
        return ()
    parts = [part.strip() for part in re.split(_LOCATION_SEPARATORS, text) if part.strip()]
    parts = [part for part in parts if not canonicalize_country(part)]
    if not parts:
        return ()
    if len(parts) > 1:
        # Several unnamed places: nothing is proven, nothing is excluded.
        return ()
    codes: list[str] = []
    for token in _fold(parts[0]).split():
        code = vocabulary.get(token)
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


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
