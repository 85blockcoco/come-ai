"""Candidate profile: proposals, per-fact approval, exact provenance.

Every fixture used here is synthetic: invented people, invented companies,
invented phone numbers and ``.test`` addresses.  No real document and no
real personal data is read by this suite.

The contract under test:

* the local pipeline only *proposes* facts -- it never approves one;
* every fact keeps the passage it was read from (page, offsets, quote);
* a fact read from an OCR layer is never approved by a machine;
* only the facts the user approved may justify an application;
* deletion and export work, so the profile stays portable.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

import docx

from career.candidate_profile import (
    ACTOR_SYSTEM,
    ACTOR_USER,
    ALLOWED_TRANSITIONS,
    FACT_STATUSES,
    JUSTIFIABLE_STATUSES,
    STATUS_APPROVED,
    STATUS_MODIFIED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_SUSPENDED,
    AutoApprovalError,
    CandidateProfile,
    FactTransitionError,
    ProfileFact,
    Provenance,
    SourceDocument,
    build_justification,
    can_transition,
    make_fact_id,
    profile_to_markdown,
    transition_fact,
    verify_profile,
)
from career.cv_quality.parser import extract_pages_from_bytes
from career.profile_builder import (
    MAX_PROPOSED_FACTS,
    OcrOutcome,
    build_source_document,
    propose_facts,
)
from career.profile_store import ProfileStore
from career.service import DELETE_CONFIRMATION, CareerService
from come_ai_web import create_app


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "candidate_profile"
SCRIPT = ROOT / "career_static" / "js" / "profile-builder.js"
HTML = ROOT / "career_static" / "index.html"

STAMP = "2026-10-21T09:00:00+00:00"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def expected_documents() -> list[dict]:
    payload = json.loads((FIXTURES / "expected_facts.json").read_text(encoding="utf-8"))
    return payload["documents"]


def build_from_text(text: str, *, filename: str = "cv-synthetique.txt"):
    document, spans = build_source_document(
        filename=filename, filetype="txt", text=text, created_at=STAMP
    )
    facts = propose_facts(document, spans, created_at=STAMP)
    return document, spans, facts


@pytest.fixture()
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "career.sqlite3")


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    service = CareerService(tmp_path)
    return TestClient(create_app(base_dir=tmp_path, career_override=service))


# --- The five statuses --------------------------------------------------------


def test_five_statuses_are_defined_and_transitions_are_explicit() -> None:
    assert FACT_STATUSES == (
        "proposed",
        "approved",
        "rejected",
        "modified",
        "suspended",
    )
    assert set(ALLOWED_TRANSITIONS) == set(FACT_STATUSES)
    # A rejected fact never jumps straight back to approved: it goes back to
    # review first.
    assert not can_transition(STATUS_REJECTED, STATUS_APPROVED)
    assert can_transition(STATUS_REJECTED, STATUS_PROPOSED)
    assert can_transition(STATUS_PROPOSED, STATUS_APPROVED)
    assert can_transition(STATUS_SUSPENDED, STATUS_APPROVED)


def test_only_approved_and_modified_facts_are_justifiable() -> None:
    assert JUSTIFIABLE_STATUSES == frozenset({STATUS_APPROVED, STATUS_MODIFIED})
    for status in (STATUS_PROPOSED, STATUS_REJECTED, STATUS_SUSPENDED):
        fact = _fact(status=status)
        assert fact.is_justifiable is False
    assert _fact(status=STATUS_APPROVED).is_justifiable is True
    assert _fact(status=STATUS_MODIFIED).is_justifiable is True


def test_impossible_transition_is_refused() -> None:
    fact = _fact(status=STATUS_REJECTED)
    with pytest.raises(FactTransitionError):
        transition_fact(fact, STATUS_APPROVED)
    assert transition_fact(fact, STATUS_PROPOSED).status == STATUS_PROPOSED


def test_modifying_a_fact_keeps_its_previous_value_and_its_source() -> None:
    fact = _fact(status=STATUS_PROPOSED)
    updated = transition_fact(fact, STATUS_MODIFIED, value="Python confirmé")
    assert updated.status == STATUS_MODIFIED
    assert updated.previous_value == fact.value
    assert updated.value == "Python confirmé"
    assert updated.provenance == fact.provenance
    assert updated.is_justifiable is True


def test_an_ocr_fact_can_only_be_approved_by_a_user() -> None:
    ocr_fact = _fact(status=STATUS_PROPOSED, extraction="ocr")
    with pytest.raises(AutoApprovalError):
        transition_fact(ocr_fact, STATUS_APPROVED, actor=ACTOR_SYSTEM)
    approved = transition_fact(ocr_fact, STATUS_APPROVED, actor=ACTOR_USER)
    assert approved.status == STATUS_APPROVED
    # A text-layer fact may be approved by a machine, but the store never
    # does it on its own: every decision comes from an explicit call.
    assert _fact(status=STATUS_PROPOSED).comes_from_ocr is False


def test_justification_only_contains_the_facts_the_user_approved() -> None:
    facts = [
        _fact(fact_id="a", status=STATUS_APPROVED, kind="skill"),
        _fact(fact_id="b", status=STATUS_PROPOSED, kind="skill"),
        _fact(fact_id="c", status=STATUS_REJECTED, kind="skill"),
        _fact(fact_id="d", status=STATUS_SUSPENDED, kind="skill"),
        _fact(fact_id="e", status=STATUS_MODIFIED, kind="experience"),
    ]
    justification = build_justification(facts)
    assert justification["fact_ids"] == ["a", "e"]
    assert justification["count"] == 2
    assert [entry["fact_id"] for entry in justification["justifiable"]["skill"]] == ["a"]
    assert [entry["fact_id"] for entry in justification["justifiable"]["experience"]] == ["e"]


# --- The pipeline -------------------------------------------------------------


def test_the_pipeline_proposes_facts_and_approves_nothing() -> None:
    document, _spans, facts = build_from_text(read_fixture("cv_synthetique.txt"))
    assert facts
    assert all(fact.status == STATUS_PROPOSED for fact in facts)
    assert not any(fact.is_justifiable for fact in facts)


def test_every_fact_keeps_the_exact_passage_it_comes_from() -> None:
    document, _spans, facts = build_from_text(read_fixture("cv_synthetique.txt"))
    for fact in facts:
        provenance = fact.provenance
        assert provenance.source_id == document.document_id
        assert provenance.filename == document.filename
        assert provenance.page == 1
        assert 0 <= provenance.start_offset < provenance.end_offset <= len(document.text)
        assert document.text[provenance.start_offset : provenance.end_offset] == provenance.quote
        assert provenance.quote.strip()
    assert verify_profile(CandidateProfile(document=document, facts=facts)) == []


def test_the_expected_facts_are_proposed_for_both_synthetic_documents() -> None:
    for expected in expected_documents():
        document, _spans, facts = build_from_text(
            read_fixture(expected["fixture"]), filename=expected["fixture"]
        )
        kinds = {fact.kind for fact in facts}
        assert set(expected["expected_kinds"]) <= kinds, expected["fixture"]
        for wanted in expected["expected_facts"]:
            matches = [
                fact
                for fact in facts
                if fact.kind == wanted["kind"] and fact.value == wanted["value"]
            ]
            assert matches, f"{expected['fixture']} : {wanted} n’est pas proposé"
        for wanted in expected["expected_attributes"]:
            matches = [
                fact
                for fact in facts
                if fact.kind == wanted["kind"] and fact.label == wanted["label"]
            ]
            assert matches
            assert matches[0].attributes == wanted["attributes"]


def test_a_scanned_document_is_read_by_the_local_ocr_and_never_auto_approved() -> None:
    text = read_fixture("cv_synthetique.txt")
    calls: list[str] = []

    def ocr_provider() -> OcrOutcome:
        calls.append("ocr")
        return OcrOutcome(text=text, pages=1, warnings=("Lecture OCR synthétique",))

    document, spans = build_source_document(
        filename="scan-synthetique.pdf",
        filetype="pdf",
        data=b"%PDF-1.4 synthetic",
        ocr_provider=ocr_provider,
        created_at=STAMP,
    )
    assert calls == ["ocr"]
    assert document.extraction == "ocr"
    facts = propose_facts(document, spans, created_at=STAMP)
    assert facts
    assert all(fact.status == STATUS_PROPOSED for fact in facts)
    assert all(fact.comes_from_ocr for fact in facts)
    with pytest.raises(AutoApprovalError):
        transition_fact(facts[0], STATUS_APPROVED, actor=ACTOR_SYSTEM)


def test_the_ocr_is_only_used_when_the_text_layer_is_missing() -> None:
    calls: list[str] = []

    def ocr_provider() -> OcrOutcome:
        calls.append("ocr")
        return OcrOutcome(text="texte ocr")

    document, _spans = build_source_document(
        filename="cv.txt",
        filetype="txt",
        text=read_fixture("cv_synthetique.txt"),
        ocr_provider=ocr_provider,
        created_at=STAMP,
    )
    assert calls == []
    assert document.extraction == "text_layer"


def test_reading_the_same_document_twice_proposes_the_same_facts() -> None:
    text = read_fixture("cv_synthetique.txt")
    _document, _spans, first = build_from_text(text)
    _document, _spans, second = build_from_text(text)
    assert [fact.fact_id for fact in first] == [fact.fact_id for fact in second]
    assert make_fact_id("skill", "Excel", "doc_x", 12) == make_fact_id("skill", "excel", "doc_x", 12)


def test_the_number_of_proposed_facts_is_bounded() -> None:
    noisy = "\n".join(f"Compétence numéro {index}" for index in range(900))
    document, spans = build_source_document(
        filename="bruit.txt", filetype="txt", text=noisy, created_at=STAMP
    )
    facts = propose_facts(document, spans, created_at=STAMP)
    assert len(facts) <= MAX_PROPOSED_FACTS


def test_a_fact_whose_quote_was_altered_is_detected() -> None:
    document, _spans, facts = build_from_text(read_fixture("cv_synthetique.txt"))
    broken = ProfileFact(
        fact_id=facts[0].fact_id,
        kind=facts[0].kind,
        label=facts[0].label,
        value=facts[0].value,
        status=facts[0].status,
        provenance=Provenance(
            source_id=facts[0].provenance.source_id,
            filename=facts[0].provenance.filename,
            filetype=facts[0].provenance.filetype,
            page=1,
            start_offset=0,
            end_offset=5,
            quote="une citation inventée",
            extraction="text_layer",
            source_sha256=facts[0].provenance.source_sha256,
        ),
    )
    problems = verify_profile(CandidateProfile(document=document, facts=(broken,)))
    assert problems
    assert "citation" in problems[0]


# --- The local store ----------------------------------------------------------


def test_the_store_keeps_the_decision_of_the_user_when_the_document_is_read_again(
    store: ProfileStore,
) -> None:
    text = read_fixture("cv_synthetique.txt")
    document, spans = build_source_document(
        filename="cv.txt", filetype="txt", text=text, created_at=STAMP
    )
    facts = propose_facts(document, spans, created_at=STAMP)
    store.save_document(document)
    store.save_facts(facts, now=STAMP)
    target = next(fact for fact in facts if fact.kind == "skill")
    store.approve(target.fact_id, now=STAMP)

    # The very same document is read again: no duplicate, no lost decision.
    store.save_document(document)
    store.save_facts(facts, now=STAMP)
    stored = store.list_facts()
    assert len(stored) == len(facts)
    assert store.get_fact(target.fact_id).status == STATUS_APPROVED


def test_the_store_refuses_to_approve_an_ocr_fact_with_a_machine(
    store: ProfileStore,
) -> None:
    text = read_fixture("cv_synthetique.txt")
    document, spans = build_source_document(
        filename="scan.pdf",
        filetype="txt",
        text=text,
        ocr_provider=None,
        created_at=STAMP,
    )
    ocr_document = SourceDocument(
        document_id=document.document_id,
        filename=document.filename,
        filetype=document.filetype,
        page_count=document.page_count,
        text=document.text,
        extraction="ocr",
        sha256=document.sha256,
        created_at=STAMP,
    )
    facts = propose_facts(ocr_document, spans, created_at=STAMP)
    store.save_document(ocr_document)
    store.save_facts(facts, now=STAMP)
    target = facts[0]
    with pytest.raises(AutoApprovalError):
        store.approve(target.fact_id, actor=ACTOR_SYSTEM, now=STAMP)
    assert store.get_fact(target.fact_id).status == STATUS_PROPOSED
    assert store.approve(target.fact_id, actor=ACTOR_USER, now=STAMP).status == STATUS_APPROVED


def test_a_deleted_fact_disappears_from_the_active_profile(store: ProfileStore) -> None:
    document, spans, facts = _seed(store)
    target = facts[0]
    store.approve(target.fact_id, now=STAMP)
    assert target.fact_id in [fact.fact_id for fact in store.active_facts()]
    assert store.delete_fact(target.fact_id) is True
    assert store.get_fact(target.fact_id) is None
    assert target.fact_id not in [fact.fact_id for fact in store.active_facts()]
    assert store.delete_fact("fact_inexistant") is False


def test_deleting_a_document_deletes_the_facts_it_produced(store: ProfileStore) -> None:
    document, _spans, facts = _seed(store)
    assert len(store.list_facts()) == len(facts)
    deleted = store.delete_document(document.document_id)
    assert deleted == len(facts)
    assert store.list_facts() == []
    assert store.get_document(document.document_id) is None


def test_the_export_is_portable_and_keeps_the_provenance(store: ProfileStore) -> None:
    document, _spans, facts = _seed(store)
    store.approve(facts[0].fact_id, now=STAMP)
    export = store.export_profile()
    assert export["schema"] == "come-candidate-profile/1"
    assert len(export["facts"]) == len(facts)
    assert export["active_facts"] == [facts[0].fact_id]
    exported_document = export["documents"][0]
    assert exported_document["document_id"] == document.document_id
    assert exported_document["text"] == document.text
    first = export["facts"][0]
    assert first["provenance"]["quote"]
    assert first["provenance"]["start_offset"] >= 0
    assert first["status"] in FACT_STATUSES

    # The export can be read back and still proves its own provenance.
    profile = CandidateProfile.from_dict(
        {"document": exported_document, "facts": export["facts"]}
    )
    assert verify_profile(profile) == []

    without_source = store.export_profile(include_source=False)
    assert "text" not in without_source["documents"][0]


def test_the_export_renders_a_readable_markdown_profile(store: ProfileStore) -> None:
    _document, _spans, facts = _seed(store)
    store.approve(facts[0].fact_id, now=STAMP)
    markdown = profile_to_markdown(store.profile())
    assert "# Profil candidat" in markdown
    assert "Source :" in markdown
    assert "«" in markdown


# --- The HTTP interface -------------------------------------------------------


def test_importing_a_text_proposes_facts_without_approving_any(client: TestClient) -> None:
    response = client.post(
        "/api/career/profile-facts/import-text",
        json={"text": read_fixture("cv_synthetique.txt"), "filename": "cv.txt"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["facts"]
    assert all(fact["status"] == STATUS_PROPOSED for fact in payload["facts"])
    assert payload["counts"]["approved"] == 0
    assert payload["active"]["count"] == 0
    for fact in payload["facts"]:
        assert fact["provenance"]["quote"]
        assert fact["provenance"]["page"] == 1
        assert fact["justifiable"] is False


def test_approving_one_fact_makes_it_part_of_the_active_profile(client: TestClient) -> None:
    payload = client.post(
        "/api/career/profile-facts/import-text",
        json={"text": read_fixture("cv_synthetique.txt"), "filename": "cv.txt"},
    ).json()
    target = payload["facts"][0]
    response = client.post(f"/api/career/profile-facts/{target['fact_id']}/approve")
    assert response.status_code == 200
    body = response.json()
    assert body["fact"]["status"] == STATUS_APPROVED
    assert body["counts"]["approved"] == 1
    assert body["active"]["fact_ids"] == [target["fact_id"]]

    active = client.get("/api/career/profile-facts/active").json()
    assert active["fact_ids"] == [target["fact_id"]]


def test_rejecting_and_suspending_a_fact_keeps_it_out_of_the_active_profile(
    client: TestClient,
) -> None:
    payload = client.post(
        "/api/career/profile-facts/import-text",
        json={"text": read_fixture("cv_synthetique.txt"), "filename": "cv.txt"},
    ).json()
    first, second = payload["facts"][0], payload["facts"][1]

    rejected = client.post(f"/api/career/profile-facts/{first['fact_id']}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["fact"]["status"] == STATUS_REJECTED

    suspended = client.post(f"/api/career/profile-facts/{second['fact_id']}/suspend")
    assert suspended.status_code == 200
    assert suspended.json()["fact"]["status"] == STATUS_SUSPENDED

    active = client.get("/api/career/profile-facts/active").json()
    assert active["count"] == 0


def test_correcting_a_fact_keeps_its_source(client: TestClient) -> None:
    payload = client.post(
        "/api/career/profile-facts/import-text",
        json={"text": read_fixture("cv_synthetique.txt"), "filename": "cv.txt"},
    ).json()
    target = payload["facts"][0]
    response = client.post(
        f"/api/career/profile-facts/{target['fact_id']}/modify",
        json={"value": "valeur corrigée"},
    )
    assert response.status_code == 200
    fact = response.json()["fact"]
    assert fact["status"] == STATUS_MODIFIED
    assert fact["value"] == "valeur corrigée"
    assert fact["previous_value"] == target["value"]
    assert fact["provenance"]["quote"] == target["provenance"]["quote"]
    assert fact["justifiable"] is True


def test_deleting_a_fact_and_a_document_works(client: TestClient) -> None:
    payload = client.post(
        "/api/career/profile-facts/import-text",
        json={"text": read_fixture("cv_synthetique.txt"), "filename": "cv.txt"},
    ).json()
    target = payload["facts"][0]
    document_id = payload["document"]["document_id"]

    deleted = client.delete(f"/api/career/profile-facts/{target['fact_id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}

    missing = client.delete("/api/career/profile-facts/fact_inexistant")
    assert missing.status_code == 404

    removed = client.delete(f"/api/career/profile-facts/documents/{document_id}")
    assert removed.status_code == 200
    assert removed.json()["facts_deleted"] >= 0
    assert client.get("/api/career/profile-facts").json()["facts"] == []


def test_the_export_endpoint_returns_the_portable_profile(client: TestClient) -> None:
    client.post(
        "/api/career/profile-facts/import-text",
        json={"text": read_fixture("cv_synthetique.txt"), "filename": "cv.txt"},
    )
    export = client.get("/api/career/profile-facts/export").json()
    assert export["schema"] == "come-candidate-profile/1"
    assert export["facts"]
    assert export["documents"][0]["text"]

    light = client.get("/api/career/profile-facts/export?include_source=false").json()
    assert "text" not in light["documents"][0]


def test_importing_an_unsupported_document_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/career/profile-facts/import",
        files={"document": ("cv.exe", b"binary", "application/octet-stream")},
    )
    assert response.status_code in (400, 422)


def test_a_missing_fact_is_reported_as_not_found(client: TestClient) -> None:
    response = client.post("/api/career/profile-facts/fact_inexistant/approve")
    assert response.status_code == 404


def test_a_full_reset_erases_the_candidate_profile(client: TestClient) -> None:
    client.post(
        "/api/career/profile-facts/import-text",
        json={"text": read_fixture("cv_synthetique.txt"), "filename": "cv.txt"},
    )
    assert client.get("/api/career/profile-facts").json()["facts"]
    response = client.request(
        "DELETE", "/api/career/data", json={"confirmation": DELETE_CONFIRMATION}
    )
    assert response.status_code == 200
    assert client.get("/api/career/profile-facts").json()["facts"] == []
    assert client.get("/api/career/profile-facts").json()["documents"] == []


# --- The manual check, kept out of the Git fixtures ---------------------------


def test_the_manual_check_script_refuses_a_document_stored_in_the_repository() -> None:
    script = ROOT / "scripts" / "candidate_profile_manual_check.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(FIXTURES / "cv_synthetique.txt")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode != 0
    assert "dépôt" in (completed.stdout + completed.stderr)


def test_the_manual_check_script_reads_a_document_outside_the_repository(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "candidate_profile_manual_check.py"
    document = tmp_path / "cv.txt"
    document.write_text(read_fixture("cv_synthetique.txt"), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script), str(document)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "aucun n'est approuvé" in completed.stdout
    assert "correspondent exactement" in completed.stdout


# --- Real formats, still synthetic --------------------------------------------


def _make_two_page_pdf(path: Path) -> None:
    """Build a two-page synthetic CV: no real person, no real company."""
    pdf = canvas.Canvas(str(path), pagesize=(595, 842))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, 800, "Camille Exemple")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(40, 780, "camille.exemple@example.test")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, 740, "COMPETENCES")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(40, 720, "Excel, Python, SQL")
    pdf.showPage()
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, 800, "EXPERIENCE")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(40, 780, "2021 - 2024 Analyste - Groupe Fictif")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, 740, "FORMATION")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(40, 720, "2019 - 2021 Master - Universite Fictive")
    pdf.save()


def test_a_pdf_keeps_the_page_of_every_fact(tmp_path: Path) -> None:
    path = tmp_path / "cv-synthetique.pdf"
    _make_two_page_pdf(path)
    document, spans = build_source_document(
        filename="cv-synthetique.pdf",
        filetype="pdf",
        data=path.read_bytes(),
        created_at=STAMP,
    )
    facts = propose_facts(document, spans, created_at=STAMP)
    pages = {fact.kind: fact.provenance.page for fact in facts}
    assert pages["skill"] == 1
    assert pages["experience"] == 2
    assert pages["education"] == 2
    for fact in facts:
        assert document.text[fact.provenance.start_offset : fact.provenance.end_offset] == fact.provenance.quote


def test_the_parser_exposes_the_text_of_each_page(tmp_path: Path) -> None:
    path = tmp_path / "cv-synthetique.pdf"
    _make_two_page_pdf(path)
    pages, page_count = extract_pages_from_bytes(path.read_bytes(), "pdf")
    assert page_count == 2
    assert [page.page_number for page in pages] == [1, 2]
    joined = "\n\n".join(page.text for page in pages)
    document, _spans = build_source_document(
        filename="cv-synthetique.pdf",
        filetype="pdf",
        data=path.read_bytes(),
        created_at=STAMP,
    )
    assert joined == document.text


def test_a_docx_is_read_locally(tmp_path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("Alex Example")
    document.add_paragraph("alex.example@example.test")
    document.add_paragraph("SKILLS")
    document.add_paragraph("Excel, Python, SQL")
    path = tmp_path / "cv-synthetique.docx"
    document.save(str(path))

    source, spans = build_source_document(
        filename="cv-synthetique.docx",
        filetype="docx",
        data=path.read_bytes(),
        created_at=STAMP,
    )
    facts = propose_facts(source, spans, created_at=STAMP)
    values = {fact.value for fact in facts if fact.kind == "skill"}
    assert {"Excel", "Python", "SQL"} <= values
    for fact in facts:
        assert source.text[fact.provenance.start_offset : fact.provenance.end_offset] == fact.provenance.quote


# --- The interface guards -----------------------------------------------------


def test_the_profile_builder_script_is_loaded_by_the_career_page() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "js/profile-builder.js" in html


def test_the_profile_builder_script_only_shows_the_approved_facts_as_active() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "profile-facts/active" in script
    assert "approved" in script
    for action in ("/approve", "/reject", "/suspend", "/modify"):
        assert action in script
    # The script never sends an approval by itself at load time.
    assert "autoApprove" not in script


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent: impossible d’exécuter les gardes JavaScript")


def test_the_profile_builder_script_filters_the_active_facts_in_javascript() -> None:
    node = _node()
    script = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"function activeFacts\(facts\) \{.*?\n  \}", script, re.DOTALL)
    assert match, "la fonction activeFacts est introuvable"
    program = f"""
const assert = require("assert");
{match.group(0)}
const facts = [
  {{fact_id: "a", status: "approved"}},
  {{fact_id: "b", status: "modified"}},
  {{fact_id: "c", status: "proposed"}},
  {{fact_id: "d", status: "rejected"}},
  {{fact_id: "e", status: "suspended"}}
];
assert.deepStrictEqual(activeFacts(facts).map(function (fact) {{ return fact.fact_id; }}), ["a", "b"]);
assert.deepStrictEqual(activeFacts(null), []);
"""
    completed = subprocess.run(
        [node, "-e", program], capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0, completed.stderr


# --- Helpers ------------------------------------------------------------------


def _fact(
    *,
    fact_id: str = "fact_test",
    kind: str = "skill",
    status: str = STATUS_PROPOSED,
    extraction: str = "text_layer",
    value: str = "Python",
) -> ProfileFact:
    return ProfileFact(
        fact_id=fact_id,
        kind=kind,
        label=value,
        value=value,
        status=status,
        provenance=Provenance(
            source_id="doc_test",
            filename="cv.txt",
            filetype="txt",
            page=1,
            start_offset=0,
            end_offset=len(value),
            quote=value,
            extraction=extraction,
            source_sha256="",
        ),
        created_at=STAMP,
        updated_at=STAMP,
    )


def _seed(store: ProfileStore):
    document, spans = build_source_document(
        filename="cv.txt",
        filetype="txt",
        text=read_fixture("cv_synthetique.txt"),
        created_at=STAMP,
    )
    facts = propose_facts(document, spans, created_at=STAMP)
    store.save_document(document)
    store.save_facts(facts, now=STAMP)
    return document, spans, facts
