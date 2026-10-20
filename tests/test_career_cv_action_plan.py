"""Fact-safe, actionable CV guidance for one synthetic offer."""

from pathlib import Path

from career.application_prep import prepare_application


def profile() -> dict[str, str]:
    return {
        "education": "Master 1 Finance, analyse financière et valorisation.",
        "experience": "Projet académique : construction d'un modèle financier à trois états.",
        "skills": "Finance: Financial Modelling, Financial Analysis.\nTools: Advanced Excel, PowerPoint.",
        "languages": "Français natif, English C1.",
        "eligibility": "compatible",
        "contact_email": "secret@example.test",
    }


def job() -> dict[str, str]:
    return {
        "id": "synthetic-job",
        "title": "M&A Internship",
        "company": "Synthetic Bank",
        "requirements": (
            "Advanced Excel skills are required.\n"
            "Bloomberg Terminal proficiency is required.\n"
            "Fluent English is required."
        ),
        "language": "en",
        "official_url": "https://careers.example.test/jobs/synthetic",
        "source_name": "synthetic",
        "source_status": "open",
    }


def test_plan_prefers_explicit_evidence_and_names_the_cv_section() -> None:
    prep = prepare_application(profile(), {}, job())
    excel = next(item for item in prep["cv_action_plan"] if "Excel" in item["requirement"])
    assert excel["section"] == "Compétences"
    assert "Excel" in excel["profile_evidence"]
    assert excel["matched_on"][0] == "excel"
    assert excel["offer_reference"] == "Exigence détectée n°1"
    assert excel["profile_reference"] == "Profil local · Compétences"
    assert "sans modifier les faits" in excel["suggested_change"]


def test_missing_requirement_is_never_turned_into_a_claim() -> None:
    prep = prepare_application(profile(), {}, job())
    missing = next(item for item in prep["cv_action_plan"] if "Bloomberg" in item["requirement"])
    assert missing["status"] == "needs_evidence"
    assert missing["action_type"] == "verify_before_adding"
    assert missing["profile_evidence"] == ""
    assert "Ne l’ajoute pas" in missing["suggested_change"]
    assert {"bloomberg", "terminal"} <= set(missing["missing_keywords"])


def test_unchiffred_experience_is_flagged_without_inventing_a_result() -> None:
    custom_job = job()
    custom_job["requirements"] = "Construction d’un modèle financier à trois états requise."
    prep = prepare_application(profile(), {}, custom_job)
    action = prep["cv_action_plan"][0]
    assert action["profile_reference"] == "Profil local · Expériences"
    assert action["evidence_quality"] == "needs_quantification"
    assert not any(character.isdigit() for character in action["profile_evidence"])


def test_coverage_is_documentary_and_excludes_contact_data() -> None:
    prep = prepare_application(profile(), {}, job())
    coverage = prep["cv_coverage"]
    assert coverage["requirements_total"] == 3
    assert coverage["supported"] == 2
    assert coverage["to_verify"] == 1
    assert coverage["coverage_percent"] == 67
    assert coverage["target_language"] == "en"
    assert "probabilité d’embauche" in coverage["disclaimer"]
    assert "secret@example.test" not in repr(prep["cv_action_plan"])


def test_ui_renders_the_precise_cv_plan() -> None:
    source = (Path(__file__).resolve().parents[1] / "career_static/career.js").read_text(encoding="utf-8")
    renderer = source.split("function renderStagePrep(prep) {", 1)[1].split(
        "\nasync function loadStagePrep", 1
    )[0]
    assert "Plan précis pour ton CV" in renderer
    assert "cv_action_plan" in renderer
    assert "cv_coverage" in renderer
    assert "Ce n’est pas une probabilité d’embauche" in renderer
    assert "profile_evidence" in renderer
    assert "suggested_change" in renderer
    assert "Préparer dans le Studio" in renderer
    assert "Mots-clés non étayés à vérifier" in renderer
    assert "openStudioForJob(job, cvCoverage.target_language)" in renderer


def test_studio_opening_stays_local_and_preselects_the_offer() -> None:
    source = (Path(__file__).resolve().parents[1] / "career_static/career.js").read_text(encoding="utf-8")
    helper = source.split("function openStudioForJob(job, language = \"\") {", 1)[1].split(
        "\nfunction renderDraftHistory", 1
    )[0]
    assert 'elements.applicationDraftMode.value = "local"' in helper
    assert "elements.applicationDraftConsent.checked = false" in helper
    assert 'showView("studio")' in helper
    renderer = source.split("function renderStudioJobOptions(jobs) {", 1)[1].split(
        "\nfunction openStudioForJob", 1
    )[0]
    assert "state.pendingStudioJob?.id || current" in renderer
    assert "elements.applicationDraftJob.value = selected" in renderer
