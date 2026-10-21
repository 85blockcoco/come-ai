"""Analyse temporelle multilingue des offres d'emploi (SPEC-SK02 — CVBOOST-23).

Les connecteurs livrent souvent des champs dates vides et les descriptions
libres mélangent publication, échéance, début, fin et durée.  Ce module extrait
de chaque texte d'offre des **faits temporels datés et prouvés** : un type de
fait, une valeur normalisée, une précision, une confiance, la citation
verbatim et ses offsets exacts dans le texte source.

``extract_dates(text, lang, source_field) -> list[DateFact]``

Principes (garantis par les tests) :

* **Pur et déterministe** — aucun appel réseau, aucun modèle, aucune horloge :
  le même texte produit toujours les mêmes faits, dans le même ordre.
* **Aucune date inventée** — un jour absent du texte reste ``day=None`` ; une
  date numérique inversable (``01/02/2025``) est marquée ``ambiguous`` au lieu
  d'être devinée.
* **Un rôle par formulation** — « Apply by 15 November » est une ``deadline`` et
  jamais un début ; « Up to six months » est un maximum et jamais un minimum ;
  « Two years of prior experience » n'est jamais une durée de contrat.
* **Les contradictions sont exposées** — deux faits incompatibles se citent
  mutuellement dans ``contradictions`` ; rien n'est arbitré en silence.
* **Le texte de l'offre est une donnée non fiable** — il n'est jamais exécuté
  ni interprété comme une instruction.

Le vocabulaire est FR / EN / DE / IT / ES.  Une langue non reconnue déclenche
une détection automatique déterministe.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence

FactType = Literal[
    "published",
    "deadline",
    "start",
    "end",
    "duration_exact",
    "duration_min",
    "duration_max",
    "duration_range",
]
Precision = Literal["day", "month", "year", "unknown"]
Confidence = Literal["confirmed", "inferred", "ambiguous"]

FACT_TYPES: tuple[FactType, ...] = (
    "published",
    "deadline",
    "start",
    "end",
    "duration_exact",
    "duration_min",
    "duration_max",
    "duration_range",
)
DATE_FACT_TYPES: frozenset[str] = frozenset({"published", "deadline", "start", "end"})
DURATION_FACT_TYPES: frozenset[str] = frozenset(
    {"duration_exact", "duration_min", "duration_max", "duration_range"}
)
PRECISIONS: tuple[Precision, ...] = ("day", "month", "year", "unknown")
CONFIDENCES: tuple[Confidence, ...] = ("confirmed", "inferred", "ambiguous")
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "fr", "de", "it", "es")

#: Champs structurés dont le type est déjà connu : le champ *est* la preuve.
SOURCE_FIELD_TYPES: dict[str, str] = {
    "deadline_date": "deadline",
    "published_date": "published",
    "start_date": "start",
    "end_date": "end",
}

#: Champs d'offre inspectés par :func:`extract_offer_dates`.
OFFER_DATE_FIELDS: tuple[str, ...] = (
    "title",
    "description_original",
    "description",
    "requirements",
    "eligibility_requirement",
    "deadline_date",
    "published_date",
    "start_date",
    "end_date",
)

MAX_TEXT_CHARS = 60_000
_TRIGGER_WINDOW = 120
_CLAUSE_BOUNDARIES = ".!?;\n\r|•"

_ID_PREFIX = "df_"


@dataclass
class DateFact:
    """Un fait temporel prouvé, extrait d'un texte d'offre.

    ``value`` contient soit ``{"day", "month", "year"}`` (faits datés), soit
    ``{"months_min", "months_max", "unit", "source_unit", ...}`` (durées).
    ``contradictions`` contient les identifiants des autres faits incompatibles
    (``ambiguous_reading:<iso>`` pour une lecture inversée d'une date
    numérique).  ``start_offset``/``end_offset`` pointent la citation
    verbatim : ``text[start_offset:end_offset] == quote`` toujours.
    """

    fact_type: FactType
    value: dict[str, Any]
    precision: Precision
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Confidence
    contradictions: list[str] = field(default_factory=list)
    id: str = ""
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = _fact_id(self)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serialisable form of the fact."""
        return {
            "id": self.id,
            "fact_type": self.fact_type,
            "value": dict(self.value),
            "precision": self.precision,
            "source_field": self.source_field,
            "quote": self.quote,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "confidence": self.confidence,
            "contradictions": list(self.contradictions),
            "notes": list(self.notes),
        }


def _fact_id(fact: DateFact) -> str:
    """Return the deterministic identifier of a fact."""
    payload = "|".join(
        [
            fact.fact_type,
            _canonical_value(fact.value),
            str(fact.start_offset),
            str(fact.end_offset),
            fact.source_field,
        ]
    )
    return _ID_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _canonical_value(value: Mapping[str, Any]) -> str:
    return ",".join(f"{key}={value[key]!r}" for key in sorted(value))


# --------------------------------------------------------------------------
# Vocabulaire par langue
# --------------------------------------------------------------------------

_EN_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_FR_MONTHS: dict[str, int] = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12,
    "janv.": 1, "févr.": 2, "avr.": 4, "juil.": 7, "sept.": 9, "oct.": 10,
    "nov.": 11, "déc.": 12,
}
_DE_MONTHS: dict[str, int] = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11,
    "dezember": 12,
    "jan.": 1, "feb.": 2, "mär.": 3, "apr.": 4, "jun.": 6, "jul.": 7,
    "sep.": 9, "sept.": 9, "okt.": 10, "nov.": 11, "dez.": 12,
}
_IT_MONTHS: dict[str, int] = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
    "gen.": 1, "feb.": 2, "mar.": 3, "apr.": 4, "mag.": 5, "giu.": 6,
    "lug.": 7, "ago.": 8, "set.": 9, "ott.": 10, "nov.": 11, "dic.": 12,
}
_ES_MONTHS: dict[str, int] = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "ene.": 1, "feb.": 2, "mar.": 3, "abr.": 4, "may.": 5, "jun.": 6,
    "jul.": 7, "ago.": 8, "sep.": 9, "sept.": 9, "oct.": 10, "nov.": 11,
    "dic.": 12,
}

_EN_NUMBERS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "twenty-four": 24, "twenty-six": 26, "thirty-six": 36,
}
_FR_NUMBERS: dict[str, int] = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
    "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "dix-sept": 17,
    "dix-huit": 18, "dix-neuf": 19, "vingt": 20, "trente": 30,
    "vingt-quatre": 24, "vingt-six": 26, "trente-six": 36,
}
_DE_NUMBERS: dict[str, int] = {
    "eins": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12,
    "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16,
    "siebzehn": 17, "achtzehn": 18, "neunzehn": 19, "zwanzig": 20,
    "dreißig": 30, "vierundzwanzig": 24, "sechsunddreißig": 36,
}
_IT_NUMBERS: dict[str, int] = {
    "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11,
    "dodici": 12, "tredici": 13, "quattordici": 14, "quindici": 15,
    "sedici": 16, "diciassette": 17, "diciotto": 18, "diciannove": 19,
    "venti": 20, "trenta": 30, "ventiquattro": 24, "trentasei": 36,
}
_ES_NUMBERS: dict[str, int] = {
    "uno": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciséis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "treinta": 30, "veinticuatro": 24, "treinta y seis": 36,
}


@dataclass(frozen=True)
class _Trigger:
    """A wording that names the role of a date in the offer."""

    pattern: str
    fact_type: str
    rank: int  # 2 = explicit label, 1 = generic temporal preposition
    requires_start: bool = False


@dataclass(frozen=True)
class _LangPack:
    """Compiled vocabulary and patterns of one language."""

    code: str
    months: Mapping[str, int]
    numbers: Mapping[str, int]
    units: Mapping[str, str]
    triggers: tuple[_Trigger, ...]
    min_markers: tuple[str, ...]
    max_markers: tuple[str, ...]
    experience_markers: tuple[str, ...]
    contract_markers: tuple[str, ...]
    per_markers: tuple[str, ...]
    month_re: str
    number_re: str
    unit_re: str
    duration_re: re.Pattern[str]
    range_re: re.Pattern[str]
    date_patterns: tuple[re.Pattern[str], ...]
    numeric_patterns: tuple[re.Pattern[str], ...]


def _alternation(words: Iterable[str]) -> str:
    """Return a regex alternation, longest first so the longest form wins."""
    unique = sorted({word for word in words if word}, key=lambda word: (-len(word), word))
    return "|".join(re.escape(word) for word in unique)


def _word_regex(words: Iterable[str]) -> str:
    return r"(?<!\w)(?:" + _alternation(words) + r")(?!\w)"


# Connecteurs d'intervalle : « three to six months », « de 3 à 6 mois »,
# « drei bis sechs Monate », « da 3 a 6 mesi », « de 3 a 6 meses ».
_RANGE_CONNECTORS = (
    "to", "and", "et", "e", "und", "y", "a", "bis", "à", "a", "-", "–", "—",
)

_EN_TRIGGERS: tuple[_Trigger, ...] = (
    _Trigger(r"applications?\s+close", "deadline", 2),
    _Trigger(r"application\s+deadline|closing\s+date|deadline", "deadline", 2),
    _Trigger(r"no\s+later\s+than", "deadline", 2),
    _Trigger(r"apply\s+(?:by|before|until|no\s+later\s+than)", "deadline", 2),
    _Trigger(r"submit\s+(?:your\s+)?(?:application|cv|résumé)\s+(?:by|before)", "deadline", 2),
    _Trigger(r"last\s+date\s+to\s+apply", "deadline", 2),
    _Trigger(r"close[sd]?\s+on", "deadline", 2),
    _Trigger(r"published\s+on|posted\s+on|listed\s+on|advertised\s+on|announced\s+on", "published", 2),
    _Trigger(r"publication\s+date|date\s+of\s+publication", "published", 2),
    _Trigger(r"published|posted|listed", "published", 2),
    _Trigger(r"start\s+date|starting\s+date|commencement\s+date", "start", 2),
    _Trigger(r"starting|starts|commencing|beginning", "start", 2),
    _Trigger(r"work\s+starts|expected\s+start|onboarding\s+from", "start", 2),
    _Trigger(r"start", "start", 2),
    _Trigger(r"end\s+date|ending\s+on|ends\s+on", "end", 2),
    _Trigger(r"until|through|final\s+day|last\s+day|finishes?\s+on", "end", 2),
    _Trigger(r"ending|ends|finish|finishing", "end", 2),
    _Trigger(r"as\s+of|w\.e\.f\.", "start", 1),
    _Trigger(r"from", "start", 1),
    _Trigger(r"to", "end", 1, requires_start=True),
)

_FR_TRIGGERS: tuple[_Trigger, ...] = (
    _Trigger(r"date\s+limite(?:\s+de\s+(?:candidature|postulation))?", "deadline", 2),
    _Trigger(r"cl[ôo]ture\s+des\s+candidatures|d[ée]lai\s+de\s+candidature", "deadline", 2),
    _Trigger(r"postul(?:ez|er|ation)\s+(?:avant|jusqu['’]au)", "deadline", 2),
    _Trigger(r"candidat(?:ez|er|es|ures?)\s+(?:avant|jusqu['’]au)", "deadline", 2),
    _Trigger(r"d[ée]p[ôo]t(?:ez|er)?\s+(?:votre\s+)?candidature\s+avant", "deadline", 2),
    _Trigger(r"avant\s+le|au\s+plus\s+tard", "deadline", 2),
    _Trigger(r"publi[ée](?:e|s|é)?\s+le|post[ée]\s+le|mis\s+en\s+ligne\s+le|annonc[ée]\s+le", "published", 2),
    _Trigger(r"date\s+de\s+publication|publié\s*:", "published", 2),
    _Trigger(r"publi[ée]|publication", "published", 2),
    _Trigger(r"d[ée]but\s+(?:du\s+poste|de\s+la\s+mission|de\s+stage|d[ée]but)|prise\s+de\s+poste", "start", 2),
    _Trigger(r"commence\s+(?:le|au)|pr[ée]vu\s+pour\s+le|commencement", "start", 2),
    _Trigger(r"d[ée]but", "start", 2),
    _Trigger(r"date\s+de\s+fin|fin\s+(?:de\s+la\s+mission|du\s+poste)\s*:", "end", 2),
    _Trigger(r"se\s+termine\s+(?:le|au)|termine\s+(?:le|au)", "end", 2),
    _Trigger(r"jusqu['’]au|jusqu['’]à|au\s+plus\s+tard", "end", 2),
    _Trigger(r"à\s+partir\s+du|à\s+partir\s+de|disponible\s+à\s+partir", "start", 1),
)

_DE_TRIGGERS: tuple[_Trigger, ...] = (
    _Trigger(r"bewerbungsfrist|frist", "deadline", 2),
    _Trigger(r"bewerbungen?\s+bis|bewerben\s+sie\s+sich\s+bis|einreichen\s+bis", "deadline", 2),
    _Trigger(r"spätestens\s+am", "deadline", 2),
    _Trigger(r"veröffentlicht\s+am|ausgeschrieben\s+am|geschrieben\s+am", "published", 2),
    _Trigger(r"veröffentlichung\s*:|veröffentlicht", "published", 2),
    _Trigger(r"einsatzbeginn|arbeitsbeginn|beginn\s+des\s+praktikums|beginn\s+der\s+stelle", "start", 2),
    _Trigger(r"beginnt\s+am|start\s+am|einstieg\s+am", "start", 2),
    _Trigger(r"beginn", "start", 2),
    _Trigger(r"ende\s+des|vertragsende|dienstende|ende\s+der\s+stelle|endet\s+am|arbeitsende|gültig\s+bis", "end", 2),
    _Trigger(r"bis\s+einschließlich|letzter\s+tag", "end", 2),
    _Trigger(r"ab\s+dem|ab", "start", 1),
    _Trigger(r"bis", "end", 1, requires_start=True),
)

_IT_TRIGGERS: tuple[_Trigger, ...] = (
    _Trigger(r"scadenza(?:\s+candidatura)?|data\s+di\s+scadenza", "deadline", 2),
    _Trigger(r"termine\s+per\s+(?:la\s+)?candidatura|candidars[iì]\s+entro", "deadline", 2),
    _Trigger(r"entro", "deadline", 2),
    _Trigger(r"pubblicat[oa]\s+(?:il\s+)?(?:giorno\s+)?|inserito\s+il", "published", 2),
    _Trigger(r"pubblicazione\s*:|data\s+di\s+pubblicazione", "published", 2),
    _Trigger(r"inizio\s+(?:del|della|di\s+lavoro|previsto)|assunzione", "start", 2),
    _Trigger(r"inizia\s+(?:il|dal)|primo\s+giorno", "start", 2),
    _Trigger(r"inizio", "start", 2),
    _Trigger(r"fine\s+(?:del|della|contratto)|termine\s+(?:del|di\s+lavoro)|conclude\s+il", "end", 2),
    _Trigger(r"fino\s+al", "end", 2),
    _Trigger(r"a\s+partire\s+dal|a\s+partire\s+da|dal", "start", 1),
)

_ES_TRIGGERS: tuple[_Trigger, ...] = (
    _Trigger(r"fecha\s+l[íi]mite|plazo\s+de\s+(?:solicitud|presentaci[óo]n)|cierre\s+de\s+candidaturas", "deadline", 2),
    _Trigger(r"postular\s+(?:antes|hasta)|candidatar\s+(?:antes|hasta)|solicitar\s+hasta|inscribirse\s+hasta", "deadline", 2),
    _Trigger(r"caduca\s+el|inscripciones?\s+hasta", "deadline", 2),
    _Trigger(r"publicad[oa]\s+el|publicaci[óo]n\s*:|fecha\s+de\s+publicaci[óo]n", "published", 2),
    _Trigger(r"inicio\s+(?:del|de\s+la\s+empresa)|fecha\s+de\s+inicio|comienzo", "start", 2),
    _Trigger(r"comienza\s+el|empieza\s+el", "start", 2),
    _Trigger(r"inicio", "start", 2),
    _Trigger(r"fecha\s+de\s+fin|fin\s+del|finaliza\s+el|termina\s+el", "end", 2),
    _Trigger(r"hasta\s+el", "end", 1, requires_start=True),
    _Trigger(r"a\s+partir\s+del|a\s+partir\s+de", "start", 1),
)


def _build_pack(
    code: str,
    months: Mapping[str, int],
    numbers: Mapping[str, int],
    units: Mapping[str, str],
    triggers: Sequence[_Trigger],
    min_markers: Sequence[str],
    max_markers: Sequence[str],
    experience_markers: Sequence[str],
    contract_markers: Sequence[str],
    per_markers: Sequence[str],
    day_prefix: str,
    year_suffix: str,
    month_year_suffix: str,
    extra_date_patterns: Sequence[str] = (),
) -> _LangPack:
    month_re = _word_regex(months)
    number_re = r"(?:(?:\d{1,3}(?!\d))|" + _alternation(numbers) + r")"
    unit_re = _word_regex(units)
    # Lookups are case-insensitive: the source text keeps its own casing.
    month_lookup = {key.lower(): value for key, value in months.items()}
    number_lookup = {key.lower(): value for key, value in numbers.items()}
    unit_lookup = {key.lower(): value for key, value in units.items()}

    duration_re = re.compile(
        r"(?<!\w)(?P<num>" + number_re + r")\s*(?:-|–|—)?\s*(?P<unit>" + unit_re + r")(?!\w)",
        re.IGNORECASE,
    )
    range_re = re.compile(
        r"(?<!\w)(?P<lo>" + number_re + r")\s*(?P<conn>" + _alternation(_RANGE_CONNECTORS) + r")\s*"
        r"(?P<hi>" + number_re + r")\s*(?:-|–|—)?\s*(?P<unit>" + unit_re + r")(?!\w)",
        re.IGNORECASE,
    )

    date_patterns = [
        re.compile(r"(?<!\w)" + day_prefix + r"(?P<month>" + month_re + r")" + year_suffix, re.IGNORECASE),
        re.compile(r"(?<!\w)(?P<month>" + month_re + r")" + month_year_suffix, re.IGNORECASE),
        re.compile(r"(?<!\w)(?P<month>" + month_re + r")(?!\w)", re.IGNORECASE),
    ]
    for extra in extra_date_patterns:
        date_patterns.insert(0, re.compile(extra, re.IGNORECASE))
    date_patterns.append(
        re.compile(
            r"(?<!\w)(?P<month>" + month_re + r")\s+(?P<day>\d{1,2})(?!\d)(?:st|nd|rd|th)?"
            r"(?:\s*,?\s*(?P<year>\d{4}))?",
            re.IGNORECASE,
        )
    )

    numeric_patterns = [
        re.compile(r"(?<![\w-])(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?![\w-])"),
        re.compile(r"(?<![\w-])(?P<year>\d{4})-(?P<month>\d{1,2})(?![\w-])"),
        re.compile(r"(?<![\w-])(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})(?![\w])"),
        re.compile(r"(?<![\w])(?P<a>\d{1,2})[/.](?P<b>\d{1,2})[/.](?P<year>\d{4})(?![\w])"),
        re.compile(r"(?<![\w])(?P<a>\d{1,2})[/.](?P<year>\d{4})(?![\w])"),
        re.compile(r"(?<!\w)(?P<year>(?:19|20)\d{2})(?![\w])"),
    ]

    return _LangPack(
        code=code,
        months=month_lookup,
        numbers=number_lookup,
        units=unit_lookup,
        triggers=tuple(triggers),
        min_markers=tuple(min_markers),
        max_markers=tuple(max_markers),
        experience_markers=tuple(experience_markers),
        contract_markers=tuple(contract_markers),
        per_markers=tuple(per_markers),
        month_re=month_re,
        number_re=number_re,
        unit_re=unit_re,
        duration_re=duration_re,
        range_re=range_re,
        date_patterns=tuple(date_patterns),
        numeric_patterns=tuple(numeric_patterns),
    )


_PACKS: dict[str, _LangPack] = {
    "en": _build_pack(
        "en",
        _EN_MONTHS,
        _EN_NUMBERS,
        {"month": "months", "months": "months", "week": "weeks", "weeks": "weeks", "year": "years", "years": "years"},
        _EN_TRIGGERS,
        min_markers=("at least", "a minimum of", "minimum of", "at minimum", "no less than", "minimum"),
        max_markers=("up to", "at most", "no more than", "not more than", "maximum of", "max of", "limited to", "not exceeding", "maximum"),
        experience_markers=("experience", "experienced", "background", "track record"),
        contract_markers=("contract", "internship", "apprenticeship", "traineeship", "employment", "assignment"),
        per_markers=("per", "/"),
        day_prefix=r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?",
        year_suffix=r"(?:\s*,?\s*(?P<year>\d{4}))?",
        month_year_suffix=r"(?:\s*,?\s*(?P<year>\d{4}))",
    ),
    "fr": _build_pack(
        "fr",
        _FR_MONTHS,
        _FR_NUMBERS,
        {"mois": "months", "semaine": "weeks", "semaines": "weeks", "an": "years", "ans": "years", "année": "years", "années": "years"},
        _FR_TRIGGERS,
        min_markers=("au moins", "a minima", "minimum de", "au minimum"),
        max_markers=("jusqu'à", "jusqu’a", "au plus", "maximum de", "maximum"),
        experience_markers=("expérience", "experienced", "expérience", "ancienneté", "ancieneté"),
        contract_markers=("contrat", "stage", "alternance", "poste", "mission"),
        per_markers=("par", "/"),
        day_prefix=r"(?P<day>\d{1,2})(?:er)?\s+",
        year_suffix=r"(?:\s*,?\s*(?P<year>\d{4}))?",
        month_year_suffix=r"(?:\s*,?\s*(?P<year>\d{4}))",
    ),
    "de": _build_pack(
        "de",
        _DE_MONTHS,
        _DE_NUMBERS,
        {"Monat": "months", "Monate": "months", "Monaten": "months", "Woche": "weeks", "Wochen": "weeks", "Jahr": "years", "Jahre": "years", "Jahren": "years"},
        _DE_TRIGGERS,
        min_markers=("mindestens", "minimum"),
        max_markers=("bis zu", "höchstens", "maximal", "max."),
        experience_markers=("Erfahrung", "Berufserfahrung", "Erfahrungsjahre"),
        contract_markers=("Vertrag", "Praktikum", "Ausbildung", "Stelle", "Anstellung"),
        per_markers=("pro", "/"),
        day_prefix=r"(?P<day>\d{1,2})\.?\s+",
        year_suffix=r"(?:\s*,?\s*(?P<year>\d{4}))?",
        month_year_suffix=r"(?:\s*,?\s*(?P<year>\d{4}))",
    ),
    "it": _build_pack(
        "it",
        _IT_MONTHS,
        _IT_NUMBERS,
        {"mese": "months", "mesi": "months", "settimana": "weeks", "settimane": "weeks", "anno": "years", "anni": "years"},
        _IT_TRIGGERS,
        min_markers=("almeno", "minimo di", "minimo"),
        max_markers=("fino a", "massimo", "al massimo"),
        experience_markers=("esperienza", "esperienze", "anziano"),
        contract_markers=("contratto", "stage", "tirocinio", "poste"),
        per_markers=("al", "/"),
        day_prefix=r"(?P<day>\d{1,2})\s+(?:di\s+)?",
        year_suffix=r"(?:\s*,?\s*(?P<year>\d{4}))?",
        month_year_suffix=r"(?:\s*,?\s*(?P<year>\d{4}))",
    ),
    "es": _build_pack(
        "es",
        _ES_MONTHS,
        _ES_NUMBERS,
        {"mes": "months", "meses": "months", "semana": "weeks", "semanas": "weeks", "año": "years", "años": "years"},
        _ES_TRIGGERS,
        min_markers=("al menos", "mínimo de", "minimo de"),
        max_markers=("hasta", "como máximo", "máximo de", "maximo de"),
        experience_markers=("experiencia", "experiencia laboral"),
        contract_markers=("contrato", "prácticas", "practicas", "puesto", "empleo"),
        per_markers=("por", "/"),
        day_prefix=r"(?P<day>\d{1,2})\s+(?:de\s+)?",
        year_suffix=r"(?:\s*,?\s*(?:de\s+)?(?P<year>\d{4}))?",
        month_year_suffix=r"(?:\s*,?\s*(?:de\s+)?(?P<year>\d{4}))",
    ),
}


# --------------------------------------------------------------------------
# Détection de langue
# --------------------------------------------------------------------------

_LANGUAGE_HINTS: dict[str, tuple[str, ...]] = {
    "en": (
        "the", "and", "with", "role", "team", "apply", "experience", "contract",
        "you will", "responsibilities", "deadline", "position", "job", "we are",
        "salary", "requirements", "starting",
    ),
    "fr": (
        "le", "la", "les", "des", "une", "poste", "candidature", "candidatures",
        "date limite", "limite", "notre", "votre", "nous recherchons", "profil",
        "durée", "stage", "avec", "cv", "date de publication",
    ),
    "de": (
        "der", "die", "das", "und", "bewerbung", "bewerbungsfrist", "unternehmen",
        "praktikum", "wir bieten", "ihre", "stelle", "beginn", "veröffentlicht",
    ),
    "it": (
        "il", "di", "per", "azienda", "candidatura", "scadenza", "stage",
        "offriamo", "esperienza", "nel", "anche", "pubblicato", "inizio",
    ),
    "es": (
        "el", "los", "las", "puesto", "candidatura", "fecha límite", "empresa",
        "buscamos", "experiencia", "con", "salario", "publicado", "inicio",
    ),
}


def detect_language(text: str) -> str:
    """Return the most likely language code of ``text`` among the supported ones.

    Deterministic: the score of each language is the number of occurrences of
    its stop-words (case-insensitive).  ``"en"`` is returned when nothing
    matches.
    """
    if not text:
        return "en"
    lowered = text.lower()
    scores: dict[str, int] = {}
    for code, hints in _LANGUAGE_HINTS.items():
        score = 0
        for hint in hints:
            score += len(re.findall(r"(?<!\w)" + re.escape(hint) + r"(?!\w)", lowered))
        scores[code] = score
    best = max(SUPPORTED_LANGUAGES, key=lambda code: (scores[code], -SUPPORTED_LANGUAGES.index(code)))
    return best if scores[best] > 0 else "en"


def _resolve_pack(lang: str, text: str = "") -> _LangPack:
    """Return the language pack for ``lang`` (auto-detection when unknown)."""
    code = (lang or "").strip().lower().replace("_", "-").split("-")[0]
    if code in _PACKS:
        return _PACKS[code]
    if code in {"", "auto", "any", "xx"}:
        return _PACKS[detect_language(text)]
    return _PACKS["en"]


# --------------------------------------------------------------------------
# Détection des mentions temporelles
# --------------------------------------------------------------------------


@dataclass
class _Mention:
    """A raw date or duration mention found in the text."""

    start: int
    end: int
    kind: str  # "date" | "duration"
    payload: dict[str, Any]


def _iter_mentions(pack: _LangPack, text: str) -> list[_Mention]:
    """Return every date and duration mention, overlaps resolved greedily."""
    candidates: list[_Mention] = []

    for pattern in pack.date_patterns:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            month_token = (groups.get("month") or "").strip().lower()
            month = pack.months.get(month_token)
            if month is None:
                continue
            day_token = groups.get("day")
            year_token = groups.get("year")
            day = int(day_token) if day_token else None
            year = int(year_token) if year_token else None
            if day is not None and not 1 <= day <= 31:
                continue
            candidates.append(
                _Mention(
                    start=match.start(),
                    end=match.end(),
                    kind="date",
                    payload={"day": day, "month": month, "year": year, "ambiguous": False},
                )
            )

    for pattern in pack.numeric_patterns:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            payload = _parse_numeric_date(groups)
            if payload is None:
                continue
            candidates.append(
                _Mention(
                    start=match.start(),
                    end=match.end(),
                    kind="date",
                    payload=payload,
                )
            )

    for pattern in pack.range_re.finditer(text):
        low = _to_int(pack, pattern.group("lo"))
        high = _to_int(pack, pattern.group("hi"))
        if low is None or high is None:
            continue
        if high < low:
            low, high = high, low
        unit = pack.units.get(pattern.group("unit").strip().lower())
        if unit is None:
            continue
        candidates.append(
            _Mention(
                start=pattern.start(),
                end=pattern.end(),
                kind="duration",
                payload={"low": low, "high": high, "unit": unit, "bounded": "range"},
            )
        )

    for pattern in pack.duration_re.finditer(text):
        if any(candidate.start <= pattern.start() < candidate.end for candidate in candidates if candidate.kind == "duration"):
            continue
        amount = _to_int(pack, pattern.group("num"))
        if amount is None:
            continue
        unit = pack.units.get(pattern.group("unit").strip().lower())
        if unit is None:
            continue
        candidates.append(
            _Mention(
                start=pattern.start(),
                end=pattern.end(),
                kind="duration",
                payload={"low": amount, "high": amount, "unit": unit, "bounded": "single"},
            )
        )

    candidates.sort(key=lambda mention: (mention.start, -(mention.end - mention.start)))
    accepted: list[_Mention] = []
    for candidate in candidates:
        if any(candidate.start < kept.end and kept.start < candidate.end for kept in accepted):
            continue
        accepted.append(candidate)
    accepted.sort(key=lambda mention: (mention.start, mention.end))
    return accepted


def _to_int(pack: _LangPack, token: Optional[str]) -> Optional[int]:
    if token is None:
        return None
    text = token.strip().lower()
    if text.isdigit():
        return int(text)
    return pack.numbers.get(text)


def _parse_numeric_date(groups: Mapping[str, Optional[str]]) -> Optional[dict[str, Any]]:
    """Normalise a numeric date into ``{day, month, year, ambiguous}``."""
    if groups.get("a") is not None and groups.get("b") is not None:
        first = int(groups["a"])
        second = int(groups["b"])
        year = int(groups["year"])
        if first > 12 and second <= 12:
            return {"day": first, "month": second, "year": year, "ambiguous": False}
        if second > 12 and first <= 12:
            return {"day": second, "month": first, "year": year, "ambiguous": False}
        if first == second:
            return {"day": first, "month": first, "year": year, "ambiguous": False}
        return {"day": None, "month": None, "year": year, "ambiguous": True, "alt": (first, second)}
    if groups.get("a") is not None and groups.get("year") is not None:
        month = int(groups["a"])
        if not 1 <= month <= 12:
            return None
        return {"day": None, "month": month, "year": int(groups["year"]), "ambiguous": False}
    if groups.get("year") is not None:
        year = int(groups["year"])
        if "month" in groups and groups["month"] is not None:
            month = int(groups["month"])
            if not 1 <= month <= 12:
                return None
            day = int(groups["day"]) if groups.get("day") else None
            if day is not None and not 1 <= day <= 31:
                return None
            return {"day": day, "month": month, "year": year, "ambiguous": False}
        return {"day": None, "month": None, "year": year, "ambiguous": False}
    return None


# --------------------------------------------------------------------------
# Rôle sémantique : déclencheurs et qualificatifs
# --------------------------------------------------------------------------


def _clause_context(text: str, position: int) -> tuple[int, str]:
    """Return ``(absolute_start, context)`` of the clause preceding ``position``."""
    start = max(0, position - _TRIGGER_WINDOW)
    segment = text[start:position]
    cut = -1
    for index in range(len(segment) - 1, -1, -1):
        if segment[index] in _CLAUSE_BOUNDARIES:
            cut = index
            break
    if cut >= 0:
        segment = segment[cut + 1 :]
        start = start + cut + 1
    return start, segment


def _find_trigger(pack: _LangPack, context: str) -> Optional[tuple[str, int, int, int]]:
    """Return ``(fact_type, rank, quote_start, match_end)`` of the best trigger.

    The best trigger is the most explicit one (rank 2 beats rank 1); ties are
    won by the closest one to the date and, at equal distance, by the most
    specific wording (deadline before published before start before end).
    A generic connector such as "to" only counts when the clause already
    carries a start marker.
    """
    matches: list[tuple[int, int, int, int, _Trigger]] = []
    for index, trigger in enumerate(pack.triggers):
        pattern = re.compile(r"(?<!\w)(?:" + trigger.pattern + r")(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(context):
            if trigger.requires_start and not _has_start_marker(pack, context, match.start()):
                continue
            matches.append((trigger.rank, match.end(), match.start(), index, trigger))
    if not matches:
        return None
    rank, end, start, _index, trigger = max(matches, key=lambda item: (item[0], item[1], -item[3]))
    return trigger.fact_type, rank, start, end


def _has_start_marker(pack: _LangPack, context: str, before: int) -> bool:
    """Return True when the clause already names a start before ``before``."""
    for trigger in pack.triggers:
        if trigger.fact_type != "start":
            continue
        pattern = re.compile(r"(?<!\w)(?:" + trigger.pattern + r")(?!\w)", re.IGNORECASE)
        if pattern.search(context[:before]):
            return True
    return False


def _duration_marker(pack: _LangPack, context: str) -> tuple[str, int]:
    """Return ``(bounded, qualifier_start)`` for a duration mention.

    ``bounded`` is ``"min"``, ``"max"``, ``"range"`` or ``"single"``.  The
    qualifier start is the offset (inside ``context``) of the marker that
    qualifies the duration, so the quote keeps the whole evidence.
    """
    lowered = context.lower()
    best: Optional[tuple[int, int, str]] = None
    for marker in pack.min_markers:
        position = lowered.rfind(marker.lower())
        if position >= 0 and (best is None or position > best[0]):
            best = (position, len(marker), "min")
    for marker in pack.max_markers:
        position = lowered.rfind(marker.lower())
        if position >= 0 and (best is None or position > best[0]):
            best = (position, len(marker), "max")
    if best is None:
        return "single", len(context)
    return best[2], best[0]


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Return the bounds of the clause containing ``[start:end]``."""
    left = start
    while left > 0 and text[left - 1] not in _CLAUSE_BOUNDARIES:
        left -= 1
    right = end
    while right < len(text) and text[right] not in _CLAUSE_BOUNDARIES:
        right += 1
    return left, right


def _is_experience_phrase(pack: _LangPack, text: str, start: int, end: int) -> bool:
    """Return True when the mention is an experience requirement, not a duration.

    The test is clause-scoped: "2 years of experience" is never a contract
    duration, while "our 6-month contract" stays one even when the same
    sentence also mentions an experience requirement.
    """
    left, right = _clause_bounds(text, start, end)
    clause = text[left:right].lower()
    if not any(marker.lower() in clause for marker in pack.experience_markers):
        return False
    # A contract word right next to the mention protects a real contract duration.
    around = (text[max(left, start - 20) : start] + " " + text[end : min(right, end + 20)]).lower()
    return not any(marker.lower() in around for marker in pack.contract_markers)


def _is_rate_phrase(pack: _LangPack, text: str, start: int, end: int) -> bool:
    """Return True when the mention is a rate ("60 000 EUR per year")."""
    before = text[max(0, start - 30) : start].lower()
    after = text[end : end + 30].lower()
    for marker in pack.per_markers:
        token = marker.lower()
        if token == "/":
            if before.rstrip().endswith("/") or after.lstrip().startswith("/"):
                return True
            continue
        if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)\s*$", before):
            return True
        if re.match(r"^\s*(?<!\w)" + re.escape(token) + r"(?!\w)\s", after):
            return True
    return False


# --------------------------------------------------------------------------
# Construction des faits
# --------------------------------------------------------------------------


def _date_precision(payload: Mapping[str, Any]) -> Precision:
    if payload.get("ambiguous"):
        return "unknown"
    if payload.get("day") is not None:
        return "day"
    if payload.get("month") is not None:
        return "month"
    if payload.get("year") is not None:
        return "year"
    return "unknown"


def _make_date_fact(
    fact_type: str,
    payload: Mapping[str, Any],
    text: str,
    source_field: str,
    quote_start: int,
    quote_end: int,
    rank: int,
) -> DateFact:
    """Build a dated fact from a mention and its semantic role."""
    day = payload.get("day")
    month = payload.get("month")
    year = payload.get("year")
    value: dict[str, Any] = {"day": day, "month": month, "year": year}
    precision = _date_precision(payload)
    notes: list[str] = []

    if payload.get("ambiguous"):
        first, second = payload["alt"]
        confidence: Confidence = "ambiguous"
        notes.append(
            f"date numérique inversable : {first:02d}/{second:02d} peut se lire "
            "jour/mois ou mois/jour, le jour n'est pas deviné"
        )
    elif year is None and precision != "unknown":
        confidence = "inferred"
        notes.append("l'année n'est pas indiquée dans le texte source")
    elif rank == 1:
        confidence = "inferred"
        notes.append("rôle temporel déduit d'un marqueur générique")
    else:
        confidence = "confirmed"

    contradictions: list[str] = []
    if payload.get("ambiguous"):
        first, second = payload["alt"]
        contradictions.append(f"ambiguous_reading:{year}-{second:02d}-{first:02d}")
        contradictions.append(f"ambiguous_reading:{year}-{first:02d}-{second:02d}")

    fact = DateFact(
        fact_type=fact_type,  # type: ignore[arg-type]
        value=value,
        precision=precision,
        source_field=source_field,
        quote=text[quote_start:quote_end],
        start_offset=quote_start,
        end_offset=quote_end,
        confidence=confidence,
        contradictions=contradictions,
        notes=notes,
    )
    return fact


def _duration_value(low: int, high: int, unit: str) -> dict[str, Any]:
    """Return the normalised value of a duration."""
    if unit == "months":
        months_min, months_max = low, high
    elif unit == "years":
        months_min, months_max = low * 12, high * 12
    else:  # weeks: no lossy conversion
        months_min, months_max = None, None
    return {
        "months_min": months_min,
        "months_max": months_max,
        "unit": unit,
        "source_unit": unit,
        "source_amount_min": low,
        "source_amount_max": high,
    }


def _make_duration_fact(
    bounded: str,
    payload: Mapping[str, Any],
    text: str,
    source_field: str,
    quote_start: int,
    quote_end: int,
) -> DateFact:
    """Build a duration fact (exact, min, max or range)."""
    low = int(payload["low"])
    high = int(payload["high"])
    unit = str(payload["unit"])
    if bounded == "range":
        fact_type = "duration_range"
    elif bounded == "min":
        fact_type = "duration_min"
    elif bounded == "max":
        fact_type = "duration_max"
    else:
        fact_type = "duration_exact"

    value = _duration_value(low, high, unit)
    if bounded == "min":
        value["months_max"] = None
    elif bounded == "max":
        value["months_min"] = None
    elif bounded == "single":
        value["months_min"] = low if unit != "weeks" else None
        value["months_max"] = high if unit != "weeks" else None

    return DateFact(
        fact_type=fact_type,  # type: ignore[arg-type]
        value=value,
        precision="unknown",
        source_field=source_field,
        quote=text[quote_start:quote_end],
        start_offset=quote_start,
        end_offset=quote_end,
        confidence="confirmed",
        contradictions=[],
        notes=[],
    )


def extract_dates(text: str, lang: str = "auto", source_field: str = "description_original") -> list[DateFact]:
    """Extract every dated and duration fact found in ``text``.

    Args:
        text: the untrusted offer text to analyse.
        lang: one of ``en``, ``fr``, ``de``, ``it``, ``es``; any other value
            (or ``"auto"``) triggers :func:`detect_language`.
        source_field: the offer field the text comes from.  Structured date
            fields (``deadline_date``, ``published_date``, ``start_date``,
            ``end_date``) name their own role, so every date they contain is a
            fact of that role.

    Returns:
        The facts, sorted by their position in ``text``.  Each fact quotes the
        exact passage that proves it: ``text[fact.start_offset:fact.end_offset]
        == fact.quote``.
    """
    if not text or not isinstance(text, str):
        return []
    text = text[:MAX_TEXT_CHARS]
    pack = _resolve_pack(lang, text)
    forced_type = SOURCE_FIELD_TYPES.get(source_field)

    facts: list[DateFact] = []
    for mention in _iter_mentions(pack, text):
        if mention.kind == "date":
            fact = _date_fact_from_mention(pack, mention, text, source_field, forced_type)
        else:
            fact = _duration_fact_from_mention(pack, mention, text, source_field)
        if fact is not None:
            facts.append(fact)

    _link_contradictions(facts)
    facts.sort(key=lambda fact: (fact.start_offset, fact.end_offset))
    return facts


def _date_fact_from_mention(
    pack: _LangPack,
    mention: _Mention,
    text: str,
    source_field: str,
    forced_type: Optional[str],
) -> Optional[DateFact]:
    """Build the dated fact of a date mention, or None when unlabelled."""
    payload = mention.payload
    if forced_type is not None:
        return _make_date_fact(
            forced_type,
            payload,
            text,
            source_field,
            mention.start,
            mention.end,
            rank=2,
        )

    context_start, context = _clause_context(text, mention.start)
    trigger = _find_trigger(pack, context)
    if trigger is None:
        return None
    fact_type, rank, trigger_start, _ = trigger
    quote_start = context_start + trigger_start
    return _make_date_fact(
        fact_type,
        payload,
        text,
        source_field,
        quote_start,
        mention.end,
        rank=rank,
    )


def _duration_fact_from_mention(
    pack: _LangPack,
    mention: _Mention,
    text: str,
    source_field: str,
) -> Optional[DateFact]:
    """Build the duration fact of a duration mention, or None when irrelevant."""
    if _is_experience_phrase(pack, text, mention.start, mention.end):
        return None
    if _is_rate_phrase(pack, text, mention.start, mention.end):
        return None

    context_start, context = _clause_context(text, mention.start)
    bounded, qualifier_start = _duration_marker(pack, context)
    if mention.payload.get("bounded") == "range":
        bounded = "range"
    quote_start = context_start + qualifier_start
    return _make_duration_fact(bounded, mention.payload, text, source_field, quote_start, mention.end)


# --------------------------------------------------------------------------
# Contradictions
# --------------------------------------------------------------------------


def _values_conflict(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Return True when two dated values cannot both be true."""
    for key in ("day", "month", "year"):
        first = left.get(key)
        second = right.get(key)
        if first is not None and second is not None and first != second:
            return True
    return False


def _dates_comparable(left: Mapping[str, Any], right: Mapping[str, Any]) -> Optional[tuple[int, int]]:
    """Return the (start, end) ordinals when two dated values are comparable."""
    if left.get("ambiguous") or right.get("ambiguous"):
        return None
    if left.get("year") is None or right.get("year") is None:
        return None
    if left.get("month") is None or right.get("month") is None:
        return None
    first = int(left["year"]) * 10000 + int(left["month"]) * 100 + int(left.get("day") or 1)
    second = int(right["year"]) * 10000 + int(right["month"]) * 100 + int(right.get("day") or 1)
    return first, second


def _duration_bounds(fact: DateFact) -> Optional[tuple[Optional[int], Optional[int]]]:
    value = fact.value
    if value.get("unit") == "weeks":
        return None
    return value.get("months_min"), value.get("months_max")


def _link_contradictions(facts: list[DateFact]) -> None:
    """Cross-reference the facts and fill their ``contradictions`` lists."""
    for index, left in enumerate(facts):
        for right in facts[index + 1 :]:
            if not _contradicts(left, right):
                continue
            if right.id not in left.contradictions:
                left.contradictions.append(right.id)
            if left.id not in right.contradictions:
                right.contradictions.append(left.id)


def _contradicts(left: DateFact, right: DateFact) -> bool:
    """Return True when two facts cannot both hold."""
    if left.fact_type in DATE_FACT_TYPES and right.fact_type in DATE_FACT_TYPES:
        if left.fact_type == right.fact_type and _values_conflict(left.value, right.value):
            return True
        if {left.fact_type, right.fact_type} == {"start", "end"}:
            ordinals = _dates_comparable(left.value, right.value)
            if ordinals is not None:
                start_value, end_value = ordinals
                if left.fact_type == "start" and start_value > end_value:
                    return True
                if right.fact_type == "start" and end_value > start_value:
                    return True
        return False

    if left.fact_type in DURATION_FACT_TYPES and right.fact_type in DURATION_FACT_TYPES:
        return _durations_conflict(left, right)
    return False


def _durations_conflict(left: DateFact, right: DateFact) -> bool:
    """Return True when two duration facts cannot both hold."""
    left_bounds = _duration_bounds(left)
    right_bounds = _duration_bounds(right)
    if left_bounds is None or right_bounds is None:
        return False
    left_min, left_max = left_bounds
    right_min, right_max = right_bounds

    if left.fact_type == "duration_min" and right.fact_type == "duration_max":
        if left_min is not None and right_max is not None and left_min > right_max:
            return True
    if left.fact_type == "duration_max" and right.fact_type == "duration_min":
        if right_min is not None and left_max is not None and right_min > left_max:
            return True
    if left.fact_type == "duration_exact" and right.fact_type == "duration_range":
        return not _within(left.value, right.value)
    if left.fact_type == "duration_range" and right.fact_type == "duration_exact":
        return not _within(right.value, left.value)
    if left.fact_type == "duration_exact" and right.fact_type == "duration_min":
        return right_min is not None and left_max is not None and left_max < right_min
    if left.fact_type == "duration_min" and right.fact_type == "duration_exact":
        return left_min is not None and right_max is not None and right_max < left_min
    if left.fact_type == "duration_exact" and right.fact_type == "duration_max":
        return left_min is not None and right_max is not None and left_min > right_max
    if left.fact_type == "duration_max" and right.fact_type == "duration_exact":
        return right_min is not None and left_max is not None and right_min > left_max
    return False


def _within(exact: Mapping[str, Any], bounds: Mapping[str, Any]) -> bool:
    """Return True when an exact duration sits inside a range."""
    value = exact.get("months_min")
    low = bounds.get("months_min")
    high = bounds.get("months_max")
    if value is None or low is None or high is None:
        return True
    return low <= value <= high


# --------------------------------------------------------------------------
# Aides
# --------------------------------------------------------------------------


def extract_offer_dates(offer: Mapping[str, Any]) -> list[DateFact]:
    """Extract the temporal facts of every dated field of an offer.

    Each field is analysed with its own ``source_field`` so the provenance of
    a fact stays exact.  Fields that are absent or empty are ignored.
    """
    facts: list[DateFact] = []
    for field_name in OFFER_DATE_FIELDS:
        if field_name not in offer:
            continue
        raw = offer.get(field_name)
        if not isinstance(raw, str) or not raw.strip():
            continue
        language = str(offer.get("language") or offer.get("lang") or "auto")
        facts.extend(extract_dates(raw, language, field_name))
    return facts


def facts_to_json(facts: Iterable[DateFact]) -> list[dict[str, Any]]:
    """Return the JSON-serialisable form of a list of facts."""
    return [fact.to_dict() for fact in facts]


__all__ = [
    "CONFIDENCES",
    "DURATION_FACT_TYPES",
    "DATE_FACT_TYPES",
    "DateFact",
    "FACT_TYPES",
    "OFFER_DATE_FIELDS",
    "PRECISIONS",
    "SOURCE_FIELD_TYPES",
    "SUPPORTED_LANGUAGES",
    "detect_language",
    "extract_dates",
    "extract_offer_dates",
    "facts_to_json",
]
