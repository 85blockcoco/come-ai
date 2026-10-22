"""Offline tests of SPEC-006 -- freshness, completeness, trust and duplicates.

Every test is local and deterministic: no network request, no public job
board, no private data.  The dates are injected, so the verdicts never
depend on the day the suite runs.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from career.offer_quality import (
    OFFER_QUALITY_FIELDS,
    assess,
    assess_completeness,
    assess_deduplication,
    assess_freshness,
    assess_offer,
    assess_source_trust,
    deadline_hint_from_text,
    detect_changes,
    offer_facts,
    source_tier,
    tier_label,
)
from career.offer_quality_store import MAX_HISTORY_PER_OFFER, OfferQualityStore, probe_source_status
from career.service import CareerService
from come_ai_web import create_app


NOW = datetime(2026, 10, 21, 8, 0, 0, tzinfo=timezone.utc)


def complete_offer(**changes: Any) -> dict[str, Any]:
    """Return an offer that carries every expected fact."""

    offer: dict[str, Any] = {
        "id": "job_1",
        "company": "Acme",
        "title": "Analyste financier",
        "source_name": "greenhouse",
        "source_id": "123",
        "official_url": "https://boards.greenhouse.io/acme/jobs/123",
        "description_original": "Stage de six mois au sein de la direction financière.",
        "requirements": "Master en finance de marché",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-10-25",
        "duration_months": 6,
        "employment_type": "stage",
        "source_status": "open",
        "last_verified_at": "2026-10-21T08:00:00Z",
    }
    offer.update(changes)
    return offer


def partner_offer(**changes: Any) -> dict[str, Any]:
    """Return the same offer published on a partner platform."""

    offer = complete_offer(
        id="job_2",
        source_name="jobteaser",
        source_id="789",
        official_url="https://www.jobteaser.com/fr/poste/acme/analyste/789",
    )
    offer.update(changes)
    return offer


# ---------------------------------------------------------------------------
# 1. The contract
# ---------------------------------------------------------------------------

def test_assess_offer_returns_the_contract_of_the_mission() -> None:
    quality = assess_offer(complete_offer(), offer_id="job_1", now=NOW, source_url_status=200)
    payload = quality.to_dict()
    assert set(OFFER_QUALITY_FIELDS) <= set(payload)
    assert payload["offer_id"] == "job_1"
    assert set(payload["freshness"]) >= {
        "last_verified_at",
        "source_url_status",
        "source_url",
        "is_active",
        "deadline_date",
        "days_until_deadline",
        "changes_since_last_check",
    }
    assert set(payload["completeness"]) >= {
        "score",
        "missing_fields",
        "has_requirements",
        "has_location",
        "has_dates",
    }
    assert set(payload["source_trust"]) >= {"status", "provider", "canonical_host", "employer_match"}
    assert set(payload["deduplication"]) >= {"canonical_id", "sources", "merged_from", "contradictions"}
    assert payload["freshness"]["days_until_deadline"] == 4
    assert payload["freshness"]["source_url_status"] == 200


def test_the_contract_is_json_serializable() -> None:
    payload = assess_offer(complete_offer(), offer_id="job_1", now=NOW).to_dict()
    assert json.loads(json.dumps(payload, ensure_ascii=False))["offer_id"] == "job_1"


# ---------------------------------------------------------------------------
# 2. Freshness
# ---------------------------------------------------------------------------

def test_a_recently_verified_offer_is_fresh() -> None:
    freshness = assess_freshness(complete_offer(), now=NOW, source_url_status=200)
    assert freshness.status == "fresh"
    assert freshness.is_active is True
    assert freshness.age_days == 0
    assert freshness.reasons


def test_an_offer_verified_long_ago_is_stale() -> None:
    freshness = assess_freshness(
        complete_offer(last_verified_at="2026-09-01T08:00:00Z"), now=NOW, source_url_status=200
    )
    assert freshness.status == "stale"
    assert freshness.age_days == 50
    assert any("périmées" in reason for reason in freshness.reasons)


def test_an_offer_verified_a_week_ago_needs_a_recheck() -> None:
    freshness = assess_freshness(
        complete_offer(last_verified_at="2026-10-10T08:00:00Z"), now=NOW, source_url_status=200
    )
    assert freshness.status == "aging"
    assert freshness.age_days == 11


def test_an_offer_never_verified_has_an_unknown_freshness() -> None:
    freshness = assess_freshness(complete_offer(last_verified_at=""), now=NOW)
    assert freshness.status == "unknown"
    assert freshness.age_days is None
    assert any("jamais vérifiée" in reason for reason in freshness.reasons)


def test_a_passed_deadline_expires_the_offer() -> None:
    freshness = assess_freshness(
        complete_offer(deadline_date="2026-10-01"), now=NOW, source_url_status=200
    )
    assert freshness.is_active is False
    assert freshness.status == "expired"
    assert freshness.days_until_deadline == -20


def test_a_closed_source_expires_the_offer() -> None:
    freshness = assess_freshness(complete_offer(source_status="closed"), now=NOW, source_url_status=200)
    assert freshness.is_active is False
    assert freshness.status == "expired"


def test_a_missing_page_expires_the_offer() -> None:
    freshness = assess_freshness(complete_offer(), now=NOW, source_url_status=404)
    assert freshness.is_active is False
    assert freshness.status == "expired"
    assert any("404" in reason for reason in freshness.reasons)


def test_a_server_error_does_not_expire_the_offer() -> None:
    freshness = assess_freshness(complete_offer(), now=NOW, source_url_status=503)
    assert freshness.is_active is True
    assert freshness.status == "fresh"
    assert any("ne prouve pas" in reason for reason in freshness.reasons)


def test_the_deadline_written_in_the_description_is_used_when_the_field_is_empty() -> None:
    offer = complete_offer(deadline_date="", description_original="Postulez avant le 25 octobre 2026.")
    hint = deadline_hint_from_text(offer)
    freshness = assess_freshness(offer, now=NOW, deadline_hint=hint)
    assert freshness.deadline_date == "2026-10-25"
    assert freshness.days_until_deadline == 4


# ---------------------------------------------------------------------------
# 3. Completeness
# ---------------------------------------------------------------------------

def test_the_completeness_score_matches_the_example_of_the_mission() -> None:
    offer = complete_offer(salary_range="", duration_months=None)
    completeness = assess_completeness(offer)
    assert completeness.score == 84
    assert completeness.missing_fields == ["duration_months", "salary_range"]
    assert completeness.has_requirements is True
    assert completeness.has_location is True
    assert completeness.has_dates is True


def test_a_complete_offer_scores_one_hundred() -> None:
    completeness = assess_completeness(complete_offer(salary_range="50-60k€"))
    assert completeness.score == 100
    assert completeness.missing_fields == []


def test_an_empty_offer_scores_zero_and_lists_everything() -> None:
    completeness = assess_completeness({})
    assert completeness.score == 0
    assert completeness.has_requirements is False
    assert completeness.has_location is False
    assert completeness.has_dates is False
    assert "requirements" in completeness.missing_fields


def test_a_missing_duration_is_not_counted_as_a_fact() -> None:
    assert assess_completeness(complete_offer(duration_months=0)).missing_fields != []
    assert "duration_months" in assess_completeness(complete_offer(duration_months=0)).missing_fields


# ---------------------------------------------------------------------------
# 4. Source trust (SPEC-SK-01)
# ---------------------------------------------------------------------------

def test_the_trust_of_an_official_board_is_the_verdict_of_spec_sk01() -> None:
    trust = assess_source_trust(complete_offer(), checked_at="2026-10-21T08:00:00Z")
    assert trust.status == "verified"
    assert trust.provider == "greenhouse"
    assert trust.canonical_host == "boards.greenhouse.io"
    assert trust.employer_match == "confirmed"
    assert trust.registry_evidence
    assert trust.reasons


def test_a_partner_platform_is_not_an_official_source() -> None:
    trust = assess_source_trust(partner_offer(), checked_at="2026-10-21T08:00:00Z")
    assert trust.status == "missing"
    assert trust.employer_match == "unknown"
    assert any("plateforme partenaire" in reason.lower() for reason in trust.reasons)


def test_a_link_without_an_official_source_is_missing() -> None:
    trust = assess_source_trust(complete_offer(official_url="", source_name="manual"))
    assert trust.status == "missing"
    assert trust.reasons


def test_a_declared_provider_that_contradicts_the_link_is_contradictory() -> None:
    offer = complete_offer(source_name="lever", official_url="https://boards.greenhouse.io/acme/jobs/123")
    trust = assess_source_trust(offer, checked_at="2026-10-21T08:00:00Z")
    assert trust.status == "contradictory"


# ---------------------------------------------------------------------------
# 5. Deduplication (SPEC-SK-06)
# ---------------------------------------------------------------------------

def test_the_duplicates_are_merged_without_losing_their_provenance() -> None:
    deduplication = assess_deduplication(complete_offer(), [partner_offer()], checked_at="2026-10-21T08:00:00Z")
    assert deduplication.canonical_id.startswith("canon_")
    assert [source.provider for source in deduplication.sources] == ["greenhouse", "jobteaser"]
    assert deduplication.merged_from == ["greenhouse:123", "jobteaser:789"]
    assert deduplication.duplicate_count == 1
    assert deduplication.primary_provider == "greenhouse"


def test_the_official_employer_page_is_the_priority_source() -> None:
    employer_page = complete_offer(
        id="job_3",
        source_name="company_career",
        source_id="acme-77",
        official_url="https://careers.acme.com/jobs/77",
    )
    deduplication = assess_deduplication(
        complete_offer(), [partner_offer(), employer_page], checked_at="2026-10-21T08:00:00Z"
    )
    assert deduplication.primary_provider == "company_career"
    assert deduplication.sources[2].is_primary is True
    assert len(deduplication.sources) == 3


def test_the_contradictions_between_the_sources_stay_visible() -> None:
    deduplication = assess_deduplication(
        complete_offer(), [partner_offer(employment_type="internship")], checked_at="2026-10-21T08:00:00Z"
    )
    assert deduplication.contradictions
    assert "employment_type" in deduplication.contradictions[0]


def test_an_offer_known_by_one_source_has_no_duplicate() -> None:
    deduplication = assess_deduplication(complete_offer(), [], checked_at="2026-10-21T08:00:00Z")
    assert deduplication.duplicate_count == 0
    assert deduplication.merged_from == ["greenhouse:123"]


def test_the_source_tiers_follow_the_table_of_the_mission() -> None:
    assert source_tier("company_career") == 1
    assert source_tier("greenhouse") == 2
    assert source_tier("lever") == 2
    assert source_tier("ashby") == 2
    assert source_tier("smartrecruiters") == 2
    assert source_tier("welcometothejungle") == 3
    assert source_tier("jobteaser") == 3
    assert source_tier("talent_com") == 3
    assert source_tier("apec") == 3
    assert source_tier("indeed") == 4
    assert source_tier("manual") == 5
    assert tier_label(1) == "Page officielle entreprise"
    assert tier_label(5) == "Saisie manuelle"


# ---------------------------------------------------------------------------
# 6. The changes
# ---------------------------------------------------------------------------

def test_the_first_check_never_invents_a_change() -> None:
    assert detect_changes(None, offer_facts(complete_offer()), "2026-10-21T08:00:00Z") == []


def test_a_changed_field_is_reported_with_its_old_and_new_values() -> None:
    previous = offer_facts(complete_offer())
    current = offer_facts(complete_offer(deadline_date="2026-11-05"))
    changes = detect_changes(previous, current, "2026-10-21T08:00:00Z")
    assert len(changes) == 1
    assert changes[0].field == "deadline_date"
    assert changes[0].old == "2026-10-25"
    assert changes[0].new == "2026-11-05"
    assert changes[0].detected_at == "2026-10-21T08:00:00Z"


def test_a_field_that_disappeared_is_reported() -> None:
    previous = offer_facts(complete_offer())
    current = offer_facts(complete_offer(duration_months=None))
    changes = detect_changes(previous, current, "2026-10-21T08:00:00Z")
    assert [change.field for change in changes] == ["duration_months"]
    assert changes[0].old == 6
    assert changes[0].new is None


def test_the_changes_are_listed_in_the_freshness_of_the_offer() -> None:
    previous = offer_facts(complete_offer())
    quality = assess_offer(
        complete_offer(deadline_date="2026-11-05"),
        offer_id="job_1",
        now=NOW,
        previous=previous,
    )
    assert [change["field"] for change in quality.to_dict()["freshness"]["changes_since_last_check"]] == [
        "deadline_date"
    ]


# ---------------------------------------------------------------------------
# 7. Purity
# ---------------------------------------------------------------------------

def test_the_assessment_never_modifies_the_offer_it_reads() -> None:
    offer = complete_offer()
    reference = json.dumps(offer, ensure_ascii=False, sort_keys=True)
    assess_offer(offer, offer_id="job_1", now=NOW, duplicates=[partner_offer()])
    assert json.dumps(offer, ensure_ascii=False, sort_keys=True) == reference


def test_the_same_inputs_always_produce_the_same_verdict() -> None:
    first = assess_offer(complete_offer(), offer_id="job_1", now=NOW, source_url_status=200)
    second = assess_offer(complete_offer(), offer_id="job_1", now=NOW, source_url_status=200)
    assert first.to_dict() == second.to_dict()


def test_assess_reads_the_offer_of_the_catalog() -> None:
    class Catalog:
        def offer(self, offer_id: str) -> dict[str, Any]:
            return complete_offer() if offer_id == "job_1" else partner_offer()

        def offers(self) -> list[dict[str, Any]]:
            return [complete_offer(), partner_offer()]

    quality = assess("job_1", Catalog(), now=NOW, source_url_status=200)
    assert quality.offer_id == "job_1"
    assert quality.deduplication.duplicate_count == 1


# ---------------------------------------------------------------------------
# 8. The store
# ---------------------------------------------------------------------------

def test_the_store_keeps_the_snapshot_and_the_history(tmp_path: Path) -> None:
    store = OfferQualityStore(tmp_path / "offer_quality.json")
    quality = assess_offer(complete_offer(), offer_id="job_1", now=NOW)
    store.record(
        "job_1",
        quality=quality.to_dict(),
        facts=offer_facts(complete_offer()),
        changes=[{"field": "deadline_date", "old": "2026-10-20", "new": "2026-10-25", "detected_at": "2026-10-21T08:00:00Z"}],
        assessed_at="2026-10-21T08:00:00Z",
    )
    store.save("2026-10-21T08:00:00Z")
    reloaded = OfferQualityStore(tmp_path / "offer_quality.json")
    reloaded.load()
    assert reloaded.snapshot("job_1")["offer_id"] == "job_1"
    assert reloaded.facts("job_1")["deadline_date"] == "2026-10-25"
    assert reloaded.history("job_1")[0]["field"] == "deadline_date"


def test_the_store_survives_a_damaged_file(tmp_path: Path) -> None:
    path = tmp_path / "offer_quality.json"
    path.write_text("{not json", encoding="utf-8")
    store = OfferQualityStore(path)
    store.load()
    assert store.snapshot("job_1") is None
    assert store.history("job_1") == []


def test_the_store_writes_a_private_file(tmp_path: Path) -> None:
    path = tmp_path / "offer_quality.json"
    store = OfferQualityStore(path)
    store.record("job_1", quality={"offer_id": "job_1"}, facts={}, changes=[])
    store.save("2026-10-21T08:00:00Z")
    assert path.exists()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_the_history_of_an_offer_is_bounded(tmp_path: Path) -> None:
    store = OfferQualityStore(tmp_path / "offer_quality.json")
    for index in range(MAX_HISTORY_PER_OFFER + 20):
        store.record(
            "job_1",
            quality={"offer_id": "job_1"},
            facts={},
            changes=[{"field": "deadline_date", "old": str(index), "new": str(index + 1), "detected_at": "x"}],
        )
    assert len(store.history("job_1")) == MAX_HISTORY_PER_OFFER


def test_the_probe_never_requests_a_non_http_url() -> None:
    assert probe_source_status("") is None
    assert probe_source_status("file:///etc/passwd") is None
    assert probe_source_status("ftp://example.test/x") is None


# ---------------------------------------------------------------------------
# 9. The service and the HTTP contract
# ---------------------------------------------------------------------------

def _client(tmp_path: Path, probe: Any = None) -> TestClient:
    career = CareerService(tmp_path, offer_quality_probe=probe)
    return TestClient(create_app(tmp_path, career_override=career))


def _import_offer(client: TestClient, **changes: Any) -> dict[str, Any]:
    payload = {
        "company": "Acme",
        "title": "Analyste financier",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.acme.com/jobs/77",
        "job_family": "Corporate Finance",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-10-25",
        "duration_months": 6,
        "source_status": "open",
        "employment_type": "stage",
        "requirements": "Master en finance",
        "description_original": "Stage de six mois.",
    }
    payload.update(changes)
    response = client.post("/api/career/jobs/import", json=payload)
    assert response.status_code == 201
    return response.json()


def test_the_quality_route_returns_the_contract(tmp_path: Path) -> None:
    client = _client(tmp_path)
    job = _import_offer(client)
    response = client.get(f"/api/career/offer-quality/{job['id']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["offer_id"] == job["id"]
    assert payload["freshness"]["source_url"] == "https://careers.acme.com/jobs/77"
    assert payload["completeness"]["score"] > 0
    assert payload["deduplication"]["canonical_id"].startswith("canon_")
    assert payload["source_trust"]["status"] in {"verified", "unverified", "contradictory", "missing"}


def test_the_quality_route_refuses_an_unknown_offer(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/career/offer-quality/job_unknown")
    assert response.status_code == 400
    assert "n’existe pas" in response.json()["detail"]


def test_the_refresh_route_reports_the_detected_changes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    job = _import_offer(client)
    first = client.post("/api/career/offer-quality/refresh", json={"offer_ids": [job["id"]], "force": False})
    assert first.status_code == 200
    assert first.json()["changed"] == 0

    _import_offer(client, deadline_date="2026-11-05")
    second = client.post("/api/career/offer-quality/refresh", json={"offer_ids": [job["id"]], "force": False})
    assert second.status_code == 200
    payload = second.json()
    assert payload["changed"] == 1
    changes = payload["offers"][0]["changes"]
    assert [change["field"] for change in changes] == ["deadline_date"]
    assert changes[0]["old"] == "2026-10-25"
    assert changes[0]["new"] == "2026-11-05"

    history = client.get(f"/api/career/offer-quality/{job['id']}/history")
    assert history.status_code == 200
    assert history.json()["history"][0]["field"] == "deadline_date"


def test_a_forced_refresh_uses_the_probe_and_stores_the_status(tmp_path: Path) -> None:
    calls: list[str] = []

    def probe(url: str) -> int:
        calls.append(url)
        return 200

    client = _client(tmp_path, probe=probe)
    job = _import_offer(client)
    response = client.post("/api/career/offer-quality/refresh", json={"offer_ids": [job["id"]], "force": True})
    assert response.status_code == 200
    assert calls == ["https://careers.acme.com/jobs/77"]
    assert response.json()["offers"][0]["verified_online"] is True
    assert response.json()["offers"][0]["reverification_due"] is False
    assert response.json()["offers"][0]["quality"]["freshness"]["source_url_status"] == 200


def test_a_refresh_without_force_never_calls_the_probe(tmp_path: Path) -> None:
    calls: list[str] = []

    def probe(url: str) -> int:
        calls.append(url)
        return 200

    client = _client(tmp_path, probe=probe)
    job = _import_offer(client)
    client.post("/api/career/offer-quality/refresh", json={"offer_ids": [job["id"]], "force": False})
    assert calls == []


def test_the_refresh_route_needs_at_least_one_offer(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/api/career/offer-quality/refresh", json={"offer_ids": [], "force": False})
    assert response.status_code == 400


def test_the_snapshots_are_private_and_erased_with_the_workspace(tmp_path: Path) -> None:
    from career.service import DELETE_CONFIRMATION

    career = CareerService(tmp_path)
    client = TestClient(create_app(tmp_path, career_override=career))
    job = _import_offer(client)
    client.post("/api/career/offer-quality/refresh", json={"offer_ids": [job["id"]], "force": False})
    store_path = tmp_path / "career_data" / "offer_quality.json"
    assert store_path.exists()
    assert stat.S_IMODE(os.stat(store_path).st_mode) == 0o600

    response = client.request("DELETE", "/api/career/data", json={"confirmation": DELETE_CONFIRMATION})
    assert response.status_code == 200
    assert not store_path.exists()


# ---------------------------------------------------------------------------
# 10. The interface
# ---------------------------------------------------------------------------

def test_the_ui_module_is_loaded_and_reads_the_local_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "career_static" / "index.html").read_text(encoding="utf-8")
    assert "/career-static/js/offer-quality.js" in html
    module = (root / "career_static" / "js" / "offer-quality.js").read_text(encoding="utf-8")
    assert "/api/career/offer-quality/" in module
    assert "/api/career/offer-quality/refresh" in module
    assert "Fraîche" in module
    career_js = (root / "career_static" / "career.js").read_text(encoding="utf-8")
    assert "CareerOfferQuality" in career_js


@pytest.mark.parametrize("route", ["/api/career/offer-quality/job_1", "/api/career/offer-quality/refresh"])
def test_the_routes_are_declared_once(route: str) -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "career" / "router.py").read_text(encoding="utf-8")
    assert source.count(f'"{route}') + source.count(f'"{route}/') <= 1
