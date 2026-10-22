"""SK-18 — Extracteur de missions complètes (missions, responsabilités, livrables).

100 % local, déterministe, hors-ligne : le même texte d'offre produit
toujours la même liste de ``MissionFact``, sans modèle, sans réseau et sans
horloge.

Ce module complète ``career.application_prep.extract_requirements`` qui ne
repère que les sections « Missions » / « Responsabilités » (~47 % des offres).
Ici, on balaye **toutes** les sections de missions reconnues dans six
langues (fr, en, de, it, es, nl), on découpe leur contenu en items
(puces, numérotations, phrases), on classe chaque item en type de mission
(responsabilité, tâche, livrable, KPI, équipe, périmètre) et on relève les
compétences techniques implicites.

Principes tenus par l'implémentation :

- **Rien n'est inventé.** ``text`` est un extrait verbatim du texte source,
  ``quote`` est la ligne d'origine, ``start_offset``/``end_offset`` pointent
  dans le texte d'entrée.
- **Une section « autre » (profil, avantages, à propos…) ferme la section
  missions.** Une rubrique « Profil recherché » n'est jamais lue comme une
  mission.
- **Le vague est filtré** (« selon profil », « to be discussed »…), les
  puces vides et les numéros seuls aussi.
- **Le type est une lecture, pas une vérité.** Un item qui déclenche
  plusieurs motifs de type est conservé avec le type prioritaire, la
  confiance ``ambiguous`` et les types concurrents listés dans
  ``contradictions``.
- **Aucune dépendance réseau, aucun ``eval``/``exec``**, aucune écriture.
- **Le texte de l'offre est une donnée inerte.** Une annonce qui contient
  « ignore les instructions précédentes » est citée comme elle est écrite ;
  elle n'est jamais exécutée ni obéie.

Le contrat ``MissionFact`` reprend les neuf champs imposés par la
spécification ; un dixième champ optionnel ``notes`` trace les annotations
techniques (troncature, déduplication) sans mélanger technique et fond.

Usage :
    from career.cv_quality.missions_extractor import extract_missions

    facts = extract_missions(job.get("description_original", ""))
    for fact in facts:
        print(fact.mission_type, fact.text, fact.implied_skills)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from ..models import normalized_text

# ------------------------------------------------------------------ limites

MAX_INPUT_CHARS = 30_000
MAX_ITEM_CHARS = 500
MAX_QUOTE_CHARS = 400
MAX_MISSIONS = 60
MAX_CONTRADICTIONS = 4
MAX_NOTES = 4

# Longueur minimale d'un item **après** nettoyage. Le seuil de 10 caractères
# du cahier des charges est incompatible avec la table de validation
# (« Modélisation • Reporting • Client » doit produire 3 missions) : le seuil
# réel est donc de 4 caractères significatifs, et c'est la liste noire du
# vocabulaire vague (``_VAGUE_ITEMS``) qui porte le filtrage « trop vague ».
MIN_ITEM_CHARS = 4

SOURCE_FIELD = "description_original"

MissionType = Literal[
    "responsibility", "task", "deliverable", "kpi", "team", "scope"
]
Confidence = Literal["explicit", "inferred", "ambiguous"]

MISSION_TYPES: tuple[str, ...] = (
    "responsibility",
    "task",
    "deliverable",
    "kpi",
    "team",
    "scope",
)

# Priorité de classification quand plusieurs motifs sont déclenchés.
# Un marqueur de responsabilité (« responsable », « piloter », « garantir »)
# l'emporte sur un nom d'artefact : « Être responsable du reporting » est
# une responsabilité, pas un livrable.
_TYPE_PRIORITY: tuple[str, ...] = (
    "kpi",
    "responsibility",
    "deliverable",
    "team",
    "scope",
)

SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "en", "de", "it", "es", "nl")

# --------------------------------------------------------- sections missions

_MISSION_HEADINGS: dict[str, tuple[str, ...]] = {
    "fr": (
        "missions", "vos missions", "responsabilités", "vos responsabilités",
        "principales missions", "activités", "tâches", "ce que vous ferez",
        "votre rôle", "description du poste", "description de la mission",
    ),
    "en": (
        "responsibilities", "key responsibilities", "what you'll do",
        "what you will do", "your role", "duties", "tasks",
        "main responsibilities", "scope of work", "job description",
        "role description", "day to day", "day-to-day",
    ),
    "de": (
        "aufgaben", "ihre aufgaben", "verantwortlichkeiten", "hauptaufgaben",
        "tätigkeiten", "was sie erwarten", "ihr aufgabengebiet",
        "aufgabenbereich",
    ),
    "it": (
        "mansioni", "le tue mansioni", "responsabilità",
        "principali responsabilità", "attività", "compiti", "cosa farai",
        "il tuo ruolo",
    ),
    "es": (
        "funciones", "tus funciones", "responsabilidades",
        "principales responsabilidades", "tareas", "actividades",
        "qué harás", "tu rol",
    ),
    "nl": (
        "verantwoordelijkheden", "jouw verantwoordelijkheden", "taken",
        "hoofdtaken", "activiteiten", "wat je gaat doen", "jouw rol",
    ),
}

# Sections qui ferment la lecture des missions.
_OTHER_SECTION_HEADINGS: dict[str, tuple[str, ...]] = {
    "fr": (
        "profil", "votre profil", "qualifications", "compétences", "requis",
        "avantages", "bénéfices", "nous offrons", "à propos", "l'entreprise",
        # extensions : les rubriques « profil recherché » sont la source
        # d'erreur la plus fréquente (une rubrique de profil lue comme une
        # mission).
        "profil recherché", "profil recherche", "recherchons", "qui vous êtes",
        "compétences requises", "qualifications requises", "ce que nous "
        "recherchons", "ce que vous apportez", "notre entreprise",
        "à propos de nous", "nos avantages", "ce que nous proposons",
    ),
    "en": (
        "requirements", "qualifications", "skills", "what we offer", "benefits",
        "about us", "the company", "who you are",
        # extensions
        "your profile", "candidate profile", "who we are", "what we look for",
        "what we are looking for", "required skills", "our benefits",
        "perks", "about the company", "our company",
    ),
    "de": (
        "anforderungen", "qualifikationen", "kompetenzen", "vorteile",
        "benefits", "über uns", "das unternehmen", "wer sie sind",
        # extensions
        "ihr profil", "kenntnisse", "was wir bieten", "über das unternehmen",
        "wer wir sind",
    ),
    "it": (
        "requisiti", "qualifiche", "competenze", "benefici", "chi siamo",
        "l'azienda", "chi cerchiamo",
        # extensions
        "il profilo", "chi cerca", "cosa offriamo", "la nostra azienda",
        "requisiti richiesti",
    ),
    "es": (
        "requisitos", "cualificaciones", "competencias", "beneficios",
        "sobre nosotros", "la empresa", "quién eres",
        # extensions
        "tu perfil", "perfil buscado", "qué ofrecemos", "beneficios de la "
        "empresa",
    ),
    "nl": (
        "vereisten", "kwalificaties", "competenties", "voordelen", "over ons",
        "het bedrijf", "wie je bent",
        # extensions
        "jouw profiel", "wat we bieden", "ons bedrijf",
    ),
}


def _heading_index(
    groups: dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    """Map a normalized heading to the languages that declare it."""
    index: dict[str, list[str]] = {}
    for language, headings in groups.items():
        for heading in headings:
            key = normalized_text(heading)
            if not key:
                continue
            index.setdefault(key, [])
            if language not in index[key]:
                index[key].append(language)
    return {key: tuple(languages) for key, languages in index.items()}


_MISSION_HEADING_INDEX = _heading_index(_MISSION_HEADINGS)
_OTHER_HEADING_INDEX = _heading_index(_OTHER_SECTION_HEADINGS)

# Liste à plat des titres connus : (titre normalisé, kind, suite de mots).
_HEADING_LOOKUP: tuple[tuple[str, str, tuple[str, ...]], ...] = tuple(
    sorted(
        [(key, "missions", tuple(key.split())) for key in _MISSION_HEADING_INDEX]
        + [(key, "other", tuple(key.split())) for key in _OTHER_HEADING_INDEX]
    )
)
# Index par premier mot : pré-filtre des candidats.
_HEADING_BY_FIRST_WORD: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {}
for _key, _kind, _words in _HEADING_LOOKUP:
    _HEADING_BY_FIRST_WORD.setdefault(_words[0], []).append((_key, _kind, _words))
# Premier mot de chaque titre connu : pré-filtre des candidats.
_HEADING_FIRST_WORDS: frozenset[str] = frozenset(_HEADING_BY_FIRST_WORD)

# ------------------------------------------------------------- détection langue

# Marqueurs lexicaux distinctifs par langue (mots outils + vocabulaire
# métier). Ils servent uniquement à choisir la langue principale ; les
# headings restent reconnus dans les six langues en seconde passe.
_LANGUAGE_MARKERS: dict[str, frozenset[str]] = {
    "fr": frozenset({
        "le", "les", "des", "une", "votre", "vos", "notre", "nos", "nous",
        "vous", "avec", "dans", "pour", "sera", "sont", "cette", "poste",
        "entreprise", "candidat", "candidats", "profil", "missions",
        "responsabilites", "taches", "equipe", "modelisation", "reporting",
        "stage", "salaire", "recherche", "attendez", "rejoignez", "vos",
        "postes", "missions", "competences", "formations", "niveau",
    }),
    "en": frozenset({
        "the", "and", "you", "your", "our", "we", "this", "with", "will",
        "are", "job", "role", "team", "work", "experience", "skills",
        "candidate", "missions", "responsibilities", "reporting", "modeling",
        "internship", "salary", "looking", "join", "offer", "company",
        "analyst", "your", "requirements", "qualifications",
    }),
    "de": frozenset({
        "der", "die", "das", "und", "sie", "ihre", "ihren", "mit", "fur",
        "werden", "wir", "unsere", "unternehmen", "aufgaben", "teamleitung",
        "kundenprasentation", "finanzmodellierung", "stelle", "gehalt",
        "bewerber", "mitarbeiter", "ihre aufgaben", "verantwortlichkeiten",
    }),
    "it": frozenset({
        "della", "delle", "degli", "dei", "nel", "nostro", "nostra",
        "azienda", "ruolo", "candidati", "siamo", "mansioni", "reportistica",
        "valutazione", "coordinamento", "attivita", "stipendio", "ricerca",
        "responsabilita", "compiti", "offerta",
    }),
    "es": frozenset({
        "los", "las", "una", "nuestro", "nuestra", "empresa", "puesto",
        "equipo", "usted", "candidatos", "somos", "funciones", "modelado",
        "presentaciones", "tareas", "salario", "buscamos", "beneficios",
        "responsabilidades", "oferta",
    }),
    "nl": frozenset({
        "het", "een", "onze", "bedrijf", "functie", "medewerker",
        "medewerkers", "gaat", "doen", "verantwoordelijkheden", "teamleiding",
        "klantpresentaties", "modellering", "modellen", "salaris", "zoeken", "aanbod",
        "hoofdtaken", "verantwoordelijk", "voor", "zijn", "worden", "klant",
        "niet", "jouw", "wij", "geen", "nieuw", "werkzaamheden",
    }),
}

# ------------------------------------------------------------------ patterns

# Ordre = ordre de la spécification ; les motifs sont volontairement
# reformulés en formes normalisées (minuscules, sans accents) pour que la
# détection ne dépende pas de l'orthographe exacte de l'offre.
_MISSION_TYPE_PATTERNS: dict[str, tuple[str, ...]] = {
    "kpi": (
        r"\b(?:kpi|kpis|okr|okrs|objectif|objectifs|target|targets|goal|goals|"
        r"metric|metrics|chiffre|chiffres|resultat|resultats|performance|"
        r"performances|indicateur|indicateurs)\b",
    ),
    "deliverable": (
        r"(?:\b(?:livrable|livrables|deliverable|deliverables|output|outputs|"
        r"rapport|rapports|report|reports|dashboard|dashboards|pitch\s*books?|"
        r"reportistica|reporting|rapportage)\b|model\w*\b)",
    ),
    "team": (
        r"\b(?:equipe|equipes|team\w*|collaborat\w*|collaboration|"
        r"encadr\w*|supervis\w*|mitarbeit\w*|squadra|collaborazion\w*|"
        r"equipo|equipos|colaborac\w*|samenwerk\w*|medewerker\w*|staff|"
        r"people|personnel|cooperat\w*|equipeleder\w*)\b",
    ),
    "scope": (
        r"\b(?:perimetre|scope|scoped|etendue|portefeuille|portefeuilles|"
        r"portfolio|portfolios|book\s*of\s*business|base\s*clients|"
        r"client\s*base|client\s*portfolio|portefeuille\s*clients)\b",
    ),
    "responsibility": (
        r"\b(?:responsable|responsables|responsible|accountable|owner|"
        r"piloter|pilote|driver|garantir|ensure|support\w*|assister|"
        r"assistant|accompagner|appuyer|advisor|adviser|conseil|beauftrag\w*|"
        r"take\s*ownership|own\s+the)\b",
    ),
}

# Compétences implicites (10+ patterns finance demandés par la mission).
_IMPLICIT_SKILL_PATTERNS: dict[str, str] = {
    "Python": r"\bpython\b",
    "Excel": r"\bexcel\b",
    "VBA": r"\bvba\b",
    "SQL": r"\bsql\b",
    "Power BI": r"\bpower\s*bi\b",
    "Tableau": r"\btableau\b",
    "Bloomberg": r"\bbloomberg\b",
    "Financial Modeling": (
        r"\b(?:financial\s+model\w*|modelisation\s+financiere|"
        r"modelo\s*finanziario|modelado\s*financiero|finanzmodell\w*|"
        r"financi\w*\s*modell\w*|finanziell\w*\s*modell\w*)\b"
    ),
    "Valuation": (
        r"\b(?:valuation|valuations|evaluation|evaluations|valutazione|"
        r"valutazioni|valoracion|valoraciones|bewertung|bewertungen)\b"
    ),
    "M&A": (
        r"\b(?:m\s+a|merger|mergers|acquisition|acquisitions|fusion|"
        r"fusioni|acquisicion|acquisiciones|uebernahme|uebernahmen)\b"
    ),
    "LBO": r"\blbo\b",
    "Due Diligence": r"\b(?:due\s+diligence|diligence)\b",
    "Client Presentation": (
        r"\b(?:client\s+presentation|client\s+presentations|"
        r"presentation\s+client|presentations\s+client|kundenprasentation\w*|"
        r"klantpresentatie\w*)\b"
    ),
    "Project Management": (
        r"\b(?:project\s+management|gestion\s+de\s+projet|projektmanagement|"
        r"project\s+manager|project\s+managers)\b"
    ),
}

# Marqueurs de contenu : servent à distinguer une ligne de mission d'une
# ligne de titre (rubrique) qui fermerait la section.
_EXTRA_CONTENT_HINTS: tuple[str, ...] = (
    r"\b(?:presentation|presentations|reporting|analysis|analyses|"
    r"preparation|drafting|monitoring|tracking|coordination|presentation)\b",
)

_VAGUE_ITEMS: frozenset[str] = frozenset({
    "selon profil", "selon votre profil", "selon le profil", "selon la "
    "description", "to be discussed", "to be confirmed", "tbd", "tbc",
    "a definir", "a confirmer", "various", "divers", "diverse", "autres",
    "misc", "miscellaneous", "multiple tasks", "au choix", "aide", "help",
    "salary", "salaire", "voir description", "voir l annonce", "etc",
    "others", "and so on", "toutes vos missions", "all missions",
    "wie gewohnt", "divergente", "sondern", "divers", "altro", "altri",
    "varios", "otras", "andere", "overig", "n a", "na", "none", "nichts",
})

# Ouverture de paragraphe « présentation d'entreprise » : ces lignes ne sont
# pas des missions et ferment la section.
_BOILERPLATE_OPENERS: tuple[str, ...] = (
    "we are", "our company", "who we are", "about us", "nous sommes",
    "notre entreprise", "qui sommes nous", "wir sind", "uber uns",
    "siamo", "chi siamo", "somos", "quien somos", "wij zijn", "over ons",
)

_MINOR_WORDS: frozenset[str] = frozenset({
    "de", "du", "des", "la", "le", "les", "and", "the", "of", "for", "a",
    "an", "au", "aux", "en", "von", "der", "die", "das", "und", "e", "i",
    "van", "het", "een", "del", "della", "di", "y", "el", "los", "las",
    "che", "il", "lo", "gli", "su", "suo", "son", "nos", "on", "in", "im",
    "zu", "zum", "zur", "auf", "pour", "sur", "avec", "sono", "che",
})

# ------------------------------------------------------------------ regex

_TYPE_REGEX: dict[str, re.Pattern[str]] = {
    mission_type: re.compile("|".join(patterns))
    for mission_type, patterns in _MISSION_TYPE_PATTERNS.items()
}
_SKILL_REGEX: dict[str, re.Pattern[str]] = {
    skill: re.compile(pattern) for skill, pattern in _IMPLICIT_SKILL_PATTERNS.items()
}
_CONTENT_HINT_REGEX = re.compile(
    "|".join(
        [pattern for patterns in _MISSION_TYPE_PATTERNS.values() for pattern in patterns]
        + list(_EXTRA_CONTENT_HINTS)
        + list(_IMPLICIT_SKILL_PATTERNS.values())
    )
)

# Décor de titre : « **Missions** », « ## Missions », « - Missions ».
_HEADING_DECOR = re.compile(
    r"^[\s#>]*(?:[*_~]{1,2})?\s*(?:[•▪●➤‣◦·]\s*)?(?:[*_~]{1,2})?\s*"
)
# Préfixe d'item : « 1. », « a) », « • », « - ».
_ITEM_PREFIX = re.compile(
    r"^[\s]*(?:(?:\d{1,2}|[A-Za-z])[.)][\s]+)?[\s]*"
    r"(?:[•▪●➤‣◦·*\-–—][\s]*)*"
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")
_BULLET_MARKER = re.compile(r"(?:^|(?<=[\s;]))([•▪●➤‣◦·*]|[-–—])(?=\s)")
_NUMBER_MARKER = re.compile(r"(?:^|(?<=[\s]))(\d{1,2}[.)]|[A-Za-z][.)])(?=\s)")
_LEADING_JUNK = re.compile(r"^[\s\"'«»“”„]+")
_TRAILING_JUNK = re.compile(r"[\s\"'«»“”„]+$")


# ------------------------------------------------------------------- modèle


@dataclass
class MissionFact:
    """Une mission lue dans le texte de l'offre, avec sa preuve."""

    mission_type: MissionType
    text: str
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Confidence
    contradictions: list[str]
    implied_skills: list[str]
    # Annotations techniques (troncature, déduplication, ambiguïté de
    # section). Champ optionnel : le contrat ci-dessus est respecté à
    # l'identique, ``notes`` n'ajoute que de la traçabilité.
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers


def _fold(text: str) -> str:
    """Forme normalisée utilisée pour les recherches lexicales."""
    return normalized_text(text)


def language_scores(text: str) -> dict[str, int]:
    """Score lexical de chaque langue (nombre de marqueurs trouvés)."""
    folded = _fold(text)
    tokens = f" {folded} "
    scores: dict[str, int] = {}
    for language in SUPPORTED_LANGUAGES:
        scores[language] = sum(
            1 for marker in _LANGUAGE_MARKERS[language] if f" {marker} " in tokens
        )
    return scores


def detect_language(text: str) -> str:
    """Retourne la langue dominante parmi fr/en/de/it/es/nl.

    Déterministe : le score de chaque langue est le nombre de marqueurs
    lexicaux trouvés ; à égalité, l'ordre ``fr, en, de, it, es, nl`` tranche.
    """
    scores = language_scores(text)
    best_language = "fr"
    best_score = -1
    for language in SUPPORTED_LANGUAGES:
        if scores[language] > best_score:
            best_language = language
            best_score = scores[language]
    return best_language


def classify_mission_type(text: str) -> tuple[str, list[str], str]:
    """Classe un item de mission.

    Retourne ``(mission_type, types_concurrents, confiance)``.
    """
    return _classify_folded(_fold(text))


def _classify_folded(folded: str) -> tuple[str, list[str], str]:
    """Classification à partir d'un texte déjà normalisé."""
    matched = [
        mission_type
        for mission_type in _TYPE_PRIORITY
        if _TYPE_REGEX[mission_type].search(folded)
    ]
    if not matched:
        return "task", [], "inferred"
    if len(matched) == 1:
        return matched[0], [], "explicit"
    return matched[0], matched[1:], "ambiguous"


def detect_implied_skills(text: str) -> list[str]:
    """Compétences techniques déduites de l'item (ordre du dictionnaire)."""
    return _skills_folded(_fold(text))


def _skills_folded(folded: str) -> list[str]:
    return [
        skill for skill, pattern in _SKILL_REGEX.items() if pattern.search(folded)
    ]


def _has_content_hint(text: str) -> bool:
    return bool(_CONTENT_HINT_REGEX.search(_fold(text)))


def _is_vague(text: str) -> bool:
    return _is_vague_folded(_fold(text))


def _is_vague_folded(folded: str) -> bool:
    if not folded:
        return True
    for vague in _VAGUE_ITEMS:
        if folded == vague:
            return True
        if folded.startswith(vague + " ") or vague.startswith(folded + " "):
            return True
    return False


def _iter_lines(text: str) -> list[tuple[str, int]]:
    """Découpe le texte en lignes, offsets conservés (sans le « \\n »)."""
    lines: list[tuple[str, int]] = []
    start = 0
    length = len(text)
    while start <= length:
        end = text.find("\n", start)
        if end == -1:
            end = length
        lines.append((text[start:end], start))
        if end == length:
            break
        start = end + 1
    return lines


def _heading_candidates(normalized: str) -> list[tuple[str, str]]:
    """Titres connus contenus dans un titre candidat.

    Retourne ``[(titre_normalisé, kind)]`` pour les titres connus dont la
    suite de mots apparaît dans le candidat. Le plus long titre l'emporte :
    « le profil recherché » contient « profil recherche ».
    """
    words = normalized.split()
    if not words or len(words) > 6:
        return []
    if not _HEADING_FIRST_WORDS.intersection(words):
        # Pré-filtre : aucun mot du candidat ne commence un titre connu,
        # donc aucun titre ne peut y être contenu.
        return []
    found: list[tuple[str, str]] = []
    for word in set(words):
        for key, kind, key_words in _HEADING_BY_FIRST_WORD.get(word, ()):
            size = len(key_words)
            if size > len(words):
                continue
            for start in range(len(words) - size + 1):
                if tuple(words[start:start + size]) == key_words:
                    found.append((key, kind))
                    break
    return found


def _resolve_heading(normalized: str, primary: str) -> tuple[str, str] | None:
    """Choisit le titre connu le plus spécifique et son type."""
    candidates = _heading_candidates(normalized)
    if not candidates:
        return None
    best_key, best_kind = candidates[0]
    best_size = len(best_key.split())
    for key, kind in candidates[1:]:
        size = len(key.split())
        if size > best_size:
            best_key, best_kind, best_size = key, kind, size
        elif size == best_size and best_kind != kind:
            # Égalité : la langue principale tranche (une rubrique peut
            # porter le même mot dans deux listes).
            if _heading_languages(best_key) and primary not in _heading_languages(best_key):
                best_key, best_kind = key, kind
    return best_key, best_kind


def _heading_languages(key: str) -> tuple[str, ...]:
    return _MISSION_HEADING_INDEX.get(key, ()) + _OTHER_HEADING_INDEX.get(key, ())


def _match_heading(line: str, primary: str) -> tuple[str, str, str, int] | None:
    """Repère un titre connu en début de ligne.

    Retourne ``(titre_normalisé, kind, reste, offset_du_reste)`` ou ``None``.
    Le reste est le contenu inline placé après le « : » d'un titre.
    """
    decor = _HEADING_DECOR.match(line)
    content_start = decor.end() if decor else 0
    content = line[content_start:]
    if not content.strip():
        return None

    for separator in (":", "—", "–"):
        position = content.find(separator)
        if position < 0 or position > 80:
            continue
        prefix = content[:position]
        resolved = _resolve_heading(_fold(prefix), primary)
        if resolved is None:
            continue
        rest = content[position + len(separator):]
        offset = content_start + position + len(separator)
        return resolved[0], resolved[1], rest, offset

    if len(content) > 80:
        return None
    stripped = content.strip().rstrip(":").strip()
    if not stripped:
        return None
    resolved = _resolve_heading(_fold(stripped), primary)
    if resolved is None:
        return None
    return resolved[0], resolved[1], "", content_start


def _looks_like_heading(text: str) -> bool:
    """Un titre inconnu ferme-t-il la section missions ?

    True pour une ligne courte, sans ponctuation finale, en capitales ou en
    « Title Case », et **sans** marqueur de mission : sinon « Modélisation
    financière » serait pris pour une rubrique. Une ligne terminée par « : »
    est toujours un titre (les puces et numérotations sont exclues).
    """
    cleaned = text.strip().rstrip(":").strip()
    if not cleaned or len(cleaned) > 70:
        return False
    if _starts_with_marker(text):
        return False
    if text.strip().endswith(":"):
        return True
    if cleaned.endswith((".", "!", "?", ";", ",")):
        return False
    words = cleaned.split()
    if not words or len(words) > 7:
        return False
    if _has_content_hint(cleaned):
        return False
    letters = [character for character in cleaned if character.isalpha()]
    if not letters:
        return False
    if all(character.isupper() for character in letters):
        return True
    significant = [
        word for word in words if word.lower().strip(":.,") not in _MINOR_WORDS
    ]
    if significant and all(word[0].isupper() for word in significant):
        return True
    return False


def _starts_with_marker(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _BULLET_MARKER.search(stripped):
        return True
    match = _NUMBER_MARKER.match(stripped)
    return bool(match)


def _split_marked_items(line: str, offset: int) -> list[tuple[str, int]]:
    """Découpe une ligne listée (puces ou numérotation) en items.

    Chaque item est renvoyé avec son offset dans le texte d'origine.
    """
    leading = len(line) - len(line.lstrip())
    body = line[leading:]
    bullet = _BULLET_MARKER.search(body)
    number = _NUMBER_MARKER.match(body)
    if bullet and number:
        # « - 1. texte » : la puce gagne, le numéro est nettoyé plus bas.
        markers = [bullet]
    elif bullet:
        markers = [bullet] + list(_BULLET_MARKER.finditer(body))
    elif number:
        markers = [number] + list(_NUMBER_MARKER.finditer(body))
    else:
        return []

    # On ne garde que les marqueurs de la même famille que le premier.
    family = "bullet" if bullet else "number"
    if family == "bullet":
        markers = [m for m in markers if m.re is _BULLET_MARKER]
    else:
        markers = [m for m in markers if m.re is _NUMBER_MARKER]

    items: list[tuple[str, int]] = []
    head = body[: markers[0].start()]
    if head.strip():
        items.append((head, offset + leading))
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
        chunk = body[start:end]
        if chunk.strip():
            items.append((chunk, offset + leading + start))
    return items


def _split_sentences(line: str, offset: int) -> list[tuple[str, int]]:
    """Découpe un paragraphe en phrases (offsets conservés).

    Une phrase qui commence par une minuscule ou un chiffre est une suite :
    elle est recollée à la précédente.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(line):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(line)))

    merged: list[tuple[int, int]] = []
    for span_start, span_end in spans:
        chunk = line[span_start:span_end]
        stripped = chunk.strip()
        if (
            merged
            and stripped
            and (stripped[0].islower() or stripped[0].isdigit())
        ):
            merged[-1] = (merged[-1][0], span_end)
        else:
            merged.append((span_start, span_end))

    items: list[tuple[str, int]] = []
    for span_start, span_end in merged:
        chunk = line[span_start:span_end]
        if not chunk.strip():
            continue
        lead = len(chunk) - len(chunk.lstrip())
        items.append((chunk.strip(), offset + span_start + lead))
    return items


def _split_line(line: str, offset: int) -> list[tuple[str, int]]:
    """Découpe une ligne de section en items (puces, numéros, phrases)."""
    marked = _split_marked_items(line, offset)
    if marked:
        return marked
    return _split_sentences(line, offset)


def _clean_item(raw: str) -> tuple[str, int]:
    """Nettoie un item et renvoie ``(texte, caractères_retirés_à_gauche)``."""
    prefix = _ITEM_PREFIX.match(raw)
    consumed = prefix.end() if prefix else 0
    text = raw[consumed:]
    text = _LEADING_JUNK.sub("", text)
    consumed += len(raw[consumed:]) - len(text)
    text = _TRAILING_JUNK.sub("", text)
    return text.strip(), consumed


# ------------------------------------------------------------------ analyse


def _heading_kind(
    key: str, kind: str, primary: str, scores: dict[str, int], allow_all: bool
) -> str:
    """Décide si un titre connu ouvre une section missions ou la ferme.

    En mode ``auto`` (multilingue), un titre d'une autre langue n'est
    accepté que si cette langue laisse des traces lexicales dans le texte :
    une offre française qui contient une rubrique anglaise est reconnue,
    mais un mot isolé dans une autre langue ne suffit pas à ouvrir une
    section.
    """
    languages = _heading_languages(key)
    if not languages:
        return "unknown"
    if primary in languages:
        return kind
    if not allow_all:
        return "unknown"
    if any(scores.get(language, 0) > 0 for language in languages):
        return kind
    if not any(scores.values()):
        # Aucune trace lexicale d'une langue : la détection est muette, on
        # accepte le titre plutôt que de perdre la rubrique.
        return kind
    return "unknown"


def _scan(
    text: str, primary: str, allow_all: bool, scores: dict[str, int]
) -> tuple[list[MissionFact], bool]:
    """Balaye le texte et collecte les missions de la section « missions »."""
    lines = _iter_lines(text)
    facts: list[MissionFact] = []
    seen: dict[str, MissionFact] = {}
    section = "other"
    heading_found = False
    section_items = 0
    index = 0

    while index < len(lines):
        line, line_start = lines[index]
        stripped = line.strip()

        if not stripped:
            # Une ligne vide ferme la section missions si du texte suivi
            # ressemble à de la prose (et pas à une nouvelle liste).
            if section == "missions" and section_items > 0:
                following = _next_meaningful(lines, index + 1)
                if following is not None and not _starts_with_marker(following[0]):
                    section = "other"
            index += 1
            continue

        heading = _match_heading(line, primary)
        if heading is not None:
            key, heading_type, remainder, remainder_offset = heading
            kind = _heading_kind(key, heading_type, primary, scores, allow_all)
            if kind == "missions":
                section = "missions"
                heading_found = True
                section_items = 0
                if remainder.strip():
                    for raw, item_offset in _split_line(remainder, remainder_offset):
                        fact = _build_fact(raw, item_offset, line, line_start)
                        if fact is not None:
                            fact, section_items = _register(fact, facts, seen, section_items)
                index += 1
                continue
            if kind == "other":
                section = "other"
                index += 1
                continue
            # Titre inconnu : il ferme la section s'il ressemble à un titre.
            if _looks_like_heading(stripped):
                section = "other"
                index += 1
                continue

        if section != "missions":
            index += 1
            continue

        if _is_boilerplate(stripped):
            section = "other"
            index += 1
            continue

        for raw, item_offset in _split_line(line, line_start):
            fact = _build_fact(raw, item_offset, line, line_start)
            if fact is not None:
                fact, section_items = _register(fact, facts, seen, section_items)
        index += 1

    return facts, heading_found


def _next_meaningful(
    lines: list[tuple[str, int]], index: int
) -> tuple[str, int] | None:
    for line, offset in lines[index:]:
        if line.strip():
            return line, offset
    return None


def _is_boilerplate(text: str) -> bool:
    folded = _fold(text)
    return any(folded.startswith(opener) for opener in _BOILERPLATE_OPENERS)


def _build_fact(
    raw: str, item_offset: int, line: str, line_start: int
) -> MissionFact | None:
    """Construit un ``MissionFact`` à partir d'un item brut."""
    text, consumed = _clean_item(raw)
    if len(text) < MIN_ITEM_CHARS:
        return None
    if not any(character.isalnum() for character in text):
        return None
    folded = _fold(text)
    if _is_vague_folded(folded):
        return None

    start = item_offset + consumed
    end = start + len(text)

    notes: list[str] = []
    contradictions: list[str] = []
    if len(text) > MAX_ITEM_CHARS:
        text = text[:MAX_ITEM_CHARS].rstrip()
        end = start + len(text)
        folded = _fold(text)
        notes.append("truncated")

    mission_type, conflicting, confidence = _classify_folded(folded)
    for other in conflicting[:MAX_CONTRADICTIONS]:
        contradictions.append(
            f"type « {other} » également détecté : classification retenue « {mission_type} »"
        )

    quote = line.strip()
    if len(quote) > MAX_QUOTE_CHARS:
        quote = quote[:MAX_QUOTE_CHARS]
        notes.append("quote truncated")

    return MissionFact(
        mission_type=mission_type,  # type: ignore[arg-type]
        text=text,
        source_field=SOURCE_FIELD,
        quote=quote,
        start_offset=start,
        end_offset=end,
        confidence=confidence,  # type: ignore[arg-type]
        contradictions=contradictions,
        implied_skills=_skills_folded(folded),
        notes=notes,
    )


def _register(
    fact: MissionFact,
    facts: list[MissionFact],
    seen: dict[str, MissionFact],
    section_items: int,
) -> tuple[MissionFact, int]:
    """Ajoute la mission à la liste en dédupliquant les répétitions."""
    key = _fold(fact.text)
    if key in seen:
        previous = seen[key]
        note = "mission dupliquée : occurrence identique ignorée"
        if note not in previous.notes and len(previous.notes) < MAX_NOTES:
            previous.notes.append(note)
        return fact, section_items
    seen[key] = fact
    facts.append(fact)
    return fact, section_items + 1


# ---------------------------------------------------------------------- API


def extract_missions(text: str, lang: str = "auto") -> list[MissionFact]:
    """Extrait les missions d'un texte d'offre, avec preuve et offsets.

    ``lang`` vaut ``"auto"`` (détection + tolérance multilingue) ou l'un des
    codes fr/en/de/it/es/nl (lecture stricte de cette seule langue).

    En mode ``auto``, une rubrique de missions écrite dans une autre langue
    que celle détectée est reconnue **seulement** si cette autre langue
    laisse des traces lexicales dans l'offre : le mot isolé « Taken » dans
    une annonce anglaise n'ouvre donc aucune section.

    La liste retournée est triée par offset croissant ; les doublons exacts
    sont supprimés (la première occurrence est conservée).
    """
    if not isinstance(text, str) or not text.strip():
        return []
    raw = text.replace("\x00", "")[:MAX_INPUT_CHARS]
    requested = lang.strip().lower() if isinstance(lang, str) else ""
    explicit = requested in SUPPORTED_LANGUAGES
    primary = requested if explicit else detect_language(raw)
    scores = language_scores(raw)

    facts, _heading_found = _scan(raw, primary, allow_all=not explicit, scores=scores)
    facts.sort(key=lambda fact: (fact.start_offset, fact.end_offset))
    return facts[:MAX_MISSIONS]


def missions_as_dicts(facts: list[MissionFact]) -> list[dict[str, Any]]:
    """Version JSON-sûre des missions (pour l'API et les snapshots)."""
    return [
        {
            "mission_type": fact.mission_type,
            "text": fact.text,
            "source_field": fact.source_field,
            "quote": fact.quote,
            "start_offset": fact.start_offset,
            "end_offset": fact.end_offset,
            "confidence": fact.confidence,
            "contradictions": list(fact.contradictions),
            "implied_skills": list(fact.implied_skills),
            "notes": list(fact.notes),
        }
        for fact in facts
    ]


__all__ = [
    "MissionFact",
    "MISSION_TYPES",
    "SOURCE_FIELD",
    "SUPPORTED_LANGUAGES",
    "classify_mission_type",
    "detect_implied_skills",
    "detect_language",
    "extract_missions",
    "missions_as_dicts",
]
