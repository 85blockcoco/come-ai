"""Tests for SPEC-044 — one-call application kit (apply_kit)."""

from __future__ import annotations

from datetime import date, timedelta
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


def kit_client(service):
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(request, error):
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def test_apply_kit_complete(tmp_path: Path):
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    kit = service.build_apply_kit(job["id"])
    assert kit["job_id"] == job["id"]
    assert kit["readiness"] == 100
    assert kit["block_reasons"] == []
    assert kit["variant"] is not None
    assert kit["variant"]["id"] in {"m_a", "markets", "corporate_finance"}
    assert kit["letter"] is not None
    assert isinstance(kit["answers"], dict)
    assert isinstance(kit["checklist"], list) and kit["checklist"]
    assert kit["deep_link"] == "https://careers.example.test/jobs/demo-42"
    assert isinstance(kit["export_urls"], dict)


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
    assert data["readiness"] == 100
    assert data["variant"]["id"] == "m_a"
    # unknown job
    bad = client.post("/api/career/apply-kit/job_unknown_12345678")
    assert bad.status_code == 400


def test_apply_kit_module_dataclass():
    from career.apply_kit import ApplyKit

    kit = build_apply_kit("x", {}, job=None)
    assert isinstance(kit, ApplyKit)
    assert kit.readiness == 0
    assert kit.block_reasons


def test_apply_kit_checklist_lists_human_steps(tmp_path: Path):
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    kit = service.build_apply_kit(job["id"])

    items = {item["id"]: item for item in kit["checklist"]}
    assert items["attach_cv"]["done"] is False
    assert items["attach_letter"]["done"] is False
    assert items["submit"]["done"] is False
    assert "Aucune soumission automatique" in items["submit"]["note"]
    assert items["deadline"]["done"] is False
    assert items["dates"]["done"] is False
    # No submission field/action is ever exposed by the kit itself.
    assert "submitted" not in kit


def test_apply_kit_near_deadline_is_flagged(tmp_path: Path):
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    near = (date.today() + timedelta(days=3)).isoformat()
    job = service.import_job(synthetic_job(deadline_date=near))
    kit = service.build_apply_kit(job["id"])

    deadline_item = next(item for item in kit["checklist"] if item["id"] == "deadline")
    assert deadline_item["urgent"] is True
    assert "proche" in deadline_item["note"]


def test_apply_kit_answers_and_exports(tmp_path: Path):
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    kit = service.build_apply_kit(job["id"])

    assert kit["answers"]["display_name"] == "Personne Démo"
    assert kit["answers"]["education"] == "Master Finance (démo)"
    assert set(kit["export_urls"]) == {"cv_pdf", "letter_pdf", "cv_docx", "letter_docx"}


def test_apply_kit_explicit_variant_override(tmp_path: Path):
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    kit = service.build_apply_kit(job["id"], variant="markets")

    assert kit["variant"]["id"] == "markets"


def test_apply_kit_unknown_job_module_is_clean():
    kit = build_apply_kit("job_unknown_12345678", synthetic_profile(), job=None)

    assert kit.readiness == 0
    assert kit.block_reasons == ["Offre inconnue ou introuvable."]
    assert kit.variant is None
    assert kit.letter is None
    assert kit.export_urls == {}
