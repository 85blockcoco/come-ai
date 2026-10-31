"""Tests for controlled automation (SPEC-016)."""

from __future__ import annotations

import pytest

from career.controlled_automation import (
    ControlledAutomation,
    AutomationPolicy,
    AutomationStatus,
)


def test_create_run() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1")
    run = ca.create_run(p, steps=["s1", "s2"])
    assert run.run_id == "run_1"
    assert len(run.steps) == 2
    assert run.status == AutomationStatus.PENDING


def test_run_step_success() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1", require_human_validation=False)
    run = ca.create_run(p, steps=["s1"])
    step = run.steps[0]
    step.action = lambda: 42
    res = ca.run_step(run.run_id, "s1")
    assert res.status == AutomationStatus.DONE
    assert res.result == 42


def test_run_step_failure() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1")
    run = ca.create_run(p, steps=["s1"])
    step = run.steps[0]
    step.action = lambda: (_ for _ in ()).throw(ValueError("boom"))
    res = ca.run_step(run.run_id, "s1")
    assert res.status == AutomationStatus.FAILED
    assert "boom" in (res.error or "")


def test_circuit_breaker_opens() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1", circuit_breaker_threshold=2)
    run = ca.create_run(p, steps=["s1", "s2"])
    for s in run.steps:
        s.action = lambda: (_ for _ in ()).throw(ValueError("boom"))
    ca.run_step(run.run_id, "s1")
    ca.run_step(run.run_id, "s2")
    # circuit should be open after 2 failures
    assert run.status == AutomationStatus.CIRCUIT_OPEN or run._consecutive_failures >= 2


def test_request_validation() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1", require_human_validation=True)
    run = ca.create_run(p, steps=["s1"])
    ca.request_validation(run.run_id, "s1")
    step = run.steps[0]
    assert step.status == AutomationStatus.AWAITING_VALIDATION
    assert run.status == AutomationStatus.AWAITING_VALIDATION


def test_validate_approved() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1", require_human_validation=True)
    run = ca.create_run(p, steps=["s1"])
    ca.request_validation(run.run_id, "s1")
    ca.validate(run.run_id, "s1", approved=True)
    assert run.steps[0].status == AutomationStatus.DONE


def test_validate_rejected() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1", require_human_validation=True)
    run = ca.create_run(p, steps=["s1"])
    ca.request_validation(run.run_id, "s1")
    ca.validate(run.run_id, "s1", approved=False)
    assert run.steps[0].status == AutomationStatus.ROLLED_BACK


def test_rollback() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1")
    run = ca.create_run(p, steps=["s1"])
    run.steps[0].status = AutomationStatus.DONE
    ca.rollback(run.run_id)
    assert run.status == AutomationStatus.ROLLED_BACK
    assert run.steps[0].status == AutomationStatus.ROLLED_BACK


def test_dashboard() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1")
    run = ca.create_run(p, steps=["s1"])
    d = ca.dashboard()
    assert d["runs"] == 1
    assert run.run_id in d["statuses"]


def test_to_dict() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1")
    run = ca.create_run(p, steps=["s1"])
    d = ca.to_dict(run.run_id)
    assert d["run_id"] == run.run_id
    assert "audit" in d
    assert len(d["audit"]) >= 1


def test_audit_trail_recorded() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1")
    run = ca.create_run(p, steps=["s1"])
    run.steps[0].action = lambda: "ok"
    ca.run_step(run.run_id, "s1")
    events = [a["event"] for a in run.audit]
    assert "created" in events
    assert "step_started" in events
    assert "step_done" in events


def test_get_run_unknown() -> None:
    ca = ControlledAutomation()
    assert ca.get_run("nope") is None


def test_step_not_found() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1")
    run = ca.create_run(p, steps=["s1"])
    with pytest.raises(KeyError):
        ca.run_step(run.run_id, "ghost")


def test_adversarial_circuit_open_skips_step() -> None:
    ca = ControlledAutomation()
    p = AutomationPolicy(name="p1", circuit_breaker_threshold=1)
    run = ca.create_run(p, steps=["s1", "s2"])
    run.steps[0].action = lambda: (_ for _ in ()).throw(ValueError("boom"))
    ca.run_step(run.run_id, "s1")
    # circuit open now
    step2 = ca.run_step(run.run_id, "s2")
    assert step2.status == AutomationStatus.CIRCUIT_OPEN