"""Tests for the append-only audit journal (SPEC-035)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.audit_journal import AuditJournal, AuditEntry, AuditExplanation, register_narrative


@pytest.fixture
def journal(tmp_path: Path) -> AuditJournal:
    return AuditJournal(tmp_path / "audit.jsonl")


def test_record_creates_entry(journal: AuditJournal) -> None:
    entry = journal.record("offer_ranked", context={"job_id": "j1", "score": 0.8}, outcome={"rank": 1})
    assert isinstance(entry, AuditEntry)
    assert entry.decision_type == "offer_ranked"
    assert entry.context == {"job_id": "j1", "score": 0.8}
    assert entry.outcome == {"rank": 1}
    assert entry.decision_id
    assert entry.at
    assert entry.entry_hash
    assert journal.count() == 1


def test_record_append_only(journal: AuditJournal) -> None:
    a = journal.record("offer_ranked", context={"job_id": "j1"}, outcome={"rank": 1})
    b = journal.record("followup_scheduled", context={"job_id": "j1"}, outcome={"scheduled_at": "2026-01-02"})
    assert journal.count() == 2
    entries = journal.entries()
    assert [e.decision_id for e in entries] == [a.decision_id, b.decision_id]


def test_filter_by_type(journal: AuditJournal) -> None:
    journal.record("offer_ranked", context={"job_id": "j1"}, outcome={"rank": 1})
    journal.record("followup_scheduled", context={"job_id": "j1"}, outcome={"scheduled_at": "x"})
    ranked = journal.entries(decision_type="offer_ranked")
    assert len(ranked) == 1
    assert ranked[0].decision_type == "offer_ranked"


def test_filter_by_id(journal: AuditJournal) -> None:
    e = journal.record("arena_verdict", context={"job_id": "j2"}, outcome={"verdict": "ok"})
    found = journal.entries(decision_id=e.decision_id)
    assert len(found) == 1
    assert found[0].decision_id == e.decision_id


def test_explain_returns_narrative(journal: AuditJournal) -> None:
    e = journal.record("offer_ranked", context={"job_id": "j1", "score": 0.9}, outcome={"rank": 1})
    exp = journal.explain(e.decision_id)
    assert isinstance(exp, AuditExplanation)
    assert exp.entry.decision_id == e.decision_id
    assert "j1" in exp.narrative
    assert isinstance(exp.contributing_factors, list)


def test_explain_unknown_id_returns_none(journal: AuditJournal) -> None:
    assert journal.explain("does-not-exist") is None


def test_chain_verifies_clean(journal: AuditJournal) -> None:
    for i in range(5):
        journal.record("offer_ranked", context={"i": i}, outcome={"rank": i})
    ok, err = journal.verify_chain()
    assert ok is True
    assert err is None


def test_chain_detects_tampering(journal: AuditJournal, tmp_path: Path) -> None:
    for i in range(3):
        journal.record("offer_ranked", context={"i": i}, outcome={"rank": i})
    # Tamper with the middle entry.
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    obj = json.loads(lines[1])
    obj["outcome"]["rank"] = 999
    lines[1] = json.dumps(obj, ensure_ascii=False)
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, err = journal.verify_chain()
    assert ok is False
    assert err is not None
    assert "incohérent" in err


def test_chain_detects_reordered_entries(journal: AuditJournal) -> None:
    for i in range(3):
        journal.record("offer_ranked", context={"i": i}, outcome={"rank": i})
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    # Swap first and last.
    lines[0], lines[2] = lines[2], lines[0]
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, err = journal.verify_chain()
    assert ok is False
    assert err is not None


def test_no_delete_or_update_api(journal: AuditJournal) -> None:
    # The public API must not expose mutation helpers.
    assert not hasattr(journal, "delete")
    assert not hasattr(journal, "update")
    assert not hasattr(journal, "remove")


def test_custom_narrative_registration(journal: AuditJournal) -> None:
    def fn(entry):
        return f"custom: {entry.decision_id}"
    register_narrative("custom_type", fn)
    e = journal.record("custom_type", context={}, outcome={})
    exp = journal.explain(e.decision_id)
    assert exp is not None
    assert exp.narrative.startswith("custom: ")


def test_since_filter(journal: AuditJournal) -> None:
    journal.record("offer_ranked", context={"i": 0}, outcome={}, at="2026-01-01T00:00:00+00:00")
    journal.record("offer_ranked", context={"i": 1}, outcome={}, at="2026-02-01T00:00:00+00:00")
    res = journal.entries(since="2026-01-15T00:00:00+00:00")
    assert len(res) == 1
    assert res[0].context["i"] == 1


def test_limit(journal: AuditJournal) -> None:
    for i in range(5):
        journal.record("offer_ranked", context={"i": i}, outcome={})
    res = journal.entries(limit=2)
    assert len(res) == 2
    assert res[-1].context["i"] == 4


def test_empty_journal_verifies(journal: AuditJournal) -> None:
    ok, err = journal.verify_chain()
    assert ok is True
    assert err is None
    assert journal.count() == 0


def test_contributing_factors_numeric(journal: AuditJournal) -> None:
    e = journal.record(
        "offer_ranked",
        context={"score": 0.85, "is_internship": True},
        outcome={"rank": 3, "confidence": 0.9},
    )
    exp = journal.explain(e.decision_id)
    assert exp is not None
    names = {f[0] for f in exp.contributing_factors}
    assert "score" in names
    assert "rank" in names
    assert "is_internship" in names