"""Tests for SPEC-051 — grouped ZIP export and one-click dossier copy."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.bundle_export import render_bundle_text, write_bundle_archive
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


def synthetic_job(**changes):
    payload = {
        "company": "Banque de Démo",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "REF-BUNDLE-2027-001",
        "official_url": "https://careers.example.test/jobs/bundle-1",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "source_status": "open",
        "requirements": "Modélisation LBO et valorisation.",
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


def bundle_client(service: CareerService) -> TestClient:
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(request, error):
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def make_service(tmp_path: Path) -> tuple[CareerService, dict]:
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    return service, job


def test_render_bundle_text_is_manual_and_complete():
    kit = {
        "readiness": 80,
        "block_reasons": ["Autorisation de travail non vérifiée."],
        "variant": {"id": "m_a", "label": "M&A"},
        "deep_link": "https://example.test/apply",
        "answers": {"availability": "6 mois", "contact_email": "demo@example.test"},
        "checklist": [{"id": "submit", "label": "Déposer manuellement", "done": False}],
        "letter": {"letter_markdown": "Lettre de démonstration", "cv_markdown": "CV de démonstration"},
    }
    text = render_bundle_text(kit, {"title": "Stagiaire", "company": "Banque"})
    assert "DOSSIER DE CANDIDATURE — Stagiaire — Banque" in text
    assert "Readiness : 80 %" in text
    assert "Variante : M&A" in text
    assert "Autorisation de travail non vérifiée." in text
    assert "- availability : 6 mois" in text
    assert "Lettre de démonstration" in text
    assert "- [ ] Déposer manuellement" in text
    assert "aucun envoi automatique" in text


def test_archive_is_flat_and_deterministic(tmp_path: Path):
    first = write_bundle_archive(
        tmp_path / "a.zip", {"cv.pdf": b"%PDF-demo", "cv.docx": b"docx"}, text="dossier"
    )
    second = write_bundle_archive(
        tmp_path / "b.zip", {"cv.pdf": b"%PDF-demo", "cv.docx": b"docx"}, text="dossier"
    )
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["cv.docx", "cv.pdf", "dossier.txt"]
        assert archive.read("dossier.txt") == b"dossier"


def test_archive_rejects_path_traversal(tmp_path: Path):
    with pytest.raises(ValueError):
        write_bundle_archive(tmp_path / "bad.zip", {"../escape.txt": b"x"})


def test_service_bundle_contains_every_document(tmp_path: Path):
    service, job = make_service(tmp_path)
    bundle = service.build_apply_kit_bundle(job["id"])
    assert bundle.suffix == ".zip"
    assert bundle.parent == service.studio_dir
    assert "/" not in bundle.name and ".." not in bundle.name
    with zipfile.ZipFile(bundle) as archive:
        assert set(archive.namelist()) == {
            "cv.pdf",
            "cv.docx",
            "lettre.pdf",
            "lettre.docx",
            "dossier.txt",
        }
        dossier = archive.read("dossier.txt").decode("utf-8")
        assert "Banque de Démo" in dossier
        assert "Stagiaire M&A" in dossier
        assert "aucun envoi automatique" in dossier
        assert "CHECKLIST HUMAINE" in dossier
        # Every member is a real document, never an empty placeholder.
        for name in archive.namelist():
            assert archive.getinfo(name).file_size > 0


def test_bundle_export_is_blocked_when_factual_audit_fails(tmp_path: Path):
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    with pytest.raises(UserFacingError, match="audit factuel"):
        service.build_apply_kit_bundle(job["id"])


def test_bundle_endpoint_smoke(tmp_path: Path):
    service, job = make_service(tmp_path)
    client = bundle_client(service)
    response = client.get(f"/api/career/apply-kit/{job['id']}/bundle.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "dossier.txt" in archive.namelist()

    bad = client.get("/api/career/apply-kit/job_unknown_bundle/bundle.zip")
    assert bad.status_code == 400


def test_bundle_filename_is_sanitized(tmp_path: Path):
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(
        synthetic_job(title="../../Stagiaire M&A", company="..\\Banque/Démo")
    )
    bundle = service.build_apply_kit_bundle(job["id"])
    assert ".." not in bundle.name
    assert "/" not in bundle.name
    assert "\\" not in bundle.name


def test_desktop_ui_wires_bundle_and_copy():
    app_js = (Path(__file__).resolve().parents[1] / "desktop_static" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "/bundle.zip" in app_js
    assert "tout télécharger (.zip)" in app_js
    assert "copier le dossier" in app_js
    assert "function kitBundleText(" in app_js
    assert "Qualité factuelle du dossier" in app_js
    assert "qualityAudit.export_allowed" in app_js
    assert '"aria-disabled": "true"' in app_js
    assert "Audit local factuel" in app_js
