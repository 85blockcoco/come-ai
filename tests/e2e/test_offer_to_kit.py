"""Parcours 1 — offre → préparation → kit → export → pipeline (SPEC-007)."""

from __future__ import annotations

from utils import synthetic_offer, synthetic_profile


def test_offer_to_kit_journey(page) -> None:
    html = page.open("/career")
    assert "Côme AI Career" in html
    assert "Candidatures" in html

    profile = page.api("PUT", "/api/career/profile", synthetic_profile())
    assert profile.status == 200

    imported = page.api("POST", "/api/career/jobs/import", synthetic_offer())
    assert imported.status == 201, imported.text
    job_id = imported.json()["id"]

    detail = page.api("GET", f"/api/career/jobs/{job_id}")
    assert detail.status == 200
    assert detail.json()["company"] == "Banque de Démo"

    prep = page.api("GET", f"/api/career/jobs/{job_id}/prep")
    assert prep.status == 200
    assert prep.json()["cv_coverage"]["requirements_total"] >= 1

    kit = page.api(
        "POST",
        "/api/career/application-kits",
        {"job_id": job_id, "language": "fr", "variant": "m_a"},
    )
    assert kit.status == 200, kit.text
    kit_payload = kit.json()
    assert kit_payload["automatic_submission"] is False
    assert kit_payload["provenance_map"], "chaque fait injecté porte sa provenance"

    reopened = page.api(
        "POST",
        "/api/career/application-kits",
        {"job_id": job_id, "language": "fr", "variant": "m_a"},
    )
    assert reopened.status == 200
    assert reopened.json()["draft"]["id"] == kit_payload["draft"]["id"]

    exported = page.download(
        f"/api/career/application-drafts/{kit_payload['draft']['id']}/download/cv/docx"
    )
    assert exported.status == 200
    assert exported.content[:2] == b"PK", "le DOCX téléchargé est une archive OOXML valide"

    pipeline = page.api("GET", "/api/career/application-pipeline")
    assert pipeline.status == 200
    payload = pipeline.json()
    assert payload["automatic_submission"] is False
    entry = next(item for item in payload["pipeline"] if item["job_id"] == job_id)
    assert entry["stage"] in {"tracking_created", "kit_generated", "variant_selected"}
