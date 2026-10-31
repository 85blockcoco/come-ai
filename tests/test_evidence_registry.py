"""Tests for evidence registry (N100-D04)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.evidence_registry import Evidence, EvidenceRegistry


@pytest.fixture
def reg(tmp_path: Path) -> EvidenceRegistry:
    return EvidenceRegistry(tmp_path / "ev.jsonl")


def test_add_and_list(reg: EvidenceRegistry) -> None:
    ev = reg.add("Managed team of 5", "cv_2024", approved=True)
    assert isinstance(ev, Evidence)
    assert ev.claim == "Managed team of 5"
    assert len(reg.list()) == 1


def test_get(reg: EvidenceRegistry) -> None:
    ev = reg.add("Fact", "source")
    assert reg.get(ev.evidence_id) is not None
    assert reg.get("nope") is None


def test_approved_filter(reg: EvidenceRegistry) -> None:
    reg.add("a", "s1", approved=True)
    reg.add("b", "s2", approved=False)
    assert len(reg.list(approved_only=True)) == 1


def test_chain_verifies(reg: EvidenceRegistry) -> None:
    for i in range(5):
        reg.add(f"fact {i}", "src")
    ok, err = reg.verify_chain()
    assert ok is True
    assert err is None


def test_chain_tampering_detected(reg: EvidenceRegistry) -> None:
    for i in range(3):
        reg.add(f"fact {i}", "src")
    lines = reg.path.read_text(encoding="utf-8").splitlines()
    obj = json.loads(lines[1])
    obj["claim"] = "TAMPERED"
    lines[1] = json.dumps(obj)
    reg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, err = reg.verify_chain()
    assert ok is False
    assert err is not None


def test_empty_registry() -> None:
    import tempfile
    p = Path(tempfile.mkdtemp()) / "empty.jsonl"
    r = EvidenceRegistry(p)
    assert r.list() == []
    ok, err = r.verify_chain()
    assert ok is True


def test_no_delete_update_api(reg: EvidenceRegistry) -> None:
    assert not hasattr(reg, "delete")
    assert not hasattr(reg, "update")
    assert not hasattr(reg, "remove")


def test_approved_at(reg: EvidenceRegistry) -> None:
    ev = reg.add("f", "s", approved=True, approved_at="2026-01-01")
    assert ev.approved_at == "2026-01-01"