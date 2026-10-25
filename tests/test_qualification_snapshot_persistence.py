"""Regression tests for safe, source-attributed qualification persistence."""

from __future__ import annotations

import copy
import sqlite3

from career.application_prep import summarize_offer
from career.offer_qualification import qualify_offer
from career.service import CareerService, SCHEMA_VERSION


def _payload(*, month: int = 1, quote: str = "starting January 2027") -> dict:
    return {
        "company": "Synthetic Bank",
        "title": "Investment Banking Intern",
        "source_name": "greenhouse",
        "source_id": "synthetic-1",
        "official_url": "https://boards.greenhouse.io/synthetic-bank/jobs/synthetic-1",
        "description_original": f"Internship {quote} for six months.",
        "source_verified": True,
        "qualification": {
            "contract_type": "internship",
            "contract_status": "confirmed",
            "start_month": month,
            "duration_min_months": 6,
            "duration_max_months": 6,
            "verification_status": "verified",
            "target_status": "conforming",
            "missing_fields": ["jour de début vérifiable"],
            "reasons": ["Stage confirmé sur la source vérifiée."],
            "provenance": {
                "contract_type": {
                    "value": "internship",
                    "source": "title_passage",
                    "quote": "Intern",
                },
                "start_month": {
                    "value": month,
                    "source": "description_passage",
                    "quote": quote,
                },
                "duration_min_months": {
                    "value": 6,
                    "source": "description_passage",
                    "quote": "six months",
                },
            },
        },
    }


def test_import_does_not_mutate_payload_or_invent_exact_dates(tmp_path) -> None:
    service = CareerService(tmp_path)
    payload = _payload()
    original = copy.deepcopy(payload)

    result = service.import_job(payload)

    assert payload == original
    assert result["start_date"] is None
    assert result["end_date"] is None
    assert result["duration_months"] is None
    assert result["employment_type"] == ""
    facts = result["qualification_facts"]
    assert facts["start_month"] == 1
    assert facts["duration_min_months"] == 6
    assert facts["contract_type"] == "internship"
    assert facts["provenance"]["start_month"]["quote"] == "starting January 2027"


def test_new_snapshot_schema_is_additive_and_versioned(tmp_path) -> None:
    service = CareerService(tmp_path)
    with sqlite3.connect(service.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 8
        columns = {row[1] for row in connection.execute("PRAGMA table_info(job_qualification_snapshots)")}
    assert {
        "job_id",
        "schema_version",
        "facts_json",
        "provenance_json",
        "missing_fields_json",
        "reasons_json",
        "source_fingerprint",
        "updated_at",
    } <= columns


def test_v7_migration_creates_private_backup_and_preserves_jobs(tmp_path) -> None:
    service = CareerService(tmp_path)
    created = service.import_job(_payload())
    with sqlite3.connect(service.db_path) as connection:
        connection.execute("DROP TABLE job_qualification_snapshots")
        connection.execute("PRAGMA user_version = 7")

    migrated = CareerService(tmp_path)

    with sqlite3.connect(migrated.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert connection.execute(
            "SELECT company FROM jobs WHERE id = ?", (created["id"],)
        ).fetchone()[0] == "Synthetic Bank"
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "job_qualification_snapshots" in tables
    backups = list(migrated.backups_dir.glob("career-before-v7-to-v8-*.sqlite3"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o077 == 0


def test_repeated_import_refreshes_snapshot_but_preserves_user_source_fields(tmp_path) -> None:
    service = CareerService(tmp_path)
    first = service.import_job(_payload())
    with sqlite3.connect(service.db_path) as connection:
        connection.execute(
            "UPDATE jobs SET start_date = '2027-01-15', employment_type = 'user-confirmed' WHERE id = ?",
            (first["id"],),
        )

    refreshed_payload = _payload(month=2, quote="starting February 2027")
    refreshed_payload["start_date"] = ""
    refreshed_payload["employment_type"] = ""
    refreshed = service.import_job(refreshed_payload, preserve_unknown_source_fields=True)

    assert refreshed["start_date"] == "2027-01-15"
    assert refreshed["employment_type"] == "user-confirmed"
    assert refreshed["qualification_facts"]["start_month"] == 2
    assert refreshed["qualification_facts"]["provenance"]["start_month"]["quote"] == "starting February 2027"


def test_import_without_qualification_keeps_last_snapshot(tmp_path) -> None:
    service = CareerService(tmp_path)
    first = service.import_job(_payload())
    unqualified = _payload()
    unqualified.pop("qualification")
    unqualified["title"] = "Investment Banking Intern — refreshed"

    refreshed = service.import_job(unqualified)

    assert refreshed["id"] == first["id"]
    assert refreshed["qualification_facts"]["start_month"] == 1


def test_summary_uses_snapshot_and_keeps_unknowns_explicit(tmp_path) -> None:
    service = CareerService(tmp_path)
    qualified = service.import_job(_payload())
    summary = summarize_offer(qualified)
    assert summary["contract_type"] == "internship"
    assert summary["start_month"] == 1
    assert summary["duration_min_months"] == 6
    assert summary["qualification_status"] == "conforming"
    assert summary["qualification_missing"] == ["jour de début vérifiable"]

    unknown_payload = _payload()
    unknown_payload["source_id"] = "synthetic-2"
    unknown_payload["official_url"] = "https://example.test/jobs/synthetic-2"
    unknown_payload.pop("qualification")
    unknown = service.import_job(unknown_payload)
    unknown_summary = summarize_offer(unknown)
    assert unknown_summary["contract_type"] == "unknown"
    assert unknown_summary["start_month"] is None
    assert unknown_summary["duration_min_months"] is None
    assert unknown_summary["qualification_status"] == "to_verify"


def test_snapshot_is_removed_with_its_job(tmp_path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_payload())
    service.delete_job(job["id"])
    with sqlite3.connect(service.db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM job_qualification_snapshots WHERE job_id = ?", (job["id"],)
        ).fetchone()[0]
    assert count == 0


def test_verified_source_survives_storage_and_restart_for_live_matching(tmp_path) -> None:
    service = CareerService(tmp_path)
    service.update_stage_search({
        "domains": ["M&A"], "contract_types": ["stage"], "start_months": [1],
        "minimum_stage_duration_months": 6,
    })
    payload = _payload()
    payload.update(
        start_date="2027-01-05", duration_months=6, employment_type="Internship",
        language="English", country="United Kingdom", city="London",
    )
    payload["qualification"] = qualify_offer(payload).to_dict()
    created = service.import_job(payload)

    reopened = CareerService(tmp_path)
    stored = reopened.get_job(created["id"])
    assert stored["qualification_snapshot_current"] is True
    assert stored["source_verified"] is True
    match = reopened.list_stage_matches()["matches"][0]
    assert match["qualification"]["verification_status"] == "verified"
    assert match["qualification"]["target_status"] == "conforming"


def test_manual_claim_does_not_create_persisted_source_verification(tmp_path) -> None:
    service = CareerService(tmp_path)
    payload = _payload()
    payload.pop("qualification")
    payload.update(start_date="2027-01-05", duration_months=6, source_verified=True)
    stored = service.import_job(payload)
    assert stored["qualification_snapshot_current"] is False
    assert stored["source_verified"] is False
    assert stored["official_source_trust"]["status"] == "verified"


def test_unverified_same_source_refresh_does_not_downgrade_verified_snapshot(tmp_path) -> None:
    service = CareerService(tmp_path)
    trusted = _payload()
    trusted.update(
        source_name="greenhouse",
        source_id="synthetic-verified",
        official_url="https://boards.greenhouse.io/synthetic-bank/jobs/synthetic-verified",
        source_verified=True,
        start_date="2027-01-05",
        duration_months=6,
        employment_type="Internship",
        language="English",
        country="United Kingdom",
        city="London",
    )
    trusted["qualification"] = qualify_offer(trusted).to_dict()
    saved = service.import_job(trusted)
    assert saved["source_verified"] is True

    unverified = dict(trusted)
    unverified.pop("source_verified")
    unverified["qualification"] = qualify_offer(unverified).to_dict()
    refreshed = service.import_job(unverified)

    assert refreshed["id"] == saved["id"]
    assert refreshed["qualification_snapshot_current"] is True
    assert refreshed["source_verified"] is True
    assert refreshed["qualification_facts"]["verification_status"] == "verified"
