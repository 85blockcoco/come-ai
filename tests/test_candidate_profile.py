"""Tests for the structured candidate profile (SK-10).

Every fixture is synthetic: fictional names, ``example.org`` addresses and
fictional companies.  No real CV is stored in the repository and no test
reaches the network.

The tests cover the three guarantees of the feature:

* a machine may only *propose* a fact — an OCR result in particular is never
  approved automatically;
* every fact keeps the source it was read from (page, offsets, quote);
* only facts validated by the person may justify a candidacy.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.candidate_profile import (
    ALLOWED_FACT_TRANSITIONS,
    EXTRACTION_METHOD_OCR,
    FACT_STATUS_APPROVED,
    FACT_STATUS_MODIFIED,
    FACT_STATUS_PROPOSED,
    FACT_STATUS_REJECTED,
    FACT_STATUS_SUSPENDED,
    FACT_STATUSES,
    CandidateProfile,
    ProfileRuleError,
    build_fact,
    decide_fact,
    merge_facts,
    validate_profile,
)
from career.ocr import OCRResult
from career.profile_builder import (
    build_source_pages,
    page_for_offset,
    propose_profile_facts,
)
from career.service import CareerService, DELETE_CONFIRMATION
from come_ai_web import create_app
from workspace_core import UserFacingError


FIXTURES = Path(__file__).parent / "fixtures" / "candidate_profile"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeAgent:
    def provider_status(self) -> dict[str, object]:
        return {
            "gemini": {"configured": False, "primary_model": "fake", "fallback_models": []},
            "ollama": {"configured": False, "model": None},
            "request_timeout_seconds": 30,
            "retry_attempts": 1,
        }

    def ask(self, message: str, *, allow_writes: bool) -> dict[str, object]:
        return {"answer": "sans appel fournisseur", "tool_events": [], "provider": "Faux modèle"}


def fact_by_kind(facts: list, kind: str, *, contains: str = "") -> object:
    for fact in facts:
        if fact.kind != kind:
            continue
        if contains and contains not in fact.value:
            continue
        return fact
    raise AssertionError(f"Aucun fait « {kind} » contenant « {contains} » n’a été proposé.")


# ──────────────────────────────────────────────────────────────────────
# Model: statuses, transitions, invariants
# ──────────────────────────────────────────────────────────────────────


def test_the_five_statuses_are_defined_and_labelled() -> None:
    assert FACT_STATUSES == (
        "proposed",
        "approved",
        "rejected",
        "modified",
        "suspended",
    )
    assert set(ALLOWED_FACT_TRANSITIONS) == set(FACT_STATUSES)
    for status in FACT_STATUSES:
        assert ALLOWED_FACT_TRANSITIONS[status]


def test_a_fact_starts_as_a_proposal_and_can_never_be_self_approved() -> None:
    fact = build_fact(fact_id="fact_1", kind="skill", label="Python", value="Python")
    assert fact.status == FACT_STATUS_PROPOSED
    assert fact.is_usable is False
    assert fact.decided_at == ""


def test_approving_a_fact_records_the_human_decision() -> None:
    fact = build_fact(fact_id="fact_1", kind="skill", label="Python", value="Python")
    approved = decide_fact(fact, decision=FACT_STATUS_APPROVED, decided_at="2026-10-21T10:00:00")
    assert approved.status == FACT_STATUS_APPROVED
    assert approved.decided_at == "2026-10-21T10:00:00"
    assert approved.is_usable is True


def test_an_illegal_transition_is_refused() -> None:
    fact = build_fact(
        fact_id="fact_1",
        kind="skill",
        label="Python",
        value="Python",
        status=FACT_STATUS_APPROVED,
        decided_at="2026-10-21T10:00:00",
    )
    with pytest.raises(ProfileRuleError):
        decide_fact(fact, decision=FACT_STATUS_PROPOSED, decided_at="2026-10-21T10:05:00")


def test_cancelling_a_fact_keeps_its_value_and_source() -> None:
    fact = build_fact(fact_id="fact_1", kind="skill", label="Python", value="Python")
    suspended = decide_fact(fact, decision=FACT_STATUS_SUSPENDED, decided_at="2026-10-21T10:00:00")
    assert suspended.status == FACT_STATUS_SUSPENDED
    assert suspended.value == "Python"
    assert suspended.is_usable is False


def test_a_correction_keeps_the_machine_value_for_the_audit() -> None:
    fact = build_fact(fact_id="fact_1", kind="skill", label="Anglais", value="Anglais - Cl")
    corrected = decide_fact(
        fact,
        decision=FACT_STATUS_MODIFIED,
        value="Anglais - C1",
        decided_at="2026-10-21T10:00:00",
    )
    assert corrected.status == FACT_STATUS_MODIFIED
    assert corrected.value == "Anglais - C1"
    assert corrected.original_value == "Anglais - Cl"
    assert corrected.is_usable is True


def test_a_correction_without_a_value_is_refused() -> None:
    fact = build_fact(fact_id="fact_1", kind="skill", label="Anglais", value="Anglais - Cl")
    with pytest.raises(ProfileRuleError):
        decide_fact(fact, decision=FACT_STATUS_MODIFIED, value="   ")


def test_a_profile_with_an_approval_without_a_decision_is_reported() -> None:
    forged = build_fact(
        fact_id="fact_1",
        kind="skill",
        label="Python",
        value="Python",
        status=FACT_STATUS_APPROVED,
    )
    profile = CandidateProfile(facts=(forged,))
    problems = validate_profile(profile)
    assert problems
    assert "décision humaine" in problems[0]


def test_a_validated_decision_without_a_date_is_refused() -> None:
    """An approval that carries no decision can never be recorded."""
    fact = build_fact(fact_id="fact_1", kind="skill", label="Python", value="Python")
    with pytest.raises(ProfileRuleError):
        decide_fact(fact, decision=FACT_STATUS_APPROVED)
    with pytest.raises(ProfileRuleError):
        decide_fact(fact, decision=FACT_STATUS_MODIFIED, value="Python")
    # A rejection needs no timestamp: it justifies nothing.
    rejected = decide_fact(fact, decision=FACT_STATUS_REJECTED)
    assert rejected.status == FACT_STATUS_REJECTED
    assert rejected.is_usable is False


def test_only_validated_facts_are_usable() -> None:
    proposal = build_fact(fact_id="fact_1", kind="skill", label="Python", value="Python")
    approved = decide_fact(
        proposal, decision=FACT_STATUS_APPROVED, decided_at="2026-10-21T10:00:00"
    )
    rejected = decide_fact(
        proposal, decision=FACT_STATUS_REJECTED, decided_at="2026-10-21T10:00:00"
    )
    suspended = decide_fact(
        proposal, decision=FACT_STATUS_SUSPENDED, decided_at="2026-10-21T10:00:00"
    )
    profile = CandidateProfile(facts=(proposal, approved, rejected, suspended))
    assert [fact.id for fact in profile.usable_facts] == [approved.id]
    assert profile.usable_summary()["skill"] == ["Python"]


def test_merging_proposals_never_overwrites_a_decided_fact() -> None:
    proposal = build_fact(fact_id="fact_1", kind="skill", label="Python", value="Python")
    approved = decide_fact(
        proposal, decision=FACT_STATUS_APPROVED, decided_at="2026-10-21T10:00:00"
    )
    again = build_fact(fact_id="fact_2", kind="skill", label="python", value="Python")
    other = build_fact(fact_id="fact_3", kind="skill", label="SQL", value="SQL")
    merged = merge_facts([approved], [again, other])
    assert [fact.id for fact in merged] == [approved.id, other.id]
    assert merged[0].status == FACT_STATUS_APPROVED


# ──────────────────────────────────────────────────────────────────────
# Builder: proposals and their provenance
# ──────────────────────────────────────────────────────────────────────


def test_every_proposal_keeps_the_exact_place_it_was_read_from() -> None:
    text = read_fixture("cv_synthetique.txt")
    facts = propose_profile_facts(text, source_name="cv_synthetique.txt")
    assert facts
    for fact in facts:
        assert fact.provenance is not None
        assert fact.provenance.quote
        assert fact.provenance.source_name == "cv_synthetique.txt"
        start = fact.provenance.start_offset
        end = fact.provenance.end_offset
        assert 0 <= start < end <= len(text)
        passage = text[start:end]
        assert passage.strip()
        assert fact.value.startswith(passage.strip()[:20]) or passage.strip() in fact.value


def test_the_proposals_read_the_sections_of_the_document() -> None:
    text = read_fixture("cv_synthetique.txt")
    facts = propose_profile_facts(text)
    skills = [fact.value for fact in facts if fact.kind == "skill"]
    assert "Python" in skills
    assert "Power BI" in skills
    languages = [fact.value for fact in facts if fact.kind == "language"]
    assert "Anglais - C1" in languages
    educations = [fact.value for fact in facts if fact.kind == "education"]
    assert any("Master Data Science" in value for value in educations)
    experiences = [fact.value for fact in facts if fact.kind == "experience"]
    assert len(experiences) == 2
    assert any("Banque Horizon" in value for value in experiences)


def test_a_section_heading_is_never_read_as_a_fact() -> None:
    text = read_fixture("cv_synthetique.txt")
    facts = propose_profile_facts(text)
    values = {fact.value for fact in facts}
    assert "COMPETENCES" not in values
    assert "EXPERIENCE" not in values
    assert "FORMATION" not in values


def test_an_english_document_is_read_too() -> None:
    facts = propose_profile_facts(read_fixture("cv_anglais_synthetique.txt"))
    assert "Python" in [fact.value for fact in facts if fact.kind == "skill"]
    assert "English - Native" in [fact.value for fact in facts if fact.kind == "language"]
    assert any(
        "Open source validation library" in fact.value for fact in facts if fact.kind == "project"
    )


def test_an_ocr_document_is_only_ever_proposed() -> None:
    facts = propose_profile_facts(
        read_fixture("cv_ocr_synthetique.txt"), extraction_method=EXTRACTION_METHOD_OCR
    )
    assert facts
    for fact in facts:
        assert fact.status == FACT_STATUS_PROPOSED
        assert fact.is_ocr is True
        assert fact.is_usable is False
        assert fact.decided_at == ""


def test_the_page_of_a_fact_follows_the_document() -> None:
    pages = ["Premiere page\nCompétences\nPython", "Seconde page\nExpérience\n2020 - Stage"]
    text = "\n\n".join(pages)
    facts = propose_profile_facts(text, pages=pages)
    spans = build_source_pages(text, pages)
    assert [span.page for span in spans] == [1, 2]
    python = fact_by_kind(facts, "skill", contains="Python")
    stage = fact_by_kind(facts, "experience", contains="Stage")
    assert python.provenance.page == 1
    assert stage.provenance.page == 2
    assert page_for_offset(spans, 0) == 1
    assert page_for_offset(spans, len(pages[0]) + 2) == 2


def test_the_offsets_point_at_the_quote_that_is_stored() -> None:
    text = read_fixture("cv_synthetique.txt")
    facts = propose_profile_facts(text)
    for fact in facts:
        passage = text[fact.provenance.start_offset : fact.provenance.end_offset]
        assert " ".join(passage.split()) == fact.provenance.quote


def test_a_document_without_any_section_proposes_nothing() -> None:
    assert propose_profile_facts("Une phrase sans rubrique utile.") == []

def test_the_pipeline_never_invents_a_status_other_than_proposed() -> None:
    facts = propose_profile_facts(read_fixture("cv_synthetique.txt"))
    assert {fact.status for fact in facts} == {FACT_STATUS_PROPOSED}


def test_the_extraction_matches_the_expected_facts() -> None:
    expected = json.loads((FIXTURES / "expected_facts.json").read_text(encoding="utf-8"))
    facts = propose_profile_facts(read_fixture(expected["source"]))
    for wanted in expected["facts"]:
        needle = wanted.get("contains") or wanted.get("value") or ""
        matches = [
            fact for fact in facts if fact.kind == wanted["kind"] and needle in fact.value
        ]
        assert matches, f"Fact attendu manquant : {wanted}"


def test_a_date_is_a_fact_of_its_own_with_its_own_source() -> None:
    text = read_fixture("cv_synthetique.txt")
    facts = propose_profile_facts(text)
    dates = [fact for fact in facts if fact.kind == "date"]
    assert [fact.value for fact in dates] == ["2021-2024", "2020", "2021", "2023"]
    for fact in dates:
        passage = text[fact.provenance.start_offset : fact.provenance.end_offset]
        assert passage == fact.value
        assert fact.status == FACT_STATUS_PROPOSED


def test_the_manual_check_script_refuses_a_file_stored_in_the_repository() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "candidate_profile_manual_check.py"
    assert script.is_file()
    source = script.read_text(encoding="utf-8")
    assert "_refuse_repository_files" in source
    assert "Ce fichier est dans le dépôt" in source
    # The script only reads and prints: it never decides anything.
    assert "decide_fact" not in source
    assert "approved" not in source


def test_the_manual_check_script_works_outside_the_repository(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "candidate_profile_manual_check.py"
    document = tmp_path / "cv-de-test.txt"
    document.write_text(read_fixture("cv_synthetique.txt"), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script), "--text-file", str(document)],
        text=True,
        capture_output=True,
        timeout=60,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert "proposition" in completed.stdout
    assert "Python" in completed.stdout
    assert "approuvée" in completed.stdout


# ──────────────────────────────────────────────────────────────────────
# Service: storage, decisions, deletion, export
# ──────────────────────────────────────────────────────────────────────


def test_proposals_are_stored_and_stay_awaiting_a_decision(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"),
        source_name="cv_synthetique.txt",
        source_kind="cv",
    )
    assert profile["facts"]
    assert profile["usable_for_matching"] is False
    assert profile["usable_facts"] == []
    assert profile["counts"]["proposed"] == len(profile["facts"])
    assert profile["usable"] == {
        "identity": [],
        "contact": [],
        "skill": [],
        "experience": [],
        "education": [],
        "language": [],
        "certification": [],
        "project": [],
        "date": [],
    }
    assert service.get_candidate_profile()["facts"] == profile["facts"]


def test_approving_a_fact_makes_it_usable_and_the_others_stay_out(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    updated = service.decide_candidate_fact(target["id"], decision=FACT_STATUS_APPROVED)
    assert updated["counts"][FACT_STATUS_APPROVED] == 1
    assert updated["usable_for_matching"] is True
    assert updated["usable"]["skill"] == [target["value"]]
    # The other proposals never justify anything.
    assert updated["usable"]["experience"] == []
    assert len(updated["usable_facts"]) == 1


def test_a_rejected_fact_never_reaches_the_matching_summary(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_APPROVED)
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_REJECTED)
    updated = service.get_candidate_profile()
    assert updated["usable_for_matching"] is False
    assert updated["usable"]["skill"] == []


def test_a_suspended_fact_never_reaches_the_matching_summary(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_APPROVED)
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_SUSPENDED)
    updated = service.get_candidate_profile()
    assert updated["usable_for_matching"] is False


def test_a_correction_keeps_the_machine_value_in_the_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = next(
        fact for fact in profile["facts"] if fact["kind"] == "language" and "Anglais" in fact["value"]
    )
    updated = service.decide_candidate_fact(
        target["id"], decision=FACT_STATUS_MODIFIED, value="Anglais - C2"
    )
    corrected = next(fact for fact in updated["facts"] if fact["id"] == target["id"])
    assert corrected["status"] == FACT_STATUS_MODIFIED
    assert corrected["value"] == "Anglais - C2"
    assert corrected["original_value"] == target["value"]
    assert corrected["decided_at"]
    assert updated["usable"]["language"] == ["Anglais - C2"]


def test_an_unknown_fact_is_refused(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    with pytest.raises(UserFacingError):
        service.decide_candidate_fact("fact_inconnu", decision=FACT_STATUS_APPROVED)
    with pytest.raises(UserFacingError):
        service.delete_candidate_fact("fact_inconnu")


def test_an_illegal_decision_is_refused(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = profile["facts"][0]
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_APPROVED)
    with pytest.raises(UserFacingError):
        service.decide_candidate_fact(target["id"], decision=FACT_STATUS_PROPOSED)


def test_a_fact_can_be_deleted_and_the_profile_can_be_deleted(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = profile["facts"][0]
    after = service.delete_candidate_fact(target["id"])
    assert target["id"] not in [fact["id"] for fact in after["facts"]]
    emptied = service.delete_candidate_profile()
    assert emptied["facts"] == []
    assert emptied["usable_for_matching"] is False


def test_the_profile_can_be_exported_as_a_portable_file(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_APPROVED)
    path = service.export_candidate_profile()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["profile"]["facts"]
    assert payload["usable"]["skill"] == [target["value"]]
    assert payload["exported_at"]
    assert path.exists()


def test_the_private_export_contains_the_structured_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    payload = json.loads(service.export_personal_data().read_text(encoding="utf-8"))
    assert payload["candidate_profile"]["facts"]


def test_deleting_the_career_data_removes_the_structured_profile(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    service.reset_personal_data(DELETE_CONFIRMATION)
    assert service.get_candidate_profile()["facts"] == []


def test_a_second_document_does_not_duplicate_an_approved_fact(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    first = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = next(fact for fact in first["facts"] if fact["kind"] == "skill")
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_APPROVED)
    second = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    assert len(second["facts"]) == len(first["facts"])
    assert second["counts"][FACT_STATUS_APPROVED] == 1


def test_an_empty_document_is_refused(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    with pytest.raises(UserFacingError):
        service.build_candidate_profile_proposals(text="   ")


def test_nothing_may_justify_a_candidature_before_a_fact_is_validated(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    with pytest.raises(UserFacingError):
        service.require_candidate_profile_evidence()
    target = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_APPROVED)
    evidence = service.require_candidate_profile_evidence()
    assert evidence["facts"][0]["value"] == target["value"]
    assert evidence["summary"]["skill"] == [target["value"]]


def test_a_local_document_is_stored_privately_and_proposes_facts(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    payload = read_fixture("cv_synthetique.txt").encode("utf-8")
    temporary = service.profile_upload_temp_path()
    temporary.write_bytes(payload)
    profile = service.build_candidate_profile_from_document(
        original_name="cv_synthetique.txt",
        temporary_path=temporary,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    assert profile["facts"]
    assert profile["has_local_file"] is True
    stored = list((tmp_path / "career_data" / "documents").glob("profile_candidat_*"))
    assert len(stored) == 1
    assert oct(stored[0].stat().st_mode)[-3:] == "600"
    service.delete_candidate_profile()
    assert not stored[0].exists()


def test_an_ocr_document_upload_is_only_ever_proposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = CareerService(tmp_path)
    ocr_text = read_fixture("cv_ocr_synthetique.txt")
    monkeypatch.setattr(
        service.ocr,
        "extract_pdf",
        lambda path, **kwargs: OCRResult(text=ocr_text, pages=1, truncated=False, warnings=["bruit"]),
    )
    # A PDF without a usable text layer falls back to the local OCR.
    payload = b"%PDF-1.4 synthetic"
    temporary = service.profile_upload_temp_path()
    temporary.write_bytes(payload)
    profile = service.build_candidate_profile_from_document(
        original_name="cv_scanné.pdf",
        temporary_path=temporary,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    assert profile["extraction_method"] == "ocr"
    assert profile["ocr_pages"] == 1
    assert profile["facts"]
    for fact in profile["facts"]:
        assert fact["status"] == FACT_STATUS_PROPOSED
        assert fact["is_ocr"] is True
        assert fact["decided_at"] == ""
    assert profile["usable_for_matching"] is False


def test_an_ocr_fact_keeps_the_page_it_was_read_from(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fact read by OCR still knows its page, like a fact read in the text."""
    service = CareerService(tmp_path)
    first_page = "COMPETENCES\nPython"
    second_page = "FORMATION\nMaster Démo"
    monkeypatch.setattr(
        service.ocr,
        "extract_pdf",
        lambda path, **kwargs: OCRResult(
            text=f"{first_page}\n\n{second_page}",
            pages=2,
            truncated=False,
            warnings=[],
            page_texts=(first_page, second_page),
        ),
    )
    payload = b"%PDF-1.4 synthetic"
    temporary = service.profile_upload_temp_path()
    temporary.write_bytes(payload)
    profile = service.build_candidate_profile_from_document(
        original_name="cv_scanné.pdf",
        temporary_path=temporary,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    assert profile["extraction_method"] == "ocr"
    pages = {fact["value"]: fact["provenance"]["page"] for fact in profile["facts"]}
    assert pages.get("Python") == 1
    assert pages.get("Master Démo") == 2



# ──────────────────────────────────────────────────────────────────────
# HTTP: the review endpoints
# ──────────────────────────────────────────────────────────────────────


def test_the_review_endpoints_work_end_to_end(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))

    health = client.get("/api/career/health")
    assert health.status_code == 200
    assert health.json()["candidate_profile"] == {
        "enabled": True,
        "local_only": True,
        "review_required": True,
        "automatic_approval": False,
    }

    created = client.post(
        "/api/career/candidate-profile/proposals",
        json={"text": read_fixture("cv_synthetique.txt"), "filename": "cv_synthetique.txt"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["facts"]
    assert body["usable_for_matching"] is False

    target = next(fact for fact in body["facts"] if fact["kind"] == "skill")
    decided = client.post(
        f"/api/career/candidate-profile/facts/{target['id']}/decision",
        json={"decision": "approved"},
    )
    assert decided.status_code == 200
    assert decided.json()["usable_for_matching"] is True

    exported = client.get("/api/career/candidate-profile/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/json")

    removed = client.delete(f"/api/career/candidate-profile/facts/{target['id']}")
    assert removed.status_code == 200
    assert client.get("/api/career/candidate-profile").json()["usable_for_matching"] is False

    emptied = client.delete("/api/career/candidate-profile")
    assert emptied.status_code == 200
    assert client.get("/api/career/candidate-profile").json()["facts"] == []


def test_the_active_profile_only_contains_the_validated_facts(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    created = client.post(
        "/api/career/candidate-profile/proposals",
        json={"text": read_fixture("cv_synthetique.txt")},
    )
    target = next(fact for fact in created.json()["facts"] if fact["kind"] == "skill")
    active = client.get("/api/career/candidate-profile/active").json()
    assert active["facts"] == []
    assert active["usable_for_matching"] is False
    client.post(
        f"/api/career/candidate-profile/facts/{target['id']}/decision",
        json={"decision": "approved"},
    )
    active = client.get("/api/career/candidate-profile/active").json()
    assert [fact["value"] for fact in active["facts"]] == [target["value"]]
    assert active["usable_for_matching"] is True


def test_the_document_endpoint_reads_a_local_file(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    response = client.post(
        "/api/career/candidate-profile/proposals/document",
        files={
            "document": (
                "cv_synthetique.txt",
                read_fixture("cv_synthetique.txt").encode("utf-8"),
                "text/plain",
            )
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["facts"]
    assert body["usable_for_matching"] is False
    assert body["has_local_file"] is True
    stored = list((tmp_path / "career_data" / "documents").glob("profile_candidat_*"))
    assert len(stored) == 1


def test_an_unknown_decision_is_refused_by_the_api(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    created = client.post(
        "/api/career/candidate-profile/proposals",
        json={"text": read_fixture("cv_synthetique.txt")},
    )
    target = created.json()["facts"][0]
    refused = client.post(
        f"/api/career/candidate-profile/facts/{target['id']}/decision",
        json={"decision": "auto-approve"},
    )
    assert refused.status_code == 422


def test_an_unknown_fact_is_refused_by_the_api(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    refused = client.post(
        "/api/career/candidate-profile/facts/fact_inconnu/decision",
        json={"decision": "approved"},
    )
    assert refused.status_code == 400


# ──────────────────────────────────────────────────────────────────────
# SK-10, criterion 5: a candidacy is justified by the validated facts only
#
# The strongest place to check the rule is the document the person actually
# sends: the CV draft.  A fact that is still a proposal, that was rejected or
# that was set aside must not appear in it.
# ──────────────────────────────────────────────────────────────────────


def _profile_with_skills(tmp_path: Path) -> tuple[CareerService, list[dict]]:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"),
        source_name="cv_synthetique.txt",
        source_kind="cv",
    )
    skills = sorted(
        (fact for fact in profile["facts"] if fact["kind"] == "skill"),
        key=lambda fact: fact["value"],
    )
    assert len(skills) >= 2, "La fixture doit proposer au moins deux compétences."
    return service, skills


def _demo_job(service: CareerService) -> dict:
    return service.import_job(
        {
            "company": "Banque Démo",
            "title": "Stagiaire M&A",
            "requirements": "Analyse de transactions et modélisation financière.",
            "description_original": "Mission de démonstration, données synthétiques.",
        }
    )


def test_an_unapproved_fact_never_reaches_the_application_draft(tmp_path: Path) -> None:
    service, skills = _profile_with_skills(tmp_path)
    job = _demo_job(service)
    approved, pending = skills[0], skills[1]
    service.decide_candidate_fact(approved["id"], decision=FACT_STATUS_APPROVED)

    draft = service.create_application_draft(job["id"], "fr")
    assert approved["value"] in draft["cv_markdown"]
    assert pending["value"] not in draft["cv_markdown"]


def test_a_rejected_fact_never_reaches_the_application_draft(tmp_path: Path) -> None:
    service, skills = _profile_with_skills(tmp_path)
    job = _demo_job(service)
    rejected = skills[0]
    service.decide_candidate_fact(rejected["id"], decision=FACT_STATUS_REJECTED)

    draft = service.create_application_draft(job["id"], "fr")
    assert rejected["value"] not in draft["cv_markdown"]


def test_a_suspended_fact_never_reaches_the_application_draft(tmp_path: Path) -> None:
    service, skills = _profile_with_skills(tmp_path)
    job = _demo_job(service)
    suspended = skills[0]
    service.decide_candidate_fact(suspended["id"], decision=FACT_STATUS_SUSPENDED)

    draft = service.create_application_draft(job["id"], "fr")
    assert suspended["value"] not in draft["cv_markdown"]


def test_a_validated_fact_reaches_the_application_draft(tmp_path: Path) -> None:
    service, skills = _profile_with_skills(tmp_path)
    job = _demo_job(service)
    approved = skills[0]
    service.decide_candidate_fact(approved["id"], decision=FACT_STATUS_APPROVED)

    draft = service.create_application_draft(job["id"], "fr")
    assert approved["value"] in draft["cv_markdown"]


def test_a_corrected_fact_reaches_the_application_draft(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    job = _demo_job(service)
    target = next(
        fact for fact in profile["facts"] if fact["kind"] == "language" and "Anglais" in fact["value"]
    )
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_MODIFIED, value="Anglais - C2")

    draft = service.create_application_draft(job["id"], "fr")
    assert "Anglais - C2" in draft["cv_markdown"]


def test_the_typed_profile_still_works_without_any_candidate_profile(tmp_path: Path) -> None:
    """Building no structured profile must not change the existing behaviour."""
    service = CareerService(tmp_path)
    service.update_profile({"skills": "Excel", "education": "Master Démo"})
    matching = service.get_matching_profile()
    assert matching["skills"] == "Excel"
    assert matching["education"] == "Master Démo"
    assert matching.get("candidate_profile_active") is None


def test_the_facts_survive_a_restart_of_the_local_service(tmp_path: Path) -> None:
    """A decision taken yesterday is still there after the app is closed."""
    service = CareerService(tmp_path)
    profile = service.build_candidate_profile_proposals(
        text=read_fixture("cv_synthetique.txt"), source_name="cv_synthetique.txt"
    )
    target = next(fact for fact in profile["facts"] if fact["kind"] == "skill")
    service.decide_candidate_fact(target["id"], decision=FACT_STATUS_APPROVED)

    restarted = CareerService(tmp_path)
    stored = restarted.get_candidate_profile()
    kept = next(fact for fact in stored["facts"] if fact["id"] == target["id"])
    assert kept["status"] == FACT_STATUS_APPROVED
    assert kept["decided_at"]
    assert restarted.get_active_candidate_profile()["profile_fields"]["skills"] == target["value"]


def test_the_matching_profile_carries_only_the_validated_facts(tmp_path: Path) -> None:
    service, skills = _profile_with_skills(tmp_path)
    service.update_profile({"skills": "Excel", "education": "Master Démo"})
    approved, pending = skills[0], skills[1]
    service.decide_candidate_fact(approved["id"], decision=FACT_STATUS_APPROVED)

    matching = service.get_matching_profile()
    assert matching["candidate_profile_active"] is True
    assert approved["value"] in matching["skills"]
    assert pending["value"] not in matching["skills"]
    # A field no validated fact covers keeps the value typed by hand.
    assert matching["education"] == "Master Démo"


def test_the_active_profile_exposes_the_projected_fields(tmp_path: Path) -> None:
    service, skills = _profile_with_skills(tmp_path)
    approved = skills[0]
    service.decide_candidate_fact(approved["id"], decision=FACT_STATUS_APPROVED)

    active = service.get_active_candidate_profile()
    assert active["profile_fields"]["skills"] == approved["value"]
    assert active["usable_for_matching"] is True


def test_the_api_never_justifies_a_candidature_without_a_decision(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    created = client.post(
        "/api/career/candidate-profile/proposals",
        json={"text": read_fixture("cv_synthetique.txt")},
    )
    assert created.status_code == 201
    active = client.get("/api/career/candidate-profile/active").json()
    assert active["facts"] == []
    assert active["usable_for_matching"] is False
    assert set(active["profile_fields"].values()) == {""}
    # The evidence contract refuses to justify anything.
    refused = client.get("/api/career/candidate-profile/evidence")
    assert refused.status_code == 400


def test_the_evidence_contract_serves_the_validated_facts(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    created = client.post(
        "/api/career/candidate-profile/proposals",
        json={"text": read_fixture("cv_synthetique.txt")},
    )
    target = next(
        fact for fact in created.json()["facts"] if fact["kind"] == "skill"
    )
    approved = client.post(
        f"/api/career/candidate-profile/facts/{target['id']}/decision",
        json={"decision": "approved"},
    )
    assert approved.status_code == 200
    evidence = client.get("/api/career/candidate-profile/evidence")
    assert evidence.status_code == 200
    payload = evidence.json()
    assert [fact["id"] for fact in payload["facts"]] == [target["id"]]
    assert target["value"] in payload["profile_fields"]["skills"]


# ──────────────────────────────────────────────────────────────────────
# Provenance: the offsets always describe exactly the passage that was quoted
# ──────────────────────────────────────────────────────────────────────


def test_the_quote_is_exactly_the_quoted_passage(tmp_path: Path) -> None:
    """A long passage is cut with its offsets, never with an ellipsis."""
    long_line = "Experience — " + ("mission détaillée " * 40)
    text = f"COMPETENCES\nPython\nEXPERIENCE\n{long_line}"
    facts = propose_profile_facts(text)
    experience = fact_by_kind(facts, "experience")
    start = experience.provenance.start_offset
    end = experience.provenance.end_offset
    assert text[start:end].strip()
    assert " ".join(text[start:end].split()) == experience.provenance.quote
    assert len(experience.provenance.quote) <= 240
    assert "…" not in experience.provenance.quote


def test_every_quote_describes_its_own_offsets(tmp_path: Path) -> None:
    text = read_fixture("cv_synthetique.txt")
    for fact in propose_profile_facts(text):
        provenance = fact.provenance
        passage = text[provenance.start_offset : provenance.end_offset]
        assert " ".join(passage.split()) == provenance.quote
        assert len(provenance.quote) <= 240


def test_the_page_of_a_fact_survives_normalised_line_endings() -> None:
    """A document written with CRLF keeps the right page for every fact."""
    first_page = "\r\n".join(["Premiere page"] + ["ligne de contexte"] * 40)
    pages = [first_page + "\r\nFORMATION\r\nMaster Démo", "FORMATION\r\nLicence Démo"]
    text = "\r\n\r\n".join(pages)
    facts = propose_profile_facts(text, pages=pages)
    licence = fact_by_kind(facts, "education", contains="Licence Démo")
    assert licence.provenance.page == 2


def test_a_truncated_source_does_not_get_a_wrong_page(tmp_path: Path) -> None:
    """A page that is not in the text gets no span rather than a wrong one."""
    pages = ["Premiere page\nCompétences\nPython", "Seconde page\nExpérience\n2020 - Stage"]
    text = "\n\n".join(pages)
    truncated = text[: len(pages[0]) + 2]
    facts = propose_profile_facts(truncated, pages=pages)
    python = fact_by_kind(facts, "skill", contains="Python")
    assert python.provenance.page == 1
    assert python.provenance.start_offset < len(truncated)


# ──────────────────────────────────────────────────────────────────────
# UI guards: the review screen exists and never approves on its own
# ──────────────────────────────────────────────────────────────────────


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : les garde-fous JavaScript ne sont pas exécutables sur cette machine")


def test_the_review_panel_is_served_with_its_script() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "career_static" / "index.html").read_text(encoding="utf-8")
    script = (root / "career_static" / "js" / "profile-builder.js").read_text(encoding="utf-8")
    assert 'id="candidate-profile-panel"' in html
    assert 'id="candidate-profile-facts"' in html
    assert 'id="candidate-profile-document-form"' in html
    assert 'id="candidate-profile-text-form"' in html
    assert "/career-static/js/profile-builder.js" in html
    assert "Aucune approbation automatique" in html
    # The screen never approves anything by itself.
    assert "automatic_approval" not in script
    assert script.count('decision: "approved"') == 0


def test_the_ui_offers_exactly_the_transitions_the_model_allows() -> None:
    """A click must never end on a transition the model would refuse."""
    root = Path(__file__).resolve().parents[1]
    script_path = root / "career_static" / "js" / "profile-builder.js"
    expected = {status: sorted(choices) for status, choices in ALLOWED_FACT_TRANSITIONS.items()}
    program = r'''
const assert = require("assert");
const fs = require("fs");
const source = fs.readFileSync(SCRIPT_PATH, "utf8");
const start = source.indexOf("const CANDIDATE_PROFILE_TRANSITIONS");
assert.ok(start >= 0, "la table des transitions est absente du script");
const end = source.indexOf("};", start);
assert.ok(end > start, "la table des transitions est illisible");
const table = new Function(source.slice(start, end + 2) + "\nreturn CANDIDATE_PROFILE_TRANSITIONS;")();
const sorted = {};
for (const [status, decisions] of Object.entries(table)) sorted[status] = decisions.slice().sort();
assert.deepStrictEqual(sorted, EXPECTED);
// The interface must not offer a transition the model would refuse.
for (const [status, decisions] of Object.entries(table)) {
  assert.ok(!decisions.includes(status), "une décision identique au statut ne doit pas être proposée");
}
'''.replace("SCRIPT_PATH", json.dumps(str(script_path))).replace(
        "EXPECTED", json.dumps(expected)
    )
    completed = subprocess.run([_node(), "-e", program], text=True, capture_output=True, timeout=8)
    assert completed.returncode == 0, completed.stderr


def test_the_ui_sends_the_decision_the_person_chose() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "career_static" / "js" / "profile-builder.js").read_text(encoding="utf-8")
    start = source.index("async function decideCandidateProfileFact(")
    end = source.index("\nasync function deleteCandidateProfileFact")
    function = source[start:end]
    script = r'''
const assert = require("assert");
const CANDIDATE_PROFILE_ENDPOINT = "/api/career/candidate-profile";
let sent = null;
global.fetch = async (url, options) => {
  sent = {url, options};
  return {ok: true, headers: {get: () => "application/json"}, json: async () => ({facts: []})};
};
function setCandidateProfileStatus() {}
function renderCandidateProfile() {}
async function candidateProfileApi(url, options = {}) {
  const formData = options.body instanceof FormData;
  const response = await fetch(url, {
    headers: options.body && !formData ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  let body = {};
  if (contentType.includes("application/json")) {
    try { body = await response.json(); } catch (_) { body = {}; }
  }
  if (!response.ok) { throw new Error("échec"); }
  return body;
}
FUNCTION
(async () => {
  await decideCandidateProfileFact("fact_1", "modified", "Anglais - C2");
  assert.ok(sent.url.endsWith("/facts/fact_1/decision"));
  assert.strictEqual(sent.options.method, "POST");
  let payload = JSON.parse(sent.options.body);
  assert.strictEqual(payload.decision, "modified");
  assert.strictEqual(payload.value, "Anglais - C2");
  await decideCandidateProfileFact("fact_2", "approved", "Python");
  payload = JSON.parse(sent.options.body);
  assert.strictEqual(payload.decision, "approved");
  // An approval never carries a rewritten value.
  assert.strictEqual(payload.value, "");
})().catch((error) => { console.error(error && error.stack || error); process.exit(1); });
'''.replace("FUNCTION", function)
    completed = subprocess.run([_node(), "-e", script], text=True, capture_output=True, timeout=8)
    assert completed.returncode == 0, completed.stderr
