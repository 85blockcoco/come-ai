"""Transparent local matching for Career Agent opportunities.

The score is deliberately deterministic and conservative.  It is a priority
signal based only on facts a person entered or an official posting supplied;
it is never a prediction of a recruitment outcome and it never modifies a
shortlist or creates an application.
"""

from __future__ import annotations

from typing import Any, Iterable

from .models import JOB_FAMILIES, clean_text, deadline_state, normalized_text


SCORING_VERSION = "deterministic-v1"
SCORING_WEIGHTS = {
    "metier": 25,
    "competences": 20,
    "geographie": 15,
    "disponibilite": 15,
    "eligibilite": 10,
    "entreprise": 10,
    "langues": 5,
}

_FAMILY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Private Equity",
        (
            "private equity",
            "capital investissement",
            "buyout",
            "growth equity",
            "lbo",
        ),
    ),
    (
        "M&A / Investment Banking",
        (
            "investment banking",
            "m a",
            "mergers acquisitions",
            "merger acquisition",
            "fusion acquisition",
            "global advisory",
            "corporate finance advisory",
        ),
    ),
    (
        "Asset Management",
        (
            "asset management",
            "gestion d actifs",
            "portfolio management",
            "investment research",
            "equity research",
            "fixed income",
        ),
    ),
    (
        "Sales & Trading",
        (
            "sales trading",
            "global markets",
            "equity sales",
            "fixed income sales",
            "trading internship",
        ),
    ),
    (
        "Corporate Finance",
        (
            "corporate finance",
            "financial planning analysis",
            "financial analysis",
            "analyse financiere",
            "fp a",
            "treasury",
            "valuation",
        ),
    ),
    (
        "Consulting",
        (
            "strategy consulting",
            "consulting intern",
            "transaction services",
            "deals advisory",
            "conseil en strategie",
        ),
    ),
)

_SKILL_PATTERNS: tuple[str, ...] = (
    "excel",
    "python",
    "vba",
    "sql",
    "power bi",
    "powerpoint",
    "bloomberg",
    "valuation",
    "financial modeling",
    "modelisation financiere",
    "financial analysis",
    "analyse financiere",
    "accounting",
    "comptabilite",
    "due diligence",
    "lbo",
    "mergers acquisitions",
    "m a",
    "private equity",
    "asset management",
    "portfolio management",
    "equity research",
    "fixed income",
    "sales trading",
    "market research",
    "market analysis",
    "data analysis",
    "analyse de donnees",
    "presentation",
)

_LANGUAGE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("français", ("francais", "french")),
    ("anglais", ("anglais", "english")),
    ("italien", ("italien", "italiano", "italian")),
    ("allemand", ("allemand", "deutsch", "german")),
)

_LOCATION_PATTERNS: dict[str, tuple[str, ...]] = {
    "paris": ("paris",),
    "london": ("london", "londres"),
    "milan": ("milan", "milano"),
    "luxembourg": ("luxembourg",),
    "frankfurt": ("frankfurt", "francfort"),
    "geneva": ("geneva", "geneve"),
}
_EUROPE_TERMS = (
    "france",
    "uk",
    "united kingdom",
    "royaume uni",
    "italy",
    "italie",
    "germany",
    "allemagne",
    "luxembourg",
    "switzerland",
    "suisse",
    "spain",
    "espagne",
    "belgium",
    "belgique",
    "netherlands",
    "pays bas",
    "ireland",
    "irlande",
    "austria",
    "autriche",
    "denmark",
    "sweden",
    "norway",
    "finland",
    "portugal",
    "poland",
    "pologne",
)


def _contains(normalized_haystack: str, pattern: str) -> bool:
    return f" {pattern} " in f" {normalized_haystack} "


def classify_job_family(title: Any, description: Any = "") -> str:
    """Classify only clear lexical matches; ambiguous roles remain unspecified."""
    title_text = normalized_text(title)
    combined = normalized_text(f"{clean_text(title, limit=300)}\n{clean_text(description, limit=30_000)}")
    matches: list[str] = []
    for family, patterns in _FAMILY_PATTERNS:
        # A title match is stronger than a descriptive mention, but both must
        # use a known phrase. We do not infer family from company or location.
        if any(_contains(title_text, pattern) for pattern in patterns) or any(
            _contains(combined, pattern) for pattern in patterns
        ):
            matches.append(family)
    return matches[0] if len(matches) == 1 else "À préciser"


def _component(
    key: str, points: int, *, status: str, reason: str, maximum: int | None = None
) -> dict[str, Any]:
    return {
        "key": key,
        "label": {
            "metier": "Métier ciblé",
            "competences": "Compétences déclarées",
            "geographie": "Géographie",
            "disponibilite": "Disponibilité",
            "eligibilite": "Éligibilité",
            "entreprise": "Entreprise préférée",
            "langues": "Langues",
        }[key],
        "points": int(points),
        "maximum": SCORING_WEIGHTS[key] if maximum is None else int(maximum),
        "status": status,
        "reason": reason,
    }


def _preferences(preferences: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    # ``family`` and ``location`` deliberately map to the public preferences
    # payload keys.  A naïve ``f"{kind}s"`` would look for ``familys`` and
    # silently make every configured target métier disappear from the score.
    keys = {"family": "families", "location": "locations"}
    raw = preferences.get(keys.get(kind, f"{kind}s"), []) if isinstance(preferences, dict) else []
    return [entry for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []


def _enabled(preferences: dict[str, Any], kind: str, *, label: str = "", key: str = "") -> dict[str, Any] | None:
    for item in _preferences(preferences, kind):
        if not bool(item.get("enabled", False)):
            continue
        if label and normalized_text(item.get("label")) == normalized_text(label):
            return item
        if key and clean_text(item.get("key"), limit=80) == key:
            return item
    return None


def _language_names(value: Any) -> set[str]:
    text = normalized_text(value)
    return {
        canonical
        for canonical, patterns in _LANGUAGE_PATTERNS
        if any(_contains(text, pattern) for pattern in patterns)
    }


def _skill_matches(candidate_text: str, offer_text: str) -> list[str]:
    candidate = normalized_text(candidate_text)
    offer = normalized_text(offer_text)
    return [term for term in _SKILL_PATTERNS if _contains(candidate, term) and _contains(offer, term)]


def _company_preferences(value: Any) -> list[str]:
    return [normalized_text(part) for part in clean_text(value, limit=2_000).split(",") if normalized_text(part)]


def _add_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _as_text(values: Iterable[Any]) -> str:
    return "\n".join(clean_text(value, limit=8_000) for value in values if clean_text(value, limit=8_000))


def scoring_placeholder() -> dict[str, Any]:
    """Legacy compatibility for callers that still expect an empty score."""
    return {
        "state": "not_configured",
        "score": None,
        "version": SCORING_VERSION,
        "weights": SCORING_WEIGHTS,
        "reason": "Un profil et une offre sont nécessaires pour calculer le score local.",
        "confidence": "non évaluée",
        "unknowns": ["Score détaillé non encore calculé."],
    }


def score_job(
    profile: dict[str, Any] | None,
    preferences: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    job: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a reproducible relevance score and its factual limits.

    Missing information gets no positive points. It is displayed as a review
    item rather than converted into a negative claim about the candidate.
    """
    profile = profile if isinstance(profile, dict) else {}
    preferences = preferences if isinstance(preferences, dict) else {}
    intake = intake if isinstance(intake, dict) else {}
    job = job if isinstance(job, dict) else {}
    answers = intake.get("answers", {}) if isinstance(intake.get("answers"), dict) else {}
    components: list[dict[str, Any]] = []
    reasons: list[str] = []
    unknowns: list[str] = []
    blockers: list[str] = []

    job_family = clean_text(job.get("job_family"), limit=160) or "À préciser"
    if job_family == "À préciser":
        job_family = classify_job_family(job.get("title"), job.get("description_original"))
    matched_family = _enabled(preferences, "family", label=job_family)
    if job_family in JOB_FAMILIES and matched_family:
        text = f"{job_family} est une préférence métier active."
        components.append(_component("metier", 25, status="match", reason=text))
        _add_unique(reasons, text)
    elif job_family in JOB_FAMILIES:
        text = f"{job_family} n’est pas une préférence métier active."
        components.append(_component("metier", 0, status="no_match", reason=text))
        _add_unique(reasons, text)
    else:
        text = "La famille de métier de cette offre reste à préciser."
        components.append(_component("metier", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)

    candidate_skill_text = _as_text(
        (profile.get("skills"), profile.get("experience"), answers.get("strengths"), answers.get("missions"))
    )
    offer_skill_text = _as_text((job.get("title"), job.get("requirements"), job.get("description_original")))
    if not candidate_skill_text:
        text = "Aucune compétence ou expérience factuelle n’est encore déclarée dans le profil."
        components.append(_component("competences", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)
    elif not offer_skill_text:
        text = "La source ne détaille pas les compétences attendues."
        components.append(_component("competences", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)
    else:
        skills = _skill_matches(candidate_skill_text, offer_skill_text)
        if skills:
            points = min(20, round(20 * min(len(skills), 3) / 3))
            display = ", ".join(skills[:4])
            text = f"Compétences citées à la fois dans le profil et l’offre : {display}."
            components.append(_component("competences", points, status="match", reason=text))
            _add_unique(reasons, text)
        else:
            text = "Aucun recoupement lexical certain de compétences n’a été trouvé ; cela ne signifie pas une inaptitude."
            components.append(_component("competences", 0, status="review", reason=text))
            _add_unique(unknowns, text)

    location_text = normalized_text(f"{job.get('city', '')} {job.get('country', '')}")
    location_match: dict[str, Any] | None = None
    location_key = ""
    for key, patterns in _LOCATION_PATTERNS.items():
        if any(_contains(location_text, pattern) for pattern in patterns):
            location_key = key
            location_match = _enabled(preferences, "location", key=key)
            break
    if not location_text:
        text = "La localisation de l’offre n’est pas indiquée."
        components.append(_component("geographie", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)
    elif location_match:
        is_secondary = clean_text(location_match.get("scope"), limit=20) == "secondary"
        points = 8 if is_secondary else 15
        text = f"{location_match.get('label')} correspond à une géographie {'secondaire' if is_secondary else 'prioritaire'} active."
        components.append(_component("geographie", points, status="match", reason=text))
        _add_unique(reasons, text)
    elif not location_key and any(_contains(location_text, term) for term in _EUROPE_TERMS) and _enabled(
        preferences, "location", key="other-europe"
    ):
        text = "La localisation européenne correspond à l’option « Autres villes européennes » active."
        components.append(_component("geographie", 8, status="match", reason=text))
        _add_unique(reasons, text)
    else:
        text = "La localisation connue ne correspond pas à une préférence géographique active."
        components.append(_component("geographie", 0, status="no_match", reason=text))

    calendar = clean_text(job.get("calendar_status"), limit=80) or "to_verify"
    calendar_points = {
        "compatible": 15,
        "partial": 10,
        "potentially_incompatible": 5,
        "incompatible": 0,
        "to_verify": 0,
    }.get(calendar, 0)
    calendar_reason = "; ".join(
        clean_text(item, limit=300) for item in job.get("calendar_reasons", []) if clean_text(item, limit=300)
    ) if isinstance(job.get("calendar_reasons"), list) else ""
    if calendar == "incompatible":
        text = calendar_reason or "La période connue de l’offre est incompatible avec la disponibilité configurée."
        components.append(_component("disponibilite", 0, status="blocked", reason=text))
        _add_unique(blockers, text)
    elif calendar == "to_verify":
        text = calendar_reason or "Les dates ou la durée de l’offre ne sont pas suffisamment renseignées."
        components.append(_component("disponibilite", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)
    else:
        text = calendar_reason or "La période annoncée a été comparée à la disponibilité configurée."
        components.append(_component("disponibilite", calendar_points, status="match" if calendar == "compatible" else "review", reason=text))
        _add_unique(reasons, text)

    eligibility_requirement = clean_text(job.get("eligibility_requirement"), limit=2_000)
    eligibility = clean_text(profile.get("eligibility"), limit=40) or "unknown"
    if not eligibility_requirement:
        text = "Aucune condition d’éligibilité structurée n’est indiquée par cette offre."
        components.append(_component("eligibilite", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)
    elif eligibility == "incompatible":
        text = "L’offre indique une condition d’éligibilité et le profil la déclare incompatible."
        components.append(_component("eligibilite", 0, status="blocked", reason=text))
        _add_unique(blockers, text)
    elif eligibility == "compatible":
        text = "Le profil déclare l’éligibilité compatible ; relis toutefois la condition officielle."
        components.append(_component("eligibilite", 10, status="match", reason=text))
        _add_unique(reasons, text)
    else:
        text = "L’offre indique une condition d’éligibilité que le profil ne confirme pas encore."
        components.append(_component("eligibilite", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)

    target_companies = _company_preferences(profile.get("target_companies"))
    job_company = normalized_text(job.get("company"))
    matching_company = next((item for item in target_companies if item and (item in job_company or job_company in item)), "")
    if not target_companies:
        text = "Aucune entreprise préférée n’est déclarée."
        components.append(_component("entreprise", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)
    elif matching_company:
        text = "Cette entreprise figure dans les préférences déclarées."
        components.append(_component("entreprise", 10, status="match", reason=text))
        _add_unique(reasons, text)
    else:
        text = "Cette entreprise ne figure pas dans les préférences déclarées."
        components.append(_component("entreprise", 0, status="no_match", reason=text))

    required_languages = _language_names(job.get("languages_required"))
    declared_languages = _language_names(profile.get("languages"))
    if not required_languages:
        text = "La source ne précise pas les langues requises."
        components.append(_component("langues", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)
    elif required_languages.issubset(declared_languages):
        text = f"Le profil déclare les langues demandées : {', '.join(sorted(required_languages))}."
        components.append(_component("langues", 5, status="match", reason=text))
        _add_unique(reasons, text)
    else:
        missing = sorted(required_languages - declared_languages)
        text = f"L’offre demande {', '.join(missing)} ; le profil ne le confirme pas encore."
        components.append(_component("langues", 0, status="unknown", reason=text))
        _add_unique(unknowns, text)

    deadline = deadline_state(job.get("deadline_date"), clean_text(job.get("source_status"), limit=40) or "unknown")
    if deadline == "closed":
        _add_unique(blockers, "L’offre est indiquée fermée ou sa date limite connue est dépassée.")

    score = sum(component["points"] for component in components)
    if blockers:
        label = "Non recommandée automatiquement"
        state = "blocked"
    elif score >= 70:
        label = "Pertinence élevée"
        state = "scored"
    elif score >= 45:
        label = "Pertinence à examiner"
        state = "scored"
    else:
        label = "Pertinence limitée ou informations incomplètes"
        state = "scored"
    # An automatic recommendation remains conservative: known blockers or an
    # incomplete mandatory condition require the person to review the source.
    critical_unknown = any(
        component["key"] in {"disponibilite", "eligibilite", "langues"}
        and component["status"] == "unknown"
        for component in components
    )
    recommendable = not blockers and score >= 55 and not critical_unknown
    return {
        "state": state,
        "score": score,
        "maximum_score": sum(SCORING_WEIGHTS.values()),
        "label": label,
        "version": SCORING_VERSION,
        "weights": dict(SCORING_WEIGHTS),
        "components": components,
        "reasons": reasons[:8],
        "unknowns": unknowns[:8],
        "blocking_constraints": blockers[:6],
        "is_recommendable": recommendable,
        "automatic_recommendation": recommendable,
        "disclaimer": "Score de pertinence explicable fondé sur les données connues, pas une probabilité de recrutement.",
    }
