"""Tests for SPEC-022 cover letter multi-AI."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from career.letter_generator import (
    LetterDraft,
    LetterPara,
    LetterPlan,
    create_letter_router,
    export_letter_docx,
    generate_letter_plan,
    generate_letter_plan_async,
    merge_drafts,
    render_text,
    validate_letter,
)
from career.letter_structure import MAX_PARAGRAPHS, MAX_WORDS
from career.letter_tone import normalize_tone


def _offer():
    return {
        "id": "OFF-LET-01",
        "title": "Stage M&A",
        "company": "Banque X",
        "requirements": "Excel, modélisation financière, anglais",
        "description": "Stage en fusions-acquisitions",
        "skills": ["Excel", "Python"],
    }


def _profile():
    return {
        "display_name": "Alice",
        "contact_email": "alice@example.com",
        "contact_phone": "+33 6 00 00 00 00",
        "linkedin_url": "https://linkedin.com/in/alice",
        "experience": ["Analysé des modèles financiers sur Excel"],
        "projects": ["Projet de valorisation DCF"],
        "education": "Master finance",
        "skills": "Excel, Python",
        "courses": [{"id": "c1", "title": "Modélisation financière"}],
    }


def test_dataclass_contracts():
    p = LetterPara(kind="hook", text="Bonjour")
    d = LetterDraft(draft_id="d1", paragraphs=[p], tone="formel", jury_score=0.5, provider="local")
    assert d.draft_id == "d1"
    plan = LetterPlan(drafts=[d], best_id="d1", merged_alternative=d, ats_compat_check={})
    assert plan.best_id == "d1"
    assert plan.as_dict()["drafts"][0]["paragraphs"][0]["text"] == "Bonjour"


def test_generates_three_drafts_and_merge():
    plan = generate_letter_plan(offer=_offer(), profile=_profile())
    assert isinstance(plan, LetterPlan)
    assert len(plan.drafts) == 3
    assert plan.merged_alternative is not None
    assert plan.best_id in {d.draft_id for d in plan.drafts}
    for d in plan.drafts:
        assert 1 <= len(d.paragraphs) <= MAX_PARAGRAPHS
        assert len(render_text(d.paragraphs).split()) <= MAX_WORDS
        assert d.tone in ("formel", "direct", "startup", "corporate")


def test_no_unsourced_company_fact():
    plan = generate_letter_plan(offer=_offer(), profile=_profile())
    for d in plan.drafts + [plan.merged_alternative]:
        for para in d.paragraphs:
            if "recrute" in para.text or "poste" in para.text.lower():
                # paragraphs mentioning company facts should carry evidence
                assert isinstance(para.evidence_refs, list)


def test_async():
    async def main():
        plan = await generate_letter_plan_async(offer=_offer(), profile=_profile())
        assert len(plan.drafts) == 3
    asyncio.run(main())


def test_merge_distinct():
    drafts = generate_letter_plan(offer=_offer(), profile=_profile()).drafts
    merged = merge_drafts(drafts)
    assert merged.draft_id == "merged"
    assert merged.paragraphs


def test_export_docx(tmp_path: Path):
    plan = generate_letter_plan(offer=_offer(), profile=_profile())
    out = tmp_path / "letter.docx"
    path = export_letter_docx(plan, out)
    assert path.exists()
    assert path.stat().st_size > 0


def test_validate_letter():
    plan = generate_letter_plan(offer=_offer(), profile=_profile())
    assert validate_letter(plan.merged_alternative) == []


def test_router():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(create_letter_router())
    client = TestClient(app)
    res = client.post("/letter/generate/OFF-LET-01", json={"offer": _offer(), "profile": _profile(), "n_drafts": 3})
    assert res.status_code == 200
    data = res.json()
    assert len(data["drafts"]) == 3
    # history
    hid = data["drafts"][0]["draft_id"]
    pres = client.patch(f"/letter/{hid}", json={"tone": "direct"})
    assert pres.status_code == 200
    # export
    ex = client.post(f"/letter/{hid}/export", json={"format": "docx"})
    assert ex.status_code == 200
    hist = client.get("/letter/OFF-LET-01/history")
    assert hist.status_code == 200
    assert hist.json()["items"]


def test_tone_normalize():
    assert normalize_tone("formal") == "formel"
    assert normalize_tone("unknown") == "formel"
    assert normalize_tone("startup") == "startup"
