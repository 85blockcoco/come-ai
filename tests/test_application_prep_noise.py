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
    by_text = {item["text"]: item["modality"] for item in requirements}
    assert by_text["Required: Excel"] == "required"
    assert by_text["Preferred: VBA"] == "preferred"
    assert by_text["Language level to verify"] == "unknown"
