"""SPEC-004 — Evidence-backed CV review workspace.

Every fixture is synthetic: no real CV, no real company, no personal data.
The tests cover the pure core (diff, statuses, export gate), the local
persistence (workspace + immutable history) and the HTTP contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.cv_review import (
    CRITICAL_SECTIONS,
    EVIDENCE_PLACEHOLDER,
    ProposedParagraph,
    ProposedSection,
    ReviewWorkspace,
    SourceSection,
    build_workspace,
    can_export,
    decide_block,
    diff_text,
    effective_text,
    find_placeholders,
    find_quote,
    render_export_markdown,
    split_phrases,
    workspace_from_dict,
    workspace_to_dict,
)
from career.cv_review_store import CVReviewStore
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cv_review"
STATIC_DIR = ROOT / "career_static"


def _profile() -> dict[str, str]:
    return json.loads((FIXTURES / "candidate_profile.json").read_text(encoding="utf-8"))


def _offer() -> dict[str, str]:
    return json.loads((FIXTURES / "offer.json").read_text(encoding="utf-8"))


def _source_cv() -> str:
    return (FIXTURES / "source_cv.txt").read_text(encoding="utf-8")


def _workspace(**overrides) -> ReviewWorkspace:
    """Build a small, fully synthetic workspace."""

    sources = {
        "experiences": SourceSection(
            text="2025 | Analyste | Banque Démo — modèle 12 DCF",
            source="cv",
            label="cv-demo.txt",
        ),
        "skills": SourceSection(
            text="Excel, financial modeling",
            source="cv",
            label="cv-demo.txt",
        ),
    }
    proposals = {
        "experiences": ProposedSection(
            heading="Professional Experience",
            paragraphs=(
                ProposedParagraph(
                    text="2025 | Analyste | Banque Démo",
                    source_line="2025 | Analyste | Banque Démo — modèle 12 DCF",
                    origin_field="experience",
                ),
            ),
        ),
        "skills": ProposedSection(
            heading="Technical Skills",
            paragraphs=(
                ProposedParagraph(
                    text="Excel, financial modelling",
                    source_line="Excel, financial modeling",
                    origin_field="skills",
                ),
            ),
        ),
    }
    payload: dict[str, object] = {
        "sources": sources,
        "proposals": proposals,
        "now": "2026-01-01T00:00:00+00:00",
    }
    payload.update(overrides)
    return build_workspace("app_demo", **payload)  # type: ignore[arg-type]


def _prepared_service(tmp_path: Path, *, with_cv: bool = False) -> tuple[CareerService, str]:
    """Return a Career service holding one tracked application."""

    service = CareerService(tmp_path)
    service.update_profile(_profile())
    if with_cv:
        service.import_profile_text(
            source_kind="cv",
            text=_source_cv(),
            original_name="cv-demo.txt",
        )
    job = service.import_job(_offer())
    kit = service.create_application_kit(str(job["id"]), "fr", "m_a")
    return service, str(kit["application"]["id"])


def _client(service: CareerService) -> TestClient:
    """Minimal app with the same error contract as the real application."""

    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


# --------------------------------------------------------------------------- #
# Diff et preuves
# --------------------------------------------------------------------------- #


def test_split_phrases_never_tears_a_decimal() -> None:
    assert split_phrases("Marge +20.5 % en 2025. Fin de l'exercice.") == [
        "Marge +20.5 % en 2025.",
        "Fin de l'exercice.",
    ]


def test_split_phrases_opens_a_new_phrase_on_the_cv_field_separator() -> None:
    assert split_phrases("2025 | Analyste | Banque Démo") == [
        "2025 |",
        "Analyste |",
        "Banque Démo",
    ]


def test_diff_text_reports_the_changed_fragments_only() -> None:
    segments = diff_text("Excel, financial modeling", "Excel, financial modelling")
    assert [segment.op for segment in segments] == ["delete", "insert"]
    assert segments[0].text == "Excel, financial modeling"
    assert segments[1].text == "Excel, financial modelling"


def test_diff_text_marks_unchanged_fragments_as_equal() -> None:
    segments = diff_text("Anglais C1", "Anglais C1")
    assert [(segment.op, segment.text) for segment in segments] == [("equal", "Anglais C1")]


def test_find_quote_returns_the_exact_offsets_of_the_quote() -> None:
    source = "2025 | Analyste | Banque Démo — modèle 12 DCF"
    found = find_quote(source, "Banque Démo — modèle 12 DCF")
    assert found is not None
    offset, length = found
    assert source[offset : offset + length] == "Banque Démo — modèle 12 DCF"


def test_find_quote_ignores_case_and_extra_spaces() -> None:
    source = "Marge   de  +15 %  sur l'exercice"
    found = find_quote(source, "marge de +15 % sur l'exercice")
    assert found is not None
    offset, length = found
    assert source[offset : offset + length] == "Marge   de  +15 %  sur l'exercice"


def test_find_placeholders_lists_every_marker() -> None:
    assert find_placeholders(f"Excel {EVIDENCE_PLACEHOLDER}") == [EVIDENCE_PLACEHOLDER]
    assert find_placeholders("Aucun marqueur ici") == []


# --------------------------------------------------------------------------- #
# Construction du workspace
# --------------------------------------------------------------------------- #


def test_build_workspace_is_pure_and_deterministic() -> None:
    first = _workspace()
    second = _workspace()
    assert workspace_to_dict(first) == workspace_to_dict(second)


def test_build_workspace_exposes_one_block_per_canonical_section() -> None:
    workspace = _workspace()
    assert [block.block_id for block in workspace.blocks] == ["experiences", "skills"]
    assert all(block.section in CRITICAL_SECTIONS for block in workspace.blocks)


def test_a_block_grounded_in_the_source_is_verified_automatically() -> None:
    workspace = _workspace()
    block = workspace.blocks[0]
    assert block.status == "verified"
    assert block.evidence
    assert block.evidence[0].kind == "source"
    assert block.evidence[0].offset == 0
    assert block.placeholder_reason is None


def test_a_proposal_absent_from_the_source_stays_pending() -> None:
    workspace = _workspace(
        sources={
            "experiences": SourceSection(
                text="2024 | Stagiaire | Conseil Démo — 3 mandats",
                source="cv",
                label="cv-demo.txt",
            ),
        },
        proposals={
            "experiences": ProposedSection(
                heading="Professional Experience",
                paragraphs=(
                    ProposedParagraph(
                        text="2025 | Analyste | Banque Démo",
                        source_line="2025 | Analyste | Banque Démo — modèle 12 DCF",
                        origin_field="experience",
                    ),
                ),
            ),
        },
        profile={"experience": "2025 | Analyste | Banque Démo — modèle 12 DCF"},
    )
    block = workspace.blocks[0]
    assert block.status == "pending"
    assert block.evidence
    assert all(item.kind == "profile" for item in block.evidence)
    assert block.evidence[0].source == "profile.experience"


def test_a_proposal_that_adds_a_word_is_never_grounded() -> None:
    workspace = _workspace(
        proposals={
            "skills": ProposedSection(
                heading="Technical Skills",
                paragraphs=(
                    ProposedParagraph(
                        text="Excel, financial modelling, SAP",
                        source_line="Excel, financial modeling",
                        origin_field="skills",
                    ),
                ),
            ),
        },
        profile={"skills": "Excel, financial modeling"},
    )
    block = workspace.blocks[1]
    assert block.status == "pending"


def test_a_placeholder_block_is_pending_and_names_the_missing_proof() -> None:
    workspace = _workspace(
        proposals={
            "skills": ProposedSection(
                heading="Technical Skills",
                paragraphs=(ProposedParagraph(text=EVIDENCE_PLACEHOLDER),),
            ),
        },
    )
    block = workspace.blocks[1]
    assert block.status == "pending"
    assert block.placeholder_reason
    assert EVIDENCE_PLACEHOLDER in block.placeholder_reason


def test_build_workspace_keeps_a_user_decision_when_the_content_is_unchanged() -> None:
    accepted, _ = decide_block(_workspace(), "skills", "accepted", now="2026-01-02T00:00:00+00:00")
    rebuilt = _workspace(saved=accepted)
    assert rebuilt.blocks[1].status == "accepted"
    assert rebuilt.blocks[1].decided_at == "2026-01-02T00:00:00+00:00"


def test_build_workspace_reopens_a_block_when_the_content_changed() -> None:
    accepted, _ = decide_block(_workspace(), "skills", "accepted")
    rebuilt = _workspace(
        saved=accepted,
        proposals={
            "skills": ProposedSection(
                heading="Technical Skills",
                paragraphs=(
                    ProposedParagraph(
                        text="Excel, financial modelling, SAP",
                        source_line="Excel, financial modeling",
                        origin_field="skills",
                    ),
                ),
            ),
        },
    )
    assert rebuilt.blocks[1].status == "pending"


# --------------------------------------------------------------------------- #
# Décisions
# --------------------------------------------------------------------------- #


def test_an_accepted_block_exports_the_proposal() -> None:
    workspace, block = decide_block(_workspace(), "skills", "accepted")
    assert block.status == "accepted"
    assert effective_text(block) == "Excel, financial modelling"


def test_a_rejected_block_falls_back_to_the_source() -> None:
    workspace, block = decide_block(_workspace(), "skills", "rejected")
    assert block.status == "rejected"
    assert effective_text(block) == "Excel, financial modeling"


def test_a_modified_block_exports_the_user_text() -> None:
    workspace, block = decide_block(
        _workspace(), "skills", "modified", user_text="Excel, PowerPoint"
    )
    assert block.status == "modified"
    assert block.user_text == "Excel, PowerPoint"
    assert effective_text(block) == "Excel, PowerPoint"


def test_a_modified_block_must_not_keep_a_placeholder() -> None:
    with pytest.raises(ValueError, match="marqueur"):
        decide_block(_workspace(), "skills", "modified", user_text=f"Excel {EVIDENCE_PLACEHOLDER}")


def test_a_modified_block_must_carry_a_text() -> None:
    with pytest.raises(ValueError, match="texte"):
        decide_block(_workspace(), "skills", "modified", user_text="   ")


def test_an_unknown_block_is_refused() -> None:
    with pytest.raises(KeyError):
        decide_block(_workspace(), "inconnu", "accepted")


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(ValueError, match="Statut"):
        decide_block(_workspace(), "skills", "peut-être")


# --------------------------------------------------------------------------- #
# Règle de blocage de l'export
# --------------------------------------------------------------------------- #


def test_can_export_blocks_a_pending_critical_block() -> None:
    workspace = _workspace(
        proposals={
            "skills": ProposedSection(
                heading="Technical Skills",
                paragraphs=(ProposedParagraph(text=EVIDENCE_PLACEHOLDER),),
            ),
        },
    )
    allowed, reasons = can_export(workspace)
    assert allowed is False
    assert any("Placeholder critique" in reason for reason in reasons)


def test_can_export_allows_a_workspace_whose_critical_blocks_are_validated() -> None:
    allowed, reasons = can_export(_workspace())
    assert allowed is True
    assert reasons == []


def test_a_rejected_critical_block_never_blocks_the_export() -> None:
    workspace, _ = decide_block(_workspace(), "skills", "rejected")
    allowed, reasons = can_export(workspace)
    assert allowed is True
    assert reasons == []


def test_can_export_blocks_an_empty_workspace() -> None:
    workspace = build_workspace("app_demo")
    allowed, reasons = can_export(workspace)
    assert allowed is False
    assert reasons


def test_render_export_markdown_uses_the_effective_text() -> None:
    workspace, _ = decide_block(_workspace(), "skills", "modified", user_text="Excel, SAP")
    markdown = render_export_markdown(
        workspace, name="Personne Démo", contact="demo@example.test"
    )
    assert "# Personne Démo" in markdown
    assert "## Technical Skills" in markdown
    assert "- Excel, SAP" in markdown
    assert "financial modelling" not in markdown


# --------------------------------------------------------------------------- #
# Persistance locale
# --------------------------------------------------------------------------- #


def test_the_store_round_trips_the_workspace(tmp_path: Path) -> None:
    store = CVReviewStore(tmp_path / "cv_review")
    workspace = _workspace()
    store.save_workspace(workspace)
    restored = store.load_workspace("app_demo")
    assert restored is not None
    assert workspace_to_dict(restored) == workspace_to_dict(workspace)


def test_the_store_returns_no_workspace_when_there_is_none(tmp_path: Path) -> None:
    store = CVReviewStore(tmp_path / "cv_review")
    assert store.load_workspace("app_demo") is None


def test_the_history_is_append_only(tmp_path: Path) -> None:
    store = CVReviewStore(tmp_path / "cv_review")
    store.append_history("app_demo", {"entry_id": "1", "action": "accepted"})
    store.append_history("app_demo", {"entry_id": "2", "action": "rejected"})
    entries = store.load_history("app_demo")
    assert [entry["entry_id"] for entry in entries] == ["1", "2"]
    # A third read never rewrites the journal.
    store.load_history("app_demo")
    assert len(store.load_history("app_demo")) == 2


def test_the_store_keeps_the_history_of_two_applications_apart(tmp_path: Path) -> None:
    store = CVReviewStore(tmp_path / "cv_review")
    store.append_history("app_a", {"entry_id": "1"})
    store.append_history("app_b", {"entry_id": "2"})
    assert len(store.load_history("app_a")) == 1
    assert len(store.load_history("app_b")) == 1


def test_the_workspace_serialization_round_trips() -> None:
    workspace = _workspace()
    restored = workspace_from_dict(workspace_to_dict(workspace))
    assert workspace_to_dict(restored) == workspace_to_dict(workspace)


# --------------------------------------------------------------------------- #
# Service local
# --------------------------------------------------------------------------- #


def test_the_service_builds_the_workspace_of_a_real_application(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    workspace = service.cv_review_workspace(application_id)
    assert workspace["application_id"] == application_id
    blocks = {block["block_id"]: block for block in workspace["blocks"]}
    assert "experiences" in blocks
    assert "skills" in blocks
    assert blocks["experiences"]["critical"] is True
    assert workspace["progress"]["critical_total"] == 2


def test_the_service_persists_a_decision_and_keeps_the_history(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    updated = service.decide_cv_review(application_id, "skills", "accepted")
    skills = next(block for block in updated["blocks"] if block["block_id"] == "skills")
    assert skills["status"] == "accepted"
    history = service.cv_review_history(application_id)
    assert history["count"] == 1
    entry = history["entries"][0]
    assert entry["block_id"] == "skills"
    assert entry["action"] == "accepted"
    assert entry["decided_by"] == "user"


def test_the_service_keeps_the_decision_across_two_reads(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    service.decide_cv_review(application_id, "skills", "accepted")
    workspace = service.cv_review_workspace(application_id)
    skills = next(block for block in workspace["blocks"] if block["block_id"] == "skills")
    assert skills["status"] == "accepted"


def test_the_service_refuses_a_modified_block_with_a_placeholder(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    with pytest.raises(UserFacingError, match="marqueur"):
        service.decide_cv_review(
            application_id, "skills", "modified", f"Excel {EVIDENCE_PLACEHOLDER}"
        )


def test_the_service_refuses_an_unknown_block(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    with pytest.raises(UserFacingError, match="n’existe pas"):
        service.decide_cv_review(application_id, "inconnu", "accepted")


def test_the_service_blocks_the_export_when_a_critical_block_is_pending(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    service.update_profile({"skills": ""})
    workspace = service.cv_review_workspace(application_id)
    assert workspace["can_export"] is False
    with pytest.raises(UserFacingError, match="Export bloqué"):
        service.export_cv_review(application_id)


def test_the_service_exports_a_docx_once_the_critical_blocks_are_validated(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    path = service.export_cv_review(application_id)
    assert path.exists()
    assert path.suffix == ".docx"
    assert path.stat().st_size > 0


def test_the_imported_document_becomes_the_reviewed_source(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path, with_cv=True)
    workspace = service.cv_review_workspace(application_id)
    assert workspace["source_document"] == "cv-demo.txt"
    experiences = next(
        block for block in workspace["blocks"] if block["block_id"] == "experiences"
    )
    assert experiences["evidence"]
    assert experiences["evidence"][0]["source"] == "cv"


# --------------------------------------------------------------------------- #
# Contrat HTTP
# --------------------------------------------------------------------------- #


def test_the_workspace_endpoint_returns_the_whole_workspace(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    client = _client(service)
    response = client.get(f"/api/career/cv-review/{application_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["application_id"] == application_id
    assert payload["blocks"]
    assert "can_export" in payload
    assert "blocking_reasons" in payload
    assert "progress" in payload


def test_the_decide_endpoint_records_the_decision(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    client = _client(service)
    response = client.post(
        f"/api/career/cv-review/{application_id}/decide",
        json={"block_id": "skills", "status": "accepted"},
    )
    assert response.status_code == 200
    payload = response.json()
    skills = next(block for block in payload["blocks"] if block["block_id"] == "skills")
    assert skills["status"] == "accepted"


def test_the_decide_endpoint_refuses_an_unknown_status(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    client = _client(service)
    response = client.post(
        f"/api/career/cv-review/{application_id}/decide",
        json={"block_id": "skills", "status": "envoye"},
    )
    assert response.status_code == 422


def test_the_history_endpoint_returns_the_immutable_journal(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    client = _client(service)
    client.post(
        f"/api/career/cv-review/{application_id}/decide",
        json={"block_id": "skills", "status": "accepted"},
    )
    response = client.get(f"/api/career/cv-review/{application_id}/history")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["entries"][0]["block_id"] == "skills"


def test_the_export_endpoint_returns_a_docx(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    client = _client(service)
    response = client.get(f"/api/career/cv-review/{application_id}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(response.content) > 0


def test_the_export_endpoint_is_blocked_when_a_critical_block_is_pending(tmp_path: Path) -> None:
    service, application_id = _prepared_service(tmp_path)
    service.update_profile({"skills": ""})
    client = _client(service)
    response = client.get(f"/api/career/cv-review/{application_id}/export")
    assert response.status_code == 400
    assert "Export bloqué" in response.json()["detail"]


def test_the_review_endpoints_refuse_an_unknown_application(tmp_path: Path) -> None:
    service, _ = _prepared_service(tmp_path)
    client = _client(service)
    response = client.get("/api/career/cv-review/app_inconnue")
    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Garde-fous statiques
# --------------------------------------------------------------------------- #


def _route_paths() -> list[str]:
    source = (ROOT / "career" / "router.py").read_text(encoding="utf-8")
    return re.findall(r'@router\.(?:get|post|patch|put|delete)\("([^"]+)"', source)


def test_the_review_routes_are_registered() -> None:
    paths = _route_paths()
    assert "/api/career/cv-review/{application_id}" in paths
    assert "/api/career/cv-review/{application_id}/decide" in paths
    assert "/api/career/cv-review/{application_id}/export" in paths
    assert "/api/career/cv-review/{application_id}/history" in paths


def test_no_route_submits_anything() -> None:
    forbidden = re.compile(r"send|mail|smtp|transmit|auto-submit|autosubmit|autoapp")
    offending = [path for path in _route_paths() if forbidden.search(path.lower())]
    assert offending == []


def test_the_review_ui_contract_is_present() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "js" / "cv-review.js").read_text(encoding="utf-8")
    assert 'id="cv-review-panel"' in html
    assert 'id="cv-review-application"' in html
    assert 'id="cv-review-progress-bar"' in html
    assert 'role="progressbar"' in html
    assert 'id="cv-review-export"' in html
    assert 'aria-live="polite"' in html
    assert "/career-static/js/cv-review.js" in html
    assert "/api/career/cv-review" in script
    assert "✅ Accepter" in script
    assert "✏️ Modifier" in script
    assert "❌ Refuser" in script
    assert "↩️ Source" in script
    assert "🟢 Vérifié" in script
    assert "🟡 À vérifier" in script
    assert "🔴 Placeholder" in script


def test_the_review_ui_never_prompts_and_never_sends() -> None:
    script = (STATIC_DIR / "js" / "cv-review.js").read_text(encoding="utf-8")
    assert "window.prompt" not in script
    assert "mailto:" not in script
    assert "smtp" not in script.lower()
