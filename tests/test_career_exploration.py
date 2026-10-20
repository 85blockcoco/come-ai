"""Explorer admission, ranking and persistence using synthetic public feeds.

No test below reads personal documents, contacts a provider or sends a
candidate application. Real Career services run in pytest temporary storage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from career.discovery import DiscoveryPayload, GreenhouseBoard, GreenhouseJobBoardConnector, PublicSourceError
from career.exploration import EXPLORATION_MAX_SOURCES, classify_internship
from career.service import CareerService
from career.stage_search import STAGE_DOMAINS, validate_brief


def source(token: str = "fiction", company: str = "Finance Synthétique") -> dict:
    return {"id": f"curated_{token}", "provider": "greenhouse", "company": company,
            "board_token": token, "public_url": f"https://boards.greenhouse.io/{token}",
            "provenance_url": f"https://finance.example.test/{token}/careers", "verified_at": "2026-10-14T00:00:00Z"}


def posting(identifier: int, title: str = "Corporate Finance Intern", **changes) -> dict:
    value = {"id": identifier, "title": title, "absolute_url": f"https://careers.example.test/jobs/{identifier}",
             "location": {"name": "Paris, France"},
             "content": "<p>Financial analysis and valuation. This synthetic internship lasts six months.</p>"}
    value.update(changes)
    return value


class FeedTransport:
    def __init__(self, feeds):
        self.feeds = feeds
        self.calls = []

    def get_json(self, endpoint, timeout_seconds):
        assert endpoint.startswith("https://boards-api.greenhouse.io/v1/boards/")
        assert 0 < timeout_seconds <= 8
        self.calls.append(endpoint)
        token = endpoint.split("/boards/", 1)[1].split("/", 1)[0]
        result = self.feeds[token]
        if isinstance(result, Exception):
            raise result
        return {"jobs": result}


def service_with(tmp_path: Path, feeds: dict, sources=None):
    transport = FeedTransport(feeds)
    service = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(transport),
                            curated_sources=tuple(sources or [source(key, f"Finance {key}") for key in feeds]))
    return service, transport


@pytest.mark.parametrize(("title", "description", "employment", "expected"), [
    ("Corporate Finance Intern", "", "", "confirmed"),
    ("Valuation Internship", "", "", "confirmed"),
    ("Stage - Analyste M&A", "", "", "confirmed"),
    ("Stagiaire en audit", "", "", "confirmed"),
    ("Finance Analyst", "This internship lasts four months.", "", "confirmed"),
    ("Finance Analyst", "Previous internship experience is desirable.", "", "uncertain"),
    ("Finance Analyst", "", "Intern", "confirmed"),
    ("Senior Finance Analyst", "This internship lasts four months.", "", "excluded"),
    ("Finance Manager Intern", "", "", "excluded"),
    ("Finance Analyst - CDI", "Stage de quatre mois.", "", "excluded"),
    ("Finance Intern", "", "permanent", "excluded"),
    ("Finance Intern", "", "full-time", "confirmed"),
    ("Finance Intern", "This is a permanent role.", "", "uncertain"),
    ("Finance Analyst", "We do not offer internships. Internal mobility is possible.", "", "uncertain"),
    ("Stage Manager", "", "", "excluded"),
    ("International Finance Analyst", "Financial analysis.", "", "uncertain"),
])
def test_classification_requires_explicit_stage_not_financial_score(title, description, employment, expected):
    job = {"title": title, "description_original": description, "employment_type": employment}
    classified = classify_internship(job)
    assert classified["status"] == expected
    assert classified["reason"]
    for evidence in classified["evidence"]:
        assert evidence["quote"] in job[evidence["field"]]


def test_classifier_does_not_claim_full_time_means_permanent():
    assert classify_internship({"title": "Finance Intern", "employment_type": "full time"})["status"] == "confirmed"


def test_admission_and_ranking_happen_before_first_150_limit():
    raw = [posting(i, "Senior Corporate Finance Analyst") for i in range(1, 171)]
    raw += [posting(171, "Corporate Finance Intern"), posting(172, "Software Engineering Intern")]
    # Boilerplate must not turn a software role into the requested financial work.
    connector = GreenhouseJobBoardConnector(FeedTransport({"fiction": raw}))
    payload = connector.discover_internships(GreenhouseBoard("fiction", "Fiction Finance", "fiction"),
                                           selection_brief=validate_brief({"domains": ["Corporate Finance"]}))
    assert [job["source_id"] for job in payload.jobs] == ["171"]
    assert payload.raw_count == payload.evaluated_count == 172
    assert payload.excluded_count == 170
    assert payload.confirmed_count == 0
    assert payload.uncertain_count == 2
    assert payload.filtered_criteria_count == 1
    assert payload.relevant_count == 1


def test_employer_boilerplate_does_not_turn_support_roles_into_finance_matches():
    raw = [
        posting(201, "Receptionist Intern", content="Private equity investment firm. This internship lasts six months."),
        posting(202, "Staff Product Designer Intern", content="Financial markets company. This internship lasts six months."),
        posting(203, "Datacentre Operations Intern", content="Investment management business. This internship lasts six months."),
        posting(204, "Join Our European Talent Community Internship", content="Corporate finance group. This internship lasts six months."),
        posting(205, "Investment Operations Intern", content="Portfolio management and fixed income. This internship lasts six months."),
    ]
    connector = GreenhouseJobBoardConnector(FeedTransport({"fiction": raw}))
    payload = connector.discover_internships(
        GreenhouseBoard("fiction", "Fiction Finance", "fiction"),
        selection_brief=validate_brief({"domains": list(STAGE_DOMAINS)}),
    )
    assert [job["title"] for job in payload.jobs] == ["Investment Operations Intern"]


def test_fresh_default_search_covers_finance_without_filling_results_with_software_roles(tmp_path):
    raw = [
        posting(301, "Software Engineering Intern", content="Financial markets company. This internship lasts six months."),
        posting(302, "Corporate Finance Intern", content="Financial analysis and valuation. This internship lasts six months."),
    ]
    connector = GreenhouseJobBoardConnector(FeedTransport({"fiction": raw}))
    payload = connector.discover_internships(
        GreenhouseBoard("fiction", "Fiction Finance", "fiction"),
        selection_brief=CareerService(tmp_path).get_stage_search()["brief"],
    )
    assert [job["source_id"] for job in payload.jobs] == ["302"]


def test_relevant_finance_stage_after_150_weak_stages_is_retained():
    raw = [posting(i, "Audit Intern", content="This internship covers audit.") for i in range(1, 171)]
    raw.append(posting(900, "Corporate Finance Intern"))
    connector = GreenhouseJobBoardConnector(FeedTransport({"fiction": raw}))
    result = connector.discover_internships(GreenhouseBoard("fiction", "Fiction", "fiction"),
                                          selection_brief=validate_brief({"domains": ["Corporate Finance"]}))
    assert len(result.jobs) == 1
    assert result.jobs[0]["source_id"] == "900"
    assert result.filtered_criteria_count == 170


def test_ranked_stage_cap_is_deterministic_when_feed_order_changes():
    feed = [posting(i) for i in range(1, 206)]
    board = GreenhouseBoard("fiction", "Fiction", "fiction")
    first = GreenhouseJobBoardConnector._normalise(board, {"jobs": feed}, internships_only=True)
    reversed_result = GreenhouseJobBoardConnector._normalise(board, {"jobs": list(reversed(feed))}, internships_only=True)
    assert len(first.jobs) == 150
    assert first.truncated and first.relevant_count == 205
    assert first.jobs == reversed_result.jobs


def test_no_personal_boards_needed_and_read_does_not_fetch(tmp_path):
    service, transport = service_with(tmp_path, {"fiction": [posting(1)]})
    initial = service.get_exploration()
    assert initial["matches"] == initial["outcomes"] == []
    assert initial["has_run"] is False and not transport.calls
    assert service.list_discovery_sources() == []
    result = service.explore_internships()
    assert result["has_run"] and len(result["matches"]) == 1
    assert result["summary"]["sources_attempted"] == result["summary"]["sources_succeeded"] == 1
    assert result["matches"][0]["internship"]["status"] == "confirmed"
    assert result["matches"][0]["job"]["official_url"] == "https://careers.example.test/jobs/1"
    assert service.list_discovery_sources() == []
    assert len(transport.calls) == 1
    assert len(service.get_exploration()["matches"]) == 1 and len(transport.calls) == 1


def test_shared_official_url_preserves_notes_tracking_and_personal_board_ownership(tmp_path):
    service, _ = service_with(tmp_path, {"fiction": [posting(1)]})
    existing = service.import_job({"company": "Finance fiction", "title": "Corporate Finance Intern",
                                   "official_url": "https://careers.example.test/jobs/1?utm_source=mail",
                                   "source_name": "greenhouse", "source_id": "personal:1"})
    service.set_shortlist(existing["id"], True, "Note de suivi fictive à préserver")
    application = service.create_application(existing["id"])
    with service._connection() as connection:
        connection.execute("UPDATE jobs SET discovery_source_id = ? WHERE id = ?", ("personal-source", existing["id"]))
    result = service.explore_internships()
    job = result["matches"][0]["job"]
    assert job["id"] == existing["id"]
    assert job["shortlisted"] and job["personal_note"] == "Note de suivi fictive à préserver"
    assert job["discovery_source_id"] == "personal-source"
    assert job["application"]["id"] == application["id"]
    assert job["last_verified_at"] == result["matches"][0]["verified_at"]
    assert len(service.list_jobs()) == 1


def test_cache_is_labelled_and_new_criteria_invalidates_selection(tmp_path):
    service, transport = service_with(tmp_path, {"fiction": [posting(1), posting(2, "Audit Intern", content="This internship covers audit.")]})
    service.update_stage_search({"domains": ["Corporate Finance"]})
    assert len(service.explore_internships()["matches"]) == 1
    cached = service.explore_internships()
    assert cached["outcomes"][0]["status"] == "cached"
    assert cached["summary"]["sources_attempted"] == 0
    assert cached["summary"]["counts_include_cached_sources"] and len(transport.calls) == 1
    service.update_stage_search({"domains": ["Audit financier"]})
    stale = service.get_exploration()
    assert stale["criteria_changed"] and stale["requires_refresh"]
    assert stale["matches"] == []
    new = service.explore_internships()
    assert new["matches"][0]["job"]["source_id"].endswith(":2")
    assert not new["criteria_changed"] and len(transport.calls) == 2


def test_source_failure_is_explicit_and_does_not_erase_tracked_jobs(tmp_path):
    service, transport = service_with(tmp_path, {"fiction": [posting(1)], "broken": PublicSourceError("Unavailable", code="503")})
    result = service.explore_internships()
    assert result["summary"]["partial"] and result["summary"]["sources_failed"] == 1
    assert result["summary"]["sources_attempted"] == 2
    job_id = result["matches"][0]["job"]["id"]
    application = service.create_application(job_id)
    transport.feeds["fiction"] = RuntimeError("Untrusted exception details MUST NOT leak")
    failed = service.explore_internships(force=True)
    assert failed["matches"] == [] and failed["summary"]["sources_failed"] == 2
    assert "MUST NOT" not in str(failed)
    assert service.get_job(job_id)["application"]["id"] == application["id"]


def test_known_geo_mismatch_is_not_used_to_fill_results_unknown_is_visible(tmp_path):
    feed = [posting(1), posting(2, location={"name": "London, United Kingdom"}), posting(3, location={})]
    service, _ = service_with(tmp_path, {"fiction": feed})
    service.update_stage_search({"domains": ["Corporate Finance"], "cities": ["Paris"]})
    result = service.explore_internships()
    ids = {item["job"]["source_id"].rsplit(":", 1)[-1] for item in result["matches"]}
    assert ids == {"1", "3"}
    unknown = next(item for item in result["matches"] if not item["job"]["city"])
    assert any("Localisation" in value for value in unknown["stage_match"]["unknowns"])


def test_country_unknown_is_not_invented_from_city(tmp_path):
    service, _ = service_with(tmp_path, {"fiction": [posting(1, location={"name": "Paris"})]})
    service.update_stage_search({"countries": ["France"]})
    result = service.explore_internships()
    assert len(result["matches"]) == 1
    assert result["matches"][0]["job"]["country"] == ""


def test_middle_city_in_multi_location_posting_is_not_dropped(tmp_path):
    service, _ = service_with(tmp_path, {"fiction": [posting(1, location={"name": "London/Paris/HK/Tokyo"})]})
    service.update_stage_search({"cities": ["Paris"], "domains": ["Corporate Finance"]})
    result = service.explore_internships()
    assert len(result["matches"]) == 1
    assert result["matches"][0]["job"]["city"] == "London/Paris/HK/Tokyo"
    assert result["matches"][0]["job"]["country"] == ""


def test_snapshot_survives_service_restart_and_does_not_refetch(tmp_path):
    service, transport = service_with(tmp_path, {"fiction": [posting(1)]})
    result = service.explore_internships()
    restarted, fresh_transport = service_with(tmp_path, {"fiction": []})
    assert restarted.get_exploration()["matches"][0]["job"]["id"] == result["matches"][0]["job"]["id"]
    assert not fresh_transport.calls


def test_global_top_150_is_chosen_across_sources_and_exact_aliases_deduped(tmp_path):
    one = [posting(i, "Audit Intern", content="This internship covers audit.") for i in range(1, 152)]
    two = [posting(500 + i, "Corporate Finance Intern") for i in range(150)]
    service, _ = service_with(tmp_path, {"one": one, "two": two, "alias": two})
    service.update_stage_search({"domains": ["Audit financier", "Corporate Finance"], "roles": ["Corporate Finance"]})
    result = service.explore_internships()
    assert len(result["matches"]) == result["summary"]["retained_count"] == 150
    assert all(item["job"]["title"] == "Corporate Finance Intern" for item in result["matches"])
    assert result["summary"]["duplicate_count"] == 150
    assert len(service.list_jobs()) == 150


def test_source_limit_and_unsupported_connectors_are_not_fake_successes(tmp_path):
    feeds = {f"fiction{i}": [posting(i + 1)] for i in range(EXPLORATION_MAX_SOURCES + 2)}
    sources = [source(key) for key in feeds]
    sources[0]["provider"] = "future_ashby"
    service, transport = service_with(tmp_path, feeds, sources)
    result = service.explore_internships()
    assert result["summary"]["sources_total"] == EXPLORATION_MAX_SOURCES + 2
    assert result["summary"]["sources_attempted"] == len(transport.calls) == EXPLORATION_MAX_SOURCES - 1
    assert result["summary"]["sources_not_queried"] == 3
    assert result["summary"]["partial"]
    assert result["outcomes"][0]["status"] == "unsupported"


def test_global_budget_prevents_new_source_calls(tmp_path, monkeypatch):
    service, transport = service_with(tmp_path, {"one": [posting(1)], "two": [posting(2)]})
    clock = [0]
    monkeypatch.setattr("career.service.time.monotonic", lambda: clock[0])
    original = transport.get_json

    def slow_response(endpoint, timeout):
        result = original(endpoint, timeout)
        clock[0] = 61
        return result

    transport.get_json = slow_response
    result = service.explore_internships()
    assert len(transport.calls) == 1
    assert result["outcomes"][1]["status"] == "not_queried"
    assert result["summary"]["partial"] and result["summary"]["elapsed_seconds"] == 61


def test_unverified_source_is_refused_without_network(tmp_path):
    invalid = source()
    invalid["verified_at"] = ""
    service, transport = service_with(tmp_path, {"fiction": [posting(1)]}, [invalid])
    result = service.explore_internships()
    assert result["matches"] == [] and not transport.calls
    assert result["outcomes"][0]["status"] == "unsupported"


def test_explorer_and_personal_search_share_reentrancy_guard(tmp_path):
    service, _ = service_with(tmp_path, {"fiction": []})
    service._discovery_lock.acquire()
    try:
        with pytest.raises(Exception, match="déjà en cours"):
            service.explore_internships()
    finally:
        service._discovery_lock.release()


def test_incomplete_rows_are_counted_and_partial_not_false_complete_success(tmp_path):
    service, _ = service_with(tmp_path, {"fiction": [posting(1), {"id": 2, "title": "Finance Intern"}, None]})
    result = service.explore_internships()
    assert len(result["matches"]) == 1
    assert result["summary"]["sources_succeeded"] == 1
    assert result["outcomes"][0]["status"] == "partial"
    assert result["summary"]["partial"]
    assert result["summary"]["raw_count"] == 3
    assert result["summary"]["invalid_count"] == 2
    assert result["summary"]["evaluated_count"] == 1


@pytest.mark.parametrize("snapshot", ['{"match_refs":null,"summary":null,"outcomes":null}',
                                       '{"match_refs":[null,17,{}],"summary":"bad","outcomes":22}',
                                       'not json', '[]'])
def test_malformed_saved_snapshot_does_not_break_page(tmp_path, snapshot):
    service, transport = service_with(tmp_path, {"fiction": []})
    with service._connection() as connection:
        connection.execute("INSERT INTO career_settings (setting_key,setting_value) VALUES (?, ?)",
                           ("stage_explorer_last_result", snapshot))
    result = service.get_exploration()
    assert result["matches"] == result["outcomes"] == []
    assert isinstance(result["summary"], dict) and not transport.calls


def test_unsupported_connector_payload_is_an_explicit_error_not_false_success(tmp_path):
    class IncompleteConnector:
        def discover_internships(self, *args, **kwargs):
            return {"success": True}

    service = CareerService(tmp_path, curated_sources=(source(),),
                            exploration_connectors={"greenhouse": IncompleteConnector()})
    result = service.explore_internships()
    assert result["summary"]["sources_succeeded"] == 0
    assert result["summary"]["sources_failed"] == 1
    assert result["outcomes"][0]["error_code"] == "invalid_payload"


def test_connector_cannot_bypass_contract_admission_with_preselected_cdi(tmp_path):
    class IncorrectConnector:
        def discover_internships(self, *args, **kwargs):
            return DiscoveryPayload(jobs=({"company": "Fiction", "title": "Senior Finance Analyst - CDI",
                                          "official_url": "https://careers.example.test/1"},),
                                    verified_at="2026-10-14T00:00:00Z", truncated=False,
                                    raw_count=1, evaluated_count=1, confirmed_count=1, relevant_count=1)

    service = CareerService(tmp_path, curated_sources=(source(),),
                            exploration_connectors={"greenhouse": IncorrectConnector()})
    result = service.explore_internships()
    assert result["matches"] == [] and service.list_jobs() == []


def test_inconsistent_connector_counts_cannot_claim_success(tmp_path):
    class IncorrectCountsConnector:
        def discover_internships(self, *args, **kwargs):
            return DiscoveryPayload(jobs=(), verified_at="2026-10-14T00:00:00Z", truncated=False,
                                    raw_count=12, confirmed_count=12)

    service = CareerService(tmp_path, curated_sources=(source(),),
                            exploration_connectors={"greenhouse": IncorrectCountsConnector()})
    result = service.explore_internships()
    assert result["summary"]["sources_succeeded"] == 0
    assert result["outcomes"][0]["error_code"] == "invalid_counts"


def test_retry_is_bounded_and_stops_when_global_deadline_is_reached(monkeypatch):
    calls = []
    clock = [0]

    class RetryTransport:
        def get_json(self, endpoint, timeout):
            calls.append(endpoint)
            clock[0] = 61
            raise PublicSourceError("Temporary error", retryable=True, code="503")

    monkeypatch.setattr("career.discovery.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("career.discovery.time.sleep", lambda duration: None)
    connector = GreenhouseJobBoardConnector(RetryTransport())
    with pytest.raises(PublicSourceError) as caught:
        connector.discover_internships(GreenhouseBoard("fiction", "Fiction", "fiction"),
                                      selection_brief={}, deadline=60)
    assert caught.value.code == "budget" and len(calls) == 1


def test_deleted_offer_is_not_recreated_by_snapshot_read(tmp_path):
    service, _ = service_with(tmp_path, {"fiction": [posting(1)]})
    result = service.explore_internships()
    service.delete_job(result["matches"][0]["job"]["id"])
    assert service.get_exploration()["matches"] == []
    assert service.list_jobs() == []
