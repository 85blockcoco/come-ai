"""Parcours 2 — profil incomplet → preuve ajoutée → couverture en hausse."""

from __future__ import annotations

from utils import (
    fill_profile_ui,
    run_offer_analysis_ui,
    synthetic_offer,
    wait_for_app_ready,
)

EMPTY_PROFILE = {
    "display_name": "",
    "education": "",
    "experience": "",
    "skills": "",
    "languages": "",
    "eligibility": "unknown",
}

PROVEN_PROFILE = {
    "display_name": "Personne Démo",
    "education": "Master Finance (démo)",
    "experience": "Projet étudiant avec Python et statistiques (démo).",
    "skills": "Python, statistiques",
    "languages": "Français",
    "eligibility": "unknown",
}


def test_incomplete_profile_adds_evidence_and_raises_coverage(page) -> None:
    assert page.api("PUT", "/api/career/profile", EMPTY_PROFILE).status == 200
    imported = page.api(
        "POST",
        "/api/career/jobs/import",
        synthetic_offer(
            source_id="REF-DEMO-E2E-002",
            official_url="https://careers.example.test/jobs/e2e-002",
            requirements="Python et statistiques requises pour l'analyse.",
        ),
    )
    assert imported.status == 201
    job_id = imported.json()["id"]

    assert "Côme AI Career" in page.open("/career")

    # Avant toute preuve, l'UI doit afficher explicitement les exigences
    # manquantes — jamais une expérience inventée.
    if page.supports_ui:
        wait_for_app_ready(page)
        before_ui = run_offer_analysis_ui(page, job_id)
        assert "Non trouvé dans ton profil" in before_ui

    before = page.api("GET", f"/api/career/jobs/{job_id}/prep")
    assert before.status == 200
    before_payload = before.json()
    assert before_payload["cv_coverage"]["requirements_total"] >= 1
    assert before_payload["cv_coverage"]["supported"] == 0
    assert before_payload["unverified_elements"], "sans preuve, l'exigence reste à vérifier"

    # La preuve est ajoutée par le vrai formulaire de profil du navigateur.
    if page.supports_ui:
        fill_profile_ui(page, PROVEN_PROFILE)
        page.open("/career")
        wait_for_app_ready(page)
        after_ui = run_offer_analysis_ui(page, job_id)
        assert "Éléments pertinents de ton profil" in after_ui
    else:
        assert page.api("PUT", "/api/career/profile", PROVEN_PROFILE).status == 200

    after = page.api("GET", f"/api/career/jobs/{job_id}/prep")
    assert after.status == 200
    after_payload = after.json()
    assert after_payload["cv_coverage"]["supported"] > before_payload["cv_coverage"]["supported"]
    assert (
        after_payload["cv_coverage"]["coverage_percent"]
        > before_payload["cv_coverage"]["coverage_percent"]
    )
    assert len(after_payload["unverified_elements"]) < len(before_payload["unverified_elements"])
