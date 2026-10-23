"""Extraction multilingue et déterministe du niveau d'études exigé par une offre.

Pur Python, local, sans réseau, sans modèle, sans horloge : analyser deux fois
le même texte produit des faits identiques à l'octet près, chacun portant une
citation exacte et des offsets dans la source (``text[start_offset:end_offset] == quote``).

Règles de lecture (contrat SK-19, arbitrage explicite — jamais silencieux) :

- Une préférence (« PhD preferred », « Doctorat préféré ») n'est jamais
  promue en exigence : elle reste ``confidence="inferred"``.
- Deux niveaux reliés par une alternative (« Bac+3 ou Bac+5 », « Diplôme
  d'ingénieur ou Master 2 ») décrivent **une** exigence satisfaisable dans
  les deux cas : le niveau cité en premier devient le fait, l'alternative
  reste visible dans ``contradictions``.
- Deux niveaux contradictoires dans des clauses distinctes (« Bac+3
  minimum, Master apprécié ») produisent **deux** faits qui se citent
  mutuellement dans ``contradictions`` (plafond : 2 faits de niveau).
- « Équivalent par l'expérience » ne prouve aucun niveau :
  ``confidence="ambiguous"`` + marqueur ``experience_equivalent``.
- Une mention niée (« sans diplôme d'ingénieur », « keinen Masterabschluss »)
  ne produit aucun fait.
- Un champ d'études exigé sans niveau détectable (« Formation en Finance
  exigée ») produit un fait ``education_field_required`` (level_rank=0).

Les motifs de niveaux proviennent du cahier des charges SK-19 ; deux abréviations
y ont été durcies pour éviter les faux positifs documentés dans le rapport :
``m.a.``/``b.a.`` (lettre seule « ma »/« ba » en français) et ``Dr.`` (titre de
politesse « Dr. Müller »), voir docs/agent-reports/SPEC-SK19-EDUCATION_EXTRACTOR.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MAX_TEXT_CHARS = 30_000
FIELD_WINDOW_CHARS = 200
MAX_LEVEL_FACTS = 2
MAX_ALT_GAP_CHARS = 60

LANGUAGES: tuple[str, ...] = ("fr", "en", "de", "it", "es", "nl")

LevelConfidence = Literal["explicit", "inferred", "ambiguous"]


@dataclass(frozen=True, slots=True)
class EducationFact:
    """Un fait d'exigence de formation, cité verbatim depuis la source."""

    fact_type: Literal["education_level_required", "education_field_required"]
    level_rank: int
    level_label: str
    field: str | None
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: LevelConfidence
    contradictions: list[str]


_LEVEL_LABELS: dict[int, str] = {
    8: "Doctorat",
    6: "Bac+6",
    5: "Bac+5",
    4: "Bac+4",
    3: "Bac+3",
    0: "Niveau non déterminé",
}

# Motifs de niveau par rang puis par langue (cahier des charges SK-19).
_LEVEL_PATTERNS: dict[int, dict[str, tuple[str, ...]]] = {
    8: {  # PhD / Doctorat
        "fr": (r"doctorat", r"\bphd\b", r"thèse", r"doctorate"),
        "en": (r"\bphd\b", r"ph\.?d\.", r"doctorate", r"doctoral\s+degree"),
        "de": (r"promotion\b", r"doktorat"),
        "it": (r"dottorato", r"\bphd\b", r"dottore\s+di\s+ricerca"),
        "es": (r"doctorado", r"\bphd\b", r"tesis"),
        "nl": (r"promotie", r"\bphd\b", r"doctoraat"),
    },
    6: {  # Bac+6 / Master 2 / M2 / Master Spécialisé — uniquement mention explicite du 2ᵉ niveau
        "fr": (r"bac\s*\+?\s*6", r"master\s*2\b", r"\bm2\b", r"master\s+sp[ée]cialis[ée]s?\b",
               r"\bmast[èe]re\b", r"grade\s+de\s+master\b"),
        "en": (r"master\s*2\b", r"m\.(?:sc|a)\.", r"\bmsc\b", r"master\s+of\s+(?:science|arts)\b"),
        "de": (r"master\s*2\b", r"\bm2\b", r"\bdiplom\b", r"masterdiplom\b"),
        "it": (r"laurea\s+(?:specialistica|biennale)\b", r"master\s*2\b", r"\bm2\b"),
        "es": (r"m[áa]ster\s+universitario\b", r"m[áa]ster\s*2\b", r"\bm2\b"),
        "nl": (r"master\s*2\b", r"\bm2\b", r"m\.(?:sc|a)\."),
    },
    5: {  # Bac+5 / Master / M1 / École d'ingénieur / Grande École
        "fr": (r"bac\s*\+?\s*5", r"master\s*1\b", r"\bm1\b", r"école\s+d['’]ing[ée]nieur\b",
               r"grande\s+[ée]cole\b", r"dipl[ôo]me\s+d['’]ing[ée]nieur\b", r"\bpge\b",
               r"programme\s+grande\s+[ée]cole\b", r"\bmaster\b"),
        "en": (r"master(?:['’]s)?\b", r"engineering\s+degree\b", r"grande\s+ecole\b", r"french\s+engineering\b"),
        "de": (r"diplom\s+ingenieur\b", r"fh\s+master\b", r"university\s+master\b", r"masterabschluss\b",
               r"master\s+abschluss\b", r"\bmaster\b"),
        "it": (r"laurea\s+magistrale\b", r"\bingegnere\b", r"laurea\s+quinquennale\b", r"\bmaster\b"),
        "es": (r"m[áa]ster\b", r"\bingeniero\b", r"t[íi]tulo\s+de\s+ingeniero\b"),
        "nl": (r"\bmaster\b", r"\bingenieur[s]?\b", r"wo\s+master\b"),
    },
    4: {  # Bac+4 / Bachelor 4 ans / Licence 3 (convention SK-19)
        "fr": (r"bac\s*\+?\s*4", r"licence\s*3\b"),
        "en": (r"bachelor(?:['’]s)?\s+degree\b", r"\bbsc\b", r"b\.(?:sc|a)\.",
               r"bachelor\s+of\s+(?:arts|science)\b", r"undergraduate\b", r"4th\s+year\b"),
        "de": (r"\bbachelor\b", r"fh\s+bachelor\b", r"bakalaus{1,2}\b", r"bachelorabschluss\b"),
        "it": (r"laurea\s+triennale\b", r"\blaurea\b", r"\bbachelor\b"),
        "es": (r"\bgrado\b", r"\bbachelor\b", r"licenciatura\b"),
        "nl": (r"\bbachelor\b", r"\bhbo\b", r"hoger\s+beroepsonderwijs\b"),
    },
    3: {  # Bac+3 / Licence / Bachelor 3 ans
        "fr": (r"bac\s*\+?\s*3", r"\blicence\b", r"\bl3\b", r"bachelor\s*3\b"),
        "en": (r"\bbachelor\b", r"\bbsc\b", r"b\.a\.", r"3rd\s+year\b", r"undergraduate\b"),
        "de": (r"\bbachelor\b", r"bakalaus{1,2}\b"),
    },
}

# Champs d'études par ordre de priorité (le premier trouvé l'emporte).
_EDUCATION_FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "Finance": (r"finance[s]?", r"financial", r"banking", r"banque",
                r"corporate\s+finance", r"finanzas", r"financi[ëe]n", r"financi[ëe]le"),
    "Engineering": (r"ing[ée]nieur[s]?", r"engineering", r"ingenieur[s]?", r"wirtschaftsingenieur",
                    r"ingegneria", r"ingegnere", r"ingeniero", r"technisch"),
    "Business": (r"business", r"management", r"gestion", r"commerce", r"wirtschaft",
                 r"economia", r"bedrijfskunde"),
    "Data Science": (r"data\s+science", r"data\s+analysis", r"analyse\s+de\s+donn[ée]es",
                     r"datenanalyse", r"analisi\s+dati", r"an[áa]lisis\s+de\s+datos", r"dataanalyse"),
    "Mathematics": (r"math[ée]matiques", r"mathematics", r"matematica", r"matem[áa]ticas",
                    r"wiskunde", r"\bmaths?\b"),
    "Economics": (r"[ée]conomie[s]?", r"economics", r"wirtschaft", r"economia", r"economie"),
    "Law": (r"\bdroit\b", r"\blaw\b", r"\brecht\b", r"giurisprudenza", r"derecho", r"\brechten\b"),
}

_REQUIREMENT_MARKERS = re.compile(
    r"\b(?:requis[es]?|obligatoire[s]?|exig[ée][e]?s?|exigence[s]?|minimum|min\.?"
    r"|required|requires?|mandatory|must(?:\s+have)?|needs?\s+(?:a|an|to)|accepted|accept[ée]e?s?"
    r"|mindestens|erforderlich[s]?|verpflichtend|vorausgesetzt|pflicht"
    r"|obbligatori[oe]?s?|richiest[oa]?|necessari[oa]?"
    r"|requerid[oa]?|exigid[oa]?|es\s+necesario|imprescindible|aceptad[oa]?"
    r"|verplicht[e]?|vereist[e]?|geaccepteerd)",
    re.IGNORECASE,
)

# L'équivalence par l'expérience ne prouve aucun niveau (marqueur canonique).
_EQUIV_EXPERIENCE = re.compile(
    r"\b(?:ou\s+[ée]quivalent(?:\s+par\s+l['’]\s*[ée]xp[ée]rience)?"
    r"|or\s+(?:equivalent|relevant)\s+(?:experience|background)"
    r"|equivalent\s+experience"
    r"|par\s+l['’]\s*[ée]xp[ée]rience"
    r"|(?:exp[ée]rience|experience|erfahrung|esperienza|experiencia|ervaring)\s+[ée]quivalent[e]?"
    r"|per\s+(?:l['’]?\s*)?esperienza"
    r"|por\s+(?:la\s+)?experiencia"
    r"|durch\s+(?:berufs)?erfahrung|durch\s+praxis"
    r"|door\s+ervaring"
    r"|equivalente?\s+(?:per\s+)?esperienza)",
    re.IGNORECASE,
)

# Conjonction d'alternative entre deux niveaux : une seule exigence, deux façons.
_ALTERNATIVE = re.compile(
    r"\b(?:ou|or|oder|ovvero|of|ofwel|alternativement|bzw\.?)\b",
    re.IGNORECASE,
)

# Délimitateurs de clause : marqueurs et préférences évalués localement.
_CLAUSE_SPLIT = re.compile(r"[,;.!?:\n\r/()]")

_NEGATION = re.compile(
    r"\b(?:sans\s+(?:un\s+)?(?:dipl[ôo]me|bac|master|doctorat|licence)"
    r"|without\s+(?:a\s+)?(?:degree|diploma|master|phd|doctorate)"
    r"|keine[nmsr]?\s+(?:abschluss|master|promotion|diplom)"
    r"|sin\s+(?:t[íi]tulo|diploma)"
    r"|senza\s+(?:laurea|diploma)"
    r"|zonder\s+(?:diploma|master|diplomaat))",
    re.IGNORECASE,
)

_COMPILED_LEVELS: dict[tuple[int, str], re.Pattern[str]] = {
    (rank, lang): re.compile("|".join(f"(?:{item})" for item in patterns), re.IGNORECASE)
    for rank, per_lang in _LEVEL_PATTERNS.items()
    for lang, patterns in per_lang.items()
}
_COMPILED_FIELDS: dict[str, re.Pattern[str]] = {
    name: re.compile("|".join(f"(?:{item})" for item in patterns), re.IGNORECASE)
    for name, patterns in _EDUCATION_FIELD_PATTERNS.items()
}


class _Mention:
    __slots__ = ("rank", "start", "end", "quote")

    def __init__(self, rank: int, start: int, end: int, quote: str) -> None:
        self.rank = rank
        self.start = start
        self.end = end
        self.quote = quote


def detect_education_language(text: str) -> str:
    """Meilleure langue candidates du texte (heuristique de report, sans modèle)."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    scores = {lang: 0 for lang in LANGUAGES}
    probes: dict[str, tuple[str, ...]] = {
        "fr": ("diplôme", "ingénieur", "requis", "préfé", "équivalent", "bac+", "école"),
        "en": ("degree", "required", "preferred", "equivalent", "experience", "university"),
        "de": ("erforderlich", "abschluss", "wünscht", "studium", "voraussetzung"),
        "it": ("laurea", "richiesto", "obbligatorio", "preferito", "equivalente"),
        "es": ("título", "requerido", "preferido", "experiencia", "carrera"),
        "nl": ("diploma", "vereist", "gewenst", "ervaring", "universiteit"),
    }
    folded = text.casefold()
    for lang, words in probes.items():
        scores[lang] = sum(folded.count(word) for word in words)
    best = max(scores, key=lambda lang: scores[lang])
    return best if scores[best] > 0 else "en"


def _target_langs(lang: str) -> frozenset[str]:
    if not isinstance(lang, str):
        raise TypeError("lang must be a string")
    requested = lang.strip().casefold()
    if requested in ("", "auto"):
        return frozenset(LANGUAGES)
    if requested not in LANGUAGES:
        raise ValueError(f"unsupported language: {lang!r}")
    return frozenset({requested})


def _clause(text: str, start: int, end: int) -> str:
    left = start
    while left > 0 and not _CLAUSE_SPLIT.search(text[left - 1]):
        left -= 1
    right = end
    while right < len(text) and not _CLAUSE_SPLIT.search(text[right]):
        right += 1
    return text[left:right]


def _sentence(text: str, start: int, end: int) -> str:
    left = start
    while left > 0 and text[left - 1] not in ".!?\n":
        left -= 1
    right = end
    while right < len(text) and text[right] not in ".!?\n":
        right += 1
    return text[left:right]


def _confidence(context: str) -> LevelConfidence:
    """Ambigu > explicite > inféré — une préférence n'est jamais une exigence."""
    if _EQUIV_EXPERIENCE.search(context):
        return "ambiguous"
    if _REQUIREMENT_MARKERS.search(context):
        return "explicit"
    return "inferred"


def _field_near(text: str, start: int, end: int) -> tuple[str, str, int, int] | None:
    """Premier champ d'études (ordre du dictionnaire) dans la phrase ± fenêtre.

    Les champs sont détectés quelle que soit la langue ciblée : un même mot
    (« master », « wirtschaft ») sert de niveau et de champ selon le contexte.
    """
    window_left = max(0, start - FIELD_WINDOW_CHARS)
    window_right = min(len(text), end + FIELD_WINDOW_CHARS)
    sentence = _sentence(text, start, end)
    for name, pattern in _COMPILED_FIELDS.items():
        hit = pattern.search(sentence)
        if hit is not None and window_left <= hit.start() and hit.end() <= window_right:
            return name, hit.group(0), hit.start(), hit.end()
        hit = pattern.search(text[window_left:window_right])
        if hit is not None:
            return name, hit.group(0), window_left + hit.start(), window_left + hit.end()
    return None


def _collect_mentions(text: str, langs: frozenset[str]) -> list[_Mention]:
    """Tous les motifs non chevauchants, du plus long au plus haut rang."""
    candidates: list[_Mention] = []
    for (rank, lang), pattern in _COMPILED_LEVELS.items():
        if lang not in langs:
            continue
        for hit in pattern.finditer(text):
            candidates.append(_Mention(rank, hit.start(), hit.end(), hit.group(0)))
    candidates.sort(key=lambda item: (-(item.end - item.start), -item.rank, item.start))
    chosen: list[_Mention] = []
    for item in candidates:
        if all(item.end <= other.start or other.end <= item.start for other in chosen):
            chosen.append(item)
    chosen = [item for item in chosen if not _NEGATION.search(_sentence(text, item.start, item.end))]
    chosen.sort(key=lambda item: item.start)
    return chosen


def _level_fact(text: str, mention: _Mention, contradictions: list[str]) -> EducationFact:
    context = _clause(text, mention.start, mention.end)
    confidence = _confidence(context)
    if confidence == "ambiguous" and "experience_equivalent" not in contradictions:
        contradictions = [*contradictions, "experience_equivalent"]
    found = _field_near(text, mention.start, mention.end)
    return EducationFact(
        fact_type="education_level_required",
        level_rank=mention.rank,
        level_label=_LEVEL_LABELS[mention.rank],
        field=found[0] if found else None,
        source_field="description_passage",
        quote=mention.quote,
        start_offset=mention.start,
        end_offset=mention.end,
        confidence=confidence,
        contradictions=contradictions,
    )


def extract_education(text: str, lang: str = "auto") -> list[EducationFact]:
    """Extraire l'exigence de formation d'une offre, avec preuve citée exacte.

    Retourne généralement un fait, deux en cas de contradiction de niveaux
    (plafond ``MAX_LEVEL_FACTS``), plus un éventuel fait de champ seul quand
    aucune phrase ne contient de niveau détectable. ``lang`` filtre les motifs
    linguistiques ; ``"auto"`` (défaut) balaie les six langues supportées.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    source = text[:MAX_TEXT_CHARS]
    if not source.strip():
        return []
    langs = _target_langs(lang)
    mentions = _collect_mentions(source, langs)

    # Deux motifs de la même classe (« Doctorat (PhD) ») disent la même chose :
    # on garde la première occurrence, seuls les rangs distincts peuvent opposer.
    if len(mentions) > 1:
        by_rank: dict[int, _Mention] = {}
        for item in mentions:
            by_rank.setdefault(item.rank, item)
        mentions = sorted(by_rank.values(), key=lambda item: item.start)

    if not mentions:
        equiv = _EQUIV_EXPERIENCE.search(source)
        if equiv is not None:
            return [EducationFact(
                fact_type="education_level_required",
                level_rank=0,
                level_label=_LEVEL_LABELS[0],
                field=None,
                source_field="description_passage",
                quote=equiv.group(0),
                start_offset=equiv.start(),
                end_offset=equiv.end(),
                confidence="ambiguous",
                contradictions=["experience_equivalent"],
            )]
        for name, pattern in _COMPILED_FIELDS.items():
            for hit in pattern.finditer(source):
                if _NEGATION.search(_sentence(source, hit.start(), hit.end())):
                    continue
                context = _sentence(source, hit.start(), hit.end())
                return [EducationFact(
                    fact_type="education_field_required",
                    level_rank=0,
                    level_label="",
                    field=name,
                    source_field="description_passage",
                    quote=hit.group(0),
                    start_offset=hit.start(),
                    end_offset=hit.end(),
                    confidence=_confidence(context),
                    contradictions=[],
                )]
        return []

    # Chaînage des mentions par ordre de texte : compound / alternative / conflit.
    if len(mentions) == 1:
        return [_level_fact(source, mentions[0], [])]

    gaps_ok = True
    for previous, following in zip(mentions, mentions[1:]):
        gap = source[previous.end:following.start]
        if _CLAUSE_SPLIT.search(gap) or _ALTERNATIVE.search(gap[:MAX_ALT_GAP_CHARS]):
            gaps_ok = False
            break
        if len(gap.strip()) > 4:
            gaps_ok = False
            break
    if gaps_ok:
        top = max(mentions, key=lambda item: (item.rank, -(item.end - item.start)))
        return [_level_fact(source, top, [])]

    alternative_pairs = [
        (previous, following)
        for previous, following in zip(mentions, mentions[1:])
        if _ALTERNATIVE.search(source[previous.end:following.start][:MAX_ALT_GAP_CHARS])
        and not _CLAUSE_SPLIT.search(source[previous.end:following.start])
    ]
    if alternative_pairs and len(alternative_pairs) == len(mentions) - 1:
        first = mentions[0]
        notes = [
            f"Niveau alternatif : {_LEVEL_LABELS[other.rank]} (« {other.quote} »)"
            for other in mentions[1:]
        ]
        return [_level_fact(source, first, notes)]

    ordered = sorted(mentions, key=lambda item: (-item.rank, item.start))[:MAX_LEVEL_FACTS]
    facts: list[EducationFact] = []
    for mention in ordered:
        notes = [
            f"Niveau concurrent : {_LEVEL_LABELS[other.rank]} (« {other.quote} »)"
            for other in ordered
            if other.start != mention.start
        ]
        facts.append(_level_fact(source, mention, notes))
    facts.sort(key=lambda fact: -fact.level_rank)
    return facts
