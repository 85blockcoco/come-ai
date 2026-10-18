"""Offline, synthetic regressions for selection *before* the 150-job cap."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from career.discovery import (
    GREENHOUSE_MAX_FEED_ROWS,
    GREENHOUSE_MAX_JOBS,
    GreenhouseBoard,
    GreenhouseJobBoardConnector,
    PublicSourceError,
)
from career.service import CareerService


BOARD = GreenhouseBoard(id="synthetic-board", company="Synthetic Bank", board_token="synthetic-bank")


def raw_job(job_id: str, *, title: str = "Software intern", city: str = "Paris", **changes: Any) -> dict[str, Any]:
    job = {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://careers.example.test/jobs/{job_id}",
        "location": {"name": f"{city}, France"},
        "content": "<p>Synthetic software engineering internship.</p>",
    }
    job.update(changes)
    return job


class SyntheticTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0
        self.on_request = None

    def get_json(self, endpoint: str, timeout_seconds: int) -> dict[str, Any]:
        assert endpoint.startswith("https://boards-api.greenhouse.io/v1/boards/")
        assert timeout_seconds == 8
        self.calls += 1
        if self.on_request:
            callback, self.on_request = self.on_request, None
            callback()
        return self.payload


def test_finance_offer_after_position_150_is_scored_before_selection() -> None:
    jobs = [raw_job(f"software-{index:04}") for index in range(160)]
    jobs.append(raw_job("late-finance", title="M&A Investment Banking Intern", content="<p>Fusion acquisition.</p>"))
    connector = GreenhouseJobBoardConnector(SyntheticTransport({"jobs": jobs}))
    result = connector.discover_ranked(BOARD, selection_brief={"domains": ["M&A"], "cities": ["Paris"]})
    assert len(result.jobs) == GREENHOUSE_MAX_JOBS
    assert result.jobs[0]["source_id"] == "late-finance"
    assert result.evaluated_count == 161
    assert result.invalid_count == 0
    assert result.truncated is True


def test_exploration_filters_known_nonconforming_duration_before_selection() -> None:
    jobs = [
        raw_job("short-internship", title="Corporate Finance Intern",
                content="<p>This internship lasts 4 months starting January 2027.</p>"),
        raw_job("unknown-internship", title="Corporate Finance Intern",
                content="<p>This is a finance internship.</p>"),
    ]
    result = GreenhouseJobBoardConnector._normalise(
        BOARD, {"jobs": jobs}, selection_brief={"domains": ["Corporate Finance"]}, internships_only=True
    )
    by_id = {job["source_id"]: job for job in result.jobs}
    assert set(by_id) == {"unknown-internship"}
    assert result.confirmed_count == 0
    assert result.uncertain_count == 1
    assert result.excluded_count == 1
    assert result.filtered_criteria_count == 0
    assert by_id["unknown-internship"]["qualification"]["target_status"] == "to_verify"


def test_selected_jobs_and_tie_order_are_invariant_to_feed_reordering() -> None:
    jobs = [raw_job(f"offer-{index:04}") for index in range(170)]
    jobs.append(raw_job("late-finance", title="M&A Intern"))
    first = GreenhouseJobBoardConnector._normalise(BOARD, {"jobs": jobs}, selection_brief={"domains": ["M&A"]})
    second = GreenhouseJobBoardConnector._normalise(BOARD, {"jobs": list(reversed(jobs))}, selection_brief={"domains": ["M&A"]})
    assert first.jobs == second.jobs
    assert first.jobs[0]["source_id"] == "late-finance"
    tied_ids = [job["source_id"] for job in first.jobs[1:]]
    assert tied_ids == sorted(tied_ids)


def test_selection_uses_the_persons_saved_weights_not_hardcoded_finance_preferences() -> None:
    jobs = [raw_job(f"finance-{index:04}", title="M&A Intern", city="Lyon") for index in range(150)]
    jobs.append(raw_job("late-paris", title="Software Intern", city="Paris"))
    normal = GreenhouseJobBoardConnector._normalise(
        BOARD, {"jobs": jobs}, selection_brief={"domains": ["M&A"], "cities": ["Paris"]}
    )
    location_first = GreenhouseJobBoardConnector._normalise(
        BOARD,
        {"jobs": jobs},
        selection_brief={"domains": ["M&A"], "cities": ["Paris"], "ranking": {"domaine": 0.5, "localisation": 2.0}},
    )
    assert "late-paris" not in {job["source_id"] for job in normal.jobs}
    assert location_first.jobs[0]["source_id"] == "late-paris"


def test_invalid_rows_before_position_150_do_not_occupy_selection_places() -> None:
    invalid = [None, {}, raw_job("unsafe", absolute_url="javascript:alert(1)")]
    jobs = invalid * 51 + [raw_job("valid-late", title="M&A Intern")]
    result = GreenhouseJobBoardConnector._normalise(BOARD, {"jobs": jobs}, selection_brief={"domains": ["M&A"]})
    assert [job["source_id"] for job in result.jobs] == ["valid-late"]
    assert result.evaluated_count == 1
    assert result.invalid_count == 153
    assert result.truncated is False


def test_empty_brief_is_neutral_and_deterministic_not_an_invented_finance_preference() -> None:
    jobs = [raw_job(f"offer-{index:04}") for index in range(150)]
    jobs.append(raw_job("zz-finance", title="M&A Intern"))
    first = GreenhouseJobBoardConnector._normalise(BOARD, {"jobs": jobs})
    second = GreenhouseJobBoardConnector._normalise(BOARD, {"jobs": list(reversed(jobs))})
    assert first.jobs == second.jobs
    assert len(first.jobs) == 150
    assert "zz-finance" not in {job["source_id"] for job in first.jobs}


def test_catchall_finance_domain_uses_the_same_family_classifier_as_import() -> None:
    jobs = [raw_job(f"software-{index:04}") for index in range(150)]
    jobs.append(raw_job("zz-finance", title="Private Equity Intern", content="Capital investissement."))
    result = GreenhouseJobBoardConnector._normalise(
        BOARD, {"jobs": jobs}, selection_brief={"domains": ["Autres métiers financiers"]}
    )
    assert result.jobs[0]["source_id"] == "zz-finance"
    assert result.jobs[0]["job_family"] == "Private Equity"


def test_pathological_feed_is_refused_instead_of_silently_selecting_a_prefix() -> None:
    with pytest.raises(PublicSourceError, match="entièrement évalué") as caught:
        GreenhouseJobBoardConnector._normalise(BOARD, {"jobs": [{}] * (GREENHOUSE_MAX_FEED_ROWS + 1)})
    assert caught.value.code == "too_many_rows"


def test_service_imports_late_finance_offer_using_saved_brief(tmp_path: Path) -> None:
    jobs = [raw_job(f"software-{index:04}") for index in range(160)]
    jobs.append(raw_job("late-finance", title="M&A Intern"))
    transport = SyntheticTransport({"jobs": jobs})
    service = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(transport))
    service.create_discovery_source({"company": BOARD.company, "board_reference": BOARD.board_token})
    service.update_stage_search({"domains": ["M&A"], "cities": ["Paris"]})
    outcome = service.discover_opportunities()["outcomes"][0]
    assert outcome["status"] == "success"
    assert outcome["imported_count"] == 150
    assert "161 entrées admissibles" in outcome["message"]
    assert len(service.list_jobs()) == 150
    assert service.list_stage_matches()["matches"][0]["job"]["title"] == "M&A Intern"
    assert service.discover_opportunities()["outcomes"][0]["status"] == "cached"
    assert transport.calls == 1


def test_changed_criteria_invalidate_selection_cache_without_losing_tracking(tmp_path: Path) -> None:
    jobs = [raw_job(f"audit-{index:04}", title="Financial Audit Intern") for index in range(150)]
    jobs.append(raw_job("zz-finance", title="M&A Intern"))
    transport = SyntheticTransport({"jobs": jobs})
    service = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(transport))
    service.create_discovery_source({"company": BOARD.company, "board_reference": BOARD.board_token})
    service.update_stage_search({"domains": ["Audit financier"]})
    service.discover_opportunities()
    tracked = service.list_jobs()[0]
    service.set_shortlist(tracked["id"], True, "Synthetic retained note")
    application = service.create_application(tracked["id"])
    assert "M&A Intern" not in {job["title"] for job in service.list_jobs()}
    # Reopening must preserve the cached criterion fingerprint, not refetch.
    reopened = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(transport))
    assert reopened.discover_opportunities()["outcomes"][0]["status"] == "cached"
    reopened.update_stage_search({"domains": ["M&A"]})
    assert reopened.discover_opportunities()["outcomes"][0]["status"] == "success"
    assert transport.calls == 2
    assert reopened.list_stage_matches()["matches"][0]["job"]["title"] == "M&A Intern"
    kept = reopened.get_job(tracked["id"])
    assert kept["shortlisted"] is True
    assert kept["personal_note"] == "Synthetic retained note"
    assert kept["application"]["id"] == application["id"]
    assert kept["source_status"] == "open"


def test_inflight_criteria_edit_cannot_cache_old_selection_as_if_it_used_new_criteria(tmp_path: Path) -> None:
    transport = SyntheticTransport({"jobs": [raw_job("audit", title="Financial Audit Intern"), raw_job("finance", title="M&A Intern")]})
    service = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(transport))
    service.create_discovery_source({"company": BOARD.company, "board_reference": BOARD.board_token})
    service.update_stage_search({"domains": ["Audit financier"]})
    transport.on_request = lambda: service.update_stage_search({"domains": ["M&A"]})
    assert service.discover_opportunities()["outcomes"][0]["status"] == "success"
    assert service.discover_opportunities()["outcomes"][0]["status"] == "success"
    assert transport.calls == 2
    assert service.discover_opportunities()["outcomes"][0]["status"] == "cached"


def test_source_failure_preserves_existing_jobs_and_tracking(tmp_path: Path) -> None:
    transport = SyntheticTransport({"jobs": [raw_job("initial", title="M&A Intern")]})
    service = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(transport))
    service.create_discovery_source({"company": BOARD.company, "board_reference": BOARD.board_token})
    service.discover_opportunities()
    job = service.list_jobs()[0]
    application = service.create_application(job["id"])
    transport.payload = {"jobs": [{}] * (GREENHOUSE_MAX_FEED_ROWS + 1)}
    outcome = service.discover_opportunities(force=True)["outcomes"][0]
    assert outcome["status"] == "error"
    assert service.get_job(job["id"])["application"]["id"] == application["id"]
    assert service.get_job(job["id"])["source_status"] == "open"


def test_invalid_source_rows_are_reported_without_hiding_valid_late_offer(tmp_path: Path) -> None:
    transport = SyntheticTransport({"jobs": [{}] * 151 + [raw_job("finance", title="M&A Intern")]})
    service = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(transport))
    service.create_discovery_source({"company": BOARD.company, "board_reference": BOARD.board_token})
    outcome = service.discover_opportunities()["outcomes"][0]
    assert outcome["status"] == "partial"
    assert outcome["skipped_count"] == 151
    assert outcome["found_count"] == outcome["imported_count"] == 1
    assert service.list_jobs()[0]["title"] == "M&A Intern"


def test_displayed_tie_order_survives_feed_reorder_and_restart(tmp_path: Path) -> None:
    jobs = [raw_job("tie-b", title="M&A Intern"), raw_job("tie-a", title="M&A Intern")]
    transport = SyntheticTransport({"jobs": jobs})
    service = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(transport))
    service.create_discovery_source({"company": BOARD.company, "board_reference": BOARD.board_token})
    service.update_stage_search({"domains": ["M&A"]})
    service.discover_opportunities()
    before = [item["job"]["official_url"] for item in service.list_stage_matches()["matches"]]
    transport.payload = {"jobs": list(reversed(jobs))}
    service.discover_opportunities(force=True)
    reopened = CareerService(tmp_path)
    after = [item["job"]["official_url"] for item in reopened.list_stage_matches()["matches"]]
    assert before == after == [jobs[1]["absolute_url"], jobs[0]["absolute_url"]]
