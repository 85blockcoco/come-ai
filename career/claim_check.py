"""Deterministic claim-by-claim audit of an application dossier (SPEC-042).

The module answers one question per sentence: *which approved fact proves
this?*  It never calls a model, never performs a request and never rewrites a
fact on its own.  A sentence is compared with an explicit evidence ledger
(approved profile facts, optionally enriched with the level and the date
returned by the evidence service).  The verdict vocabulary is closed:

``supported``
    The sentence is covered by approved evidence.
``inflated``
    The sentence is covered but adds an unproven level or an exaggeration
    ("expert" without supported years, guaranteed result, sentimental appeal).
``out_of_context``
    Every ingredient exists in the ledger, but they come from different
    contexts and are stitched together in a way no single proof supports.
``invented``
    A number, entity, skill or credential in the sentence is absent from the
    approved evidence.
``unverifiable``
    The sentence is too vague (or has no approved proof) to be verified.

Everything is local, reproducible and user-editable: the exaggeration rules
live in ``career/dossier_quality_rules.json`` (versioned) and can be replaced
by passing ``rules_path=``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from career.models import clean_text, normalized_text

LABELS: tuple[str, ...] = (
    "supported",
    "inflated",
    "out_of_context",
    "invented",
    "unverifiable",
)
LABEL_LABELS: dict[str, str] = {
    "supported": "étayé",
    "inflated": "exagéré",
    "out_of_context": "hors contexte",
    "invented": "inventé",
    "unverifiable": "non vérifiable",
}

DEFAULT_RULES_PATH = Path(__file__).with_name("dossier_quality_rules.json")
RULES_ENV_VAR = "COME_DOSSIER_QUALITY_RULES"

MAX_CLAIMS = 400
MAX_DOCUMENT_CHARS = 200_000
MAX_EVIDENCE = 1_000
MAX_QUOTE = 2_000

EVIDENCE_LEVELS: tuple[str, ...] = ("declared", "documented", "verified", "quantified")
_LEVEL_ALIASES: dict[str, str] = {
    "declared": "declared",
    "self_declared": "declared",
    "self-declared": "declared",
    "weak": "declared",
    "documented": "documented",
    "document": "documented",
    "medium": "documented",
    "verified": "verified",
    "strong": "verified",
    "confirmed": "verified",
    "quantified": "quantified",
    "measured": "quantified",
    "chiffre": "quantified",
}

APPROVED_STATUSES: frozenset[str] = frozenset({"approved", "modified"})

# --------------------------------------------------------------------- lexicons

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "afin", "ai", "ainsi", "au", "aucun", "aucune", "aujourd", "auquel",
        "aussi", "autre", "autres", "aux", "avec", "avoir", "avons", "ayant",
        "ce", "cet", "cette", "ces", "cependant", "chaque", "chez", "ci",
        "comme", "comment", "dans", "de", "des", "du", "dedans", "deja",
        "depuis", "derriere", "dessous", "dessus", "deux", "devant", "doit",
        "donc", "dont", "durant", "elle", "elles", "en", "encore", "entre",
        "est", "et", "etaient", "etait", "etant", "ete", "etre", "eu", "eux",
        "fait", "faire", "fais", "faites", "font", "grace", "il", "ils", "j",
        "je", "jusqu", "l", "la", "le", "les", "leur", "leurs", "lui", "ma",
        "mais", "me", "mes", "mien", "moi", "mon", "meme", "mes", "moins",
        "ne", "ni", "non", "nos", "notre", "nous", "on", "ont", "ou", "oui",
        "par", "parce", "parmi", "pas", "pendant", "peu", "plus", "plusieurs",
        "pour", "pourquoi", "premier", "premiere", "pres", "puis", "qu",
        "quand", "que", "quel", "quelle", "quelles", "quels", "qui", "quoi",
        "sa", "sans", "se", "selon", "sera", "serai", "serais", "seront",
        "ses", "si", "sien", "soi", "soit", "sommes", "son", "sont", "sous",
        "suis", "es", "etes", "etait", "etaient",
        "ans", "an", "annee", "annees", "mois", "personne", "personnes",
        "client", "clients", "euro", "euros", "eur",
        "sur", "ta", "te", "tes", "toi", "ton", "toujours", "tous", "tout",
        "toute", "toutes", "tres", "tu", "un", "une", "va", "vais", "vers",
        "via", "voici", "voila", "vos", "votre", "vous", "y",
        "about", "after", "all", "also", "an", "and", "any", "are", "as",
        "at", "be", "because", "been", "being", "both", "but", "by", "can",
        "could", "did", "do", "does", "during", "each", "few", "for", "from",
        "had", "has", "have", "having", "he", "her", "here", "hers", "him",
        "his", "how", "i", "if", "in", "into", "is", "it", "its", "just",
        "me", "more", "most", "my", "no", "not", "of", "on", "only", "or",
        "other", "our", "out", "over", "own", "same", "she", "should", "so",
        "some", "such", "than", "that", "the", "their", "them", "then",
        "there", "these", "they", "this", "those", "through", "to", "too",
        "under", "until", "up", "very", "was", "we", "were", "what", "when",
        "where", "which", "while", "who", "whom", "why", "will", "with",
        "would", "you", "your",
    }
)

# Light verbs and filler words: they express style, never a fact.  Keeping
# them out of the topic tokens avoids flagging "j'ai réalisé une analyse"
# just because the evidence says "analyse financière".
_LIGHT_VERBS: frozenset[str] = frozenset(
    {
        "realise", "realisee", "realiser", "effectue", "effectuee", "effectuer",
        "participe", "participee", "participer", "contribue", "contribuee",
        "contribuer", "developpe", "developpee", "developper", "gere", "geree",
        "gerer", "pilote", "pilolee", "piloter", "mene", "menee", "mener",
        "assure", "assuree", "assurer", "fais", "fait", "faire", "travaille",
        "travaillee", "travailler", "occupe", "occupee", "occuper", "porte",
        "portee", "souhaite", "souhaiter", "peux", "puis", "veux", "vouloir",
        "maitrise", "maitrisee", "maitriser", "connais", "connait", "connaitre",
        "obtenu", "obtenue", "obtenir", "suis", "etudie", "etudiee", "etudier",
        "mis", "mise", "mettre", "utilise", "utilisee", "utiliser", "cree",
        "creee", "creer", "dirige", "dirigee", "diriger", "encadre",
        "encadree", "encadrer", "coordonne", "coordonnee", "coordonner",
        "develop", "developed", "manage", "managed", "led", "worked",
        "created", "built", "used", "ensure", "ensured",
    }
)

_MONTHS_DAYS: frozenset[str] = frozenset(
    {
        "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
        "aout", "septembre", "octobre", "novembre", "decembre", "janv",
        "fevr", "sept", "oct", "nov", "dec", "lundi", "mardi", "mercredi",
        "jeudi", "vendredi", "samedi", "dimanche", "january", "february",
        "march", "april", "may", "june", "july", "august", "september",
        "october", "november", "december", "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday",
    }
)

_SENTENCE_STARTERS: frozenset[str] = frozenset(
    {
        "je", "j", "mon", "ma", "mes", "notre", "nos", "le", "la", "les",
        "un", "une", "des", "du", "de", "ce", "cet", "cette", "ces", "son",
        "sa", "ses", "leur", "leurs", "pour", "dans", "avec", "sur", "sous",
        "en", "au", "aux", "grace", "apres", "avant", "depuis", "durant",
        "pendant", "lors", "ainsi", "tout", "tous", "toute", "toutes",
        "candidature", "madame", "monsieur", "mesdames", "messieurs", "cher",
        "chere", "objet", "re", "entreprise", "poste", "lieu", "contact",
        "competences", "experiences", "formation", "langues", "profil",
        "education", "experience", "skills", "languages", "application",
        "dear", "to", "the", "my", "our", "we", "i",
    }
)

_HEADING_LABELS: frozenset[str] = frozenset(
    {
        "profil cible", "profil cible pour cette offre", "formation", "experiences",
        "experience", "competences", "langues", "ciblage de l offre",
        "ciblage de l offre et elements a verifier", "coordonnees", "contact",
        "education", "skills", "languages", "targeted profile", "application focus",
        "cover letter", "lettre de motivation", "curriculum vitae", "cv",
        "informations complementaires", "centres d interet",
    }
)

_CONTACT_RE = re.compile(
    r"@|https?://|www\.|(?:linkedin|github)\.com|\+?\d[\d .()\-]{7,}\d", re.IGNORECASE
)

_OFFER_MARKERS: tuple[str, ...] = (
    "votre offre", "l offre", "offre mentionne", "offre indique", "offre precise",
    "cette offre", "cette opportunite", "candidature au poste",
    "candidature pour le poste", "candidature au sein", "je vous adresse ma candidature",
    "the offer", "offer details", "job description", "position at", "application for",
    "i am applying", "role of",
)

_METADATA_PREFIXES: tuple[str, ...] = (
    "entreprise", "poste", "lieu", "objet", "re", "role", "location", "subject",
    "company", "position",
)

_BOILERPLATE_MARKERS: tuple[str, ...] = (
    "madame monsieur", "madame, monsieur", "mesdames messieurs", "dear hiring team",
    "dear sir", "dear madam", "je vous prie d agreer", "salutations distinguees",
    "cordialement", "bien cordialement", "sincerely", "best regards", "kind regards",
    "je vous remercie", "je me tiens a votre disposition", "je serais heureux",
    "je serais heureuse", "je souhaite", "n hesitez pas", "do not hesitate",
    "i would be glad", "i would welcome the opportunity", "i look forward",
    "thank you for considering my application",
)

_PLACEHOLDER_RE = re.compile(r"\[[^\]]{1,120}\]|«\s*[^»]{0,120}\s*»")

_NUMBER_RE = re.compile(
    r"(?<![\w])(\d{1,4}(?:[.,]\d+)?)\s*"
    r"(%|€|euros?|k€|m€|k|m|ans?|ann[eé]es?|mois|personnes?|clients?|projets?|x)?"
    r"(?![\w])",
    re.IGNORECASE,
)
_YEARS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:ans?|ann[eé]es?|years?)\b", re.IGNORECASE)
_MONTHS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*mois\b", re.IGNORECASE)

_PROPER_RE = re.compile(
    r"(?<![\wÀ-ÿ])("
    r"[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’.-]*"
    r"(?:\s+(?:de|du|des|la|le|les|&|and)\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’.-]*"
    r"|\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’.-]*)*"
    r")"
)

_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "m", "mm", "mme", "mmes", "mlle", "dr", "pr", "etc", "ex", "cf",
        "env", "p", "pp", "no", "nos", "vs", "st", "ste", "av", "bd", "fig",
        "janv", "fevr", "sept", "oct", "nov", "dec",
    }
)


# ------------------------------------------------------------------------ rules


@dataclass(frozen=True, slots=True)
class Ruleset:
    """Versioned local exaggeration rules, loaded from a user-editable file."""

    version: str
    source_path: str
    ats_repetition_threshold: int
    expert_min_years: int
    senior_min_years: int
    rules: tuple[dict[str, Any], ...]
    generic_phrases: tuple[str, ...]
    skill_terms: tuple[str, ...]
    credential_terms: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    patterns: Mapping[str, re.Pattern[str]] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_path": self.source_path,
            "ats_repetition_threshold": self.ats_repetition_threshold,
            "expert_min_years": self.expert_min_years,
            "senior_min_years": self.senior_min_years,
            "rule_count": len(self.rules),
            "rules": [dict(rule) for rule in self.rules],
            "generic_phrases": list(self.generic_phrases),
            "skill_terms": list(self.skill_terms),
            "credential_terms": list(self.credential_terms),
            "warnings": list(self.warnings),
        }


_FALLBACK_RULES: dict[str, Any] = {
    "version": "fallback",
    "ats_repetition_threshold": 3,
    "expert_min_years": 5,
    "senior_min_years": 3,
    "rules": [
        {
            "id": "expert_without_years",
            "category": "factual_taboo",
            "pattern": r"\bexperts?\b|\bexpertise\b",
            "severity": "high",
            "min_years": 5,
            "label": "« expert » sans années d'expérience appuyées",
            "suggestion": "Supprime « expert » ou remplace-le par un niveau approuvé.",
        },
        {
            "id": "senior_without_years",
            "category": "factual_taboo",
            "pattern": r"\bseniors?\b",
            "severity": "high",
            "min_years": 3,
            "label": "« senior » sans années d'expérience appuyées",
            "suggestion": "Supprime « senior » ou appuie-le sur une preuve approuvée.",
        },
        {
            "id": "guaranteed_result",
            "category": "undocumented_promise",
            "pattern": r"\bgaranti[e]?s?\b|\bpromets?\b|\bpromis[e]?s?\b",
            "severity": "high",
            "label": "promesse de résultat non documentée",
            "suggestion": "Retire la promesse : elle n'est pas démontrable.",
        },
        {
            "id": "sentimental_appeal",
            "category": "sentimental_appeal",
            "pattern": r"\bpassionn?[eé]?e?s?\b|\bpassion\b|\bdepuis toujours\b",
            "severity": "low",
            "label": "appel sentimental non vérifiable",
            "suggestion": "Remplace l'appel sentimental par un fait approuvé.",
        },
        {
            "id": "superlative_claim",
            "category": "intensifier",
            "pattern": r"\b(extr[eê]mement|parfaitement|totalement|meilleur[e]?s?|unique)\b",
            "severity": "medium",
            "label": "superlatif non démontrable",
            "suggestion": "Supprime le superlatif ou remplace-le par un fait chiffré approuvé.",
        },
        {
            "id": "inflated_anglicism",
            "category": "inflated_anglicism",
            "pattern": r"\b(rockstar|ninja|guru|game[- ]changer|world[- ]class)\b",
            "severity": "medium",
            "label": "anglicisme gonflé non démontrable",
            "suggestion": "Remplace l'anglicisme par l'intitulé factuel de la compétence.",
        },
    ],
    "generic_phrases": [
        "motivé", "motivée", "dynamique", "rigoureux", "rigoureuse", "esprit d'équipe",
        "team player", "capacité d'adaptation", "proactif", "polyvalent", "autonome",
        "excellent relationnel", "sens du contact", "leadership",
    ],
    "skill_terms": [
        "excel", "python", "sql", "vba", "bloomberg", "lbo", "dcf", "valuation",
        "modélisation", "modelisation", "analyse financière", "analyse financiere",
        "comptabilité", "comptabilite", "audit", "ifrs", "cfa", "cpa", "git",
        "java", "javascript", "sap", "oracle", "salesforce", "machine learning",
        "data science", "marketing", "communication", "gestion de projet", "management",
    ],
    "credential_terms": [
        "master", "licence", "bachelor", "mba", "phd", "doctorat", "baccalauréat",
        "baccalaureat", "certification", "certificat", "diplôme", "diplome", "cfa", "cpa",
    ],
}


def _normalize_phrase_list(values: Any) -> tuple[str, ...]:
    out: list[str] = []
    for value in values if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else ():
        normalized = normalized_text(value)
        if normalized and normalized not in out:
            out.append(normalized)
    return tuple(out)


def load_rules(path: str | os.PathLike[str] | None = None) -> Ruleset:
    """Load the versioned rules file, falling back safely when it is invalid."""

    warnings: list[str] = []
    candidate = path or os.environ.get(RULES_ENV_VAR) or DEFAULT_RULES_PATH
    resolved = Path(candidate)
    payload: dict[str, Any]
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("la racine du fichier de règles doit être un objet JSON")
        source_path = str(resolved)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        warnings.append(
            f"Règles locales illisibles ({resolved}) : {error}. Repli sur les règles intégrées."
        )
        payload = dict(_FALLBACK_RULES)
        source_path = "<fallback>"

    raw_rules = payload.get("rules")
    rules: list[dict[str, Any]] = []
    patterns: dict[str, re.Pattern[str]] = {}
    for index, raw in enumerate(raw_rules if isinstance(raw_rules, list) else []):
        if not isinstance(raw, Mapping):
            warnings.append(f"Règle #{index + 1} ignorée : elle n'est pas un objet.")
            continue
        rule_id = clean_text(raw.get("id"), limit=80) or f"rule_{index + 1}"
        pattern = clean_text(raw.get("pattern"), limit=1_000)
        if not pattern:
            warnings.append(f"Règle {rule_id} ignorée : motif vide.")
            continue
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as error:
            warnings.append(f"Règle {rule_id} ignorée : motif invalide ({error}).")
            continue
        rule = {
            "id": rule_id,
            "category": clean_text(raw.get("category"), limit=80) or "other",
            "severity": clean_text(raw.get("severity"), limit=20) or "medium",
            "label": clean_text(raw.get("label"), limit=300) or rule_id,
            "suggestion": clean_text(raw.get("suggestion"), limit=800),
            "pattern": pattern,
            "requires": clean_text(raw.get("requires"), limit=40).lower(),
        }
        min_years = raw.get("min_years")
        if isinstance(min_years, int) and min_years > 0:
            rule["min_years"] = min_years
        rules.append(rule)
        patterns[rule_id] = compiled

    def _positive_int(key: str, default: int) -> int:
        value = payload.get(key, default)
        if isinstance(value, int) and value >= 1:
            return value
        warnings.append(f"Valeur {key} invalide : {value!r}. Valeur par défaut {default} utilisée.")
        return default

    return Ruleset(
        version=clean_text(payload.get("version"), limit=80) or "unknown",
        source_path=source_path,
        ats_repetition_threshold=_positive_int("ats_repetition_threshold", 3),
        expert_min_years=_positive_int("expert_min_years", 5),
        senior_min_years=_positive_int("senior_min_years", 3),
        rules=tuple(rules),
        generic_phrases=_normalize_phrase_list(payload.get("generic_phrases")),
        skill_terms=_normalize_phrase_list(payload.get("skill_terms")),
        credential_terms=_normalize_phrase_list(payload.get("credential_terms")),
        warnings=tuple(warnings),
        patterns=patterns,
    )


# --------------------------------------------------------------------- evidence


@dataclass(frozen=True, slots=True)
class NumberAnchor:
    """One number found in a claim or in an approved evidence quote."""

    value: str
    unit: str
    raw: str

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value, "unit": self.unit, "raw": self.raw}


@dataclass(frozen=True, slots=True)
class ApprovedEvidence:
    """One approved fact usable as proof, with its level and its date."""

    evidence_id: str
    fact_id: str
    category: str
    source: str
    quote: str
    level: str
    dated_at: str | None
    years: int | None
    normalized: str
    tokens: frozenset[str]
    numbers: tuple[NumberAnchor, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "fact_id": self.fact_id,
            "category": self.category,
            "source": self.source,
            "quote": self.quote,
            "level": self.level,
            "dated_at": self.dated_at,
            "years": self.years,
        }


def _number_anchors(text: str) -> tuple[NumberAnchor, ...]:
    anchors: list[NumberAnchor] = []
    seen: set[tuple[str, str]] = set()
    for match in _NUMBER_RE.finditer(text):
        raw_value = match.group(1).replace(",", ".")
        if raw_value.endswith(".0"):
            raw_value = raw_value[:-2]
        raw_unit = (match.group(2) or "").strip().lower()
        if raw_unit in {"%", "€", "k€", "m€"}:
            unit = raw_unit
        else:
            unit = normalized_text(raw_unit)
            unit = {
                "annee": "ans",
                "annees": "ans",
                "year": "ans",
                "years": "ans",
                "euro": "eur",
                "euros": "eur",
                "personne": "personnes",
                "client": "clients",
                "projet": "projets",
                "k": "k",
                "m": "m",
            }.get(unit, unit)
        if not unit and re.fullmatch(r"(?:19|20)\d{2}", raw_value):
            unit = "annee"
        key = (raw_value, unit)
        if key in seen:
            continue
        seen.add(key)
        anchors.append(NumberAnchor(value=raw_value, unit=unit, raw=match.group(0).strip()))
    return tuple(anchors)


def _explicit_years(text: str) -> int | None:
    years = [float(match.group(1).replace(",", ".")) for match in _YEARS_RE.finditer(text)]
    if years:
        return int(max(years))
    months = [float(match.group(1).replace(",", ".")) for match in _MONTHS_RE.finditer(text)]
    if months:
        return int(max(months) // 12)
    return None


def _level(value: Any, quote: str, payload: Mapping[str, Any]) -> str:
    raw = normalized_text(value or payload.get("evidence_level") or payload.get("strength") or "")
    mapped = _LEVEL_ALIASES.get(raw)
    if mapped:
        return mapped
    if payload.get("verified_at") or payload.get("verified") is True:
        return "verified"
    if _number_anchors(quote):
        return "quantified"
    return "declared"


def _evidence_from_payload(
    payload: Any,
    *,
    index: int,
    default_category: str = "other",
    default_source: str = "profile",
    default_date: str | None = None,
) -> ApprovedEvidence | None:
    if isinstance(payload, ApprovedEvidence):
        return payload
    if isinstance(payload, str):
        data: Mapping[str, Any] = {"value": payload}
    elif isinstance(payload, Mapping):
        data = payload
    else:
        return None

    status = normalized_text(data.get("status") or "approved").replace(" ", "_")
    if status and status not in APPROVED_STATUSES:
        return None

    quote = clean_text(
        data.get("quote") or data.get("text") or data.get("value") or data.get("detail"),
        limit=MAX_QUOTE,
    )
    if not quote:
        return None
    fact_id = clean_text(data.get("fact_id") or data.get("id"), limit=120) or f"fact_{index:04d}"
    category = normalized_text(
        data.get("category") or data.get("type") or data.get("topic") or default_category
    ).replace(" ", "_") or "other"
    source = normalized_text(data.get("source") or default_source).replace(" ", "_") or "other"
    dated_at = clean_text(
        data.get("dated_at")
        or data.get("proof_date")
        or data.get("approved_at")
        or data.get("date")
        or data.get("verified_at")
        or data.get("retrieved_at")
        or data.get("updated_at")
        or default_date,
        limit=64,
    ) or None
    level = _level(data.get("level"), quote, data)
    years = data.get("years")
    if not isinstance(years, int) or years <= 0:
        months = data.get("months")
        years = int(months) // 12 if isinstance(months, int) and months > 0 else _explicit_years(quote)
    normalized = normalized_text(quote)
    return ApprovedEvidence(
        evidence_id=clean_text(data.get("evidence_id"), limit=120) or f"ev_{index:04d}",
        fact_id=fact_id,
        category=category,
        source=source,
        quote=quote,
        level=level,
        dated_at=dated_at,
        years=years,
        normalized=normalized,
        tokens=frozenset(normalized.split()),
        numbers=_number_anchors(quote),
    )


_PROFILE_LEDGER_FIELDS: tuple[str, ...] = (
    "display_name",
    "contact_email",
    "contact_phone",
    "linkedin_url",
    "education",
    "experience",
    "skills",
    "languages",
    "eligibility",
    "availability",
    "strengths",
    "missions",
)


def _append_mapping_facts(
    payload: Mapping[str, Any],
    *,
    default_date: str | None,
    default_source: str = "profile",
) -> list[ApprovedEvidence]:
    out: list[ApprovedEvidence] = []
    raw_facts = payload.get("facts")
    if isinstance(raw_facts, Sequence) and not isinstance(raw_facts, (str, bytes)):
        for item in raw_facts:
            evidence = _evidence_from_payload(item, index=len(out), default_date=default_date, default_source=default_source)
            if evidence is not None:
                out.append(evidence)
        return out

    for key in _PROFILE_LEDGER_FIELDS:
        if key not in payload:
            continue
        value = payload.get(key)
        default_category = key
        if isinstance(value, str):
            chunks = [line.strip(" •-\t") for line in value.splitlines() if line.strip(" •-\t")]
            if len(chunks) == 1 and ";" in chunks[0]:
                chunks = [part.strip() for part in chunks[0].split(";") if part.strip()]
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            chunks = [str(item) for item in value if str(item).strip()]
        else:
            continue
        for chunk in chunks:
            evidence = _evidence_from_payload(
                {"value": chunk, "category": default_category, "source": default_source},
                index=len(out),
                default_date=default_date,
                default_source=default_source,
            )
            if evidence is not None:
                out.append(evidence)
    return out


def build_evidence_ledger(
    source: Any = None,
    *,
    extra_facts: Any = None,
) -> tuple[ApprovedEvidence, ...]:
    """Normalise approved facts into a deterministic evidence ledger.

    ``source`` may be a profile mapping, a list of facts, an ``ApprovedProfile``
    from :mod:`career.requirements_fit`, or a local evidence service exposing
    ``approved_facts()`` / ``list_approved_evidence()``.  Only ``approved`` and
    ``modified`` facts are kept.  No network access is ever attempted.
    """

    collected: list[ApprovedEvidence] = []

    def _collect(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, ApprovedEvidence):
            collected.append(value)
            return
        if isinstance(value, Mapping):
            date = clean_text(value.get("updated_at") or value.get("approved_at"), limit=64) or None
            collected.extend(_append_mapping_facts(value, default_date=date))
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                if isinstance(item, ApprovedEvidence):
                    collected.append(item)
                else:
                    evidence = _evidence_from_payload(item, index=len(collected))
                    if evidence is not None:
                        collected.append(evidence)
            return
        for method_name in ("approved_facts", "list_approved_evidence", "get_approved_evidence"):
            method = getattr(value, method_name, None)
            if not callable(method):
                continue
            try:
                result = method()
            except Exception:
                continue
            _collect(result)
            return

    _collect(source)
    _collect(extra_facts)

    deduped: list[ApprovedEvidence] = []
    seen: set[tuple[str, str]] = set()
    for evidence in collected:
        key = (evidence.normalized, evidence.category)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(evidence)
        if len(deduped) >= MAX_EVIDENCE:
            break
    return tuple(deduped)


# ---------------------------------------------------------------------- context


@dataclass(frozen=True, slots=True)
class AuditContext:
    entities: frozenset[str]
    contacts: frozenset[str]
    terms: frozenset[str]
    numbers: frozenset[str]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "entities": sorted(self.entities),
            "contacts": sorted(self.contacts),
            "terms": sorted(self.terms),
            "numbers": sorted(self.numbers),
        }


def _build_context(context: Mapping[str, Any] | None) -> AuditContext:
    context = context or {}

    def _values(*keys: str) -> list[str]:
        out: list[str] = []
        for key in keys:
            value = context.get(key)
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                out.extend(str(item) for item in value)
        return out

    entities = frozenset(
        normalized_text(item) for item in _values("entities", "companies", "job_entities") if normalized_text(item)
    )
    contacts = frozenset(
        normalized_text(item) for item in _values("contacts") if normalized_text(item)
    )
    terms = frozenset(
        normalized_text(item) for item in _values("terms", "offer_terms") if normalized_text(item)
    )
    numbers = frozenset(
        anchor.value for item in _values("numbers") for anchor in _number_anchors(item)
    )
    return AuditContext(entities=entities, contacts=contacts, terms=terms, numbers=numbers)


# ------------------------------------------------------------------ text split


@dataclass(frozen=True, slots=True)
class _RawClaim:
    text: str
    section: str
    offset: int
    list_id: str | None


def _split_sentences(line: str) -> list[tuple[str, int]]:
    parts: list[tuple[str, int]] = []
    start = 0
    index = 0
    length = len(line)
    while index < length:
        character = line[index]
        if character not in ".!?;":
            index += 1
            continue
        if character == "." and index < length - 1:
            if not line[index + 1].isspace():
                index += 1
                continue
            if line[index - 1].isdigit() and line[index + 1].isdigit():
                index += 1
                continue
        before = re.search(r"([A-Za-zÀ-ÿ]+)$", line[:index])
        word = before.group(1).lower() if before else ""
        if character == "." and (word in _ABBREVIATIONS or len(word) == 1):
            index += 1
            continue
        piece = line[start : index + 1].strip()
        if piece:
            parts.append((piece, start))
        start = index + 1
        index += 1
    tail = line[start:].strip()
    if tail:
        offset = line.find(tail, start)
        parts.append((tail, offset if offset >= 0 else start))
    return parts


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    normalized = normalized_text(stripped)
    if normalized in _HEADING_LABELS:
        return True
    if stripped.endswith(":") and len(stripped.split()) <= 6:
        return True
    if stripped.startswith("[") and stripped.endswith("]"):
        return True
    if stripped.isupper() and len(stripped.split()) <= 8:
        return True
    return False


def _raw_claims(document: Any) -> list[_RawClaim]:
    sections: list[tuple[str, str]]
    if isinstance(document, Mapping):
        sections = [(str(name), clean_text(value, limit=MAX_DOCUMENT_CHARS)) for name, value in document.items()]
    else:
        sections = [("document", clean_text(document, limit=MAX_DOCUMENT_CHARS))]

    claims: list[_RawClaim] = []
    for section, text in sections:
        bullet_block = 0
        previous_bullet = False
        offset = 0
        for raw_line in text.splitlines():
            line_start = offset
            offset += len(raw_line) + 1
            stripped = raw_line.strip()
            if not stripped:
                previous_bullet = False
                continue
            is_bullet = bool(re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", raw_line))
            if is_bullet and not previous_bullet:
                bullet_block += 1
            previous_bullet = is_bullet
            if stripped.startswith("#"):
                continue
            cleaned = re.sub(r"^#{1,6}\s*", "", stripped)
            cleaned = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", cleaned).strip()
            if not cleaned or _is_heading(cleaned):
                continue
            list_id = f"{section}:{bullet_block}" if is_bullet else None
            for sentence, sentence_offset in _split_sentences(cleaned):
                claims.append(
                    _RawClaim(
                        text=sentence,
                        section=section,
                        offset=line_start + sentence_offset,
                        list_id=list_id,
                    )
                )
                if len(claims) >= MAX_CLAIMS:
                    return claims
    return claims


# ------------------------------------------------------------------ classifiers


def _topic_tokens(text: str, generic_words: frozenset[str]) -> set[str]:
    tokens = set()
    for token in normalized_text(text).split():
        if token in _STOPWORDS or token in _LIGHT_VERBS or token in _MONTHS_DAYS:
            continue
        if token in generic_words or len(token) < 3 or token.isdigit():
            continue
        tokens.add(token)
    return tokens


def _proper_nouns(text: str, context: AuditContext) -> list[str]:
    out: list[str] = []
    for match in _PROPER_RE.finditer(text):
        raw = match.group(1)
        normalized = normalized_text(raw)
        if not normalized or len(normalized.replace(" ", "")) < 2:
            continue
        first = normalized.split()[0]
        if match.start() == 0:
            # A sentence-initial capital is grammar, not a named entity.
            continue
        if first in _SENTENCE_STARTERS or first in _MONTHS_DAYS:
            continue
        if normalized in context.entities or normalized in context.contacts:
            continue
        if normalized not in out:
            out.append(normalized)
    return out


def _skill_matches(text: str, terms: Sequence[str]) -> list[str]:
    normalized = f" {normalized_text(text)} "
    return [term for term in terms if f" {term} " in normalized]


def _contact_or_offer(text: str, context: AuditContext) -> str | None:
    normalized = normalized_text(text)
    candidate_voice = bool(
        re.search(r"\b(je|j|nous|mon|ma|mes|notre|nos|my|i|we|our|have|ai|suis|am)\b", f" {normalized} ")
    )
    # Placeholders have their own hard gate in the application kit.  Auditing
    # the surrounding template as if it were a candidate fact produces noisy
    # duplicate warnings and hides the useful corrections.
    if _PLACEHOLDER_RE.search(text):
        return "boilerplate"
    if _CONTACT_RE.search(text):
        return "contact"
    if normalized in context.contacts:
        return "contact"
    if normalized in context.entities and len(normalized.split()) <= 6:
        return "offer_reference"
    context_tokens = {token for entity in context.entities for token in entity.split()}
    if normalized.split() and set(normalized.split()) <= context_tokens and len(normalized.split()) <= 8:
        return "offer_reference"
    if ":" in text:
        prefix = normalized_text(text.split(":", 1)[0])
        if prefix in _METADATA_PREFIXES or prefix.split()[:1] and prefix.split()[0] in _METADATA_PREFIXES:
            return "offer_reference"
    if len(normalized.split()) <= 6 and not candidate_voice and normalized in context.terms:
        return "offer_reference"
    # The kit often quotes one complete requirement or timing sentence from a
    # longer offer description.  It remains an offer fact, not a personal
    # claim, when the exact normalized phrase is present in that source.  The
    # first-person guard is essential: "I have fluent English" must still be
    # proved by the candidate profile even if the offer asks for English.
    if len(normalized.split()) >= 4 and not candidate_voice and any(
        f" {normalized} " in f" {term} " for term in context.terms
    ):
        return "offer_reference"
    padded = f" {normalized} "
    if any(f" {normalized_text(marker)} " in padded for marker in _OFFER_MARKERS):
        return "offer_reference"
    if any(f" {normalized_text(marker)} " in padded for marker in _BOILERPLATE_MARKERS):
        return "boilerplate"
    return None


# ------------------------------------------------------------------- verdicts


@dataclass(frozen=True, slots=True)
class ClaimIssue:
    code: str
    category: str
    severity: str
    label: str
    matched_text: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "label": self.label,
            "matched_text": self.matched_text,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    index: int
    section: str
    claim_type: str
    audited: bool
    text: str
    offset: int
    label: str
    evidence: tuple[dict[str, Any], ...] = ()
    missing_evidence: tuple[str, ...] = ()
    issues: tuple[ClaimIssue, ...] = ()
    suggestion: str = ""
    best_evidence: dict[str, Any] | None = None
    numbers: tuple[NumberAnchor, ...] = ()
    topic_tokens: tuple[str, ...] = ()

    @property
    def label_label(self) -> str:
        return LABEL_LABELS.get(self.label, self.label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "section": self.section,
            "claim_type": self.claim_type,
            "audited": self.audited,
            "text": self.text,
            "offset": self.offset,
            "label": self.label,
            "label_label": self.label_label,
            "evidence": list(self.evidence),
            "missing_evidence": list(self.missing_evidence),
            "issues": [issue.to_dict() for issue in self.issues],
            "suggestion": self.suggestion,
            "best_evidence": self.best_evidence,
            "numbers": [anchor.to_dict() for anchor in self.numbers],
            "topic_tokens": list(self.topic_tokens),
        }


@dataclass(frozen=True, slots=True)
class ClaimCheckReport:
    claims: tuple[ClaimVerdict, ...]
    counts: dict[str, int]
    skipped: dict[str, int]
    rules_version: str
    rules_source: str
    evidence_count: int
    document_chars: int
    warnings: tuple[str, ...] = ()
    context: dict[str, list[str]] = field(default_factory=dict)

    @property
    def audited_claims(self) -> tuple[ClaimVerdict, ...]:
        return tuple(claim for claim in self.claims if claim.audited)

    @property
    def support_rate(self) -> int:
        total = sum(self.counts.values())
        return round(100 * self.counts.get("supported", 0) / total) if total else 0

    @property
    def exaggeration_density(self) -> int:
        total = sum(self.counts.values())
        if not total:
            return 0
        risky = (
            self.counts.get("inflated", 0)
            + self.counts.get("out_of_context", 0)
            + self.counts.get("invented", 0)
        )
        return round(100 * risky / total)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules_version": self.rules_version,
            "rules_source": self.rules_source,
            "evidence_count": self.evidence_count,
            "document_chars": self.document_chars,
            "claim_count": len(self.audited_claims),
            "counts": dict(self.counts),
            "support_rate": self.support_rate,
            "exaggeration_density": self.exaggeration_density,
            "skipped": dict(self.skipped),
            "warnings": list(self.warnings),
            "context": self.context,
            "claims": [claim.to_dict() for claim in self.claims],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        return readable_report(self)


def _best_evidence(
    claim_tokens: set[str],
    claim_numbers: tuple[NumberAnchor, ...],
    claim_proper: list[str],
    ledger: tuple[ApprovedEvidence, ...],
) -> list[tuple[float, ApprovedEvidence]]:
    scored: list[tuple[float, ApprovedEvidence]] = []
    claim_number_values = {anchor.value for anchor in claim_numbers}
    for evidence in ledger:
        overlap = len(claim_tokens & evidence.tokens)
        numbers = len(claim_number_values & {anchor.value for anchor in evidence.numbers})
        proper = sum(1 for noun in claim_proper if noun in evidence.normalized)
        score = overlap * 2 + numbers * 3 + proper * 3
        if score <= 0:
            continue
        scored.append((float(score), evidence))
    scored.sort(key=lambda item: (-item[0], item[1].evidence_id))
    return scored


def _issue_suggestion(issue: ClaimIssue, best: ApprovedEvidence | None) -> str:
    if best is None:
        return issue.suggestion or (
            "Retire cette formulation ou appuie-la d'abord sur un fait approuvé dans ton profil. "
            "Aucune reformulation n'est inventée automatiquement."
        )
    date = f", approuvée le {best.dated_at}" if best.dated_at else ""
    suffix = f" Preuve approuvée disponible : « {clean_text(best.quote, limit=240)} » (niveau {best.level}{date})."
    base = issue.suggestion or "Reformule uniquement à partir d'un fait approuvé."
    return base + suffix


def _suggestion_for(
    label: str,
    *,
    best: ApprovedEvidence | None,
    missing: Sequence[str],
    issues: Sequence[ClaimIssue],
    generic: bool,
) -> str:
    if label == "supported":
        return ""
    if label == "invented":
        if missing:
            quoted = ", ".join(f"« {item} »" for item in missing[:4])
            return (
                f"Élément absent de toute preuve approuvée : {quoted}. "
                "Retire-le, ou ajoute d'abord ce fait dans ton profil ; l'auditeur ne fabrique aucune valeur."
            )
        if best is not None:
            return (
                "Aucune preuve approuvée ne couvre cette phrase. "
                f"Utilise uniquement la preuve existante : « {clean_text(best.quote, limit=240)} » "
                f"(niveau {best.level}{f', {best.dated_at}' if best.dated_at else ''})."
            )
        return (
            "Aucune preuve approuvée ne couvre cette phrase. Retire-la, ou ajoute d'abord "
            "un fait approuvé dans ton profil : aucune reformulation n'est inventée."
        )
    if label == "out_of_context":
        base = (
            "Cette phrase assemble des faits approuvés dans des contextes différents. "
            "Réutilise chaque preuve dans son contexte d'origine, sans transférer un chiffre ou une mission."
        )
        if best is not None:
            base += f" Preuve la plus proche : « {clean_text(best.quote, limit=240)} »."
        return base
    if label == "inflated":
        if issues:
            return _issue_suggestion(issues[0], best)
        if best is not None:
            return (
                "Reformule sans exagération, à partir de la preuve approuvée : "
                f"« {clean_text(best.quote, limit=240)} » (niveau {best.level})."
            )
        return "Retire la formulation exagérée : aucune preuve approuvée ne la justifie."
    if generic:
        if best is not None:
            return (
                "Argument générique : remplace-le par le fait précis déjà approuvé "
                f"« {clean_text(best.quote, limit=240)} »."
            )
        return (
            "Argument générique : remplace-le par un fait précis déjà approuvé dans ton profil, "
            "ou retire-le. Aucun fait n'est ajouté automatiquement."
        )
    if best is not None:
        return (
            "Preuve trop faible pour vérifier la phrase en l'état. Appuie-toi sur la preuve approuvée "
            f"« {clean_text(best.quote, limit=240)} » (niveau {best.level}) ou retire la phrase."
        )
    return (
        "Phrase non vérifiable : aucune preuve approuvée ne la couvre. Retire-la ou reformule-la "
        "à partir d'un fait approuvé de ton profil."
    )


def _rule_issues(
    text: str,
    *,
    rules: Ruleset,
    evidence: Sequence[ApprovedEvidence],
) -> tuple[list[ClaimIssue], bool]:
    issues: list[ClaimIssue] = []
    credential_missing = False
    supported_years = max((item.years or 0 for item in evidence), default=0)
    evidence_blob = " ".join(item.normalized for item in evidence)
    for rule in rules.rules:
        pattern = rules.patterns.get(rule["id"])
        if pattern is None:
            continue
        match = pattern.search(text)
        if match is None:
            continue
        min_years = rule.get("min_years")
        if isinstance(min_years, int) and supported_years >= min_years:
            continue
        requires = str(rule.get("requires") or "")
        if requires == "education":
            category_hit = any(
                item.category in {"education", "formation", "diplome", "certification"}
                for item in evidence
            )
            term_hit = any(term and term in evidence_blob for term in rules.credential_terms)
            if not category_hit and not term_hit:
                credential_missing = True
            else:
                continue
        issues.append(
            ClaimIssue(
                code=rule["id"],
                category=rule["category"],
                severity=rule.get("severity", "medium"),
                label=rule.get("label", rule["id"]),
                matched_text=match.group(0),
                suggestion=rule.get("suggestion", ""),
            )
        )
    return issues, credential_missing


def _analyse_candidate(
    raw: _RawClaim,
    *,
    index: int,
    ledger: tuple[ApprovedEvidence, ...],
    rules: Ruleset,
    context: AuditContext,
    generic_words: frozenset[str],
) -> ClaimVerdict:
    text = raw.text
    topic = _topic_tokens(text, generic_words)
    numbers = _number_anchors(text)
    proper = _proper_nouns(text, context)
    skills = _skill_matches(text, rules.skill_terms)
    credentials = _skill_matches(text, rules.credential_terms)
    generic_hits = _skill_matches(text, rules.generic_phrases)

    scored = _best_evidence(topic, numbers, proper, ledger)
    matched = [evidence for _score, evidence in scored[:3]]
    union_tokens: set[str] = set()
    union_normalized: list[str] = []
    union_numbers: set[str] = set()
    for evidence in ledger:
        union_tokens |= evidence.tokens
        union_normalized.append(evidence.normalized)
        union_numbers |= {anchor.value for anchor in evidence.numbers}
    union_blob = " ".join(union_normalized)
    claim_number_values = {anchor.value for anchor in numbers}

    missing_numbers = [
        anchor.raw for anchor in numbers
        if anchor.value not in union_numbers and anchor.value not in context.numbers
    ]
    missing_proper = [noun for noun in proper if noun not in union_blob]
    missing_skills = [skill for skill in skills if skill not in union_blob]
    credential_evidence = any(
        item.category in {"education", "formation", "diplome", "certification"}
        for item in ledger
    ) or any(term and term in union_blob for term in rules.credential_terms)
    missing_credentials = [] if credential_evidence else [
        term for term in credentials if term not in union_blob
    ]

    coverage = len(topic & union_tokens) / len(topic) if topic else 0.0
    covered_by_one = False
    unit_mismatch = False
    for evidence in ledger:
        evidence_numbers = {anchor.value: anchor for anchor in evidence.numbers}
        if not claim_number_values <= set(evidence_numbers):
            continue
        if topic and len(topic & evidence.tokens) / len(topic) < 0.55:
            continue
        covered_by_one = True
        for anchor in numbers:
            other = evidence_numbers.get(anchor.value)
            if other and anchor.unit and other.unit and anchor.unit != other.unit:
                unit_mismatch = True
        if covered_by_one:
            break

    combined_support = (
        coverage >= 0.55
        and not missing_numbers
        and not missing_proper
        and not missing_skills
        and not missing_credentials
    )

    has_anchor = bool(numbers or proper or skills or credentials)
    base_label = "unverifiable"
    if missing_numbers or missing_proper or missing_skills or missing_credentials:
        base_label = "invented"
    elif unit_mismatch:
        base_label = "out_of_context"
    elif combined_support and not covered_by_one and bool(numbers) and bool(topic):
        base_label = "out_of_context"
    elif combined_support:
        base_label = "supported"
    elif (
        covered_by_one
        and not missing_numbers
        and not missing_proper
        and not missing_skills
        and not missing_credentials
        and (numbers or proper or skills or credentials)
    ):
        base_label = "supported"
    elif coverage >= 0.3:
        base_label = "unverifiable"
    elif has_anchor:
        base_label = "invented"
    else:
        base_label = "unverifiable"

    rule_issues, credential_missing = _rule_issues(text, rules=rules, evidence=matched or ledger)
    if credential_missing:
        base_label = "invented"

    issue_list = list(rule_issues)
    generic = bool(generic_hits)
    if generic and base_label == "supported" and not has_anchor:
        base_label = "unverifiable"
    if generic:
        issue_list.append(
            ClaimIssue(
                code="generic_argument",
                category="generic_argument",
                severity="low",
                label="argument générique sans fait précis",
                matched_text=generic_hits[0],
                suggestion=(
                    "Remplace cet argument générique par un fait précis déjà approuvé dans ton profil."
                ),
            )
        )

    exaggeration = any(issue.category != "generic_argument" for issue in issue_list)
    if base_label == "invented":
        label = "invented"
    elif base_label == "out_of_context":
        label = "out_of_context"
    elif exaggeration:
        label = "inflated"
    elif base_label == "supported":
        label = "supported"
    else:
        label = "unverifiable"

    missing_labels: list[str] = []
    missing_labels.extend(missing_numbers)
    missing_labels.extend(missing_proper)
    missing_labels.extend(missing_skills)
    missing_labels.extend(missing_credentials)
    if credential_missing:
        missing_labels.append("preuve de certification ou de diplôme")
    if unit_mismatch:
        missing_labels.append("unité du chiffre différente de la preuve")

    best = matched[0] if matched else None
    suggestion = _suggestion_for(
        label,
        best=best,
        missing=missing_labels,
        issues=issue_list,
        generic=generic,
    )
    evidence_payload = tuple(evidence.to_dict() for evidence in matched)
    return ClaimVerdict(
        index=index,
        section=raw.section,
        claim_type="candidate",
        audited=True,
        text=text,
        offset=raw.offset,
        label=label,
        evidence=evidence_payload,
        missing_evidence=tuple(dict.fromkeys(missing_labels)),
        issues=tuple(issue_list),
        suggestion=suggestion,
        best_evidence=best.to_dict() if best is not None else None,
        numbers=numbers,
        topic_tokens=tuple(sorted(topic)),
    )


def _skipped_verdict(raw: _RawClaim, *, index: int, claim_type: str) -> ClaimVerdict:
    return ClaimVerdict(
        index=index,
        section=raw.section,
        claim_type=claim_type,
        audited=False,
        text=raw.text,
        offset=raw.offset,
        label="supported",
        suggestion="",
    )


def _ats_issues(
    raw_claims: Sequence[_RawClaim],
    verdicts: Sequence[ClaimVerdict],
    *,
    threshold: int,
    generic_words: frozenset[str],
) -> dict[int, list[ClaimIssue]]:
    by_list: dict[str, list[tuple[_RawClaim, ClaimVerdict]]] = {}
    for raw, verdict in zip(raw_claims, verdicts):
        if not verdict.audited or not raw.list_id:
            continue
        by_list.setdefault(raw.list_id, []).append((raw, verdict))
    issues: dict[int, list[ClaimIssue]] = {}
    for entries in by_list.values():
        counts: dict[str, int] = {}
        for raw, _verdict in entries:
            for token in _topic_tokens(raw.text, generic_words):
                counts[token] = counts.get(token, 0) + 1
        stuffed = {token: count for token, count in counts.items() if count > threshold}
        if not stuffed:
            continue
        labels = ", ".join(f"« {token} » ×{count}" for token, count in sorted(stuffed.items()))
        for _raw, verdict in entries:
            verdict_tokens = set(verdict.topic_tokens)
            if not verdict_tokens & set(stuffed):
                continue
            issues.setdefault(verdict.index, []).append(
                ClaimIssue(
                    code="ats_keyword_stuffing",
                    category="ats_stuffing",
                    severity="medium",
                    label="mot-clé répété sans contexte (parasitage ATS)",
                    matched_text=", ".join(sorted(verdict_tokens & set(stuffed))),
                    suggestion=(
                        f"Mot-clé répété plus de {threshold} fois dans la même liste ({labels}). "
                        "Garde-le une fois, accompagné d'une preuve concrète."
                    ),
                )
            )
    return issues


def _with_issues(verdict: ClaimVerdict, extra: Sequence[ClaimIssue]) -> ClaimVerdict:
    if not extra:
        return verdict
    label = "inflated" if verdict.label in {"supported", "unverifiable", "inflated"} else verdict.label
    issue_list = tuple(list(verdict.issues) + list(extra))
    suggestion = verdict.suggestion or (extra[0].suggestion if extra else "")
    return ClaimVerdict(
        index=verdict.index,
        section=verdict.section,
        claim_type=verdict.claim_type,
        audited=verdict.audited,
        text=verdict.text,
        offset=verdict.offset,
        label=label,
        evidence=verdict.evidence,
        missing_evidence=verdict.missing_evidence,
        issues=issue_list,
        suggestion=suggestion,
        best_evidence=verdict.best_evidence,
        numbers=verdict.numbers,
        topic_tokens=verdict.topic_tokens,
    )


def check_claims(
    document: Any,
    *,
    evidence: Any = None,
    profile: Mapping[str, Any] | None = None,
    evidence_service: Any = None,
    extra_facts: Any = None,
    rules: Ruleset | None = None,
    rules_path: str | os.PathLike[str] | None = None,
    context: Mapping[str, Any] | None = None,
) -> ClaimCheckReport:
    """Audit every sentence of ``document`` against approved evidence.

    ``document`` is either a string or a mapping ``{section: text}`` (for
    example ``{"CV": ..., "Lettre": ...}``).  ``evidence`` may be a mapping,
    a sequence of facts or a local evidence service; ``profile=`` is a
    convenience shorthand.  The function is pure and deterministic.
    """

    ruleset = rules if isinstance(rules, Ruleset) else load_rules(rules_path)
    ledger = build_evidence_ledger(evidence, extra_facts=extra_facts)
    if not ledger and profile is not None:
        ledger = build_evidence_ledger(profile)
    if not ledger and evidence_service is not None:
        ledger = build_evidence_ledger(evidence_service)
    audit_context = _build_context(context)

    warnings = list(ruleset.warnings)
    if not ledger:
        warnings.append(
            "Aucune preuve approuvée disponible : les affirmations factuelles seront signalées "
            "comme non vérifiables ou inventées. L'auditeur ne complète jamais le profil."
        )

    generic_words = frozenset(
        token
        for phrase in ruleset.generic_phrases
        for token in phrase.split()
        if token
    )
    raw_claims = _raw_claims(document)
    if not raw_claims:
        warnings.append("Document vide : aucune affirmation à auditer.")

    verdicts: list[ClaimVerdict] = []
    skipped: dict[str, int] = {}
    for index, raw in enumerate(raw_claims, start=1):
        non_candidate = _contact_or_offer(raw.text, audit_context)
        if non_candidate is not None:
            verdicts.append(_skipped_verdict(raw, index=index, claim_type=non_candidate))
            skipped[non_candidate] = skipped.get(non_candidate, 0) + 1
            continue
        verdicts.append(
            _analyse_candidate(
                raw,
                index=index,
                ledger=ledger,
                rules=ruleset,
                context=audit_context,
                generic_words=generic_words,
            )
        )

    ats = _ats_issues(
        raw_claims,
        verdicts,
        threshold=ruleset.ats_repetition_threshold,
        generic_words=generic_words,
    )
    if ats:
        verdicts = [
            _with_issues(verdict, ats.get(verdict.index, ()))
            for verdict in verdicts
        ]

    counts = {label: 0 for label in LABELS}
    for verdict in verdicts:
        if verdict.audited:
            counts[verdict.label] = counts.get(verdict.label, 0) + 1

    document_chars = sum(
        len(value) for value in (document.values() if isinstance(document, Mapping) else [document])
        if isinstance(value, str)
    )
    return ClaimCheckReport(
        claims=tuple(verdicts),
        counts=counts,
        skipped=skipped,
        rules_version=ruleset.version,
        rules_source=ruleset.source_path,
        evidence_count=len(ledger),
        document_chars=document_chars,
        warnings=tuple(dict.fromkeys(warnings)),
        context=audit_context.to_dict(),
    )


def readable_report(report: ClaimCheckReport) -> str:
    """Human-readable French report with quotes, missing proof and suggestions."""

    lines = [
        "# Audit qualité des affirmations",
        "",
        f"- Règles : version {report.rules_version} ({report.rules_source})",
        f"- Preuves approuvées disponibles : {report.evidence_count}",
        f"- Affirmations auditées : {len(report.audited_claims)}",
        f"- Taux d'affirmations étayées : {report.support_rate} %",
        f"- Densité d'exagérations : {report.exaggeration_density} %",
        "",
        "## Synthèse",
        "",
    ]
    for label in LABELS:
        lines.append(f"- {LABEL_LABELS[label]} ({label}) : {report.counts.get(label, 0)}")
    if report.skipped:
        skipped = ", ".join(f"{key} {value}" for key, value in sorted(report.skipped.items()))
        lines.append(f"- Non audité (références, contacts, formules) : {skipped}")
    lines.append("")

    if not report.audited_claims:
        lines.append("Aucune affirmation candidate à auditer.")
        return "\n".join(lines)

    lines.extend(["## Détail phrase par phrase", ""])
    for verdict in report.audited_claims:
        lines.append(f"### {verdict.index}. [{verdict.label}] {verdict.text}")
        lines.append("")
        if verdict.best_evidence:
            evidence = verdict.best_evidence
            date = f", {evidence['dated_at']}" if evidence.get("dated_at") else ", date non fournie"
            lines.append(
                f"- Preuve : « {evidence['quote']} » (niveau {evidence['level']}{date})"
            )
        else:
            lines.append("- Preuve : aucune preuve approuvée")
        if verdict.missing_evidence:
            lines.append(f"- Preuve manquante : {', '.join(verdict.missing_evidence)}")
        for issue in verdict.issues:
            lines.append(f"- Signal [{issue.severity}] {issue.label} : « {issue.matched_text} »")
        if verdict.suggestion:
            lines.append(f"- Reformulation sûre : {verdict.suggestion}")
        lines.append("")

    if report.warnings:
        lines.extend(["## Avertissements", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines)


# Stable aliases used by other modules and by older call sites.
audit_claims = check_claims
audit_document = check_claims
