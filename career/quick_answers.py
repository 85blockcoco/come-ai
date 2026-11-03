"""SPEC-045 — Réponses types copiables pour les formulaires d'offre.

Le pack de réponses est calculé depuis les seules données déjà stockées
localement (profil, préférences, offre).  Aucune valeur n'est jamais inventée :
quand l'information est absente, la réponse porte ``confidence="missing"`` et
une valeur vide, à compléter par la personne.  Les valeurs sont du texte brut
copiable, sans markdown, et restent exactement le fait tel qu'il a été
enregistré (jamais traduit, jamais reformulé).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

SUPPORTED_LANGS: tuple[str, ...] = ("fr", "en")

Confidence = Literal["exact", "derived", "missing"]


@dataclass(frozen=True)
class Answer:
    label: str
    value: str
    source_field: str
    confidence: Confidence

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# Libellés de questions, localisés.  Les valeurs stockées ne sont jamais
# traduites : une réponse recopiée dans un formulaire reste le fait tel que la
# personne l'a enregistré.
_LABELS: dict[str, dict[str, str]] = {
    "availability_start": {
        "fr": "Date de début souhaitée",
        "en": "Earliest start date",
    },
    "work_authorization": {
        "fr": "Autorisation de travail",
        "en": "Work authorization",
    },
    "languages": {
        "fr": "Langues",
        "en": "Languages",
    },
    "education": {
        "fr": "Formation / diplôme en cours",
        "en": "Current degree / school",
    },
    "internship_duration": {
        "fr": "Durée de stage souhaitée",
        "en": "Preferred internship duration",
    },
    "mobility": {
        "fr": "Mobilité / villes",
        "en": "Mobility / locations",
    },
    "current_status": {
        "fr": "Situation actuelle",
        "en": "Current situation",
    },
    "motivation": {
        "fr": "Motivation courte",
        "en": "Short motivation statement",
    },
    "salary_expectations": {
        "fr": "Prétentions",
        "en": "Compensation expectations",
    },
}

# Clés facultatives consultées dans les réglages de disponibilité pour les
# prétentions.  Le schéma local n'en stocke aucune aujourd'hui : la réponse
# reste « missing » tant qu'une telle préférence n'existe pas.
_SALARY_SETTING_KEYS: tuple[str, ...] = ("salary_expectation", "compensation_expectation")

_GENERIC_FAMILY = "À préciser"
_PLAIN_LIMIT = 2_000


def _plain(value: Any, *, limit: int = _PLAIN_LIMIT) -> str:
    """Texte brut copiable : sans fioriture, jamais de markdown généré."""
    return str(value or "").strip()[:limit]


def _answer(
    question: str,
    lang: str,
    *,
    value: str,
    source_field: str,
    confidence: Confidence,
) -> Answer:
    labels = _LABELS[question]
    return Answer(
        label=labels.get(lang) or labels["fr"],
        value=value,
        source_field=source_field,
        confidence=confidence,
    )


def _profile_field(profile: dict[str, Any], field: str, lang: str) -> str:
    """Champ de profil, en version EN si un champ ``*_en`` existe et est rempli.

    Le schéma local ne stocke pas de champs EN aujourd'hui : la valeur FR fait
    alors office, sans traduction improvisée.
    """
    if lang == "en":
        english = _plain(profile.get(f"{field}_en"))
        if english:
            return english
    return _plain(profile.get(field))


def _int_setting(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _availability_answer(preferences: dict[str, Any], lang: str) -> Answer:
    availability = preferences.get("availability") or {}
    value = _plain(availability.get("availability_start"), limit=32)
    if not value:
        return _answer(
            "availability_start", lang,
            value="", source_field="preferences.availability.availability_start",
            confidence="missing",
        )
    return _answer(
        "availability_start", lang,
        value=value, source_field="preferences.availability.availability_start",
        confidence="exact",
    )


def _work_authorization_answer(profile: dict[str, Any], lang: str) -> Answer:
    # L'éligibilité est déclarée par la personne (« selon mes informations »).
    # La réponse restitue cette déclaration, sans la déduire d'aucun autre fait.
    source_field = "profile.eligibility"
    eligibility = _plain(profile.get("eligibility")).lower()
    mapping = {
        "compatible": {"fr": "Oui", "en": "Yes"},
        "incompatible": {"fr": "Non", "en": "No"},
    }
    if eligibility not in mapping:
        return _answer("work_authorization", lang, value="", source_field=source_field, confidence="missing")
    return _answer(
        "work_authorization", lang,
        value=mapping[eligibility].get(lang) or mapping[eligibility]["fr"],
        source_field=source_field,
        confidence="derived",
    )


def _languages_answer(profile: dict[str, Any], lang: str) -> Answer:
    value = _profile_field(profile, "languages", lang)
    if not value:
        return _answer("languages", lang, value="", source_field="profile.languages", confidence="missing")
    return _answer(
        "languages", lang,
        value=value, source_field="profile.languages", confidence="exact",
    )


def _education_answer(profile: dict[str, Any], lang: str) -> Answer:
    value = _profile_field(profile, "education", lang)
    if not value:
        return _answer("education", lang, value="", source_field="profile.education", confidence="missing")
    return _answer(
        "education", lang,
        value=value, source_field="profile.education", confidence="exact",
    )


def _duration_answer(preferences: dict[str, Any], lang: str) -> Answer:
    availability = preferences.get("availability") or {}
    minimum = _int_setting(availability.get("minimum_duration_months"))
    maximum = _int_setting(availability.get("maximum_duration_months"))
    if minimum is None and maximum is None:
        return _answer(
            "internship_duration", lang,
            value="",
            source_field="preferences.availability.minimum_duration_months,maximum_duration_months",
            confidence="missing",
        )
    if minimum is not None and maximum is not None:
        if minimum == maximum:
            value = f"{minimum} mois" if lang == "fr" else f"{minimum} months"
        else:
            value = f"{minimum} à {maximum} mois" if lang == "fr" else f"{minimum} to {maximum} months"
    elif minimum is not None:
        value = f"À partir de {minimum} mois" if lang == "fr" else f"At least {minimum} months"
    else:
        value = f"Jusqu'à {maximum} mois" if lang == "fr" else f"Up to {maximum} months"
    return _answer(
        "internship_duration", lang,
        value=value,
        source_field="preferences.availability.minimum_duration_months,maximum_duration_months",
        confidence="derived",
    )


def _mobility_answer(preferences: dict[str, Any], lang: str) -> Answer:
    locations = preferences.get("locations") or []
    labels = [
        _plain(item.get("label"), limit=160)
        for item in locations
        if isinstance(item, dict) and item.get("enabled") and _plain(item.get("label"), limit=160)
    ]
    if not labels:
        return _answer("mobility", lang, value="", source_field="preferences.locations", confidence="missing")
    return _answer(
        "mobility", lang,
        value=", ".join(labels), source_field="preferences.locations", confidence="derived",
    )


def _current_status_answer(profile: dict[str, Any], lang: str) -> Answer:
    # Un copier direct du champ formation ; à défaut, du champ expérience.
    # Aucune phrase n'est fabriquée autour de la valeur.
    for field in ("education", "experience"):
        value = _profile_field(profile, field, lang)
        if value:
            return _answer(
                "current_status", lang,
                value=value, source_field=f"profile.{field}", confidence="exact",
            )
    return _answer("current_status", lang, value="", source_field="profile.education", confidence="missing")


def _motivation_answer(job: dict[str, Any], lang: str) -> Answer:
    title = _plain(job.get("title"), limit=300)
    company = _plain(job.get("company"), limit=240)
    family = _plain(job.get("job_family"), limit=160)
    if not title or not company:
        return _answer(
            "motivation", lang, value="", source_field="job.title,job.company", confidence="missing",
        )
    source_field = "job.title,job.company"
    if lang == "en":
        first = f"Motivation for the “{title}” position at {company}: [complete with your personal reason]."
        if family and family != _GENERIC_FAMILY:
            second = f"Approved profile fact to connect to “{family}”: [complete and verify before use]."
            source_field += ",job.job_family"
        else:
            second = "Approved profile fact that supports this motivation: [complete and verify before use]."
    else:
        first = f"Motivation pour le poste « {title} » chez {company} : [à compléter avec ta raison personnelle]."
        if family and family != _GENERIC_FAMILY:
            second = f"Fait approuvé du profil à relier à « {family} » : [à compléter et vérifier avant usage]."
            source_field += ",job.job_family"
        else:
            second = "Fait approuvé du profil qui étaye cette motivation : [à compléter et vérifier avant usage]."
    return _answer(
        "motivation", lang,
        value=f"{first} {second}", source_field=source_field, confidence="derived",
    )


def _salary_answer(preferences: dict[str, Any], lang: str) -> Answer:
    availability = preferences.get("availability") or {}
    for key in _SALARY_SETTING_KEYS:
        value = _plain(availability.get(key))
        if value:
            return _answer(
                "salary_expectations", lang,
                value=value, source_field=f"preferences.availability.{key}", confidence="exact",
            )
    return _answer(
        "salary_expectations", lang,
        value="", source_field=f"preferences.availability.{_SALARY_SETTING_KEYS[0]}", confidence="missing",
    )


def build_answer_pack(
    profile: dict[str, Any] | None,
    job: dict[str, Any] | None,
    preferences: dict[str, Any] | None,
    lang: str = "fr",
) -> list[Answer]:
    """Construis le pack de réponses types depuis les données stockées.

    Chaque réponse trace le champ local d'où elle vient.  Aucune valeur n'est
    inventée : une information absente donne ``confidence="missing"`` et une
    valeur vide, à compléter par la personne.
    """
    normalized_lang = str(lang or "fr").strip().lower() or "fr"
    if normalized_lang not in SUPPORTED_LANGS:
        normalized_lang = "fr"
    safe_profile = profile if isinstance(profile, dict) else {}
    safe_job = job if isinstance(job, dict) else {}
    safe_preferences = preferences if isinstance(preferences, dict) else {}
    return [
        _availability_answer(safe_preferences, normalized_lang),
        _work_authorization_answer(safe_profile, normalized_lang),
        _languages_answer(safe_profile, normalized_lang),
        _education_answer(safe_profile, normalized_lang),
        _duration_answer(safe_preferences, normalized_lang),
        _mobility_answer(safe_preferences, normalized_lang),
        _current_status_answer(safe_profile, normalized_lang),
        _motivation_answer(safe_job, normalized_lang),
        _salary_answer(safe_preferences, normalized_lang),
    ]
