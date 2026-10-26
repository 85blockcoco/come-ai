"""Tests for SPEC-044 — one-call application kit (apply_kit)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.apply_kit import build_apply_kit
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


def synthetic_job(**changes):
    payload = {
        "company": "Banque de Démo",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "REF-DEMO-2027-014",
        "official_url": "https://careers.example.test/jobs/demo-42",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "deadline_date": "2027-02-01",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": "Modélisation LBO avancée et valorisation.",
        "description_original": "Stage de démonstration, données synthétiques.",
    }
    payload.update(changes)
    return payload


def synthetic_profile():
    return {
        "display_name": "Personne Démo",
        "education": "Master Finance (démo)",
        "experience": "Projet étudiant de modélisation (démo)",
        "skills": "Excel, analyse financière",
        "languages": "Français, anglais C1",
        "eligibility": "compatible",
    }


def verified_conforming_job(**changes):
    payload = synthetic_job(
        official_url="https://careers.example.test/jobs/demo-42",
        duration_months=6,
        end_date="2027-07-31",
        source_status="open",
        deadline_status="upcoming",
        requirements="",
        description_original="",
        source_verified=True,
        qualification_snapshot_current=True,
        official_source_trust={"status": "verified"},
        apply_qualification={"target_status": "conforming", "reasons": []},
    )
    payload.update(changes)
    return payload


def kit_client(service):
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(request, error):
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def test_apply_kit_complete():
    job = verified_conforming_job()
    kit = build_apply_kit(job["source_id"], synthetic_profile(), job=job)
    assert kit.job_id == job["source_id"]
    assert kit.readiness == 100
    assert kit.block_reasons == []
    assert kit.variant is not None
    assert kit.variant["id"] in {"m_a", "markets", "corporate_finance"}
    assert kit.letter is not None
    assert isinstance(kit.answers, dict)
    assert isinstance(kit.checklist, list) and kit.checklist
    assert kit.deep_link == "https://careers.example.test/jobs/demo-42"
    assert isinstance(kit.export_urls, dict)


def test_apply_kit_incomplete(tmp_path: Path):
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    kit = service.build_apply_kit(job["id"])
    assert kit["readiness"] < 100
    assert kit["block_reasons"]
    assert any("Autorisation de travail" in r for r in kit["block_reasons"])


def test_apply_kit_unknown_job(tmp_path: Path):
    service = CareerService(tmp_path)
    with pytest.raises(UserFacingError):
        service.build_apply_kit("job_does_not_exist_12345678")


def test_apply_kit_endpoint_smoke(tmp_path: Path):
    service = CareerService(tmp_path)
    client = kit_client(service)
    client.put("/api/career/profile", json=synthetic_profile())
    job = client.post("/api/career/jobs/import", json=synthetic_job()).json()
    job_id = job["id"]
    resp = client.post(f"/api/career/apply-kit/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["readiness"] < 100
    assert data["block_reasons"]
    assert data["deep_link"] is None
    first_exports = data["export_urls"]
    assert set(first_exports) == {"cv_pdf", "letter_pdf", "cv_docx", "letter_docx"}
    application = service.list_applications()[0]
    assert application["stage"] == "to_review"
    assert application["approval_granted"] is False
    repeat = client.post(f"/api/career/apply-kit/{job_id}")
    assert repeat.status_code == 200
    assert repeat.json()["export_urls"] == first_exports
    applications = service.list_applications()
    assert len(applications) == 1
    assert applications[0]["approval_granted"] is False
    assert client.post(f"/api/career/apply-kit/{job_id}", json={"language": "es"}).status_code == 422
    assert client.post(f"/api/career/apply-kit/{job_id}", json={"variant": "unknown"}).status_code == 422
    # unknown job
    bad = client.post("/api/career/apply-kit/job_unknown_12345678")
    assert bad.status_code == 400


def test_apply_kit_module_dataclass():
    from career.apply_kit import ApplyKit

    kit = build_apply_kit("x", {}, job=None)
    assert isinstance(kit, ApplyKit)
    assert kit.readiness == 0
    assert kit.block_reasons


def test_apply_kit_does_not_follow_unvalidated_apply_url():
    job = verified_conforming_job(apply_url="https://attacker.example.test/collect")
    kit = build_apply_kit(job["source_id"], synthetic_profile(), job=job)
    assert kit.deep_link == job["official_url"]


def test_apply_kit_does_not_mark_unverified_qualification_ready():
    job = verified_conforming_job(
        apply_qualification={
            "target_status": "to_verify",
            "reasons": ["Durée ou début non vérifiable."],
        }
    )
    kit = build_apply_kit(job["source_id"], synthetic_profile(), job=job)
    assert kit.readiness < 100
    assert any("qualification" in item["id"] for item in kit.checklist)
    qualification = next(item for item in kit.checklist if item["id"] == "qualification")
    assert qualification["done"] is False
