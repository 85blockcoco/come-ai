"""Synthetic regression tests for user-configurable contract/month criteria."""

from __future__ import annotations

import socket
from datetime import date

import pytest

from career.offer_qualification import qualify_offer
from career.service import CareerService
from career.stage_search import STAGE_DOMAINS, brief_is_configured, default_brief, validate_brief


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network is forbidden in synthetic criteria tests")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, blocked)


def offer(title: str, employment_type: str, month: int, *, duration: int | None = None,
          deadline: str = "2027-01-01"):
    value = {
        "title": title, "employment_type": employment_type,
        "official_url": "https://careers.example.test/synthetic-role",
        "source_name": "synthetic", "source_id": "synthetic-role", "source_verified": True,
        "start_date": f"2027-{month:02d}-01", "deadline_date": deadline,
    }
    if duration is not None:
        value["duration_months"] = duration
    return value


@pytest.mark.parametrize("month", [1, 2, 3])
def test_stage_in_each_default_quarter_month_can_qualify(month):
    result = qualify_offer(offer("Finance Intern", "Internship", month, duration=6), as_of=date(2026, 10, 18))
    assert result.contract_type == "internship"
    assert result.target_status == "conforming"


def test_april_stage_is_excluded_by_default_month_selection():
    result = qualify_offer(offer("Finance Intern", "Internship", 4, duration=6), as_of=date(2026, 10, 18))
    assert result.target_status == "non_conforming"


@pytest.mark.parametrize("title,employment,month,expected_type", [
    ("Financial Analyst", "CDD", 2, "fixed_term"),
    ("Financial Analyst", "CDI", 3, "permanent"),
    ("Finance VIE Analyst", "VIE", 1, "VIE"),
])
def test_selected_non_intern_contracts_can_qualify_without_stage_duration(title, employment, month, expected_type):
    result = qualify_offer(offer(title, employment, month), as_of=date(2026, 10, 18))
    assert result.contract_type == expected_type
    assert result.target_status == "conforming"


@pytest.mark.parametrize("missing", ["start_date", "duration_months"])
def test_stage_missing_date_or_duration_never_qualifies_automatically(missing):
    value = offer("Finance Intern", "Internship", 1, duration=6)
    value.pop(missing, None)
    result = qualify_offer(value, as_of=date(2026, 10, 18))
    assert result.target_status == "to_verify"


def test_ambiguous_contract_stays_to_verify():
    value = offer("Financial Analyst", "CDD or CDI", 2)
    result = qualify_offer(value, as_of=date(2026, 10, 18))
    assert result.contract_type == "ambiguous"
    assert result.target_status == "to_verify"


def test_expired_offer_is_excluded():
    value = offer("Finance Intern", "Internship", 1, duration=6, deadline="2026-10-17")
    result = qualify_offer(value, as_of=date(2026, 10, 18))
    assert result.target_status == "non_conforming"


def test_unknown_dates_and_duration_are_not_invented():
    value = offer("Finance Intern", "Internship", 1, duration=6)
    value.pop("start_date")
    value.pop("duration_months")
    result = qualify_offer(value, as_of=date(2026, 10, 18))
    assert result.target_status == "to_verify"
    assert result.start_date is None
    assert result.duration_min_months is None and result.duration_max_months is None
    assert "start_date" not in result.provenance
    assert "duration_min_months" not in result.provenance


def test_contract_and_month_criteria_validate_and_persist_locally(tmp_path):
    defaults = default_brief()
    assert defaults["domains"] == []
    assert defaults["contract_types"] == ["stage", "cdd", "cdi", "vie"]
    assert defaults["start_months"] == [1, 2, 3]
    assert defaults["minimum_stage_duration_months"] == 6
    assert set(CareerService(tmp_path).get_stage_search()["brief"]["domains"]) == set(STAGE_DOMAINS)
    chosen = validate_brief({"contract_types": ["cdd", "vie"], "start_months": [2, 12],
                             "minimum_stage_duration_months": 8})
    assert chosen["contract_types"] == ["cdd", "vie"]
    assert chosen["start_months"] == [2, 12]
    assert chosen["minimum_stage_duration_months"] == 8
    service = CareerService(tmp_path)
    saved = service.update_stage_search(chosen)
    restarted = CareerService(tmp_path).get_stage_search()["brief"]
    assert saved["brief"] == chosen == restarted


def test_saved_month_and_contract_criteria_are_reused_by_matching(tmp_path):
    service = CareerService(tmp_path)
    for month in (2, 4):
        service.import_job({
            "company": "Synthetic Finance",
            "title": "M&A Intern",
            "source_name": "synthetic",
            "source_id": f"synthetic-{month}",
            "official_url": f"https://careers.example.test/synthetic-{month}",
            "job_family": "M&A / Investment Banking",
            "city": "Paris",
            "country": "France",
            "start_date": f"2027-{month:02d}-01",
            "duration_months": 6,
            "source_status": "open",
            "description_original": "Synthetic internship for regression testing.",
            "source_verified": True,
        })
    service.update_stage_search({"domains": ["M&A"], "contract_types": ["stage"], "start_months": [2]})
    matches = service.list_stage_matches()
    by_month = {item["job"]["start_date"][5:7]: item for item in matches["matches"]}
    assert by_month["02"]["stage_match"]["qualification_status"] == "to_verify"
    assert by_month["04"]["stage_match"]["qualification_status"] == "non_conforming"


@pytest.mark.parametrize("employment", ["CDD", "CDI", "VIE"])
def test_selected_contract_fact_preserves_its_source_evidence(employment):
    result = qualify_offer(offer("Finance Analyst", employment, 2), as_of=date(2026, 10, 18))
    assert result.provenance["contract_type"].quote == employment
    assert result.provenance["contract_type"].source == "source_field:employment_type"


def test_application_month_is_never_invented_as_a_start_month():
    value = offer("Finance Intern", "Internship", 1, duration=6)
    value.pop("start_date")
    value["description_original"] = "Apply before January 2027; start date to be determined."
    result = qualify_offer(value, as_of=date(2026, 10, 18))
    assert result.target_status == "to_verify"
    assert result.start_month is None


def test_known_short_duration_excludes_stage_even_if_start_is_missing():
    value = offer("Finance Intern", "Internship", 1, duration=4)
    value.pop("start_date")
    assert qualify_offer(value, as_of=date(2026, 10, 18)).target_status == "non_conforming"


def test_personalized_contract_and_month_filters_alone_configure_the_search():
    assert brief_is_configured(validate_brief({"contract_types": ["cdd"], "start_months": [12]}))


@pytest.mark.parametrize("provider", ["greenhouse", "lever"])
@pytest.mark.parametrize("contract", ["CDD", "CDI", "VIE"])
def test_real_connector_path_keeps_selected_non_intern_contracts(provider, contract):
    from career.discovery import GreenhouseBoard, GreenhouseJobBoardConnector
    from career.connectors import LeverConnector
    # This regression isolates contract handling; an explicit empty domain list
    # disables the separate finance-domain filter.
    brief = validate_brief({"domains": [], "contract_types": [contract.lower()], "start_months": [3]})
    text = "Synthetic finance role. Starts in March 2027."
    if provider == "greenhouse":
        raw = {"jobs": [{"id": "synthetic-contract", "title": "Finance Analyst",
                        "absolute_url": "https://careers.example.test/synthetic-contract",
                        "content": text, "metadata": [{"name": "Employment Type", "value": contract}]}]}
        result = GreenhouseJobBoardConnector._normalise(
            GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"), raw,
            selection_brief=brief, internships_only=True)
    else:
        class Feed:
            def get_json(self, *_args, **_kwargs):
                return [{"id": "synthetic-contract", "text": "Finance Analyst", "descriptionPlain": text,
                         "hostedUrl": "https://jobs.lever.co/synthetic/synthetic-contract",
                         "categories": {"commitment": contract}}]
        source = {"id": "synthetic", "company": "Synthetic Finance", "provider": "lever",
                  "board_token": "synthetic", "verified_at": "2026-10-18T00:00:00Z",
                  "provenance_url": "https://careers.example.test/synthetic"}
        result = LeverConnector(transport=Feed(), enabled=True).discover_internships(source, selection_brief=brief)
    assert len(result.jobs) == 1
    assert result.jobs[0]["qualification"]["target_status"] == "conforming"


@pytest.mark.parametrize("text,expected", [
    ("This internship starts in January 2027 and lasts 3–6 months.", "to_verify"),
    ("This internship starts in January 2027 and lasts 6–12 months.", "conforming"),
    ("This internship starts in January 2027 and lasts up to 6 months.", "to_verify"),
    ("Ce stage débute en février 2027 pour six mois.", "conforming"),
])
def test_description_durations_do_not_invent_a_guaranteed_minimum(text, expected):
    value = offer("Finance Intern", "Internship", 1)
    value.pop("start_date")
    value["description_original"] = text
    result = qualify_offer(value, as_of=date(2026, 10, 18))
    assert result.target_status == expected


@pytest.mark.parametrize("field", ["contract_types", "start_months"])
def test_empty_checkbox_selection_is_rejected_clearly(field):
    from workspace_core import UserFacingError
    with pytest.raises(UserFacingError, match="Sélectionne au moins"):
        validate_brief({field: []})


def test_education_preference_persists_without_changing_candidate_degree(tmp_path):
    service = CareerService(tmp_path)
    service.update_stage_search({"education_preference": "any"})
    assert CareerService(tmp_path).get_stage_search()["brief"]["education_preference"] == "any"
    assert service.get_profile()["education"] == ""


def test_bachelor_preference_breaks_equal_relevance_ties_without_excluding_m2():
    from career.discovery import GreenhouseBoard, GreenhouseJobBoardConnector
    rows = []
    for identifier, level in (("a", "Master 2 degree required."), ("z", "Bachelor degree required."), ("b", "")):
        rows.append({"id": identifier, "title": "Corporate Finance Intern",
                     "absolute_url": f"https://careers.example.test/synthetic-{identifier}",
                     "content": f"Synthetic internship starts in January 2027 and lasts six months. Requirements: {level}"})
    result = GreenhouseJobBoardConnector._normalise(
        GreenhouseBoard("synthetic", "Synthetic Finance", "synthetic"), {"jobs": rows},
        selection_brief=validate_brief({"domains": ["Corporate Finance"]}), internships_only=True)
    assert [job["source_id"] for job in result.jobs] == ["z", "a", "b"]
    assert all(job["qualification"]["target_status"] == "conforming" for job in result.jobs)


def test_configurable_fields_survive_the_real_http_request_model(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from career.router import create_career_router
    service = CareerService(tmp_path)
    app = FastAPI()
    app.include_router(create_career_router(service))
    with TestClient(app) as client:
        response = client.put("/api/career/stage-search", json={
            "contract_types": ["cdd", "vie"], "start_months": [2, 12],
            "minimum_stage_duration_months": 8, "education_preference": "any"})
        assert response.status_code == 200
        brief = client.get("/api/career/stage-search").json()["brief"]
        assert brief["contract_types"] == ["cdd", "vie"] and brief["start_months"] == [2, 12]
        assert brief["minimum_stage_duration_months"] == 8 and brief["education_preference"] == "any"
