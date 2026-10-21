"""SK-10 — profil candidat avec preuves approuvées.

Règles centrales testées ici :

1. un fait extrait n'est jamais approuvé automatiquement (OCR compris) ;
2. chaque fait garde sa source exacte (page, offsets, citation) ;
3. un fait non approuvé ne peut jamais justifier une correspondance ni une
   candidature ;
4. la suppression et l'export fonctionnent (profil portable) ;
5. les tests n'utilisent que des fixtures synthétiques : aucun document réel.

Aucun réseau, aucun modèle, aucune candidature envoyée.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.candidate_profile import (
    FACT_STATUSES,
    STATUS_APPROVED,
    STATUS_MODIFIED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_SUSPENDED,
    USABLE_STATUSES,
    CandidateProfile,
    Evidence,
    Fact,
    apply_decision,
    export_profile,
    fact_line,
    merge_usable_facts,
    serialize_fact,
)
from career.profile_builder import build_fact_proposals, page_spans
from career.service import DELETE_CONFIRMATION, CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "candidate_profile"
CV_SYNTHETIQUE = (FIXTURES / "cv_synthetique.txt").read_text(encoding="utf-8")
CV_OCR_SYNTHETIQUE = (FIXTURES / "cv_ocr_synthetique.txt").read_text(encoding="utf-8")


# ── Helpers ─────────────────────────────────────────────────────────────────


def fact_of(**changes: object) -> Fact:
    base = {
        "id": "fact_test",
        "kind": "skill",
        "label": "Excel",
        "value": "",
        "status": STATUS_PROPOSED,
        "evidence": Evidence(source="embedded_text", page=1, page_confidence="exact", start_offset=0, end_offset=5, quote="Excel"),
    }
    base.update(changes)
    return Fact(**base)  # type: ignore[arg-type]


def service_with_profile(tmp_path: Path) -> CareerService:
    service = CareerService(tmp_path)
    service.update_profile(
        {
            "display_name": "Camille Exemple",
            "contact_email": "camille.exemple@example.test",
            "education": "Master 1 Finance",
            "experience": "Stage fictif en contrôle de gestion.",
            "skills": "Excel",
            "languages": "français",
        }
    )
    return service


def synthetic_job(service: CareerService) -> dict:
    return service.import_job(
        {
            "company": "Banque Synthetique",
            "title": "Stagiaire Analyse Financiere",
            "requirements": "Excel est requis pour ce poste.",
            "languages_required": "Anglais",
            "description_original": "Stage de six mois.",
        }
    )


def skills_section(draft: dict) -> str:
    text = draft["cv_markdown"]
    start = text.find("## Compétences")
    if start < 0:
        return ""
    end = text.find("##", start + 3)
    return text[start : end if end > 0 else len(text)]


# ── 1. Modèle et statuts ────────────────────────────────────────────────────


def test_five_statuses_are_declared_and_only_two_are_usable():
    assert set(FACT_STATUSES) == {
        STATUS_PROPOSED,
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_MODIFIED,
        STATUS_SUSPENDED,
    }
    assert USABLE_STATUSES == {STATUS_APPROVED, STATUS_MODIFIED}


def test_apply_decision_covers_every_status():
    approved = apply_decision(fact_of(), "approve", now="2026-10-21T10:00:00Z")
    assert approved.status == STATUS_APPROVED
    assert approved.is_usable
    assert approved.decided_at == "2026-10-21T10:00:00Z"

    rejected = apply_decision(fact_of(), "reject")
    assert rejected.status == STATUS_REJECTED
    assert not rejected.is_usable

    suspended = apply_decision(fact_of(), "suspend")
    assert suspended.status == STATUS_SUSPENDED
    assert not suspended.is_usable

    reopened = apply_decision(fact_of(status=STATUS_REJECTED), "reopen")
    assert reopened.status == STATUS_PROPOSED
    assert reopened.decided_at == ""


def test_modification_keeps_the_original_value_and_requires_a_value():
    modified = apply_decision(fact_of(), "modify", value="Excel avancé")
    assert modified.status == STATUS_MODIFIED
    assert modified.label == "Excel avancé"
    assert modified.original_label == "Excel"
    assert modified.is_usable
    with pytest.raises(ValueError):
        apply_decision(fact_of(), "modify", value="   ")
    with pytest.raises(ValueError):
        apply_decision(fact_of(), "approuver")


def test_only_the_person_can_decide_a_fact():
    with pytest.raises(ValueError):
        apply_decision(fact_of(), "approve", actor="system")


def test_the_review_state_machine_is_explicit():
    reopened = apply_decision(fact_of(status=STATUS_REJECTED), "reopen")
    assert reopened.status == STATUS_PROPOSED
    with pytest.raises(ValueError):
        apply_decision(fact_of(status=STATUS_REJECTED), "approve")
    assert apply_decision(fact_of(status=STATUS_APPROVED), "suspend").status == STATUS_SUSPENDED


def test_language_correction_keeps_the_language_and_corrects_the_level():
    language = fact_of(kind="language", label="Anglais", value="C1")
    corrected = apply_decision(language, "modify", value="B2")
    assert corrected.label == "Anglais"
    assert corrected.value == "B2"
    assert corrected.original_value == "C1"


def test_profile_counts_and_serialization_are_stable():
    profile = CandidateProfile(
        facts=(
            fact_of(id="a"),
            fact_of(id="b", status=STATUS_APPROVED),
            fact_of(id="c", status=STATUS_REJECTED),
        )
    )
    counts = profile.counts()
    assert counts[STATUS_PROPOSED] == 1
    assert counts[STATUS_APPROVED] == 1
    assert counts[STATUS_REJECTED] == 1
    assert len(profile.usable_facts()) == 1
    assert len(profile.pending_facts()) == 1
    payload = serialize_fact(profile.facts[0])
    assert payload["status"] == STATUS_PROPOSED
    assert payload["usable"] is False
    assert payload["requires_review"] is True
    assert payload["evidence"]["quote"] == "Excel"


def test_only_approved_facts_reach_the_profile_fields():
    profile = {
        "skills": "Excel",
        "experience": "",
        "education": "",
        "languages": "",
    }
    facts = (
        fact_of(id="a", label="Power BI", status=STATUS_PROPOSED),
        fact_of(id="b", label="SQL", status=STATUS_APPROVED),
        fact_of(id="c", label="VBA", status=STATUS_REJECTED),
        fact_of(id="d", label="SAS", status=STATUS_SUSPENDED),
    )
    merged = merge_usable_facts(profile, facts)
    assert merged["skills"] == "Excel\nSQL"
    assert "Power BI" not in merged["skills"]
    assert "VBA" not in merged["skills"]
    assert "SAS" not in merged["skills"]


def test_fact_line_renders_an_experience_like_a_profile_line():
    experience = fact_of(
        kind="experience",
        label="Analyste financier",
        meta={"company": "Groupe Synthetique", "dates": "2023 – 2025", "result": "20% de gain"},
    )
    assert fact_line(experience) == "2023 – 2025 | Analyste financier | Groupe Synthetique — 20% de gain"


def test_export_is_portable_and_keeps_the_evidence():
    profile = CandidateProfile(facts=(fact_of(id="a", status=STATUS_APPROVED), fact_of(id="b")))
    payload = export_profile(profile, generated_at="2026-10-21T10:00:00Z")
    assert payload["schema"] == "come-ai-candidate-profile/1"
    assert len(payload["facts"]) == 2
    assert payload["facts"][0]["evidence"]["quote"] == "Excel"
    assert payload["active_profile"]["skills"] == ["Excel"]
    assert "approuvés" in payload["disclaimer"]


# ── 2. Construction des propositions ───────────────────────────────────────


def test_builder_proposes_skills_experiences_education_and_languages():
    facts = build_fact_proposals(CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    kinds = {fact.kind for fact in facts}
    assert {"skill", "experience", "education", "language"} <= kinds
    labels = {fact.label for fact in facts}
    assert {"Excel", "Power BI", "SQL"} <= labels
    assert "Analyste financier" in labels
    assert "2021-2023 | Master Finance d'entreprise | Universite Synthetique" in labels
    languages = {fact.label: fact.value for fact in facts if fact.kind == "language"}
    assert languages["Anglais"] == "C1"
    assert languages["Francais"] == "natif"


def test_builder_never_approves_anything_even_for_ocr():
    for source in (CV_SYNTHETIQUE, CV_OCR_SYNTHETIQUE):
        facts = build_fact_proposals(source, source_method="ocr")
        assert facts
        assert {fact.status for fact in facts} == {STATUS_PROPOSED}


def test_builder_keeps_the_exact_source_of_every_fact():
    facts = build_fact_proposals(CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    for fact in facts:
        evidence = fact.evidence
        excerpt = CV_SYNTHETIQUE[evidence.start_offset : evidence.end_offset]
        assert excerpt.strip(), fact.label
        assert evidence.quote.startswith(excerpt.strip()[:60])
        assert evidence.start_offset < evidence.end_offset
        assert evidence.page >= 1
        assert evidence.page_confidence in {"exact", "estimated"}


def test_builder_maps_offsets_to_the_right_page_when_pages_are_known():
    pages = ["Page une\nCompétences\nExcel", "Page deux\nLangues\nAnglais - C1"]
    facts = build_fact_proposals("\n\n".join(pages), pages=pages)
    by_label = {fact.label: fact for fact in facts}
    assert by_label["Excel"].evidence.page == 1
    assert by_label["Excel"].evidence.page_confidence == "exact"
    assert by_label["Anglais"].evidence.page == 2
    assert by_label["Anglais"].evidence.page_confidence == "exact"


def test_builder_ignores_a_section_title_as_a_fact():
    facts = build_fact_proposals(CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    labels = {fact.label for fact in facts}
    assert "COMPETENCES" not in labels
    assert "LANGUES" not in labels
    assert "FORMATION" not in labels


def test_page_spans_fall_back_to_one_block_without_page_information():
    spans = page_spans("une seule page", None, None)
    assert len(spans) == 1
    assert spans[0].page == 1
    assert spans[0].confidence == "estimated"


def test_the_synthetic_fixture_produces_exactly_the_expected_facts():
    """Golden file: the proposals of the synthetic CV never drift silently."""
    expected = json.loads((FIXTURES / "expected_facts.json").read_text(encoding="utf-8"))
    document = expected["documents"][0]
    text = (FIXTURES / document["fixture"]).read_text(encoding="utf-8")
    facts = build_fact_proposals(text, filename=document["fixture"])
    produced = [{"kind": fact.kind, "label": fact.label, "value": fact.value} for fact in facts]
    assert produced == document["expected_facts"]


# ── 3. Service local : propositions, décisions, suppression, export ─────────


def test_service_stores_every_proposal_as_proposed(tmp_path):
    service = CareerService(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    assert result["facts"]
    assert all(fact["status"] == STATUS_PROPOSED for fact in result["facts"])
    assert result["counts"][STATUS_PROPOSED] == len(result["facts"])
    assert result["source"]["from_ocr"] is False
    stored = service.list_candidate_facts()
    assert len(stored) == len(result["facts"])


def test_service_never_writes_an_approved_status_outside_a_decision():
    """The insertion hard-codes ``proposed``: approval needs a user action."""
    source = inspect.getsource(CareerService.build_candidate_facts)
    assert "'proposed'" in source
    assert "approved" not in source.split("INSERT INTO candidate_facts")[-1].split("VALUES")[0]


def test_service_decides_one_fact_at_a_time(tmp_path):
    service = CareerService(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    fact = result["facts"][0]
    updated = service.decide_candidate_fact(fact["id"], "approve")
    assert updated["fact"]["status"] == STATUS_APPROVED
    assert updated["fact"]["usable"] is True
    assert updated["counts"][STATUS_APPROVED] == 1
    with pytest.raises(UserFacingError):
        service.decide_candidate_fact("fact_inexistant", "approve")
    with pytest.raises(UserFacingError):
        service.decide_candidate_fact(fact["id"], "modify", value="")


def test_service_deletes_one_fact(tmp_path):
    service = CareerService(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    fact_id = result["facts"][0]["id"]
    service.delete_candidate_fact(fact_id)
    assert fact_id not in {fact["id"] for fact in service.list_candidate_facts()}
    with pytest.raises(UserFacingError):
        service.delete_candidate_fact(fact_id)


def test_service_exports_a_portable_profile(tmp_path):
    service = CareerService(tmp_path)
    service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    path = service.export_candidate_profile()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "come-ai-candidate-profile/1"
    assert payload["facts"]
    assert payload["facts"][0]["evidence"]["quote"]


def test_service_applies_only_approved_facts_to_the_profile(tmp_path):
    service = service_with_profile(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    proposed = [fact for fact in result["facts"] if fact["kind"] == "skill"][0]
    with pytest.raises(UserFacingError):
        service.apply_candidate_facts([proposed["id"]])
    service.decide_candidate_fact(proposed["id"], "approve")
    applied = service.apply_candidate_facts([proposed["id"]])
    assert applied["applied"] == 1
    assert proposed["label"] in applied["profile"]["skills"]


def test_facts_survive_a_restart_of_the_local_service(tmp_path):
    service = CareerService(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    service.decide_candidate_fact(result["facts"][0]["id"], "approve")
    reopened = CareerService(tmp_path)
    assert len(reopened.list_candidate_facts()) == len(result["facts"])
    assert reopened.candidate_fact_counts()[STATUS_APPROVED] == 1


# ── 4. Les faits non approuvés ne justifient aucune candidature ────────────


def test_a_proposed_fact_never_reaches_the_candidature_draft(tmp_path):
    service = service_with_profile(tmp_path)
    job = synthetic_job(service)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    skill = [fact for fact in result["facts"] if fact["label"] == "Power BI"][0]
    assert skill["status"] == STATUS_PROPOSED
    draft = service.create_application_draft(job["id"], "fr")
    assert "Power BI" not in skills_section(draft)


def test_an_approved_fact_reaches_the_candidature_draft(tmp_path):
    service = service_with_profile(tmp_path)
    job = synthetic_job(service)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    skill = [fact for fact in result["facts"] if fact["label"] == "Power BI"][0]
    service.decide_candidate_fact(skill["id"], "approve")
    draft = service.create_application_draft(job["id"], "fr")
    assert "Power BI" in skills_section(draft)


def test_a_suspended_or_rejected_fact_leaves_the_candidature_draft(tmp_path):
    service = service_with_profile(tmp_path)
    job = synthetic_job(service)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    skill = [fact for fact in result["facts"] if fact["label"] == "Power BI"][0]
    service.decide_candidate_fact(skill["id"], "approve")
    service.decide_candidate_fact(skill["id"], "suspend")
    draft = service.create_application_draft(job["id"], "fr")
    assert "Power BI" not in skills_section(draft)
    service.decide_candidate_fact(skill["id"], "reject")
    draft = service.create_application_draft(job["id"], "fr")
    assert "Power BI" not in skills_section(draft)


def test_the_active_profile_only_lists_the_usable_facts(tmp_path):
    service = CareerService(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    approved = [fact for fact in result["facts"] if fact["label"] == "SQL"][0]
    service.decide_candidate_fact(approved["id"], "approve")
    active = service.active_candidate_profile()
    assert [fact["label"] for fact in active["facts"]] == ["SQL"]
    assert active["pending_count"] >= 1
    assert active["active_profile"]["skills"] == ["SQL"]


def test_an_ocr_import_proposes_facts_without_approving_them(tmp_path):
    service = CareerService(tmp_path)
    imported = service._create_profile_import(
        source_kind="cv",
        original_name="cv-scanné-synthetique.pdf",
        stored_filename="",
        content_sha256="0" * 64,
        size_bytes=len(CV_OCR_SYNTHETIQUE),
        extracted_text=CV_OCR_SYNTHETIQUE,
        extraction_method="macos_vision",
        ocr_pages=2,
    )
    result = service.build_candidate_facts(import_id=imported["id"])
    assert result["facts"]
    assert result["source"]["from_ocr"] is True
    assert {fact["status"] for fact in result["facts"]} == {STATUS_PROPOSED}
    assert all(fact["from_ocr"] for fact in result["facts"])
    assert all(fact["requires_review"] for fact in result["facts"])


def test_the_local_reset_erases_the_facts(tmp_path):
    service = CareerService(tmp_path)
    service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    service.reset_personal_data(DELETE_CONFIRMATION)
    assert service.list_candidate_facts() == []
    assert service.candidate_fact_counts()[STATUS_PROPOSED] == 0


def test_migration_from_v8_keeps_the_existing_profile(tmp_path):
    service = CareerService(tmp_path)
    service.update_profile({"display_name": "Camille Exemple"})
    with sqlite3.connect(service.db_path) as connection:
        connection.execute("DROP TABLE candidate_facts")
        connection.execute("PRAGMA user_version = 8")
    reopened = CareerService(tmp_path)
    assert reopened.get_profile()["display_name"] == "Camille Exemple"
    assert reopened.candidate_fact_counts()[STATUS_PROPOSED] == 0
    result = reopened.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv.txt")
    assert result["facts"]


# ── 5. API HTTP ─────────────────────────────────────────────────────────────


def career_client(tmp_path: Path, service: CareerService) -> TestClient:
    return TestClient(create_app(tmp_path, agent_override=object(), career_override=service))


def test_http_proposals_decisions_and_deletion(tmp_path):
    service = CareerService(tmp_path)
    client = career_client(tmp_path, service)
    response = client.post(
        "/api/career/candidate-profile/proposals",
        json={"text": CV_SYNTHETIQUE, "filename": "cv_synthetique.txt"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["facts"]
    fact_id = payload["facts"][0]["id"]

    listed = client.get("/api/career/candidate-profile/facts").json()
    assert listed["counts"][STATUS_PROPOSED] == len(payload["facts"])

    decided = client.patch(
        f"/api/career/candidate-profile/facts/{fact_id}",
        json={"decision": "approve"},
    )
    assert decided.status_code == 200
    assert decided.json()["fact"]["status"] == STATUS_APPROVED

    deleted = client.delete(f"/api/career/candidate-profile/facts/{fact_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}


def test_http_export_returns_a_local_json_file(tmp_path):
    service = CareerService(tmp_path)
    client = career_client(tmp_path, service)
    client.post(
        "/api/career/candidate-profile/proposals",
        json={"text": CV_SYNTHETIQUE, "filename": "cv_synthetique.txt"},
    )
    response = client.get("/api/career/candidate-profile/export")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    payload = json.loads(response.content.decode("utf-8"))
    assert payload["schema"] == "come-ai-candidate-profile/1"


def test_http_health_reports_the_local_candidate_profile(tmp_path):
    service = CareerService(tmp_path)
    client = career_client(tmp_path, service)
    payload = client.get("/api/career/health").json()
    assert payload["candidate_profile"]["local_only"] is True
    assert payload["candidate_profile"]["ocr_auto_approved"] is False
    assert payload["candidate_profile"]["statuses"] == [
        "proposed",
        "approved",
        "rejected",
        "modified",
        "suspended",
    ]


# ── 6. Garde-fous de l'interface ────────────────────────────────────────────


def test_the_profile_panel_exposes_a_field_by_field_review():
    root = Path(__file__).resolve().parents[1]
    html = (root / "career_static" / "index.html").read_text(encoding="utf-8")
    script = (root / "career_static" / "js" / "profile-builder.js").read_text(encoding="utf-8")
    career_js = (root / "career_static" / "career.js").read_text(encoding="utf-8")
    for marker in (
        'id="candidate-profile-builder"',
        'id="candidate-facts-list"',
        'id="candidate-facts-import"',
        'id="candidate-facts-text"',
        'id="candidate-facts-apply"',
        'id="candidate-facts-export"',
        '/career-static/js/profile-builder.js',
    ):
        assert marker in html
    assert "careerProfileBuilder" in career_js
    assert "/api/career/candidate-profile/proposals" in script
    assert "/api/career/candidate-profile/facts/" in script
    # The panel never injects document content as HTML.
    assert "innerHTML" not in script
    assert "insertAdjacentHTML" not in script


def test_the_interface_states_that_nothing_is_approved_automatically():
    root = Path(__file__).resolve().parents[1]
    html = (root / "career_static" / "index.html").read_text(encoding="utf-8")
    assert "Rien n’est validé automatiquement" in html
    assert "ne peut pas justifier" in html


# ── 7. Essais utilisateur réels : script hors dépôt ────────────────────────


def test_the_manual_check_script_refuses_a_document_stored_in_the_repository():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "candidate_profile_manual_check.py"
    assert script.is_file()
    completed = subprocess.run(
        [sys.executable, str(script), str(FIXTURES / "cv_synthetique.txt")],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=root,
    )
    assert completed.returncode != 0
    assert "dans le dépôt" in completed.stdout + completed.stderr


def test_the_manual_check_script_reads_a_document_outside_the_repository(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "candidate_profile_manual_check.py"
    document = tmp_path / "cv-hors-depot.txt"
    document.write_text(CV_SYNTHETIQUE, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script), str(document)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=root,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Faits proposés" in completed.stdout
    assert "Aucun fait n'est approuvé" in completed.stdout
    assert "Excel" in completed.stdout
