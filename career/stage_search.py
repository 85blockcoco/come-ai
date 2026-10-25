"""Deterministic stage-search criteria and explainable matching for Career.

This module is a pure, local logic layer.  It never performs a network
request, never calls a model, and never invents an offer, a company or a
date: it only compares facts a person entered (their search brief) with
facts already stored locally for an offer.  Every score component carries
the reason that produced it so the ranking stays auditable.
"""

from __future__ import annotations

from typing import Any

from .countries import DEFAULT_COUNTRIES_EXCLUDE, canonical_country_codes
from .models import (
    COUNTRY_LABELS,
    DEFAULT_GEO_EXCLUDED_COUNTRIES,
    DEFAULT_PREFERRED_COUNTRIES,
    GEO_EXCLUDED_PENALTY,
    GEO_PREFERRED_BOOST,
    JOB_FAMILIES,
    clean_text,
    normalized_text,
    parse_date,
)
from .offer_qualification import geo_score_for
from .sources import SEARCH_TERMS
from .education_access import assess_education_access
from workspace_core import UserFacingError


# The finance domains a person actually hunts for.  These are finer-grained
# than ``JOB_FAMILIES`` (which drive preferences) and deliberately lexical:
# an offer matches only through words its own posting contains.
STAGE_DOMAINS: dict[str, tuple[str, ...]] = {
    "M&A": (
        "m a",
        "mergers",
        "acquisitions",
        "fusion acquisition",
        "fusions acquisitions",
        "investment banking",
        "banque d affaires",
        "corporate finance advisory",
    ),
    "Corporate Finance": (
        "corporate finance",
        "finance d entreprise",
        "finance intern",
        "finance analyst",
        "financial analysis",
        "analyse financiere",
        "valuation",
        "treasury",
        "strategic finance",
    ),
    "Private Equity": (
        "private equity",
        "capital investissement",
        "capital developpement",
        "fonds d investissement",
        "buyout",
        "growth equity",
        "lbo",
    ),
    "Transaction Services": (
        "transaction services",
        "transaction advisory",
        "deals advisory",
        "due diligence",
        "financial due diligence",
        "fdd",
    ),
    "Audit financier": (
        "audit",
        "audit financier",
        "financial audit",
        "statutory audit",
        "controle externe",
        "commissariat aux comptes",
    ),
    "Asset Management": (
        "asset management",
        "gestion d actifs",
        "societe de gestion",
        "gestionnaire de portefeuille",
        "portfolio management",
        "investment research",
        "equity research",
        "fixed income",
    ),
    "FP&A": (
        "fp a",
        "financial planning",
        "planning analytique",
        "controle de gestion",
        "business partner",
        "business partnering",
    ),
    # A catch-all the person selects explicitly; it is resolved after the
    # specific domains so a precise match is always reported first.
    "Autres métiers financiers": (),
}

# Source-faithful vocabulary the person can type into a public board search.
# These are search hints, never offers and never deadlines.
_DOMAIN_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "M&A": SEARCH_TERMS["M&A / Investment Banking"],
    "Corporate Finance": SEARCH_TERMS["Corporate Finance"],
    "Private Equity": SEARCH_TERMS["Private Equity"],
    "Transaction Services": (
        "Transaction Services Intern",
        "Deals Advisory Intern",
        "Financial Due Diligence Intern",
        "Stage Transaction Services",
    ),
    "Audit financier": (
        "Audit Intern",
        "Financial Audit Intern",
        "Statutory Audit Intern",
        "Stage Audit Financier",
    ),
    "Asset Management": SEARCH_TERMS["Asset Management"],
    "FP&A": (
        "FP&A Intern",
        "Financial Planning Analyst Intern",
        "Strategic Finance Intern",
        "Stage FP&A",
    ),
    "Autres métiers financiers": SEARCH_TERMS["Sales & Trading"],
}

RANKING_CRITERIA: dict[str, str] = {
    "domaine": "Domaine recherché",
    "metier": "Intitulé du métier",
    "localisation": "Pays ou ville",
    "dates": "Date de début",
    "duree": "Durée du stage",
    "niveau": "Niveau d’études",
    "langues": "Langues",
}
RANKING_MIN_MULTIPLIER = 0.5
RANKING_MAX_MULTIPLIER = 2.0

_LANGUAGE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("français", ("francais", "french")),
    ("anglais", ("anglais", "english")),
    ("italien", ("italien", "italian", "italiano")),
    ("allemand", ("allemand", "german", "deutsch")),
    ("espagnol", ("espagnol", "spanish", "espanol")),
)

# Ordered from the lowest to the highest common student level.  A requirement
# is satisfied when the offer asks for no more than the declared level.
_STUDY_LEVEL_RANKS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (3, ("bac 3", "bac +3", "bac+3", "licence", "l3", "bachelor", "3rd year")),
    (4, ("bac 4", "bac +4", "bac+4", "m1", "master 1", "4th year")),
    (5, ("bac 5", "bac +5", "bac+5", "m2", "master 2", "master s", "5th year", "mastere")),
    (6, ("bac 6", "bac +6", "bac+6", "m3", "master 3", "6th year")),
    (8, ("doctorat", "phd", "doctorate")),
)

# Unambiguous permanent-contract markers only: "temps plein" alone is
# deliberately excluded because a full-time internship is still an internship.
_PERMANENT_CONTRACT_PATTERNS: tuple[str, ...] = ("cdi", "permanent")

MAX_COMPONENTS = 8
CONTRACT_TYPES: dict[str, str] = {"stage": "Stage", "cdd": "CDD", "cdi": "CDI", "vie": "VIE"}
MONTHS: tuple[tuple[int, str], ...] = (
    (1, "janvier"), (2, "février"), (3, "mars"), (4, "avril"), (5, "mai"), (6, "juin"),
    (7, "juillet"), (8, "août"), (9, "septembre"), (10, "octobre"), (11, "novembre"), (12, "décembre"),
)


def default_brief() -> dict[str, Any]:
    """Default search criteria; optional personal preferences remain empty."""
    return {
        "domains": [],
        "other_domains": [],
        "roles": [],
        "countries": [],
        "cities": [],
        "excluded_countries": [],
        "excluded_cities": [],
        # Countries a connector must never return.  The person never wants
        # French postings, so the default excludes France at the source.
        "countries_exclude": list(DEFAULT_COUNTRIES_EXCLUDE),
        "require_known_location": False,
        "start_date": "",
        "duration_months": None,
        "contract_types": ["stage", "cdd", "cdi", "vie"],
        "start_months": [1, 2, 3],
        "minimum_stage_duration_months": 6,
        "education_preference": "bachelor_m1_then_m2",
        "study_level": "",
        "languages": [],
        "constraints": "",
        "ranking": {},
        # Countries the ranking rewards, and the one it penalizes.  Both are
        # editable: an explicitly empty list turns the signal off.
        "preferred_countries": list(DEFAULT_PREFERRED_COUNTRIES),
        "geo_excluded_countries": list(DEFAULT_GEO_EXCLUDED_COUNTRIES),
    }


def _contains(haystack: str, needle: str) -> bool:
    return f" {needle} " in f" {haystack} "


def _string_list(value: Any, label: str, *, max_items: int, max_length: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise UserFacingError(f"{label} doivent être une liste.")
    if len(value) > max_items:
        raise UserFacingError(f"{label} contiennent trop d’éléments (maximum {max_items}).")
    result: list[str] = []
    for item in value:
        text = clean_text(item, limit=max_length)
        if text and text not in result:
            result.append(text)
    return result


def _ranking_values(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UserFacingError("Les préférences de classement sont invalides.")
    ranking: dict[str, float] = {}
    for key, raw in value.items():
        criterion = clean_text(key, limit=40)
        if criterion not in RANKING_CRITERIA:
            raise UserFacingError(f"La pondération « {criterion or 'vide'} » concerne un critère inconnu.")
        try:
            multiplier = float(raw)
        except (TypeError, ValueError) as error:
            raise UserFacingError("Chaque pondération doit être un nombre entre 0.5 et 2.") from error
        if not RANKING_MIN_MULTIPLIER <= multiplier <= RANKING_MAX_MULTIPLIER:
            raise UserFacingError(
                f"La pondération de « {RANKING_CRITERIA[criterion]} » doit rester entre "
                f"{RANKING_MIN_MULTIPLIER} et {RANKING_MAX_MULTIPLIER}."
            )
        ranking[criterion] = round(multiplier, 2)
    return ranking


def _countries_exclude(payload: dict[str, Any]) -> list[str]:
    """Countries a connector must never return, as canonical ISO codes.

    Three inputs are read, in this order:

    * ``countries_exclude`` — the explicit list, written in ISO codes.  An
      empty list turns the filter off: it is the only way for a French
      posting to reach the person.
    * ``excluded_countries`` — the older free-text list the interface still
      edits.  An emptied list means the person removed every country
      exclusion, so the source filter must follow instead of silently
      keeping the default.
    * neither — France stays excluded, the one country this product never
      offers.  A country the person explicitly asks for is not excluded.

    The list is resolved once, here, so every connector reads the same
    countries and no wording is interpreted twice.
    """
    if "countries_exclude" in payload and payload.get("countries_exclude") is not None:
        raw = payload.get("countries_exclude")
        if not isinstance(raw, list):
            raise UserFacingError("Les pays exclus par défaut doivent être une liste.")
        if len(raw) > 20:
            raise UserFacingError("Les pays exclus par défaut contiennent trop d’éléments (maximum 20).")
        return list(canonical_country_codes(raw))
    if "excluded_countries" in payload:
        raw_legacy = payload.get("excluded_countries") or []
        if not isinstance(raw_legacy, list):
            raise UserFacingError("Les pays exclus doivent être une liste.")
        if not raw_legacy:
            # An emptied list is an explicit choice: no country is excluded,
            # and a French posting may reach the person again.
            return []
        legacy = list(canonical_country_codes(raw_legacy))
        # A list that names no known country keeps the default instead of
        # silently disabling the filter.
        return legacy or list(DEFAULT_COUNTRIES_EXCLUDE)
    wanted = set(canonical_country_codes(payload.get("countries") or []))
    return [code for code in DEFAULT_COUNTRIES_EXCLUDE if code not in wanted]


def validate_brief(payload: Any) -> dict[str, Any]:
    """Validate and normalize a stage-search brief once, without presumption."""
    if payload is None:
        return default_brief()
    if not isinstance(payload, dict):
        raise UserFacingError("Le stage recherché est invalide.")
    domain_lookup = {normalized_text(label): label for label in STAGE_DOMAINS}
    domains: list[str] = []
    for item in _string_list(payload.get("domains"), "Les domaines", max_items=12, max_length=80):
        canonical = domain_lookup.get(normalized_text(item))
        if not canonical:
            raise UserFacingError(
                f"Le domaine « {item} » n’existe pas. Domaines disponibles : {', '.join(STAGE_DOMAINS)}."
            )
        if canonical not in domains:
            domains.append(canonical)
    start = payload.get("start_date", "")
    start_text = clean_text(start, limit=32)
    if start_text:
        parse_date(start_text, "La date de début recherchée")
    duration_raw = payload.get("duration_months")
    duration: int | None = None
    if clean_text(duration_raw):
        try:
            duration = int(str(duration_raw).strip())
        except ValueError as error:
            raise UserFacingError("La durée recherchée doit être un nombre de mois entier.") from error
        if not 1 <= duration <= 24:
            raise UserFacingError("La durée recherchée doit être comprise entre 1 et 24 mois.")
    contract_types: list[str] = []
    for item in _string_list(payload.get("contract_types", ["stage", "cdd", "cdi", "vie"]),
                             "Les types de contrat", max_items=4, max_length=20):
        canonical = item.strip().casefold()
        if canonical not in CONTRACT_TYPES:
            raise UserFacingError("Type de contrat inconnu. Choisis Stage, CDD, CDI ou VIE.")
        if canonical not in contract_types:
            contract_types.append(canonical)
    if not contract_types:
        raise UserFacingError("Sélectionne au moins un type de contrat.")
    month_values = payload.get("start_months", [1, 2, 3])
    if not isinstance(month_values, list) or len(month_values) > 12:
        raise UserFacingError("Les mois de début doivent être une liste de 1 à 12.")
    start_months: list[int] = []
    for item in month_values:
        if type(item) is not int or not 1 <= item <= 12:
            raise UserFacingError("Chaque mois de début doit être compris entre janvier et décembre.")
        if item not in start_months:
            start_months.append(item)
    start_months.sort()
    if not start_months:
        raise UserFacingError("Sélectionne au moins un mois de début.")
    minimum_stage_duration = payload.get("minimum_stage_duration_months", 6)
    if type(minimum_stage_duration) is not int or not 1 <= minimum_stage_duration <= 24:
        raise UserFacingError("La durée minimale du stage doit être comprise entre 1 et 24 mois.")
    education_preference = payload.get("education_preference", "bachelor_m1_then_m2")
    if education_preference not in {"bachelor_m1_then_m2", "any"}:
        raise UserFacingError("Préférence de niveau d’études inconnue.")
    require_known_location = payload.get("require_known_location", False)
    if type(require_known_location) is not bool:
        raise UserFacingError("Le contrôle de localisation doit être activé ou désactivé explicitement.")
    # The geographic ranking signal is configured by the person.  An explicit
    # list wins, even an empty one (the penalty is then off); without any
    # list, France stays penalized by default.  A field that is present but
    # null means "not configured": the default then applies.
    if payload.get("geo_excluded_countries") is not None:
        geo_excluded_countries = _string_list(
            payload.get("geo_excluded_countries"), "Les pays pénalisés au classement",
            max_items=40, max_length=120,
        )
    elif payload.get("excluded_countries") is not None:
        geo_excluded_countries = _string_list(
            payload.get("excluded_countries"), "Les pays pénalisés au classement",
            max_items=40, max_length=120,
        )
    else:
        geo_excluded_countries = list(DEFAULT_GEO_EXCLUDED_COUNTRIES)
    if payload.get("preferred_countries") is None:
        preferred_countries = list(DEFAULT_PREFERRED_COUNTRIES)
    else:
        preferred_countries = _string_list(
            payload.get("preferred_countries"), "Les pays ciblés",
            max_items=40, max_length=120,
        )
    return {
        "domains": domains,
        "other_domains": _string_list(payload.get("other_domains"), "Les autres métiers", max_items=12, max_length=120),
        "roles": _string_list(payload.get("roles"), "Les métiers", max_items=20, max_length=120),
        "countries": _string_list(payload.get("countries"), "Les pays", max_items=20, max_length=120),
        "cities": _string_list(payload.get("cities"), "Les villes", max_items=20, max_length=120),
        "excluded_countries": _string_list(
            payload.get("excluded_countries", []), "Les pays exclus", max_items=20, max_length=120
        ),
        "excluded_cities": _string_list(
            payload.get("excluded_cities", []), "Les villes exclues", max_items=20, max_length=120
        ),
        "countries_exclude": _countries_exclude(payload),
        "require_known_location": require_known_location,
        "start_date": start_text,
        "duration_months": duration,
        "contract_types": contract_types,
        "start_months": start_months,
        "minimum_stage_duration_months": minimum_stage_duration,
        "education_preference": education_preference,
        "study_level": clean_text(payload.get("study_level"), limit=120),
        "languages": _string_list(payload.get("languages"), "Les langues", max_items=10, max_length=60),
        "constraints": clean_text(payload.get("constraints"), limit=2_000),
        "ranking": _ranking_values(payload.get("ranking")),
        "preferred_countries": preferred_countries,
        "geo_excluded_countries": geo_excluded_countries,
    }


def brief_is_configured(brief: dict[str, Any]) -> bool:
    """Whether the person asked for at least one concrete criterion."""
    return any(
        [
            brief.get("domains"),
            brief.get("other_domains"),
            brief.get("roles"),
            brief.get("countries"),
            brief.get("cities"),
            brief.get("excluded_countries"),
            brief.get("excluded_cities"),
            brief.get("require_known_location") is True,
            clean_text(brief.get("start_date"), limit=32),
            clean_text(brief.get("duration_months")),
            clean_text(brief.get("study_level"), limit=120),
            brief.get("languages"),
            brief.get("contract_types", ["stage", "cdd", "cdi", "vie"]) != ["stage", "cdd", "cdi", "vie"],
            brief.get("start_months", [1, 2, 3]) != [1, 2, 3],
            brief.get("minimum_stage_duration_months", 6) != 6,
        ]
    )


def vocabulary() -> dict[str, Any]:
    """Everything the interface needs to render the brief form."""
    return {
        "domains": list(STAGE_DOMAINS),
        "contract_types": [{"key": key, "label": label} for key, label in CONTRACT_TYPES.items()],
        "months": [{"value": value, "label": label} for value, label in MONTHS],
        "quarter_months": [1, 2, 3],
        "default_countries_exclude": list(DEFAULT_COUNTRIES_EXCLUDE),
        "ranking_criteria": [
            {"key": key, "label": label} for key, label in RANKING_CRITERIA.items()
        ],
        "ranking_min": RANKING_MIN_MULTIPLIER,
        "ranking_max": RANKING_MAX_MULTIPLIER,
        # Countries the ranking rewards and the one it penalizes: the form can
        # offer them without inventing a preference of its own.
        "preferred_countries": list(DEFAULT_PREFERRED_COUNTRIES),
        "geo_excluded_countries": list(DEFAULT_GEO_EXCLUDED_COUNTRIES),
        "countries": [
            {"code": code, "label": label}
            for code, label in sorted(COUNTRY_LABELS.items())
        ],
        "geo_preferred_boost": GEO_PREFERRED_BOOST,
        "geo_excluded_penalty": GEO_EXCLUDED_PENALTY,
    }


def search_terms_for(domains: list[str]) -> list[dict[str, Any]]:
    """Local query vocabulary for the selected domains (no browsing here)."""
    return [
        {"domain": domain, "terms": list(_DOMAIN_SEARCH_TERMS.get(domain, ()))}
        for domain in domains
        if domain in _DOMAIN_SEARCH_TERMS
    ]


def _component(key: str, points: int, maximum: int, *, status: str, reason: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": RANKING_CRITERIA[key],
        "points": int(points),
        "maximum": int(maximum),
        "status": status,
        "reason": clean_text(reason, limit=400),
    }


def _matched_domains(text: str, job_family: str, brief: dict[str, Any]) -> list[tuple[str, str]]:
    matched: list[tuple[str, str]] = []
    for domain in brief.get("domains", []):
        if domain == "Autres métiers financiers":
            continue
        term = next((pattern for pattern in STAGE_DOMAINS.get(domain, ()) if _contains(text, pattern)), "")
        if term:
            matched.append((domain, term))
    if not matched and "Autres métiers financiers" in brief.get("domains", []):
        if job_family in JOB_FAMILIES:
            matched.append(("Autres métiers financiers", job_family))
    for custom in brief.get("other_domains", []):
        pattern = normalized_text(custom)
        if pattern and _contains(text, pattern):
            matched.append((custom, pattern))
    return matched


def _language_names(value: Any) -> set[str]:
    text = normalized_text(value)
    return {
        canonical
        for canonical, patterns in _LANGUAGE_ALIASES
        if any(_contains(text, pattern) for pattern in patterns)
    }


def _study_rank(value: Any) -> int | None:
    text = normalized_text(value)
    rank: int | None = None
    for candidate, patterns in _STUDY_LEVEL_RANKS:
        if any(_contains(text, pattern) for pattern in patterns):
            rank = candidate if rank is None else max(rank, candidate)
    return rank


def _geo_excluded_countries(brief: dict[str, Any]) -> list[str]:
    """Countries the ranking penalises, read from the brief the person saved.

    A brief that names its own penalised list wins, even when that list is
    empty (the penalty is then off).  A brief that only knows the hard
    exclusions uses them.  A brief that names neither keeps France penalised
    by default.
    """
    if "geo_excluded_countries" in brief:
        return [clean_text(item, limit=120) for item in (brief.get("geo_excluded_countries") or [])]
    if "excluded_countries" in brief:
        return [clean_text(item, limit=120) for item in (brief.get("excluded_countries") or [])]
    return list(DEFAULT_GEO_EXCLUDED_COUNTRIES)


def score_brief_match(brief: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Compare one stored offer with the search brief; every point is explained.

    Only requested criteria take part in the score.  A criterion whose value
    is unknown on the offer earns no point but stays visible as a review item,
    which keeps an incomplete posting from looking like a confident match.
    """
    components: list[dict[str, Any]] = []
    reasons: list[str] = []
    unknowns: list[str] = []
    warnings: list[str] = []

    text = normalized_text(
        f"{clean_text(job.get('title'), limit=300)} "
        f"{clean_text(job.get('description_original'), limit=30_000)} "
        f"{clean_text(job.get('requirements'), limit=12_000)}"
    )
    job_family = clean_text(job.get("job_family"), limit=160)

    if brief.get("domains") or brief.get("other_domains"):
        matched = _matched_domains(text, job_family, brief)
        if matched:
            detail = ", ".join(f"{domain} (« {term} »)" for domain, term in matched[:4])
            components.append(_component("domaine", 30, 30, status="match", reason=f"Domaines repérés : {detail}."))
            reasons.append(f"Domaines repérés : {detail}.")
        elif text:
            components.append(
                _component(
                    "domaine",
                    0,
                    30,
                    status="no_match",
                    reason="Aucun domaine recherché n’apparaît dans le texte de cette offre.",
                )
            )
        else:
            components.append(
                _component("domaine", 0, 30, status="unknown", reason="Le texte de l’offre est insuffisant pour vérifier le domaine.")
            )
            unknowns.append("Domaine non vérifiable faute de texte source.")

    if brief.get("roles"):
        title = normalized_text(job.get("title"))
        role = next((item for item in brief["roles"] if _contains(title, normalized_text(item))), "")
        if title and role:
            components.append(_component("metier", 15, 15, status="match", reason=f"L’intitulé contient « {role} »."))  # noqa: E501 - short reason
            reasons.append(f"L’intitulé contient « {role} ».")
        elif title:
            components.append(
                _component("metier", 0, 15, status="no_match", reason="L’intitulé ne correspond à aucun métier recherché.")
            )
        else:
            components.append(_component("metier", 0, 15, status="unknown", reason="Intitulé absent."))
            unknowns.append("Métier non vérifiable faute d’intitulé.")

    if brief.get("cities") or brief.get("countries"):
        city = normalized_text(job.get("city"))
        country = normalized_text(job.get("country"))
        wanted_cities = [normalized_text(item) for item in brief.get("cities", [])]
        wanted_countries = [normalized_text(item) for item in brief.get("countries", [])]
        city_match = next(
            (item for item in wanted_cities if item and (item in city or city in item) and city),
            "",
        )
        country_match = next(
            (item for item in wanted_countries if item and (item in country or country in item) and country),
            "",
        )
        if city_match:
            components.append(_component("localisation", 20, 20, status="match", reason=f"Ville correspondante : {job.get('city')}."))
            reasons.append(f"Ville correspondante : {job.get('city')}.")
        elif country_match:
            components.append(
                _component("localisation", 12, 20, status="match", reason=f"Pays correspondant : {job.get('country')}.")
            )
            reasons.append(f"Pays correspondant : {job.get('country')}.")
        elif city or country:
            components.append(
                _component(
                    "localisation",
                    0,
                    20,
                    status="no_match",
                    reason="La localisation de l’offre ne correspond à aucun pays ni ville recherché.",
                )
            )
        else:
            components.append(
                _component("localisation", 0, 20, status="unknown", reason="Localisation absente de l’offre.")
            )
            unknowns.append("Localisation non renseignée par la source.")

    start_text = clean_text(brief.get("start_date"), limit=32)
    if start_text:
        wanted_start = parse_date(start_text, "La date de début recherchée")
        job_start = parse_date(job.get("start_date"), "La date de début de l’offre")
        job_end = parse_date(job.get("end_date"), "La date de fin de l’offre")
        start_fact = None
        if not job_start:
            # Use only explicit, uncontradicted source evidence. A month-level
            # fact may meet an earliest-date criterion on day 1 of that month;
            # it cannot establish a later day in the same month.
            from .offer_dates import extract_offer_dates

            facts = [fact for fact in extract_offer_dates(job) if fact.fact_type == "start"]
            usable = [fact for fact in facts if not fact.contradictions and fact.confidence != "ambiguous"]
            if len(usable) == 1:
                start_fact = usable[0]
                value = start_fact.value
                if value.get("year") and value.get("month"):
                    from datetime import date

                    job_start = date(int(value["year"]), int(value["month"]), int(value.get("day") or 1))
        if job_start and wanted_start:
            if start_fact and start_fact.precision != "day" and job_start == wanted_start and wanted_start.day != 1:
                components.append(_component("dates", 8, 15, status="review", reason=f"La source indique « {start_fact.quote} » : le jour exact reste à vérifier."))
                unknowns.append("Jour exact de début non précisé par la source.")
            elif job_start >= wanted_start:
                reason = (f"Début annoncé selon la source : « {start_fact.quote} » (mois/année)." if start_fact else f"Début annoncé le {job_start.isoformat()}.")
                components.append(
                    _component("dates", 15, 15, status="match", reason=reason)
                )
                reasons.append(reason)
            elif job_end and job_end >= wanted_start:
                components.append(
                    _component(
                        "dates",
                        8,
                        15,
                        status="review",
                        reason=f"Début annoncé avant ta date ({job_start.isoformat()}) : à vérifier.",
                    )
                )
            else:
                components.append(
                    _component("dates", 0, 15, status="no_match", reason="Le stage se termine avant ta date de début.")
                )
        elif start_fact and not start_fact.value.get("year"):
            reason = f"La source indique « {start_fact.quote} », sans année : début à vérifier."
            components.append(_component("dates", 8, 15, status="review", reason=reason))
            unknowns.append("Année de début non renseignée par la source.")
        elif job_end and wanted_start:
            status = "review" if job_end >= wanted_start else "no_match"
            points = 8 if status == "review" else 0
            components.append(
                _component(
                    "dates",
                    points,
                    15,
                    status=status,
                    reason=f"Seule la fin est connue ({job_end.isoformat()}) : début à vérifier.",
                )
            )
            if status != "review":
                unknowns.append("La fin annoncée précède ta date de début.")
        elif not job_start and not job_end:
            components.append(
                _component("dates", 0, 15, status="unknown", reason="Les dates du stage ne sont pas renseignées.")
            )
            unknowns.append("Dates non renseignées par la source.")

    wanted_duration = brief.get("duration_months")
    if wanted_duration:
        job_duration = job.get("duration_months")
        try:
            job_duration = int(job_duration) if clean_text(job_duration) else None
        except (TypeError, ValueError):
            job_duration = None
        if job_duration:
            if job_duration >= int(wanted_duration):
                components.append(
                    _component("duree", 10, 10, status="match", reason=f"Durée annoncée : {job_duration} mois.")
                )
                reasons.append(f"Durée annoncée : {job_duration} mois.")
            else:
                components.append(
                    _component(
                        "duree",
                        0,
                        10,
                        status="no_match",
                        reason=f"Durée annoncée ({job_duration} mois) inférieure à {wanted_duration} mois.",
                    )
                )
        else:
            components.append(_component("duree", 0, 10, status="unknown", reason="Durée non renseignée par la source."))
            unknowns.append("Durée non renseignée par la source.")

    study_level = clean_text(brief.get("study_level"), limit=120)
    if study_level:
        wanted_rank = _study_rank(study_level)
        offer_text = normalized_text(
            f"{clean_text(job.get('role_level'), limit=120)} {clean_text(job.get('requirements'), limit=12_000)}"
        )
        offer_rank = _study_rank(offer_text)
        if wanted_rank and offer_rank:
            if offer_rank <= wanted_rank:
                components.append(
                    _component("niveau", 5, 5, status="match", reason="Le niveau demandé est compatible avec ton niveau déclaré.")
                )
                reasons.append("Le niveau demandé est compatible avec ton niveau déclaré.")
            else:
                components.append(
                    _component(
                        "niveau",
                        0,
                        5,
                        status="no_match",
                        reason="Le niveau demandé est supérieur au niveau déclaré dans tes critères.",
                    )
                )
        elif wanted_rank and not offer_text:
            components.append(_component("niveau", 0, 5, status="unknown", reason="Le niveau demandé n’est pas indiqué."))
            unknowns.append("Niveau d’études non renseigné par la source.")
        else:
            components.append(
                _component("niveau", 0, 5, status="unknown", reason="Ton niveau déclaré n’a pu être comparé à aucune exigence explicite.")
            )
            unknowns.append("Comparaison de niveau non déterministe : vérifie la page officielle.")

    if brief.get("languages"):
        wanted_languages = _language_names(" ".join(brief["languages"]))
        required = _language_names(job.get("languages_required"))
        if required:
            if required.issubset(wanted_languages):
                components.append(
                    _component("langues", 5, 5, status="match", reason=f"Langues demandées déclarées : {', '.join(sorted(required))}.")
                )
                reasons.append(f"Langues demandées déclarées : {', '.join(sorted(required))}.")
            else:
                missing = ", ".join(sorted(required - wanted_languages))
                components.append(
                    _component("langues", 0, 5, status="no_match", reason=f"Langues demandées non déclarées : {missing}.")
                )
        else:
            components.append(
                _component("langues", 0, 5, status="unknown", reason="La source ne précise pas les langues requises.")
            )
            unknowns.append("Langues non renseignées par la source.")

    ranking = brief.get("ranking", {})
    weighted_points = 0.0
    weighted_maximum = 0.0
    applied: dict[str, float] = {}
    for component in components[:MAX_COMPONENTS]:
        multiplier = float(ranking.get(component["key"], 1.0))
        applied[component["key"]] = multiplier
        weighted_points += component["points"] * multiplier
        weighted_maximum += component["maximum"] * multiplier

    base_score = round(100 * weighted_points / weighted_maximum) if weighted_maximum else None
    # Geographic ranking signal: the country the source wrote decides the
    # points, never the city.  ``base_score`` keeps the relevance of the
    # offer on its own; ``score`` is the total every ranking uses, so an
    # offer published in a penalised country can never lead a list.
    geo_score, geo_reason = geo_score_for(
        job.get("country"),
        preferred_countries=brief.get("preferred_countries"),
        excluded_countries=_geo_excluded_countries(brief),
    )
    score = None if base_score is None else max(0, min(100, base_score + geo_score))
    if geo_score:
        reasons.insert(0, f"{geo_reason} : {geo_score:+d} points au classement.")
    if score is None:
        label = "Aucun critère renseigné : classement neutre"
    elif score >= 70:
        label = "Correspondance forte"
    elif score >= 45:
        label = "Correspondance à examiner"
    else:
        label = "Correspondance faible ou incomplète"

    source_status = clean_text(job.get("source_status"), limit=40) or "unknown"
    if source_status != "open":
        warnings.append(
            "Le statut de cette annonce n’est pas confirmé ouvert par la source ; elle a peut-être été pourvue."
        )
    deadline_status = clean_text(job.get("deadline_status"), limit=40)
    if deadline_status == "closed":
        warnings.append("La date limite connue est dépassée ou l’annonce est indiquée fermée.")
    # Warn only when a permanent contract falls outside the selected types.
    employment = normalized_text(job.get("employment_type"))
    if ("cdi" not in brief.get("contract_types", ["stage", "cdd", "cdi", "vie"])
            and employment and any(_contains(employment, pattern) for pattern in _PERMANENT_CONTRACT_PATTERNS)):
        warnings.append(
            f"Contrat permanent annoncé (« {clean_text(job.get('employment_type'), limit=120)} ») : "
            "cette offre n’est probablement pas un stage."
        )
    if not clean_text(job.get("official_url"), limit=2_000):
        warnings.append("Aucune URL officielle n’est conservée pour cette offre : vérifie la source avant toute action.")

    return {
        "score": score,
        "base_score": base_score,
        "geo_score": geo_score,
        "geo_reason": geo_reason,
        "total_score": score,
        "education_access": assess_education_access(job, brief.get("education_preference", "bachelor_m1_then_m2")),
        "label": label,
        "components": components[:MAX_COMPONENTS],
        "weights_applied": applied,
        "reasons": reasons[:8],
        "unknowns": unknowns[:8],
        "warnings": warnings[:6],
        "disclaimer": "Comparaison locale déterministe entre tes critères et les faits enregistrés de l’offre ; ce n’est ni une prédiction, ni une vérification du site de l’entreprise.",
    }
