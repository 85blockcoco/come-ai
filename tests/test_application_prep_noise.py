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
