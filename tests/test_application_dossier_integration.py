"""SK-11 — dossier de candidature 1 clic : intégration service + HTTP.

La boucle complète est vérifiée de bout en bout, sur une application locale et
des données synthétiques :

    offre → dossier (recommandations, CV, lettre, fiche, checklist, questions)
          → vérification (supported / unsupported / to_verify)
          → édition manuelle → nouvelle vérification
          → export local refusé tant qu'une affirmation n'est pas prouvée.

Aucune donnée réelle, aucun appel réseau, aucun envoi automatique.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.router import create_career_router
from career.service import SCHEMA_VERSION, CareerService
from workspace_core import UserFacingError


def synthetic_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Maison Démo",
        "title": "Analyste de données junior",
        "source_name": "manual",
        "source_id": "REF-DEMO-2027-021",
        "official_url": "https://careers.example.test/jobs/demo-21",
        "job_family": "Corporate Finance",
        "city": "Berlin",
        "country": "Germany",
        "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": "Excel\nMaster en finance\nAnglais professionnel",
        "languages_required": "English (Fluent)",
        "description_original": "Maison Démo recrute un analyste de données junior à Berlin. Excel est obligatoire.",
    }
    payload.update(changes)
    return payload


def synthetic_profile() -> dict[str, str]:
    return {
        "display_name": "Personne Démo",
        "education": "Master Finance (démo)",
        "experience": "Analyse SQL chez un distributeur (démo)",
        "skills": "Excel, tableaux de bord",
        "languages": "Anglais C1",
        "eligibility": "unknown",
    }


def dossier_client(service: CareerService) -> TestClient:
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


@pytest.fixture()
def service(tmp_path: Path) -> CareerService:
    instance = CareerService(tmp_path)
    instance.update_profile(synthetic_profile())
    return instance


@pytest.fixture()
def application(service: CareerService) -> dict:
    job = service.import_job(synthetic_job())
    created = service.create_application(job["id"])
    return {"job_id": job["id"], "application_id": created["id"]}


def test_schema_carries_the_dossier_table(service: CareerService) -> None:
    with sqlite3.connect(service.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "application_dossiers" in tables


def test_dossier_is_built_from_the_offer_and_the_profile(
    service: CareerService, application: dict
) -> None:
    payload = service.build_application_dossier(application["application_id"])
    assert payload["language"] == "en"
    assert payload["language_source"] == "offer"
    assert payload["version"] == 1
    keys = [artifact["key"] for artifact in payload["artifacts"]]
    assert keys == [
        "cv_recommendations",
        "adapted_cv",
        "cover_letter",
        "prep_sheet",
        "interview_questions",
        "checklist",
    ]
    letter = next(a for a in payload["artifacts"] if a["key"] == "cover_letter")
    assert "Excel" in letter["body"]
    assert payload["automatic_submission"] is False


def test_dossier_language_can_be_forced(service: CareerService, application: dict) -> None:
    payload = service.build_application_dossier(application["application_id"], "fr")
    assert payload["language"] == "fr"
    assert payload["language_source"] == "user"
    letter = next(a for a in payload["artifacts"] if a["key"] == "cover_letter")
    assert "Bonjour" in letter["body"]


def test_versions_are_kept(service: CareerService, application: dict) -> None:
    service.build_application_dossier(application["application_id"])
    second = service.build_application_dossier(application["application_id"])
    assert second["version"] == 2
    versions = service.list_application_dossier_versions(application["application_id"])
    assert [item["version"] for item in versions] == [2, 1]
    assert len(second["history"]) == 2


def test_unsupported_edition_blocks_the_export(
    service: CareerService, application: dict
) -> None:
    service.build_application_dossier(application["application_id"])
    stored = service.get_application_dossier(application["application_id"])
    letter = next(a for a in stored["artifacts"] if a["key"] == "cover_letter")
    edited = letter["body"] + "\n\nI have 5 years of experience with Kubernetes.\n"
    updated = service.update_application_dossier(
        application["application_id"], {"cover_letter": edited}
    )
    assert updated["export_allowed"] is False
    blocking = [
        claim
        for claim in updated["verification"]["claims"]
        if claim["verdict"] == "unsupported"
    ]
    assert blocking
    with pytest.raises(UserFacingError) as error:
        service.export_application_dossier(application["application_id"])
    assert "Export final bloqué" in str(error.value)


def test_supported_dossier_is_exported(service: CareerService, application: dict) -> None:
    service.build_application_dossier(application["application_id"])
    result = service.export_application_dossier(application["application_id"])
    assert result["automatic_submission"] is False
    files = result["files"]
    assert Path(files["cover_letter"]).exists()
    assert Path(files["verification"]).exists()
    manifest = json.loads(Path(files["manifest"]).read_text(encoding="utf-8"))
    assert manifest["automatic_submission"] is False


def test_dossier_is_read_only_before_building(service: CareerService, application: dict) -> None:
    with pytest.raises(UserFacingError):
        service.get_application_dossier(application["application_id"])


def test_http_workflow(service: CareerService, application: dict) -> None:
    client = dossier_client(service)
    response = client.post(
        f"/api/career/applications/{application['application_id']}/dossier",
        json={"language": ""},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "en"
    assert payload["export_allowed"] is True

    read = client.get(f"/api/career/applications/{application['application_id']}/dossier")
    assert read.status_code == 200
    assert read.json()["version"] == 1

    letter = next(a for a in payload["artifacts"] if a["key"] == "cover_letter")
    edited = letter["body"] + "\n\nI am a certified Kubernetes administrator.\n"
    patched = client.patch(
        f"/api/career/applications/{application['application_id']}/dossier",
        json={"cover_letter": edited},
    )
    assert patched.status_code == 200
    assert patched.json()["export_allowed"] is False

    blocked = client.post(
        f"/api/career/applications/{application['application_id']}/dossier/export"
    )
    assert blocked.status_code == 400
    assert "Export final bloqué" in blocked.json()["detail"]


def test_http_export_succeeds_when_everything_is_proved(
    service: CareerService, application: dict
) -> None:
    client = dossier_client(service)
    client.post(f"/api/career/applications/{application['application_id']}/dossier", json={})
    exported = client.post(
        f"/api/career/applications/{application['application_id']}/dossier/export"
    )
    assert exported.status_code == 200
    assert exported.json()["automatic_submission"] is False


def test_unknown_application_is_refused(service: CareerService) -> None:
    client = dossier_client(service)
    response = client.post("/api/career/applications/app_does_not_exist/dossier", json={})
    assert response.status_code == 400


def test_a_fact_removed_from_the_profile_stops_proving(
    service: CareerService, application: dict
) -> None:
    """Un fait modifié ou supprimé du profil ne peut plus rien prouver."""
    built = service.build_application_dossier(application["application_id"])
    assert built["export_allowed"] is True
    service.update_profile(
        {
            "display_name": "Personne Démo",
            "education": "Master Finance (démo)",
            "experience": "Analyse SQL chez un distributeur (démo)",
            "skills": "",
            "languages": "Anglais C1",
            "eligibility": "unknown",
        }
    )
    letter = next(a for a in built["artifacts"] if a["key"] == "cover_letter")
    updated = service.update_application_dossier(
        application["application_id"], {"cover_letter": letter["body"]}
    )
    assert updated["export_allowed"] is False
    blocking = [
        claim
        for claim in updated["verification"]["claims"]
        if claim["verdict"] == "unsupported"
    ]
    assert any("tableaux de bord" in claim["text"] for claim in blocking)
    with pytest.raises(UserFacingError):
        service.export_application_dossier(application["application_id"])


# --------------------------------------------------------------- garde-fous UI


def _node() -> str:
    import shutil

    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : les garde-fous JavaScript ne sont pas exécutables sur cette machine")


def _dossier_ui_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "career_static"
        / "js"
        / "application_dossier.js"
    ).read_text(encoding="utf-8")


def test_dossier_ui_blocks_the_export_and_never_sends_anything() -> None:
    source = _dossier_ui_source()
    script = r'''
const assert = require("assert");
const calls = [];
function make(tag, text="", className="") {
  return {tag, textContent:text, className, children:[], dataset:{},
    append(...items){this.children.push(...items);}, addEventListener(){}};
}
async function api(url, options = {}) { calls.push({url, options}); return {files:{}}; }
function setMessage(value="", error=false) { calls.push({message:value, error}); }
__SOURCE__
function container() {
  return {children:[], hidden:false,
    replaceChildren(){ this.children = []; },
    append(...items){ this.children.push(...items); }};
}
const dossier = {
  application_id: "app_demo",
  version: 2,
  language: "en",
  language_source: "user",
  export_allowed: false,
  automatic_submission: false,
  verification: {supported_count: 3, unsupported_count: 1, to_verify_count: 2,
    claims: [
      {verdict: "supported", text: "Excel dashboards for sales reporting", fact_id: "f1"},
      {verdict: "unsupported", text: "I have 5 years of experience with Kubernetes.", fact_id: ""},
      {verdict: "to_verify", text: "Confirm the start date with the team.", fact_id: ""},
    ]},
  recommendations: [{code: "HIGHLIGHT", requirement: "Excel", quote: "Excel dashboards"}],
  diff: [{kind: "kept", text: "Excel dashboards"}],
  artifacts: [{key: "cover_letter", body: "# Cover letter"}],
};
const target = container();
renderApplicationDossier(dossier, target);
const rendered = JSON.stringify(target);
assert.ok(rendered.includes("Export final bloqué"), "le blocage doit être visible");
assert.ok(rendered.includes("non prouvée"), "le compteur doit être visible");
assert.ok(rendered.includes("I have 5 years of experience with Kubernetes."), "la phrase fautive doit être montrée");
assert.ok(rendered.includes("HIGHLIGHT"), "les recommandations doivent être affichées");
assert.ok(rendered.includes("Cover letter"), "les livrables doivent être listés");
assert.ok(rendered.includes("aucun envoi automatique"), "l'absence d'envoi doit être rappelée");
assert.strictEqual(calls.length, 0, "le rendu ne doit déclencher aucun appel");
'''.replace("__SOURCE__", source)
    import subprocess

    completed = subprocess.run([_node(), "-e", script], text=True, capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stderr


def test_dossier_ui_never_calls_a_remote_host() -> None:
    source = _dossier_ui_source()
    assert "http://" not in source
    assert "https://" not in source
    assert "fetch(" not in source
    assert "/api/career/" in source


def test_dossier_button_is_wired_in_the_career_ui() -> None:
    root = Path(__file__).resolve().parents[1]
    career_js = (root / "career_static" / "career.js").read_text(encoding="utf-8")
    index = (root / "career_static" / "index.html").read_text(encoding="utf-8")
    assert "openApplicationDossier(application, dossierContainer)" in career_js
    assert "Ouvrir le dossier vérifiable" in career_js
    assert '<script src="/career-static/js/application_dossier.js" defer></script>' in index
    assert index.index("cv_plan.js") < index.index("application_dossier.js") < index.index("career.js")
