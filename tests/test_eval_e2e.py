"""Tests for E2E metrics & evaluation (SPEC-044)."""

from __future__ import annotations

import json


from career.metrics import MetricsStore, StepTimer, new_run_id
from career.eval_e2e import load_offers, evaluate_offer, aggregate, render_report


def test_metrics_record_and_aggregate() -> None:
    store = MetricsStore(":memory:")
    rid = new_run_id()
    with StepTimer(store, rid, "step_a"):
        pass
    with StepTimer(store, rid, "step_b"):
        pass
    agg = store.aggregate(rid)
    assert "step_a" in agg
    assert "step_b" in agg
    assert store.total_duration(rid) >= 0.0
    store.close()


def test_metrics_pause_resume() -> None:
    store = MetricsStore(":memory:")
    rid = new_run_id()
    t = StepTimer(store, rid, "s")
    t.__enter__()
    t.pause()
    t.resume()
    t.__exit__()
    assert store.total_duration(rid) >= 0.0
    store.close()


def test_metrics_steps_for_run() -> None:
    store = MetricsStore(":memory:")
    rid = new_run_id()
    with StepTimer(store, rid, "x"):
        pass
    steps = store.steps_for_run(rid)
    assert len(steps) == 1
    assert steps[0].step == "x"
    store.close()


def test_load_offers_empty_dir(tmp_path) -> None:
    assert load_offers(tmp_path / "nope") == []


def test_load_offers_json(tmp_path) -> None:
    d = tmp_path / "offers"
    d.mkdir()
    (d / "o1.json").write_text(json.dumps({"title": "Stage M&A"}), encoding="utf-8")
    (d / "o2.txt").write_text("description text", encoding="utf-8")
    offers = load_offers(d)
    assert len(offers) == 2
    ids = {o["offer_id"] for o in offers}
    assert "o1" in ids
    assert "o2" in ids


def test_load_offers_skips_hidden(tmp_path) -> None:
    d = tmp_path / "offers"
    d.mkdir()
    (d / ".hidden.json").write_text(json.dumps({"title": "x"}), encoding="utf-8")
    assert load_offers(d) == []


def test_evaluate_offer_basic() -> None:
    offer = {"offer_id": "o1", "title": "Stage"}
    r = evaluate_offer(offer, dossier_text="Built a dashboard.", evidence=["Built a dashboard"])
    assert r.offer_id == "o1"
    assert r.quality_score >= 0.0
    assert isinstance(r.steps, dict)


def test_evaluate_offer_with_steps() -> None:
    calls = {"n": 0}

    def step():
        calls["n"] += 1

    offer = {"offer_id": "o2"}
    r = evaluate_offer(offer, steps={"s1": step})
    assert calls["n"] == 1
    assert "s1" in r.steps


def test_aggregate_empty() -> None:
    rep = aggregate([])
    assert rep.n_offers == 0
    assert rep.confidence.startswith("n=0")


def test_aggregate_basic() -> None:
    from career.eval_e2e import OfferResult
    r1 = OfferResult(offer_id="a", quality_score=80.0, errors_found=1, total_duration_sec=10.0)
    r2 = OfferResult(offer_id="b", quality_score=60.0, errors_found=2, total_duration_sec=20.0)
    rep = aggregate([r1, r2])
    assert rep.n_offers == 2
    assert rep.avg_quality_score == 70.0
    assert rep.total_errors == 3
    assert "indicatif" in rep.confidence


def test_render_report() -> None:
    from career.eval_e2e import OfferResult
    r = OfferResult(offer_id="a", quality_score=80.0, errors_found=1, total_duration_sec=10.0)
    rep = aggregate([r])
    text = render_report(rep)
    assert "Rapport E2E" in text
    assert "a" in text


def test_confidence_n10() -> None:
    from career.eval_e2e import OfferResult
    results = [OfferResult(offer_id=f"o{i}", quality_score=70.0) for i in range(10)]
    rep = aggregate(results)
    assert "n=10" in rep.confidence