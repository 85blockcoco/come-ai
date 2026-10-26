"""Quick answers for offer forms: traced, copyable, never invented.

Synthetic fixtures only: every value below is fictional and the pack must
stay able to answer "missing" instead of guessing a value.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from career.quick_answers import Answer, build_answer_pack, normalize_lang
from career.service import CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError


COMPLETE_PROFILE = {
    "display_name": "Côme Fictif",
    "contact_email": "come@example.test",
    "contact_phone": "+33 6 00 00 00 00",
    "education": "Master Finance d’entreprise — ESAF fictive (M1)",
    "experience": "Stage analytique fictif de 6 mois chez Exemple SARL.",
    "skills": "Excel, SQL, modélisation",
    "languages": "Anglais C1, Espagnol B2",
    "eligibility": "compatible",
}

COMPLETE_JOB = {
    "company": "Banque Fictive",
    "title": "Stagiaire Corporate Finance",
    "city": "Londres",
}

COMPLETE_PREFERENCES = {
    "availability": {
        "availability_start": "2027-01-01",
        "availability_end": "2027-06-30",
        "minimum_duration_months": "3",
        "maximum_duration_months": "6",
    },
    "locations": [
        {"key": "london", "label": "Londres", "enabled": True, "priority": 100, "scope": "primary"},
        {"key": "amsterdam", "label": "Amsterdam", "enabled": True, "priority": 90, "scope": "primary"},
        {"key": "paris", "label": "Paris", "enabled": False, "priority": 80, "scope": "primary"},
    ],
}


def _by_label(answers: list[Answer], label: str) -> Answer:
    return next(answer for answer in answers if answer.label == label)


def test_complete_profile_answers_are_exact_or_derived() -> None:
    answers = build_answer_pack(COMPLETE_PROFILE, COMPLETE_JOB, COMPLETE_PREFERENCES)

    by_label = {answer.label: answer for answer in answers}
    assert len(answers) == 9

    start = by_label["Date de début souhaitée"]
    assert (start.value, start.confidence) == ("2027-01-01", "exact")
    assert start.source_field == "preferences.availability.availability_start"

    authorization = by_label["Autorisation de travail"]
    assert (authorization.value, authorization.confidence) == ("Oui", "exact")
    assert authorization.source_field == "profile.eligibility"

    languages = by_label["Langues et niveaux"]
    assert languages.value == "Anglais C1, Espagnol B2"
    assert (languages.confidence, languages.source_field) == ("exact", "profile.languages")

    education = by_label["Formation / école en cours"]
    assert education.value == COMPLETE_PROFILE["education"]
    assert (education.confidence, education.source_field) == ("exact", "profile.education")

    duration = by_label["Durée de stage souhaitée"]
    assert duration.value == "3 à 6 mois"
    assert duration.confidence == "derived"
    assert "minimum_duration_months" in duration.source_field

    mobility = by_label["Mobilité / villes"]
    assert mobility.value == "Londres, Amsterdam"
    assert mobility.confidence == "derived"
    assert mobility.source_field == "preferences.locations"

    situation = by_label["Situation actuelle"]
    assert situation.value == COMPLETE_PROFILE["education"]
    assert (situation.confidence, situation.source_field) == ("derived", "profile.education")

    motivation = by_label["Motivation courte"]
    assert "Stagiaire Corporate Finance" in motivation.value
    assert "Banque Fictive" in motivation.value
    assert motivation.source_field == "job.title+job.company"
    assert motivation.value.count(".") == 2, "la motivation courte est un template de 2 phrases"


def test_every_value_is_plain_copyable_text() -> None:
    answers = build_answer_pack(COMPLETE_PROFILE, COMPLETE_JOB, COMPLETE_PREFERENCES)
    for answer in answers:
        assert isinstance(answer, Answer)
        assert "**" not in answer.value
        assert not answer.value.startswith(("#", "-", "*"))
        assert answer.value == answer.value.strip()


def test_incomplete_profile_never_invents_a_value() -> None:
    answers = build_answer_pack({}, {}, {})
    assert len(answers) == 9
    for answer in answers:
        assert answer.value == ""
        assert answer.confidence == "missing"
        assert answer.source_field, "chaque réponse manquante reste tracée vers son champ source"


def test_unknown_eligibility_stays_missing() -> None:
    answers = build_answer_pack(
        {**COMPLETE_PROFILE, "eligibility": "unknown"}, COMPLETE_JOB, COMPLETE_PREFERENCES,
    )
    authorization = _by_label(answers, "Autorisation de travail")
    assert (authorization.value, authorization.confidence) == ("", "missing")


def test_availability_start_traces_the_profile_field_first() -> None:
    answers = build_answer_pack(
        {**COMPLETE_PROFILE, "availability_start": "2027-02-15"},
        COMPLETE_JOB,
        COMPLETE_PREFERENCES,
    )
    start = _by_label(answers, "Date de début souhaitée")
    assert (start.value, start.confidence) == ("2027-02-15", "exact")
    assert start.source_field == "profile.availability_start"


def test_duration_range_stays_missing_when_settings_are_inconsistent() -> None:
    preferences = {
        "availability": {
            "minimum_duration_months": "6",
            "maximum_duration_months": "3",
        }
    }
    answers = build_answer_pack(COMPLETE_PROFILE, COMPLETE_JOB, preferences)
    duration = _by_label(answers, "Durée de stage souhaitée")
    assert (duration.value, duration.confidence) == ("", "missing")


def test_duration_accepts_a_single_bound_without_inventing_the_other() -> None:
    minimum_only = build_answer_pack(
        {}, {}, {"availability": {"minimum_duration_months": "3"}},
    )
    assert _by_label(minimum_only, "Durée de stage souhaitée").value == "À partir de 3 mois"
    maximum_only = build_answer_pack(
        {}, {}, {"availability": {"maximum_duration_months": "6"}},
    )
    assert _by_label(maximum_only, "Durée de stage souhaitée").value == "Jusqu’à 6 mois"
    invalid = build_answer_pack({}, {}, {"availability": {"minimum_duration_months": "trois"}})
    assert _by_label(invalid, "Durée de stage souhaitée").confidence == "missing"


def test_salary_answers_only_from_stored_preferences() -> None:
    missing = build_answer_pack(COMPLETE_PROFILE, COMPLETE_JOB, COMPLETE_PREFERENCES)
    salary = _by_label(missing, "Prétentions (salaire)")
    assert (salary.value, salary.confidence) == ("", "missing")

    declared = {
        **COMPLETE_PREFERENCES,
        "availability": {**COMPLETE_PREFERENCES["availability"], "salary_expectation": "1 200 €/mois"},
    }
    answers = build_answer_pack(COMPLETE_PROFILE, COMPLETE_JOB, declared)
    salary = _by_label(answers, "Prétentions (salaire)")
    assert (salary.value, salary.confidence) == ("1 200 €/mois", "exact")
    assert salary.source_field == "preferences.availability.salary_expectation"


def test_english_labels_and_templates() -> None:
    answers = build_answer_pack(COMPLETE_PROFILE, COMPLETE_JOB, COMPLETE_PREFERENCES, lang="en")
    by_label = {answer.label: answer for answer in answers}
    assert set(by_label) == {
        "Desired start date",
        "Work authorization",
        "Languages and levels",
        "Current degree / school",
        "Desired internship duration",
        "Mobility / cities",
        "Current situation",
        "Short motivation statement",
        "Salary expectations",
    }
    assert by_label["Work authorization"].value == "Yes"
    assert by_label["Desired internship duration"].value == "3 to 6 months"
    motivation = by_label["Short motivation statement"]
    assert motivation.value.startswith("I am applying for the Stagiaire Corporate Finance position at Banque Fictive.")
    # Stored profile text has no EN field yet: the stored value is kept as is.
    assert by_label["Languages and levels"].value == "Anglais C1, Espagnol B2"


def test_unsupported_language_is_rejected() -> None:
    with pytest.raises(UserFacingError):
        normalize_lang("de")
    with pytest.raises(UserFacingError):
        build_answer_pack(COMPLETE_PROFILE, COMPLETE_JOB, COMPLETE_PREFERENCES, lang="de")


def test_quick_answers_endpoint_serves_copyable_answers(tmp_path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(
        {
            "company": COMPLETE_JOB["company"],
            "title": COMPLETE_JOB["title"],
            "city": COMPLETE_JOB["city"],
        }
    )
    service.update_profile(COMPLETE_PROFILE)
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.get(f"/api/career/quick-answers/{job['id']}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["job_id"] == job["id"]
        assert payload["lang"] == "fr"
        assert payload["automatic_submission"] is False
        labels = [answer["label"] for answer in payload["answers"]]
        assert "Date de début souhaitée" in labels
        assert "Autorisation de travail" in labels
        for answer in payload["answers"]:
            assert set(answer) == {"label", "value", "source_field", "confidence"}

        english = client.get(f"/api/career/quick-answers/{job['id']}", params={"lang": "en"})
        assert english.status_code == 200
        assert english.json()["lang"] == "en"
        assert any(answer["label"] == "Work authorization" for answer in english.json()["answers"])


def test_quick_answers_endpoint_rejects_unknown_job_and_lang(tmp_path) -> None:
    service = CareerService(tmp_path)
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        missing_job = client.get("/api/career/quick-answers/job_inconnu")
        assert missing_job.status_code == 400
        missing_lang = client.get(
            "/api/career/quick-answers/job_inconnu", params={"lang": "de"},
        )
        assert missing_lang.status_code == 400
