"""Parcours 3 — anti-invention : une exigence non étayée n'est jamais revendiquée."""

from __future__ import annotations

from utils import synthetic_offer, synthetic_profile


def test_unsupported_requirement_is_flagged_not_invented(page) -> None:
    assert "Côme AI Career" in page.open("/career")

    profile = synthetic_profile(
        experience="Projet étudiant d'analyse financière (démo).",
        skills="Excel, analyse financière",
    )
    assert page.api("PUT", "/api/career/profile", profile).status == 200

    imported = page.api(
        "POST",
        "/api/career/jobs/import",
        synthetic_offer(
            source_id="REF-DEMO-E2E-003",
            official_url="https://careers.example.test/jobs/e2e-003",
            requirements="Modélisation LBO avancée et suivi de dossiers private equity.",
        ),
    )
    assert imported.status == 201
    job_id = imported.json()["id"]

    kit = page.api(
        "POST",
        "/api/career/application-kits",
        {"job_id": job_id, "language": "fr", "variant": "m_a"},
    )
    assert kit.status == 200, kit.text
    payload = kit.json()

    unverified = payload["fact_checks"]["unverified_requirements"]
    assert any("LBO" in item["requirement"] for item in unverified)
    assert any("Non trouvé dans ton profil" in item["note"] for item in unverified)

    motivation = payload["kit_texts"]["motivation_short"]
    assert "LBO" not in motivation
    assert "private equity" not in motivation

    draft = payload["draft"]
    assert "LBO" in draft["cv_markdown"], "l'exigence reste citée pour vérification"
    assert "à vérifier" in draft["cv_markdown"].lower()

    exported = page.download(
        f"/api/career/application-drafts/{draft['id']}/download/cv/docx"
    )
    assert exported.status == 200
    assert exported.content[:2] == b"PK"
