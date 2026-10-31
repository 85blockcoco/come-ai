"""Tests for the weekly review aggregator (SPEC-036)."""

from __future__ import annotations

import json
from pathlib import Path


from career.weekly_review import (
    WeeklySummary,
    Objective,
    weekly_summary,
    objective_check,
    recommend_next,
    to_dict,
)


FIXTURE = Path(__file__).parent / "fixtures" / "weekly_synthetic.json"


def _events():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["events"]


def test_weekly_summary_counts() -> None:
    events = _events()
    s = weekly_summary(events, week="2026-W05")
    assert isinstance(s, WeeklySummary)
    assert s.applications_sent == 3
    assert s.responses == 2
    assert s.interviews == 1
    assert s.interview_rate == round(1 / 3, 4)


def test_objective_met_true() -> None:
    events = _events()
    obj = Objective(metric="applications", target=2)
    s = weekly_summary(events, week="2026-W05", objective=obj)
    assert s.objective_met is True


def test_objective_met_false() -> None:
    events = _events()
    obj = Objective(metric="applications", target=10)
    s = weekly_summary(events, week="2026-W05", objective=obj)
    assert s.objective_met is False


def test_objective_absent_is_none() -> None:
    events = _events()
    s = weekly_summary(events, week="2026-W05", objective=None)
    assert s.objective_met is None


def test_top_actions_max_three() -> None:
    events = _events()
    obj = Objective(metric="applications", target=10)
    s = weekly_summary(events, week="2026-W05", objective=obj)
    assert len(s.top_actions) <= 3


def test_empty_events() -> None:
    s = weekly_summary([], week="2026-W05")
    assert s.applications_sent == 0
    assert s.responses == 0
    assert s.interviews == 0
    assert s.interview_rate == 0.0
    assert s.objective_met is None
    assert "Envoyer au moins une candidature cette semaine." in s.top_actions


def test_no_responses_recommends_targeting() -> None:
    events = [
        {"status": "sent", "date": "2026-01-26"},
        {"status": "sent", "date": "2026-01-27"},
    ]
    s = weekly_summary(events, week="2026-W05")
    assert s.applications_sent == 2
    assert s.responses == 0
    assert any("ciblage" in a for a in s.top_actions)


def test_objective_check_helper() -> None:
    s = WeeklySummary(iso_week="2026-W05", applications_sent=5, responses=2, interviews=1, interview_rate=0.2, objective_met=None)
    obj = Objective(metric="responses", target=2)
    assert objective_check(s, obj) is True
    obj2 = Objective(metric="responses", target=5)
    assert objective_check(s, obj2) is False
    assert objective_check(s, None) is None


def test_recommend_next_cap() -> None:
    actions = recommend_next(
        applications_sent=0, responses=0, interviews=0,
        objective=Objective(metric="applications", target=5), objective_met=False,
    )
    assert len(actions) <= 3


def test_to_dict() -> None:
    s = WeeklySummary(iso_week="2026-W05", applications_sent=1, responses=1, interviews=1, interview_rate=1.0, objective_met=True, top_actions=["a"])
    d = to_dict(s)
    assert d["iso_week"] == "2026-W05"
    assert d["top_actions"] == ["a"]


def test_week_inference() -> None:
    events = [
        {"status": "sent", "date": "2026-01-26"},
        {"status": "sent", "date": "2026-02-02"},
    ]
    s = weekly_summary(events)
    # most recent week
    assert s.iso_week == "2026-W06"


def test_adversarial_empty_objective_target() -> None:
    # target 0 → met if actual >= 0 (always true for non-negative)
    obj = Objective(metric="applications", target=0)
    s = weekly_summary([], week="2026-W05", objective=obj)
    assert s.objective_met is True