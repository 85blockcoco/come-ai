"""Profil candidat avec preuves approuvées (SK-10).

Toutes les fixtures sont synthétiques : aucun vrai CV, aucune vraie
entreprise, aucune donnée personnelle.  Rien n'appelle le réseau.

Ce qui est vérifié :

* les cinq statuts de fait existent et leurs transitions sont encadrées ;
* le builder n'approuve jamais un fait, et signale les faits lus par OCR ;
* chaque fait garde sa source exacte (page, offsets, citation) ;
* les faits non approuvés n'entrent jamais dans le matching ni la candidature ;
* la suppression et l'export du profil fonctionnent ;
* l'interface d'approbation champ par champ est bien branchée.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.candidate_profile import (
    ALLOWED_TRANSITIONS,
    CANDIDATE_PROFILE_SCHEMA_VERSION,
    FACT_STATUSES,
    CandidateFact,
    CandidateProfile,
    FactProvenance,
    active_profile_fields,
    apply_review,
    can_transition,
    is_usable_status,
    usable_facts,
)
from career.cv_quality import extract_paged_text_from_bytes
from career.profile_builder import build_candidate_profile, build_fact_proposals
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "candidate_profile"
PROFILE_BUILDER_JS = ROOT / "career_static" / "js" / "profile-builder.js"
INDEX_HTML = ROOT / "career_static" / "index.html"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def load_cases() -> dict:
    return json.loads((FIXTURE_DIR / "synthetic_cases.json").read_text(encoding="utf-8"))


def fixture_document(case: dict) -> str:
    return (FIXTURE_DIR / case["file"]).read_text(encoding="utf-8")


def build_pdf(pages: list[list[str]]) -> bytes:
    """Build a small, valid, text-only PDF with one page per list of lines.

    The PDF is assembled byte by byte so the test needs no extra dependency
    and stays fully synthetic.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_number = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    content_numbers: list[int] = []
    for lines in pages:
        content = "BT /F1 12 Tf 72 720 Td 14 TL\n"
        for line in lines:
            escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            content += f"({escaped}) Tj T*\n"
        content += "ET\n"
        stream = content.encode("latin-1", "replace")
        content_numbers.append(
            add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        )
    page_numbers: list[int] = []
    for content_number in content_numbers:
        body = (
            f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_number} 0 R >> >> /Contents {content_number} 0 R >>"
        ).encode()
        page_numbers.append(add(body))
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    pages_number = add(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    catalog_number = add(f"<< /Type /Catalog /Pages {pages_number} 0 R >>".encode())

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_number} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_fact(**changes) -> CandidateFact:
    """Build one synthetic fact with a usable provenance."""
    values = {
        "id": "fact_demo",
        "kind": "skill",
        "label": "Excel",
        "value": "Excel",
        "status": "proposed",
        "provenance": FactProvenance(
            source_document="synthetic_cv.txt",
            source_kind="cv",
            extraction="text_layer",
            page=1,
            start_offset=10,
            end_offset=15,
            quote="Excel",
        ),
        "original_value": "Excel",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    values.update(changes)
    return CandidateFact(**values)


def career_client(service: CareerService) -> TestClient:
    """Minimal app with the same error contract as the real application."""
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Le modèle : cinq statuts, transitions, profil actif
# ─────────────────────────────────────────────────────────────────────────────


def test_the_five_documented_statuses_exist() -> None:
    assert FACT_STATUSES == ("proposed", "approved", "rejected", "modified", "suspended")
    assert is_usable_status("approved") is True
    assert is_usable_status("modified") is True
    assert is_usable_status("proposed") is False
    assert is_usable_status("rejected") is False
    assert is_usable_status("suspended") is False


def test_transitions_are_enclosed_by_the_documented_rules() -> None:
    assert can_transition("proposed", "approved") is True
    assert can_transition("approved", "modified") is True
    assert can_transition("rejected", "proposed") is True
    assert can_transition("suspended", "proposed") is True
    # A refusal cannot be turned into an approval without a new proposal.
    assert can_transition("rejected", "approved") is False
    assert set(ALLOWED_TRANSITIONS) == set(FACT_STATUSES)


def test_correcting_a_proposed_fact_keeps_it_proposed() -> None:
    """A correction is not an approval: the fact stays unusable."""
    fact = make_fact()
    reviewed = apply_review(fact, value="Excel avancé")
    assert reviewed.status == "proposed"
    assert reviewed.value == "Excel avancé"
    assert reviewed.original_value == "Excel"
    assert reviewed.corrected is True
    assert reviewed.usable is False


def test_correcting_an_approved_fact_keeps_it_usable_as_modified() -> None:
    fact = make_fact(status="approved")
    reviewed = apply_review(fact, value="Excel avancé")
    assert reviewed.status == "modified"
    assert reviewed.usable is True
    assert reviewed.original_value == "Excel"


def test_an_illegal_transition_is_refused() -> None:
    fact = make_fact(status="rejected")
    with pytest.raises(ValueError):
        apply_review(fact, status="approved")
    with pytest.raises(ValueError):
        apply_review(fact, status="unknown-status")


def test_only_approved_facts_feed_the_active_profile() -> None:
    facts = [
        make_fact(id="a", kind="skill", label="Excel", value="Excel", status="approved"),
        make_fact(id="b", kind="skill", label="Python", value="Python", status="proposed"),
        make_fact(id="c", kind="skill", label="SQL", value="SQL", status="rejected"),
        make_fact(id="d", kind="skill", label="R", value="R", status="suspended"),
        make_fact(id="e", kind="education", label="Master", value="Master Démo", status="modified"),
        make_fact(
            id="f",
            kind="contact",
            label="email",
            value="demo@example.test",
            status="approved",
        ),
    ]
    active = active_profile_fields(facts)
    assert active["skills"] == "Excel"
    assert active["education"] == "Master Démo"
    assert active["contact_email"] == "demo@example.test"
    assert [fact.id for fact in usable_facts(facts)] == ["a", "e", "f"]


def test_the_profile_serialises_and_reloads_without_loss() -> None:
    profile = CandidateProfile(
        facts=(make_fact(),),
        source_document="synthetic_cv.txt",
        source_kind="cv",
        extraction="text_layer",
        page_count=2,
        created_at="2026-01-01T00:00:00Z",
    )
    restored = CandidateProfile.from_dict(profile.to_dict())
    assert restored.to_dict() == profile.to_dict()
    assert restored.schema_version == CANDIDATE_PROFILE_SCHEMA_VERSION
    assert restored.facts[0].provenance.page == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. Le builder : extraction locale, provenance exacte, aucune approbation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", load_cases()["documents"], ids=lambda case: case["file"])
def test_builder_reads_the_expected_facts_from_each_synthetic_cv(case: dict) -> None:
    document = extract_paged_text_from_bytes(
        fixture_document(case).encode("utf-8"), "txt", case["file"]
    )
    facts = build_fact_proposals(document, source_kind=case["source_kind"])
    counts: dict[str, int] = {}
    for fact in facts:
        counts[fact.kind] = counts.get(fact.kind, 0) + 1
    assert counts == case["expected_kinds"]
    assert [fact.value for fact in facts if fact.kind == "skill"] == case["expected_skills"]
    assert [fact.value for fact in facts if fact.kind == "language"] == case["expected_language_values"]
    assert [
        fact.label for fact in facts if fact.kind == "experience"
    ] == case["expected_experience_labels"]
    assert [
        fact.label for fact in facts if fact.kind == "education"
    ] == case["expected_education_labels"]


@pytest.mark.parametrize("case", load_cases()["documents"], ids=lambda case: case["file"])
def test_every_fact_keeps_an_exact_provenance(case: dict) -> None:
    text = fixture_document(case)
    document = extract_paged_text_from_bytes(text.encode("utf-8"), "txt", case["file"])
    facts = build_fact_proposals(document, source_kind=case["source_kind"])
    assert facts
    for fact in facts:
        passage = text[fact.start_offset : fact.end_offset]
        assert passage.strip(), "le passage cité ne peut pas être vide"
        assert fact.quote.startswith(passage.strip()[:20]) or passage.strip().startswith(
            fact.quote[:20]
        ), "la citation doit être le passage exact"
        assert fact.page == document.page_for_offset(fact.start_offset)


def test_the_builder_never_approves_a_fact() -> None:
    document = extract_paged_text_from_bytes(
        fixture_document(load_cases()["documents"][0]).encode("utf-8"), "txt", "cv.txt"
    )
    profile = build_candidate_profile(document, source_kind="cv", created_at="2026-01-01T00:00:00Z")
    assert profile.facts
    assert {fact.status for fact in profile.facts} == {"proposed"}
    assert profile.usable_facts == ()


def test_ocr_facts_are_flagged_for_review_and_capped_in_confidence() -> None:
    document = extract_paged_text_from_bytes(
        fixture_document(load_cases()["documents"][0]).encode("utf-8"), "txt", "cv.txt"
    )
    ocr_document = type(document)(
        text=document.text,
        pages=document.pages,
        filename=document.filename,
        filetype=document.filetype,
        page_count=document.page_count,
        extraction="ocr",
    )
    profile = build_candidate_profile(ocr_document, source_kind="cv", created_at="2026-01-01T00:00:00Z")
    assert profile.facts
    assert all(fact.requires_review is True for fact in profile.facts)
    assert all(fact.status == "proposed" for fact in profile.facts)
    assert all(fact.confidence <= 0.4 for fact in profile.facts)


def test_a_two_page_pdf_gives_the_exact_page_of_each_fact() -> None:
    pdf = build_pdf(
        [
            ["Camille Demo", "camille.demo@example.test", "", "SKILLS", "Excel, Python"],
            [
                "EXPERIENCE",
                "2020 - 2023 | Analyste | Example Bank",
                "",
                "EDUCATION",
                "2019 - 2022 | Licence | Example University",
            ],
        ]
    )
    document = extract_paged_text_from_bytes(pdf, "pdf", "synthetic.pdf")
    assert document.page_count == 2
    assert len(document.pages) == 2
    facts = build_fact_proposals(document, source_kind="cv")
    by_kind = {fact.kind: fact for fact in facts}
    assert by_kind["skill"].page == 1
    assert by_kind["experience"].page == 2
    assert by_kind["education"].page == 2
    for fact in facts:
        assert document.text[fact.start_offset : fact.end_offset].strip()
        assert fact.page == document.page_for_offset(fact.start_offset)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Le service : persistance, revue, suppression, export
# ─────────────────────────────────────────────────────────────────────────────


def test_the_service_persists_the_profile_and_its_facts(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    text = fixture_document(load_cases()["documents"][0])
    profile = service.build_candidate_profile_from_text(
        source_kind="cv", text=text, original_name="synthetic_cv_fr.txt"
    )
    assert profile["total"] > 0
    assert profile["counts"]["proposed"] == profile["total"]
    assert profile["usable"] == 0

    reopened = CareerService(tmp_path)
    stored = reopened.get_candidate_profile()
    assert stored["total"] == profile["total"]
    assert stored["document"]["source_document"] == "synthetic_cv_fr.txt"
    assert stored["document"]["extraction"] == "text_layer"
    assert stored["facts"][0]["provenance"]["quote"]


def test_the_service_applies_one_review_at_a_time(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    profile = service.get_candidate_profile()
    skill = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    reviewed = service.review_candidate_fact(skill["id"], status="approved")
    assert reviewed["counts"]["approved"] == 1
    assert reviewed["usable"] == 1
    assert reviewed["active_profile"]["skills"] == skill["value"]

    refused = service.review_candidate_fact(skill["id"], status="rejected")
    assert refused["counts"]["rejected"] == 1
    assert refused["usable"] == 0
    assert refused["active_profile"]["skills"] == ""

    with pytest.raises(UserFacingError):
        service.review_candidate_fact(skill["id"], status="approved")


def test_a_corrected_fact_keeps_its_extracted_value(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    profile = service.get_candidate_profile()
    skill = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    service.review_candidate_fact(skill["id"], status="approved")
    corrected = service.review_candidate_fact(skill["id"], value="Excel (niveau avancé)")
    fact = next(item for item in corrected["facts"] if item["id"] == skill["id"])
    assert fact["status"] == "modified"
    assert fact["value"] == "Excel (niveau avancé)"
    assert fact["original_value"] == skill["value"]
    assert fact["usable"] is True


def test_the_service_deletes_one_fact_and_the_whole_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    profile = service.get_candidate_profile()
    fact_id = profile["facts"][0]["id"]
    after_fact = service.delete_candidate_fact(fact_id)
    assert after_fact["total"] == profile["total"] - 1
    assert all(item["id"] != fact_id for item in after_fact["facts"])

    after_profile = service.delete_candidate_profile()
    assert after_profile["profile"]["total"] == 0
    assert after_profile["profile"]["document"] == {}
    assert CareerService(tmp_path).get_candidate_profile()["total"] == 0


def test_the_service_exports_a_portable_json_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    path = service.export_candidate_profile()
    assert path.is_file()
    assert path.suffix == ".json"
    exported = json.loads(path.read_text(encoding="utf-8"))
    assert exported["facts"]
    assert exported["facts"][0]["provenance"]["quote"]
    assert exported["document"]["source_document"] == "synthetic_cv_fr.txt"


def test_rebuilding_from_the_same_document_keeps_the_reviews(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    text = fixture_document(load_cases()["documents"][0])
    service.build_candidate_profile_from_text(
        source_kind="cv", text=text, original_name="synthetic_cv_fr.txt"
    )
    profile = service.get_candidate_profile()
    skill = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    service.review_candidate_fact(skill["id"], status="approved")
    rebuilt = service.build_candidate_profile_from_text(
        source_kind="cv", text=text, original_name="synthetic_cv_fr.txt"
    )
    assert rebuilt["counts"]["approved"] == 1
    assert rebuilt["usable"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Les faits non approuvés n'entrent jamais dans le matching
# ─────────────────────────────────────────────────────────────────────────────


def test_unapproved_facts_are_excluded_from_the_matching_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile({"skills": "Excel", "education": "Master Démo"})
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    profile = service.get_candidate_profile()
    skills = [fact for fact in profile["facts"] if fact["kind"] == "skill"]
    approved = skills[0]
    pending = skills[1]

    service.review_candidate_fact(approved["id"], status="approved")
    matching = service.get_matching_profile()
    assert approved["value"] in matching["skills"]
    assert pending["value"] not in matching["skills"]
    assert len(service.get_active_candidate_profile()["skills"].split(", ")) == 1


def test_a_refused_fact_never_justifies_an_application(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    profile = service.get_candidate_profile()
    for fact in profile["facts"]:
        if fact["kind"] == "skill":
            service.review_candidate_fact(fact["id"], status="rejected")
    matching = service.get_matching_profile()
    assert matching["skills"] == ""
    assert service.get_active_candidate_profile()["skills"] == ""


def test_a_typed_profile_still_works_without_any_candidate_profile(tmp_path: Path) -> None:
    """Building no candidate profile must not change the existing behaviour."""
    service = CareerService(tmp_path)
    service.update_profile({"skills": "Excel", "education": "Master Démo"})
    matching = service.get_matching_profile()
    assert matching["skills"] == "Excel"
    assert matching["education"] == "Master Démo"


def test_an_application_draft_only_repeats_the_approved_facts(tmp_path: Path) -> None:
    """The generated CV is the strongest place to check the SK-10 rule."""
    service = CareerService(tmp_path)
    job = service.import_job(
        {
            "company": "Banque Démo",
            "title": "Stagiaire M&A",
            # The offer deliberately names no skill, so the only trace of a
            # skill in the draft can come from the candidate profile.
            "requirements": "Analyse de transactions et modélisation financière.",
            "description_original": "Mission de démonstration, données synthétiques.",
        }
    )
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    profile = service.get_candidate_profile()
    # Sorted by value: the fact order in the database follows the identifier,
    # which is random by design.
    skills = sorted(
        (fact for fact in profile["facts"] if fact["kind"] == "skill"),
        key=lambda fact: fact["value"],
    )
    approved, pending = skills[0], skills[1]
    service.review_candidate_fact(approved["id"], status="approved")

    draft = service.create_application_draft(job["id"], "fr")
    assert approved["value"] in draft["cv_markdown"]
    assert pending["value"] not in draft["cv_markdown"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Les endpoints
# ─────────────────────────────────────────────────────────────────────────────


def test_the_router_builds_reviews_and_exports_the_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = career_client(service)
    response = client.post(
        "/api/career/candidate-profile/text",
        json={
            "source_kind": "cv",
            "text": fixture_document(load_cases()["documents"][0]),
            "original_name": "synthetic_cv_fr.txt",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["total"] > 0
    assert payload["usable"] == 0

    fact_id = payload["facts"][0]["id"]
    reviewed = client.patch(
        f"/api/career/candidate-profile/facts/{fact_id}", json={"status": "approved"}
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["counts"]["approved"] == 1

    exported = client.get("/api/career/candidate-profile/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/json")
    assert json.loads(exported.content)["facts"]

    deleted = client.delete(f"/api/career/candidate-profile/facts/{fact_id}")
    assert deleted.status_code == 200
    assert deleted.json()["total"] == payload["total"] - 1

    removed = client.delete("/api/career/candidate-profile")
    assert removed.status_code == 200
    assert removed.json()["profile"]["total"] == 0


def test_the_router_refuses_an_unknown_fact_or_status(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = career_client(service)
    response = client.patch(
        "/api/career/candidate-profile/facts/fact_missing", json={"status": "approved"}
    )
    assert response.status_code == 400
    assert "n’existe pas" in response.json()["detail"]

    client.post(
        "/api/career/candidate-profile/text",
        json={
            "source_kind": "cv",
            "text": fixture_document(load_cases()["documents"][0]),
            "original_name": "synthetic_cv_fr.txt",
        },
    )
    fact_id = client.get("/api/career/candidate-profile").json()["facts"][0]["id"]
    refused = client.patch(
        f"/api/career/candidate-profile/facts/{fact_id}", json={"status": "invented"}
    )
    assert refused.status_code == 400


def test_the_router_builds_a_profile_from_an_uploaded_document(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = career_client(service)
    text = fixture_document(load_cases()["documents"][0])
    response = client.post(
        "/api/career/candidate-profile/document",
        files={"document": ("synthetic_cv_fr.txt", text.encode("utf-8"), "text/plain")},
        data={"source_kind": "cv"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["total"] > 0
    assert payload["document"]["source_document"] == "synthetic_cv_fr.txt"
    assert payload["facts"][0]["provenance"]["start_offset"] >= 0


def test_the_router_never_leaves_a_fact_approved_after_a_build(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = career_client(service)
    client.post(
        "/api/career/candidate-profile/text",
        json={
            "source_kind": "cv",
            "text": fixture_document(load_cases()["documents"][0]),
            "original_name": "synthetic_cv_fr.txt",
        },
    )
    payload = client.get("/api/career/candidate-profile").json()
    assert payload["counts"]["approved"] == 0
    assert payload["usable"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Confidentialité : export et suppression globales
# ─────────────────────────────────────────────────────────────────────────────


def test_the_privacy_export_carries_the_candidate_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    path = service.export_personal_data()
    exported = json.loads(path.read_text(encoding="utf-8"))
    assert exported["candidate_profile"]["facts"]
    assert exported["candidate_profile"]["facts"][0]["provenance"]["quote"]


def test_the_global_reset_removes_the_candidate_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_from_text(
        source_kind="cv",
        text=fixture_document(load_cases()["documents"][0]),
        original_name="synthetic_cv_fr.txt",
    )
    service.reset_personal_data("SUPPRIMER MES DONNÉES CAREER")
    assert service.get_candidate_profile()["total"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 7. L'interface d'approbation champ par champ
# ─────────────────────────────────────────────────────────────────────────────


def test_the_profile_builder_javascript_is_safe_by_construction() -> None:
    source = PROFILE_BUILDER_JS.read_text(encoding="utf-8")
    assert "window.prompt" not in source
    assert "innerHTML" not in source
    assert "eval(" not in source
    assert "/api/career/candidate-profile" in source
    assert "approved" in source and "rejected" in source and "suspended" in source
    # Shadowing the global ``document`` would break every render call.
    assert "const document" not in source
    assert "let document" not in source


def test_the_profile_panel_is_present_in_the_career_page() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "/career-static/js/profile-builder.js" in html
    assert 'id="candidate-profile-facts"' in html
    assert 'id="candidate-profile-file"' in html
    assert 'id="candidate-profile-export"' in html
    assert 'id="candidate-profile-delete"' in html


def test_the_application_serves_the_profile_builder_script(tmp_path: Path) -> None:
    """The script lives in a subfolder: the static mount must serve it."""
    from come_ai_web import create_app

    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.get("/career-static/js/profile-builder.js")
    assert response.status_code == 200
    assert "pbReviewFact" in response.text
    page = client.get("/career")
    assert page.status_code == 200
    assert "/career-static/js/profile-builder.js" in page.text


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent: JavaScript behavioural guards not executable on this host")


def _run_node_script(script: str) -> None:
    handle = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False)
    handle.write(script)
    handle.close()
    try:
        completed = subprocess.run([_node(), handle.name], text=True, capture_output=True, timeout=20)
        assert completed.returncode == 0, completed.stderr
    finally:
        os.unlink(handle.name)


_JS_PRELUDE = r'''
const assert = require("assert");
class ClassStub {
  constructor(tag = "div") { this.tagName = String(tag).toUpperCase(); this.children = []; this.attributes = {}; this.dataset = {}; this.className = ""; this.style = {}; this.hidden = false; this.value = ""; this.type = ""; this.maxLength = 0; this.rows = 0; this.placeholder = ""; this.files = []; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
  setAttribute(name, value) { this.attributes[name] = value; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  remove() {}
  focus() {}
}
function domStub(tag = "div") { return new ClassStub(tag); }
const registry = {};
globalThis.document = {
  readyState: "complete",
  createElement: (tag) => domStub(tag),
  querySelector: (selector) => registry[selector] || null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};
globalThis.window = { location: { assign: () => {} } };
globalThis.fetch = async () => ({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => ({}) });
'''


def test_the_javascript_renders_one_card_per_fact_with_its_provenance() -> None:
    script = _JS_PRELUDE + PROFILE_BUILDER_JS.read_text(encoding="utf-8") + r'''
const payload = {
  total: 2,
  usable: 0,
  counts: { proposed: 2, approved: 0, rejected: 0, modified: 0, suspended: 0 },
  document: { source_document: "synthetic_cv.txt", warnings: [] },
  facts: [
    { id: "f1", kind: "skill", label: "Excel", value: "Excel", status: "proposed", requires_review: false, corrected: false, original_value: "Excel", provenance: { page: 2, start_offset: 40, end_offset: 45, quote: "Excel", extraction: "text_layer" } },
    { id: "f2", kind: "experience", label: "Analyste", value: "Analyste M&A", status: "approved", requires_review: true, corrected: false, original_value: "Analyste M&A", provenance: { page: 1, start_offset: 10, end_offset: 22, quote: "Analyste M&A", extraction: "ocr" } },
  ],
};
const container = domStub("div");
registry["#candidate-profile-facts"] = container;
registry["#candidate-profile-summary"] = domStub("div");
registry["#candidate-profile-empty"] = domStub("p");
pbRenderFacts(payload);
assert.strictEqual(container.children.length, 2, "un groupe par type de fait");
const skillGroup = container.children[0];
assert.strictEqual(skillGroup.children.length, 2, "un titre puis une carte par fait");
const card = skillGroup.children[1];
assert.strictEqual(card.dataset.status, "proposed");
assert.strictEqual(card.dataset.factId, "f1");
const texts = [];
(function collect(node) {
  if (typeof node.textContent === "string" && node.textContent) texts.push(node.textContent);
  (node.children || []).forEach(collect);
})(card);
assert.ok(texts.some((value) => value.includes("Page 2")), "la page doit être affichée");
assert.ok(texts.some((value) => value.includes("caractères 40–45")), "les offsets doivent être affichés");
assert.ok(texts.some((value) => value.includes("Excel")), "la citation doit être affichée");
'''
    _run_node_script(script)


def test_the_javascript_shows_the_active_profile_and_its_empty_state() -> None:
    script = _JS_PRELUDE + PROFILE_BUILDER_JS.read_text(encoding="utf-8") + r'''
const summary = domStub("div");
registry["#candidate-profile-summary"] = summary;
registry["#candidate-profile-facts"] = domStub("div");
registry["#candidate-profile-empty"] = domStub("p");
function collect(node, into) {
  if (typeof node.textContent === "string" && node.textContent) into.push(node.textContent);
  (node.children || []).forEach((child) => collect(child, into));
}
pbRenderSummary({
  total: 1,
  counts: { proposed: 1, approved: 0, rejected: 0, modified: 0, suspended: 0 },
  document: { source_document: "synthetic_cv.txt", warnings: [] },
  active_profile: { skills: "Excel", education: "", experience: "", languages: "" },
});
const texts = [];
collect(summary, texts);
assert.ok(texts.some((value) => value.includes("Excel")), "le profil actif doit être affiché");
assert.ok(texts.some((value) => value.includes("uniquement les faits approuvés")), "la règle doit être rappelée");
pbRenderSummary({
  total: 1,
  counts: { proposed: 1, approved: 0, rejected: 0, modified: 0, suspended: 0 },
  document: {},
  active_profile: {},
});
const emptyTexts = [];
collect(summary, emptyTexts);
assert.ok(emptyTexts.some((value) => value.includes("profil actif est vide")), "un profil sans fait doit être signalé");
'''
    _run_node_script(script)


def test_the_javascript_calls_the_review_and_delete_endpoints() -> None:
    script = _JS_PRELUDE + PROFILE_BUILDER_JS.read_text(encoding="utf-8") + r'''
const calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url, method: options.method || "GET", body: options.body || "" });
  return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => ({ total: 0, facts: [], counts: {}, document: {} }) };
};
registry["#candidate-profile-facts"] = domStub("div");
registry["#candidate-profile-summary"] = domStub("div");
registry["#candidate-profile-empty"] = domStub("p");
(async () => {
  await pbReviewFact("fact_1", { status: "approved" });
  await pbDeleteFact("fact_2");
  assert.strictEqual(calls[0].url, "/api/career/candidate-profile/facts/fact_1");
  assert.strictEqual(calls[0].method, "PATCH");
  assert.ok(calls[0].body.includes("approved"), "le statut doit être transmis");
  assert.strictEqual(calls[1].url, "/api/career/candidate-profile/facts/fact_2");
  assert.strictEqual(calls[1].method, "DELETE");
})().catch((error) => { console.error(error); process.exit(1); });
'''
    _run_node_script(script)


def test_the_javascript_never_approves_a_fact_on_its_own() -> None:
    """The interface may only ask; the approval always comes from a click."""
    source = PROFILE_BUILDER_JS.read_text(encoding="utf-8")
    assert "status: \"approved\"" in source
    # L'approbation n'est jamais envoyée sans une action explicite de la personne.
    assert source.count("pbReviewFact(fact.id, { status: \"approved\" })") == 1
    assert "pbReviewFact(payload" not in source
