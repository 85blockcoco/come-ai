"""Multilingual temporal analyzer for job offers (SPEC SK-02 / CVBOOST-23).

The connectors of the Career workspace often return empty dates, and the
qualification code that exists today does not separate *publication*,
*application deadline*, *start*, *end* and *duration*.  This module reads an
offer text and returns **dated facts with their exact proof**.

WHAT IT DOES
- Extracts eight fact types: ``published``, ``deadline``, ``start``, ``end``,
  ``duration_exact``, ``duration_min``, ``duration_max`` and ``duration_range``.
- Supports five languages: French, English, German, Italian and Spanish.
- Every fact carries the verbatim ``quote``, the exact ``start_offset`` /
  ``end_offset`` of that quote inside the analysed text, the ``precision``
  (day / month / year / unknown), the ``confidence``
  (confirmed / inferred / ambiguous) and the list of the facts it
  contradicts.
- Facts are never merged: a publication and a deadline written in the same
  sentence stay two distinct facts.

WHAT IT NEVER DOES
- It never invents a day: ``"Starting January"`` is ``start`` with
  ``precision="month"`` and ``value["day"] is None`` — never the 1st.
- It never turns a deadline into a start: ``"Apply by 15 November"`` is a
  ``deadline``, and only a ``deadline``.
- It never turns a maximum into a minimum: ``"Up to six months"`` is a
  ``duration_max``, ``"At least six months"`` a ``duration_min``.
- It never turns a contract duration into an experience requirement:
  ``"Two years of prior experience"`` yields no duration fact at all.
- It never arbitrates a contradiction: both facts are returned and each one
  names the other in ``contradictions``.

TRUST RULES
- Offer text is untrusted data, never an instruction: no function here
  branches on the imperative content of an offer.
- Pure, deterministic, offline: no clock, no randomness, no network, no
  model.  The same text always yields the same facts, in the same order.
- Unknown stays unknown: a date that cannot be resolved to a calendar date
  is reported with ``precision="unknown"`` and never guessed.

SCHEMA (compact JSON of one fact)
::
  {
    "fact_type": "start",
    "value": {"day": null, "month": 1, "year": 2027},
    "precision": "month",
    "source_field": "description_original",
    "quote": "Starting January 2027",
    "start_offset": 312,
    "end_offset": 333,
    "confidence": "confirmed",
    "contradictions": [],
    "fact_id": "start@description_original:312",
    "lang": "en",
  }

VALUE SHAPES
- date facts (``published``, ``deadline``, ``start``, ``end``):
  ``{"day": int|None, "month": int|None, "year": int|None}``
- duration facts: ``{"months_min": int|None, "months_max": int|None}`` —
  always normalised to months, never guessed.  ``duration_exact`` gives
  ``(N, N)``, ``duration_min`` gives ``(N, None)``, ``duration_max`` gives
  ``(None, N)`` and ``duration_range`` gives the two bounds of the interval.
  The ``precision`` of a duration reports the unit of the value (``month``).

PRECISION AND CONFIDENCE
- ``precision`` is the finest component the text names explicitly:
  ``day`` (a day is written), ``month`` (only a month is written), ``year``
  (only a year is written), ``unknown`` (nothing is resolvable).
- A missing year does not change the precision but lowers the confidence to
  ``inferred``: ``"Starting January"`` -> month 1, year ``None``, ``inferred``.
- ``confidence`` is ``confirmed`` when the value is explicit, ``inferred``
  when a part is missing, ``ambiguous`` when the text admits several
  readings.  An inversable numeric date (``01/02/2025``) commits to
  nothing: its day and month stay ``None``, its precision is ``unknown`` and
  both possible readings are listed in ``contradictions``.

CONTRADICTIONS
``contradictions`` lists the ``fact_id`` of the other facts that cannot be
true at the same time as this one.  Both sides are listed, so the consumer
never has to guess which one won.  An ambiguous date also lists its possible
readings as ``"ambiguous_reading:YYYY-MM-DD"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

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

FACT_TYPES: tuple[str, ...] = (
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

SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "en", "de", "it", "es")

MAX_TEXT_CHARS = 60_000
MAX_FACTS = 200
MAX_DURATION_MONTHS = 60
MAX_DURATION_YEARS = 5

# How far before a date expression a context marker may stand, and how far
# after the marker the date may be.
_CONTEXT_WINDOW = 120
_MAX_CONTEXT_GAP = 45
_LEFT_WINDOW = 70
_RIGHT_WINDOW = 45

# Tie-break order when two markers are equally close to the date.
_PRIORITY: dict[str, int] = {"deadline": 0, "published": 1, "start": 2, "end": 3}

_SENTENCE_BREAK = re.compile(r"[.!?]\s|\n\s*\n|;[\s]")


# --------------------------------------------------------------------- data

_MONTHS: dict[str, dict[str, int]] = {
    "en": {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    },
    "fr": {
        "janvier": 1, "janv": 1, "février": 2, "fevrier": 2, "févr": 2, "fevr": 2,
        "mars": 3, "avril": 4, "avr": 4, "mai": 5, "juin": 6, "juillet": 7,
        "juil": 7, "juill": 7, "août": 8, "aout": 8, "septembre": 9, "sept": 9,
        "sep": 9, "octobre": 10, "oct": 10, "novembre": 11, "nov": 11,
        "décembre": 12, "decembre": 12, "déc": 12, "dec": 12,
    },
    "de": {
        "januar": 1, "jan": 1, "februar": 2, "feb": 2, "märz": 3, "marz": 3,
        "mär": 3, "mar": 3, "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6,
        "juli": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9,
        "oktober": 10, "okt": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12,
    },
    "it": {
        "gennaio": 1, "gen": 1, "febbraio": 2, "feb": 2, "marzo": 3, "mar": 3,
        "aprile": 4, "apr": 4, "maggio": 5, "mag": 5, "giugno": 6, "giu": 6,
        "luglio": 7, "lug": 7, "agosto": 8, "ago": 8, "settembre": 9, "set": 9,
        "ottobre": 10, "ott": 10, "novembre": 11, "nov": 11, "dicembre": 12, "dic": 12,
    },
    "es": {
        "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
        "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
        "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9,
        "setiembre": 9, "sept": 9, "sep": 9, "octubre": 10, "oct": 10,
        "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12,
    },
}

_NUMBERS: dict[str, dict[str, int]] = {
    "en": {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "eighteen": 18,
    },
    "fr": {
        "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
        "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11,
        "douze": 12, "dix-huit": 18,
    },
    "de": {
        "eins": 1, "ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4,
        "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
        "elf": 11, "zwölf": 12, "achtzehn": 18,
    },
    "it": {
        "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
        "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11,
        "dodici": 12, "diciotto": 18,
    },
    "es": {
        "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
        "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
        "doce": 12, "dieciocho": 18,
    },
}

# Duration units. Only months and years are supported: a week cannot be
# converted to a month without inventing a ratio, so it is simply not read.
_UNIT_PATTERNS: dict[str, str] = {
    "en": r"months?|mo\b|years?|yrs?\b",
    "fr": r"mois|ann[ée]es?|ans\b",
    "de": r"monat\w*|jahr\w*",
    "it": r"mesi\b|mes(?:e)?\b|ann[io]\b",
    "es": r"meses|mes\b|a[ñn]os?\b",
}

_YEAR_UNITS: dict[str, frozenset[str]] = {
    "en": frozenset({"year", "years", "yr", "yrs"}),
    "fr": frozenset({"an", "ans", "année", "années", "annee", "annees"}),
    "de": frozenset({"jahr", "jahre", "jahren", "jahrs"}),
    "it": frozenset({"anno", "anni"}),
    "es": frozenset({"año", "años", "ano", "anos"}),
}

# Connector between the two bounds of a range ("3 to 6 months").
_RANGE_CONNECTORS: dict[str, str] = {
    "en": r"to|through|and|-|–|—",
    "fr": r"[àa]|et|-|–|—",
    "de": r"bis|und|-|–|—",
    "it": r"a|e|-|–|—",
    "es": r"a|y|-|–|—",
}

# Connector between two month names ("January to June 2027").
_MONTH_RANGE_CONNECTORS: dict[str, str] = {
    "en": r"to|through|until|-|–|—",
    "fr": r"[àa]|jusqu['’]au|au|-|–|—",
    "de": r"bis|bis zu|-|–|—",
    "it": r"a|fino al|fino a|-|–|—",
    "es": r"a|hasta|-|–|—",
}

# Separator between the day and the month name.
_DAY_TO_MONTH: dict[str, str] = {
    "en": r"(?:\s+of\s+|\s+)",
    "fr": r"(?:\s+de\s+|\s+)",
    "de": r"(?:\s*\.\s*|\s+)",
    "it": r"(?:\s+di\s+|\s+)",
    "es": r"(?:\s+de\s+|\s+)",
}

# Separator between the month name and the year. It is only used when a
# year actually follows, so it may be absent.
_MONTH_TO_YEAR: dict[str, str] = {
    "en": r"(?:\s*,\s*|\s+)",
    "fr": r"(?:\s*,\s*|\s+)",
    "de": r"(?:\s*,\s*|\s+)",
    "it": r"(?:\s*,\s*|\s+)",
    "es": r"(?:\s+de\s+|\s*,\s*|\s+)",
}

_DAY_ORDINAL = r"(?:\s*(?:er|ère|º|ª|st|nd|rd|th))?"

_CONTEXT_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "published": (
            r"\bdate of publication\b", r"\bdate posted\b", r"\bposted date\b",
            r"\bposted(?:\s+on)?\b", r"\bpublished(?:\s+on)?\b",
            r"\badvertised(?:\s+on)?\b", r"\blisted(?:\s+on)?\b",
            r"\bavailable since\b", r"\breleased on\b",
        ),
        "deadline": (
            r"\bapplication deadline\b", r"\blast (?:day|date) (?:to apply|for applications)\b",
            r"\bsubmit (?:your )?applications? (?:by|before)\b",
            r"\bapply\s+(?:by|before|until|no later than)\b",
            r"\bapplications?\b[^.\n]{0,30}?\b(?:close|closes|closed|until|by|before|deadline)\b",
            r"\bclosing date\b", r"\bregister by\b", r"\brespond by\b", r"\bdeadline\b",
        ),
        "start": (
            r"\bposition\s+(?:will\s+)?starts?\b", r"\bstart(?:s|ing)?\s+(?:date|on|from|in)\b",
            r"\bstart date\b", r"\bstarting date\b", r"\bstart(?:s|ing)?\s+as\b",
            r"\bstarting(?!\s+(?:salary|price|rate|from home|at home))\b",
            r"\bbegins?\s+(?:on|from|in|as)\b", r"\bbeginning\b", r"\bstarts\b", r"\bbegins\b",
            r"\bcommences?\s+(?:on|from|in|as)\b", r"\bavailable from\b", r"\bfrom\b",
        ),
        "end": (
            r"\bend of (?:the )?(?:contract|internship|placement|period|assignment|programme|program)\b",
            r"\bcontract ends?\b", r"\bending (?:on|of)\b", r"\bends?\s+(?:on|by)\b",
            r"\bend date\b", r"\buntil the end of\b",
        ),
    },
    "fr": {
        "published": (
            r"\bdate de publication\b", r"\bmis en ligne le\b",
            r"\bpubli(?:e|é|ée|es|ées)\s+le\b",
            r"\bpublication\b", r"\bpost(?:e|é|ée|ées?)\s+le\b",
            r"\bannonc(?:e|é|ée|ées?)\s+le\b",
        ),
        "deadline": (
            r"\bdate limite de candidature\b", r"\bdate limite\b", r"\bdate butoir\b",
            r"\bcl[ôo]ture des candidatures\b",
            r"\bcandidat(?:e|es|ures)?\b[^.\n]{0,30}?\b(?:jusqu['’]au|avant (?:le|l['’])|date limite)\b",
            r"\bpostul(?:ez|er|ation)\s+(?:avant|jusqu['’])\b",
            r"\benvoyez?\s+(?:votre\s+)?(?:candidature|lettre)\s+avant\b",
            r"\bcl[ôo]ture\b",
        ),
        "start": (
            r"\bprise de (?:poste|fonction)\b", r"\b[àa] compter du\b",
            r"\b[àa] partir du\b", r"\bposte [àa] pourvoir\b", r"\bpr[ée]vu (?:pour|le|à)\b",
            r"\bdisponible (?:le|[àa] partir|au)\b", r"\bd[ée]but\b", r"\bcommence(?:nt)?\b",
            r"\bd[ée]marre\b",
        ),
        "end": (
            r"\bfin (?:de|du|des|de la|de l['’]) (?:contrat|stage|mission)\b",
            r"\bdate de fin\b",
            r"\bse (?:termine|ach[èe]ve) le\b", r"\btermine le\b", r"\bjusqu['’]au\b",
            r"\bfin\s+le\b",
        ),
    },
    "de": {
        "published": (
            r"\bdatum der ver[öo]ffentlichung\b", r"\bver[öo]ffentlichungsdatum\b",
            r"\bver[öo]ffentlicht(?:\s+am)?\b", r"\bausgeschrieben(?:\s+am)?\b",
            r"\bgeschrieben am\b",
        ),
        "deadline": (
            r"\bbewerbungsfrist\b", r"\bbewerbung(?:en)?\s+bis\b", r"\beinreichung bis\b",
            r"\bbewerbbar bis\b", r"\bantrag bis\b", r"\bfrist\b",
        ),
        "start": (
            r"\bstartdatum\b", r"\bstart(?:et|en)?\s+(?:am|ab|in)\b", r"\bab dem\b",
            r"\beintritt\b", r"\bwir starten\b", r"\bbeginn(?:end|t|nt|e|es)?\b",
            r"\bverf[üu]gbar ab\b",
        ),
        "end": (
            r"\bvertragsende\b", r"\bendet am\b", r"\bende am\b", r"\bl[äa]uft ab\b",
            r"\bbis zum\b", r"\bende\b",
        ),
    },
    "it": {
        "published": (
            r"\bdata di pubblicazione\b", r"\bpubblicat(?:o|a|to|i|he)\b",
            r"\bpubblicazione\b", r"\binserito il\b",
        ),
        "deadline": (
            r"\bscadenza(?: per le candidature)?\b", r"\bscadenza entro\b",
            r"\bcandidate?\s+entro\b", r"\btermine (?:entro|per)\b", r"\binvio entro\b",
            r"\bentro (?:il|le)\b",
        ),
        "start": (
            r"\bdata di inizio\b", r"\ba partire dal\b", r"\binizio attivit[àa]\b",
            r"\bcomm[ée]incia (?:il|dal)\b", r"\binizio\b", r"\binizia\b", r"\bdal\b",
        ),
        "end": (
            r"\bdata di fine\b", r"\bfine del\b", r"\bfine di\b", r"\btermine (?:il|del)\b",
            r"\bfino al\b", r"\bfine\b",
        ),
    },
    "es": {
        "published": (
            r"\bfecha de publicaci[óo]n\b", r"\bfecha de alta\b",
            r"\bpublicaci[óo]n\b", r"\bpublicad[oa]\b", r"\binsertado el\b",
        ),
        "deadline": (
            r"\bfecha l[íi]mite\b", r"\bplazo de (?:solicitud|presentaci[óo]n)\b",
            r"\bpostular hasta\b", r"\bpostulaci[óo]n hasta\b",
            r"\bpresente su (?:solicitud|candidatura) antes del\b",
            r"\bsolicitudes?\b[^.\n]{0,30}?\b(?:hasta|antes del)\b",
        ),
        "start": (
            r"\bfecha de inicio\b", r"\ba partir de\b", r"\bdisponible (?:el|a partir|desde)\b",
            r"\bdesde el\b", r"\binicio\b", r"\bcomienzo\b", r"\bempieza\b",
        ),
        "end": (
            r"\bfecha de fin\b", r"\bfin de (?:contrato|pr[áa]ctica)\b", r"\btermina el\b",
            r"\bhasta el\b", r"\bfin\b",
        ),
    },
}

# Words that mean "this number is not about the contract".
_EXPERIENCE_LEFT: dict[str, str] = {
    "en": r"\b(?:experience|experiences|work history|background|track record)\b[^.\n]{0,15}$",
    "fr": r"\b(?:exp[ée]rience|exp[ée]riences|anciennet[ée]|parcours)\b[^.\n]{0,15}$",
    "de": r"\b(?:Erfahrung|Erfahrungen|Berufserfahrung)\b[^.\n]{0,15}$",
    "it": r"\b(?:esperienza|esperienze|curriculum)\b[^.\n]{0,15}$",
    "es": r"\b(?:experiencia|experiencias|trayectoria)\b[^.\n]{0,15}$",
}

_EXPERIENCE_RIGHT: dict[str, str] = {
    "en": r"^\s*(?:of\s+)?(?:prior\s+|previous\s+|preceding\s+|relevant\s+|professional\s+|work\s+)?(?:experience|experiences)\b",
    "fr": r"^\s*(?:de\s+)?(?:pr[ée]c[ée]dente|ant[ée]rieure|enrichie\s+)?(?:exp[ée]rience|exp[ée]riences)\b",
    "de": r"^\s*(?:in\s+)?(?:der\s+)?(?:Erfahrung|Erfahrungen)\b",
    "it": r"^\s*(?:di\s+)?(?:precedente|pregressiva)?\s*(?:esperienza|esperienze)\b",
    "es": r"^\s*(?:de\s+)?(?:previa|anterior|relacionada\s+)?(?:experiencia|experiencias)\b",
}

# Words that mean "this number is relative to today", not a contract length.
_RELATIVE_LEFT: dict[str, str] = {
    "en": r"\b(?:within|in|after|since|from|over|under|for the last|over the last)\s+$",
    "fr": r"\b(?:dans|sous|dans les|dans l['’]|en moins de|au bout de|au cours des?|apr[èe]s)\s+$",
    "de": r"\b(?:in|nach|innerhalb|innerhalb von|vor|seit)\s+$",
    "it": r"\b(?:entro|entro a|entro da|dopo|tra|fra)\s+$",
    "es": r"\b(?:en|dentro de|dentro|tras)\s+$",
}

_RELATIVE_RIGHT: dict[str, str] = {
    "en": r"^\s*(?:ago|later|earlier|previously|before|from now)\b",
    "fr": r"^\s*(?:plus tard|avant|pr[ée]c[ée]demment|ensuite)\b",
    "de": r"^\s*(?:her|sp[äa]ter|zuvor|vorher)\b",
    "it": r"^\s*(?:fa|pi[ùu] tardi|prima)\b",
    "es": r"^\s*(?:atr[áa]s|hace|despu[ée]s|m[áa]s tarde)\b",
}

# Words that make a number a contract duration.
_DURATION_LEFT: dict[str, str] = {
    "en": (
        r"\b(?:duration|length|lasting|lasts?|contracts?|internships?|stages?|placements?|"
        r"assignments?|employment|engagement|programmes?|programs?|period|term|between|for)\b"
        r"(?:\s+(?:of|de|di|del|d['’]|von|para|per))?\s*[:\-–]?\s*$"
    ),
    "fr": (
        r"\b(?:dur[ée]e|longueur|dure|contrats?|stages?|periodes?|p[ée]riodes?|engagement|"
        r"programme|formation|entre|pour)\b(?:\s+(?:de|de d['’]|di|del|d['’]|von|para|per))?\s*[:\-–]?\s*$"
    ),
    "de": (
        r"\b(?:dauer|l[äa]nge|dauert|vertr[äa]ge|praktikum|stage|stellen|zeitraum|"
        r"anstellung|beschaeftigung|programm|zwischen|f[üu]r|einen|einem)\b"
        r"(?:\s+(?:von|of|de|di|del|d['’]))?\s*[:\-–]?\s*$"
    ),
    "it": (
        r"\b(?:durata|contratti?|stage|tirocini|period[oi]|periodi|assunzione|"
        r"programma|tra|per|un|una)\b(?:\s+(?:di|da|in|a|tra))?\s*[:\-–]?\s*$"
    ),
    "es": (
        r"\b(?:duraci[óo]n|contratos?|stage|pasant[íi]as?|becas?|periodo|per[íi]odo|"
        r"programa|empleo|entre|para|un|una)\b(?:\s+(?:de|del|di|in|para|entre))?\s*[:\-–]?\s*$"
    ),
}

_DURATION_RIGHT: dict[str, str] = {
    "en": (
        r"^\s*[-–]?\s*(?:internships?|stages?|contracts?|programmes?|programs?|employment|"
        r"engagement|traineeship|placement|full[- ]time|part[- ]time)\b"
    ),
    "fr": (
        r"^\s*[-–]?\s*(?:stages?|alternances?|contrats?|programmes?|formations?|emploi|"
        r"alternance|plein temps|temps plein)\b"
    ),
    "de": (
        r"^\s*[-–]?\s*(?:praktikum|stellen?vertrag|vertr[äa]ge|vertrag|anstellung|programm|"
        r"vollzeit|teilzeit|aushilfe)\b"
    ),
    "it": (
        r"^\s*[-–]?\s*(?:stage|tirocinio|contratti?|contratto|programma|assunzione|"
        r"tempo pieno|tempo parziale)\b"
    ),
    "es": (
        r"^\s*[-–]?\s*(?:stage|pasant[íi]a|becas?|contratos?|contrato|programa|empleo|"
        r"jornada completa|tiempo completo)\b"
    ),
}

_DURATION_MIN: dict[str, str] = {
    "en": r"\b(?:at least|a minimum of|minimum of|min\.?)\s*$",
    "fr": r"\b(?:au moins|un minimum de|minimum de|[àa] partir de)\s*$",
    "de": r"\b(?:mindestens|mindestens|minimal|minimale?n?|zum mindesten)\s*$",
    "it": r"\b(?:almeno|minimo di|minimo)\s*$",
    "es": r"\b(?:al menos|m[íi]nimo de|m[íi]nimo)\s*$",
}

_DURATION_MAX: dict[str, str] = {
    "en": r"\b(?:up to|a maximum of|maximum of|max\.?)\s*$",
    "fr": r"\b(?:jusqu['’][àa]|maximum de|au maximum)\s*$",
    "de": r"\b(?:h[öo]chstens|maximal|maximum|sp[äa]testens|bis zu)\s*$",
    "it": r"\b(?:fino a|massimo|fino)\s*$",
    "es": r"\b(?:hasta|m[áa]ximo|m[áa]ximo de)\s*$",
}

# Preposition that introduces a range ("de 3 à 6 mois"): it belongs to the
# quoted duration.
_RANGE_PREFIX: dict[str, str] = {
    "en": r"\b(?:from|of|between)\s+$",
    "fr": r"\b(?:de|d['’]|du|entre)\s+$",
    "de": r"\b(?:von|zwischen)\s+$",
    "it": r"\b(?:da|di|tra)\s+$",
    "es": r"\b(?:de|del|entre)\s+$",
}

# A start that talks about the applications, not about the job.
_APPLICATION_WORDS = re.compile(
    r"\b(?:applications?|candidat(?:e|es|ures)?|candidaturas|candidatur\w*|solicitudes?|"
    r"solicitud|anmeldung(?:en)?|bewerbung(?:en)?|inscrizion\w*|inscriptions?)\b",
    re.IGNORECASE,
)

# Words that may sit between the application word and the marker.
_APPLICATION_GLUE = re.compile(
    r"^\s*(?:(?:open|opens|close|closes|closed|start|starts|starting|begin|begins|beginnt|"
    r"ouverte?s?|abiertas?|abierto?s?|aperta|abrennen|chiude|schliessen|öffnen|apertura|"
    r"inizio|empiezo|comienza|ge[öo]ffnet|aperte?|sono|sont|sind|ist|are|est[áa]n|"
    r"son|están|estan)\s*)*$",
    re.IGNORECASE,
)

# Expressions that announce a date without giving one ("Starting ASAP").
# They are read as facts with ``precision="unknown"``: the moment is
# certain, the calendar date is not.
_NO_CALENDAR_DATE: dict[str, tuple[str, ...]] = {
    "en": (
        "as soon as possible", "immediately", "shortly", "asap", "soon",
    ),
    "fr": (
        "dès que possible", "des que possible", "immédiatement", "rapidement",
        "sous peu", "dès demain",
    ),
    "de": (
        "sobald wie möglich", "möglichst bald", "zum nächstmöglichen Zeitpunkt",
        "sofort", "umgehend", "baldigst",
    ),
    "it": ("al più presto", "immediatamente", "presto", "tempestivamente"),
    "es": ("cuanto antes", "lo antes posible", "inmediatamente", "pronto"),
}

_LANG_HINTS: dict[str, tuple[str, ...]] = {
    "en": (
        "the", "and", "for", "with", "job", "internship", "position", "apply",
        "duration", "months", "your", "we", "contract", "deadline", "starting",
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december",
    ),
    "fr": (
        "les", "des", "une", "pour", "poste", "candidature", "stage", "durée",
        "mois", "offre", "votre", "notre", "début", "cv", "janvier", "février",
        "mars", "avril", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre",
    ),
    "de": (
        "der", "die", "das", "und", "für", "stelle", "praktikum", "bewerbung",
        "monate", "dauer", "ihr", "beginn", "bewerbungsfrist", "januar",
        "februar", "märz", "april", "juni", "juli", "oktober", "dezember",
    ),
    "it": (
        "della", "delle", "per", "con", "posizione", "tirocinio", "offerta",
        "mesi", "durata", "nel", "candidatura", "inizio", "gennaio", "febbraio",
        "aprile", "giugno", "luglio", "settembre", "dicembre",
    ),
    "es": (
        "los", "las", "para", "con", "puesto", "práctica", "oferta",
        "solicitud", "meses", "duración", "del", "fecha", "cv", "enero",
        "febrero", "abril", "junio", "julio", "septiembre", "diciembre",
    ),
}

_LANG_ALIASES: dict[str, str] = {
    "fr": "fr", "french": "fr", "francais": "fr", "français": "fr", "fra": "fr",
    "en": "en", "english": "en", "eng": "en",
    "de": "de", "german": "de", "deutsch": "de", "ger": "de",
    "it": "it", "italian": "it", "italiano": "it", "ita": "it",
    "es": "es", "spanish": "es", "espanol": "es", "español": "es", "spa": "es",
    "auto": "auto", "": "auto", "any": "auto", "xx": "auto",
}


# ------------------------------------------------------------------- models


@dataclass(frozen=True)
class DateFact:
    """One dated fact, with the exact proof it was read from."""

    fact_type: FactType
    value: dict[str, Any]
    precision: Precision
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Confidence
    contradictions: list[str] = field(default_factory=list)
    fact_id: str = ""
    lang: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_type": self.fact_type,
            "value": dict(self.value),
            "precision": self.precision,
            "source_field": self.source_field,
            "quote": self.quote,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "confidence": self.confidence,
            "contradictions": list(self.contradictions),
            "fact_id": self.fact_id,
            "lang": self.lang,
        }


@dataclass(frozen=True)
class _Candidate:
    """A date expression found in the text, before it is classified."""

    start: int
    end: int
    day: Optional[int]
    month: Optional[int]
    year: Optional[int]
    kind: str  # "named" | "numeric" | "year"
    alternative: Optional[str] = None


@dataclass(frozen=True)
class _Vocab:
    """Compiled vocabulary of one language."""

    code: str
    months: dict[str, int]
    numbers: dict[str, int]
    month_alt: str
    number_alt: str
    unit_alt: str
    contexts: dict[str, re.Pattern[str]]
    date_pattern: re.Pattern[str]
    numeric_pattern: re.Pattern[str]
    year_pattern: re.Pattern[str]
    duration_pattern: re.Pattern[str]
    range_pattern: re.Pattern[str]
    month_range_pattern: re.Pattern[str]
    experience_left: re.Pattern[str]
    experience_right: re.Pattern[str]
    relative_left: re.Pattern[str]
    relative_right: re.Pattern[str]
    duration_left: re.Pattern[str]
    duration_right: re.Pattern[str]
    duration_min: re.Pattern[str]
    duration_max: re.Pattern[str]
    range_prefix: re.Pattern[str]
    no_calendar_date: re.Pattern[str]
    blocker: re.Pattern[str]


# ------------------------------------------------------------------ helpers


def _alternation(tokens: Any) -> str:
    """Regex alternation of the tokens, longest first so the longest wins."""
    return "|".join(re.escape(token) for token in sorted(tokens, key=len, reverse=True))


def _compile_contexts(code: str) -> dict[str, re.Pattern[str]]:
    compiled: dict[str, re.Pattern[str]] = {}
    for fact_type, phrases in _CONTEXT_PHRASES[code].items():
        ordered = sorted(phrases, key=len, reverse=True)
        compiled[fact_type] = re.compile("|".join(ordered), re.IGNORECASE)
    return compiled


def _build_vocab(code: str) -> _Vocab:
    months = _MONTHS[code]
    numbers = _NUMBERS[code]
    month_alt = _alternation(months)
    number_alt = _alternation(numbers)
    unit_alt = _UNIT_PATTERNS[code]
    day_to_month = _DAY_TO_MONTH[code]
    month_to_year = _MONTH_TO_YEAR[code]
    connector = _RANGE_CONNECTORS[code]
    month_connector = _MONTH_RANGE_CONNECTORS[code]

    date_pattern = re.compile(
        rf"(?P<d1>\d{{1,2}}){_DAY_ORDINAL}\b{day_to_month}(?P<m1>{month_alt})\b"
        rf"(?:{month_to_year}(?P<y1>(?:19|20)\d{{2}}))?"
        rf"|(?P<m2>{month_alt})\b\s+(?P<d2>\d{{1,2}}){_DAY_ORDINAL}\b(?:\s*,)?"
        rf"(?:{month_to_year}(?P<y2>(?:19|20)\d{{2}}))?"
        rf"|(?P<m3>{month_alt})\b"
        rf"(?:{month_to_year}(?P<y3>(?:19|20)\d{{2}}))?",
        re.IGNORECASE,
    )
    numeric_pattern = re.compile(
        r"(?P<iy>(?:19|20)\d{2})-(?P<im>\d{1,2})-(?P<id>\d{1,2})(?!\d)"
        r"|(?P<na>\d{1,2})(?P<nsep>[/.\-])(?P<nb>\d{1,2})"
        r"(?:(?P=nsep)(?P<nc>\d{2,4}))?(?!\d)"
        r"|(?P<mm>\d{1,2})[/.\-](?P<myy>(?:19|20)\d{2})(?!\d)"
    )
    year_pattern = re.compile(r"(?P<oy>(?:19|20)\d{2})(?!\d)")
    number_token = rf"(?:\d{{1,3}}|{number_alt})"
    duration_pattern = re.compile(
        rf"(?P<num>{number_token})\s*(?:[-–—]\s*)?(?P<unit>{unit_alt})\b",
        re.IGNORECASE,
    )
    range_pattern = re.compile(
        rf"(?P<lo>{number_token})\s*(?:{connector})\s*(?P<hi>{number_token})"
        rf"\s*(?:[-–—]\s*)?(?P<unit>{unit_alt})\b",
        re.IGNORECASE,
    )
    month_range_pattern = re.compile(
        rf"(?P<m1>{month_alt})\b\s*(?:{month_connector})\s*(?P<m2>{month_alt})\b"
        rf"(?:\s*(?:de\s+)?(?P<y>(?:19|20)\d{{2}}))?",
        re.IGNORECASE,
    )
    blockers = {
        "en": r"\b(?:experience|experiences|ago|within|earlier|prior|previous|preceding)\b",
        "fr": r"\b(?:exp[ée]rience|exp[ée]riences|il y a|depuis|au cours des?|dans les)\b",
        "de": r"\b(?:Erfahrung|Erfahrungen|vor|nach)\b",
        "it": r"\b(?:esperienza|esperienze|fa|entro)\b",
        "es": r"\b(?:experiencia|hace|dentro de|dentro)\b",
    }
    return _Vocab(
        code=code,
        months=months,
        numbers=numbers,
        month_alt=month_alt,
        number_alt=number_alt,
        unit_alt=unit_alt,
        contexts=_compile_contexts(code),
        date_pattern=date_pattern,
        numeric_pattern=numeric_pattern,
        year_pattern=year_pattern,
        duration_pattern=duration_pattern,
        range_pattern=range_pattern,
        month_range_pattern=month_range_pattern,
        experience_left=re.compile(_EXPERIENCE_LEFT[code], re.IGNORECASE),
        experience_right=re.compile(_EXPERIENCE_RIGHT[code], re.IGNORECASE),
        relative_left=re.compile(_RELATIVE_LEFT[code], re.IGNORECASE),
        relative_right=re.compile(_RELATIVE_RIGHT[code], re.IGNORECASE),
        duration_left=re.compile(_DURATION_LEFT[code], re.IGNORECASE),
        duration_right=re.compile(_DURATION_RIGHT[code], re.IGNORECASE),
        duration_min=re.compile(_DURATION_MIN[code], re.IGNORECASE),
        duration_max=re.compile(_DURATION_MAX[code], re.IGNORECASE),
        range_prefix=re.compile(_RANGE_PREFIX[code], re.IGNORECASE),
        no_calendar_date=re.compile(
            r"\b(?:" + "|".join(
                re.escape(phrase)
                for phrase in sorted(_NO_CALENDAR_DATE[code], key=len, reverse=True)
            ) + r")\b",
            re.IGNORECASE,
        ),
        blocker=re.compile(blockers[code], re.IGNORECASE),
    )


_VOCABS: dict[str, _Vocab] = {code: _build_vocab(code) for code in SUPPORTED_LANGUAGES}


def detect_language(text: str) -> str:
    """Guess the language of ``text`` from its most frequent markers.

    Deterministic and offline: the same text always gives the same answer.
    Falls back to ``"en"`` when nothing is conclusive.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    lowered = text.lower()
    tokens = set(re.findall(r"[\w'’\-]+", lowered))
    scores: dict[str, int] = {}
    for code, hints in _LANG_HINTS.items():
        scores[code] = sum(1 for hint in hints if _hint_matches(hint, tokens))
    best = max(scores.items(), key=lambda item: (item[1], -_LANG_TIE_ORDER.index(item[0])))
    if best[1] < 2:
        return "en"
    return best[0]


def _hint_matches(hint: str, tokens: set[str]) -> bool:
    """A hint matches a token exactly, or a longer form of it ("candidatures")."""
    if hint in tokens:
        return True
    if len(hint) < 5:
        return False
    return any(token.startswith(hint) for token in tokens)


_LANG_TIE_ORDER: list[str] = ["en", "fr", "de", "it", "es"]


def _resolve_lang(lang: str | None, text: str) -> str:
    """Return the language code to use for ``text``."""
    if lang is None:
        return detect_language(text)
    if not isinstance(lang, str):
        raise TypeError("lang must be a string")
    key = lang.strip().lower().replace("_", "-")
    if "-" in key:
        key = key.split("-", 1)[0]
    if key in _LANG_ALIASES:
        code = _LANG_ALIASES[key]
        return detect_language(text) if code == "auto" else code
    raise ValueError(f"unsupported language: {lang!r} (expected one of {', '.join(SUPPORTED_LANGUAGES)})")


# --------------------------------------------------------------- candidates


def _month_number(vocab: _Vocab, token: str) -> int | None:
    return vocab.months.get(token.lower())


def _named_candidates(text: str, vocab: _Vocab) -> list[_Candidate]:
    """Month-name date expressions (``15 January 2027``, ``January 2027``)."""
    out: list[_Candidate] = []
    for match in vocab.date_pattern.finditer(text):
        groups = match.groupdict()
        day = groups.get("d1") or groups.get("d2")
        month = groups.get("m1") or groups.get("m2") or groups.get("m3")
        year = groups.get("y1") or groups.get("y2") or groups.get("y3")
        month_number = _month_number(vocab, month) if month else None
        if month_number is None:
            continue
        day_number = int(day) if day else None
        if day_number is not None and not 1 <= day_number <= 31:
            continue
        out.append(
            _Candidate(
                start=match.start(),
                end=match.end(),
                day=day_number,
                month=month_number,
                year=int(year) if year else None,
                kind="named",
            )
        )
    return out


def _numeric_candidates(text: str, vocab: _Vocab) -> list[_Candidate]:
    """ISO and numeric date expressions (``2027-01-15``, ``15/11/2025``)."""
    out: list[_Candidate] = []
    for match in vocab.numeric_pattern.finditer(text):
        groups = match.groupdict()
        if groups.get("iy"):
            month = int(groups["im"])
            day = int(groups["id"])
            if not 1 <= month <= 12 or not 1 <= day <= 31:
                continue
            out.append(
                _Candidate(
                    start=match.start(),
                    end=match.end(),
                    day=day,
                    month=month,
                    year=int(groups["iy"]),
                    kind="numeric",
                )
            )
            continue
        if groups.get("na"):
            first = int(groups["na"])
            second = int(groups["nb"])
            raw_year = groups.get("nc")
            year = None
            if raw_year:
                year = int(raw_year)
                if len(raw_year) == 2:
                    year = 2000 + year
            if first > 12 and second > 12:
                continue
            if first > 12:
                day, month = first, second
                alternative = None
            elif second > 12:
                day, month = second, first
                alternative = None
            elif first == second:
                day, month = first, second
                alternative = None
            else:
                day, month = first, second
                # The other reading swaps the roles: month = first, day = second.
                alternative = (
                    f"{year:04d}-{first:02d}-{second:02d}" if year else None
                )
            if not 1 <= month <= 12 or not 1 <= day <= 31:
                continue
            out.append(
                _Candidate(
                    start=match.start(),
                    end=match.end(),
                    day=day,
                    month=month,
                    year=year,
                    kind="numeric",
                    alternative=alternative,
                )
            )
            continue
        if groups.get("mm"):
            month = int(groups["mm"])
            if not 1 <= month <= 12:
                continue
            out.append(
                _Candidate(
                    start=match.start(),
                    end=match.end(),
                    day=None,
                    month=month,
                    year=int(groups["myy"]),
                    kind="numeric",
                )
            )
    return out


def _year_candidates(text: str, vocab: _Vocab, taken: list[tuple[int, int]]) -> list[_Candidate]:
    """Bare years (``in 2027``) that no longer date expression already covers."""
    out: list[_Candidate] = []
    for match in vocab.year_pattern.finditer(text):
        start, end = match.span()
        if any(start < taken_end and taken_start < end for taken_start, taken_end in taken):
            continue
        out.append(
            _Candidate(
                start=start,
                end=end,
                day=None,
                month=None,
                year=int(match.group("oy")),
                kind="year",
            )
        )
    return out


def _merge_candidates(groups: list[list[_Candidate]]) -> list[_Candidate]:
    """Keep the longest candidate when two expressions overlap."""
    ordered = sorted(
        (candidate for group in groups for candidate in group),
        key=lambda candidate: (candidate.start, -(candidate.end - candidate.start)),
    )
    kept: list[_Candidate] = []
    for candidate in ordered:
        if any(
            candidate.start < other.end and other.start < candidate.end
            for other in kept
        ):
            continue
        kept.append(candidate)
    kept.sort(key=lambda candidate: candidate.start)
    return kept


# ----------------------------------------------------------------- contexts


def _nearest_context(text: str, position: int, vocab: _Vocab) -> tuple[int, int, str] | None:
    """Closest context marker before ``position``.

    Returns the absolute ``(start, end, fact_type)`` of the marker.
    """
    window_start = max(0, position - _CONTEXT_WINDOW)
    window = text[window_start:position]
    best: tuple[tuple[int, int, int], int, int, str] | None = None
    for fact_type, pattern in vocab.contexts.items():
        for match in pattern.finditer(window):
            gap = position - (window_start + match.end())
            if gap > _MAX_CONTEXT_GAP:
                continue
            between = window[match.end():]
            if _SENTENCE_BREAK.search(between):
                continue
            if vocab.blocker.search(between):
                continue
            key = (gap, -(match.end() - match.start()), _PRIORITY[fact_type])
            if best is None or key < best[0]:
                best = (key, window_start + match.start(), window_start + match.end(), fact_type)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _is_application_start(text: str, marker_start: int) -> bool:
    """True when the marker opens the applications, not the job.

    ``"Applications open from 1 March 2027"`` says when the *candidates*
    may apply; the job start is a different fact.  The guard only fires
    when the application word is directly tied to the marker, so a normal
    sentence (``"The application team starts on 1 March"``) is not blocked.
    """
    left = text[max(0, marker_start - 60):marker_start]
    found = None
    for match in _APPLICATION_WORDS.finditer(left):
        found = match
    if found is None:
        return False
    glue = left[found.end():]
    return bool(_APPLICATION_GLUE.match(glue))


# ------------------------------------------------------------------- values


def _date_value(candidate: _Candidate) -> tuple[dict[str, Any], str, str, list[str]]:
    """Build the value, the precision and the confidence of a date candidate.

    ``precision`` is the finest component the text names explicitly.  A
    missing year does not change the precision but lowers the confidence to
    ``inferred`` (``value["year"]`` stays ``None``).

    An inversable numeric date (``01/02/2025``) commits to nothing: the day
    and the month stay ``None``, the precision is ``unknown`` and the two
    possible readings are listed in ``contradictions``.
    """
    if candidate.alternative:
        value = {"day": None, "month": None, "year": candidate.year}
        readings = {candidate.alternative}
        if candidate.year is not None:
            readings.add(f"{candidate.year:04d}-{candidate.month:02d}-{candidate.day:02d}")
        contradictions = [f"ambiguous_reading:{reading}" for reading in sorted(readings)]
        return value, "unknown", "ambiguous", contradictions

    value = {
        "day": candidate.day,
        "month": candidate.month,
        "year": candidate.year,
    }
    if candidate.day is not None:
        precision = "day"
    elif candidate.month is not None:
        precision = "month"
    elif candidate.year is not None:
        precision = "year"
    else:
        precision = "unknown"
    confidence = "inferred" if candidate.year is None else "confirmed"
    return value, precision, confidence, []


def _duration_months(number: int, unit: str, vocab: _Vocab) -> int | None:
    """Normalise a duration to months, or ``None`` when it is implausible."""
    months = number * 12 if unit.lower() in _YEAR_UNITS[vocab.code] else number
    if not 1 <= months <= MAX_DURATION_MONTHS:
        return None
    if unit.lower() in _YEAR_UNITS[vocab.code] and not 1 <= number <= MAX_DURATION_YEARS:
        return None
    return months


def _duration_number(token: str, vocab: _Vocab) -> int | None:
    if token.isdigit():
        return int(token)
    return vocab.numbers.get(token.lower())


def _duration_kind(left_window: str, vocab: _Vocab) -> str | None:
    """``duration_min`` / ``duration_max`` / ``duration_exact`` from the wording."""
    if vocab.duration_min.search(left_window):
        return "duration_min"
    if vocab.duration_max.search(left_window):
        return "duration_max"
    return "duration_exact"


# ------------------------------------------------------------------ extract


def _extract_date_facts(
    text: str,
    vocab: _Vocab,
    source_field: str,
    skip_spans: list[tuple[int, int]] | None = None,
) -> list[DateFact]:
    candidates = _merge_candidates(
        [
            _named_candidates(text, vocab),
            _numeric_candidates(text, vocab),
        ]
    )
    taken = [(candidate.start, candidate.end) for candidate in candidates]
    candidates += _year_candidates(text, vocab, taken)
    candidates.sort(key=lambda candidate: candidate.start)

    facts: list[DateFact] = []
    for candidate in candidates:
        if skip_spans and any(
            candidate.start < span_end and span_start < candidate.end
            for span_start, span_end in skip_spans
        ):
            continue
        found = _nearest_context(text, candidate.start, vocab)
        if found is None:
            continue
        marker_start, _marker_end, fact_type = found
        if fact_type == "start" and _is_application_start(text, marker_start):
            continue
        value, precision, confidence, contradictions = _date_value(candidate)
        start_offset = marker_start
        end_offset = candidate.end
        facts.append(
            DateFact(
                fact_type=fact_type,
                value=value,
                precision=precision,
                source_field=source_field,
                quote=text[start_offset:end_offset],
                start_offset=start_offset,
                end_offset=end_offset,
                confidence=confidence,
                contradictions=contradictions,
                fact_id=f"{fact_type}@{source_field}:{start_offset}",
                lang=vocab.code,
            )
        )
    return facts


def _duration_is_usable(text: str, start: int, end: int, vocab: _Vocab, *, is_range: bool = False) -> bool:
    """False when the number is an experience, a relative delay or unqualified.

    A duration that carries its own bound wording ("up to six months",
    "at least six months") or its own interval ("three to six months") is
    explicit enough on its own: the bound *is* the contract length.
    Otherwise the number needs a nearby duration marker ("a six-month
    internship", "duration: 6 months").
    """
    left = text[max(0, start - _LEFT_WINDOW):start]
    right = text[end:end + _RIGHT_WINDOW]
    if vocab.experience_left.search(left) or vocab.experience_right.search(right):
        return False
    if vocab.relative_left.search(left) or vocab.relative_right.search(right):
        return False
    if vocab.duration_min.search(left) or vocab.duration_max.search(left):
        return True
    if is_range:
        return True
    if vocab.duration_left.search(left) or vocab.duration_right.search(right):
        return True
    return False


def _duration_anchor(text: str, start: int, vocab: _Vocab) -> int:
    """Where the quoted duration starts: its bound wording, or its marker."""
    window_start = max(0, start - _LEFT_WINDOW)
    left = text[window_start:start]
    for pattern in (vocab.duration_min, vocab.duration_max):
        match = pattern.search(left)
        if match is not None:
            return window_start + match.start()
    match = vocab.duration_left.search(left)
    if match is not None:
        return window_start + match.start()
    match = vocab.range_prefix.search(left)
    if match is not None:
        return window_start + match.start()
    return start


def _extract_duration_facts(text: str, vocab: _Vocab, source_field: str) -> list[DateFact]:
    facts: list[DateFact] = []
    consumed: list[tuple[int, int]] = []

    for match in vocab.range_pattern.finditer(text):
        low = _duration_number(match.group("lo"), vocab)
        high = _duration_number(match.group("hi"), vocab)
        if low is None or high is None or low > high:
            continue
        months_low = _duration_months(low, match.group("unit"), vocab)
        months_high = _duration_months(high, match.group("unit"), vocab)
        if months_low is None or months_high is None:
            continue
        if not _duration_is_usable(text, match.start(), match.end(), vocab, is_range=True):
            continue
        consumed.append(match.span())
        anchor = _duration_anchor(text, match.start(), vocab)
        facts.append(
            DateFact(
                fact_type="duration_range",
                value={"months_min": months_low, "months_max": months_high},
                precision="month",
                source_field=source_field,
                quote=text[anchor:match.end()],
                start_offset=anchor,
                end_offset=match.end(),
                confidence="confirmed",
                contradictions=[],
                fact_id=f"duration_range@{source_field}:{anchor}",
                lang=vocab.code,
            )
        )

    for match in vocab.duration_pattern.finditer(text):
        start, end = match.span()
        if any(start < taken_end and taken_start < end for taken_start, taken_end in consumed):
            continue
        number = _duration_number(match.group("num"), vocab)
        if number is None:
            continue
        months = _duration_months(number, match.group("unit"), vocab)
        if months is None:
            continue
        if not _duration_is_usable(text, start, end, vocab):
            continue
        left = text[max(0, start - _LEFT_WINDOW):start]
        fact_type = _duration_kind(left, vocab)
        anchor = _duration_anchor(text, start, vocab)
        facts.append(
            DateFact(
                fact_type=fact_type,
                value=_duration_value(fact_type, months),
                precision="month",
                source_field=source_field,
                quote=text[anchor:end],
                start_offset=anchor,
                end_offset=end,
                confidence="confirmed",
                contradictions=[],
                fact_id=f"{fact_type}@{source_field}:{anchor}",
                lang=vocab.code,
            )
        )
    return facts


def _extract_unknown_date_facts(text: str, vocab: _Vocab, source_field: str) -> list[DateFact]:
    """``Starting ASAP`` -> a start whose calendar date is not known.

    The moment is explicit, the date is not: the fact keeps an empty value
    and ``precision="unknown"`` instead of guessing a day.
    """
    facts: list[DateFact] = []
    for match in vocab.no_calendar_date.finditer(text):
        found = _nearest_context(text, match.start(), vocab)
        if found is None:
            continue
        marker_start, _marker_end, fact_type = found
        if fact_type == "start" and _is_application_start(text, marker_start):
            continue
        start_offset = marker_start
        end_offset = match.end()
        facts.append(
            DateFact(
                fact_type=fact_type,
                value={"day": None, "month": None, "year": None},
                precision="unknown",
                source_field=source_field,
                quote=text[start_offset:end_offset],
                start_offset=start_offset,
                end_offset=end_offset,
                confidence="ambiguous",
                contradictions=[],
                fact_id=f"{fact_type}@{source_field}:{start_offset}",
                lang=vocab.code,
            )
        )
    return facts


def _extract_month_range_facts(text: str, vocab: _Vocab, source_field: str) -> list[DateFact]:
    """``January to June 2027`` -> one ``start`` fact and one ``end`` fact."""
    facts: list[DateFact] = []
    for match in vocab.month_range_pattern.finditer(text):
        first = _month_number(vocab, match.group("m1"))
        second = _month_number(vocab, match.group("m2"))
        if first is None or second is None or first == second:
            continue
        year = int(match.group("y")) if match.group("y") else None
        precision = "month" if year else "month"
        confidence = "confirmed" if year else "inferred"
        for fact_type, month in (("start", first), ("end", second)):
            facts.append(
                DateFact(
                    fact_type=fact_type,
                    value={"day": None, "month": month, "year": year},
                    precision=precision,
                    source_field=source_field,
                    quote=match.group(0),
                    start_offset=match.start(),
                    end_offset=match.end(),
                    confidence=confidence,
                    contradictions=[],
                    fact_id=f"{fact_type}@{source_field}:{match.start()}",
                    lang=vocab.code,
                )
            )
    return facts


# ------------------------------------------------------------ contradictions


def _date_conflict(left: DateFact, right: DateFact) -> bool:
    """True when two date facts cannot both be true."""
    if left.fact_type != right.fact_type:
        return False
    a, b = left.value, right.value
    if a.get("month") is not None and b.get("month") is not None and a["month"] != b["month"]:
        return True
    if a.get("year") is not None and b.get("year") is not None and a["year"] != b["year"]:
        return True
    if (
        a.get("day") is not None
        and b.get("day") is not None
        and a.get("year") is not None
        and b.get("year") is not None
        and a["year"] == b["year"]
        and a["day"] != b["day"]
    ):
        return True
    return False


def _duration_value(fact_type: str, months: int | None) -> dict[str, Any]:
    """Normalised value of a duration: bounds in months.

    ``duration_exact`` gives a closed bound, ``duration_min`` an open upper
    bound, ``duration_max`` an open lower bound and ``duration_range`` the
    two bounds of the interval.  The value is always expressed in months.
    """
    if fact_type == "duration_min":
        return {"months_min": months, "months_max": None}
    if fact_type == "duration_max":
        return {"months_min": None, "months_max": months}
    return {"months_min": months, "months_max": months}


def _duration_bounds(fact: DateFact) -> tuple[float, float]:
    value = fact.value
    low = value.get("months_min")
    high = value.get("months_max")
    return (
        float(low) if low is not None else float("-inf"),
        float(high) if high is not None else float("inf"),
    )


def _duration_conflict(left: DateFact, right: DateFact) -> bool:
    low_a, high_a = _duration_bounds(left)
    low_b, high_b = _duration_bounds(right)
    if high_a < low_b or high_b < low_a:
        return True
    return False


def _ordered_date(left: DateFact, right: DateFact) -> tuple[int, int, int] | None:
    """Comparable ``(year, month, day)`` when both facts are fully dated."""
    a, b = left.value, right.value
    if a.get("year") is None or b.get("year") is None:
        return None
    if a.get("month") is None or b.get("month") is None:
        return None
    if a.get("day") is None or b.get("day") is None:
        return None
    return int(a["year"]), int(a["month"]), int(a["day"])


def _link_contradictions(facts: list[DateFact]) -> None:
    """Fill the ``contradictions`` of every fact with the facts it clashes with."""
    for fact in facts:
        linked: list[str] = list(fact.contradictions)
        for other in facts:
            if other is fact:
                continue
            conflict = False
            if fact.fact_type in DATE_FACT_TYPES and other.fact_type in DATE_FACT_TYPES:
                if fact.fact_type == other.fact_type:
                    conflict = _date_conflict(fact, other)
                else:
                    conflict = _cross_date_conflict(fact, other)
            elif fact.fact_type in DURATION_FACT_TYPES and other.fact_type in DURATION_FACT_TYPES:
                conflict = _duration_conflict(fact, other)
            if conflict and other.fact_id not in linked:
                linked.append(other.fact_id)
        if linked != list(fact.contradictions):
            object.__setattr__(fact, "contradictions", linked)


def _cross_date_conflict(left: DateFact, right: DateFact) -> bool:
    """``start`` after ``end``, ``published`` after ``deadline``."""
    pair = {left.fact_type, right.fact_type}
    if pair == {"start", "end"}:
        ordered = _ordered_date(left, right)
        if ordered is None:
            return False
        start_fact = left if left.fact_type == "start" else right
        end_fact = left if left.fact_type == "end" else right
        start_value = start_fact.value
        end_value = end_fact.value
        return (end_value["year"], end_value["month"], end_value["day"]) < (
            start_value["year"],
            start_value["month"],
            start_value["day"],
        )
    if pair == {"published", "deadline"}:
        ordered = _ordered_date(left, right)
        if ordered is None:
            return False
        published = left if left.fact_type == "published" else right
        deadline = left if left.fact_type == "deadline" else right
        return (deadline.value["year"], deadline.value["month"], deadline.value["day"]) < (
            published.value["year"],
            published.value["month"],
            published.value["day"],
        )
    return False


# --------------------------------------------------------------------- API


def extract_dates(
    text: str,
    lang: str = "auto",
    source_field: str = "description_original",
) -> list[DateFact]:
    """Extract every dated fact of ``text``.

    ``lang`` is one of ``fr``, ``en``, ``de``, ``it``, ``es`` (or ``"auto"``
    to let the module guess it).  ``source_field`` is only recorded in the
    output: it names the offer field the text came from.

    The function is pure and deterministic: no clock, no network, no model.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(source_field, str):
        raise TypeError("source_field must be a string")
    if not text.strip():
        return []
    body = text[:MAX_TEXT_CHARS]
    code = _resolve_lang(lang, body)
    vocab = _VOCABS[code]

    facts: list[DateFact] = []
    month_range_facts = _extract_month_range_facts(body, vocab, source_field)
    range_spans = [(fact.start_offset, fact.end_offset) for fact in month_range_facts]
    facts.extend(_extract_date_facts(body, vocab, source_field, skip_spans=range_spans))
    facts.extend(_extract_unknown_date_facts(body, vocab, source_field))
    facts.extend(_extract_duration_facts(body, vocab, source_field))
    facts.extend(month_range_facts)

    facts = _dedupe(facts)
    facts.sort(key=lambda fact: (fact.start_offset, fact.end_offset, fact.fact_type))
    _link_contradictions(facts)
    return facts[:MAX_FACTS]


def _dedupe(facts: list[DateFact]) -> list[DateFact]:
    """Remove the facts that describe the very same thing twice."""
    seen: set[tuple[str, int, int, str]] = set()
    out: list[DateFact] = []
    for fact in facts:
        key = (fact.fact_type, fact.start_offset, fact.end_offset, fact.quote)
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    return out


def facts_by_type(facts: list[DateFact]) -> dict[str, list[DateFact]]:
    """Group the facts by type, keeping the original order."""
    grouped: dict[str, list[DateFact]] = {}
    for fact in facts:
        grouped.setdefault(fact.fact_type, []).append(fact)
    return grouped


_STRUCTURED_FIELDS: tuple[tuple[str, str], ...] = (
    ("posted_date", "published"),
    ("deadline_date", "deadline"),
    ("start_date", "start"),
    ("end_date", "end"),
)


def extract_offer_dates(offer: dict[str, Any], lang: str = "auto") -> list[DateFact]:
    """Extract the dated facts of a whole offer, across all its fields.

    Text fields (``title``, ``description_original``) are read with the
    temporal analyzer; the structured fields (``posted_date``,
    ``deadline_date``, ``start_date``, ``end_date``, ``duration_months``)
    are read as they are.  Facts from different fields that cannot both be
    true name each other in ``contradictions``.
    """
    if not isinstance(offer, dict):
        raise TypeError("offer must be an object")

    facts: list[DateFact] = []
    for source_field in ("title", "description_original"):
        value = offer.get(source_field)
        if not isinstance(value, str) or not value.strip():
            continue
        facts.extend(extract_dates(value, lang=lang, source_field=source_field))

    for source_field, fact_type in _STRUCTURED_FIELDS:
        value = offer.get(source_field)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = _numeric_candidates(value, _VOCABS["en"])
        if not candidate:
            continue
        item = candidate[0]
        parsed, precision, confidence, contradictions = _date_value(item)
        facts.append(
            DateFact(
                fact_type=fact_type,
                value=parsed,
                precision=precision,
                source_field=source_field,
                quote=value.strip(),
                start_offset=0,
                end_offset=len(value.strip()),
                confidence=confidence,
                contradictions=contradictions,
                fact_id=f"{fact_type}@{source_field}:0",
                lang="en",
            )
        )

    duration = offer.get("duration_months")
    if isinstance(duration, int) and not isinstance(duration, bool) and duration >= 1:
        facts.append(
            DateFact(
                fact_type="duration_exact",
                value=_duration_value("duration_exact", duration),
                precision="month",
                source_field="duration_months",
                quote=str(duration),
                start_offset=0,
                end_offset=len(str(duration)),
                confidence="confirmed",
                contradictions=[],
                fact_id="duration_exact@duration_months:0",
                lang="en",
            )
        )

    facts = _dedupe(facts)
    facts.sort(key=lambda fact: (fact.source_field, fact.start_offset, fact.end_offset, fact.fact_type))
    _link_contradictions(facts)
    return facts[:MAX_FACTS]
