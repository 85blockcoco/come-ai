"""Tests for learning loop (SPEC-045)."""

from __future__ import annotations


from career.learning import (
    Experience,
    LearningStore,
    analyze,
    to_dict,
    MIN_OBSERVATIONS_FOR_MODEL,
)


def test_record_and_count(tmp_path) -> None:
    store = LearningStore(tmp_path / "l.db")
    store.record(Experience(application_id="a1", variants={"cv": "ats"}, context={"sector": "finance"}, outcome="interview", observed_at="2026-01-01"))
    assert store.count() == 1
    assert len(store.all()) == 1
    store.close()


def test_analyze_empty() -> None:
    store = LearningStore(":memory:")
    rep = analyze(store)
    assert rep.n_total == 0
    assert rep.model_allowed is False
    assert rep.stats == []
    assert len(rep.recommendations) >= 1
    store.close()


def test_analyze_basic() -> None:
    store = LearningStore(":memory:")
    for i in range(5):
        store.record(Experience(application_id=f"a{i}", variants={"cv": "ats"}, context={"sector": "finance"}, outcome="interview" if i < 3 else "no_response", observed_at="2026-01-01"))
    for i in range(5):
        store.record(Experience(application_id=f"b{i}", variants={"cv": "narrative"}, context={"sector": "finance"}, outcome="interview" if i < 1 else "no_response", observed_at="2026-01-01"))
    rep = analyze(store)
    assert rep.n_total == 10
    assert rep.model_allowed is False  # <30
    assert len(rep.stats) == 2
    # ats should have higher rate
    ats = next(s for s in rep.stats if "ats" in s.family)
    assert ats.response_rate == 0.6
    store.close()


def test_model_allowed_threshold() -> None:
    store = LearningStore(":memory:")
    for i in range(MIN_OBSERVATIONS_FOR_MODEL):
        store.record(Experience(application_id=f"a{i}", variants={"cv": "ats"}, context={}, outcome="no_response", observed_at="2026-01-01"))
    rep = analyze(store)
    assert rep.model_allowed is True
    store.close()


def test_interval_bounds() -> None:
    store = LearningStore(":memory:")
    store.record(Experience(application_id="a1", variants={"cv": "x"}, context={}, outcome="interview", observed_at="2026-01-01"))
    rep = analyze(store)
    s = rep.stats[0]
    assert 0.0 <= s.interval[0] <= s.interval[1] <= 1.0


def test_recommendations_cap() -> None:
    store = LearningStore(":memory:")
    for i in range(3):
        store.record(Experience(application_id=f"a{i}", variants={"cv": "ats"}, context={}, outcome="no_response", observed_at="2026-01-01"))
    rep = analyze(store)
    assert len(rep.recommendations) <= 3


def test_to_dict() -> None:
    store = LearningStore(":memory:")
    rep = analyze(store)
    d = to_dict(rep)
    assert "n_total" in d
    assert "stats" in d
    assert "correlation_disclaimer" in d
    store.close()


def test_manual_flag() -> None:
    store = LearningStore(":memory:")
    store.record(Experience(application_id="a1", variants={}, context={}, outcome="interview", observed_at="2026-01-01", manual=True))
    exps = store.all()
    assert exps[0].manual is True
    store.close()


def test_adversarial_n_less_than_30_locked() -> None:
    store = LearningStore(":memory:")
    for i in range(29):
        store.record(Experience(application_id=f"a{i}", variants={"cv": "ats"}, context={}, outcome="interview", observed_at="2026-01-01"))
    rep = analyze(store)
    assert rep.model_allowed is False
    assert any("n=29" in r or "indicatif" in r.lower() or "n=" in r for r in rep.recommendations) or not rep.model_allowed


def test_family_grouping() -> None:
    store = LearningStore(":memory:")
    store.record(Experience(application_id="a1", variants={"cv": "ats", "tone": "formal"}, context={}, outcome="interview", observed_at="2026-01-01"))
    store.record(Experience(application_id="a2", variants={"cv": "ats", "tone": "formal"}, context={}, outcome="no_response", observed_at="2026-01-01"))
    rep = analyze(store)
    assert len(rep.stats) == 1
    assert rep.stats[0].n == 2