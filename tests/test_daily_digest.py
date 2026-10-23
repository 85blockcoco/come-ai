"""Daily digest guarantees: local projection, cache, manual refresh, no invention.

Everything here is synthetic.  No socket is opened, no public source is read
and no personal fact is used: the digest only projects what the local database
already stores.
"""

from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.daily_digest import (
    DAILY_DIGEST_SETTING,
    MAX_PARALLEL_SOURCES,
    build_tracks,
    changed_fields,
    collect_broken_sources,
    normalize_ttl,
    offer_track,
    project_digest,
)
from career.discovery import DiscoveryPayload
from career.service import CareerService
from come_ai_web import create_app


NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
LAUNCHD_DOC = Path(__file__).resolve().parents[1] / "docs" / "career" / "daily-digest-launchd.md"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("the daily digest must never open a socket")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, blocked)


def job(**updates):
    value = {
        "id": "job_synthetic_1",
        "title": "Corporate Finance Intern",
        "company": "Synthetic Finance",
        "city": "London",
        "country": "United Kingdom",
        "employment_type": "Internship",
        "role_level": "",
        "posted_date": "2026-10-21",
        "deadline_date": "2026-10-30",
        "duration_months": 6,
        "source_name": "greenhouse",
        "source_id": "role-1",
        "official_url": "https://boards.greenhouse.io/synthetic/jobs/1",
        "source_status": "open",
        "status": "discovered",
        "shortlisted": False,
        "created_at": "2026-10-21T08:00:00+00:00",
        "updated_at": "2026-10-21T08:00:00+00:00",
        "last_verified_at": "2026-10-21T08:00:00+00:00",
        "description_original": "Six month corporate finance internship.",
        "source_verified": True,
        "scoring": {"score": 72},
    }
    value.update(updates)
    return value


def match(**updates):
    job_updates = updates.pop("job", {})
    qualification = {
        "target_status": "conforming",
        "geography_status": "allowed",
        "missing_fields": [],
    }
    qualification.update(updates.pop("qualification", {}))
    stage_match = updates.pop("stage_match", {"score": 72})
    return {"job": job(**job_updates), "qualification": qualification, "stage_match": stage_match}


def digest(matches, **kwargs):
    return project_digest(matches=matches, now=NOW, **kwargs)


def import_offer(service, **updates):
    payload = {
        "company": "Synthetic Finance",
        "title": "Corporate Finance Intern",
        "source_name": "greenhouse",
        "source_id": "role-1",
        "official_url": "https://boards.greenhouse.io/synthetic/jobs/1",
        "city": "London",
        "country": "United Kingdom",
        "posted_date": "2026-10-21",
        "start_date": "2027-01-15",
        "duration_months": 6,
        "source_status": "open",
        "employment_type": "Internship",
        "description_original": "Six month corporate finance internship.",
    }
    payload.update(updates)
    return service.import_job(payload)


class RecordingConnector:
    """A synthetic board reader that records how many reads overlap."""

    def __init__(self, *, delay: float = 0.05):
        self.delay = delay
        self.calls: list[str] = []
        self.max_concurrent = 0
        self._active = 0
        self._lock = threading.Lock()

    def discover_ranked(self, board, *, selection_brief=None, **kwargs):
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
            self.calls.append(board.board_token)
        try:
            time.sleep(self.delay)
            return DiscoveryPayload(
                jobs=(),
                verified_at="2026-10-22T08:00:00+00:00",
                truncated=False,
            )
        finally:
            with self._lock:
                self._active -= 1


# ----------------------------------------------------------------------
# Pure projection
# ----------------------------------------------------------------------


def test_digest_reports_the_offers_that_appeared_since_the_last_visit():
    payload = digest([match()], state={"last_visit": "2026-10-20T00:00:00+00:00"})

    assert [offer["offer_id"] for offer in payload["new_offers"]] == ["job_synthetic_1"]
    assert payload["new_offers"][0]["employer"] == "Synthetic Finance"
    assert payload["new_offers"][0]["location"] == "London, United Kingdom"
    assert payload["new_offers"][0]["published_date"] == "2026-10-21"
    assert payload["new_offers"][0]["match_score"] == 72
    assert payload["new_offers"][0]["source_trust"] == "verified"


def test_digest_never_repeats_an_offer_the_person_already_saw():
    payload = digest([match()], state={"last_visit": "2026-10-22T09:00:00+00:00"})

    assert payload["new_offers"] == []
    assert payload["counts"]["new_offers"] == 0


def test_digest_separates_the_offers_the_person_already_rejected():
    payload = digest(
        [match(job={"status": "rejected"}), match(job={"id": "job_synthetic_2", "status": "archived"})],
        state={"last_visit": "2026-10-20T00:00:00+00:00"},
    )

    assert payload["new_offers"] == []
    assert payload["counts"]["separated_offers"] == 2


def test_digest_excludes_france_and_paris_with_the_saved_criteria():
    payload = digest(
        [
            match(job={"id": "job_france", "country": "France", "city": "Lyon"},
                  qualification={"geography_status": "excluded", "target_status": "non_conforming"}),
            match(job={"id": "job_paris", "country": "", "city": "Paris"},
                  qualification={"geography_status": "excluded", "target_status": "non_conforming"}),
            match(job={"id": "job_london"}),
        ],
        state={"last_visit": "2026-10-20T00:00:00+00:00"},
    )

    assert [offer["offer_id"] for offer in payload["new_offers"]] == ["job_london"]
    assert payload["counts"]["excluded_by_criteria"] == 2


def test_digest_names_the_fields_that_really_changed():
    previous = offer_track(job())
    current = offer_track(job(title="Corporate Finance Intern (new)", deadline_date="2026-11-05"))

    assert changed_fields(previous, current) == ["deadline_date", "title"]

    # An offer already seen is not new again: it belongs to the updates.
    seen = {"last_visit": "2026-10-22T00:00:00+00:00", "tracks": {"job_synthetic_1": previous}}

    payload = digest([match()], state=seen)
    assert payload["new_offers"] == []
    assert payload["updated_offers"] == []

    payload = digest(
        [match(job={"title": "Corporate Finance Intern (new)", "deadline_date": "2026-11-05"})],
        state=seen,
    )
    assert payload["updated_offers"][0]["changed_fields"] == ["deadline_date", "title"]
    assert payload["updated_offers"][0]["updated_at"] == "2026-10-21T08:00:00+00:00"


def test_an_offer_that_is_new_is_not_also_reported_as_an_update():
    previous = offer_track(job())
    payload = digest(
        [match(job={"title": "Corporate Finance Intern (new)"})],
        state={"last_visit": "2026-10-20T00:00:00+00:00", "tracks": {"job_synthetic_1": previous}},
    )

    assert len(payload["new_offers"]) == 1
    assert payload["updated_offers"] == []


def test_a_new_offer_hidden_by_the_cap_is_never_reported_as_an_update():
    matches = [match(job={"id": f"job_{index}"}) for index in range(45)]
    tracks = {f"job_{index}": {"title": "Ancienne version"} for index in range(45)}

    payload = digest(matches, state={"last_visit": "2026-10-20T00:00:00+00:00", "tracks": tracks})

    assert len(payload["new_offers"]) == 40
    assert payload["counts"]["new_offers"] == 45
    assert payload["updated_offers"] == []


def test_digest_reports_the_offers_that_expire_soon():
    payload = digest(
        [
            match(job={"id": "job_soon", "deadline_date": "2026-10-30"}),
            match(job={"id": "job_later", "deadline_date": "2026-12-30"}),
            match(job={"id": "job_no_deadline", "deadline_date": ""}),
        ],
        state={"last_visit": "2026-10-20T00:00:00+00:00"},
    )

    assert [offer["offer_id"] for offer in payload["expiring_soon"]] == ["job_soon"]
    assert payload["expiring_soon"][0]["days_left"] == 8
    assert payload["expiring_soon"][0]["deadline_date"] == "2026-10-30"


def test_digest_reports_the_offers_that_became_unavailable():
    payload = digest(
        [
            match(job={"id": "job_closed", "source_status": "closed"}),
            match(job={"id": "job_expired", "deadline_date": "2026-10-01"}),
        ],
        state={"last_visit": "2026-10-20T00:00:00+00:00"},
    )

    reasons = {offer["offer_id"]: offer["reason"] for offer in payload["unavailable"]}
    assert set(reasons) == {"job_closed", "job_expired"}
    assert "clôturée" in reasons["job_closed"]
    assert "date limite" in reasons["job_expired"]
    assert payload["unavailable"][0]["detected_at"] == "2026-10-21T08:00:00+00:00"


def test_digest_ranks_the_best_offers_and_counts_the_missing_critical_facts():
    payload = digest(
        [
            match(job={"id": "job_best"}, stage_match={"score": 91}),
            match(
                job={"id": "job_uncertain"},
                stage_match={"score": 40},
                qualification={"target_status": "to_verify", "missing_fields": ["durée", "pays", "publication"]},
            ),
            match(job={"id": "job_excluded"}, qualification={"target_status": "non_conforming"}),
        ],
        state={"last_visit": "2026-10-20T00:00:00+00:00"},
    )

    assert [offer["offer_id"] for offer in payload["top_matches"]] == ["job_best", "job_uncertain"]
    assert payload["top_matches"][0]["fit_score"] == 91
    assert payload["top_matches"][0]["missing_critical_count"] == 0
    assert payload["top_matches"][1]["missing_critical_count"] == 3
    assert payload["counts"]["uncertain_offers"] == 1


def test_digest_lists_the_broken_sources_with_the_next_retry_time():
    broken = collect_broken_sources(
        [{"company": "Synthetic Finance", "last_error_code": "timeout", "last_error_at": "2026-10-22T08:00:00+00:00"}],
        [{"company": "Other Finance", "status": "error", "error_code": "invalid_payload"}],
    )

    assert [item["source"] for item in broken] == ["Synthetic Finance", "Other Finance"]
    assert broken[0]["error"] == "timeout"
    assert broken[0]["last_failure"] == "2026-10-22T08:00:00+00:00"
    assert broken[0]["retry_at"] == "2026-10-22T08:30:00+00:00"
    assert broken[1]["retry_at"] is None
    # A source that failed without a readable date stays last: it is the least
    # recent known failure.
    assert broken[1]["last_failure"] == ""


def test_an_empty_digest_stays_empty_instead_of_being_filled():
    payload = digest([])

    assert payload["new_offers"] == []
    assert payload["updated_offers"] == []
    assert payload["expiring_soon"] == []
    assert payload["unavailable"] == []
    assert payload["top_matches"] == []
    assert payload["broken_sources"] == []
    assert payload["last_refresh"] is None
    assert payload["cache_expires_at"] == "2026-10-22T09:15:00+00:00"


def test_the_cache_lifetime_is_bounded_and_never_zero():
    assert normalize_ttl(0) == 60
    assert normalize_ttl(10 ** 9) == 86_400
    assert normalize_ttl("nope") == 900
    assert normalize_ttl(1_800) == 1_800


def test_the_tracked_state_stays_bounded():
    matches = [match(job={"id": f"job_{index}"}) for index in range(400)]
    tracks = build_tracks(matches)

    assert len(tracks) == 300


# ----------------------------------------------------------------------
# Service behaviour
# ----------------------------------------------------------------------


def test_reading_the_digest_never_queries_a_source(tmp_path):
    connector = RecordingConnector()
    service = CareerService(tmp_path, discovery_connector=connector)
    import_offer(service)

    payload = service.daily_digest()

    assert connector.calls == []
    assert payload["cache_status"] == "missing"
    assert payload["requires_refresh"] is True
    assert len(payload["new_offers"]) == 1


def test_a_cached_digest_is_served_until_its_lifetime_expires(tmp_path):
    connector = RecordingConnector()
    service = CareerService(tmp_path, discovery_connector=connector)
    import_offer(service)

    refreshed = service.refresh_daily_digest(include_curated=False)
    assert refreshed["cache_status"] == "fresh"
    assert refreshed["last_refresh"] is not None
    calls_after_refresh = len(connector.calls)

    again = service.daily_digest()
    assert again["cache_status"] == "fresh"
    assert again["requires_refresh"] is False
    assert len(connector.calls) == calls_after_refresh


def test_an_expired_cache_is_rebuilt_from_the_local_facts_and_asks_for_a_refresh(tmp_path):
    service = CareerService(tmp_path, daily_digest_ttl_seconds=60)
    import_offer(service)
    service.refresh_daily_digest(include_curated=False)

    with service._lock, service._connection() as connection:
        connection.execute(
            "UPDATE career_settings SET setting_value = ? WHERE setting_key = ?",
            (
                '{"version": 1, "expires_at": "2020-01-01T00:00:00+00:00", "digest": {"new_offers": []}}',
                DAILY_DIGEST_SETTING,
            ),
        )

    payload = service.daily_digest()
    assert payload["cache_status"] == "expired"
    assert payload["requires_refresh"] is True
    assert len(payload["new_offers"]) == 1


def test_an_explicit_refresh_inside_the_lifetime_does_not_read_a_source(tmp_path):
    connector = RecordingConnector()
    service = CareerService(tmp_path, discovery_connector=connector)
    service.create_discovery_source({"company": "Synthetic Finance", "board_reference": "synthetic-board"})

    service.refresh_daily_digest(include_curated=False)
    calls = len(connector.calls)
    assert calls == 1

    service.refresh_daily_digest(include_curated=False)
    assert len(connector.calls) == calls


def test_a_refresh_reads_at_most_two_sources_at_the_same_time(tmp_path):
    connector = RecordingConnector(delay=0.05)
    service = CareerService(tmp_path, discovery_connector=connector)
    for index in range(4):
        service.create_discovery_source(
            {"company": f"Synthetic Finance {index}", "board_reference": f"synthetic-board-{index}"}
        )

    service.refresh_daily_digest(include_curated=False)

    assert len(connector.calls) == 4
    assert connector.max_concurrent <= MAX_PARALLEL_SOURCES
    assert connector.max_concurrent == MAX_PARALLEL_SOURCES


def test_an_interrupted_refresh_is_reported_as_partial_and_can_resume(tmp_path):
    service = CareerService(tmp_path)
    import_offer(service)
    with service._lock, service._connection() as connection:
        connection.execute(
            "INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?) "
            "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
            (
                DAILY_DIGEST_SETTING,
                '{"version": 1, "status": "running", "started_at": "2026-10-22T07:00:00+00:00"}',
            ),
        )

    payload = service.daily_digest()
    assert payload["partial"] is True
    assert any("interrompue" in note for note in payload["notes"])

    refreshed = service.refresh_daily_digest(include_curated=False)
    assert refreshed["partial"] is False
    assert any("interrompue" in note for note in refreshed["notes"])


def test_recording_a_visit_moves_the_new_offers_watermark(tmp_path):
    service = CareerService(tmp_path)
    import_offer(service)
    service.refresh_daily_digest(include_curated=False)

    service.record_daily_digest_visit()

    state = service._daily_digest_state()
    assert state["last_visit"]
    payload = service.daily_digest()
    assert payload["cache_status"] == "fresh"


def test_the_cache_lifetime_is_configurable_from_the_local_settings(tmp_path):
    service = CareerService(tmp_path)
    assert service._daily_digest_ttl() == 900

    service.update_daily_digest_settings({"ttl_seconds": 3_600})
    assert service._daily_digest_ttl() == 3_600

    from workspace_core import UserFacingError

    with pytest.raises(UserFacingError, match="entier"):
        service.update_daily_digest_settings({"ttl_seconds": "beaucoup"})


def test_the_digest_keeps_a_failed_source_visible_instead_of_hiding_it(tmp_path):
    service = CareerService(tmp_path)
    source = service.create_discovery_source(
        {"company": "Synthetic Finance", "board_reference": "synthetic-board"}
    )
    with service._lock, service._connection() as connection:
        connection.execute(
            "UPDATE discovery_sources SET last_error_code = ?, last_error_at = ? WHERE id = ?",
            ("timeout", "2026-10-22T08:00:00+00:00", source["id"]),
        )

    payload = service.daily_digest()
    assert [item["source"] for item in payload["broken_sources"]] == ["Synthetic Finance"]
    assert payload["broken_sources"][0]["error"] == "timeout"


# ----------------------------------------------------------------------
# HTTP contract
# ----------------------------------------------------------------------


def test_the_http_endpoint_returns_the_seven_documented_categories(tmp_path):
    service = CareerService(tmp_path)
    import_offer(service)

    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.get("/api/career/daily")
        assert response.status_code == 200
        payload = response.json()
        for category in ("new_offers", "updated_offers", "expiring_soon", "unavailable",
                         "top_matches", "broken_sources"):
            assert isinstance(payload[category], list)
        assert payload["last_refresh"] is None
        assert payload["cache_expires_at"]
        assert len(payload["new_offers"]) == 1

        alias = client.get("/career/daily")
        assert alias.status_code == 200
        assert alias.json()["new_offers"] == payload["new_offers"]


def test_the_http_refresh_and_visit_endpoints_work(tmp_path):
    connector = RecordingConnector()
    service = CareerService(tmp_path, discovery_connector=connector)
    service.create_discovery_source({"company": "Synthetic Finance", "board_reference": "synthetic-board"})

    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        refreshed = client.post("/api/career/daily/refresh", json={"force": True, "include_curated": False})
        assert refreshed.status_code == 200
        assert refreshed.json()["refreshed"] is True
        assert refreshed.json()["last_refresh"] is not None

        visited = client.post("/api/career/daily/visit")
        assert visited.status_code == 200
        assert visited.json()["recorded"] is True

        settings = client.put("/api/career/daily/settings", json={"ttl_seconds": 1_800})
        assert settings.status_code == 200
        assert settings.json()["ttl_seconds"] == 1_800

        invalid = client.put("/api/career/daily/settings", json={"ttl_seconds": 5})
        assert invalid.status_code == 422


def test_the_launchd_model_is_documented_but_never_installed():
    assert LAUNCHD_DOC.is_file()
    content = LAUNCHD_DOC.read_text(encoding="utf-8")
    assert "launchd" in content
    assert "launchctl load" in content
    # The model is documented, never installed: no plist is shipped in a
    # launchable location and no scheduler is enabled by the code.
    assert not list(Path(__file__).resolve().parents[1].glob("**/LaunchAgents/*.plist"))
    assert "launchd" not in Path(__file__).resolve().parents[1].joinpath("career", "service.py").read_text(encoding="utf-8")


def test_the_panel_is_served_with_its_own_script(tmp_path):
    service = CareerService(tmp_path)
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        page = client.get("/career")
        assert page.status_code == 200
        assert 'id="daily-digest-panel"' in page.text
        assert 'src="/career-static/js/daily-digest.js"' in page.text

        script = client.get("/career-static/js/daily-digest.js")
        assert script.status_code == 200
        assert "/api/career/daily" in script.text
        # The script never triggers a refresh by itself: only a click does.
        assert "dailyDigestRefresh()" in script.text
