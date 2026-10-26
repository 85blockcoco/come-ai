"""Parcours 4 — zéro envoi automatique : ni UI, ni route, ni pipeline."""

from __future__ import annotations

from utils import synthetic_offer, synthetic_profile

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

    pipeline = page.api("GET", "/api/career/application-pipeline")
    assert pipeline.status == 200
    assert pipeline.json()["automatic_submission"] is False

    kit = page.api(
        "POST",
        "/api/career/application-kits",
        {"job_id": imported.json()["id"], "language": "fr", "variant": "m_a"},
    )
    assert kit.status == 200
    assert kit.json()["automatic_submission"] is False
