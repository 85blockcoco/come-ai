from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from career.stage_fit_kit import (
    StageFitKit,
    StageFitKitOrchestrator,
    StageFitScorecard,
    build_stage_fit_kit,
)
from career.stage_fit_scorer import (
    StageFitScorer,
    compute_stage_fit_scorecard,
    score_stage_fit,
)
from career.stage_fit_router import create_stage_fit_router


def test_scorecard_dataclass_fields() -> None:
    card = StageFitScorecard(
        offer_id="o1",
        ats_before=40.0,
        ats_after=80.0,
        keyword_coverage_before=30.0,
        keyword_coverage_after=70.0,
        gaps_unresolved=["gap"],
        jury_summary={"jury": 0.9},
        evidence_audit={"pct": 100.0},
    )
    assert card.offer_id == "o1"
    assert card.ats_after == 80.0


def test_kit_dataclass_fields() -> None:
    card = StageFitScorecard(offer_id="o1")
    kit = StageFitKit(kit_id="k1", offer_id="o1", scorecard=card)
    assert kit.kit_id == "k1"
    assert kit.scorecard.offer_id == "o1"


def test_scorer_builds_scorecard() -> None:
    card = compute_stage_fit_scorecard(
        offer_id="o1",
        ats_before=50.0,
        ats_after=90.0,
        keyword_coverage_before=40.0,
        keyword_coverage_after=85.0,
        gaps_unresolved=["g"],
        jury_summary={"a": 0.8},
        evidence_audit={"x": 1},
    )
    assert card.ats_before == 50.0
    assert card.gaps_unresolved == ["g"]
    assert score_stage_fit("o1", ats_before=10.0).offer_id == "o1"
    scorer = StageFitScorer()
    assert scorer.score(offer_id="o2").offer_id == "o2"


def test_orchestrator_resumable(tmp_path: Path) -> None:
    orch = StageFitKitOrchestrator(base_dir=tmp_path)
    kit = orch.run_pipeline("offer-1")
    assert kit.kit_id
    assert (tmp_path / "career_data" / "stage_fit_kits" / f"{kit.kit_id}.json").exists()
    # resume by offer reuses kit
    kit2 = orch.run_pipeline("offer-1")
    assert kit2.kit_id == kit.kit_id
    # rerun forced creates trace
    kit3 = orch.rerun(kit.kit_id, force=True)
    assert kit3.kit_id == kit.kit_id


def test_orchestrator_async(tmp_path: Path) -> None:
    orch = StageFitKitOrchestrator(base_dir=tmp_path)
    kit = asyncio.run(orch.abuild_kit("offer-2"))
    assert kit.offer_id == "offer-2"


def test_module_helper(tmp_path: Path) -> None:
    kit = build_stage_fit_kit("offer-3", base_dir=tmp_path)
    assert isinstance(kit, StageFitKit)
    assert kit.docx_path.endswith(".docx")
    assert Path(kit.docx_path).exists()


def test_router_endpoints(tmp_path: Path) -> None:
    orch = StageFitKitOrchestrator(base_dir=tmp_path)
    router = create_stage_fit_router(orchestrator=orch)
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post("/stagefit/kit/offer-4")
    assert resp.status_code == 200
    data = resp.json()
    kit_id = data["kit_id"]
    get_resp = client.get(f"/stagefit/kit/{kit_id}")
    assert get_resp.status_code == 200
    exp = client.get(f"/stagefit/kit/{kit_id}/export")
    assert exp.status_code == 200


def test_service_integration(tmp_path: Path) -> None:
    from career.service import CareerService

    service = CareerService(tmp_path)
    kit = service.create_stage_fit_kit("offer-5")
    assert kit["kit_id"]
    got = service.get_stage_fit_kit(kit["kit_id"])
    assert got is not None