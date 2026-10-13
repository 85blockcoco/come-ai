"""Offline tests for the V6 local usage observability ledger."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from usage_ledger import (
    CacheState,
    CostState,
    FallbackState,
    UsageLedger,
    UsageLedgerError,
    UsageOutcome,
    VerificationState,
)


UTC = timezone.utc


def instant(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC)


def make_ledger(tmp_path: Path, *, max_events: int = 50_000) -> UsageLedger:
    return UsageLedger(tmp_path / "state" / "usage-ledger.sqlite3", max_events=max_events)


def test_persists_declared_facts_and_redacts_sensitive_tags(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    # Synthetic credential-shaped values only; no real key is present in tests.
    raw_key = "sk_" + "x" * 32
    raw_gemini_key = "AIza" + "y" * 28

    event = ledger.record_execution(
        provider="gemini",
        model=raw_key,
        mode="performance",
        task_kind="document.index",
        outcome=UsageOutcome.FAILED,
        occurred_at=instant(7, 10, 5),
        latency_ms=125,
        input_tokens=12,
        output_tokens=7,
        total_tokens=19,
        cache_state=CacheState.MISS,
        retry_count=0,
        error_category=f"api_key={raw_gemini_key}",
        fallback_state=FallbackState.NOT_USED,
        verification_state=VerificationState.NOT_VERIFIED,
        cost=Decimal("0.0125"),
        cost_currency="usd",
    )

    restored = UsageLedger(ledger.database_path).list_events(limit=1)[0]
    assert restored.id == event.id
    assert restored.provider == "gemini"
    assert restored.model == "redacted"
    assert restored.error_category == "redacted"
    assert restored.latency_ms == 125
    assert restored.total_tokens == 19
    assert restored.retry_count == 0
    assert restored.cost_state is CostState.KNOWN
    assert restored.cost_amount == "0.0125"
    assert restored.cost_currency == "USD"

    # No credential/prompt-like free text reaches SQLite, including its WAL.
    persisted = b"".join(
        path.read_bytes()
        for path in tmp_path.rglob("usage-ledger.sqlite3*")
        if path.is_file()
    )
    assert raw_key.encode() not in persisted
    assert raw_gemini_key.encode() not in persisted


def test_hour_day_week_month_aggregates_preserve_unknown_measurements(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    ledger.record_execution(
        provider="gemini",
        model="gemini-2.5-flash",
        mode="automatic",
        task_kind="spreadsheet.analysis",
        occurred_at=instant(7, 10, 5),
        latency_ms=120,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cache_state="miss",
        retry_count=0,
        fallback_state="not_used",
        verification_state="verified",
        cost="0.003",
        cost_currency="USD",
    )
    # The runtime did not report these metrics.  The ledger must not invent
    # zero tokens, zero latency, zero retries, or a zero provider price.
    ledger.record_execution(
        provider="gemini",
        model="gemini-2.5-flash",
        mode="automatic",
        task_kind="spreadsheet.analysis",
        occurred_at=instant(7, 10, 45),
        cache_state="unknown",
        fallback_state="unknown",
        verification_state="unknown",
    )
    ledger.record_execution(
        provider="ollama",
        model="llama3.2",
        mode="local",
        task_kind="study.quiz",
        occurred_at=instant(8, 11, 0),
        latency_ms=80,
        input_tokens=8,
        output_tokens=4,
        total_tokens=12,
        cache_state="bypass",
        retry_count=0,
        fallback_state="not_used",
        verification_state="verified",
    )

    hourly = ledger.aggregate_hourly()
    assert [bucket["event_count"] for bucket in hourly] == [2, 1]
    first_hour = hourly[0]["summary"]
    assert first_hour["latency_ms"] == {
        "state": "partial",
        "measured_count": 1,
        "unknown_count": 1,
        "complete": False,
        "measured_sum": 120,
        "measured_average": 120.0,
        "measured_min": 120,
        "measured_max": 120,
    }
    assert first_hour["total_tokens"]["state"] == "partial"
    assert first_hour["total_tokens"]["measured_sum"] == 15
    assert first_hour["retry_count"]["state"] == "partial"
    assert first_hour["cost"] == {
        "state": "partial",
        "known_count": 1,
        "unknown_count": 1,
        "not_incurred_count": 0,
        "complete_for_chargeable_events": False,
        "by_currency": [
            {
                "currency": "USD",
                "measured_sum": "0.003",
                "event_count": 1,
                "has_unknown_cost_events": True,
            }
        ],
    }

    daily = ledger.aggregate_daily()
    weekly = ledger.aggregate_weekly()
    monthly = ledger.aggregate_monthly()
    assert [bucket["event_count"] for bucket in daily] == [2, 1]
    assert weekly[0]["event_count"] == 3
    assert monthly[0]["event_count"] == 3
    assert weekly[0]["start_at"] == "2026-01-05T00:00:00.000+00:00"
    assert monthly[0]["start_at"] == "2026-01-01T00:00:00.000+00:00"


def test_zero_spend_refusal_is_not_misreported_as_an_unknown_or_zero_price(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    refused = ledger.record_zero_spend_refusal(
        provider="openai",
        model="gpt-5",
        mode="performance",
        task_kind="career.cover_letter",
        occurred_at=instant(7, 12),
    )

    assert refused.outcome is UsageOutcome.REFUSED
    assert refused.zero_spend_refused is True
    assert refused.cost_state is CostState.NOT_INCURRED
    assert refused.cost_amount is None
    assert refused.cost_currency is None

    summary = ledger.dashboard_summary(now=instant(7, 12, 30))["all_time"]
    assert summary["zero_spend_refusal_count"] == 1
    assert summary["cost"] == {
        "state": "not_incurred",
        "known_count": 0,
        "unknown_count": 0,
        "not_incurred_count": 1,
        "complete_for_chargeable_events": True,
        "by_currency": [],
    }


def test_dashboard_and_retention_are_persistent_and_bounded(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path, max_events=2)
    for day in (1, 2, 3):
        ledger.record_execution(
            provider="ollama",
            model="qwen2.5",
            mode="local",
            task_kind="study.flashcards",
            occurred_at=instant(day, 9),
            latency_ms=day,
            retry_count=0,
        )

    restored = UsageLedger(ledger.database_path, max_events=2)
    events = restored.list_events(limit=10)
    assert len(events) == 2
    assert [event.latency_ms for event in events] == [3, 2]
    dashboard = restored.dashboard_summary(now=instant(4, 9))
    assert dashboard["retention"] == {"max_events": 2, "current_events": 2}
    assert dashboard["database"]["journal_mode"] == "wal"
    assert dashboard["all_time"]["latency_ms"]["state"] == "measured"
    assert dashboard["all_time"]["latency_ms"]["measured_sum"] == 5

    with sqlite3.connect(ledger.database_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_csv_export_contains_only_safe_metadata_and_never_a_prompt_column(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    raw_key = "AIza" + "z" * 28
    ledger.record_execution(
        provider="gemini",
        model=raw_key,
        mode="free",
        task_kind="document.import",
        occurred_at=instant(7, 14),
        error_category=f"authorization=Bearer {raw_key}",
    )
    destination = tmp_path / "exports" / "usage.csv"
    result = ledger.export_csv(destination)

    assert result == {
        "status": "ready",
        "event_count": 1,
        "filename": "usage.csv",
        "bytes": destination.stat().st_size,
        "contains_prompt_content": False,
        "contains_raw_error_messages": False,
    }
    exported = destination.read_text(encoding="utf-8")
    assert raw_key not in exported
    assert "prompt" not in exported.lower()
    assert "error_summary" not in exported
    with destination.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["model"] == "redacted"
    assert rows[0]["error_category"] == "redacted"
    assert rows[0]["cost_state"] == "unknown"

    with pytest.raises(UsageLedgerError, match="écrasement"):
        ledger.export_csv(destination)
    with pytest.raises(UsageLedgerError, match="contenu libre"):
        ledger.record_execution(
            provider="gemini",
            model="gemini-2.5-flash",
            mode="free",
            task_kind="Voici le contenu d’un prompt qui ne doit jamais être journalisé",
        )


def test_provider_retry_after_is_stored_only_when_the_provider_reported_it(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    # Nothing declared: the field stays empty instead of guessing a delay.
    ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="automatic",
                            task_kind="general", outcome="failed", error_category="quota")
    assert ledger.list_events()[0].retry_after_seconds is None

    ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="automatic",
                            task_kind="general", outcome="failed", error_category="quota",
                            retry_after_seconds=3600)
    ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="automatic",
                            task_kind="general", outcome="failed", error_category="quota",
                            retry_after_seconds=0)
    stored = [event for event in ledger.list_events() if event.retry_after_seconds is not None]
    assert {event.to_dict()["retry_after_seconds"] for event in stored} == {0, 3600}
    assert {event.retry_after_seconds for event in UsageLedger(ledger.database_path).list_events()
            if event.retry_after_seconds is not None} == {0, 3600}

    # A local invention of a delay is refused, not clamped into the record.
    with pytest.raises(UsageLedgerError):
        ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="automatic",
                                task_kind="general", retry_after_seconds=90000)
    with pytest.raises(UsageLedgerError):
        ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="automatic",
                                task_kind="general", retry_after_seconds=True)


def test_existing_ledger_gains_the_retry_after_column_without_losing_events(tmp_path: Path) -> None:
    import sqlite3

    legacy = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        """
        CREATE TABLE usage_ledger_events (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
            mode TEXT NOT NULL, task_kind TEXT NOT NULL, outcome TEXT NOT NULL,
            occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL, latency_ms INTEGER,
            input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
            cache_state TEXT NOT NULL, retry_count INTEGER, error_category TEXT,
            fallback_state TEXT NOT NULL, verification_state TEXT NOT NULL,
            cost_state TEXT NOT NULL, cost_amount TEXT, cost_currency TEXT,
            zero_spend_refused INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    connection.execute(
        """
        INSERT INTO usage_ledger_events
            (id, provider, model, mode, task_kind, outcome, occurred_at, recorded_at,
             cache_state, fallback_state, verification_state, cost_state)
        VALUES ('legacy-1', 'gemini', 'gemini-3.8-flash', 'automatic', 'general',
                'succeeded', '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00',
                'unknown', 'not_used', 'not_verified', 'unknown')
        """
    )
    original_columns = [row[1] for row in connection.execute("PRAGMA table_info(usage_ledger_events)")]
    original_rows = connection.execute("SELECT * FROM usage_ledger_events").fetchall()
    connection.commit()
    connection.close()

    ledger = UsageLedger(legacy)
    events = ledger.list_events()
    assert len(events) == 1
    assert events[0].id == "legacy-1"
    assert events[0].retry_after_seconds is None
    # Opening the ledger again must not repeat or replace the migration.
    assert UsageLedger(legacy).list_events()[0].to_dict() == events[0].to_dict()
    with sqlite3.connect(legacy) as connection:
        preserved = connection.execute("SELECT " + ", ".join(original_columns) + " FROM usage_ledger_events").fetchall()
    assert preserved == original_rows
    # The migrated database is writable again with the new field.
    ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="automatic",
                            task_kind="general", outcome="failed", error_category="quota",
                            retry_after_seconds=0)
    assert len(ledger.list_events()) == 2
    assert next(event for event in ledger.list_events() if event.id != "legacy-1").retry_after_seconds == 0
