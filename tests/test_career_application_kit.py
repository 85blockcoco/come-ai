"""Kit de candidature local (CVBOOST-05) : couverture hors ligne.

Toutes les fixtures sont synthétiques : aucune vraie offre, aucune vraie
entreprise, aucune donnée personnelle. Rien n'appelle le réseau. Ce qui est
vérifié : la création idempotente du suivi, le préremplissage depuis l'offre
présélectionnée, la langue conservée, l'honnêteté du contenu (profil vide,
exigence non étayée), l'export DOCX/PDF après correction, la robustesse au
double clic et au rechargement, et la preuve statique qu'aucune route
d'envoi/de courriel n'existe.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


def synthetic_job(**changes: object) -> dict[str, object]:
    """Offre clairement synthétique, sans référence à une vraie entreprise."""
    payload: dict[str, object] = {
        "company": "Banque de Démo",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "REF-DEMO-2027-014",
        "official_url": "https://careers.example.test/jobs/demo-42",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "deadline_date": (date.today() + timedelta(days=14)).isoformat(),
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": "Modélisation LBO avancée et valorisation.",
        "description_original": "Stage de démonstration, données synthétiques.",
    }
    payload.update(changes)
    return payload


def synthetic_profile() -> dict[str, str]:
    return {
        "display_name": "Personne Démo",
        "education": "Master Finance (démo)",
        "experience": "Projet étudiant de modélisation (démo)",
        "skills": "Excel, analyse financière",
        "languages": "Français, anglais C1",
        "eligibility": "unknown",
    }


def kit_client(service: CareerService) -> TestClient:
    """App minimale avec le même contrat d'erreur que l'application réelle."""
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


# --- 1. Création idempotente du suivi ----------------------------------------


def test_kit_creation_is_idempotent_for_tracking_and_draft(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())

    first = service.create_application_kit(job["id"], "fr")
    assert first["created_tracking"] is True
    assert first["created_draft"] is True
    assert first["application"]["stage"] == "to_review"

    second = service.create_application_kit(job["id"], "fr")
    assert second["created_tracking"] is False, "le suivi existe déjà, il est réutilisé"
    assert second["created_draft"] is False, "le brouillon local est réutilisé, pas dupliqué"
    assert second["application"]["id"] == first["application"]["id"]
    assert second["draft"]["id"] == first["draft"]["id"]

    events = service.get_application(first["application"]["id"])["events"]
    types = [event["event_type"] for event in events]
    assert types.count("application_created") == 1
    assert types.count("kit_prepared") == 1
    assert len(service.list_applications()) == 1
    assert len(service.list_application_drafts()) == 1


def test_double_click_produces_one_tracking_one_draft_one_event(tmp_path: Path) -> None:
    """Deux appels rapprochés (double clic) n'écrivent qu'une seule fois."""
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())

    rapid = [service.create_application_kit(job["id"], "fr") for _ in range(2)]
    assert rapid[0]["application"]["id"] == rapid[1]["application"]["id"]
    assert rapid[0]["draft"]["id"] == rapid[1]["draft"]["id"]

    events = service.get_application(rapid[0]["application"]["id"])["events"]
    assert [event["event_type"] for event in events].count("kit_prepared") == 1
    assert [event["event_type"] for event in events].count("application_created") == 1


# --- 2. Offre préselectionnée : champs préremplis exacts ----------------------


def test_kit_prefills_exact_offer_facts_and_reference(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())

    kit = service.create_application_kit(job["id"], "fr")
    facts = kit["job"]
    assert facts["company"] == "Banque de Démo"
    assert facts["title"] == "Stagiaire M&A"
    assert facts["reference"] == "REF-DEMO-2027-014"
    assert facts["official_url"] == "https://careers.example.test/jobs/demo-42"
    assert facts["deadline_date"] == job["deadline_date"]
    assert kit["draft"]["job_id"] == job["id"], "le brouillon est rattaché à CETTE offre"
    motivation = kit["kit_texts"]["motivation_short"]
    assert "Stagiaire M&A" in motivation
    assert "Banque de Démo" in motivation
    assert "Modélisation LBO" not in motivation, "aucune compétence exigée n'est revendiquée"


def test_kit_is_scoped_to_the_preselected_offer_only(tmp_path: Path) -> None:
    """Un kit ouvert depuis une offre ne touche jamais les autres offres."""
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job_a = service.import_job(synthetic_job())
    job_b = service.import_job(
        synthetic_job(
            title="Stage Corporate (démo)",
            source_id="REF-DEMO-777",
            official_url="https://careers.example.test/jobs/demo-777",
        )
    )
    assert job_b["id"] != job_a["id"], "les deux offres synthétiques restent distinctes"

    kit = service.create_application_kit(job_a["id"], "fr")
    assert kit["application"]["job_id"] == job_a["id"]
    assert len(service.list_applications()) == 1, "pas de suivi fantôme pour les autres offres"
    assert len(service.list_application_drafts()) == 1, "pas de brouillon pour les autres offres"
    assert service.get_job(job_b["id"])["application"] is None


# --- 3. Langue conservée ------------------------------------------------------


def test_kit_language_is_conserved_per_explicit_choice(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())

    kit_en = service.create_application_kit(job["id"], "en")
    assert kit_en["language"] == "en"
    assert kit_en["draft"]["language"] == "en"
    assert "I am applying for the Stagiaire M&A position" in kit_en["kit_texts"]["motivation_short"]

    # Rouvrir en français : le brouillon français est créé une fois, puis
    # réutilisé ; le brouillon anglais n'est pas écrasé.
    kit_fr = service.create_application_kit(job["id"], "fr")
    assert kit_fr["draft"]["language"] == "fr"
    assert "Je candidate au poste de Stagiaire M&A" in kit_fr["kit_texts"]["motivation_short"]
    again_fr = service.create_application_kit(job["id"], "fr")
    assert again_fr["draft"]["id"] == kit_fr["draft"]["id"]
    assert [d["language"] for d in service.list_application_drafts()] == ["fr", "en"]

    texts_fr = service.update_kit_texts(
        kit_fr["application"]["id"], {"motivation_short": "Relu par moi, en français."}
    )
    assert texts_fr["language"] == "fr"

# --- 4. Profil vide : honnêteté ----------------------------------------------


def test_empty_profile_keeps_bracketed_placeholders_and_flags_missing_fields(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())

    kit = service.create_application_kit(job["id"], "fr")
    cv = kit["draft"]["cv_markdown"]
    for placeholder in ("[Nom à compléter]", "[Formation à compléter]", "[Expériences à compléter]"):
        assert placeholder in cv
        assert placeholder in kit["kit_texts"]["motivation_short"]
    assert "Excel" not in cv, "aucune compétence n'est inventée avec un profil vide"

    markers = kit["fact_checks"]["placeholders"]
    assert any("Nom à compléter" in marker for marker in markers)
    assert any("Formation à compléter" in marker for marker in markers)
    assert any("Disponibilité à compléter" in marker for marker in markers)
    assert any("Éléments à compléter" in check for check in kit["draft"]["checks"]), (
        "les champs de profil manquants sont signalés par le vérificateur"
    )


def test_kit_rejects_an_unknown_language(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(synthetic_job())
    with pytest.raises(UserFacingError):
        service.create_application_kit(job["id"], "klingon")


# --- 5. Exigence non étayée : listée, jamais revendiquée ---------------------


def test_unsubstantiated_offer_requirement_is_listed_never_claimed(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    # Le profil ne mentionne ni LBO ni private equity : l'exigence doit rester
    # « non trouvé dans ton profil » dans le kit, sans être revendiquée.
    service.update_profile(synthetic_profile())
    job = service.import_job(
        synthetic_job(requirements="Structuration LBO avancée et suivi de dossiers private equity.")
    )

    kit = service.create_application_kit(job["id"], "fr")
    unverified = kit["fact_checks"]["unverified_requirements"]
    assert any("LBO" in item["requirement"] for item in unverified)
    assert any("Non trouvé dans ton profil" in item["note"] for item in unverified)
    motivation = kit["kit_texts"]["motivation_short"]
    assert "LBO" not in motivation and "private equity" not in motivation

    draft = kit["draft"]
    assert "LBO" in draft["cv_markdown"], "l'exigence reste citée telle quelle, marquée « à vérifier »"
    assert "à vérifier" in draft["cv_markdown"]


# --- 6. Textes du kit : modifications, rechargement, validation --------------


def test_kit_text_edits_persist_across_reload_and_stay_partial(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    application_id = service.create_application_kit(job["id"], "fr")["application"]["id"]

    saved = service.update_kit_texts(
        application_id,
        {
            "motivation_short": "Bonjour, motivation personnelle relue par moi.",
            "availability": "Disponible 6 mois à partir du 1er février (démo).",
        },
    )
    assert saved["kit_edited"] is True
    assert saved["kit_texts"]["motivation_short"] == "Bonjour, motivation personnelle relue par moi."

    # Rechargement : les textes modifiés restent enregistrés.
    reloaded = service.get_application_kit(application_id, "fr")
    assert reloaded["kit_texts"] == saved["kit_texts"]
    assert reloaded["kit_edited"] is True

    # Mise à jour partielle : la motivation précédente reste conservée.
    partial = service.update_kit_texts(application_id, {"availability": "Dispo immédiate (démo)."})
    assert partial["kit_texts"]["motivation_short"] == "Bonjour, motivation personnelle relue par moi."
    assert partial["kit_texts"]["availability"] == "Dispo immédiate (démo)."

    events = service.get_application(application_id)["events"]
    contents = [event["detail"] for event in events if event["event_type"] == "kit_content"]
    assert len(contents) == 2, "chaque enregistrement est un événement JSON, sans changement de schéma"


def test_kit_text_validation_rejects_empty_or_oversized(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    application_id = service.create_application_kit(job["id"], "fr")["application"]["id"]

    for bad_texts in ({"motivation_short": ""}, {"motivation_short": "   "}, {}, "pas un dictionnaire"):
        with pytest.raises(UserFacingError):
            service.update_kit_texts(application_id, bad_texts)
    with pytest.raises(UserFacingError):
        service.update_kit_texts(application_id, {"motivation_short": "x" * 1_301})
    with pytest.raises(UserFacingError):
        service.update_kit_texts(application_id, {"availability": "x" * 401})
    with pytest.raises(UserFacingError):
        service.update_kit_texts("app_inexistante_0001", {"motivation_short": "texte"})


# --- 7. Brouillon modifiable avant export + exports locaux -------------------


def test_draft_edits_feed_the_docx_pdf_exports(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    kit = service.create_application_kit(job["id"], "fr")
    draft_id = kit["draft"]["id"]

    edited = service.update_application_draft(
        draft_id,
        "# CV relu\n\nContenu corrigé localement, sans invention.",
        "# Lettre relu\n\nEn-tête corrigé (démo).",
    )
    assert "Contenu corrigé localement" in edited["cv_markdown"]

    markdown_export = service.export_application_draft(draft_id, "cv", "md")
    assert "Contenu corrigé localement" in markdown_export.read_text(encoding="utf-8")
    for kind in ("cv", "letter"):
        for export_format in ("docx", "pdf"):
            target = service.export_application_draft(draft_id, kind, export_format)
            assert target.exists() and target.stat().st_size > 1_000
            if export_format == "docx":
                with zipfile.ZipFile(target) as archive:
                    assert "word/document.xml" in archive.namelist()
            else:
                assert target.read_bytes()[:4] == b"%PDF"


def test_export_failure_is_a_clean_user_error_leaving_no_file(tmp_path: Path) -> None:
    from career import service as career_service_module

    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    kit = service.create_application_kit(job["id"], "fr")
    draft_id = kit["draft"]["id"]
    studio_dir_before = {path.name for path in service.studio_dir.glob("*")}

    original = career_service_module.write_docx

    def broken_writer(**_: object) -> None:
        raise RuntimeError("échec synthétique de génération")

    try:
        career_service_module.write_docx = broken_writer  # type: ignore[assignment]
        with pytest.raises(UserFacingError) as error:
            service.export_application_draft(draft_id, "cv", "docx")
        assert "n’a pas pu être généré" in str(error.value)
    finally:
        career_service_module.write_docx = original  # type: ignore[assignment]

    studio_dir_after = {path.name for path in service.studio_dir.glob("*")}
    assert studio_dir_after == studio_dir_before, "aucun fichier partiel n'est laissé"


# --- 8. Parcours HTTP complet sur données synthétiques -----------------------


def test_full_http_kit_journey_with_synthetic_data(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = kit_client(service)

    profile = client.put("/api/career/profile", json=synthetic_profile())
    assert profile.status_code == 200

    job = client.post("/api/career/jobs/import", json=synthetic_job())
    assert job.status_code == 201
    job_id = job.json()["id"]

    opened = client.post("/api/career/application-kits", json={"job_id": job_id, "language": "fr"})
    assert opened.status_code == 200
    kit = opened.json()
    assert kit["application"]["job_id"] == job_id
    assert kit["job"]["official_url"].startswith("https://careers.example.test/")

    reopened = client.post("/api/career/application-kits", json={"job_id": job_id, "language": "fr"})
    assert reopened.status_code == 200
    assert reopened.json()["application"]["id"] == kit["application"]["id"]
    assert reopened.json()["draft"]["id"] == kit["draft"]["id"]

    application_id = kit["application"]["id"]
    saved_texts = client.patch(
        f"/api/career/applications/{application_id}/kit",
        json={"motivation_short": "Bonjour (démo), motivation relue.", "availability": "6 mois à partir du 1er février (démo)."},
    )
    assert saved_texts.status_code == 200
    assert saved_texts.json()["kit_texts"]["availability"] == "6 mois à partir du 1er février (démo)."
    reloaded = client.get(f"/api/career/applications/{application_id}/kit")
    assert reloaded.status_code == 200
    assert reloaded.json()["kit_texts"] == saved_texts.json()["kit_texts"]

    draft_id = kit["draft"]["id"]
    saved_draft = client.patch(
        f"/api/career/application-drafts/{draft_id}",
        json={
            "cv_markdown": "# CV (démo)\n\nRelu et corrigé localement.",
            "letter_markdown": "# Lettre (démo)\n\nRelue et corrigée localement.",
        },
    )
    assert saved_draft.status_code == 200
    assert "Relu et corrigé localement" in saved_draft.json()["cv_markdown"]

    for kind in ("cv", "letter"):
        for export_format in ("docx", "pdf"):
            download = client.get(f"/api/career/application-drafts/{draft_id}/download/{kind}/{export_format}")
            assert download.status_code == 200
            assert download.headers["cache-control"] == "no-store"

    texts_error = client.patch(
        f"/api/career/applications/{application_id}/kit", json={"motivation_short": "x" * 1_301}
    )
    # L'app minimale laisse pydantic répondre 422 ; l'app réelle transforme
    # la même validation en 400. Dans les deux cas la requête est refusée.
    assert texts_error.status_code in (400, 422)
    events = service.get_application(application_id)["events"]
    assert [event["event_type"] for event in events].count("application_created") == 1


# --- 9. Preuve statique : aucune route d'envoi, schéma inchangé ---------------


def _route_paths() -> list[str]:
    source = (career_path := Path(__file__).resolve().parents[1] / "career" / "router.py").read_text(
        encoding="utf-8"
    )
    del career_path
    return re.findall(r'@router\.(?:get|post|patch|put|delete)\("([^"]+)"', source)


def test_no_submission_or_email_route_exists() -> None:
    """Preuve statique : aucune route n'envoie de courriel ni de candidature.

    Seule exception assumée (SPEC-047) : le préfixe ``/api/career/send-confirmation``
    enregistre la *déclaration* d'un envoi que la personne a déjà effectué
    elle-même — il ne transmet rien (ni courriel, ni candidature, ni relance ;
    la relance reste un brouillon local à copier).
    """
    paths = _route_paths()
    forbidden = re.compile(r"send|mail|smtp|transmit|auto-submit|autosubmit|autoapp")
    declared_send_prefix = "/api/career/send-confirmation"
    offending = [
        path
        for path in paths
        if forbidden.search(path.lower()) and not path.lower().startswith(declared_send_prefix)
    ]
    assert offending == [], f"routes d'envoi interdites détectées : {offending}"
    # SPEC-047 : « send » n'apparaît que sur les routes de déclaration d'un
    # envoi manuel déjà fait — liste fermée, aucune route d'envoi réel.
    declared_send_routes = sorted(path for path in paths if path.startswith(declared_send_prefix))
    assert declared_send_routes == sorted(
        [
            "/api/career/send-confirmation/{job_id}",
            "/api/career/send-confirmation/{job_id}",
            "/api/career/send-confirmation/{job_id}/followup",
        ]
    ), f"routes de confirmation inattendues : {declared_send_routes}"
    assert "/api/career/application-kits" in paths
    assert not any(path.endswith("/submit") for path in paths)

    service_source = Path(__file__).resolve().parents[1].joinpath("career", "service.py").read_text(
        encoding="utf-8"
    )
    for forbidden_import in ("smtplib", "import requests", "urllib.request", "http.client"):
        assert forbidden_import not in service_source, forbidden_import

    js_source = (Path(__file__).resolve().parents[1] / "career_static" / "career.js").read_text(
        encoding="utf-8"
    )
    assert "mailto:" not in js_source, "aucun lien courriel latéral n'est fabriqué côté client"


def test_application_events_schema_is_unchanged_and_drafts_store_variant() -> None:
    """Les textes restent événementiels ; seule la variante enrichit le brouillon."""
    source = Path(__file__).resolve().parents[1].joinpath("career", "service.py").read_text(encoding="utf-8")
    applications_match = re.search(r"CREATE TABLE applications \((.*?)\);", source, flags=re.DOTALL)
    events_match = re.search(r"CREATE TABLE application_events \((.*?)\);", source, flags=re.DOTALL)
    drafts_match = re.search(r"CREATE TABLE application_drafts \((.*?)\);", source, flags=re.DOTALL)
    assert applications_match and events_match and drafts_match
    assert sorted(re.findall(r"(\w+) TEXT", applications_match.group(1))) == sorted(
        ["id", "job_id", "stage", "receipt_status", "confirmation_reference", "created_at", "updated_at"]
    )
    assert sorted(re.findall(r"(\w+) TEXT", events_match.group(1))) == sorted(
        ["id", "application_id", "job_id", "event_type", "detail", "created_at"]
    )
    assert sorted(re.findall(r"(\w+) TEXT", drafts_match.group(1))) == sorted(
        ["id", "job_id", "language", "variant", "generation_mode", "provider", "cv_markdown", "letter_markdown",
         "checks_json", "quality_json", "profile_updated_at", "job_updated_at", "created_at"]
    )


# --- 10. Copie presse-papiers : clic uniquement, repli documenté --------------


def test_kit_clipboard_copy_is_click_only_with_fallback() -> None:
    source = (Path(__file__).resolve().parents[1] / "career_static" / "career.js").read_text(encoding="utf-8")
    # Méthode principale : API clipboard standard
    assert "navigator.clipboard" in source
    assert "writeText" in source
    # Repli légitime : document.execCommand("copy") UNIQUEMENT en fallback
    # quand navigator.clipboard n'est pas disponible ou échoue
    exec_lines = [line for line in source.splitlines() if "document.execCommand" in line]
    assert exec_lines, "repli document.execCommand attendu pour compatibilité"
    for line in exec_lines:
        # Le fallback doit être dans un bloc try/except ou conditionnel sur l'absence de clipboard API
        context = source[max(0, source.index(line)-200):source.index(line)+200]
        assert ("navigator.clipboard" in context or "try" in context.lower()), (
            "document.execCommand doit être un repli conditionnel, pas la méthode principale"
        )
    body = source.split("function copyKitValue", 1)[1].split("\nfunction kitFactRow", 1)[0]
    assert "writeText" in body, "la copie presse-papiers utilise l'API standard"
    assert "sélectionne le texte" in body, "un repli manuel doit être proposé si la copie échoue"
    assert 'addEventListener("click"' not in body, "la fonction ne branche pas elle-même ses appels"
    attach_lines = [line for line in source.splitlines() if "copyKitValue(" in line]
    click_attached = [line for line in attach_lines if "addEventListener" in line]
    assert click_attached, "kitFactRow doit brancher copyKitValue sur un clic utilisateur"


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : comportement presse-papiers non exécutable sur cet hôte")


def test_copy_kit_value_behaviour_in_node() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "career_static" / "career.js").read_text(encoding="utf-8")
    body = source.split("function copyKitValue", 1)[1].split("\nfunction kitFactRow", 1)[0]
    script = """
const assert = require("assert");
function makeCopy(clipboardStub) {
  const factory = new Function(
    "clipboardStub",
    "const navigator = { clipboard: clipboardStub };\\nfunction copyKitValue" + BODY_TEXT + "\\nreturn copyKitValue;"
  );
  return factory(clipboardStub);
}
(async () => {
  // 1 : clipboard indisponible (CSP ou navigateur) -> repli manuel explicite
  const unavailable = makeCopy(undefined);
  const statusUnavailable = { textContent: "" };
  unavailable("REF-DEMO", statusUnavailable);
  assert.match(statusUnavailable.textContent, /Copie indisponible/);
  assert.match(statusUnavailable.textContent, /sélectionne le texte/);
  // 2 : clipboard disponible -> confirmation après résolution de la promesse
  const copied = makeCopy({ writeText: () => Promise.resolve() });
  const statusCopied = { textContent: "" };
  copied("REF-DEMO", statusCopied);
  assert.equal(statusCopied.textContent, "");
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(statusCopied.textContent, "Copié.");
  // 3 : refus du navigateur -> repli manuel, aucune exception levée
  const refused = makeCopy({ writeText: () => Promise.reject(new Error("refus")) });
  const statusRefused = { textContent: "" };
  refused("REF-DEMO", statusRefused);
  await Promise.resolve();
  await Promise.resolve();
  assert.match(statusRefused.textContent, /Copie refusée/);
  assert.match(statusRefused.textContent, /sélectionne le texte/);
  // 4 : valeur vide -> signal explicite, aucune écriture presse-papiers
  let wrote = false;
  const empty = makeCopy({ writeText: () => { wrote = true; return Promise.resolve(); } });
  const statusEmpty = { textContent: "" };
  empty("", statusEmpty);
  assert.match(statusEmpty.textContent, /Rien à copier/);
  assert.equal(wrote, false);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    completed = subprocess.run(
        [_node(), "-e", script.replace("BODY_TEXT", json.dumps(body))],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr
