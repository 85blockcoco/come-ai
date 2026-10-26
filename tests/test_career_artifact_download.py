"""Téléchargement contrôlé des artefacts du kit de candidature (SPEC-009).

Ces tests complètent le parcours navigateur : ils vérifient que l'endpoint
introduit pour les liens de téléchargement E2E ne peut servir que les fichiers
du kit d'une candidature existante, jamais un chemin arbitraire.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError

_MEDIA_TYPES = {
    "cv": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "cover_letter": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "prep_sheet": "text/markdown; charset=utf-8",
}


def _client(service: CareerService) -> TestClient:
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def _service_with_kit(tmp_path: Path) -> tuple[CareerService, str]:
    service = CareerService(tmp_path)
    service.update_profile(
        {
            "display_name": "Personne Démo",
            "contact_email": "personne@example.test",
            "education": "Master Finance (démo)",
            "experience": "Projet étudiant de modélisation (démo)",
            "skills": "Excel, analyse financière",
            "languages": "Français, anglais C1",
            "eligibility": "unknown",
        }
    )
    job = service.import_job(
        {
            "company": "Banque de Démo",
            "title": "Stagiaire M&A",
            "source_name": "manual",
            "source_id": "REF-ARTEFACT-001",
            "official_url": "https://careers.example.test/jobs/artefact-42",
            "job_family": "M&A / Investment Banking",
            "city": "Paris",
            "country": "France",
            "source_status": "open",
            "requirements": "Modélisation financière et valorisation.",
            "description_original": "Offre de démonstration, données synthétiques.",
        }
    )
    kit = service.create_application_kit(job["id"], "fr")
    return service, kit["application"]["id"]


def test_each_kit_artifact_downloads_from_the_local_kits_directory(tmp_path: Path) -> None:
    service, application_id = _service_with_kit(tmp_path)
    client = _client(service)
    kits_root = (tmp_path / "output" / "career" / "kits").resolve()

    for kind, media_type in _MEDIA_TYPES.items():
        response = client.get(f"/api/career/applications/{application_id}/artifacts/{kind}")
        assert response.status_code == 200, (kind, response.text)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-type"].startswith(media_type)
        assert response.content, f"Artefact {kind} vide"
        path = service.application_artifact_path(application_id, kind)
        assert kits_root in path.parents, f"{path} hors du répertoire kits"


def test_unknown_artifact_kind_and_application_are_rejected(tmp_path: Path) -> None:
    service, application_id = _service_with_kit(tmp_path)
    client = _client(service)

    unknown_kind = client.get(f"/api/career/applications/{application_id}/artifacts/passwd")
    assert unknown_kind.status_code == 400
    assert "reconnu" in unknown_kind.json()["detail"]

    unknown_application = client.get("/api/career/applications/inconnue/artifacts/cv")
    assert unknown_application.status_code == 400
    assert "n’existe pas" in unknown_application.json()["detail"]


def test_artifact_path_never_escapes_the_kits_directory(tmp_path: Path) -> None:
    service, application_id = _service_with_kit(tmp_path)

    for kind in ("../cv", "../../etc/passwd", "cv/../../secret"):
        try:
            path = service.application_artifact_path(application_id, kind)
        except UserFacingError:
            continue
        raise AssertionError(f"Chemin accepté hors contrat : {path}")
