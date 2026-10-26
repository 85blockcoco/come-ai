"""Copyable quick answers for the repetitive fields of external offer forms.

Filling an ATS form means retyping the same local facts twenty times a day:
start date, work authorization, languages, school, internship duration,
mobility…  This module composes, from already stored facts only, a plain-text
answer pack that can be copied field by field.

Every answer traces the exact local field it comes from (``source_field``) and
carries a ``confidence``:

- ``exact``  : the value is the stored, user-declared fact itself;
- ``derived``: the value is composed from stored facts (template, range or
  transcribed field);
- ``missing``: no local fact answers the question, so no value is invented —
  ``value`` stays empty and the human completes the form field themselves.

The values are plain copyable text: no markdown, no markup, no model call.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from .models import clean_text
from workspace_core import UserFacingError


SUPPORTED_LANGS = ("fr", "en")

PROFILE_TEXT_LIMIT = 8_000

Confidence = Literal["exact", "derived", "missing"]


@dataclass(frozen=True)
class Answer:
    """One copyable form answer, traced back to its local source field."""

    label: str
    value: str
    source_field: str
    confidence: Literal["exact", "derived", "missing"]

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


_LABELS: dict[str, dict[str, str]] = {
    "availability_start": {"fr": "Date de début souhaitée", "en": "Desired start date"},
    "work_authorization": {"fr": "Autorisation de travail", "en": "Work authorization"},
    "languages": {"fr": "Langues et niveaux", "en": "Languages and levels"},
    "education": {"fr": "Formation / école en cours", "en": "Current degree / school"},
    "stage_duration": {"fr": "Durée de stage souhaitée", "en": "Desired internship duration"},
    "mobility": {"fr": "Mobilité / villes", "en": "Mobility / cities"},
    "current_situation": {"fr": "Situation actuelle", "en": "Current situation"},
    "motivation": {"fr": "Motivation courte", "en": "Short motivation statement"},
    "salary": {"fr": "Prétentions (salaire)", "en": "Salary expectations"},
}

# The work authorization answer is a direct transcription of the eligibility
# the person declared locally; "unknown" must never become a yes or a no.
_ELIGIBILITY_ANSWERS: dict[str, dict[str, str]] = {
    "compatible": {"fr": "Oui", "en": "Yes"},
    "incompatible": {"fr": "Non", "en": "No"},
}

# No salary preference exists in the local schema yet, so the answer stays
# "missing" until such a setting is stored under one of these keys.
_SALARY_SETTING_KEYS: tuple[str, ...] = (
    "salary_expectation",
    "salary_expectations",
    "pretentions",
    "remuneration_expectation",
)


def normalize_lang(lang: Any) -> str:
    normalized = str(lang or "fr").strip().lower()
    if normalized not in SUPPORTED_LANGS:
        raise UserFacingError("La langue des réponses types doit être fr ou en.")
    return normalized


def _label(key: str, lang: str) -> str:
    return _LABELS[key][lang]


def _answer(key: str, lang: str, value: str, source_field: str, confidence: Confidence) -> Answer:
    return Answer(label=_label(key, lang), value=value, source_field=source_field, confidence=confidence)


def _missing(key: str, lang: str, source_field: str) -> Answer:
    return _answer(key, lang, "", source_field, "missing")


def _profile_text(profile: dict[str, Any], field: str, limit: int = PROFILE_TEXT_LIMIT) -> str:
    return clean_text(profile.get(field), limit=limit)


def _availability_settings(preferences: dict[str, Any]) -> dict[str, Any]:
    availability = preferences.get("availability")
    return availability if isinstance(availability, dict) else {}


def _availability_start_answer(
    profile: dict[str, Any], preferences: dict[str, Any], lang: str,
) -> Answer:
    raw = _profile_text(profile, "availability_start", limit=32)
    source_field = "profile.availability_start"
    if not raw:
        raw = clean_text(_availability_settings(preferences).get("availability_start"), limit=32)
        source_field = "preferences.availability.availability_start"
    if not raw:
        return _missing("availability_start", lang, "preferences.availability.availability_start")
    return _answer("availability_start", lang, raw, source_field, "exact")


def _work_authorization_answer(profile: dict[str, Any], lang: str) -> Answer:
    eligibility = _profile_text(profile, "eligibility", limit=40)
    transcribed = _ELIGIBILITY_ANSWERS.get(eligibility)
    if not transcribed:
        return _missing("work_authorization", lang, "profile.eligibility")
    return _answer("work_authorization", lang, transcribed[lang], "profile.eligibility", "exact")


def _languages_answer(profile: dict[str, Any], lang: str) -> Answer:
    value = _profile_text(profile, "languages")
    if not value:
        return _missing("languages", lang, "profile.languages")
    return _answer("languages", lang, value, "profile.languages", "exact")


def _education_answer(profile: dict[str, Any], lang: str) -> Answer:
    value = _profile_text(profile, "education")
    if not value:
        return _missing("education", lang, "profile.education")
    return _answer("education", lang, value, "profile.education", "exact")


def _positive_months(value: Any) -> int | None:
    text = clean_text(value, limit=8)
    try:
        number = int(text)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _stage_duration_answer(preferences: dict[str, Any], lang: str) -> Answer:
    settings = _availability_settings(preferences)
    minimum = _positive_months(settings.get("minimum_duration_months"))
    maximum = _positive_months(settings.get("maximum_duration_months"))
    source_field = "preferences.availability.minimum_duration_months+maximum_duration_months"
    if minimum and maximum:
        if maximum < minimum:
            # Inconsistent stored settings: report the gap instead of guessing.
            return _missing("stage_duration", lang, source_field)
        if minimum == maximum:
            value = {"fr": f"{minimum} mois", "en": f"{minimum} month(s)"}[lang]
        else:
            value = {"fr": f"{minimum} à {maximum} mois", "en": f"{minimum} to {maximum} months"}[lang]
        return _answer("stage_duration", lang, value, source_field, "derived")
    if minimum:
        value = {"fr": f"À partir de {minimum} mois", "en": f"From {minimum} months"}[lang]
        return _answer("stage_duration", lang, value, source_field, "derived")
    if maximum:
        value = {"fr": f"Jusqu’à {maximum} mois", "en": f"Up to {maximum} months"}[lang]
        return _answer("stage_duration", lang, value, source_field, "derived")
    return _missing("stage_duration", lang, source_field)


def _mobility_answer(preferences: dict[str, Any], lang: str) -> Answer:
    locations = preferences.get("locations")
    labels: list[str] = []
    if isinstance(locations, list):
        for item in locations:
            if not isinstance(item, dict) or not item.get("enabled"):
                continue
            label = clean_text(item.get("label"), limit=160)
            if label:
                labels.append(label)
    if not labels:
        return _missing("mobility", lang, "preferences.locations")
    return _answer("mobility", lang, ", ".join(labels), "preferences.locations", "derived")


def _current_situation_answer(profile: dict[str, Any], lang: str) -> Answer:
    value = _profile_text(profile, "education")
    if not value:
        return _missing("current_situation", lang, "profile.education")
    # The tracker stores no dedicated "current situation" field, so the
    # in-progress education line is copied verbatim; the confidence stays
    # "derived" because the source field answers a slightly different question.
    return _answer("current_situation", lang, value, "profile.education", "derived")


def _motivation_answer(job: dict[str, Any], lang: str) -> Answer:
    title = clean_text(job.get("title"), limit=300)
    company = clean_text(job.get("company"), limit=240)
    source_field = "job.title+job.company"
    if not title or not company:
        return _missing("motivation", lang, source_field)
    if lang == "en":
        value = (
            f"I am applying for the {title} position at {company}. "
            "You will find the details of my background in my CV."
        )
    else:
        value = (
            f"Je vous adresse ma candidature pour le poste de {title} chez {company}. "
            "Vous trouverez le détail de mon parcours dans mon CV."
        )
    return _answer("motivation", lang, value, source_field, "derived")


def _salary_answer(preferences: dict[str, Any], lang: str) -> Answer:
    settings = _availability_settings(preferences)
    for scope, source in (("availability", settings), ("top", preferences)):
        if not isinstance(source, dict):
            continue
        for key in _SALARY_SETTING_KEYS:
            value = clean_text(source.get(key), limit=200)
            if value:
                field = key if scope == "top" else f"availability.{key}"
                return _answer("salary", lang, value, f"preferences.{field}", "exact")
    return _missing("salary", lang, "preferences.availability.salary_expectation")


def build_answer_pack(
    profile: dict[str, Any] | None,
    job: dict[str, Any] | None,
    preferences: dict[str, Any] | None,
    lang: str = "fr",
) -> list[Answer]:
    """Build the ordered, copyable answer pack for one offer's form.

    The pack never invents a value: when no local fact answers a question the
    answer is returned with ``confidence="missing"`` and an empty value, for
    the human to complete.  With ``lang="en"`` the questions are asked in
    English and template answers are written in English; profile values are
    copied from the stored EN fields when they exist, otherwise the stored
    text is kept as is.
    """
    normalized = normalize_lang(lang)
    safe_profile = profile if isinstance(profile, dict) else {}
    safe_job = job if isinstance(job, dict) else {}
    safe_preferences = preferences if isinstance(preferences, dict) else {}
    return [
        _availability_start_answer(safe_profile, safe_preferences, normalized),
        _work_authorization_answer(safe_profile, normalized),
        _languages_answer(safe_profile, normalized),
        _education_answer(safe_profile, normalized),
        _stage_duration_answer(safe_preferences, normalized),
        _mobility_answer(safe_preferences, normalized),
        _current_situation_answer(safe_profile, normalized),
        _motivation_answer(safe_job, normalized),
        _salary_answer(safe_preferences, normalized),
    ]
