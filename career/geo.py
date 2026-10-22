"""Canonical country reading and connector-level country filtering.

The country filter belongs to the connector boundary: an offer published in
an excluded country must not cost a match, a qualification or a request.
This module therefore owns three things and nothing else:

* :func:`canonical_country_code` reads the ISO-3166-1 alpha-2 code of wording
  a source actually published.  Unreadable wording returns an empty string: a
  missing country is unknown, never France.
* :func:`geo_filter_decision` decides whether one offer is kept, using only
  published evidence.
* the location hint tables, which let a city or region wording *suggest* a
  country.  A hint may only exclude an offer; it never proves that an offer
  is located in a country.

Two rules are never broken:

* An offer published in several places is excluded only when every country
  it mentions is excluded.
* A country that could not be read is never excluded.  An unknown country
  stays visible and the person decides.

The module is pure: no network, no clock, no filesystem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .models import clean_text, normalized_text


# --------------------------------------------------------------------------
# Countries
# --------------------------------------------------------------------------

# ISO-3166-1 alpha-2 code and the English wording a public job board uses.
_COUNTRY_NAMES: dict[str, tuple[str, ...]] = {
    "AD": ("andorra",),
    "AE": ("united arab emirates",),
    "AF": ("afghanistan",),
    "AG": ("antigua and barbuda",),
    "AI": ("anguilla",),
    "AL": ("albania",),
    "AM": ("armenia",),
    "AO": ("angola",),
    "AR": ("argentina",),
    "AT": ("austria",),
    "AU": ("australia",),
    "AW": ("aruba",),
    "AX": ("aland islands",),
    "AZ": ("azerbaijan",),
    "BA": ("bosnia and herzegovina",),
    "BB": ("barbados",),
    "BD": ("bangladesh",),
    "BE": ("belgium",),
    "BF": ("burkina faso",),
    "BG": ("bulgaria",),
    "BH": ("bahrain",),
    "BI": ("burundi",),
    "BJ": ("benin",),
    "BL": ("saint barthelemy",),
    "BM": ("bermuda",),
    "BN": ("brunei",),
    "BO": ("bolivia",),
    "BR": ("brazil",),
    "BS": ("bahamas",),
    "BT": ("bhutan",),
    "BW": ("botswana",),
    "BY": ("belarus",),
    "BZ": ("belize",),
    "CA": ("canada",),
    "CD": ("democratic republic of the congo",),
    "CF": ("central african republic",),
    "CG": ("republic of the congo",),
    "CH": ("switzerland",),
    "CI": ("ivory coast",),
    "CL": ("chile",),
    "CM": ("cameroon",),
    "CN": ("china",),
    "CO": ("colombia",),
    "CR": ("costa rica",),
    "CU": ("cuba",),
    "CV": ("cape verde",),
    "CY": ("cyprus",),
    "CZ": ("czechia",),
    "DE": ("germany",),
    "DK": ("denmark",),
    "DO": ("dominican republic",),
    "DZ": ("algeria",),
    "EC": ("ecuador",),
    "EE": ("estonia",),
    "EG": ("egypt",),
    "ES": ("spain",),
    "ET": ("ethiopia",),
    "FI": ("finland",),
    "FJ": ("fiji",),
    "FM": ("micronesia",),
    "FR": ("france",),
    "GA": ("gabon",),
    "GB": ("united kingdom",),
    "GD": ("grenada",),
    "GE": ("georgia",),
    "GH": ("ghana",),
    "GR": ("greece",),
    "GT": ("guatemala",),
    "HR": ("croatia",),
    "HT": ("haiti",),
    "HU": ("hungary",),
    "ID": ("indonesia",),
    "IE": ("ireland",),
    "IL": ("israel",),
    "IN": ("india",),
    "IQ": ("iraq",),
    "IR": ("iran",),
    "IS": ("iceland",),
    "IT": ("italy",),
    "JM": ("jamaica",),
    "JO": ("jordan",),
    "JP": ("japan",),
    "KE": ("kenya",),
    "KG": ("kyrgyzstan",),
    "KH": ("cambodia",),
    "KR": ("south korea",),
    "KW": ("kuwait",),
    "KZ": ("kazakhstan",),
    "LB": ("lebanon",),
    "LC": ("saint lucia",),
    "LI": ("liechtenstein",),
    "LK": ("sri lanka",),
    "LR": ("liberia",),
    "LT": ("lithuania",),
    "LU": ("luxembourg",),
    "LV": ("latvia",),
    "LY": ("libya",),
    "MA": ("morocco",),
    "MC": ("monaco",),
    "MD": ("moldova",),
    "ME": ("montenegro",),
    "MG": ("madagascar",),
    "MK": ("north macedonia",),
    "ML": ("mali",),
    "MM": ("myanmar",),
    "MN": ("mongolia",),
    "MT": ("malta",),
    "MU": ("mauritius",),
    "MV": ("maldives",),
    "MX": ("mexico",),
    "MY": ("malaysia",),
    "MZ": ("mozambique",),
    "NA": ("namibia",),
    "NE": ("niger",),
    "NG": ("nigeria",),
    "NL": ("netherlands",),
    "NO": ("norway",),
    "NP": ("nepal",),
    "NZ": ("new zealand",),
    "OM": ("oman",),
    "PE": ("peru",),
    "PH": ("philippines",),
    "PK": ("pakistan",),
    "PL": ("poland",),
    "PR": ("puerto rico",),
    "PT": ("portugal",),
    "QA": ("qatar",),
    "RO": ("romania",),
    "RS": ("serbia",),
    "RU": ("russia",),
    "RW": ("rwanda",),
    "SA": ("saudi arabia",),
    "SE": ("sweden",),
    "SG": ("singapore",),
    "SI": ("slovenia",),
    "SK": ("slovakia",),
    "SN": ("senegal",),
    "TR": ("turkey",),
    "TW": ("taiwan",),
    "TZ": ("tanzania",),
    "UA": ("ukraine",),
    "US": ("united states",),
    "UY": ("uruguay",),
    "UZ": ("uzbekistan",),
    "VE": ("venezuela",),
    "VN": ("vietnam",),
    "ZA": ("south africa",),
    "ZM": ("zambia",),
    "ZW": ("zimbabwe",),
}

# Wordings that are not the official English name but are published anyway.
_COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "AE": ("uae", "emirates"),
    "BA": ("bosnia",),
    "BR": ("brasil",),
    "BY": ("belarus",),
    "CD": ("drc", "democratic republic of congo", "congo kinshasa"),
    "CG": ("congo", "congo brazzaville"),
    "CH": ("suisse", "swiss confederation", "confederation suisse"),
    "CI": ("cote d ivoire", "republique de cote d ivoire"),
    "CN": ("peoples republic of china", "mainland china"),
    "CZ": ("czech republic", "tchequie"),
    "DE": ("allemagne", "deutschland", "federal republic of germany"),
    "DK": ("danemark"),
    "EE": ("estonia",),
    "ES": ("espagne", "spanish kingdom"),
    "FI": ("finlande"),
    "FR": ("french republic", "republique francaise", "republique de france"),
    "GB": ("uk", "u k", "great britain", "britain", "england", "scotland", "wales",
           "northern ireland", "united kingdom of great britain and northern ireland"),
    "GR": ("grece", "hellenic republic"),
    "HR": ("croatia",),
    "HU": ("hongrie"),
    "IE": ("irlande", "republic of ireland", "eire"),
    "IN": ("inde", "republic of india"),
    "IR": ("iran", "islamic republic of iran"),
    "IT": ("italie", "italia", "italian republic"),
    "JP": ("japon"),
    "KR": ("korea", "republic of korea", "south korea"),
    "LT": ("lithuania",),
    "LU": ("luxembourg", "grand duchy of luxembourg"),
    "LV": ("latvia",),
    "MA": ("maroc"),
    "MX": ("mexique"),
    "NL": ("netherlands", "the netherlands", "nederland", "holland", "pays bas"),
    "NO": ("norvege", "kingdom of norway"),
    "NZ": ("nouvelle zelande"),
    "PL": ("pologne"),
    "PT": ("portugal", "portuguese republic"),
    "RO": ("roumanie"),
    "RU": ("russia", "russian federation"),
    "SE": ("suede", "kingdom of sweden"),
    "SG": ("singapour"),
    "SK": ("slovakia", "slovak republic"),
    "TR": ("turkey", "turkiye", "turquie"),
    "TW": ("taiwan", "chinese taipei"),
    "UA": ("ukraine",),
    "US": ("usa", "u s a", "u s", "united states of america", "america"),
    "ZA": ("afrique du sud", "union of south africa"),
}

# ISO-3166-1 alpha-3 codes published by some applicant tracking systems.
_COUNTRY_ALPHA3: dict[str, str] = {
    "AUT": "AT", "BEL": "BE", "BGR": "BG", "BRA": "BR", "CHE": "CH", "CYP": "CY",
    "CZE": "CZ", "DEU": "DE", "DNK": "DK", "ESP": "ES", "EST": "EE", "FIN": "FI",
    "FRA": "FR", "GBR": "GB", "GRC": "GR", "HRV": "HR", "HUN": "HU", "IRL": "IE",
    "ISL": "IS", "ITA": "IT", "JPN": "JP", "KOR": "KR", "LTU": "LT", "LUX": "LU",
    "LVA": "LV", "MAR": "MA", "MEX": "MX", "NLD": "NL", "NOR": "NO", "NZL": "NZ",
    "POL": "PL", "PRT": "PT", "ROU": "RO", "RUS": "RU", "SVK": "SK", "SVN": "SI",
    "SWE": "SE", "TUR": "TR", "UKR": "UA", "USA": "US", "ZAF": "ZA",
}


def _build_country_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for code, names in _COUNTRY_NAMES.items():
        index.setdefault(code.lower(), code)
        for name in names:
            key = normalized_text(name)
            if key:
                index.setdefault(key, code)
    for code, names in _COUNTRY_ALIASES.items():
        for name in names:
            key = normalized_text(name)
            if key:
                index[key] = code
    for alpha3, code in _COUNTRY_ALPHA3.items():
        index.setdefault(normalized_text(alpha3), code)
    return index


_COUNTRY_INDEX: dict[str, str] = _build_country_index()

# Separators a source uses between a city, a region and a country.
_LOCATION_SEPARATORS = re.compile(r"[,;|/()\[\]\n]|\s+[-–—]\s+")

# Wordings that name a country inside a longer free-text location.
_COUNTRY_SEPARATORS = re.compile(r"[,;|/()\[\]]")


def _split_location(value: str) -> list[str]:
    return [part.strip() for part in _LOCATION_SEPARATORS.split(value) if part.strip()]


def canonical_country_code(value: Any) -> str:
    """Return the ISO-3166-1 alpha-2 code of a published country wording.

    ``""`` is returned for wording that names no readable country.  A missing
    country is unknown; it is never silently read as France or as any other
    country a source did not publish.
    """
    text = clean_text(value, limit=200)
    if not text:
        return ""
    key = normalized_text(text)
    if not key:
        return ""
    code = _COUNTRY_INDEX.get(key)
    if code:
        return code
    # A location such as "Paris, France" or "Paris (France)" carries the
    # country inside a longer wording: read it part by part.
    for part in _COUNTRY_SEPARATORS.split(text):
        part_key = normalized_text(part)
        if part_key:
            code = _COUNTRY_INDEX.get(part_key)
            if code:
                return code
    return ""


def country_codes_in(value: Any) -> tuple[str, ...]:
    """Every country code explicitly published inside a free-text location."""
    text = clean_text(value, limit=300)
    if not text:
        return ()
    found: list[str] = []
    for part in _split_location(text):
        code = canonical_country_code(part)
        if code and code not in found:
            found.append(code)
    return tuple(found)


def excluded_country_codes(values: Iterable[Any] | None) -> tuple[str, ...]:
    """ISO-3166-1 alpha-2 codes for country wordings a person excluded."""
    codes: list[str] = []
    for value in values or ():
        if not isinstance(value, str):
            continue
        for part in _COUNTRY_SEPARATORS.split(value):
            code = canonical_country_code(part)
            if code and code not in codes:
                codes.append(code)
    return tuple(codes)


def _normalize_codes(values: Iterable[Any] | None) -> tuple[str, ...]:
    """ISO-3166-1 alpha-2 codes from codes or published country wordings."""
    codes: list[str] = []
    for value in values or ():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        if len(text) == 2 and text.isalpha():
            code = text.upper()
        else:
            code = canonical_country_code(text)
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


# Historical default of each connector family.  The HTML connectors always
# excluded France before this filter existed; the ATS connectors never
# filtered a country.  A connector called without the parameter must keep
# its own historical behaviour.
DEFAULT_ATS_EXCLUDED_COUNTRIES: tuple[str, ...] = ()
DEFAULT_HTML_EXCLUDED_COUNTRIES: tuple[str, ...] = ("FR",)


def resolve_country_filter(
    countries_exclude: Sequence[str] | None = None,
    countries_include: Sequence[str] | None = None,
    *,
    default_exclude: Sequence[str] = DEFAULT_ATS_EXCLUDED_COUNTRIES,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Normalize the connector country filter.

    ``None`` keeps the connector's historical behaviour; an explicit empty
    list disables the country filter without changing anything else.
    """
    excluded = (
        _normalize_codes(default_exclude)
        if countries_exclude is None
        else _normalize_codes(countries_exclude)
    )
    return excluded, _normalize_codes(countries_include)


# --------------------------------------------------------------------------
# Location hints
# --------------------------------------------------------------------------

# City wording that suggests a country.  A hint is only ever used to exclude
# an offer; it never proves where an offer is located.
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


def _build_hint_index(hints: Mapping[str, str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for name, code in hints.items():
        key = normalized_text(name)
        if key:
            index.setdefault(key, code)
    return index


CITY_HINT_INDEX: dict[str, str] = _build_hint_index(_CITY_HINTS)
FRANCE_REGION_HINT_INDEX: dict[str, str] = _build_hint_index(_FRANCE_REGION_HINTS)
APEC_HINT_INDEX: dict[str, str] = {**CITY_HINT_INDEX, **FRANCE_REGION_HINT_INDEX}


def _hint_codes(text: str, hints: Mapping[str, str]) -> tuple[str, ...]:
    """Country codes suggested by a city or region wording."""
    normalized = normalized_text(text)
    if not normalized or not hints:
        return ()
    codes: list[str] = []
    direct = hints.get(normalized)
    if direct:
        return (direct,)
    for token in normalized.split():
        code = hints.get(token)
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


# --------------------------------------------------------------------------
# Decision
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GeoDecision:
    """Why one offer was kept or excluded by the country filter."""

    excluded: bool
    reason: str
    codes: tuple[str, ...] = ()
    used_hint: bool = False

    @property
    def kept(self) -> bool:
        return not self.excluded


def geo_filter_decision(
    *,
    location_text: Any = "",
    country: Any = "",
    excluded_codes: Sequence[str] | None = None,
    included_codes: Sequence[str] | None = None,
    hints: Mapping[str, str] | None = None,
) -> GeoDecision:
    """Decide whether one offer survives the country filter.

    ``location_text`` and ``country`` are the wordings a source published.
    ``excluded_codes`` and ``included_codes`` are ISO-3166-1 alpha-2 codes.
    ``hints`` maps a city or region wording to a country; a hint may only
    exclude an offer, never include one.
    """
    excluded = _normalize_codes(excluded_codes)
    included = _normalize_codes(included_codes)
    if not excluded and not included:
        return GeoDecision(excluded=False, reason="Aucun filtre pays demandé.", codes=())

    location = clean_text(location_text, limit=300)
    codes = list(country_codes_in(location))
    for code in country_codes_in(country):
        if code not in codes:
            codes.append(code)

    if codes:
        known = set(codes)
        if excluded and known.issubset(set(excluded)):
            return GeoDecision(
                excluded=True,
                reason=f"Pays publié exclu ({', '.join(codes)}).",
                codes=tuple(codes),
            )
        if included and not known.intersection(included):
            return GeoDecision(
                excluded=True,
                reason=f"Pays publié hors de la cible ({', '.join(codes)}).",
                codes=tuple(codes),
            )
        return GeoDecision(
            excluded=False,
            reason=f"Pays publié conservé ({', '.join(codes)}).",
            codes=tuple(codes),
        )

    if excluded and hints:
        city_parts = [part for part in _split_location(location) if not canonical_country_code(part)]
        # A posting published in several unnamed places is never excluded: it
        # is not possible to prove that every one of them is excluded.
        if len(city_parts) == 1:
            hinted = _hint_codes(city_parts[0], hints)
            if any(code in excluded for code in hinted):
                return GeoDecision(
                    excluded=True,
                    reason=f"Localisation indicative d'un pays exclu ({hinted[0]}).",
                    codes=hinted,
                    used_hint=True,
                )
    return GeoDecision(
        excluded=False,
        reason="Pays inconnu : l'offre reste visible.",
        codes=(),
    )
