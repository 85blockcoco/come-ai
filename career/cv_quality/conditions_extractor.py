"""Extraction des conditions de travail d'une offre (SK-17).

Module **pur, déterministe, hors-ligne** : pas de réseau, pas de modèle, pas
d'écriture disque.  Seules les conditions **écrites** dans le texte sont
renvoyées — une offre qui ne dit rien du télétravail ne produit aucun fait
(jamais de valeur par défaut).

Ce que le module capte :

- **Localisation du travail** : ``remote``, ``hybrid`` (avec le nombre de
  jours par semaine quand le texte le précise), ``onsite``.
- **Organisation du temps** : ``flexible_hours``, ``part_time``.
- **Avantages** (typés) : ``meal_vouchers``, ``health_insurance``,
  ``transport``, ``equipment``.
- **Formation** : ``training_budget`` (avec le montant), ``certification_support``,
  ``language_training``.
- **Mobilité** : ``relocation``, ``visa_sponsorship``, ``mobility_budget``.

Langues couvertes : **FR, EN, DE, IT, ES, NL**.

Usage :

    >>> from career.cv_quality import extract_conditions
    >>> [f.condition_type for f in extract_conditions("Télétravail 2 jours par semaine")]
    ['hybrid']
    >>> extract_conditions("Télétravail 2 jours par semaine")[0].value
    '2 days/week'

Principes de conception :

1. **Rien n'est inventé.**  Un fait porte la citation exacte qui l'a produit,
   son champ source et ses offsets dans le texte.  Une condition absente du
   texte est absente du résultat.
2. **Les contradictions restent visibles.**  Deux statements incompatibles
   (« full remote » + « 2 days onsite ») produisent deux faits, chacun
   annoté, jamais une moyenne silencieuse.
3. **Le contrat est prioritaire, la précision ensuite.**  Un motif qui
   précise (« 3 days per week remote ») est préféré à un motif vague
   (« remote »).
4. **La langue ne supprime rien.**  ``lang`` fixe l'**ordre de priorité** des
   motifs (la langue détectée d'abord), pas un filtre : une annonce bilingue
   reste entièrement analysée.

Voir ``docs/agent-reports/SPEC-SK17-CONDITIONS_EXTRACTOR.md`` pour le
détail des décisions et la couverture de tests.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

# ───────────────────────────────────────────────────────────────────────
# Types publics
# ───────────────────────────────────────────────────────────────────────

ConditionType = Literal[
    "remote",
    "hybrid",
    "onsite",
    "flexible_hours",
    "part_time",
    "meal_vouchers",
    "health_insurance",
    "transport",
    "equipment",
    "training_budget",
    "certification_support",
    "language_training",
    "relocation",
    "visa_sponsorship",
    "mobility_budget",
]
"""Types de conditions extraits (15 types)."""

Confidence = Literal["explicit", "inferred", "ambiguous"]
"""Niveau de confiance d'un fait.

- ``explicit`` : le texte énonce la condition sans ambiguïté.
- ``inferred`` : la condition est sous-entendue (mention générique, sans
  précision exploitable).
- ``ambiguous`` : deux statements du même type se contredisent.
"""

SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "en", "de", "it", "es", "nl")

CONDITION_GROUPS: dict[str, str] = {
    "remote": "work_location",
    "hybrid": "work_location",
    "onsite": "work_location",
    "flexible_hours": "schedule",
    "part_time": "schedule",
    "meal_vouchers": "benefits",
    "health_insurance": "benefits",
    "transport": "benefits",
    "equipment": "benefits",
    "training_budget": "training",
    "certification_support": "training",
    "language_training": "training",
    "relocation": "mobility",
    "visa_sponsorship": "mobility",
    "mobility_budget": "mobility",
}
"""Rattachement des types fins aux groupes du contrat SK-17.

``benefits`` = ``meal_vouchers`` / ``health_insurance`` / ``transport`` /
``equipment`` ; ``training`` = ``training_budget`` /
``certification_support`` / ``language_training`` ; ``mobility`` =
``relocation`` / ``visa_sponsorship`` / ``mobility_budget``.
"""


@dataclass
class ConditionFact:
    """Une condition de travail explicitement écrite dans le texte d'une offre.

    Attributes:
        condition_type: Type de condition (voir :data:`ConditionType`).
        value: Valeur lue : ``True``/``False`` pour un booléen, ``"2 days/week"``
            pour un rythme hybridé, ``2000`` pour un montant de formation.
        source_field: Champ d'origine (``description_original``, ``title``…).
        quote: Citation **exacte** du texte qui a produit le fait.
        start_offset: Index du début de la citation dans le texte.
        end_offset: Index de la fin de la citation dans le texte.
        confidence: Niveau de confiance (voir :data:`Confidence`).
        contradictions: Contradictions relevées avec les autres faits
            (``remote_vs_onsite``, ``hybrid_conflict``…).
    """

    condition_type: ConditionType
    value: Optional[bool | str | int]
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Confidence
    contradictions: list[str] = field(default_factory=list)

    @property
    def group(self) -> str:
        """Groupe du contrat SK-17 auquel appartient le type."""
        return CONDITION_GROUPS.get(self.condition_type, "other")

    def to_dict(self) -> dict[str, Any]:
        """Version sérialisable (JSON-safe) du fait."""
        data = asdict(self)
        data["group"] = self.group
        return data


# ───────────────────────────────────────────────────────────────────────
# Motifs du contrat SK-17
# ───────────────────────────────────────────────────────────────────────
#
# Les motifs « obligatoires » du contrat sont repris **verbatim**, regroupés
# par langue pour que la priorité de langue soit exploitable.  Les motifs
# complémentaires (notés ``supplementary`` plus bas) ne font qu'élargir la
# couverture : ils n'ont jamais de rôle dans la suppression d'un fait.

_REMOTE_PATTERNS: dict[str, tuple[str, ...]] = {
    "fr": (
        r"\b(?:télétravail|travail\s+à\s+distance|full\s*remote|100%\s*remote|entièrement\s+à\s+distance)\b",
    ),
    "en": (
        r"\b(?:remote|work\s+from\s+home|wfh|fully\s+remote|remote-first)\b",
    ),
    "de": (
        r"\b(?:homeoffice|home\s*office|remote\s*arbeit|vollständig\s+remote)\b",
    ),
    "it": (
        r"\b(?:lavoro\s+da\s+casa|smart\s*working|full\s*remote|lavoro\s+agile)\b",
    ),
    "es": (
        r"\b(?:teletrabajo|trabajo\s+remoto|totalmente\s+remoto)\b",
    ),
    "nl": (
        r"\b(?:thuiswerken|volledig\s+remote|remote\s+werken)\b",
    ),
}

_HYBRID_PATTERNS: dict[str, tuple[str, ...]] = {
    "fr": (
        r"\b(?:hybride|télétravail\s+partiel|(\d)\s*jours?\s*(?:par\s+semaine|/semaine)\s*(?:de\s+télétravail|à\s+distance))\b",
    ),
    "en": (
        r"\b(?:hybrid|(\d)\s*days?\s*(?:per\s+week|/week)\s*(?:remote|wfh|from\s+home))\b",
    ),
    "de": (
        r"\b(?:hybrid|(\d)\s*tage\s*(?:pro\s+woche|/woche)\s*(?:homeoffice|remote))\b",
    ),
    "it": (
        r"\b(?:ibrido|(\d)\s*giorni?\s*(?:a\s+settimana|/sett)\s*(?:smart\s+working|da\s+casa))\b",
    ),
    "es": (
        r"\b(?:híbrido|(\d)\s*días?\s*(?:por\s+semana|/sem)\s*(?:teletrabajo|en\s+remoto))\b",
    ),
    "nl": (
        r"\b(?:hybride|(\d)\s*dagen?\s*(?:per\s+week|/week)\s*(?:thuiswerken|remote))\b",
    ),
}

_ONSITE_PATTERNS: dict[str, tuple[str, ...]] = {
    "*": (
        r"\b(?:présentiel|on.?site|sur\s+site|büro|in\s+office|in\s+sede|en\s+oficina|op\s+locatie)\b",
    ),
}

_FLEXIBLE_HOURS_PATTERNS: dict[str, tuple[str, ...]] = {
    "*": (
        r"\b(?:horaires?\s+flexibles?|flexible\s+(?:working\s+)?hours?|flexitime|gleitzeit|orari?\s+flessibili|horario\s+flexible|flexibele\s+werkuren)\b",
        r"\b(?:choix\s+(?:des\s+)?horaires?|choose\s+(?:your\s+)?hours?|selbstbestimmte\s+arbeitszeit)\b",
    ),
}

_PART_TIME_PATTERNS: dict[str, tuple[str, ...]] = {
    "*": (
        r"\b(?:temps\s+partiel|part.?time|teilzeit|part.?time|tijdsdeeltijd)\b",
        r"\b(?:(\d{1,2})\s*h(?:eures?)?\s*(?:par\s+semaine|/sem))\b",
    ),
}

_BENEFITS_PATTERNS: dict[str, tuple[str, ...]] = {
    "meal_vouchers": (
        r"\b(?:tickets?\s+resto|tickets?\s+restaurant|meal\s+vouchers?|essenszuschuss|buoni\s+pasto|cheques?\s+comida|maaltijdcheques)\b",
    ),
    "health_insurance": (
        r"\b(?:mutuelle|assurance\s+santé|health\s+insurance|krankenversicherung|assicurazione\s+salute|seguro\s+médico|ziekteverzekering)\b",
    ),
    "transport": (
        r"\b(?:remboursement\s+transport|transport\s+allowance|jobticket|fahrtkostenzuschuss|rimborso\s+trasporti|transporte\s+público|vergoeding\s+openbaar\s+vervoer)\b",
    ),
    "equipment": (
        r"\b(?:matériel\s+fourni|equipment\s+provided|arbeitsmittel|attrezzatura\s+fornita|equipo\s+proporcionado|apparatuur\s+geleverd)\b",
    ),
}

_TRAINING_PATTERNS: dict[str, tuple[str, ...]] = {
    "training_budget": (
        r"\b(?:budget\s+formation|training\s+budget|fortbildungsbudget|budget\s+formazione|presupuesto\s+formación|opleidingsbudget)\s*(?:de|:)?\s*(\d+(?:[.,]\d{3})*)\s*[€$£]",
        r"\b(?:formation\s+(?:prise\s+en\s+charge|financée)|paid\s+training|bezahlte\s+fortbildung)\b",
    ),
    "certification_support": (
        r"\b(?:certification\s+(?:payée|financée|sponsorisée)|certification\s+support|zertifizierung|certificazione)\b",
    ),
    "language_training": (
        r"\b(?:cours?\s+de?\s+langues?|language\s+(?:classes?|training)|sprachkurs|corsi?\s+di\s+lingua|clases?\s+de\s+idiomas|taalcursus)\b",
    ),
}

_MOBILITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "relocation": (
        r"\b(?:relocation|aide\s+installation|relocation\s+package|umzugshilfe|trasloco|reubicación|verhuizing)\b",
    ),
    "visa_sponsorship": (
        r"\b(?:visa\s+sponsor(?:ship|ed)|sponsor\s+visa|visa\s+support|arbeitserlaubnis|permesso\s+lavoro|permiso\s+trabajo|visum\s+sponsoring)\b",
    ),
    "mobility_budget": (
        r"\b(?:budget\s+mobilité|mobility\s+budget|mobilitätsbudget|budget\s+mobilità|presupuesto\s+movilidad|mobiliteitsbudget)\b",
    ),
}

# Motifs complémentaires : ils élargissent la couverture sans jamais retirer
# un fait (motifs du contrat).  Ils portent tous une confiance explicite.
_SUPPLEMENTARY_PATTERNS: dict[tuple[str, str], tuple[str, ...]] = {
    ("flexible_hours", "*"): (
        # Formules explicites : elles nomment le rythme de travail.
        r"\bflexible\s+(?:arbeitszeiten?|schedule|temps\s+de\s+travail|agenda|planning|zeiten|working\s+times)\b",
        # Mentions génériques : elles n'apportent aucune précision, donc la
        # confiance reste « inferred ».
        r"\bflexible\b",
        r"\bflexibel\b",
        r"\bflessibile\b",
        r"\bflexibilit[ée]\b",
        r"\bflexibilit[äa]t\b",
        r"\bflessibilit[àa]\b",
        r"\bflexibilidad\b",
        r"\bflexibiliteit\b",
    ),
    ("equipment", "*"): (
        r"\b(?:laptop|macbook|pc\s+portable|computer)\s+(?:fourni|provided|gestellte|incluso|incluido|geleverd)\b",
        r"\b(?:fourni|provided|gestellte)\s+(?:laptop|macbook|pc\s+portable)\b",
    ),
    ("training_budget", "*"): (
        # Le motif du contrat exige un symbole monétaire ; on accepte aussi
        # le code ISO écrit (« 1500 EUR »).
        r"\b(?:budget\s+formation|training\s+budget|fortbildungsbudget|budget\s+formazione|presupuesto\s+formaci[óo]n|opleidingsbudget)\s*(?:de|:)?\s*(\d+(?:[.,]\d{3})*)\s*(?:eur|euros?|usd|chf|gbp)\b",
    ),
    ("certification_support", "*"): (
        r"\bcertifications?\s+(?:pay[ée]e?s?|financ[ée]e?s?|sponsoris[ée]e?s?|support|inclus|included|covered)\b",
    ),
    ("language_training", "*"): (
        r"\b(?:cours?\s+de\s+langues?|formation\s+linguistique|language\s+lessons)\b",
    ),
    ("relocation", "*"): (
        r"\brelocation\s+(?:package|support|assistance)\b",
    ),
    ("visa_sponsorship", "*"): (
        r"\b(?:visa\s+relocation|relocation\s+visa)\b",
    ),
}

# Vocabulaire par langue : sert aux motifs complémentaires (rythme
# hybridé, détection de langue).  Les alternatives sont rangées de la plus
# longue à la plus courte : une alternative préfixe d'une autre ne doit
# jamais masquer la forme longue (« en remoto » avant « remoto »).
_LANG_VOCAB: dict[str, dict[str, str]] = {
    "fr": {
        "day": r"journ[ée]es?|jours?",
        "remote": r"travail\s+[àa]\s+distance|t[ée]l[ée]travail|[àa]\s+distance",
        "onsite": r"pr[ée]sentiel|sur\s+site|en\s+office",
        "hybrid": r"hybride",
        "per_week": r"par\s+semaine|/semaine",
        "markers": (
            r"\b(?:poste|notre|nous|vous|avec|pour|recherche|horaires|mutuelle|CDI|stage|t[ée]l[ée]travail|pr[ée]sentiel|hybride)\b",
        ),
    },
    "en": {
        "day": r"days?",
        "remote": r"work\s+from\s+home|from\s+home|remote|wfh",
        "onsite": r"on.?site|in\s+office|in-person",
        "hybrid": r"hybrid",
        "per_week": r"per\s+week|/week|a\s+week",
        "markers": (
            r"\b(?:the|and|with|for|our|job|role|apply|salary|benefits|location|experience|full-time|remote|hybrid)\b",
        ),
    },
    "de": {
        "day": r"tagen|tage",
        "remote": r"home\s*office|remote\s*arbeit|remote",
        "onsite": r"vor\s+ort|vor-ort|pr[äa]sent|b[üu]ro",
        "hybrid": r"hybrid",
        "per_week": r"pro\s+woche|/woche|je\s+woche",
        "markers": (
            r"\b(?:und|der|die|das|mit|f[üu]r|unsere|wir|gehalt|vorteile|standort|bewerbung|anforderung|homeoffice|gleitzeit)\b",
        ),
    },
    "it": {
        "day": r"giorni|giorno",
        "remote": r"lavoro\s+da\s+casa|smart\s*working|da\s+casa|a\s+distanza|remoto",
        "onsite": r"in\s+sede|in\s+presenza|ufficio",
        "hybrid": r"ibrido",
        "per_week": r"a\s+settimana|/sett|alla\s+settimana",
        "markers": (
            r"\b(?:e|di|con|per|nostra|noi|voi|offerta|candidatura|esperienza|retribuzione|benefit|requisiti|smart\s*working)\b",
        ),
    },
    "es": {
        "day": r"d[íi]as?|dias",
        "remote": r"trabajo\s+remoto|en\s+remoto|teletrabajo|a\s+distancia|remoto",
        "onsite": r"presencial|en\s+oficina|en\s+sede",
        "hybrid": r"h[íi]brido|hibrido",
        "per_week": r"por\s+semana|/sem",
        "markers": (
            r"\b(?:y|el|la|los|las|para|con|nuestro|nuestra|salario|beneficios|requisitos|experiencia|teletrabajo)\b",
        ),
    },
    "nl": {
        "day": r"dagen|dag",
        "remote": r"thuis\s*werken|remote",
        "onsite": r"op\s+locatie|op\s+kantoor|ter\s+plaatse",
        "hybrid": r"hybride",
        "per_week": r"per\s+week|/week",
        "markers": (
            r"\b(?:en|de|het|een|met|voor|onze|salaris|voordelen|vereisten|ervaring|thuiswerken)\b",
        ),
    },
}

# Espace flexible entre deux mots : autorise « Hybrid: 3 days », « 2 jours,
# par semaine », sans jamais franchir un point-virgule ou un point.
_GAP = r"[^\S\n]{0,4}(?:[:;,\u2013\u2014-][^\S\n]{0,4})?"

# ───────────────────────────────────────────────────────────────────────
# Négation
# ───────────────────────────────────────────────────────────────────────

_NEGATION_MARKERS: dict[str, tuple[str, ...]] = {
    "*": (
        r"\bno\b",
        r"\bnot\b",
        r"\bnon\b",
        r"\bnessun[ao]?\b",
        r"\bwithout\b",
        r"\bkein(?:e|en|er|es)?\b",
        r"\bnicht\b",
        r"\bohne\b",
        r"\bsin\b",
        r"\bsenza\b",
        r"\bgeen\b",
        r"\bniet\b",
        r"\bzonder\b",
        r"\bpas\s+de\b",
        r"\bpas\s+d\u2019",
        r"\bpas\s+d'",
        r"\baucun(?:e)?\b",
        r"\bwithout\s+any\b",
        r"\bnot\s+available\b",
    ),
}

# Mots qui peuvent s'intercaler entre le marqueur de négation et le mot
# nié (« pas de télétravail », « no remote work », « sin teletrabajo »).
_NEGATION_FILLERS = frozenset(
    {
        "de", "d'", "d\u2019", "du", "des", "la", "le", "les", "l'", "un", "une",
        "the", "a", "an", "any", "of", "e", "el", "los", "las", "il", "lo",
        "gli", "dei", "der", "die", "das", "den", "dem", "het", "een", "en",
        "y", "i", "und", "o", "possibilite", "possibilit\u00e9", "possibility",
        "mogelijkheid", "m\u00f6glichkeit", "possibilit\u00e0", "possibilite",
    }
)

_NEGATION_BOUNDARIES = ".,;:!?\n\r()[]|\u201c\u201d\u2018\u2019"

# ───────────────────────────────────────────────────────────────────────
# Garde-fous
# ───────────────────────────────────────────────────────────────────────

#: En deçà de ce nombre d'heures par semaine, un volume horaire est un
#: temps partiel.  Au-delà, c'est un temps plein : le signaler comme temps
#: partiel serait faux.
PART_TIME_MAX_HOURS = 34

#: Nombre maximum de faits conservés par type de condition (garde-fou anti-bruit).
MAX_FACTS_PER_TYPE = 3

#: Champs d'offre inspectés par :func:`extract_conditions_from_offer`.
OFFER_SOURCE_FIELDS: tuple[str, ...] = (
    "description_original",
    "description",
    "title",
    "requirements",
    "benefits",
    "conditions",
    "working_conditions",
    "perks",
    "notes",
)


# ───────────────────────────────────────────────────────────────────────
# Compilation des motifs
# ───────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Rule:
    """Un motif compilé, rattaché à un type de condition."""

    condition_type: ConditionType
    pattern: re.Pattern[str]
    language: str
    confidence: Confidence
    order: int


def _skip_class(pattern: str, index: int) -> int:
    """Index de la fin d'une classe de caractères (``[...]``)."""
    end = index + 1
    if end < len(pattern) and pattern[end] == "^":
        end += 1
    if end < len(pattern) and pattern[end] == "]":
        end += 1
    while end < len(pattern) and pattern[end] != "]":
        if pattern[end] == "\\":
            end += 1
        end += 1
    return end


def _matching_paren(pattern: str, index: int) -> int:
    """Index de la parenthèse fermante correspondant à ``pattern[index]``."""
    depth = 0
    end = index
    while end < len(pattern):
        char = pattern[end]
        if char == "\\":
            end += 2
            continue
        if char == "[":
            end = _skip_class(pattern, end) + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return end
        end += 1
    return len(pattern)


def _split_top_level(text: str) -> list[str]:
    """Découpe un motif sur ses ``|`` de premier niveau."""
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            buffer.append(text[index:index + 2])
            index += 2
            continue
        if char == "[":
            end = _skip_class(text, index)
            buffer.append(text[index:end + 1])
            index = end + 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "|" and depth == 0:
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
        index += 1
    parts.append("".join(buffer))
    return parts


def _expand_alternatives(pattern: str, limit: int = 64) -> list[str]:
    """Développe les alternatives d'un motif en motifs indépendants.

    Python applique une alternative dans l'ordre d'écriture : dans
    ``(?:remote|remote-first)``, c'est ``remote`` qui gagne toujours et
    ``remote-first`` ne sera jamais cité.  Chaque alternative du **premier**
    groupe est donc compilée séparément : la plus longue (« Remote-first »)
    l'emporte ensuite naturally, et la citation reste la plus précise
    possible.

    Seul le premier groupe est développé : une expansion récursive ferait
    exploser le nombre de variantes (et risquerait d'en perdre au passage).

    Args:
        pattern: Motif regex.
        limit: Nombre maximal de variantes produites (garde-fou).

    Returns:
        La liste des variantes (une seule si le motif n'a pas d'alternative).
    """
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            index = _skip_class(pattern, index) + 1
            continue
        if pattern.startswith("(?:", index):
            end = _matching_paren(pattern, index)
            inner = pattern[index + 3:end]
            parts = _split_top_level(inner)
            if len(parts) > 1:
                return [pattern[:index] + part + pattern[end + 1:] for part in parts[:limit]]
            index = end + 1
            continue
        index += 1
    return [pattern]


def _compile_rules() -> list[_Rule]:
    """Compile tous les motifs (contrat + complémentaires) en règles ordonnées."""
    rules: list[_Rule] = []
    order = 0

    def add(condition_type: ConditionType, language: str, raw: str, confidence: Confidence) -> None:
        nonlocal order
        for variant in _expand_alternatives(raw):
            rules.append(
                _Rule(condition_type, re.compile(variant, re.IGNORECASE), language, confidence, order)
            )
            order += 1

    # ── Localisation du travail ──────────────────────────────────────────
    for language, patterns in _REMOTE_PATTERNS.items():
        for raw in patterns:
            add("remote", language, raw, "explicit")
    for language, patterns in _HYBRID_PATTERNS.items():
        for raw in patterns:
            add("hybrid", language, raw, "explicit")
    for language, patterns in _ONSITE_PATTERNS.items():
        for raw in patterns:
            add("onsite", language, raw, "explicit")

    # ── Organisation du temps ───────────────────────────────────────────
    for language, patterns in _FLEXIBLE_HOURS_PATTERNS.items():
        for raw in patterns:
            add("flexible_hours", language, raw, "explicit")
    for language, patterns in _PART_TIME_PATTERNS.items():
        for raw in patterns:
            add("part_time", language, raw, "explicit")

    # ── Avantages ───────────────────────────────────────────────────────
    for condition_type, patterns in _BENEFITS_PATTERNS.items():
        for raw in patterns:
            add(condition_type, "*", raw, "explicit")

    # ── Formation ───────────────────────────────────────────────────────
    for condition_type, patterns in _TRAINING_PATTERNS.items():
        for raw in patterns:
            add(condition_type, "*", raw, "explicit")

    # ── Mobilité ────────────────────────────────────────────────────────
    for condition_type, patterns in _MOBILITY_PATTERNS.items():
        for raw in patterns:
            add(condition_type, "*", raw, "explicit")

    # ── Motifs complémentaires ──────────────────────────────────────────
    for (condition_type, language), patterns in _SUPPLEMENTARY_PATTERNS.items():
        for raw in patterns:
            confidence: Confidence = "explicit"
            if condition_type == "flexible_hours":
                # Une mention générique (« flexible ») reste une inférence.
                confidence = (
                    "inferred"
                    if not re.search(r"(?:horaires|hours|arbeitszeiten|schedule|zeiten|travail|planning|agenda)", raw, re.IGNORECASE)
                    else "explicit"
                )
            add(condition_type, language, raw, confidence)

    # ── Rythme hybridé (complémentaire, par langue) ─────────────────────
    for language, vocab in _LANG_VOCAB.items():
        location = rf"(?:{vocab['remote']}|{vocab['onsite']})"
        day = rf"(?:{vocab['day']})"
        add("hybrid", language, rf"\b(?:{vocab['hybrid']}){_GAP}(?:\w+\s+){{0,2}}?(\d{{1,2}})\s+{day}\b", "explicit")
        add("hybrid", language, rf"\b(\d{{1,2}})\s+{day}\b{_GAP}{location}\b", "explicit")
        add("hybrid", language, rf"\b{location}{_GAP}(\d{{1,2}})\s+{day}\b", "explicit")

    return rules


_RULES = _compile_rules()

#: Motifs de négation compilés (toutes langues confondues).
_NEGATION_RE = re.compile("|".join(f"(?:{raw})" for raw in _NEGATION_MARKERS["*"]), re.IGNORECASE)

#: Détection du nombre de jours dans une citation hybridée.
_DAY_COUNT_RE = re.compile(r"\b(\d{1,2})\b")

#: Montant d'un budget de formation.
_AMOUNT_RE = re.compile(r"\d+(?:[.,]\d{3})*")

#: Repérage d'une heure hebdomadaire (pour le garde-fou temps partiel).
_HOURS_RE = re.compile(r"\b(\d{1,2})\s*h(?:eures?)?\s*(?:par\s+semaine|/sem)\b", re.IGNORECASE)


# ───────────────────────────────────────────────────────────────────────
# Détection de langue
# ───────────────────────────────────────────────────────────────────────


def detect_language(text: str) -> str:
    """Devine la langue principale d'un texte.

    La détection est volontairement grossière et **stable** : elle ne sert
    qu'à fixer l'ordre de priorité des motifs.  Un texte sans marqueur
    linguistique reconnaissable renvoie ``"en"``.

    Args:
        text: Texte analysé.

    Returns:
        Un code de langue parmi :data:`SUPPORTED_LANGUAGES`.
    """
    if not text:
        return "en"
    lowered = text.lower()
    scores: dict[str, int] = {}
    for language, vocab in _LANG_VOCAB.items():
        score = 0
        for marker in vocab["markers"]:
            score += 3 * len(re.findall(marker, lowered, re.IGNORECASE))
        scores[language] = score
    best = max(scores, key=lambda language: (scores[language], -SUPPORTED_LANGUAGES.index(language)))
    return best


def _language_phases(primary: str) -> tuple[str, ...]:
    """Ordre de traitement des langues : langue prioritaire d'abord."""
    return (primary,) + tuple(lang for lang in SUPPORTED_LANGUAGES if lang != primary)


# ───────────────────────────────────────────────────────────────────────
# Internes
# ───────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Candidate:
    """Candidat brut : un motif a matché un passage du texte."""

    condition_type: ConditionType
    start: int
    end: int
    quote: str
    language: str
    confidence: Confidence
    rule_order: int

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def phase(self) -> int:
        return 0 if self.language == "*" else 1


def _only_fillers(tail: str) -> bool:
    """Indique si ``tail`` ne contient que des mots de remplissage."""
    tokens = [token.strip(".,;:!?\u2019'\"").lower() for token in tail.split()]
    tokens = [token for token in tokens if token]
    return all(token in _NEGATION_FILLERS for token in tokens)


def _is_negated(text: str, start: int) -> bool:
    """Indique si le passage démarrant à ``start`` est nié.

    La négation est cherchée **avant** le passage, sans franchir de frontière
    de phrase ou de champ : « pas de télétravail, sur site » ne nie donc que
    le télétravail.
    """
    window = text[max(0, start - 60):start]
    cut = -1
    for boundary in _NEGATION_BOUNDARIES:
        index = window.rfind(boundary)
        if index > cut:
            cut = index
    window = window[cut + 1:]
    for match in _NEGATION_RE.finditer(window):
        if _only_fillers(window[match.end():]):
            return True
    return False


def _amount_value(raw: str) -> int:
    """Convertit un montant écrit (``2.000``, ``1,500``) en entier."""
    cleaned = re.sub(r"[.,\s]", "", raw)
    try:
        return int(cleaned)
    except ValueError:
        return 0


def _day_count(quote: str) -> int | None:
    """Nombre de jours/semaine mentionné dans une citation hybridée."""
    match = _DAY_COUNT_RE.search(quote)
    if match is None:
        return None
    return int(match.group(1))


def _collect_candidates(text: str, primary: str) -> list[_Candidate]:
    """Exécute tous les motifs et renvoie les candidats retenus par type."""
    phases = _language_phases(primary)
    phase_index = {language: index for index, language in enumerate(phases)}

    best: dict[str, list[_Candidate]] = {}
    for rule in _RULES:
        for match in rule.pattern.finditer(text):
            candidate = _Candidate(
                condition_type=rule.condition_type,
                start=match.start(),
                end=match.end(),
                quote=match.group(0),
                language=rule.language,
                confidence=rule.confidence,
                rule_order=rule.order,
            )
            bucket = best.setdefault(rule.condition_type, [])
            bucket.append(candidate)

    # 1. Un candidat contenu dans un candidat plus long du même type est
    #    redondant (« flexible » dans « flexible hours »).
    for condition_type, candidates in best.items():
        kept: list[_Candidate] = []
        for candidate in candidates:
            redundant = any(
                other is not candidate
                and other.start <= candidate.start
                and other.end >= candidate.end
                and other.length > candidate.length
                for other in candidates
            )
            if not redundant:
                kept.append(candidate)
        best[condition_type] = kept

    # 2. Un arrangement hybridé est plus précis que « remote » ou « onsite »
    #    : quand les passages se recouvrent, le plus spécifique l'emporte.
    hybrid_spans = [
        (candidate.start, candidate.end)
        for candidate in best.get("hybrid", [])
    ]
    if hybrid_spans:
        for condition_type in ("remote", "onsite"):
            kept = []
            for candidate in best.get(condition_type, []):
                overlapping = any(
                    candidate.start < end and start < candidate.end
                    for start, end in hybrid_spans
                )
                if not overlapping:
                    kept.append(candidate)
            best[condition_type] = kept

    # 3. Un seul fait par type et par zone : on ne garde que les passages
    #    non chevauchants, priorité à la langue prioritaire puis au motif
    #    le plus long.
    selected: list[_Candidate] = []
    for condition_type, candidates in best.items():
        if not candidates:
            continue
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                phase_index.get(candidate.language, len(phases)) if candidate.language != "*" else len(phases),
                -candidate.length,
                candidate.start,
            ),
        )
        chosen: list[_Candidate] = []
        for candidate in ordered:
            if len(chosen) >= MAX_FACTS_PER_TYPE:
                break
            if any(candidate.start < other.end and other.start < candidate.end for other in chosen):
                continue
            chosen.append(candidate)
        selected.extend(chosen)

    selected.sort(key=lambda candidate: (candidate.start, candidate.condition_type))
    return selected


def _build_fact(candidate: _Candidate, text: str, source_field: str) -> ConditionFact:
    """Transforme un candidat en fait exploitable (valeur, confiance, négation)."""
    condition_type = candidate.condition_type
    value: bool | str | int | None = True
    confidence = candidate.confidence

    if condition_type == "hybrid":
        days = _day_count(candidate.quote)
        value = f"{days} days/week" if days is not None else True
    elif condition_type == "part_time":
        hours_match = _HOURS_RE.search(candidate.quote)
        if hours_match is not None:
            hours = int(hours_match.group(1))
            if hours > PART_TIME_MAX_HOURS:
                # « 40 heures par semaine » est un temps plein : le signaler
                # comme temps partiel serait faux.
                value = False
            else:
                value = f"{hours} h/week"
        else:
            value = True
    elif condition_type == "training_budget":
        amount_match = _AMOUNT_RE.search(candidate.quote)
        if amount_match is not None:
            value = _amount_value(amount_match.group(0))
        else:
            value = True
    elif condition_type in {"remote", "hybrid", "onsite"}:
        if _is_negated(text, candidate.start):
            value = False

    return ConditionFact(
        condition_type=condition_type,
        value=value,
        source_field=source_field,
        quote=candidate.quote.strip(),
        start_offset=candidate.start,
        end_offset=candidate.end,
        confidence=confidence,
        contradictions=[],
    )


def _add_contradiction(fact: ConditionFact, token: str) -> None:
    if token not in fact.contradictions:
        fact.contradictions.append(token)


def _has_internal_conflict(condition_type: str, group: list[ConditionFact]) -> bool:
    """Indique si deux faits du même type se contredisent.

    ``True`` est compatible avec toute valeur précise : « hybride » et
    « hybride 3 jours par semaine » ne se contredisent pas.  En revanche
    ``True`` et ``False`` du même type sont incompatibles (télétravail /
    pas de télétravail, temps partiel / volume temps plein).
    """
    values = {fact.value for fact in group}
    if condition_type == "remote":
        return len({value for value in values if isinstance(value, bool)}) > 1
    if condition_type == "part_time":
        booleans = {value for value in values if isinstance(value, bool)}
        precise = {value for value in values if not isinstance(value, bool)}
        if len(booleans) > 1:
            return True
        if False in booleans and precise:
            return True
        return len(precise) > 1
    return len({value for value in values if value is not True and value is not None}) > 1


def _refine_facts(facts: list[ConditionFact]) -> list[ConditionFact]:
    """Supprime les faits redondants ou moins précis.

    - Une mention vague (``hybrid``) est remplacée par la mention précise
      (``3 days/week``) : la précision gagne, la citation la plus longue
      est conservée.
    - Deux mentions de même valeur ne sont comptées qu'une fois.

    Les oppositions (``True`` / ``False``) ne sont **jamais** fusionnées :
    elles doivent rester visibles pour être signalées comme contradiction.
    """
    grouped: dict[tuple[str, str], list[ConditionFact]] = {}
    for fact in facts:
        grouped.setdefault((fact.source_field, fact.condition_type), []).append(fact)

    kept: list[ConditionFact] = []
    for group in grouped.values():
        precise = [
            fact for fact in group
            if isinstance(fact.value, (str, int)) and not isinstance(fact.value, bool)
        ]
        candidates = precise or group
        best: dict[Any, ConditionFact] = {}
        for fact in candidates:
            current = best.get(fact.value)
            if current is None or len(fact.quote) > len(current.quote):
                best[fact.value] = fact
        kept.extend(best.values())
    return kept


def _apply_contradictions(facts: list[ConditionFact]) -> list[ConditionFact]:
    """Relève les contradictions internes et croisées entre les faits.

    Deux statements incompatibles ne sont jamais fusionnés : les deux faits
    restent visibles et portent un jeton de contradiction.
    """
    facts = _refine_facts(facts)
    by_type: dict[str, list[ConditionFact]] = {}
    for fact in facts:
        by_type.setdefault(fact.condition_type, []).append(fact)

    # ── Conflits à l'intérieur d'un même type ──────────────────────────
    for condition_type, group in by_type.items():
        if len(group) < 2:
            continue
        if _has_internal_conflict(condition_type, group):
            for fact in group:
                fact.confidence = "ambiguous"
                _add_contradiction(fact, f"{condition_type}_conflict")

    remotes = by_type.get("remote", [])
    hybrids = by_type.get("hybrid", [])
    onsites = by_type.get("onsite", [])
    remote_true = [fact for fact in remotes if fact.value is True]
    remote_false = [fact for fact in remotes if fact.value is False]
    onsite_true = [fact for fact in onsites if fact.value is True]

    if remote_true and onsite_true:
        for fact in remote_true + onsite_true:
            _add_contradiction(fact, "remote_vs_onsite")
    if remote_true and hybrids:
        for fact in remote_true + hybrids:
            _add_contradiction(fact, "remote_vs_hybrid")
    if remote_false and hybrids:
        for fact in remote_false + hybrids:
            _add_contradiction(fact, "remote_negated_vs_hybrid")
    if onsite_true and hybrids:
        for fact in onsite_true + hybrids:
            _add_contradiction(fact, "onsite_vs_hybrid")

    facts.sort(key=_fact_sort_key)
    return facts


def _field_rank(source_field: str) -> int:
    """Rang d'un champ source dans :data:`OFFER_SOURCE_FIELDS`."""
    try:
        return OFFER_SOURCE_FIELDS.index(source_field)
    except ValueError:
        return len(OFFER_SOURCE_FIELDS)


def _fact_sort_key(fact: ConditionFact) -> tuple[int, int, str]:
    """Ordre de lecture des faits : champ d'abord, puis position dans le texte."""
    return (_field_rank(fact.source_field), fact.start_offset, fact.condition_type)


# ───────────────────────────────────────────────────────────────────────
# API publique
# ───────────────────────────────────────────────────────────────────────


def extract_conditions(
    text: str,
    lang: str = "auto",
    *,
    source_field: str = "description_original",
) -> list[ConditionFact]:
    """Extrait les conditions de travail écrites dans un texte.

    Fonction **pure et déterministe** : pas de réseau, pas de modèle, pas
    d'écriture disque.  Le même texte produit toujours la même liste.

    Args:
        text: Texte libre (typiquement ``description_original`` d'une offre).
        lang: ``"auto"`` (détection) ou un code de :data:`SUPPORTED_LANGUAGES`.
            La langue ne **filtre** rien : elle fixe seulement l'ordre de
            priorité des motifs, une annonce bilingue reste analysée
            entièrement.
        source_field: Nom du champ d'origine reported dans les faits.

    Returns:
        Les faits trouvés, triés par position dans le texte.  Une liste vide
        signifie « le texte ne dit rien » — jamais « aucune condition ».

    Raises:
        ValueError: Si ``lang`` n'est ni ``"auto"`` ni une langue supportée.
    """
    if lang != "auto":
        normalized = str(lang).strip().lower()
        if normalized not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Langue non supportée : {lang!r} (attendu 'auto' ou l'un de {SUPPORTED_LANGUAGES})."
            )
        lang = normalized

    if not text or not text.strip():
        return []

    primary = detect_language(text) if lang == "auto" else lang
    candidates = _collect_candidates(text, primary)
    facts = [_build_fact(candidate, text, source_field) for candidate in candidates]
    return _apply_contradictions(facts)


def _field_text(value: Any) -> str:
    """Normalise un champ d'offre en texte exploitable."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_field_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_field_text(item)}" for key, item in value.items())
    return str(value)


def extract_conditions_from_offer(
    offer: dict[str, Any],
    lang: str = "auto",
) -> list[ConditionFact]:
    """Extrait les conditions de travail d'une offre, tous champs confondus.

    Chaque champ candidat est analysé séparément (les offsets sont donc
    relatifs au champ lu), puis les faits sont rapprochés : une contradiction
    entre deux champs différents — « Remote » dans la description, « Onsite »
    dans les métadonnées — est tracée comme telle.

    Args:
        offer: Offre normalisée (dict).
        lang: ``"auto"`` ou un code de :data:`SUPPORTED_LANGUAGES`.

    Returns:
        Les faits trouves, triés par champ puis par position.
    """
    if not isinstance(offer, dict):
        raise TypeError("offer must be an object")

    facts: list[ConditionFact] = []
    for source_field in OFFER_SOURCE_FIELDS:
        text = _field_text(offer.get(source_field))
        if not text.strip():
            continue
        facts.extend(extract_conditions(text, lang, source_field=source_field))

    return _apply_contradictions(facts)


def summarize_conditions(facts: list[ConditionFact]) -> dict[str, Any]:
    """Résume une liste de faits en un aperçu lisible et sérialisable.

    Args:
        facts: Faits issus de :func:`extract_conditions`.

    Returns:
        Un dict ``{"types": [...], "by_type": {...}, "contradictions": [...]}``.
    """
    by_type: dict[str, Any] = {}
    for fact in facts:
        by_type.setdefault(fact.condition_type, []).append(fact.value)
    return {
        "types": [fact.condition_type for fact in facts],
        "by_type": by_type,
        "contradictions": sorted({token for fact in facts for token in fact.contradictions}),
        "groups": sorted({fact.group for fact in facts}),
    }


__all__ = [
    "CONDITION_GROUPS",
    "ConditionFact",
    "ConditionType",
    "Confidence",
    "MAX_FACTS_PER_TYPE",
    "OFFER_SOURCE_FIELDS",
    "PART_TIME_MAX_HOURS",
    "SUPPORTED_LANGUAGES",
    "detect_language",
    "extract_conditions",
    "extract_conditions_from_offer",
    "summarize_conditions",
]
