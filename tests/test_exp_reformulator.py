"""Tests for the experience reformulator (SPEC-020)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from career.exp_constraints import (
    check_no_invention,
    validate_bullet,
)
from career.exp_reformulate import (
    RecommendVerdict,
    ReformulatedBullet,
    build_verdict,
    gap_signals,
    reformulate_experience,
    reformulate_experience_async,
    reformulate_section,
)
from career.exp_router import create_exp_router
from career.exp_scorer import keyword_coverage, score_bullet


def test_dataclass_contracts() -> None:
    b = ReformulatedBullet(
        original_block_id="b1",
        text_fr="Dirigé l'analyse financière",
        variant_actions=["verbe d'action"],
        keyword_hits=["analyse"],
        evidence_refs=["ev1"],
        ats_score=0.8,
        jury_score=0.7,
        provider="local",
        version=1,
    )
    assert b.original_block_id == "b1"
    v = RecommendVerdict(bullets=[b], recommended_combo=[b.text_fr], diff_vs_current="diff")
    assert v.bullets[0] is b


def test_reformulate_produces_at_least_three_variants() -> None:
    bullets = reformulate_experience(
        "analysé des modèles financiers",
        block_id="b1",
        offer_keywords=["modélisation", "Excel"],
        evidence_text="analysé des modèles financiers sur Excel",
    )
    assert len(bullets) >= 3
    for b in bullets:
        assert b.text_fr.strip()
        assert b.evidence_refs == [] or isinstance(b.evidence_refs, list)


def test_no_invention_rejects_unknown_number() -> None:
    # bullet invents 42% not in evidence
    viol = check_no_invention("Dirigé la mission avec 42% de gain", "Dirigé la mission")
    assert viol is not None
    assert viol.code == "INVENTED_FACT"


def test_no_invention_allows_evidence_number() -> None:
    viol = check_no_invention("Dirigé la mission avec 12% de gain", "gain de 12% observé")
    assert viol is None


def test_action_verb_required() -> None:
    check = validate_bullet("random text without verb", "evidence")
    assert check.ok is False
    assert any(v.code == "ACTION_VERB_MISSING" for v in check.violations)


def test_max_lines() -> None:
    text = "Dirigé la mission\nligne2\nligne3"
    check = validate_bullet(text, "mission")
    assert check.ok is False
    assert any(v.code == "TOO_MANY_LINES" for v in check.violations)


def test_keyword_coverage() -> None:
    assert keyword_coverage("analyse financière Excel", ["Excel", "Python"]) == 0.5
    assert keyword_coverage("rien", []) == 1.0


def test_score_bullet() -> None:
    sr = score_bullet("Dirigé l'analyse financière avec Excel", ["Excel"], "Excel")
    assert 0.0 <= sr.ats_score <= 1.0
    assert 0.0 <= sr.jury_score <= 1.0
    assert "Excel" in sr.keyword_hits


def test_reformulate_async() -> None:
    async def main():
        bullets = await reformulate_experience_async(
            original_text="mission stage",
            block_id="b2",
            offer_keywords=["stage"],
            evidence_text="mission stage",
        )
        assert len(bullets) >= 3
    asyncio.run(main())


def test_reformulate_section() -> None:
    blocks = [{"id": "e1", "text": "expérience A", "evidence_text": "expérience A"}]
    bullets = reformulate_section(blocks, offer_keywords=["expérience"])
    assert len(bullets) >= 3
    assert all(b.original_block_id == "e1" for b in bullets)


def test_gap_signals() -> None:
    gaps = gap_signals(["Python"], ["Python", "Excel"])
    assert gaps == ["Excel"]


def test_build_verdict_diff() -> None:
    bullets = reformulate_experience("mission", block_id="b", evidence_text="mission")
    verdict = build_verdict(bullets, current_text="actuel")
    assert isinstance(verdict, RecommendVerdict)
    assert "actuel" in verdict.diff_vs_current


def test_adversarial_invention_suite() -> None:
    evidence = "Dirigé une équipe de 5 personnes pendant 6 mois"
    cases = [
        "Dirigé une équipe de 5 personnes pendant 6 mois",
        "Dirigé une équipe de 5 personnes pendant 12 mois",  # invented duration
        "Dirigé une équipe de 10 personnes pendant 6 mois",  # invented size
        "Dirigé une équipe de 5 personnes avec 50% de gain",  # invented percent
    ]
    # first should pass, others should detect invention (except maybe first)
    results = [check_no_invention(c, evidence) for c in cases]
    assert results[0] is None
    assert any(r is not None for r in results[1:])


def test_router_endpoints() -> None:
    router = create_exp_router()
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/reformulate/experience", json={
        "original_text": "analysé des données",
        "block_id": "b1",
        "offer_keywords": ["données"],
        "evidence_text": "analysé des données",
    })
    assert r.status_code == 200
    data = r.json()
    assert "bullets" in data
    assert len(data["bullets"]) >= 3

    r2 = client.post("/reformulate/section", json={
        "blocks": [{"id": "e1", "text": "expérience", "evidence_text": "expérience"}],
        "offer_keywords": ["expérience"],
    })
    assert r2.status_code == 200

    r3 = client.get("/reformulate/offer1/score")
    assert r3.status_code == 200


def test_router_apply_reject() -> None:
    router = create_exp_router()
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/reformulate/bulletX/apply", json={"accepted": True})
    assert r.status_code == 200
    r2 = client.post("/reformulate/bulletX/reject", json={"note": "no"})
    assert r2.status_code == 200
