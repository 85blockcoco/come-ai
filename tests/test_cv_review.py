"""Espace de revue du CV ciblé (SPEC-004) : couverture hors ligne.

Toutes les fixtures sont synthétiques (tests/fixtures/cv_review/) : aucune
vraie offre, aucune vraie entreprise, aucune donnée personnelle. Rien n'appelle
le réseau. Ce qui est vérifié : la construction pure du workspace, la preuve
attachée à chaque bloc, le diff source → proposé, la persistance des décisions,
l'immuabilité de l'historique, le blocage de l'export tant qu'un bloc critique
n'est pas tranché, et le contenu du DOCX exporté.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.cv_review import (
    CRITICAL_SECTIONS,
    apply_decision,
    build_workspace,
    can_export,
    diff_segments,
    effective_text,
    merge_decisions,
    render_workspace_markdown,
    review_progress,
    serialize_workspace,
)
from career.cv_review_store import (
    append_event,
    history_path,
    load_workspace,
    read_events,
    save_workspace,
    workspace_path,
)
from career.cv_fit import CoverageResult
from career.cv_variants import MA_VARIANT
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cv_review"


def synthetic_profile() -> dict[str, str]:
    return json.loads((FIXTURES / "synthetic_profile.json").read_text(encoding="utf-8"))


def synthetic_job() -> dict[str, Any]:
    payload = json.loads((FIXTURES / "synthetic_offer.json").read_text(encoding="utf-8"))
    payload.pop("note", None)
    payload["deadline_date"] = (date.today() + timedelta(days=14)).isoformat()
    return payload


def empty_coverage() -> CoverageResult:
    return CoverageResult(
        mandatory_total=0,
        mandatory_covered=0,
        preferred_total=0,
        preferred_covered=0,
        mandatory_pct=0.0,
        preferred_pct=0.0,
        gaps=[],
        recommended_variant=MA_VARIANT,
        variant_rationale="démo",
    )


def review_client(service: CareerService) -> TestClient:
    """App minimale avec le même contrat d'erreur que l'application réelle."""

    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def tracked_application(service: CareerService, variant: str = "m_a") -> str:
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    kit = service.create_application_kit(job["id"], "fr", variant)
    return str(kit["application"]["id"])


# --- 1. Construction pure du workspace --------------------------------------


def test_build_workspace_is_pure_and_deterministic() -> None:
    profile = synthetic_profile()
    first = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        language="fr",
        profile=profile,
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    second = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        language="fr",
        profile=profile,
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    assert [block.block_id for block in first.blocks] == [block.block_id for block in second.blocks]
    assert [block.status for block in first.blocks] == [block.status for block in second.blocks]
    assert first.created_at == second.created_at
    # Le cœur ne touche jamais le disque : rien n'est écrit par le build.
    assert not workspace_path(Path("/nonexistent-review-dir"), "app_demo").exists()


def test_every_proposed_line_carries_a_verbatim_local_proof() -> None:
    profile = synthetic_profile()
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=profile,
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    proved = [block for block in workspace.blocks if block.evidence]
    assert proved, "au moins un bloc doit être justifié par une preuve locale"
    for block in proved:
        evidence = block.evidence[0]
        assert evidence.source.startswith("profile.")
        assert evidence.quote in str(profile.get(evidence.source.split(".", 1)[1]) or "")
        offset = str(profile.get(evidence.source.split(".", 1)[1]) or "").find(evidence.quote)
        assert offset == evidence.offset


def test_a_block_without_proof_is_a_placeholder_not_an_invention() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    placeholders = [block for block in workspace.blocks if block.placeholder_reason]
    assert placeholders, "les sections sans ligne doivent rester visibles"
    for block in placeholders:
        assert block.evidence is None
        assert block.source_text == ""
        assert "AJOUTER PREUVE" in block.proposed_text


def test_a_locale_variant_is_verified_and_a_new_wording_stays_pending() -> None:
    profile = synthetic_profile()
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=profile,
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    verified = [block for block in workspace.blocks if block.status == "verified"]
    assert verified, "une reformulation purement orthographique reste prouvée"
    for block in verified:
        assert block.evidence, "un bloc vérifié porte toujours sa preuve"
    summary = next(block for block in workspace.blocks if block.block_id == "summary")
    assert summary.status == "pending"
    assert summary.section in CRITICAL_SECTIONS


# --- 2. Diff source → proposé ----------------------------------------------


def test_diff_segments_show_the_exact_change() -> None:
    segments = diff_segments("financial modeling", "financial modelling")
    kinds = [segment.kind for segment in segments]
    assert "insert" in kinds and "delete" in kinds
    inserted = "".join(segment.text for segment in segments if segment.kind == "insert")
    deleted = "".join(segment.text for segment in segments if segment.kind == "delete")
    assert inserted.strip() == "modelling"
    assert deleted.strip() == "modeling"
    equal = "".join(segment.text for segment in segments if segment.kind == "equal")
    assert equal == "financial "


def test_diff_of_identical_text_is_a_single_equal_segment() -> None:
    segments = diff_segments("Excel", "Excel")
    assert [segment.kind for segment in segments] == ["equal"]
    assert segments[0].text == "Excel"


# --- 3. Décisions ----------------------------------------------------------


def test_apply_decision_never_mutates_the_workspace() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    target = workspace.blocks[0].block_id
    updated = apply_decision(workspace, target, "accepted", decided_at="2026-10-22T09:10:00+00:00")
    assert workspace.blocks[0].status == "pending"
    assert next(block for block in updated.blocks if block.block_id == target).status == "accepted"


def test_a_modified_block_requires_the_validated_text() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    target = workspace.blocks[0].block_id
    with pytest.raises(ValueError):
        apply_decision(workspace, target, "modified", user_text="   ")
    updated = apply_decision(workspace, target, "modified", user_text="  Preuve chiffrée  ")
    block = next(block for block in updated.blocks if block.block_id == target)
    assert block.user_text == "Preuve chiffrée"
    assert effective_text(block) == "Preuve chiffrée"


def test_an_unknown_block_or_status_is_refused() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    with pytest.raises(KeyError):
        apply_decision(workspace, "block-inexistant", "accepted")
    with pytest.raises(ValueError):
        apply_decision(workspace, workspace.blocks[0].block_id, "verified")


def test_a_pending_or_rejected_block_exports_the_source_wording() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    target = next(block for block in workspace.blocks if block.block_id == "summary")
    assert effective_text(target) == target.source_text
    rejected = apply_decision(workspace, target.block_id, "rejected", decided_at="2026-10-22T09:10:00+00:00")
    block = next(block for block in rejected.blocks if block.block_id == target.block_id)
    assert effective_text(block) == block.source_text


def test_a_decision_is_dropped_when_the_proposal_changed_meanwhile() -> None:
    profile = synthetic_profile()
    saved = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=profile,
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    decided = apply_decision(saved, saved.blocks[0].block_id, "accepted", decided_at="2026-10-22T09:10:00+00:00")
    changed = dict(profile)
    changed["skills"] = "Excel, analyse financière, financial modeling, Bloomberg"
    fresh = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=changed,
        coverage=empty_coverage(),
        created_at="2026-10-22T09:20:00.000000+00:00",
    )
    merged, invalidated = merge_decisions(fresh, decided)
    assert "summary" in invalidated
    assert next(block for block in merged.blocks if block.block_id == "summary").status == "pending"


# --- 4. Règle de blocage de l'export ---------------------------------------


def test_export_is_blocked_while_a_critical_block_is_undecided() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    allowed, blockers = can_export(workspace)
    assert allowed is False
    assert blockers, "un blocage doit être explicite"


def test_export_is_allowed_once_every_critical_block_is_settled() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    settled = workspace
    for block in workspace.blocks:
        if not block.critical:
            continue
        if block.status == "pending":
            settled = apply_decision(
                settled, block.block_id, "modified", user_text="Preuve chiffrée (démo)", decided_at="2026-10-22T09:10:00+00:00"
            )
    allowed, blockers = can_export(settled)
    assert allowed is True, blockers
    assert review_progress(settled)["critical_pending"] == 0


def test_an_accepted_placeholder_still_blocks_the_export() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    placeholder = next(block for block in workspace.blocks if block.placeholder_reason)
    accepted = apply_decision(
        workspace, placeholder.block_id, "accepted", decided_at="2026-10-22T09:10:00+00:00"
    )
    allowed, blockers = can_export(accepted)
    if placeholder.critical:
        assert allowed is False
        assert any("preuve" in reason for reason in blockers)


def test_the_exported_markdown_never_carries_an_unresolved_marker() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    markdown = render_workspace_markdown(workspace)
    assert "AJOUTER PREUVE" not in markdown
    assert "Excel" in markdown


def test_a_requirement_proof_joins_its_own_section() -> None:
    """Un titre de section ne doit jamais apparaître deux fois dans l'export."""
    from career.cv_fit import FitGap

    coverage = replace(
        empty_coverage(),
        gaps=[
            FitGap(
                requirement="Expérience",
                requirement_type="mandatory",
                current_state="missing",
                adapted_state="Ajouter une preuve chiffrée.",
                provenance=None,
                variant_specific=True,
            )
        ],
    )
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=coverage,
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    requirement = next(block for block in workspace.blocks if block.block_id == "requirement-experience")
    assert requirement.section == "experiences"
    settled = apply_decision(
        workspace, requirement.block_id, "modified", user_text="Preuve chiffrée (démo)", decided_at="2026-10-22T09:10:00+00:00"
    )
    markdown = render_workspace_markdown(settled)
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert len(headings) == len(set(headings)), headings
    assert "Preuve chiffrée (démo)" in markdown


# --- 5. Persistance et historique immuable ---------------------------------


def test_workspace_round_trip(tmp_path: Path) -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    directory = tmp_path / "cv_review"
    save_workspace(directory, workspace)
    restored = load_workspace(directory, "app_demo", "m_a")
    assert restored is not None
    assert [block.block_id for block in restored.blocks] == [block.block_id for block in workspace.blocks]
    assert restored.blocks[0].status == workspace.blocks[0].status
    assert restored.header.display_name == workspace.header.display_name


def test_two_variants_keep_two_separate_reviews(tmp_path: Path) -> None:
    """Une décision prise sur une variante ne doit jamais played sur l'autre."""
    directory = tmp_path / "cv_review"
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    save_workspace(directory, workspace)
    other = replace(workspace, variant_id="markets")
    save_workspace(directory, other)
    assert load_workspace(directory, "app_demo", "m_a") is not None
    assert load_workspace(directory, "app_demo", "markets") is not None
    assert workspace_path(directory, "app_demo", "m_a") != workspace_path(directory, "app_demo", "markets")


def test_the_history_only_ever_grows(tmp_path: Path) -> None:
    directory = tmp_path / "cv_review"
    from career.cv_review import ReviewEvent

    append_event(
        directory,
        ReviewEvent("rev_1", "app_demo", "summary", "pending", "accepted", "", "2026-10-22T09:10:00+00:00", "user", 1, "m_a"),
    )
    first_read = history_path(directory, "app_demo", "m_a").read_text(encoding="utf-8")
    append_event(
        directory,
        ReviewEvent("rev_2", "app_demo", "summary", "accepted", "rejected", "", "2026-10-22T09:20:00+00:00", "user", 2, "m_a"),
    )
    second_read = history_path(directory, "app_demo", "m_a").read_text(encoding="utf-8")
    assert second_read.startswith(first_read)
    assert len(second_read) > len(first_read)
    events = read_events(directory, "app_demo", "m_a")
    assert [event.sequence for event in events] == [1, 2]
    assert [event.to_status for event in events] == ["accepted", "rejected"]
    assert read_events(directory, "app_demo", "markets") == []


def test_the_store_refuses_an_identifier_that_could_escape_the_folder(tmp_path: Path) -> None:
    directory = tmp_path / "cv_review"
    with pytest.raises(ValueError):
        workspace_path(directory, "../../etc/passwd")
    with pytest.raises(ValueError):
        history_path(directory, "app demo/../x")
    assert not (tmp_path.parent / "etc").exists()


def test_the_synthetic_workspace_fixture_is_replayable(tmp_path: Path) -> None:
    """La fixture d'état de revue se relit et se réécrit sans perte."""
    from career.cv_review_store import deserialize_workspace

    payload = json.loads((FIXTURES / "synthetic_workspace.json").read_text(encoding="utf-8"))
    workspace = deserialize_workspace(payload)
    assert workspace.application_id == "app_demo_review"
    assert workspace.variant_id == "m_a"
    assert len(workspace.blocks) == 3
    assert workspace.blocks[0].evidence is not None
    assert workspace.blocks[0].evidence[0].source == "profile.skills"
    directory = tmp_path / "cv_review"
    save_workspace(directory, workspace)
    restored = load_workspace(directory, "app_demo_review", "m_a")
    assert restored is not None
    assert len(restored.blocks) == 3
    assert restored.blocks[0].status == "accepted"


def test_a_stray_file_does_not_break_the_privacy_export(tmp_path: Path) -> None:
    """Un fichier temporaire laissé par un crash ne doit pas casser l'export."""
    from career.cv_review_store import list_workspaces

    directory = tmp_path / "cv_review"
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    save_workspace(directory, workspace)
    (directory / ".app_demo.m_a-9f8e7d6c.json").write_text("{}", encoding="utf-8")
    exported = list_workspaces(directory)
    assert len(exported) == 1
    assert exported[0]["application_id"] == "app_demo"


def test_the_decisions_are_rebuilt_from_the_history_when_the_state_is_lost(tmp_path: Path) -> None:
    """L'historique immuable est la source de vérité : l'état se rejoue."""
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    target = payload["blocks"][0]["block_id"]
    service.decide_cv_review_block(application_id, target, "modified", "Preuve (démo)")
    state = service.review_dir / f"{application_id}.m_a.json"
    assert state.exists()
    state.write_text("{ ceci n'est pas du json", encoding="utf-8")
    replayed = service.get_cv_review_workspace(application_id, "fr", "m_a")
    assert replayed["blocks"][0]["status"] == "modified"
    assert replayed["blocks"][0]["user_text"] == "Preuve (démo)"
    assert len(service.cv_review_history(application_id, "m_a")) == 1


def test_a_decision_on_a_stale_proposal_is_refused(tmp_path: Path) -> None:
    """La décision doit porter sur le texte qui a été lu."""
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    target = payload["blocks"][0]
    with pytest.raises(UserFacingError):
        service.decide_cv_review_block(
            application_id,
            target["block_id"],
            "accepted",
            "",
            "fr",
            "m_a",
            "une proposition que la personne n'a pas lue",
        )
    accepted = service.decide_cv_review_block(
        application_id,
        target["block_id"],
        "accepted",
        "",
        "fr",
        "m_a",
        target["proposed_text"],
    )
    assert accepted["blocks"][0]["status"] == "accepted"


def test_two_variants_keep_two_independent_reviews(tmp_path: Path) -> None:
    """Une décision sur une variante ne doit pas décider l'autre variante."""
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile())
    job = service.import_job(synthetic_job())
    kit = service.create_application_kit(job["id"], "fr", "m_a")
    application_id = str(kit["application"]["id"])
    service.create_application_kit(job["id"], "fr", "markets")
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    target = payload["blocks"][0]
    service.decide_cv_review_block(
        application_id, target["block_id"], "accepted", "", "fr", "m_a", target["proposed_text"]
    )
    ma = service.get_cv_review_workspace(application_id, "fr", "m_a")
    markets = service.get_cv_review_workspace(application_id, "fr", "markets")
    assert ma["variant_id"] == "m_a"
    assert markets["variant_id"] == "markets"
    assert next(block for block in ma["blocks"] if block["block_id"] == target["block_id"])["status"] == "accepted"
    assert next(block for block in markets["blocks"] if block["block_id"] == target["block_id"])["status"] == "pending"
    assert len(service.cv_review_history(application_id, "m_a")) == 1
    assert service.cv_review_history(application_id, "markets") == []


def test_the_header_is_covered_by_the_export_gate(tmp_path: Path) -> None:
    """Un marqueur de preuve resté dans l'en-tête bloque l'export."""
    service = CareerService(tmp_path)
    service.update_profile(
        {
            **synthetic_profile(),
            "education": "Master Finance — [AJOUTER PREUVE CHIFFRÉE]",
        }
    )
    job = service.import_job(synthetic_job())
    kit = service.create_application_kit(job["id"], "fr", "m_a")
    application_id = str(kit["application"]["id"])
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    for block in payload["blocks"]:
        if block["critical"] and block["status"] == "pending":
            service.decide_cv_review_block(application_id, block["block_id"], "modified", "Preuve (démo)")
    checked = service.get_cv_review_workspace(application_id, "fr", "m_a")
    assert checked["can_export"] is False
    assert any("En-tête" in reason for reason in checked["export_blockers"])
    with pytest.raises(UserFacingError):
        service.export_cv_review(application_id, "fr", "m_a")


def test_an_empty_workspace_can_never_be_exported() -> None:
    empty = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=None,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    allowed, blockers = can_export(empty)
    assert allowed is False
    assert blockers


def test_a_long_proposal_can_still_be_decided(tmp_path: Path) -> None:
    """Une proposition très longue ne doit pas rendre le bloc indécidable."""
    service = CareerService(tmp_path)
    long_skills = ", ".join(f"compétence-{index}" for index in range(400))
    service.update_profile({**synthetic_profile(), "skills": long_skills})
    job = service.import_job(synthetic_job())
    kit = service.create_application_kit(job["id"], "fr", "m_a")
    application_id = str(kit["application"]["id"])
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    target = next(block for block in payload["blocks"] if len(block["proposed_text"]) > 4_000)
    assert len(target["proposed_text"]) > 4_000
    answered = service.decide_cv_review_block(
        application_id,
        target["block_id"],
        "accepted",
        "",
        "fr",
        "m_a",
        target["proposed_text"],
    )
    assert next(block for block in answered["blocks"] if block["block_id"] == target["block_id"])["status"] == "accepted"


def test_the_history_wins_over_a_stale_state_snapshot(tmp_path: Path) -> None:
    """Un instantané périmé ne doit jamais cacher une décision tracée."""
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    target = payload["blocks"][0]["block_id"]
    service.decide_cv_review_block(application_id, target, "modified", "Preuve (démo)")
    state = service.review_dir / f"{application_id}.m_a.json"
    assert state.exists()
    state.write_text(
        json.dumps(
            {
                "format": "career-cv-review/1",
                "application_id": application_id,
                "variant_id": "m_a",
                "blocks": [],
            }
        ),
        encoding="utf-8",
    )
    replayed = service.get_cv_review_workspace(application_id, "fr", "m_a")
    assert next(block for block in replayed["blocks"] if block["block_id"] == target)["status"] == "modified"


def test_two_simultaneous_decisions_are_both_kept(tmp_path: Path) -> None:
    """Deux décisions concurrentes ne doivent pas s'écraser l'une l'autre."""
    import threading

    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    blocks = [block for block in payload["blocks"] if block["critical"]][:2]
    errors: list[Exception] = []

    def decide(block_id: str) -> None:
        try:
            service.decide_cv_review_block(application_id, block_id, "accepted", "", "fr", "m_a")
        except Exception as error:  # pragma: no cover - the assertion below reports it
            errors.append(error)

    threads = [threading.Thread(target=decide, args=(block["block_id"],)) for block in blocks]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    final = service.get_cv_review_workspace(application_id, "fr", "m_a")
    for block in blocks:
        assert next(item for item in final["blocks"] if item["block_id"] == block["block_id"])["status"] == "accepted"


def test_the_review_export_is_erased_by_a_reset(tmp_path: Path) -> None:
    """Une remise à zéro efface aussi les DOCX exportés par la revue."""
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    for block in payload["blocks"]:
        if block["critical"] and block["status"] == "pending":
            service.decide_cv_review_block(application_id, block["block_id"], "modified", "Preuve (démo)")
    exported = service.export_cv_review(application_id, "fr", "m_a")
    assert exported.exists()
    service.reset_personal_data("SUPPRIMER MES DONNÉES CAREER")
    assert not exported.exists()


# --- 6. Service local ------------------------------------------------------


def test_service_builds_a_workspace_for_a_tracked_application(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    assert payload["application_id"] == application_id
    assert payload["variant_id"] == "m_a"
    assert payload["blocks"]
    assert payload["progress"]["critical_total"] > 0
    assert payload["can_export"] is False
    assert payload["export_blockers"]


def test_a_decision_is_persisted_and_replayed(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    target = payload["blocks"][0]
    updated = service.decide_cv_review_block(application_id, target["block_id"], "modified", "Preuve (démo)")
    assert updated["blocks"][0]["status"] == "modified"
    assert updated["blocks"][0]["user_text"] == "Preuve (démo)"
    replayed = service.get_cv_review_workspace(application_id, "fr", "m_a")
    assert replayed["blocks"][0]["status"] == "modified"
    history = service.cv_review_history(application_id)
    assert len(history) == 1
    assert history[0]["to_status"] == "modified"
    assert history[0]["block_id"] == target["block_id"]


def test_an_unknown_block_is_refused_by_the_service(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    with pytest.raises(UserFacingError):
        service.decide_cv_review_block(application_id, "block-inexistant", "accepted")


def test_the_export_stays_blocked_until_the_critical_blocks_are_settled(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    with pytest.raises(UserFacingError):
        service.export_cv_review(application_id, "fr", "m_a")
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    for block in payload["blocks"]:
        if block["critical"] and block["status"] == "pending":
            service.decide_cv_review_block(application_id, block["block_id"], "modified", "Preuve chiffrée (démo)")
    allowed = service.get_cv_review_workspace(application_id, "fr", "m_a")
    assert allowed["can_export"] is True, allowed["export_blockers"]
    target = service.export_cv_review(application_id, "fr", "m_a")
    assert target.exists() and target.stat().st_size > 1_000
    with zipfile.ZipFile(target) as archive:
        assert "word/document.xml" in archive.namelist()
        document = archive.read("word/document.xml").decode("utf-8")
    assert "AJOUTER PREUVE" not in document
    assert "Preuve chiffrée" in document


def test_the_history_survives_a_new_workspace_build(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    application_id = tracked_application(service)
    payload = service.get_cv_review_workspace(application_id, "fr", "m_a")
    service.decide_cv_review_block(application_id, payload["blocks"][0]["block_id"], "accepted")
    service.decide_cv_review_block(application_id, payload["blocks"][0]["block_id"], "rejected")
    history = service.cv_review_history(application_id)
    assert [event["to_status"] for event in history] == ["accepted", "rejected"]
    assert [event["from_status"] for event in history] == ["pending", "accepted"]
    assert history[0]["decided_at"] <= history[1]["decided_at"]


# --- 7. HTTP ---------------------------------------------------------------


def test_review_routes_answer_the_full_journey(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = review_client(service)
    application_id = tracked_application(service)

    workspace = client.get(f"/api/career/applications/{application_id}/cv-review?variant=m_a")
    assert workspace.status_code == 200
    payload = workspace.json()
    assert payload["blocks"]
    assert payload["can_export"] is False

    blocked = client.get(f"/api/career/applications/{application_id}/cv-review/export")
    assert blocked.status_code == 400
    assert "bloqué" in blocked.json()["detail"].lower()

    for block in payload["blocks"]:
        if block["critical"] and block["status"] == "pending":
            answer = client.post(
                f"/api/career/applications/{application_id}/cv-review/decide",
                json={"block_id": block["block_id"], "status": "modified", "user_text": "Preuve chiffrée (démo)"},
            )
            assert answer.status_code == 200

    history = client.get(f"/api/career/applications/{application_id}/cv-review/history")
    assert history.status_code == 200
    assert history.json()["history"]

    exported = client.get(f"/api/career/applications/{application_id}/cv-review/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert exported.headers.get("cache-control") == "no-store"
    assert exported.content[:2] == b"PK"


def test_an_unknown_application_is_refused_over_http(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = review_client(service)
    answer = client.get("/api/career/applications/app_inexistant/cv-review")
    assert answer.status_code == 400
    assert "n’existe pas" in answer.json()["detail"]


def test_an_invalid_decision_status_is_refused_over_http(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = review_client(service)
    application_id = tracked_application(service)
    answer = client.post(
        f"/api/career/applications/{application_id}/cv-review/decide",
        json={"block_id": "summary", "status": "verified"},
    )
    assert answer.status_code == 422


# --- 8. Preuves statiques --------------------------------------------------


def test_the_review_module_has_no_network_and_no_dialog() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = [
        (root / "career" / "cv_review.py").read_text(encoding="utf-8"),
        (root / "career" / "cv_review_store.py").read_text(encoding="utf-8"),
        (root / "career_static" / "js" / "cv-review.js").read_text(encoding="utf-8"),
    ]
    for source in sources:
        for forbidden in ("import requests", "import httpx", "urllib.request", "http.client", "smtplib"):
            assert forbidden not in source, forbidden
        assert "window.prompt" not in source
        assert "mailto:" not in source


def test_the_review_interface_declares_the_four_decisions_and_the_badges() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "career_static" / "js" / "cv-review.js").read_text(encoding="utf-8")
    for marker in ("Accepter", "Modifier", "Refuser", "Source", "Vérifié", "À vérifier", "Placeholder"):
        assert marker in script, marker
    assert "Exporter" in script
    style = (root / "career_static" / "css" / "cv-review.css").read_text(encoding="utf-8")
    assert ".cv-review-diff" in style


def test_the_serialized_workspace_is_json_safe() -> None:
    workspace = build_workspace(
        "app_demo",
        job=synthetic_job(),
        job_id="j_demo",
        variant=MA_VARIANT,
        profile=synthetic_profile(),
        coverage=empty_coverage(),
        created_at="2026-10-22T09:00:00.000000+00:00",
    )
    payload = serialize_workspace(workspace)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert json.loads(encoded)["application_id"] == "app_demo"
    assert payload["checks"]
