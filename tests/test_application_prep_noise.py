from career.application_prep import extract_requirements, prepare_application


def test_legal_footer_is_not_a_cv_requirement() -> None:
    job = {
        "requirements": "Ambitious third-year bachelor or master's students\n"
        "Strong analytical thinking, business acumen, and attention to detail\n"
        "All Rights Reserved.\n"
        "110 North Wacker Drive | 51st Floor | Chicago",
    }

    requirements = extract_requirements(job)
    texts = [item["text"] for item in requirements]

    assert any("bachelor" in text.casefold() for text in texts)
    assert not any("all rights reserved" in text.casefold() for text in texts)
    assert not any("north wacker" in text.casefold() for text in texts)


def test_generic_connectors_do_not_create_profile_improvement_suggestions() -> None:
    job = {
        "requirements": "Enthusiastic and motivated team player, with a clear interest in M&A",
    }
    profile = {"education": "Bachelor in Business Administration", "skills": "M&A and financial modelling"}

    result = prepare_application(profile, {}, job)
    suggestions = " ".join(item["suggestion"] for item in result["cv_improvements"])

    assert "« with »" not in suggestions
    assert "M&A" in suggestions or not result["cv_improvements"]


def test_education_evidence_is_not_mislabelled_as_a_skill() -> None:
    result = prepare_application(
        {"education": "Bachelor in Business Administration", "skills": "Financial modelling"},
        {},
        {"requirements": "Bachelor degree in business or finance"},
    )

    suggestions = " ".join(item["suggestion"] for item in result["cv_improvements"])
    assert "section compétences" not in suggestions.casefold()


def test_requirement_modality_is_inferred_without_claiming_unknown_facts() -> None:
    requirements = extract_requirements({"requirements": "Required: Excel\nPreferred: VBA\nLanguage level to verify"})
    by_text = {item["text"]: item.get("modality", "unknown") for item in requirements}
    assert by_text["Required: Excel"] == "required"
    assert by_text["Preferred: VBA"] == "preferred"
    assert by_text.get("Language level to verify", "unknown") == "unknown"


def test_negated_statements_do_not_become_cv_requirements() -> None:
    requirements = extract_requirements(
        {"description_original": "Profil :\n- Java n'est pas requis ; d'autres langages sont acceptés."}
    )

    assert requirements == []


def test_benefit_sections_and_meal_allowances_are_not_cv_requirements() -> None:
    requirements = extract_requirements(
        {
            "description_original": (
                "Avantages :\n- Mutuelle d'entreprise : prise en charge des repas.\n"
                "Profil :\n- Maîtrise d'Excel."
            ),
            "requirements": "Excel\nTicket restaurant Swile",
        }
    )
    texts = [item["text"] for item in requirements]

    assert any("Excel" in text for text in texts)
    assert not any("Mutuelle" in text or "repas" in text.casefold() for text in texts)
    assert not any("Ticket restaurant" in text for text in texts)


def test_spanish_profile_heading_is_recognized() -> None:
    requirements = extract_requirements(
        {"description_original": "Perfil:\n- Buen conocimiento de Excel."}
    )

    assert any("Buen conocimiento de Excel" in item["text"] for item in requirements)


def test_contact_only_structured_field_does_not_hide_description_requirements() -> None:
    requirements = extract_requirements(
        {
            "requirements": "Contact : jobs@example.test",
            "description_original": "Profil :\n- Maîtrise d'Excel.",
        }
    )

    assert any("Maîtrise d'Excel" in item["text"] for item in requirements)
    assert all("jobs@example.test" not in item["text"] for item in requirements)


def test_duplicate_requirement_with_punctuation_keeps_one_provenance_record() -> None:
    requirements = extract_requirements(
        {
            "requirements": "Maîtrise d'Excel",
            "description_original": "Profil :\nMaîtrise d'Excel.",
        }
    )

    assert len(requirements) == 1
    assert requirements[0]["source"] == "requirements"
