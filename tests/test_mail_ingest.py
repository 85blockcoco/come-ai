"""Tests for mail ingestion (SPEC-039)."""

from __future__ import annotations


import pytest

from career.mail_states import (
    MailState, is_recruiter_email, classify_state, make_evidence,
)
from career.mail_ingest import (
    consent_granted, MailConfig, purge_old, ingest,
)


def test_consent_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CAREER_MAIL_CONSENT", raising=False)
    assert consent_granted() is False


def test_consent_on(monkeypatch) -> None:
    monkeypatch.setenv("CAREER_MAIL_CONSENT", "1")
    assert consent_granted() is True


def test_is_recruiter_by_domain() -> None:
    assert is_recruiter_email("Hello", "hr@greenhouse.io") is True


def test_is_recruiter_by_subject() -> None:
    assert is_recruiter_email("Interview invitation", "someone@example.com") is True


def test_is_not_recruiter() -> None:
    assert is_recruiter_email("Lunch tomorrow?", "friend@gmail.com") is False


def test_classify_interview() -> None:
    assert classify_state("Interview invitation", "") == MailState.INTERVIEW


def test_classify_rejected() -> None:
    assert classify_state("We regret to inform you", "") == MailState.REJECTED


def test_classify_assessment() -> None:
    assert classify_state("Technical assessment", "") == MailState.ASSESSMENT


def test_classify_received() -> None:
    assert classify_state("Application received", "") == MailState.RECEIVED


def test_make_evidence() -> None:
    ev = make_evidence("m1", "subj", "a@b.com", "2026-01-01", "abc123", MailState.RECEIVED)
    assert ev.message_id == "m1"
    assert ev.state == MailState.RECEIVED


def test_purge_old() -> None:
    import datetime
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=800)
    recent = datetime.datetime.now(datetime.timezone.utc)
    records = [
        {"received_at": old.isoformat(), "id": "old"},
        {"received_at": recent.isoformat(), "id": "new"},
    ]
    out = purge_old(records, months=24)
    ids = {r["id"] for r in out}
    assert "new" in ids
    assert "old" not in ids


def test_purge_keeps_unparseable() -> None:
    records = [{"received_at": "not-a-date", "id": "x"}]
    out = purge_old(records, months=24)
    assert len(out) == 1


def test_ingest_requires_consent(monkeypatch) -> None:
    monkeypatch.delenv("CAREER_MAIL_CONSENT", raising=False)
    cfg = MailConfig(host="imap.example.com", login="u", password="p")
    with pytest.raises(PermissionError):
        ingest(cfg)


def test_fetch_headers_requires_consent(monkeypatch) -> None:
    monkeypatch.delenv("CAREER_MAIL_CONSENT", raising=False)
    cfg = MailConfig(host="imap.example.com", login="u", password="p")
    with pytest.raises(PermissionError):
        # fetch_headers checks consent first
        from career.mail_ingest import fetch_headers
        fetch_headers(cfg)


def test_mail_state_enum_values() -> None:
    assert MailState.PENDING_CONFIRMATION.value == "pending_user_confirmation"