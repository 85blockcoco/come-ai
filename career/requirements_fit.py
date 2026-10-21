"""Adéquation exigences d'une offre ↔ profil approuvé (SPEC SK-03 / CVBOOST-24).

Ce module **ne réinvente pas l'extraction des exigences**. Il consomme le
contrat canonique ``career.offer_requirements.analyze_offer()`` — chaque
énoncé avec son texte exact, sa provenance et sa modalité — et confronte
chacune de ces exigences aux **faits approuvés** du profil candidat.

WHAT IT DOES
------------
- one verdict per canonical requirement: ``supported`` / ``unsupported`` /
  ``contradicted`` / ``to_verify`` / ``not_applicable``;
- the modality of the canonical contract is preserved and translated:
  ``required`` → ``mandatory``, ``preferred`` / ``contextual`` / ``unknown``
  are kept as-is;
- nine mandatory fit categories are reachable: ``etudes``, ``experience``,
  ``tech``, ``outils``, ``langues``, ``mobilite``, ``auth_travail``,
  ``dispo``, ``diplomation`` (plus ``other`` for statements the canonical
  contract does not classify);
- every match is a **cross citation**: the exact offer wording
  (``requirement_text``) plus the exact approved profile excerpt
  (``profile_evidence``) and its offset in the profile (``evidence_offset``).

NON-NEGOTIABLE RULES
---------------------
1. *Absent ≠ incompatible.*  A requirement whose proof is missing from the
   profile is ``to_verify`` — never ``unsupported``.  ``unsupported`` is
   reserved for a **proven shortfall** (the profile proves less than the
   offer demands).
2. *"Master preferred" never rejects.*  A level preference (``preferred``
   modality) met by a lower approved level stays ``to_verify``: it never
   becomes ``unsupported`` nor ``contradicted``.
3. *"Master 2 required" is handled on its own.*  A mandatory level
   requirement is compared with the approved level ladder and reported with
   its own wording; it is never merged into the generic education match.
4. *Non-approved OCR is not evidence.*  Only facts whose status is
   ``approved`` or ``modified`` count.  ``proposed``, ``rejected`` and
   ``suspended`` facts are invisible to the matcher, and an OCR result is
   never approved implicitly.
5. *Cross citations.*  Every ``supported`` (and every ``contradicted``)
   quotes the offer statement **and** the approved profile fact.
6. *Isolation.*  ``analyze_fit`` never mutates the offer and never writes
   profile data into the offer snapshot: the public offer stays public.

TRUST RULES
-----------
- The offer text is untrusted data, never an instruction: a statement flagged
  as an injection suspect by the canonical contract is reported as
  ``not_applicable`` and never treated as a requirement to satisfy.
- A negated statement ("no management experience required") carries no
  obligation: it is reported as ``not_applicable`` with the ``contextual``
  modality of the canonical contract.
- Pure, deterministic, offline: no clock, no randomness, no network, no
  model.  The same offer and the same profile always give the same result,
  in the same order.

VERDICTS
--------
======================  ====================================================
verdict                 meaning
======================  ====================================================
``supported``           exact proof found in the approved profile
``unsupported``         the profile proves less than the offer demands
``contradicted``        the profile explicitly contradicts the requirement
``to_verify``           the information is absent from the profile
``not_applicable``      the statement carries no obligation for this profile
======================  ====================================================

SCORE
-----
``overall_score`` is a 0–1 ratio of modality-weighted verdicts:
``supported`` = 1.0, ``to_verify`` = 0.5, ``unsupported`` /
``contradicted`` = 0.0, ``not_applicable`` is excluded from both numerator
and denominator.  Modality weights: ``mandatory`` = 1.0, ``preferred`` =
0.5, ``unknown`` = 0.5, ``contextual`` = 0.0.  An unknown requirement is
therefore neither rewarded nor punished as a mandatory one.

SCHEMA (compact JSON of one fit)
--------------------------------
::
  {
    "requirement_id": "req_ab88a6f0d8d460fb",
    "requirement_text": "Master 2 en finance",
    "modality": "mandatory",
    "category": "etudes",
    "verdict": "supported",
    "profile_evidence": "Master 2 en finance — 2026",
    "evidence_offset": 128,
    "reason": "Niveau approuvé « master 2 » ≥ exigence « master 2 ».",
    "confidence": 0.85,
  }
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Mapping, Sequence

from .models import clean_text, normalized_text
from .offer_requirements import analyze_offer

Verdict = Literal["supported", "unsupported", "contradicted", "to_verify", "not_applicable"]
Modality = Literal["mandatory", "preferred", "contextual", "unknown"]

VERDICTS: tuple[str, ...] = ("supported", "unsupported", "contradicted", "to_verify", "not_applicable")
MODALITIES: tuple[str, ...] = ("mandatory", "preferred", "contextual", "unknown")

# The nine categories the mission requires, plus ``other`` for the statements
# the canonical contract does not classify.  ``CATEGORY_LABELS`` gives the
# human-readable French label of each slug.
FIT_CATEGORIES: tuple[str, ...] = (
    "etudes",
    "experience",
    "tech",
    "outils",
    "langues",
    "mobilite",
    "auth_travail",
    "dispo",
    "diplomation",
    "other",
)
REQUIRED_FIT_CATEGORIES: tuple[str, ...] = FIT_CATEGORIES[:-1]

CATEGORY_LABELS: dict[str, str] = {
    "etudes": "Niveau d'études",
    "experience": "Expérience",
    "tech": "Compétences techniques",
    "outils": "Outils",
    "langues": "Langues",
    "mobilite": "Mobilité",
    "auth_travail": "Autorisation de travail",
    "dispo": "Disponibilité",
    "diplomation": "Date de diplomation",
    "other": "Non classé",
}

# Fact statuses (SPEC SK-10 vocabulary).  Only the two approved ones count as
# evidence: an OCR extraction is never approved implicitly.
FACT_STATUSES: tuple[str, ...] = ("proposed", "approved", "rejected", "modified", "suspended")
APPROVED_STATUSES: frozenset[str] = frozenset({"approved", "modified"})

_MODALITY_FROM_CONTRACT: dict[str, str] = {
    "required": "mandatory",
    "preferred": "preferred",
    "contextual": "contextual",
    "unknown": "unknown",
}

_CATEGORY_ALIASES: dict[str, str] = {
    "etudes": "etudes",
    "education": "etudes",
    "education_level": "etudes",
    "degree": "etudes",
    "diplome": "etudes",
    "experience": "experience",
    "experiences": "experience",
    "work_experience": "experience",
    "tech": "tech",
    "technical_skill": "tech",
    "technical_skills": "tech",
    "skills": "tech",
    "competences": "tech",
    "outils": "outils",
    "tools": "outils",
    "software": "outils",
    "langues": "langues",
    "language": "langues",
    "languages": "langues",
    "mobilite": "mobilite",
    "mobility": "mobilite",
    "location": "mobilite",
    "auth_travail": "auth_travail",
    "work_authorization": "auth_travail",
    "authorization": "auth_travail",
    "dispo": "dispo",
    "availability": "dispo",
    "diplomation": "diplomation",
    "graduation": "diplomation",
    "graduation_date": "diplomation",
    "other": "other",
}

# ------------------------------------------------------------------ profiles


@dataclass(frozen=True)
class ProfileFact:
    """One approved fact of the candidate profile.

    ``value`` is the canonical value used by the matcher, ``quote`` the exact
    excerpt of the approved source and ``offset`` its position inside the
    profile text (``profile_text[offset:offset + len(quote)] == quote``).
    """

    fact_id: str
    category: str
    value: str
    quote: str = ""
    offset: int | None = None
    status: str = "approved"
    source: str = "profile"
    topic: str = ""
    detail: str = ""
    months: int | None = None
    year: int | None = None
    negated: bool = False

    @property
    def evidence(self) -> str:
        """The exact excerpt shown to the user (quote, else value)."""
        return self.quote or self.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovedProfile:
    """The approved facts of the candidate profile.

    ``facts`` holds every fact with its status; only the ``approved`` and
    ``modified`` ones are evidence for the matcher.
    """

    facts: tuple[ProfileFact, ...] = ()
    profile_text: str = ""

    def approved_facts(self) -> tuple[ProfileFact, ...]:
        return tuple(fact for fact in self.facts if fact.status in APPROVED_STATUSES)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ApprovedProfile":
        """Build a profile from a plain mapping (facts or category sections)."""
        raw_facts = payload.get("facts")
        facts: list[ProfileFact] = []
        if isinstance(raw_facts, Sequence) and not isinstance(raw_facts, (str, bytes)):
            for index, item in enumerate(raw_facts):
                facts.append(_fact_from_payload(item, index=index))
        else:
            for key, value in payload.items():
                if key in {"facts", "profile_text"}:
                    continue
                category = _CATEGORY_ALIASES.get(normalized_text(key).replace(" ", "_"))
                if category is None or not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                    continue
                for item in value:
                    facts.append(
                        _fact_from_payload(item, index=len(facts), default_category=category)
                    )
        return cls(facts=tuple(facts), profile_text=clean_text(payload.get("profile_text"), limit=200_000))

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": [fact.to_dict() for fact in self.facts],
            "profile_text": self.profile_text,
        }


def _fact_from_payload(payload: Any, *, index: int, default_category: str = "other") -> ProfileFact:
    if isinstance(payload, ProfileFact):
        return payload
    if isinstance(payload, str):
        text = clean_text(payload, limit=1000)
        return ProfileFact(
            fact_id=f"fact_{index:04d}",
            category=default_category,
            value=text,
            quote=text,
            status="approved",
            source="profile",
        )
    data = dict(payload or {})
    raw_category = normalized_text(data.get("category") or default_category).replace(" ", "_")
    category = _CATEGORY_ALIASES.get(raw_category, default_category)
    value = clean_text(data.get("value"), limit=1000)
    quote = clean_text(data.get("quote") or data.get("text") or value, limit=2000)
    status = normalized_text(data.get("status") or "approved").replace(" ", "_")
    if status not in FACT_STATUSES:
        status = "proposed"
    source = normalized_text(data.get("source") or "profile").replace(" ", "_") or "profile"
    offset = data.get("offset")
    if not isinstance(offset, int) or offset < 0:
        offset = None
    months = data.get("months")
    months = months if isinstance(months, int) and months >= 0 else None
    year = data.get("year")
    year = year if isinstance(year, int) else None
    fact_id = clean_text(data.get("fact_id") or data.get("id"), limit=120)
    if not fact_id:
        digest = hashlib.sha256(f"{index}|{category}|{value}|{quote}".encode("utf-8")).hexdigest()[:12]
        fact_id = f"fact_{index:04d}_{digest}"
    return ProfileFact(
        fact_id=fact_id,
        category=category,
        value=value,
        quote=quote,
        offset=offset,
        status=status,
        source=source,
        topic=clean_text(data.get("topic"), limit=200),
        detail=clean_text(data.get("detail"), limit=500),
        months=months,
        year=year,
        negated=bool(data.get("negated")),
    )


# --------------------------------------------------------------------- fits


@dataclass
class RequirementFit:
    """The verdict for one canonical requirement."""

    requirement_id: str
    requirement_text: str
    modality: Modality
    category: str
    verdict: Verdict
    profile_evidence: str | None
    evidence_offset: int | None
    reason: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FitResult:
    """The aggregated result of one offer ↔ profile comparison."""

    fits: list[RequirementFit] = field(default_factory=list)
    supported_count: int = 0
    unsupported_count: int = 0
    to_verify_count: int = 0
    contradicted_count: int = 0
    overall_score: float = 0.0
    missing_critical: list[str] = field(default_factory=list)

    @property
    def not_applicable_count(self) -> int:
        return sum(1 for fit in self.fits if fit.verdict == "not_applicable")

    def fits_by_category(self, category: str) -> list[RequirementFit]:
        return [fit for fit in self.fits if fit.category == category]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fits": [fit.to_dict() for fit in self.fits],
            "supported_count": self.supported_count,
            "unsupported_count": self.unsupported_count,
            "to_verify_count": self.to_verify_count,
            "contradicted_count": self.contradicted_count,
            "not_applicable_count": self.not_applicable_count,
            "overall_score": self.overall_score,
            "missing_critical": list(self.missing_critical),
        }


# ------------------------------------------------------------- vocabularies

_STOPWORDS: frozenset[str] = frozenset(
    {
        # english
        "the", "and", "for", "with", "you", "your", "our", "will", "have", "has", "are",
        "not", "that", "this", "from", "plus", "minimum", "maximum", "least", "most",
        "must", "required", "requirements", "requirement", "experience", "experiences",
        "skill", "skills", "knowledge", "knowledge", "solid", "strong", "good",
        "excellent", "ability", "abilities", "level", "levels", "proven", "use",
        "using", "used", "work", "working", "role", "team", "teams", "years", "year",
        "months", "month", "must", "have", "years", "prior", "previous", "relevant",
        # french
        "atout", "atouts", "requis", "requise", "requisites", "exigee", "exige",
        "obligatoire", "obligatoires", "indispensable", "maitrise", "maitriser",
        "maitrisant", "competences", "competence", "connaissances", "connaissance",
        "solides", "solide", "bonne", "bonnes", "excellente", "capable", "autonomie",
        "rigoureux", "rigoureuse", "esprit", "tres", "concrete", "reelle",
        "utilisation", "ans", "mois", "precedente", "anterieure", "experience",
        "experiences", "niveau", "diplome", "diplomee", "etudes", "formation",
        "formations", "diplomes", "universite", "ecole", "etudiant", "cursus",
        # german
        "kenntnisse", "kenntnissen", "erfahrung", "erfahrungen", "mindestens",
        "erforderlich", "voraussetzung", "vorzuge", "wunschenswert", "gute", "guter",
        "solide", "monate", "jahre", "jahr", "studium", "abschluss",
        # italian
        "competenze", "conoscenze", "esperienza", "esperienze", "minimo", "almeno",
        "requisito", "requisiti", "forte", "ottima", "ottimo", "buona", "buono",
        "livello", "laurea", "mesi", "anni",
        # spanish
        "competencias", "conocimientos", "experiencia", "experiencias", "minimo",
        "menos", "requerido", "requerida", "requeridos", "imprescindible", "sólido",
        "sólida", "nivel", "buen", "buena", "excelente", "titulo", "estudios",
        "meses", "anos", "años",
        # function words (fr / en / de / it / es)
        "des", "les", "une", "pour", "par", "avec", "dans", "aux", "cette",
        "ces", "leur", "leurs", "votre", "notre", "nos", "vos", "tout", "tous",
        "toute", "toutes", "aussi", "ainsi", "dont", "sans", "sous", "entre",
        "vers", "chez", "comme", "selon", "sont", "etre", "avoir", "bien",
        "peut", "faut", "doit", "faire", "selon", "sowie", "und", "oder",
        "della", "delle", "dello", "degli", "para", "como", "sobre", "entre",
        "the", "for", "with", "from", "into", "onto", "upon", "shall", "must",
    }
)

_TECH_STOP: frozenset[str] = frozenset(
    {
        "technical", "techniques", "technique", "technisch", "tecnico", "tecnicas",
        "maitrise", "mastery", "proficiency", "connaissance", "connaissances",
        "kenntnis", "kenntnisse", "competenza", "competencias", "conocimiento",
        "outil", "outils", "tools", "tool", "usage", "utilisation", "utiliser",
        "maîtrise", "besitzer", "beherrschung",
    }
)

_EXPERIENCE_STOP: frozenset[str] = frozenset(
    {
        "experience", "experiences", "experience", "experienze", "experiencia",
        "erfahrung", "ans", "an", "years", "year", "mois", "months", "monate",
        "mesi", "meses", "anos", "años", "minimum", "mindestens", "minimo", "at",
        "least", "ameno", "plus", "au", "moins", "precedente", "anterieure",
        "previous", "prior", "relevant", "professional", "professionnelle",
        "proficiency", "connaissance",
    }
)

_EDUCATION_STOP: frozenset[str] = frozenset(
    {
        "diplome", "diplomes", "diploma", "diplomas", "degree", "degrees", "niveau",
        "level", "formation", "formations", "etudes", "etude", "studium", "studies",
        "studien", "laurea", "diplomi", "titulo", "titulos", "universite",
        "universitat", "university", "ecole", "school", "hochschule", "etudiant",
        "student", "studente", "cursus", "ingenieur", "engineer", "engineering",
        "graduate", "graduat", "abschluss", "master", "masters", "licence",
        "bachelor", "mba", "msc", "m1", "m2", "bac", "baccalaureat", "dut", "deug",
        # modality markers: they are not part of the studied field
        "appreciated", "appreciee", "appreciee", "apprecie", "souhaite",
        "souhaitable", "atout", "atouts", "requis", "requise", "requisites",
        "obligatoire", "obligatoires", "indispensable", "exige", "exigee",
        "preference", "preferences", "bonus", "desirable", "valued", "welcome",
        "plus", "nice", "have", "must", "should", "required", "recommanded",
    }
)

_MOBILITY_STOP: frozenset[str] = frozenset(
    {
        "mobilite", "mobilité", "mobility", "mobilita", "movilidad", "relocation",
        "relocalisation", "deplacement", "deplacements", "based", "base", "poste",
        "lieu", "siege", "sede", "sede", "ansatz", "office", "sur", "site",
        "presentiel", "onsite", "remote", "teletravail", "home", "office",
        "hybride", "hybrid", "bereit", "standort", "ubicazione", "sede",
    }
)

# Tools are software / platforms, not generic skills.
_TOOL_TERMS: frozenset[str] = frozenset(
    {
        "excel", "vba", "macro", "macros", "power bi", "powerbi", "tableau",
        "sap", "salesforce", "jira", "confluence", "sharepoint", "dynamics",
        "workday", "bloomberg", "factset", "capital iq", "outlook", "office",
        "matlab", "sql server", "oracle", "google analytics", "qlik", "sas",
        "hyperion", "birt", "cognos", "tm1", "anaplan",
    }
)

_LANGUAGE_NAMES: dict[str, str] = {
    "anglais": "anglais",
    "english": "anglais",
    "englisch": "anglais",
    "ingles": "anglais",
    "inglesa": "anglais",
    "inglese": "anglais",
    "engels": "anglais",
    "francais": "francais",
    "french": "francais",
    "franzosisch": "francais",
    "frances": "francais",
    "francese": "francais",
    "frans": "francais",
    "allemand": "allemand",
    "german": "allemand",
    "deutsch": "allemand",
    "aleman": "allemand",
    "tedesco": "allemand",
    "espagnol": "espagnol",
    "spanish": "espagnol",
    "spanisch": "espagnol",
    "spagnolo": "espagnol",
    "italien": "italien",
    "italian": "italien",
    "italienisch": "italien",
    "italiano": "italien",
    "portugais": "portugais",
    "portuguese": "portugais",
    "portugues": "portugais",
    "neerlandais": "neerlandais",
    "dutch": "neerlandais",
    "chinois": "chinois",
    "chinese": "chinois",
    "japonais": "japonais",
    "japanese": "japonais",
    "arabe": "arabe",
    "arabic": "arabe",
    "hongrois": "hongrois",
    "polonais": "polonais",
    "suedois": "suedois",
}

_LANGUAGE_LEVELS: dict[str, int] = {
    "c2": 6,
    "c1": 5,
    "b2": 4,
    "b1": 3,
    "a2": 2,
    "a1": 1,
    "courant": 5,
    "courante": 5,
    "currante": 5,
    "fluent": 5,
    "avance": 5,
    "avancee": 5,
    "avanzado": 5,
    "avanzata": 5,
    "professionnel": 5,
    "professionnelle": 5,
    "profesional": 5,
    "bilingue": 5,
    "bilingual": 5,
    "trilingue": 6,
    "trilingual": 6,
    "maternel": 6,
    "maternelle": 6,
    "nativo": 6,
    "nativa": 6,
    "native": 6,
    "lingua materna": 6,
    "mutter Sprache": 6,
    "intermediaire": 3,
    "intermediate": 3,
    "intermedio": 3,
    "elementaire": 2,
    "grundkenntnisse": 2,
    "bon": 3,
    "bonne": 3,
    "bueno": 3,
    "buena": 3,
    "good": 3,
    "solide": 3,
    "beginner": 1,
    "debutant": 1,
    "principiante": 1,
}

_EDUCATION_LEVELS: dict[str, int] = {
    "doctorat": 6,
    "phd": 6,
    "doctor": 6,
    "doktorarbeit": 6,
    "master of science": 5,
    "master 2": 5,
    "master2": 5,
    "m2": 5,
    "msc": 5,
    "mba": 5,
    "master": 5,
    "masters": 5,
    "ingenieur": 5,
    "engineering degree": 5,
    "master 1": 4,
    "master1": 4,
    "m1": 4,
    "licence": 3,
    "license": 3,
    "bachelor": 3,
    "bachelors": 3,
    "laurea": 3,
    "bsc": 3,
    "bac 2": 2,
    "bac2": 2,
    "dut": 2,
    "deug": 2,
    "baccalaureat": 1,
    "high school": 1,
    "abitur": 1,
    "bac": 1,
}

_EXPERIENCE_MARKERS: tuple[str, ...] = (
    "experience", "experiences", "erfahrung", "erfahrungen", "esperienza",
    "esperienze", "experiencia", "experiencias",
)

_DURATION_RE = re.compile(
    r"(?P<value>\d{1,3})\s*(?P<unit>mois|month|months|monate|mesi|meses|monat|monate)\b"
)
_DURATION_YEARS_RE = re.compile(
    r"(?P<value>\d{1,2})\s*(?P<unit>ans|an|year|years|jahre|jahr|anni|ano|anos|años)\b"
)
_RANGE_YEARS_RE = re.compile(r"\b(?P<start>19\d{2}|20\d{2})\s*(?:[-–—/]|to|au|a|bis|hasta|al|jusqu|a)\s*(?P<end>19\d{2}|20\d{2})\b")

_MONTH_NAMES: dict[str, int] = {
    "janvier": 1, "january": 1, "jan": 1, "januar": 1, "gennaio": 1, "enero": 1,
    "fevrier": 2, "february": 2, "feb": 2, "februar": 2, "febbraio": 2, "febrero": 2,
    "mars": 3, "march": 3, "mar": 3, "marz": 3, "marzo": 3,
    "avril": 4, "april": 4, "apr": 4, "aprile": 4, "abril": 4,
    "mai": 5, "may": 5, "maggio": 5, "mayo": 5,
    "juin": 6, "june": 6, "jun": 6, "giugno": 6, "junio": 6,
    "juillet": 7, "july": 7, "jul": 7, "luglio": 7, "julio": 7,
    "aout": 8, "august": 8, "aug": 8, "agosto": 8, "ago": 8,
    "septembre": 9, "september": 9, "sep": 9, "settembre": 9, "septiembre": 9,
    "octobre": 10, "october": 10, "oct": 10, "ottobre": 10, "octubre": 10,
    "novembre": 11, "november": 11, "nov": 11, "noviembre": 11,
    "decembre": 12, "december": 12, "dec": 12, "dicembre": 12, "diciembre": 12,
}

_ISO_DATE_RE = re.compile(r"\b(?P<year>19\d{2}|20\d{2})-(?P<month>0[1-9]|1[0-2])(?:-(?P<day>0[1-9]|[12]\d|3[01]))?\b")
_SLASH_DATE_RE = re.compile(r"\b(?P<day>0[1-9]|[12]\d|3[01])/(?P<month>0[1-9]|1[0-2])/(?P<year>19\d{2}|20\d{2})\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

_GRADUATION_MARKERS: tuple[str, ...] = (
    "date de diplomation", "date of graduation", "graduation date", "date de laurea",
    "data di laurea", "abschlussdatum", "diploma date", "date du diplome",
    "diplome obtenu", "obtention du diplome", "promu", "abschluss",
)

_GRADUATION_DEADLINE_MARKERS: tuple[str, ...] = (
    "avant", "au plus tard", "before", "no later than", "not later than",
    "spatestens", "spätestens", "entro", "antes de", "latest", "bis",
)

_AUTH_MARKERS: tuple[str, ...] = (
    "autorisation de travail", "work authorization", "work authorisation",
    "right to work", "droit de travailler", "permis de travail", "aufenthaltstitel",
    "arbeitsbewilligung", "permesso di lavoro", "permiso de trabajo", "carte de sejour",
    "residence permit",
)

_SPONSORSHIP_MARKERS: tuple[str, ...] = (
    "sponsorship", "visa sponsorship", "visa", "sponsors", "visa sponsorship available",
    "sponsore", "patrocinio", "patrocinio", "sponsoring",
)

_AUTH_NEED_MARKERS: tuple[str, ...] = (
    "need sponsorship", "needs sponsorship", "sponsorship required", "requires visa",
    "requires sponsorship", "visa required", "demande un visa", "besoin d un visa",
    "visa sponsorship required", "sponsorship needed", "benoetigt ein visa",
    "richiede visto", "necesita visado",
)

_AUTHORIZED_MARKERS: tuple[str, ...] = (
    "autorisation de travail", "work authorization", "work permit", "right to work",
    "citizen", "citoyen", "citizenship", "nationalite", "nationality", "eu citizen",
    "citoyen ue", "permanent permit", "carte de sejour", "aufenthaltstitel",
    "permesso di lavoro", "permiso de trabajo",
)

_RELOCATION_MARKERS: tuple[str, ...] = (
    "relocalisation", "relocaliser", "relocation", "umzug", "trasferta", "traslado",
    "pret a relocaliser", "willing to relocate", "bereit umzuziehen", "pronto a trasferirsi",
    "movilidad geografica",
)

# A profile fact may state the *absence* of an attribute ("aucune expérience
# de gestion d'équipe"): that is an explicit contradiction, not a missing
# proof.
_FACT_NEGATION_MARKERS: tuple[str, ...] = (
    "aucune", "aucun", "aucuns", "aucunes", "pas", "sans", "no", "without",
    "keine", "kein", "nessun", "nessuna", "ninguna", "nein", "ohne", "sin",
)

_MOBILITY_REMOTE_MARKERS: tuple[str, ...] = (
    "remote", "teletravail", "home office", "a distance", "full remote",
)

_MOBILITY_ONSITE_MARKERS: tuple[str, ...] = (
    "sur site", "onsite", "on site", "presentiel", "sur place", "presencial",
    "vor ort", "in haus",
)

_CITIES: frozenset[str] = frozenset(
    {
        "paris", "londres", "london", "milan", "milan", "luxembourg", "luxemburg",
        "frankfurt", "geneve", "geneva", "bruxelles", "brussels", "amsterdam",
        "rotterdam", "madrid", "barcelone", "barcelona", "lisbonne", "lisbon",
        "marseille", "lyon", "toulouse", "bordeaux", "nantes", "lille", "nice",
        "strasbourg", "rennes", "montpellier", "grenoble", "zurich", "zuerich",
        "vienne", "vienna", "munich", "berlin", "hamburg", "rome", "roma", "turin",
        "marseille", "dublin", "edinburgh", "manchester", "varsovie", "warsaw",
    }
)

_IMMEDIATE_MARKERS: tuple[str, ...] = (
    "immediatement", "immediatamente", "immediately", "asap", "sofort", "subito",
    "right away", "des que possible", "tout de suite", "disponible immediatement",
)


# ------------------------------------------------------------------ helpers


def _tokens(text: str) -> list[str]:
    return normalized_text(text).split()


def _content_tokens(text: str, *, extra: Iterable[str] = ()) -> set[str]:
    stop = set(_STOPWORDS)
    stop.update(normalized_text(word).replace(" ", "_") for word in extra)
    return {token for token in _tokens(text) if len(token) >= 3 and token not in stop}


def _token_match(left: str, right: str) -> bool:
    """Lenient token equality (handles ``finance`` vs ``financier``).

    The rule stays narrow on purpose: both tokens share their five first
    characters and their lengths differ by at most four.  ``sales`` never
    matches ``salesforce`` (too far apart), ``finance`` does match
    ``financier``.
    """
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < 5 or len(longer) - len(shorter) > 4:
        return False
    return longer[:5] == shorter[:5]


def _overlap(left: set[str], right: set[str]) -> set[str]:
    if not left or not right:
        return set()
    hits = {token for token in left if token in right}
    if hits:
        return hits
    for token in left:
        for other in right:
            if _token_match(token, other):
                hits.add(token)
                break
    return hits


def _display_terms(text: str, tokens: set[str]) -> list[str]:
    """Original spellings of ``tokens`` inside ``text`` (readable quotes)."""
    out: list[str] = []
    for word in re.findall(r"[\wÀ-ÖØ-öø-ÿ+-]+", text):
        key = normalized_text(word)
        if key and key in tokens and word not in out:
            out.append(word)
    return out[:6]


def _quote(fact: ProfileFact | None, limit: int = 140) -> str:
    if fact is None:
        return ""
    text = fact.evidence.replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _has_marker(text: str, markers: Iterable[str]) -> bool:
    padded = f" {normalized_text(text)} "
    return any(f" {normalized_text(marker)} " in padded or f" {normalized_text(marker)}" in padded
               for marker in markers)


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(normalized_text(word))}\b", normalized_text(text)) is not None


def _first_marker(text: str, markers: Iterable[str]) -> str:
    normalized = normalized_text(text)
    best = ""
    for marker in markers:
        key = normalized_text(marker)
        if not key:
            continue
        if re.search(rf"\b{re.escape(key)}\b", normalized) and len(key) > len(best):
            best = key
    return best


# -------------------------------------------------------------- level ladders


def _education_level(text: str) -> tuple[int | None, str]:
    """Rank of the highest education level named in ``text``.

    A numbered level always wins over a generic one: ``Master 1`` is a
    first-year master (rank 4), never the generic ``Master`` (rank 5).
    """
    normalized = normalized_text(text)
    bac_plus = re.search(r"\bbac\s*\+?\s*(\d)\b", normalized)
    if bac_plus:
        level = min(6, int(bac_plus.group(1)))
        return level, f"bac+{bac_plus.group(1)}"
    numbered: tuple[int, str] | None = None
    plain: tuple[int, str] | None = None
    for marker in sorted(_EDUCATION_LEVELS, key=len, reverse=True):
        if not re.search(rf"\b{re.escape(marker)}\b", normalized):
            continue
        level = _EDUCATION_LEVELS[marker]
        if any(character.isdigit() for character in marker):
            if numbered is None or level > numbered[0]:
                numbered = (level, marker)
        elif plain is None or level > plain[0]:
            plain = (level, marker)
    best = numbered or plain
    if best is None:
        return None, ""
    return best


def _language_level(text: str) -> tuple[int | None, str]:
    """Rank of the language level named in ``text`` (higher is stronger).

    An explicit scale (``B2``, ``C1``) wins over a descriptive marker
    (``courant``): the scale is what the offer really asks for.
    """
    normalized = normalized_text(text)
    numbered: tuple[int, str] | None = None
    plain: tuple[int, str] | None = None
    for marker in sorted(_LANGUAGE_LEVELS, key=len, reverse=True):
        if not re.search(rf"\b{re.escape(marker)}\b", normalized):
            continue
        level = _LANGUAGE_LEVELS[marker]
        if any(character.isdigit() for character in marker):
            if numbered is None or level > numbered[0]:
                numbered = (level, marker)
        elif plain is None or level > plain[0]:
            plain = (level, marker)
    best = numbered or plain
    if best is None:
        return None, ""
    return best


def _languages_in(text: str) -> list[str]:
    """Languages named in ``text`` (canonical keys)."""
    normalized = normalized_text(text)
    found: list[str] = []
    for marker, key in _LANGUAGE_NAMES.items():
        if re.search(rf"\b{re.escape(marker)}\b", normalized) and key not in found:
            found.append(key)
    return found


def _months_from_text(text: str) -> int | None:
    """Duration in months written in ``text`` (``None`` when absent)."""
    normalized = normalized_text(text)
    match = _DURATION_RE.search(normalized)
    if match:
        return int(match.group("value"))
    match = _DURATION_YEARS_RE.search(normalized)
    if match:
        return int(match.group("value")) * 12
    match = _RANGE_YEARS_RE.search(normalized)
    if match:
        start, end = int(match.group("start")), int(match.group("end"))
        if 0 < end - start <= 40:
            return (end - start) * 12
    return None


def _experience_months(text: str) -> int | None:
    """Months demanded by an *experience* requirement (never a contract duration)."""
    normalized = normalized_text(text)
    if not any(re.search(rf"\b{re.escape(marker)}\b", normalized) for marker in _EXPERIENCE_MARKERS):
        return None
    months = _months_from_text(text)
    if months is None:
        return None
    # The duration must belong to the experience phrase, not to the internship
    # duration ("six-month internship" is not "six months of experience").
    for marker in ("stage", "internship", "internship", "praktikum", "tirocinio", "pasantia"):
        if re.search(rf"\b{re.escape(marker)}\b", normalized):
            return None
    return months


def _date_parts(text: str) -> tuple[int | None, int | None]:
    """(year, month) named in ``text`` — the finest component available."""
    match = _ISO_DATE_RE.search(text)
    if match:
        return int(match.group("year")), int(match.group("month"))
    match = _SLASH_DATE_RE.search(text)
    if match:
        return int(match.group("year")), int(match.group("month"))
    normalized = normalized_text(text)
    for name, number in _MONTH_NAMES.items():
        pattern = rf"\b{re.escape(name)}\s+(19\d{{2}}|20\d{{2}})\b"
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1)), number
        pattern = rf"\b(19\d{{2}}|20\d{{2}})\s+{re.escape(name)}\b"
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1)), number
    match = _YEAR_RE.search(text)
    if match:
        return int(match.group(0)), None
    return None, None


def _date_leq(left: tuple[int | None, int | None], right: tuple[int | None, int | None]) -> bool:
    """``left`` is earlier than or equal to ``right`` (month-less = January)."""
    left_key = (left[0] or 0, left[1] or 0)
    right_key = (right[0] or 0, right[1] or 0)
    return left_key <= right_key


# --------------------------------------------------------------- fact index


class _Facts:
    """Index of the approved facts, by category and by tokens."""

    def __init__(self, facts: Sequence[ProfileFact]) -> None:
        self.facts: list[ProfileFact] = list(facts)
        self._by_category: dict[str, list[ProfileFact]] = {}
        self._tokens: dict[int, set[str]] = {}
        for fact in self.facts:
            self._by_category.setdefault(fact.category, []).append(fact)
            self._tokens[id(fact)] = _fact_tokens(fact)

    def by_category(self, *categories: str) -> list[ProfileFact]:
        out: list[ProfileFact] = []
        for category in categories:
            out.extend(self._by_category.get(category, []))
        return out

    def tokens(self, fact: ProfileFact) -> set[str]:
        return self._tokens.get(id(fact), set())


def _fact_tokens(fact: ProfileFact) -> set[str]:
    parts = [fact.value, fact.quote, fact.topic, fact.detail]
    tokens: set[str] = set()
    for part in parts:
        tokens.update(token for token in _tokens(part) if len(token) >= 2)
    return tokens


def _fact_is_negated(fact: ProfileFact) -> bool:
    """True when the approved fact states the *absence* of the attribute."""
    if fact.negated:
        return True
    return _mentions(f"{fact.value} {fact.quote}", _FACT_NEGATION_MARKERS)


def _mobility_polarity(text: str) -> str | None:
    """``remote`` / ``onsite`` when the wording states one of them."""
    onsite = _mentions(text, _MOBILITY_ONSITE_MARKERS)
    remote = _mentions(text, _MOBILITY_REMOTE_MARKERS)
    if onsite and remote:
        return None
    if onsite:
        return "onsite"
    if remote:
        return "remote"
    return None


# -------------------------------------------------------------- categories

# Marker sets used to *verify* the canonical category and to re-derive it
# when the canonical contract could not classify a statement.  They only
# decide the fit category of a requirement — they never extract requirements.
_EDUCATION_CATEGORY_MARKERS: tuple[str, ...] = tuple(_EDUCATION_LEVELS) + (
    "diplome", "diploma", "diplom", "degree", "etudes", "etude", "formation",
    "laurea", "grado", "licenciatura", "studium", "studien", "studii", "titulo",
    "titulos", "estudios", "university", "universite", "universitat", "ecole",
    "school", "hochschule", "cursus", "graduate", "graduat", "abschluss",
)

_TECH_CATEGORY_MARKERS: tuple[str, ...] = (
    "python", "java", "javascript", "typescript", "react", "angular", "vue",
    "sql", "nosql", "mongodb", "machine learning", "deep learning",
    "data analysis", "data science", "data visualisation", "statistiques",
    "statistics", "modelisation", "modeling", "valuation", "comptabilite",
    "accounting", "audit", "scala", "git", "docker", "aws", "azure",
    "competences", "competencias", "kenntnisse", "competenza", "conoscenze",
    "conocimiento", "skills", "technique", "techniques", "technisch",
    "tecnico", "savoir faire",
)

_LANGUAGE_CATEGORY_MARKERS: tuple[str, ...] = tuple(_LANGUAGE_NAMES) + (
    "langue", "langues", "language", "languages", "langua", "idioma", "sprache",
    "bilingue", "bilingual", "trilingue", "courant", "courante", "fluent",
    "native", "maternel", "maternelle", "c1", "c2", "b1", "b2", "a1", "a2",
)

_EXPERIENCE_CATEGORY_MARKERS: tuple[str, ...] = (
    "experience", "experiences", "erfahrung", "erfahrungen", "esperienza",
    "esperienze", "experiencia", "experiencias", "internship", "praktikum",
    "tirocinio", "pasantia", "stage", "ans d", "ans de", "years of",
    "months of", "background",
)

_MOBILITY_CATEGORY_MARKERS: tuple[str, ...] = (
    "mobilite", "mobility", "mobilita", "movilidad", "relocation",
    "relocalisation", "umzug", "trasferta", "traslado", "remote", "teletravail",
    "home office", "sur site", "onsite", "presentiel", "hybride", "hybrid",
    "based in", "base a", "deplacement", "deplacements", "ville", "city",
) + tuple(sorted(_CITIES))

_AUTH_CATEGORY_MARKERS: tuple[str, ...] = _AUTH_MARKERS + _SPONSORSHIP_MARKERS + (
    "citoyen", "citizen", "nationalite", "nationality", "residence permit",
    "carte de sejour", "aufenthaltstitel", "permesso di lavoro", "permiso de trabajo",
)

_AVAILABILITY_CATEGORY_MARKERS: tuple[str, ...] = (
    "disponible", "disponibilite", "disponibilita", "disponibilidad",
    "verfugbarkeit", "availability", "asap", "sofort", "immediately",
    "immediatement", "immediatamente", "date de debut", "starting date",
    "start date", "starting period", "start period", "au plus tot",
)

_AVAILABILITY_CONTEXT_MARKERS: tuple[str, ...] = (
    "immediately", "immediatement", "asap", "sofort", "from", "starting",
    "start", "date", "period", "periodo", "periode", "ab", "a partir de",
)


def _mentions(text: str, markers: Iterable[str]) -> bool:
    normalized = normalized_text(text)
    for marker in markers:
        key = normalized_text(marker)
        if not key:
            continue
        if re.search(rf"\b{re.escape(key)}\b", normalized):
            return True
    return False


def _mentions_availability(text: str) -> bool:
    """``available`` alone is ambiguous ("sponsorship available")."""
    if _mentions(text, _AVAILABILITY_CATEGORY_MARKERS):
        return True
    normalized = normalized_text(text)
    if "available" in normalized and _mentions(text, _AVAILABILITY_CONTEXT_MARKERS):
        return True
    return False


def _fit_category(record: Mapping[str, Any]) -> str:
    """Fit category of a canonical requirement.

    The canonical contract decides first; the fit category only *refines* it
    (a graduation date is not a level, a named software is a tool).  When the
    canonical contract could not classify the statement — or when its
    keyword match is spurious — the category is re-derived from the wording.
    """
    text = clean_text(record.get("text"), limit=400)
    contract_category = clean_text(record.get("category"), limit=40) or "other"
    if contract_category == "education" and _mentions(text, _EDUCATION_CATEGORY_MARKERS):
        return "diplomation" if _is_graduation_statement(text) else "etudes"
    if contract_category == "technical_skill" and _mentions(text, _TECH_CATEGORY_MARKERS + tuple(_TOOL_TERMS)):
        return "outils" if _mentions(text, _TOOL_TERMS) else "tech"
    if contract_category == "language" and _mentions(text, _LANGUAGE_CATEGORY_MARKERS):
        return "langues"
    if contract_category == "experience" and _mentions(text, _EXPERIENCE_CATEGORY_MARKERS):
        return "experience"
    if contract_category == "availability" and _mentions_availability(text):
        return "dispo"
    if contract_category == "mobility" and _mentions(text, _MOBILITY_CATEGORY_MARKERS):
        return "mobilite"
    if contract_category == "work_authorization" and _mentions(text, _AUTH_CATEGORY_MARKERS):
        return "auth_travail"
    return _derive_category(text)


def _derive_category(text: str) -> str:
    """Category of a statement the canonical contract left unclassified."""
    if _is_graduation_statement(text):
        return "diplomation"
    if _mentions(text, _EDUCATION_CATEGORY_MARKERS):
        return "etudes"
    if _mentions(text, _TOOL_TERMS):
        return "outils"
    if _mentions(text, _TECH_CATEGORY_MARKERS):
        return "tech"
    if _mentions(text, _LANGUAGE_CATEGORY_MARKERS):
        return "langues"
    if _mentions(text, _EXPERIENCE_CATEGORY_MARKERS):
        return "experience"
    if _mentions_availability(text):
        return "dispo"
    if _mentions(text, _MOBILITY_CATEGORY_MARKERS):
        return "mobilite"
    if _mentions(text, _AUTH_CATEGORY_MARKERS):
        return "auth_travail"
    return "other"


def _is_graduation_statement(text: str, normalized: str | None = None) -> bool:
    """True when the statement talks about a graduation *date*."""
    if normalized is None:
        normalized = normalized_text(text)
    if any(re.search(rf"\b{re.escape(normalized_text(marker))}\b", normalized) for marker in _GRADUATION_MARKERS):
        return True
    has_diploma = re.search(r"\b(diplom|laurea|abschluss|graduat)\w*\b", normalized) is not None
    has_year = _YEAR_RE.search(text) is not None
    has_deadline = any(
        re.search(rf"\b{re.escape(normalized_text(marker))}\b", normalized)
        for marker in _GRADUATION_DEADLINE_MARKERS
    )
    return has_diploma and has_year and has_deadline


def _fit_modality(record: Mapping[str, Any]) -> str:
    contract_modality = clean_text(record.get("modality"), limit=20) or "unknown"
    return _MODALITY_FROM_CONTRACT.get(contract_modality, "unknown")


# --------------------------------------------------------------- evaluators


def _handle_etudes(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    text = clean_text(record.get("text"), limit=400)
    required_level, required_label = _education_level(text)
    education_facts = facts.by_category("etudes")
    if not education_facts:
        return ("to_verify", None, "Aucune formation approuvée dans le profil : exigence à vérifier.", 0.60)
    best = max(education_facts, key=lambda fact: (_fact_education_level(fact)[0] or 0))
    profile_level, profile_label = _fact_education_level(best)
    if required_level is None:
        return ("supported", best, f"Formation approuvée dans le profil : « {_quote(best)} ».", 0.70)
    if profile_level is None:
        return ("to_verify", best, f"Formation approuvée « {_quote(best)} » mais niveau illisible : à vérifier.", 0.50)
    if profile_level >= required_level:
        domain = _content_tokens(text, extra=_EDUCATION_STOP) - _level_tokens(text)
        if domain and not _overlap(domain, facts.tokens(best)):
            terms = ", ".join(_display_terms(text, domain))
            return (
                "to_verify",
                best,
                f"Niveau approuvé « {profile_label} » atteint, mais domaine non couvert ({terms}) : à vérifier.",
                0.60,
            )
        return (
            "supported",
            best,
            f"Niveau approuvé « {profile_label} » atteint l'exigence « {required_label} » (fait approuvé : « {_quote(best)} »).",
            0.85,
        )
    if modality == "mandatory":
        return (
            "unsupported",
            best,
            f"Exigence de niveau obligatoire « {required_label} » non atteinte : niveau approuvé « {profile_label} », "
            "inférieur à l'exigence.",
            0.80,
        )
    return (
        "to_verify",
        best,
        f"Exigence de niveau « {required_label} » non bloquante face au niveau approuvé « {profile_label} » : "
        "cela ne rejette jamais le profil.",
        0.70,
    )


def _level_tokens(text: str) -> set[str]:
    tokens = set()
    for marker in list(_EDUCATION_LEVELS) + list(_LANGUAGE_LEVELS):
        key = normalized_text(marker).replace(" ", "_")
        if key and key in normalized_text(text).replace(" ", "_"):
            tokens.add(key)
    return tokens


def _fact_education_level(fact: ProfileFact) -> tuple[int | None, str]:
    level, label = _education_level(fact.value or fact.quote)
    if level is None:
        level, label = _education_level(fact.quote)
    return level, label


def _handle_experience(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    text = clean_text(record.get("text"), limit=400)
    normalized = normalized_text(text)
    if not any(re.search(rf"\b{re.escape(marker)}\b", normalized) for marker in _EXPERIENCE_MARKERS):
        return (
            "to_verify",
            None,
            "L'énoncé ne formule pas d'exigence d'expérience exploitable : à vérifier.",
            0.50,
        )
    required_months = _experience_months(text)
    domain = _content_tokens(text, extra=_EXPERIENCE_STOP)
    experience_facts = facts.by_category("experience")
    if not experience_facts:
        return ("to_verify", None, "Aucune expérience approuvée dans le profil : à vérifier.", 0.60)
    matching = [fact for fact in experience_facts if not domain or _overlap(domain, facts.tokens(fact))]
    if not matching:
        terms = ", ".join(_display_terms(text, domain))
        return (
            "to_verify",
            None,
            f"Aucune expérience approuvée ne couvre le domaine demandé ({terms}) : à vérifier.",
            0.60,
        )
    denied = next((fact for fact in matching if _fact_is_negated(fact)), None)
    if denied is not None:
        return (
            "contradicted",
            denied,
            f"Le profil approuvé déclare explicitement l'absence demandée par l'offre "
            f"(fait approuvé : « {_quote(denied)} »).",
            0.82,
        )
    best = max(matching, key=lambda fact: (_fact_months(fact), len(_overlap(domain, facts.tokens(fact)))))
    if required_months is None:
        return ("supported", best, f"Expérience approuvée dans le profil : « {_quote(best)} ».", 0.78)
    total = sum(_fact_months(fact) for fact in matching)
    if total >= required_months:
        return (
            "supported",
            best,
            f"Expérience approuvée de {total} mois ≥ {required_months} mois exigés (fait approuvé : « {_quote(best)} »).",
            0.85,
        )
    if total > 0:
        if modality == "mandatory":
            return (
                "unsupported",
                best,
                f"Expérience approuvée de {total} mois < {required_months} mois exigés.",
                0.75,
            )
        return (
            "to_verify",
            best,
            f"Expérience approuvée de {total} mois, exigence de {required_months} mois non bloquante : à vérifier.",
            0.65,
        )
    return ("to_verify", None, "Durée d'expérience approuvée inconnue : à vérifier.", 0.55)


def _fact_months(fact: ProfileFact) -> int:
    if fact.months:
        return fact.months
    months = _months_from_text(fact.value) or _months_from_text(fact.quote) or _months_from_text(fact.detail)
    return months or 0


def _handle_tech(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    text = clean_text(record.get("text"), limit=400)
    required = _content_tokens(text, extra=_TECH_STOP)
    candidates = facts.by_category("tech", "outils")
    if not candidates:
        return ("to_verify", None, "Aucune compétence technique approuvée dans le profil : à vérifier.", 0.60)
    if not required:
        return (
            "to_verify",
            None,
            "Exigence technique trop générique pour être rapprochée d'un fait approuvé précis.",
            0.50,
        )
    required_months = _experience_months(text)
    matched = [(fact, _overlap(required, facts.tokens(fact))) for fact in candidates]
    matched = [(fact, overlap) for fact, overlap in matched if overlap]
    denied = next((fact for fact, _overlap_found in matched if _fact_is_negated(fact)), None)
    if denied is not None:
        return (
            "contradicted",
            denied,
            f"Le profil approuvé déclare explicitement l'absence de cette compétence "
            f"(fait approuvé : « {_quote(denied)} »).",
            0.82,
        )
    if required_months is not None:
        total = sum(_fact_months(fact) for fact, _ in matched)
        if total >= required_months:
            best = max(matched, key=lambda item: _fact_months(item[0]))[0]
            return (
                "supported",
                best,
                f"Compétence approuvée avec {total} mois ≥ {required_months} mois exigés (fait approuvé : « {_quote(best)} »).",
                0.82,
            )
        if total > 0:
            best = max(matched, key=lambda item: _fact_months(item[0]))[0]
            if modality == "mandatory":
                return (
                    "unsupported",
                    best,
                    f"Compétence approuvée avec {total} mois < {required_months} mois exigés.",
                    0.72,
                )
            return (
                "to_verify",
                best,
                f"Compétence approuvée avec {total} mois, exigence de {required_months} mois non bloquante : à vérifier.",
                0.62,
            )
    covered: set[str] = set()
    best_fact: ProfileFact | None = None
    best_size = 0
    for fact, overlap in matched:
        covered |= overlap
        if len(overlap) > best_size:
            best_fact, best_size = fact, len(overlap)
    missing = required - covered
    if not missing:
        return (
            "supported",
            best_fact,
            f"Exigence couverte par le fait approuvé « {_quote(best_fact)} ».",
            0.90,
        )
    if covered:
        terms = ", ".join(_display_terms(text, missing))
        return (
            "to_verify",
            best_fact,
            f"Exigence partiellement couverte : {terms} absent(s) du profil approuvé.",
            0.62,
        )
    return ("to_verify", None, "Aucune preuve approuvée pour cette exigence : à vérifier.", 0.55)


def _handle_langues(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    text = clean_text(record.get("text"), limit=400)
    required_level, level_label = _language_level(text)
    languages = _languages_in(text)
    language_facts = facts.by_category("langues")
    if not language_facts:
        return ("to_verify", None, "Aucune langue approuvée dans le profil : à vérifier.", 0.60)
    if not languages:
        return (
            "to_verify",
            None,
            "Exigence de langue non précisée dans l'énoncé : à vérifier.",
            0.50,
        )
    missing: list[str] = []
    shortfalls: list[tuple[str, str]] = []
    first_fact: ProfileFact | None = None
    for language in languages:
        fact = _find_language_fact(language_facts, language)
        if fact is None:
            missing.append(language)
            continue
        if first_fact is None:
            first_fact = fact
        if _fact_is_negated(fact):
            return (
                "contradicted",
                fact,
                f"Le profil approuvé déclare ne pas parler {language} (fait approuvé : « {_quote(fact)} »).",
                0.82,
            )
        level, _label = _fact_language_level(fact)
        if required_level is not None and level is not None and level < required_level:
            shortfalls.append((language, _label or "niveau inconnu"))
    if shortfalls:
        details = ", ".join(f"{language} ({label})" for language, label in shortfalls)
        if modality == "mandatory":
            return (
                "unsupported",
                first_fact,
                f"Niveau de langue approuvé insuffisant : {details} < exigence « {level_label} ».",
                0.78,
            )
        return (
            "to_verify",
            first_fact,
            f"Niveau de langue approuvé inférieur à l'exigence « {level_label} » ({details}), exigence non bloquante.",
            0.66,
        )
    if missing:
        return (
            "to_verify",
            first_fact,
            f"Aucune langue approuvée ne couvre : {', '.join(missing)} : à vérifier.",
            0.60,
        )
    return (
        "supported",
        first_fact,
        f"Langue approuvée conforme à l'exigence « {level_label or 'présence'} » (fait approuvé : « {_quote(first_fact)} »).",
        0.88,
    )


def _fact_language_level(fact: ProfileFact) -> tuple[int | None, str]:
    level, label = _language_level(fact.value)
    if level is None:
        level, label = _language_level(fact.quote)
    return level, label


def _find_language_fact(language_facts: Sequence[ProfileFact], language: str) -> ProfileFact | None:
    for fact in language_facts:
        haystack = f"{fact.topic} {fact.value} {fact.quote}"
        if language in _languages_in(haystack):
            return fact
    return None


def _handle_mobilite(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    text = clean_text(record.get("text"), limit=400)
    requested = _content_tokens(text, extra=_MOBILITY_STOP)
    mobility_facts = facts.by_category("mobilite")
    if not mobility_facts:
        return ("to_verify", None, "Aucune information de mobilité approuvée dans le profil : à vérifier.", 0.60)
    best: ProfileFact | None = None
    best_overlap: set[str] = set()
    for fact in mobility_facts:
        overlap = _overlap(requested, facts.tokens(fact))
        if len(overlap) > len(best_overlap):
            best, best_overlap = fact, overlap
    required_polarity = _mobility_polarity(text)
    for fact in mobility_facts:
        fact_polarity = _mobility_polarity(f"{fact.value} {fact.quote}")
        if required_polarity and fact_polarity and required_polarity != fact_polarity:
            return (
                "contradicted",
                fact,
                f"Le profil approuvé est « {fact_polarity} » alors que l'offre exige « {required_polarity} » "
                f"(fait approuvé : « {_quote(fact)} »).",
                0.82,
            )
    cities = {city for city in _CITIES if city in requested}
    if best is not None and best_overlap:
        terms = ", ".join(_display_terms(text, best_overlap))
        return (
            "supported",
            best,
            f"Exigence de mobilité couverte par le fait approuvé « {_quote(best)} » ({terms}).",
            0.86,
        )
    if cities and any(_has_marker(f"{fact.value} {fact.quote}", _RELOCATION_MARKERS) for fact in mobility_facts):
        willing = next(
            fact for fact in mobility_facts if _has_marker(f"{fact.value} {fact.quote}", _RELOCATION_MARKERS)
        )
        return (
            "supported",
            willing,
            f"Profil approuvé prêt à relocaliser ({', '.join(sorted(cities))}) : fait approuvé « {_quote(willing)} ».",
            0.80,
        )
    return (
        "to_verify",
        best,
        "Aucune information de mobilité approuvée ne couvre cette exigence : à vérifier.",
        0.60,
    )


def _handle_auth_travail(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    text = clean_text(record.get("text"), limit=400)
    expectation = _auth_expectation(text)
    auth_facts = facts.by_category("auth_travail")
    if not auth_facts:
        return ("to_verify", None, "Aucune autorisation de travail approuvée dans le profil : à vérifier.", 0.60)
    if expectation == "unknown":
        return (
            "to_verify",
            auth_facts[0],
            "L'exigence ne précise pas le niveau d'autorisation demandé : à vérifier.",
            0.50,
        )
    for fact in auth_facts:
        state = _auth_fact_state(fact)
        if expectation == "authorized" and state == "authorized":
            return (
                "supported",
                fact,
                f"Autorisation de travail approuvée conforme à l'exigence (fait approuvé : « {_quote(fact)} »).",
                0.88,
            )
        if expectation == "authorized" and state == "sponsorship":
            return (
                "contradicted",
                fact,
                f"Le profil approuvé exige un sponsor de visa (« {_quote(fact)} ») alors que l'offre demande une autorisation de travail.",
                0.82,
            )
        if expectation == "sponsorship" and state == "sponsorship":
            return (
                "supported",
                fact,
                f"Le sponsor de visa demandé par l'offre correspond au profil approuvé (« {_quote(fact)} »).",
                0.85,
            )
    return (
        "to_verify",
        auth_facts[0],
        "L'information d'autorisation de travail approuvée ne permet pas de conclure : à vérifier.",
        0.55,
    )


def _auth_expectation(text: str) -> str:
    normalized = normalized_text(text)
    if any(re.search(rf"\b{re.escape(normalized_text(marker))}\b", normalized) for marker in _SPONSORSHIP_MARKERS):
        if any(re.search(rf"\b{re.escape(normalized_text(marker))}\b", normalized) for marker in _AUTH_MARKERS):
            return "authorized"
        return "sponsorship"
    if any(re.search(rf"\b{re.escape(normalized_text(marker))}\b", normalized) for marker in _AUTH_MARKERS):
        return "authorized"
    return "unknown"


def _auth_fact_state(fact: ProfileFact) -> str:
    haystack = normalized_text(f"{fact.value} {fact.quote} {fact.detail}")
    if any(re.search(rf"\b{re.escape(normalized_text(marker))}\b", haystack) for marker in _AUTH_NEED_MARKERS):
        return "sponsorship"
    if any(re.search(rf"\b{re.escape(normalized_text(marker))}\b", haystack) for marker in _AUTHORIZED_MARKERS):
        return "authorized"
    return "neutral"


def _handle_dispo(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    text = clean_text(record.get("text"), limit=400)
    availability_facts = facts.by_category("dispo")
    if not availability_facts:
        return ("to_verify", None, "Aucune disponibilité approuvée dans le profil : à vérifier.", 0.60)
    immediate = bool(_first_marker(text, _IMMEDIATE_MARKERS))
    required_year, required_month = _date_parts(text)
    best: ProfileFact | None = None
    best_months = 0
    for fact in availability_facts:
        months = _fact_months(fact)
        if months > best_months:
            best, best_months = fact, months
    if best is None:
        best = availability_facts[0]
    if immediate:
        if _has_marker(f"{best.value} {best.quote}", _IMMEDIATE_MARKERS):
            return (
                "supported",
                best,
                f"Disponibilité immédiate approuvée (fait approuvé : « {_quote(best)} »).",
                0.85,
            )
        return (
            "to_verify",
            best,
            "Le profil approuve une disponibilité datée : la comparaison avec une disponibilité immédiate reste à vérifier.",
            0.60,
        )
    if required_year is None:
        return (
            "to_verify",
            best,
            "Exigence de disponibilité sans date exploitable : à vérifier.",
            0.55,
        )
    profile_year, profile_month = _fact_date(best)
    if profile_year is None:
        return (
            "to_verify",
            best,
            f"Disponibilité approuvée sans date lisible (« {_quote(best)} ») : à vérifier.",
            0.55,
        )
    if _date_leq((profile_year, profile_month), (required_year, required_month)):
        return (
            "supported",
            best,
            f"Disponibilité approuvée ({profile_year}-{profile_month or 1:02d}) compatible avec l'exigence "
            f"({required_year}-{required_month or 1:02d}) (fait approuvé : « {_quote(best)} »).",
            0.85,
        )
    return (
        "contradicted",
        best,
        f"Disponibilité approuvée ({profile_year}-{profile_month or 1:02d}) postérieure à l'exigence "
        f"({required_year}-{required_month or 1:02d}) : le profil ne peut pas y répondre.",
        0.80,
    )


def _fact_date(fact: ProfileFact) -> tuple[int | None, int | None]:
    year, month = _date_parts(fact.value)
    if year is None:
        year, month = _date_parts(fact.quote)
    if year is None:
        year, month = _date_parts(fact.detail)
    if year is None and fact.year:
        year, month = fact.year, month
    return year, month


def _handle_diplomation(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    text = clean_text(record.get("text"), limit=400)
    graduation_facts = facts.by_category("diplomation")
    if not graduation_facts:
        return ("to_verify", None, "Aucune date de diplomation approuvée dans le profil : à vérifier.", 0.60)
    required_year, required_month = _date_parts(text)
    best = graduation_facts[0]
    profile_year, profile_month = _fact_date(best)
    if required_year is None:
        return (
            "supported",
            best,
            f"Date de diplomation approuvée : « {_quote(best)} ».",
            0.80,
        )
    if profile_year is None:
        return (
            "to_verify",
            best,
            f"Date de diplomation approuvée non datable (« {_quote(best)} ») : à vérifier.",
            0.55,
        )
    if _date_leq((profile_year, profile_month), (required_year, required_month)):
        return (
            "supported",
            best,
            f"Diplôme approuvé ({profile_year}-{profile_month or 1:02d}) obtenu avant l'exigence "
            f"({required_year}-{required_month or 1:02d}) : fait approuvé « {_quote(best)} ».",
            0.85,
        )
    return (
        "contradicted",
        best,
        f"Diplôme approuvé ({profile_year}-{profile_month or 1:02d}) postérieur à l'exigence "
        f"({required_year}-{required_month or 1:02d}) : le profil ne répond pas à l'exigence.",
        0.80,
    )


def _handle_other(record: Mapping[str, Any], facts: _Facts, modality: str) -> tuple[str, ProfileFact | None, str, float]:
    return (
        "to_verify",
        None,
        "Exigence hors des catégories de correspondance : à vérifier manuellement.",
        0.50,
    )


_HANDLERS = {
    "etudes": _handle_etudes,
    "experience": _handle_experience,
    "tech": _handle_tech,
    "outils": _handle_tech,
    "langues": _handle_langues,
    "mobilite": _handle_mobilite,
    "auth_travail": _handle_auth_travail,
    "dispo": _handle_dispo,
    "diplomation": _handle_diplomation,
    "other": _handle_other,
}


# -------------------------------------------------------------------- score

_VERDICT_WEIGHT: dict[str, float | None] = {
    "supported": 1.0,
    "to_verify": 0.5,
    "unsupported": 0.0,
    "contradicted": 0.0,
    "not_applicable": None,
}

_MODALITY_WEIGHT: dict[str, float] = {
    "mandatory": 1.0,
    "preferred": 0.5,
    "unknown": 0.5,
    "contextual": 0.0,
}


def _overall_score(fits: Sequence[RequirementFit]) -> float:
    numerator = 0.0
    denominator = 0.0
    for fit in fits:
        verdict_weight = _VERDICT_WEIGHT.get(fit.verdict)
        modality_weight = _MODALITY_WEIGHT.get(fit.modality, 0.5)
        if verdict_weight is None or modality_weight <= 0:
            continue
        numerator += verdict_weight * modality_weight
        denominator += modality_weight
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


# --------------------------------------------------------------------- API


def analyze_fit(
    offer_or_analysis: Mapping[str, Any],
    approved_profile: ApprovedProfile | Mapping[str, Any] | Sequence[Any],
) -> FitResult:
    """Compare the canonical requirements of an offer with an approved profile.

    ``offer_or_analysis`` is either an offer dict (the canonical requirements
    are then extracted with ``offer_requirements.analyze_offer()``) or an
    already computed analysis of that contract.  ``approved_profile`` is an
    :class:`ApprovedProfile`, a mapping of facts/sections, or a sequence of
    facts.

    The function is pure and deterministic: the offer is never modified and no
    profile data is ever written back into it.
    """
    analysis = _coerce_analysis(offer_or_analysis)
    profile = _coerce_profile(approved_profile)
    facts = _Facts(profile.approved_facts())

    fits: list[RequirementFit] = []
    for record in analysis.get("requirements", []):
        fits.append(_fit_one(record, facts))

    supported = sum(1 for fit in fits if fit.verdict == "supported")
    unsupported = sum(1 for fit in fits if fit.verdict == "unsupported")
    to_verify = sum(1 for fit in fits if fit.verdict == "to_verify")
    contradicted = sum(1 for fit in fits if fit.verdict == "contradicted")
    missing_critical = [
        fit.requirement_id
        for fit in fits
        if fit.modality == "mandatory" and fit.verdict != "supported"
    ]
    return FitResult(
        fits=fits,
        supported_count=supported,
        unsupported_count=unsupported,
        to_verify_count=to_verify,
        contradicted_count=contradicted,
        overall_score=_overall_score(fits),
        missing_critical=missing_critical,
    )


def _coerce_analysis(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    requirements = payload.get("requirements")
    if (
        isinstance(requirements, Sequence)
        and not isinstance(requirements, (str, bytes))
        and requirements
        and all(isinstance(item, Mapping) and "id" in item and "text" in item for item in requirements)
    ):
        return payload
    return analyze_offer(dict(payload))


def _coerce_profile(profile: ApprovedProfile | Mapping[str, Any] | Sequence[Any]) -> ApprovedProfile:
    if isinstance(profile, ApprovedProfile):
        return profile
    if isinstance(profile, Mapping):
        return ApprovedProfile.from_dict(profile)
    if isinstance(profile, Sequence) and not isinstance(profile, (str, bytes)):
        return ApprovedProfile(facts=tuple(_fact_from_payload(item, index=index) for index, item in enumerate(profile)))
    return ApprovedProfile()


def _fit_one(record: Mapping[str, Any], facts: _Facts) -> RequirementFit:
    text = clean_text(record.get("text"), limit=400)
    category = _fit_category(record)
    modality = _fit_modality(record)
    requirement_id = clean_text(record.get("id"), limit=80)
    locator = clean_text(record.get("locator"), limit=40)
    source_field = clean_text(record.get("source_field"), limit=40)
    citation = f"{source_field} {locator}".strip()

    if record.get("injection_suspect"):
        return RequirementFit(
            requirement_id=requirement_id,
            requirement_text=text,
            modality=modality,
            category=category,
            verdict="not_applicable",
            profile_evidence=None,
            evidence_offset=None,
            reason=(
                "Passage signalé comme tentative d'instruction : il reste une donnée inerte "
                "et n'est jamais traité comme une exigence."
            ),
            confidence=0.95,
        )
    if record.get("negated") or modality == "contextual":
        return RequirementFit(
            requirement_id=requirement_id,
            requirement_text=text,
            modality=modality,
            category=category,
            verdict="not_applicable",
            profile_evidence=None,
            evidence_offset=None,
            reason=(
                "Énoncé négativé ou contextuel : aucune obligation à satisfaire n'y est formulée."
            ),
            confidence=0.90,
        )

    handler = _HANDLERS.get(category, _handle_other)
    verdict, evidence, reason, confidence = handler(record, facts, modality)
    if citation:
        reason = f"{reason} [exigence : {citation}]"
    return RequirementFit(
        requirement_id=requirement_id,
        requirement_text=text,
        modality=modality,
        category=category,
        verdict=verdict,
        profile_evidence=_quote(evidence) or None,
        evidence_offset=evidence.offset if evidence is not None else None,
        reason=reason,
        confidence=round(float(confidence), 2),
    )


__all__ = [
    "analyze_fit",
    "ApprovedProfile",
    "ProfileFact",
    "RequirementFit",
    "FitResult",
    "VERDICTS",
    "MODALITIES",
    "FIT_CATEGORIES",
    "REQUIRED_FIT_CATEGORIES",
    "CATEGORY_LABELS",
    "FACT_STATUSES",
    "APPROVED_STATUSES",
]
