"""Tests for followup engine (N100-H05)."""

from __future__ import annotations

from career.followup_engine import due_followups, FollowUp, to_dict


def test_due_after_7_days() -> None:
    apps = [{"id": "a1", "status": "sent", "last_contact": "2026-01-01"}]
    out = due_followups(apps, today="2026-01-10")
    assert len(out) == 1
    assert out[0].application_id == "a1"


def test_not_due() -> None:
    apps = [{"id": "a1", "status": "sent", "last_contact": "2026-01-09"}]
    out = due_followups(apps, today="2026-01-10")
    assert len(out) == 0


def test_rejected_skipped() -> None:
    apps = [{"id": "a1", "status": "rejected", "last_contact": "2026-01-01"}]
    out = due_followups(apps, today="2026-01-10")
    assert len(out) == 0


def test_high_priority_after_14() -> None:
    apps = [{"id": "a1", "status": "sent", "last_contact": "2025-12-20"}]
    out = due_followups(apps, today="2026-01-10")
    assert out[0].priority == "high"


def test_to_dict() -> None:
    f = FollowUp(application_id="a1", due_date="2026-01-10", reason="r")
    d = to_dict(f)
    assert d["application_id"] == "a1"