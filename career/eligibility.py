"""Verdict d'éligibilité par offre (SPEC-043, CVBOOST-78).

Module **pur, déterministe, hors-ligne** : aucune IA décisionnelle, aucun
réseau, aucune écriture disque.  Le moteur confronte les faits **déjà extraits**
d'une offre aux **tickets remplis par la personne** dans
``career/rules_eligibility.json`` (règles locales versionnées, éditables) et
rend un verdict clause par clause :

- ``ÉLIGIBLE`` — chaque clause est prouvée conforme par une preuve citée ;
- ``NON ÉLIGIBLE`` — au moins une clause prouve un blocage explicite
  (contrat fermé au statut, durée trop courte, visa refusé, pays exclu,
  langue insuffisante…) ; l'offre est marquée et sortie du classement par
  défaut, mais reste visible pour apprendre pourquoi ;
- ``À VÉRIFIER`` — à défaut de preuve (donnée manquante, ticket non rempli,
  extraction absente), **jamais de verdict positif implicite**.

CONTRAT DU MOTEUR
-----------------
Le moteur ne lit **aucun texte libre** : il consomme les faits des couches
d'extraction existantes, déterministes elles-mêmes.

- ``offer["qualification"]`` — sortie de
  ``career.offer_qualification.qualify_offer`` (``contract_type``,
  ``duration_min_months``, ``duration_max_months``, ``country``, ``city``,
  ``provenance``…).  Accepte aussi le dataclass ``QualifiedOffer``.
- ``conditions`` — faits de conditions SK-17 déjà extraits du texte de
  l'offre (type ``ConditionFact`` ou dictionnaires ``to_dict()`` portant
  ``condition_type`` / ``value`` / ``quote`` / ``source_field`` :
  ``visa_sponsorship``, ``remote``, ``hybrid``, ``onsite``…).  ``None``
  quand l'extraction n'a pas tourné — le verdict reste alors prudent.
- ``requirements`` — relevés d'exigences de
  ``career.offer_requirements.extract.analyze_offer`` (sa clé
  ``"requirements"``) : chaque relevé porte ``category`` / ``modality`` /
  ``text`` et, quand la couche d'extraction l'a résolu, ``level`` (niveau
  d'étude) ou ``language`` + ``level`` (langue, CECRL).  ``None`` quand
  l'extraction n'a pas tourné — l'absence d'extraction n'est **pas** une
  preuve d'absence d'exigence.
- ``offer["education_access"]`` — sortie de
  ``career.education_access.assess_education_access``, utilisée en repli
  pour le niveau académique exigé.

TICKETS PROFIL (dans le fichier de règles)
------------------------------------------
``profile_approved``, contrats acceptés, durée minimale, niveau d'étude réel,
filières, **tickets WORK AUTH explicites** (statut, pays de travail, besoin de
sponsorisation visa — remplis par la personne, jamais devinés), localisation,
modes de travail et langues parlées.  Un ticket vide ou ``null`` produit
toujours ``À VÉRIFIER`` : le moteur ne comble jamais un trou.

Usage :

    >>> from career.eligibility import check_eligibility
    >>> verdict = check_eligibility({"qualification": {"contract_type": "permanent"}})
    >>> verdict["verdict"]
    'NON ÉLIGIBLE'
    >>> verdict["etat_suivant"]
    'exclue_du_classement'

Voir ``docs/agent-reports/CVBOOST-78-ELIGIBILITY.md`` pour les décisions.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import canonical_country_code, clean_text, normalized_text

DEFAULT_RULES_PATH = Path(__file__).with_name("rules_eligibility.json")
SCHEMA_NAME = "eligibility_rules"
SCHEMA_VERSION = 1

VERDICT_ELIGIBLE = "ÉLIGIBLE"
VERDICT_NOT_ELIGIBLE = "NON ÉLIGIBLE"
VERDICT_TO_VERIFY = "À VÉRIFIER"
VERDICT_ORDER: dict[str, int] = {
    VERDICT_ELIGIBLE: 0,
    VERDICT_TO_VERIFY: 1,
    VERDICT_NOT_ELIGIBLE: 2,
}

CLAUSE_OK = "ok"
CLAUSE_NOT_OK = "non"
CLAUSE_TO_VERIFY = "a_verifier"

STATE_RANKABLE = "classable"
STATE_EXCLUDED = "exclue_du_classement"
STATE_REVIEW = "a_verifier"

STATE_BY_VERDICT = {
    VERDICT_ELIGIBLE: STATE_RANKABLE,
    VERDICT_NOT_ELIGIBLE: STATE_EXCLUDED,
    VERDICT_TO_VERIFY: STATE_REVIEW,
}

# Niveaux d'étude comparables (échelle française fermée).  Un niveau absent
# du tableau n'est pas un niveau : il reste inconnu.
EDUCATION_RANKS: dict[str, int] = {
    "bac": 0,
    "bac+2": 2,
    "bac+3": 3,
    "bac+4": 4,
    "bac+5": 5,
    "doctorat": 8,
}
_EDUCATION_ALIASES_SRC: dict[str, str] = {
    "bac": "bac",
    "baccalaureat": "bac",
    "bac+2": "bac+2", "bts": "bac+2", "dut": "bac+2", "but": "bac+2",
    "bac+3": "bac+3", "licence": "bac+3", "bachelor": "bac+3", "b3": "bac+3",
    "bac+4": "bac+4", "m1": "bac+4", "master 1": "bac+4", "master1": "bac+4",
    "bac+5": "bac+5", "m2": "bac+5", "master 2": "bac+5", "master2": "bac+5",
    "master": "bac+5",
    "doctorat": "doctorat", "doctorate": "doctorat", "phd": "doctorat",
}
# Tables indexées en espace normalisé (« bac+3 » s'écrit « bac 3 » une fois
# normalisé) : une formulation du profil ou d'un relevé d'extraction est
# ramenée au même canonique, sans deviner.
EDUCATION_RANK_LOOKUP: dict[str, str] = {
    normalized_text(level): level for level in EDUCATION_RANKS
}
_EDUCATION_ALIASES: dict[str, str] = {
    normalized_text(key): value for key, value in _EDUCATION_ALIASES_SRC.items()
}
# Étiquettes produites par ``assess_education_access`` → niveau comparable.
_EDUCATION_ACCESS_LABELS: dict[str, str] = {
    "Bachelor / Bac+3": "bac+3",
    "Master 1 / Bac+4": "bac+4",
    "Master 2 / Bac+5": "bac+5",
    "Doctorat": "doctorat",
}
_EDUCATION_ACCESS_REQUIRED_LEVELS: dict[str, str] = {"outside_preference": "doctorat"}

# Échelle CECRL fermée.  ``native`` n'est comparable qu'à lui-même : une
# exigence « langue maternelle » face à un profil C1/C2 reste à vérifier,
# parce qu'un diplôme ne prouve pas une langue maternelle.
LANGUAGE_RANKS: dict[str, int] = {
    "a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6, "native": 7,
}
_LANGUAGE_LEVEL_ALIASES: dict[str, str] = {
    "a1": "a1", "a2": "a2", "b1": "b1", "b2": "b2", "c1": "c1", "c2": "c2",
    "notions": "a2", "base": "a2", "basic": "a2", "basique": "a2",
    "intermediate": "b1", "intermediaire": "b1",
    "professional": "b2", "professionnel": "b2", "business": "b2",
    "affaires": "b2", "operational": "b2", "operationnel": "b2",
    "fluent": "c1", "courant": "c1", "advanced": "c1", "avance": "c1",
    "bilingual": "c2", "bilingue": "c2", "native": "native",
    "natif": "native", "langue maternelle": "native", "mother tongue": "native",
}
# Vocabulaire fermé des langues des sources et du profil : une langue absente
# de ce tableau reste une langue inconnue, jamais devinée.
_LANGUAGE_CODES: dict[str, str] = {
    "en": "en", "english": "en", "anglais": "en",
    "fr": "fr", "french": "fr", "francais": "fr",
    "de": "de", "german": "de", "allemand": "de",
    "es": "es", "spanish": "es", "espagnol": "es",
    "it": "it", "italian": "it", "italien": "it",
    "nl": "nl", "dutch": "nl", "neerlandais": "nl",
    "pt": "pt", "portuguese": "pt", "portugais": "pt",
    "ar": "ar", "arabic": "ar", "arabe": "ar",
    "zh": "zh", "chinese": "zh", "chinois": "zh", "mandarin": "zh",
    "ru": "ru", "russian": "ru", "russe": "ru",
    "ja": "ja", "japanese": "ja", "japonais": "ja",
    "lb": "lb", "luxembourgish": "lb", "luxembourgeois": "lb",
}
LANGUAGE_LABELS: dict[str, str] = {
    "en": "anglais", "fr": "français", "de": "allemand", "es": "espagnol",
    "it": "italien", "nl": "néerlandais", "pt": "portugais", "ar": "arabe",
    "zh": "chinois", "ru": "russe", "ja": "japonais", "lb": "luxembourgeois",
}

CONTRACT_LABELS: dict[str, str] = {
    "internship": "stage",
    "apprenticeship": "alternance / apprentissage",
    "fixed_term": "CDD",
    "permanent": "CDI",
    "VIE": "VIE",
    "graduate": "programme graduate",
}
CONTRACT_ALIASES: dict[str, str] = {
    "stage": "internship", "internship": "internship", "intern": "internship",
    "alternance": "apprenticeship", "apprenticeship": "apprenticeship",
    "apprentice": "apprenticeship", "cdd": "fixed_term", "fixed term": "fixed_term",
    "cdi": "permanent", "permanent": "permanent", "vie": "VIE",
    "graduate": "graduate",
}

WORK_STATUSES: frozenset[str] = frozenset(
    {"student", "employee", "contractor", "freelance", "job_seeker", "other", "unknown"}
)
WORK_MODES: frozenset[str] = frozenset({"onsite", "hybrid", "remote"})
WORK_MODE_LABELS: dict[str, str] = {
    "onsite": "sur site", "hybrid": "hybride", "remote": "télétravail",
}

# Régions fermées (définies dans le code, citables dans les tickets du
# profil) : « EU » et « EEA » couvrent les codes ISO-2 listés ici, rien d'autre.
_EU_COUNTRIES: frozenset[str] = frozenset(
    {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
     "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
     "SI", "ES", "SE"}
)
REGIONS: dict[str, frozenset[str]] = {
    "EU": _EU_COUNTRIES,
    "EEA": _EU_COUNTRIES | {"IS", "NO", "LI"},
}


class RulesError(ValueError):
    """Le fichier de règles est illisible ou contient des valeurs interdites."""


# ───────────────────────────────────────────────────────────────────────
# Chargement et validation des règles
# ───────────────────────────────────────────────────────────────────────

def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    """Charger et valider le fichier de règles (par défaut celui du paquet).

    Le fichier est la source de vérité du PROFIL APPROUVÉ : toute valeur
    invalide est une erreur signalée, jamais une valeur devinée.
    """
    rules_path = Path(path) if path is not None else DEFAULT_RULES_PATH
    try:
        data = json.loads(rules_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RulesError(f"Fichier de règles introuvable : {rules_path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise RulesError(f"Fichier de règles illisible : {rules_path} ({error})") from error
    if not isinstance(data, dict):
        raise RulesError("Le fichier de règles doit contenir un objet JSON.")
    problems = validate_rules(data)
    if problems:
        raise RulesError("Règles d'éligibilité invalides : " + " ; ".join(problems))
    return data


def validate_rules(rules: Mapping[str, Any]) -> list[str]:
    """Lister les problèmes du fichier de règles (vide = fichier valide)."""
    problems: list[str] = []
    if rules.get("schema") != SCHEMA_NAME:
        problems.append(f"schema attendu « {SCHEMA_NAME} »")
    version = rules.get("version")
    if type(version) is not int or version < 1:
        problems.append("version doit être un entier positif")
    if type(rules.get("profile_approved")) is not bool:
        problems.append("profile_approved doit être true ou false")
    section = rules.get("rules")
    if not isinstance(section, dict):
        problems.append("rules doit être un objet")
        return problems
    known_rules = {"contract", "duration", "education", "work_authorization", "location", "languages"}
    unknown = sorted(str(key) for key in section if key not in known_rules)
    if unknown:
        problems.append("règles inconnues : " + ", ".join(unknown))
    for key in sorted(known_rules & set(section)):
        if not isinstance(section[key], dict):
            problems.append(f"rules.{key} doit être un objet")
    contract = section.get("contract")
    if isinstance(contract, dict):
        accepted = contract.get("accepted")
        if not isinstance(accepted, list) or not all(isinstance(item, str) for item in accepted):
            problems.append("rules.contract.accepted doit être une liste de chaînes")
    duration = section.get("duration")
    if isinstance(duration, dict):
        months = duration.get("minimum_months")
        if type(months) is not int or not 1 <= months <= 24:
            problems.append("rules.duration.minimum_months doit être un entier de 1 à 24")
    education = section.get("education")
    if isinstance(education, dict):
        level = clean_text(education.get("profile_level"), limit=40)
        if level and _education_level(level) is None:
            problems.append(f"rules.education.profile_level « {level} » est un niveau inconnu")
        fields = education.get("profile_fields")
        if not isinstance(fields, list) or not all(isinstance(item, str) for item in fields):
            problems.append("rules.education.profile_fields doit être une liste de chaînes")
    work = section.get("work_authorization")
    if isinstance(work, dict):
        status = clean_text(work.get("status"), limit=40).casefold()
        if status not in WORK_STATUSES:
            problems.append(f"rules.work_authorization.status « {status} » est un statut inconnu")
        permits = work.get("work_permits")
        if not isinstance(permits, list) or not all(isinstance(item, str) for item in permits):
            problems.append("rules.work_authorization.work_permits doit être une liste de chaînes")
        else:
            unknown_permits = [item for item in permits if _resolve_permit(item) is None]
            if unknown_permits:
                problems.append("work_permits inconnus : " + ", ".join(unknown_permits))
        needed = work.get("visa_sponsorship_needed")
        if needed is not None and type(needed) is not bool:
            problems.append("rules.work_authorization.visa_sponsorship_needed doit être true, false ou null")
    location = section.get("location")
    if isinstance(location, dict):
        for key in ("countries", "excluded_countries", "excluded_cities", "work_modes"):
            values = location.get(key)
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                problems.append(f"rules.location.{key} doit être une liste de chaînes")
        invalid_modes = [
            mode for mode in (location.get("work_modes") or [])
            if isinstance(mode, str) and normalized_text(mode) not in WORK_MODES
        ]
        if invalid_modes:
            problems.append("modes de travail inconnus : " + ", ".join(invalid_modes))
    languages = section.get("languages")
    if isinstance(languages, dict):
        levels = languages.get("profile_levels")
        if not isinstance(levels, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in levels.items()
        ):
            problems.append("rules.languages.profile_levels doit être un objet {langue: niveau}")
        else:
            for name, level in levels.items():
                if _language_level(level) is None:
                    problems.append(f"niveau « {level} » inconnu pour la langue « {name} »")
    return problems


def _resolve_permit(value: str) -> str | None:
    """Code ISO-2 ou nom de région fermé correspondant à un ticket du profil."""
    text = clean_text(value, limit=40)
    if not text:
        return None
    token = normalized_text(text)
    if token.upper() in REGIONS:
        return token.upper()
    return canonical_country_code(text) or None


# ───────────────────────────────────────────────────────────────────────
# Normalisation des faits d'extraction
# ───────────────────────────────────────────────────────────────────────

def _qualification_dict(offer: Mapping[str, Any]) -> dict[str, Any]:
    value = offer.get("qualification") if isinstance(offer, Mapping) else None
    if hasattr(value, "to_dict") and not isinstance(value, dict):
        value = value.to_dict()
    return value if isinstance(value, dict) else {}


def _condition_dicts(conditions: Any) -> list[dict[str, Any]]:
    """Normaliser les faits SK-17 (dataclasses ou dictionnaires)."""
    normalized_conditions: list[dict[str, Any]] = []
    for item in conditions or ():
        if hasattr(item, "to_dict") and not isinstance(item, dict):
            item = item.to_dict()
        if isinstance(item, dict):
            normalized_conditions.append(item)
    return normalized_conditions


def _required_facts(requirements: Any, category: str) -> tuple[list[dict[str, Any]], bool]:
    """Relevés ``required`` d'une catégorie, et si l'extraction a eu lieu.

    Le second élément distingue « aucune exigence trouvée » (extraction
    présente, liste éventuellement vide) de « extraction absente » : seule la
    première situation prouve l'absence d'exigence.  Une entrée qui n'est ni
    une liste ni un tuple (champ tableau brut, analyse non exécutée) compte
    comme extraction absente — jamais comme preuve d'absence.
    """
    if not isinstance(requirements, (list, tuple)):
        return [], False
    facts: list[dict[str, Any]] = []
    for item in requirements:
        if not isinstance(item, dict) or item.get("category") != category:
            continue
        if item.get("modality") == "required":
            facts.append(item)
    return facts, True


def _fact_level(fact: Mapping[str, Any], aliases: Mapping[str, str], ranks: Mapping[str, Any]) -> str | None:
    """Niveau écrit sur un relevé d'extraction, ou ``None`` si non résolu.

    ``aliases`` ramène la formulation brute (``"fluent"``, ``"Master 2"``)
    vers le niveau canonique du tableau ``ranks`` ; toute autre valeur reste
    inconnue.
    """
    level = clean_text(fact.get("level"), limit=40)
    if not level:
        return None
    token = normalized_text(level)
    canonical = aliases.get(token, token)
    return canonical if canonical in ranks else None


def _education_level(value: Any) -> str | None:
    token = normalized_text(value)
    if not token:
        return None
    level = _EDUCATION_ALIASES.get(token)
    if level:
        return level
    return EDUCATION_RANK_LOOKUP.get(token)


def _language_level(value: Any) -> str | None:
    token = normalized_text(value)
    if not token:
        return None
    level = _LANGUAGE_LEVEL_ALIASES.get(token)
    return level if level else (token if token in LANGUAGE_RANKS else None)


def _language_code(value: Any) -> str | None:
    token = normalized_text(value)
    if not token:
        return None
    return _LANGUAGE_CODES.get(token)


def _evidence(source: Any, quote: Any) -> dict[str, str] | None:
    text = clean_text(quote, limit=400)
    origin = clean_text(source, limit=120)
    if not text and not origin:
        return None
    return {"source": origin, "quote": text}


def _condition_evidence(facts: Iterable[Mapping[str, Any]]) -> dict[str, str] | None:
    for fact in facts:
        evidence = _evidence(fact.get("source_field"), fact.get("quote"))
        if evidence:
            return evidence
    return None


def _clause(
    rule: str,
    label: str,
    *,
    exigence: str,
    fait: str,
    statut: str,
    preuve_offre: dict[str, str] | None = None,
    preuve_profil: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "label": label,
        "exigence_offre": exigence,
        "fait_profil": fait,
        "statut_ok": statut,
        "preuve": {"offre": preuve_offre, "profil": preuve_profil},
    }


# ───────────────────────────────────────────────────────────────────────
# Clauses du moteur
# ───────────────────────────────────────────────────────────────────────

def _clause_contract(offer: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    section = rules["rules"]["contract"]
    accepted = {
        CONTRACT_ALIASES.get(normalized_text(item), normalized_text(item))
        for item in (section.get("accepted") or [])
        if clean_text(item, limit=40)
    }
    labels = ", ".join(CONTRACT_LABELS.get(code, code) for code in sorted(accepted)) or "aucun"
    qualification = _qualification_dict(offer)
    contract_type = clean_text(qualification.get("contract_type"), limit=40)
    provenance = qualification.get("provenance") if isinstance(qualification.get("provenance"), dict) else {}
    evidence = provenance.get("contract_type") if isinstance(provenance.get("contract_type"), dict) else {}
    work_status = clean_text((rules["rules"].get("work_authorization") or {}).get("status"), limit=40).casefold()
    if not contract_type or contract_type in {"unknown", "ambiguous", "graduate role ambiguous"}:
        return _clause(
            "contract", "Type de contrat (stage / alternance…)",
            exigence="Type de contrat inconnu dans l'offre.",
            fait=f"Contrats acceptés dans tes règles : {labels}.",
            statut=CLAUSE_TO_VERIFY,
            preuve_offre=_evidence(evidence.get("source"), evidence.get("quote")),
        )
    normalized_contract = CONTRACT_ALIASES.get(normalized_text(contract_type), normalized_text(contract_type))
    exigence = f"L'offre propose un contrat « {CONTRACT_LABELS.get(normalized_contract, contract_type)} »."
    preuve = _evidence(evidence.get("source"), evidence.get("quote"))
    if work_status == "student" and normalized_contract == "permanent":
        # Un statut étudiant n'ouvre pas un CDI : blocage explicite, cité.
        return _clause(
            "contract", "Type de contrat (stage / alternance…)",
            exigence=exigence,
            fait="Ton ticket de statut indique « étudiant » : un CDI n'ouvre pas à ce statut.",
            statut=CLAUSE_NOT_OK,
            preuve_offre=preuve,
        )
    statut = CLAUSE_OK if normalized_contract in accepted else CLAUSE_NOT_OK
    return _clause(
        "contract", "Type de contrat (stage / alternance…)",
        exigence=exigence,
        fait=f"Contrats acceptés dans tes règles : {labels}.",
        statut=statut,
        preuve_offre=preuve,
    )


def _clause_duration(offer: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    section = rules["rules"]["duration"]
    minimum = int(section.get("minimum_months") or 0)
    qualification = _qualification_dict(offer)
    low = qualification.get("duration_min_months")
    high = qualification.get("duration_max_months")
    provenance = qualification.get("provenance") if isinstance(qualification.get("provenance"), dict) else {}
    evidence = provenance.get("duration_max_months") or provenance.get("duration_min_months") or {}
    preuve = _evidence(evidence.get("source"), evidence.get("quote"))
    if type(low) is int and type(high) is int:
        exigence = f"Durée annoncée : {low} à {high} mois."
    elif type(high) is int:
        exigence = f"Durée annoncée : {high} mois (maximum connu)."
    elif type(low) is int:
        exigence = f"Durée annoncée : {low} mois (minimum connu)."
    else:
        exigence = "Durée inconnue dans l'offre."
    fait = f"Durée minimale acceptée dans tes règles : {minimum} mois."
    if type(high) is int and high < minimum:
        statut = CLAUSE_NOT_OK
    elif type(low) is int and low >= minimum:
        statut = CLAUSE_OK
    else:
        statut = CLAUSE_TO_VERIFY
    return _clause(
        "duration", "Durée minimale acceptée",
        exigence=exigence, fait=fait, statut=statut, preuve_offre=preuve,
    )


def _clause_education_level(offer: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    section = rules["rules"]["education"]
    profile_level = _education_level(clean_text(section.get("profile_level"), limit=40))
    facts, extracted = _required_facts(offer.get("requirements"), "education")
    fact_level: str | None = None
    fact_quote = ""
    for fact in facts:
        quote = clean_text(fact.get("text"), limit=300)
        level = _fact_level(fact, _EDUCATION_ALIASES, EDUCATION_RANKS)
        if level and not fact_level:
            fact_level, fact_quote = level, quote
        elif not fact_quote:
            fact_quote = quote
    if fact_level is None:
        access = offer.get("education_access") if isinstance(offer.get("education_access"), dict) else {}
        fact_level = _EDUCATION_ACCESS_REQUIRED_LEVELS.get(clean_text(access.get("status"), limit=40))
        if fact_level is None:
            labels = [clean_text(label, limit=60) for label in (access.get("labels") or [])]
            mapped = {_EDUCATION_ACCESS_LABELS[label] for label in labels if label in _EDUCATION_ACCESS_LABELS}
            if len(mapped) == 1:
                fact_level = mapped.pop()
            elif len(mapped) > 1:
                # Des niveaux distincts coexistent : aucun n'est prouvé
                # comme le niveau exigé.
                fact_quote = fact_quote or " ; ".join(label for label in labels if label)
    preuve_offre = _evidence("requirements", fact_quote) if fact_quote else None
    if facts and fact_level is None:
        return _clause(
            "education_level", "Niveau d'étude exigé",
            exigence="Une exigence académique existe mais son niveau n'est pas lisible.",
            fait=f"Ton niveau réel inscrit dans tes règles : {profile_level or 'non rempli'}.",
            statut=CLAUSE_TO_VERIFY,
            preuve_offre=preuve_offre,
        )
    if fact_level is None and not extracted:
        return _clause(
            "education_level", "Niveau d'étude exigé",
            exigence="Exigence académique inconnue (extraction des exigences absente).",
            fait=f"Ton niveau réel inscrit dans tes règles : {profile_level or 'non rempli'}.",
            statut=CLAUSE_TO_VERIFY,
        )
    if fact_level is None:
        return _clause(
            "education_level", "Niveau d'étude exigé",
            exigence="Aucune exigence de niveau d'étude trouvée dans l'offre.",
            fait=f"Ton niveau réel inscrit dans tes règles : {profile_level or 'non rempli'}.",
            statut=CLAUSE_OK,
        )
    exigence = (
        f"L'offre exige le niveau {fact_level} (« {fact_quote} »)." if fact_quote
        else f"L'offre exige le niveau {fact_level}."
    )
    if profile_level is None:
        return _clause(
            "education_level", "Niveau d'étude exigé",
            exigence=exigence,
            fait="Ton niveau d'étude n'est pas rempli dans tes règles.",
            statut=CLAUSE_TO_VERIFY,
            preuve_offre=preuve_offre,
        )
    statut = CLAUSE_NOT_OK if EDUCATION_RANKS[fact_level] > EDUCATION_RANKS[profile_level] else CLAUSE_OK
    return _clause(
        "education_level", "Niveau d'étude exigé",
        exigence=exigence,
        fait=f"Ton niveau réel inscrit dans tes règles : {profile_level}.",
        statut=statut,
        preuve_offre=preuve_offre,
    )


def _clause_education_field(offer: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    section = rules["rules"]["education"]
    profile_fields = [normalized_text(item) for item in (section.get("profile_fields") or []) if clean_text(item, limit=120)]
    facts, extracted = _required_facts(offer.get("requirements"), "education")
    required_fields: list[str] = []
    fact_quote = ""
    for fact in facts:
        field = normalized_text(clean_text(fact.get("field"), limit=120))
        if field:
            if field not in required_fields:
                required_fields.append(field)
            fact_quote = fact_quote or clean_text(fact.get("text"), limit=300)
    if required_fields:
        exigence = "L'offre exige une filière : " + ", ".join(required_fields) + "."
    elif extracted:
        exigence = "Aucune filière exigée trouvée dans l'offre."
    else:
        exigence = "Filière exigée inconnue (extraction des exigences absente)."
    fait = (
        "Filières inscrites dans tes règles : "
        + (", ".join(profile_fields) if profile_fields else "non remplies") + "."
    )
    preuve_offre = _evidence("requirements", fact_quote) if fact_quote else None
    if not extracted and not required_fields:
        statut = CLAUSE_TO_VERIFY
    elif not required_fields:
        statut = CLAUSE_OK
    elif not profile_fields:
        statut = CLAUSE_TO_VERIFY
    elif set(required_fields) & set(profile_fields):
        statut = CLAUSE_OK
    else:
        # Un écart de filière n'est jamais un blocage prouvé : les offres
        # acceptent souvent « ou équivalent ».  Le point reste à vérifier.
        statut = CLAUSE_TO_VERIFY
    return _clause(
        "education_field", "Filière exigée",
        exigence=exigence, fait=fait, statut=statut, preuve_offre=preuve_offre,
    )


def _work_permit_clauses(offer: Mapping[str, Any], rules: Mapping[str, Any]) -> list[dict[str, Any]]:
    section = rules["rules"]["work_authorization"]
    permits = [permit for permit in (_resolve_permit(item) for item in (section.get("work_permits") or [])) if permit]
    qualification = _qualification_dict(offer)
    country = clean_text(qualification.get("country") or offer.get("country"), limit=120)
    code = canonical_country_code(country) if country else ""
    preuve_pays = _evidence("qualification.country", country) if country else None
    if code:
        exigence = f"L'offre est publiée en {country} ({code})."
    elif country:
        exigence = f"Le pays de travail annoncé (« {country} ») n'est pas identifiable."
    else:
        exigence = "Le pays de travail de l'offre est inconnu."
    fait = (
        "Pays où tu peux travailler (ticket) : " + ", ".join(permits)
        if permits else "Ton ticket « pays de travail » n'est pas rempli."
    )
    if not permits or not code:
        statut = CLAUSE_TO_VERIFY
    else:
        covered = code in permits or any(
            code in REGIONS[region] for region in permits if region in REGIONS
        )
        statut = CLAUSE_OK if covered else CLAUSE_NOT_OK
    return [_clause(
        "work_authorization", "Autorisation de travail (ticket pays)",
        exigence=exigence, fait=fait, statut=statut, preuve_offre=preuve_pays,
    )]


def _visa_sponsorship_clause(conditions: list[dict[str, Any]], rules: Mapping[str, Any]) -> dict[str, Any]:
    section = rules["rules"]["work_authorization"]
    needed = section.get("visa_sponsorship_needed")
    facts = [fact for fact in conditions if fact.get("condition_type") == "visa_sponsorship"]
    offered_facts = [fact for fact in facts if fact.get("value") is True]
    refused_facts = [fact for fact in facts if fact.get("value") is False]
    preuve_offre = _condition_evidence(refused_facts or offered_facts or facts)
    preuve_profil = _evidence(
        "rules.work_authorization.visa_sponsorship_needed",
        f"visa_sponsorship_needed: {needed}" if needed is not None else "null (non rempli)",
    )
    if refused_facts:
        exigence = "L'offre indique qu'elle ne prend pas en charge de visa."
    elif offered_facts:
        exigence = "L'offre indique une prise en charge de visa possible."
    elif facts:
        exigence = "La mention de visa de l'offre est ambiguë."
    else:
        exigence = "L'offre ne dit rien d'exploitable sur la sponsorisation de visa."
    fait = (
        "Ton ticket visa : sponsorisation nécessaire." if needed is True
        else "Ton ticket visa : aucune sponsorisation nécessaire." if needed is False
        else "Ton ticket visa n'est pas rempli."
    )
    if needed is None:
        statut = CLAUSE_TO_VERIFY
    elif needed is False:
        statut = CLAUSE_OK
    elif refused_facts:
        statut = CLAUSE_NOT_OK
    elif offered_facts:
        statut = CLAUSE_OK
    else:
        statut = CLAUSE_TO_VERIFY
    return _clause(
        "visa_sponsorship", "Sponsorisation de visa (ticket)",
        exigence=exigence, fait=fait, statut=statut,
        preuve_offre=preuve_offre, preuve_profil=preuve_profil,
    )


def _clause_location(offer: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    section = rules["rules"]["location"]
    whitelist = {canonical_country_code(item) for item in (section.get("countries") or [])}
    whitelist.discard("")
    excluded = {canonical_country_code(item) for item in (section.get("excluded_countries") or [])}
    excluded.discard("")
    excluded_cities = {
        normalized_text(clean_text(item, limit=120)) for item in (section.get("excluded_cities") or [])
        if clean_text(item, limit=120)
    }
    qualification = _qualification_dict(offer)
    country = clean_text(qualification.get("country") or offer.get("country"), limit=120)
    city = clean_text(qualification.get("city") or offer.get("city"), limit=160)
    code = canonical_country_code(country) if country else ""
    preuve_pays = _evidence("qualification.country", country) if country else None
    exigence = f"L'offre est publiée en {country}." if country else "Le pays de l'offre est inconnu."
    fait_parts = []
    if whitelist:
        fait_parts.append("pays ciblés : " + ", ".join(sorted(whitelist)))
    if excluded:
        fait_parts.append("pays exclus : " + ", ".join(sorted(excluded)))
    if excluded_cities:
        fait_parts.append("villes exclues : " + ", ".join(sorted(excluded_cities)))
    fait = (
        "Localisation inscrite dans tes règles : "
        + (" ; ".join(fait_parts) if fait_parts else "aucune contrainte") + "."
    )
    clause = _clause(
        "location", "Localisation (pays / ville)",
        exigence=exigence, fait=fait, statut=CLAUSE_OK, preuve_offre=preuve_pays,
    )
    if code and code in excluded:
        clause["statut_ok"] = CLAUSE_NOT_OK
        return clause
    city_wording = normalized_text(city)
    city_tokens = {part for part in re.split(r"[,;/|]", city_wording) if part}
    excluded_city_hit = city_tokens & excluded_cities
    if excluded_city_hit:
        clause["statut_ok"] = CLAUSE_NOT_OK
        clause["exigence_offre"] = f"L'offre est publiée à {city}."
        clause["preuve"]["offre"] = _evidence("qualification.city", city)
        return clause
    if whitelist:
        if not code:
            clause["statut_ok"] = CLAUSE_TO_VERIFY
        elif code not in whitelist:
            clause["statut_ok"] = CLAUSE_NOT_OK
        return clause
    if not code and (excluded or excluded_cities):
        clause["statut_ok"] = CLAUSE_TO_VERIFY
    return clause


def _work_mode_clause(conditions: list[dict[str, Any]], rules: Mapping[str, Any]) -> dict[str, Any]:
    section = rules["rules"]["location"]
    profile_modes = {
        normalized_text(mode) for mode in (section.get("work_modes") or []) if clean_text(mode, limit=40)
    }
    modes: list[str] = []
    quotes: list[str] = []
    for fact in conditions:
        fact_type = clean_text(fact.get("condition_type"), limit=40)
        if fact_type not in {"remote", "hybrid", "onsite"}:
            continue
        value = fact.get("value")
        quote = clean_text(fact.get("quote"), limit=200)
        if value is True:
            if fact_type not in modes:
                modes.append(fact_type)
            if quote:
                quotes.append(quote)
        elif value is False and fact_type == "remote" and not modes:
            # « pas de télétravail » écrit par la source ⇒ travail sur site.
            modes.append("onsite")
            if quote:
                quotes.append(quote)
    mode_facts = [fact for fact in conditions if clean_text(fact.get("condition_type"), limit=40) in {"remote", "hybrid", "onsite"}]
    preuve = _condition_evidence(mode_facts)
    if len(modes) > 1:
        exigence = "L'offre contient des mentions de mode de travail contradictoires."
        statut = CLAUSE_TO_VERIFY
    elif modes:
        mode = modes[0]
        exigence = f"L'offre indique un mode de travail « {WORK_MODE_LABELS[mode]} »."
        if not profile_modes:
            statut = CLAUSE_TO_VERIFY
        elif mode in profile_modes:
            statut = CLAUSE_OK
        elif mode == "hybrid" and "remote" in profile_modes:
            # Un rythme hybride est souvent acceptable pour qui veut du
            # télétravail : ce n'est pas un blocage prouvé, c'est un point à
            # vérifier (combien de jours sur site ?).
            statut = CLAUSE_TO_VERIFY
        else:
            statut = CLAUSE_NOT_OK
    else:
        exigence = "Le mode de travail de l'offre n'est pas exploitable."
        statut = CLAUSE_TO_VERIFY
    fait = (
        "Modes de travail acceptés (ticket) : "
        + ", ".join(WORK_MODE_LABELS.get(mode, mode) for mode in sorted(profile_modes))
        if profile_modes else "Ton ticket « mode de travail » n'est pas rempli."
    )
    return _clause(
        "work_mode", "Mode de travail (sur site / hybride / télétravail)",
        exigence=exigence, fait=fait, statut=statut, preuve_offre=preuve,
    )


def _language_clauses(offer: Mapping[str, Any], rules: Mapping[str, Any]) -> list[dict[str, Any]]:
    section = rules["rules"]["languages"]
    profile_levels = section.get("profile_levels") if isinstance(section.get("profile_levels"), dict) else {}
    profile_by_code: dict[str, str] = {}
    for name, level in profile_levels.items():
        code = _language_code(clean_text(name, limit=60))
        if code:
            profile_by_code[code] = clean_text(level, limit=40)
    facts, extracted = _required_facts(offer.get("requirements"), "language")
    required: list[tuple[str, str | None, str]] = []
    unidentified: list[dict[str, Any]] = []
    for fact in facts:
        code = _language_code(clean_text(fact.get("language") or fact.get("text"), limit=120))
        if not code:
            # Une exigence de langue existe mais la langue sort du
            # vocabulaire fermé : jamais absorbée dans un « aucune langue ».
            unidentified.append(fact)
            continue
        level = _fact_level(fact, _LANGUAGE_LEVEL_ALIASES, LANGUAGE_RANKS)
        if all(existing != code for existing, _, _ in required):
            required.append((code, level, clean_text(fact.get("text"), limit=300)))
    raw_field = clean_text(offer.get("languages_required"), limit=2_000)
    if raw_field:
        for token in re.split(r"[,;/|]| et | and ", raw_field):
            token = clean_text(token, limit=120)
            if not token:
                continue
            words = normalized_text(token).split()
            code = next((part for part in words if _language_code(part)), None)
            code = _language_code(code) if code else None
            level = next((_language_level(part) for part in words if _language_level(part)), None)
            if code and all(existing != code for existing, _, _ in required):
                required.append((code, level, token))
    clauses: list[dict[str, Any]] = []
    for code, level, quote in required:
        label = LANGUAGE_LABELS.get(code, code)
        exigence = (
            f"L'offre exige {label} niveau {level}." if level
            else f"L'offre exige {label} (niveau non précisé)."
        )
        profile_raw = profile_by_code.get(code, "")
        profile_level = _language_level(profile_raw) if profile_raw else None
        fait = (
            f"Ton ticket langue : {label} niveau {profile_level}." if profile_level
            else f"Ton ticket langue n'indique pas de niveau pour {label}."
        )
        preuve_offre = _evidence("requirements", quote) if quote else None
        preuve_profil = _evidence("rules.languages.profile_levels", f"{label}: {profile_raw}") if profile_raw else None
        if profile_level is None or level is None:
            statut = CLAUSE_TO_VERIFY
        elif level == "native" and profile_level != "native":
            # « Langue maternelle » n'est comparable qu'à lui-même : un C2
            # ne prouve pas une langue maternelle, mais ne l'exclut pas
            # non plus.  Le point reste à vérifier.
            statut = CLAUSE_TO_VERIFY
        elif LANGUAGE_RANKS[profile_level] >= LANGUAGE_RANKS[level]:
            statut = CLAUSE_OK
        else:
            statut = CLAUSE_NOT_OK
        clauses.append(_clause(
            "languages", f"Langue requise : {label}",
            exigence=exigence, fait=fait, statut=statut,
            preuve_offre=preuve_offre, preuve_profil=preuve_profil,
        ))
    if unidentified:
        quote = clean_text(unidentified[0].get("text"), limit=300)
        clauses.append(_clause(
            "languages", "Langue exigée non identifiable",
            exigence="Une exigence de langue existe mais la langue n'est pas identifiable.",
            fait="Ton ticket langues est celui de tes règles.",
            statut=CLAUSE_TO_VERIFY,
            preuve_offre=_evidence("requirements", quote) if quote else None,
        ))
    if not required and not unidentified:
        clauses.append(_clause(
            "languages", "Langues requises",
            exigence=(
                "Aucune langue exigée trouvée dans l'offre." if extracted
                else "Langues exigées inconnues (extraction des exigences absente)."
            ),
            fait="Ton ticket langues est celui de tes règles.",
            statut=CLAUSE_OK if extracted else CLAUSE_TO_VERIFY,
        ))
    return clauses


# ───────────────────────────────────────────────────────────────────────
# Moteur principal
# ───────────────────────────────────────────────────────────────────────

_CLAUSE_BUILDERS = {
    "contract": lambda offer, rules, conditions: [_clause_contract(offer, rules)],
    "duration": lambda offer, rules, conditions: [_clause_duration(offer, rules)],
    "education": lambda offer, rules, conditions: [
        _clause_education_level(offer, rules),
        _clause_education_field(offer, rules),
    ],
    "work_authorization": lambda offer, rules, conditions: (
        _work_permit_clauses(offer, rules) + [_visa_sponsorship_clause(conditions, rules)]
    ),
    "location": lambda offer, rules, conditions: [
        _clause_location(offer, rules),
        _work_mode_clause(conditions, rules),
    ],
    "languages": lambda offer, rules, conditions: _language_clauses(offer, rules),
}


def check_eligibility(
    offer: Mapping[str, Any],
    rules: Mapping[str, Any] | str | Path | None = None,
    *,
    conditions: Any = None,
    requirements: Any = None,
) -> dict[str, Any]:
    """Confronter une offre au profil approuvé et rendre un verdict.

    Paramètres :
        offer: offre normalisée (dict ou objet avec ``to_dict``).
        rules: règles chargées, chemin de fichier, ou ``None`` (fichier du
            paquet).
        conditions: faits SK-17 déjà extraits du texte de l'offre
            (``None`` = extraction non exécutée).
        requirements: relevés d'exigences déjà analysés (``None`` =
            extraction non exécutée).

    Retour : ``{verdict, clauses, etat_suivant, points_a_verifier,
    motifs_non_eligibilite, rules_version, profile_approved}``.
    """
    if hasattr(offer, "to_dict") and not isinstance(offer, dict):
        offer = offer.to_dict()
    if not isinstance(offer, dict):
        raise TypeError("offer must be an object")
    if rules is None or isinstance(rules, (str, Path)):
        rules = load_rules(rules)
    if not isinstance(rules, dict):
        raise TypeError("rules must be a mapping, a path or None")
    problems = validate_rules(rules)
    if problems:
        raise RulesError("Règles d'éligibilité invalides : " + " ; ".join(problems))
    section = rules["rules"]
    condition_list = _condition_dicts(conditions)
    clause_list: list[dict[str, Any]] = []
    for rule_id, builder in _CLAUSE_BUILDERS.items():
        rule_section = section.get(rule_id)
        if not isinstance(rule_section, dict) or rule_section.get("enabled") is False:
            continue
        payload = dict(offer)
        if rule_id in {"education", "languages"} and requirements is not None:
            # Les relevés passés en argument priment ; à défaut, ceux déjà
            # portés par l'offre restent utilisables.
            payload["requirements"] = requirements
        clause_list.extend(builder(payload, rules, condition_list))
    not_ok = [clause for clause in clause_list if clause["statut_ok"] == CLAUSE_NOT_OK]
    to_verify = [clause for clause in clause_list if clause["statut_ok"] == CLAUSE_TO_VERIFY]
    profile_approved = rules.get("profile_approved") is True
    if not_ok:
        verdict = VERDICT_NOT_ELIGIBLE
    elif to_verify or not profile_approved:
        verdict = VERDICT_TO_VERIFY
    else:
        verdict = VERDICT_ELIGIBLE
    points = [f"{clause['label']} — {clause['exigence_offre']}" for clause in to_verify]
    if not profile_approved and verdict != VERDICT_NOT_ELIGIBLE:
        points.insert(0, "Profil non approuvé — passe profile_approved à true après relecture de tes tickets.")
    motifs = [f"{clause['label']} — {clause['exigence_offre']}" for clause in not_ok]
    return {
        "verdict": verdict,
        "clauses": clause_list,
        "etat_suivant": STATE_BY_VERDICT[verdict],
        "points_a_verifier": points,
        "motifs_non_eligibilite": motifs,
        "rules_version": rules.get("version"),
        "profile_approved": profile_approved,
    }


# ───────────────────────────────────────────────────────────────────────
# Branchement radar / dailies (CVBOOST-35)
# ───────────────────────────────────────────────────────────────────────

def _offer_key(offer: Mapping[str, Any]) -> str:
    return clean_text(offer.get("id") or offer.get("source_id"), limit=240)


def apply_eligibility_to_offers(
    offers: Iterable[Mapping[str, Any]],
    rules: Mapping[str, Any] | str | Path | None = None,
    *,
    conditions_by_offer: Mapping[str, Any] | None = None,
    requirements_by_offer: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Annoter puis trier une liste d'offres pour le radar / les dailies.

    Chaque offre reçoit ``offer["eligibility"]`` (verdict complet) ; les
    offres ``NON ÉLIGIBLES`` passent en fin de liste — marquées, sorties du
    classement par défaut, mais toujours visibles avec leurs motifs.  L'entrée
    n'est jamais mutée : la fonction rend de nouvelles copies.
    """
    conditions_map = conditions_by_offer or {}
    requirements_map = requirements_by_offer or {}
    # Les règles sont chargées une seule fois pour tout le lot : le fichier
    # ne change pas entre deux offres d'un même radar.
    if rules is None or isinstance(rules, (str, Path)):
        rules = load_rules(rules)
    annotated: list[dict[str, Any]] = []
    for offer in offers:
        if not isinstance(offer, dict):
            raise TypeError("offers must be dictionaries")
        key = _offer_key(offer)
        verdict = check_eligibility(
            offer,
            rules,
            conditions=conditions_map.get(key),
            requirements=requirements_map.get(key),
        )
        annotated.append(dict(offer))
        annotated[-1]["eligibility"] = verdict
    annotated.sort(key=eligibility_ranking_key)
    return annotated


def eligibility_ranking_key(offer: Mapping[str, Any]) -> tuple[Any, ...]:
    """Clé de classement : ÉLIGIBLE d'abord, NON ÉLIGIBLE en fin de liste.

    Composable avec la clé de pertinence de ``career.exploration.ranking_key`` :
    les offres éligibles y gardent leur ordre de pertinence, les non
    éligibles restent lisibles en queue sans disparaître.
    """
    eligibility = offer.get("eligibility") if isinstance(offer, dict) else None
    verdict = eligibility.get("verdict") if isinstance(eligibility, dict) else ""
    order = VERDICT_ORDER.get(verdict, VERDICT_ORDER[VERDICT_TO_VERIFY])
    score = offer.get("match_score", offer.get("score"))
    score_value = -int(score) if type(score) in {int, float} else 0
    digest = hashlib.sha256(
        json.dumps(offer, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return (
        order,
        score_value,
        str(offer.get("company") or "").casefold(),
        str(offer.get("source_name") or ""),
        str(offer.get("source_id") or ""),
        digest,
    )
