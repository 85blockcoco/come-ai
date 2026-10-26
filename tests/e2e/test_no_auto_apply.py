"""Parcours 4 — zéro envoi automatique : ni UI, ni route, ni pipeline."""

from __future__ import annotations

from utils import (
    generate_kit_from_prep_ui,
    run_offer_analysis_ui,
    synthetic_offer,
    synthetic_profile,
    wait_for_app_ready,
)

FORBIDDEN_UI = ("mailto:", "smtplib", "automatic_submission\": true", "automatic_submission: true")


def test_no_automatic_submission_anywhere(page) -> None:
    html = page.open("/career")
    assert "Côme AI Career" in html
    lowered = html.lower()
    for marker in FORBIDDEN_UI:
        assert marker not in lowered, f"l'UI expose une action d'envoi : {marker}"
    assert 'id="auto-apply"' not in lowered
    assert 'id="send-application"' not in lowered

    schema_free_checks = (
        "/api/career/apply",
        "/api/career/send",
        "/api/career/submit",
        "/api/career/upload",
        "/api/career/contact",
    )
    for forbidden_path in schema_free_checks:
        response = page.api("POST", forbidden_path, {})
        assert response.status in {404, 405}, (
            f"route d'envoi accessible : {forbidden_path} → {response.status}"
        )

    assert page.api("PUT", "/api/career/profile", synthetic_profile()).status == 200
    imported = page.api(
        "POST",
        "/api/career/jobs/import",
        synthetic_offer(
            source_id="REF-DEMO-E2E-004",
            official_url="https://careers.example.test/jobs/e2e-004",
        ),
    )
    assert imported.status == 201
    job_id = imported.json()["id"]

    # Même après un parcours complet dans le navigateur, aucune action
    # d'envoi, de contact ou de téléversement n'apparaît.
    if page.supports_ui:
        page.open("/career")
        wait_for_app_ready(page)
        run_offer_analysis_ui(page, job_id)
        kit_text = generate_kit_from_prep_ui(page)
        assert "Aucun envoi automatique" in kit_text
        assert page.count('a[href^="mailto:"]') == 0
        assert page.count("button:has-text('Envoyer la candidature')") == 0
        assert page.count("button:has-text('Contacter le recruteur')") == 0

    pipeline = page.api("GET", "/api/career/application-pipeline")
    assert pipeline.status == 200
    assert pipeline.json()["automatic_submission"] is False

    kit = page.api(
        "POST",
        "/api/career/application-kits",
        {"job_id": job_id, "language": "fr", "variant": "m_a"},
    )
    assert kit.status == 200
    assert kit.json()["automatic_submission"] is False
