"""CVBOOST-82 / SPEC-045 — réponses types copiables pour formulaires d'offre.

Règle centrale testée partout : aucune valeur n'est jamais inventée.  Une
information absente donne ``confidence="missing"`` et une valeur vide, à
compléter par la personne.  Tous les jeux de données sont synthétiques ; rien
n'est soumis, aucun réseau n'est appelé et aucune donnée réelle n'est lue.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from career.models import JOB_FAMILIES, PRIMARY_LOCATIONS
from career.quick_answers import Answer, build_answer_pack
from career.service import CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError


FULL_PROFILE = {
    "display_name": "Côme Synthétique",
    "contact_email": "come.synthetic@example.test",
    "education": "Master Finance d'entreprise — École Synthétique",
    "experience": "Stage M&A de 6 mois chez Banque Exemple",
    "skills": "Modélisation financière, Excel",
    "languages": "Français C2, Anglais C1, Espagnol B2",
    "eligibility": "compatible",
}


def full_preferences() -> dict[str, object]:
    return {
        "availability": {
            "availability_start": "2027-01-15",
            "availability_end": "2027-06-30",
            "minimum_duration_months": "4",
            "maximum_duration_months": "6",
        },
        "families": [
            {
                "key": CareerService._preference_key(label),
                "label": label,
                "enabled": label == "M&A / Investment Banking",
                "priority": 100,
                "scope": "primary",
            }
            for label in JOB_FAMILIES
        ],
        "locations": [
            {
                "key": key,
                "label": label,
                "enabled": key in {"london", "paris"},
                "priority": 100,
                "scope": scope,
            }
            for key, label, scope in PRIMARY_LOCATIONS
        ],
    }


FULL_JOB = {
    "id": "job-synthetic-quick-answers",
    "title": "Stagiaire M&A",
    "company": "Banque Synthétique",
    "job_family": "M&A / Investment Banking",
    "city": "Londres",
}


def answer_by_question(answers: list[Answer], label: str) -> Answer:
    return next(answer for answer in answers if answer.label == label)


def synthetic_job_payload() -> dict[str, object]:
    return {
        "company": "Banque Synthétique",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/quick-answers-1",
        "job_family": "M&A / Investment Banking",
        "city": "Londres",
        "country": "United Kingdom",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
    }


# ---------------------------------------------------------------------------
# Pack pur (builder)


def test_full_inputs_produce_exact_copiable_values():
    answers = build_answer_pack(FULL_PROFILE, FULL_JOB, full_preferences(), lang="fr")

    availability = answer_by_question(answers, "Date de début souhaitée")
    assert availability.value == "2027-01-15"
    assert availability.confidence == "exact"
    assert availability.source_field == "preferences.availability.availability_start"

    languages = answer_by_question(answers, "Langues")
    assert languages.value == "Français C2, Anglais C1, Espagnol B2"
    assert languages.confidence == "exact"
    assert languages.source_field == "profile.languages"

    education = answer_by_question(answers, "Formation / diplôme en cours")
    assert education.value == "Master Finance d'entreprise — École Synthétique"
    assert education.confidence == "exact"
    assert education.source_field == "profile.education"

    current_status = answer_by_question(answers, "Situation actuelle")
    assert current_status.value == FULL_PROFILE["education"]
    assert current_status.source_field == "profile.education"
    assert current_status.confidence == "exact"


def test_nine_questions_are_covered_in_a_stable_order():
    answers = build_answer_pack(FULL_PROFILE, FULL_JOB, full_preferences(), lang="fr")
    labels = [answer.label for answer in answers]
    assert labels == [
        "Date de début souhaitée",
        "Autorisation de travail",
        "Langues",
        "Formation / diplôme en cours",
        "Durée de stage souhaitée",
        "Mobilité / villes",
        "Situation actuelle",
        "Motivation courte",
        "Prétentions",
    ]


def test_work_authorization_restores_the_declared_eligibility_only():
    compatible = build_answer_pack(
        {**FULL_PROFILE, "eligibility": "compatible"}, FULL_JOB, full_preferences()
    )
    assert answer_by_question(compatible, "Autorisation de travail").value == "Oui"
    assert answer_by_question(compatible, "Autorisation de travail").confidence == "derived"

    incompatible = build_answer_pack(
        {**FULL_PROFILE, "eligibility": "incompatible"}, FULL_JOB, full_preferences(), lang="en"
    )
    assert answer_by_question(incompatible, "Work authorization").value == "No"

    unknown = build_answer_pack(
        {**FULL_PROFILE, "eligibility": "unknown"}, FULL_JOB, full_preferences()
    )
    work = answer_by_question(unknown, "Autorisation de travail")
    assert work.confidence == "missing"
    assert work.value == ""
    assert work.source_field == "profile.eligibility"


def test_missing_inputs_never_invent_any_value():
    answers = build_answer_pack({}, {}, {}, lang="fr")
    assert answers
    for answer in answers:
        assert answer.confidence == "missing"
        assert answer.value == ""
        assert answer.label  # la question reste posée, à compléter par l'humain
        assert answer.source_field


def test_lang_en_localizes_labels_without_translating_values():
    answers = build_answer_pack(FULL_PROFILE, FULL_JOB, full_preferences(), lang="en")
    labels = {answer.label for answer in answers}
    assert {
        "Earliest start date",
        "Work authorization",
        "Languages",
        "Current degree / school",
        "Preferred internship duration",
        "Mobility / locations",
        "Current situation",
        "Short motivation statement",
        "Compensation expectations",
    } <= labels
    # La valeur stockée n'est jamais traduite : une réponse copiée reste le
    # fait tel qu'il a été enregistré.
    assert answer_by_question(answers, "Languages").value == "Français C2, Anglais C1, Espagnol B2"
    assert answer_by_question(answers, "Languages").source_field == "profile.languages"


def test_lang_en_uses_english_profile_fields_when_available():
    profile = {
        **FULL_PROFILE,
        "languages_en": "French C2, English C1",
        "education_en": "MSc in Corporate Finance — Synthetic Business School",
    }
    answers = build_answer_pack(profile, FULL_JOB, full_preferences(), lang="en")
    assert answer_by_question(answers, "Languages").value == "French C2, English C1"
    assert answer_by_question(answers, "Current degree / school").value == (
        "MSc in Corporate Finance — Synthetic Business School"
    )
    # Le français reste la valeur de repli quand le champ EN est absent ou vide.
    answers_fr_fallback = build_answer_pack(
        {**profile, "languages_en": ""}, FULL_JOB, full_preferences(), lang="en"
    )
    assert answer_by_question(answers_fr_fallback, "Languages").value == (
        "Français C2, Anglais C1, Espagnol B2"
    )


@pytest.mark.parametrize(
    "availability, expected_fr, expected_en",
    [
        (
            {"minimum_duration_months": "4", "maximum_duration_months": "6"},
            "4 à 6 mois",
            "4 to 6 months",
        ),
        (
            {"minimum_duration_months": "5", "maximum_duration_months": "5"},
            "5 mois",
            "5 months",
        ),
        ({"minimum_duration_months": "4"}, "À partir de 4 mois", "At least 4 months"),
        ({"maximum_duration_months": "6"}, "Jusqu'à 6 mois", "Up to 6 months"),
    ],
)
def test_duration_is_derived_from_the_configured_range(availability, expected_fr, expected_en):
    preferences = {"availability": availability}
    duration_fr = answer_by_question(
        build_answer_pack({}, {}, preferences, lang="fr"), "Durée de stage souhaitée"
    )
    assert duration_fr.value == expected_fr
    assert duration_fr.confidence == "derived"
    assert duration_fr.source_field == (
        "preferences.availability.minimum_duration_months,maximum_duration_months"
    )
    duration_en = answer_by_question(
        build_answer_pack({}, {}, preferences, lang="en"), "Preferred internship duration"
    )
    assert duration_en.value == expected_en


def test_duration_with_no_range_stays_missing():
    duration = answer_by_question(build_answer_pack({}, {}, {}, lang="fr"), "Durée de stage souhaitée")
    assert duration.confidence == "missing"
    assert duration.value == ""


def test_invalid_duration_values_are_never_guessed():
    preferences = {"availability": {"minimum_duration_months": "beaucoup", "maximum_duration_months": ""}}
    duration = answer_by_question(build_answer_pack({}, {}, preferences, lang="fr"), "Durée de stage souhaitée")
    assert duration.confidence == "missing"
    assert duration.value == ""


def test_mobility_lists_only_enabled_locations():
    mobility = answer_by_question(
        build_answer_pack({}, {}, full_preferences(), lang="fr"), "Mobilité / villes"
    )
    # Le builder restitue l'ordre reçu, sans le réinventer ; via le service,
    # les libellés arrivent triés par SQL (priority DESC, label).
    assert mobility.value == "Paris, Londres"
    assert mobility.confidence == "derived"
    assert mobility.source_field == "preferences.locations"

    disabled = full_preferences()
    for item in disabled["locations"]:  # type: ignore[index]
        item["enabled"] = False
    mobility_missing = answer_by_question(
        build_answer_pack({}, {}, disabled, lang="fr"), "Mobilité / villes"
    )
    assert mobility_missing.confidence == "missing"
    assert mobility_missing.value == ""


def test_motivation_is_exactly_two_plain_sentences_derived_from_the_offer():
    motivation = answer_by_question(
        build_answer_pack(FULL_PROFILE, FULL_JOB, full_preferences(), lang="fr"), "Motivation courte"
    )
    assert motivation.confidence == "derived"
    assert motivation.source_field == "job.title,job.company,job.job_family"
    sentences = [sentence for sentence in motivation.value.split(". ") if sentence]
    assert len(sentences) == 2
    assert motivation.value.endswith(".")
    assert "Stagiaire M&A" in motivation.value
    assert "Banque Synthétique" in motivation.value
    assert "M&A / Investment Banking" in motivation.value


def test_motivation_without_job_family_uses_a_generic_second_sentence():
    motivation = answer_by_question(
        build_answer_pack({}, {**FULL_JOB, "job_family": "À préciser"}, {}, lang="fr"), "Motivation courte"
    )
    assert motivation.source_field == "job.title,job.company"
    assert "À préciser" not in motivation.value
    assert motivation.value.endswith("votre équipe.")


def test_motivation_with_unnamed_offer_is_missing_not_invented():
    motivation = answer_by_question(build_answer_pack({}, {"company": "Banque Synthétique"}, {}), "Motivation courte")
    assert motivation.confidence == "missing"
    assert motivation.value == ""


def test_salary_stays_missing_until_a_preference_exists():
    missing = answer_by_question(
        build_answer_pack(FULL_PROFILE, FULL_JOB, full_preferences(), lang="fr"), "Prétentions"
    )
    assert missing.confidence == "missing"
    assert missing.value == ""
    assert missing.source_field == "preferences.availability.salary_expectation"

    stated = full_preferences()
    stated["availability"] = {**stated["availability"], "salary_expectation": "1 200 € / mois"}  # type: ignore[index]
    exact = answer_by_question(
        build_answer_pack(FULL_PROFILE, FULL_JOB, stated, lang="fr"), "Prétentions"
    )
    assert exact.confidence == "exact"
    assert exact.value == "1 200 € / mois"
    assert exact.source_field == "preferences.availability.salary_expectation"


def test_every_value_is_plain_text_without_markdown():
    answers = build_answer_pack(FULL_PROFILE, FULL_JOB, full_preferences(), lang="fr")
    assert answers
    for answer in answers:
        for forbidden in ("**", "#", "`", "](http", "- ["):
            assert forbidden not in answer.value
        assert answer.value == answer.value.strip()


def test_builder_is_deterministic_and_accepts_none():
    first = build_answer_pack(None, None, None, lang="fr")
    second = build_answer_pack(None, None, None, lang="fr")
    assert first == second
    assert all(answer.confidence == "missing" for answer in first)


def test_unknown_lang_falls_back_to_french_labels():
    answers = build_answer_pack({}, {}, {}, lang="es")
    assert answers[0].label == "Date de début souhaitée"


# ---------------------------------------------------------------------------
# Service + endpoint


@pytest.fixture()
def service_with_job(tmp_path):
    service = CareerService(tmp_path)
    service.update_profile({**FULL_PROFILE, "eligibility": "compatible", "target_companies": "", "notes": ""})
    service.update_preferences(full_preferences())
    job = service.import_job(synthetic_job_payload())
    return service, str(job["id"])


def test_service_builds_the_pack_from_stored_local_data(service_with_job):
    service, job_id = service_with_job
    payload = service.get_quick_answers(job_id)
    assert payload["job_id"] == job_id
    assert payload["lang"] == "fr"
    answers = payload["answers"]
    assert len(answers) == 9
    by_label = {answer["label"]: answer for answer in answers}
    assert by_label["Date de début souhaitée"] == {
        "label": "Date de début souhaitée",
        "value": "2027-01-15",
        "source_field": "preferences.availability.availability_start",
        "confidence": "exact",
    }
    assert by_label["Autorisation de travail"]["value"] == "Oui"
    assert by_label["Durée de stage souhaitée"]["value"] == "4 à 6 mois"
    assert by_label["Mobilité / villes"]["value"] == "Londres, Paris"
    assert by_label["Prétentions"]["confidence"] == "missing"
    assert by_label["Prétentions"]["value"] == ""


def test_service_unknown_job_raises(service_with_job):
    service, _ = service_with_job
    with pytest.raises(UserFacingError):
        service.get_quick_answers("job-inconnu")


def test_service_lang_en_returns_english_questions(service_with_job):
    service, job_id = service_with_job
    payload = service.get_quick_answers(job_id, lang="en")
    assert payload["lang"] == "en"
    by_label = {answer["label"]: answer for answer in payload["answers"]}
    assert "Earliest start date" in by_label
    assert by_label["Earliest start date"]["value"] == "2027-01-15"
    with pytest.raises(UserFacingError):
        service.get_quick_answers(job_id, lang="de")


def test_endpoint_serves_quick_answers(service_with_job, tmp_path):
    service, job_id = service_with_job
    client = TestClient(create_app(tmp_path, agent_override=object(), career_override=service))
    response = client.get(f"/api/career/quick-answers/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert len(body["answers"]) == 9
    english = client.get(f"/api/career/quick-answers/{job_id}", params={"lang": "en"})
    assert english.status_code == 200
    assert any(answer["label"] == "Work authorization" for answer in english.json()["answers"])
    unknown = client.get("/api/career/quick-answers/job-inconnu")
    assert unknown.status_code == 400
    bad_lang = client.get(f"/api/career/quick-answers/{job_id}", params={"lang": "de"})
    assert bad_lang.status_code == 422
