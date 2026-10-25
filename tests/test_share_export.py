"""SPEC-030 — partage lecture seule : bundle ZIP et projection redacted.

Toutes les données de ce module de test sont synthétiques.  Aucune archive
n'est envoyée : le test vérifie au contraire qu'aucune valeur privée ne sort
du workspace dans la vue JSON, le manifeste ou les documents.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from career.service import CareerService
from career.share_export import (
    APPLICATION_SHARE_FIELDS,
    JOB_SHARE_FIELDS,
    MANIFEST_NAME,
    MAX_FILE_BYTES,
    PROFILE_SHARE_FIELDS,
    README_NAME,
    REDACTION_PLACEHOLDER,
    SHARE_BUNDLE_VERSION,
    build_bundle,
    bundle_checksums,
    bundle_filename,
    is_private_field,
    redact,
    scrub_text,
    verify_bundle,
)
from come_ai_web import create_app
from workspace_core import UserFacingError

FIXTURE = Path(__file__).parent / "fixtures" / "share_synthetic.json"
MOMENT = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)

PRIVATE_PROFILE_VALUES = (
    "camille.exemple@example.invalid",
    "+33 6 00 00 00 00",
    "https://www.linkedin.com/in/camille-exemple",
    "Note personnelle privée : ne jamais partager.",
)


def synthetic_data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def synthetic_bundle(**changes: Any):
    data = synthetic_data()
    payload: dict[str, Any] = {
        "offer_id": data["offer_id"],
        "job": data["job"],
        "profile": data["profile"],
        "application": data["application"],
        "sensitive_values": PRIVATE_PROFILE_VALUES,
        "generated_at": MOMENT,
    }
    payload.update(changes)
    return build_bundle(**payload)


def manual_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Banque Synthétique",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/synthetic-42",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-12-15",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": "Excel modelling.\nEnglish fluency.",
        "description_original": "Stage de quatre mois.",
    }
    payload.update(changes)
    return payload


def prepared_service(tmp_path: Path) -> tuple[CareerService, dict[str, Any]]:
    service = CareerService(tmp_path)
    service.update_profile(
        {
            "display_name": "Camille Exemple",
            "contact_email": "camille.exemple@example.invalid",
            "contact_phone": "+33 6 00 00 00 00",
            "linkedin_url": "https://www.linkedin.com/in/camille-exemple",
            "education": "Master Finance — Université Synthétique",
            "experience": "Stage analyse financière — Banque Fictive",
            "skills": "Modélisation Excel, Python",
            "languages": "Français, anglais",
            "notes": "SECRET-NOTE-030 ne jamais partager",
            "target_companies": "Banque Fictive",
        }
    )
    job = service.import_job(manual_job())
    return service, job


def client_for(tmp_path: Path, service: CareerService) -> TestClient:
    return TestClient(create_app(tmp_path, agent_override=object(), career_override=service))


def archive_payloads(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def filename_from(response: Any) -> str:
    disposition = response.headers["content-disposition"]
    return disposition.split('filename="', 1)[1].rstrip('"')


# ---------------------------------------------------------------------------
# Projection en liste blanche
# ---------------------------------------------------------------------------

def test_curated_allow_lists_never_trip_the_private_name_guard() -> None:
    for field in PROFILE_SHARE_FIELDS + JOB_SHARE_FIELDS + APPLICATION_SHARE_FIELDS:
        assert not is_private_field(field), field


def test_redact_keeps_allowlisted_public_fields_and_reports_omissions() -> None:
    data = synthetic_data()
    view = redact(data["profile"], PROFILE_SHARE_FIELDS)

    assert set(view.fields) == {"display_name", "education", "experience", "skills", "languages"}
    assert view.fields["display_name"] == "Camille Exemple"
    assert "contact_email" in view.redacted
    assert "contact_phone" in view.redacted
    assert "notes" in view.redacted
    assert "readiness" in view.redacted
    assert view.redacted == sorted(view.redacted)


def test_redact_private_guard_overrides_a_mistaken_allowlist() -> None:
    record = {
        "display_name": "Camille Exemple",
        "contact_email": "camille@example.invalid",
        "contactEmail": "camille@example.invalid",
        "personal_note": "privé",
        "approval_granted": True,
        "confirmation_reference": "REF-PRIVEE",
        "session_token": "abc",
        "linkedin_url": "https://example.invalid/in/x",
    }
    # Adversarial: the caller explicitly asks for private names.
    view = redact(record, record.keys())

    assert view.fields == {"display_name": "Camille Exemple"}
    assert "contact_email" in view.redacted
    assert "contactEmail" in view.redacted
    assert "personal_note" in view.redacted
    assert "approval_granted" in view.redacted
    assert "confirmation_reference" in view.redacted
    assert "session_token" in view.redacted


def test_redact_drops_nested_data_and_non_finite_numbers() -> None:
    record = {
        "company": "Banque Synthétique",
        "application": {"contact_email": "nested@example.invalid", "stage": "interview"},
        "scoring": {"score": 88},
        "duration_months": float("nan"),
        "languages_required": ["Français", "anglais"],
    }
    view = redact(record, ["company", "application", "scoring", "duration_months", "languages_required"])

    assert view.fields == {"company": "Banque Synthétique", "languages_required": ["Français", "anglais"]}
    assert {"application", "scoring", "duration_months"} <= set(view.redacted)


def test_redact_strips_control_characters_and_truncates_text() -> None:
    view = redact({"company": "Banque\x00\x07 Synthétique"}, ["company"])
    assert view.fields["company"] == "Banque Synthétique"

    long_view = redact({"requirements": "a" * 50}, ["requirements"], text_limit=10)
    assert long_view.fields["requirements"] == "a" * 10


# ---------------------------------------------------------------------------
# Bundle et manifeste
# ---------------------------------------------------------------------------

def test_build_bundle_is_deterministic_and_manifest_matches_checksums() -> None:
    first = synthetic_bundle()
    second = synthetic_bundle()

    assert first.zip_bytes() == second.zip_bytes()
    assert first.manifest == second.manifest
    assert first.manifest["version"] == SHARE_BUNDLE_VERSION
    assert first.manifest["offer_id"] == "job_synthetic_share_030"
    assert first.manifest["generated_at"] == "2026-10-25T12:00:00Z"
    assert first.manifest["read_only"] is True
    assert first.manifest["checksums"] == bundle_checksums(first.files)
    assert set(first.manifest["checksums"]) == set(first.files)
    assert verify_bundle(first) is True


def test_manifest_never_repeats_private_names_or_values() -> None:
    bundle = synthetic_bundle()
    manifest = json.dumps(bundle.manifest, ensure_ascii=False)

    # Adversarial: even the *names* of private fields must stay local.  The
    # exported manifest only reports how many fields were omitted per entity.
    for name in (
        "contact_email",
        "contact_phone",
        "linkedin_url",
        "notes",
        "readiness",
        "personal_note",
        "scoring",
        "approval_granted",
        "confirmation_reference",
        "checklist_json",
        "events",
    ):
        assert name not in manifest
    assert "redacted" not in bundle.manifest
    assert bundle.manifest["redacted_counts"] == {"application": 9, "job": 7, "profile": 10}

    for value in (*PRIVATE_PROFILE_VALUES, "REF-PRIVEE-030", "Note privée de suivi."):
        assert value not in manifest

    # The structured views do not contain the private fields either.
    offer = json.loads(bundle.files["offre.json"])
    profile = json.loads(bundle.files["profil.json"])
    application = json.loads(bundle.files["candidature.json"])
    assert "personal_note" not in offer and "scoring" not in offer
    assert "contact_email" not in profile and "notes" not in profile
    assert set(application) == set(APPLICATION_SHARE_FIELDS)


def test_bundle_zip_is_ordered_private_and_inert() -> None:
    bundle = synthetic_bundle()
    payload = bundle.zip_bytes()

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        infos = archive.infolist()
        assert names[0] == MANIFEST_NAME
        assert names[1:] == sorted(names[1:])
        assert README_NAME in names
        for info in infos:
            assert (info.external_attr >> 16) == 0o600
            assert info.create_system == 3
        assert json.loads(archive.read(MANIFEST_NAME)) == bundle.manifest
        for name in names:
            assert not archive.read(name).startswith(b"PK\x03\x04")


def test_documents_are_masked_with_known_private_values() -> None:
    bundle = synthetic_bundle(
        documents={
            "cv.md": "# CV\nÉcrire à camille.exemple@example.invalid ou +33 6 00 00 00 00.",
            "lettre.md": "Note personnelle privée : ne jamais partager.",
            "annexe.txt": b"Contact : camille.exemple@example.invalid",
        }
    )
    cv = bundle.files["cv.md"].decode("utf-8")
    letter = bundle.files["lettre.md"].decode("utf-8")
    annex = bundle.files["annexe.txt"].decode("utf-8")

    assert REDACTION_PLACEHOLDER in cv
    assert "camille.exemple@example.invalid" not in cv
    assert "+33 6 00 00 00 00" not in cv
    assert "Note personnelle privée" not in letter
    assert "camille.exemple@example.invalid" not in annex
    assert bundle.manifest["documents_scrubbed"] is True


def test_binary_documents_are_refused_instead_of_shared_verbatim() -> None:
    with pytest.raises(ValueError):
        synthetic_bundle(documents={"cv.bin": b"%PDF-1.7\xff\xfe binary"})


def test_scrub_text_is_case_insensitive_and_ignores_short_noise() -> None:
    scrubbed = scrub_text("Contact: CAMILLE@EXAMPLE.INVALID — id 12.", ["Camille@Example.Invalid", "12", "x"])
    assert "CAMILLE@EXAMPLE.INVALID" not in scrubbed
    assert REDACTION_PLACEHOLDER in scrubbed
    assert "id 12." in scrubbed


@pytest.mark.parametrize(
    "name",
    ["../evil.md", "docs/cv.md", "..\\evil.md", "/etc/passwd", "CV.MD", "manifest.json", "lisez-moi.txt", ""],
)
def test_build_bundle_rejects_unsafe_document_names(name: str) -> None:
    with pytest.raises(ValueError):
        synthetic_bundle(documents={name: "contenu"})


def test_build_bundle_rejects_oversize_and_missing_offer() -> None:
    with pytest.raises(ValueError):
        synthetic_bundle(documents={"cv.md": "a" * (MAX_FILE_BYTES + 1)})
    with pytest.raises(ValueError):
        synthetic_bundle(job={})
    with pytest.raises(ValueError):
        synthetic_bundle(offer_id="")


def test_verify_bundle_detects_tampering() -> None:
    bundle = synthetic_bundle()
    assert verify_bundle(bundle) is True

    bundle.files["offre.json"] = b"{}\n"
    assert verify_bundle(bundle) is False

    clean = synthetic_bundle()
    clean.manifest["checksums"]["offre.json"] = "0" * 64
    assert verify_bundle(clean) is False


def test_bundle_filename_is_opaque_and_filesystem_safe() -> None:
    name = bundle_filename("../../etc/passwd", MOMENT)

    assert Path(name).name == name
    assert name.startswith("career_partage_")
    assert name.endswith(".zip")
    assert "/" not in name and ".." not in name
    assert bundle_filename("job_1", MOMENT) != bundle_filename("job_1", MOMENT, nonce="ab12cd34")


# ---------------------------------------------------------------------------
# Service et REST
# ---------------------------------------------------------------------------

def test_share_view_service_exposes_only_public_fields(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    service.create_application(job["id"])

    view = service.share_view(job["id"])

    assert view["schema"] == "career-share-view/1"
    assert view["read_only"] is True
    assert view["offer_id"] == job["id"]
    assert set(view["profile"]["fields"]) == {"display_name", "education", "experience", "skills", "languages"}
    assert "contact_email" in view["profile"]["redacted"]
    assert "notes" in view["profile"]["redacted"]
    assert view["job"]["fields"]["company"] == "Banque Synthétique"
    assert "personal_note" in view["job"]["redacted"]
    assert "scoring" in view["job"]["redacted"]
    assert set(view["application"]["fields"]) == set(APPLICATION_SHARE_FIELDS)
    assert "approval_granted" in view["application"]["redacted"]
    assert "events" in view["application"]["redacted"]


def test_share_bundle_rest_smoke_and_audit_trace(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    client = client_for(tmp_path, service)

    view_response = client.get(f"/api/career/jobs/{job['id']}/share-view")
    assert view_response.status_code == 200
    assert "contact_email" not in json.dumps(view_response.json()["profile"]["fields"])

    response = client.post(f"/api/career/jobs/{job['id']}/share-bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    filename = filename_from(response)
    assert filename.startswith("career_partage_") and filename.endswith(".zip")

    payloads = archive_payloads(response.content)
    assert MANIFEST_NAME in payloads and "offre.json" in payloads and "profil.json" in payloads
    combined = b"\n".join(payloads.values()).decode("utf-8")
    for value in (*PRIVATE_PROFILE_VALUES, "SECRET-NOTE-030", "REF-PRIVEE-030"):
        assert value not in combined

    manifest = json.loads(payloads[MANIFEST_NAME])
    assert manifest["offer_id"] == job["id"]
    assert manifest["checksums"]["offre.json"] == bundle_checksums(
        {name: payload for name, payload in payloads.items() if name != MANIFEST_NAME}
    )["offre.json"]

    trace = client.get("/api/career/share-exports")
    assert trace.status_code == 200
    entries = trace.json()["share_exports"]
    assert any(entry["filename"] == filename for entry in entries)


def test_share_bundle_rest_masks_contact_details_in_draft_documents(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    service.create_application_draft(job["id"], "fr")
    client = client_for(tmp_path, service)

    response = client.post(f"/api/career/jobs/{job['id']}/share-bundle")
    assert response.status_code == 200
    payloads = archive_payloads(response.content)

    assert "cv.md" in payloads and "lettre.md" in payloads
    combined = b"\n".join(payloads.values()).decode("utf-8")
    for value in PRIVATE_PROFILE_VALUES:
        assert value not in combined
    assert REDACTION_PLACEHOLDER in combined
    assert json.loads(payloads[MANIFEST_NAME])["documents_scrubbed"] is True


def test_share_endpoints_reject_unknown_and_unsafe_offers(tmp_path: Path) -> None:
    service, _job = prepared_service(tmp_path)
    client = client_for(tmp_path, service)

    assert client.get("/api/career/jobs/job_inconnu_030/share-view").status_code == 400
    assert client.post("/api/career/jobs/job_inconnu_030/share-bundle").status_code == 400
    assert client.post("/api/career/jobs/..%2F..%2Fetc%2Fpasswd/share-bundle").status_code in {400, 404}


def test_service_export_rejects_an_empty_offer_id(tmp_path: Path) -> None:
    service = CareerService(tmp_path)

    with pytest.raises(UserFacingError):
        service.export_share_bundle("")
