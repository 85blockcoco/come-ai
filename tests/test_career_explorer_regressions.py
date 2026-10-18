"""Regressions found during real public-board browser acceptance, no network."""
import pytest

from career.discovery import GreenhouseBoard, GreenhouseJobBoardConnector
from career.exploration import classify_internship
from career.stage_search import validate_brief
from test_career_exploration import posting, service_with


@pytest.mark.parametrize("title,description,expected", [
    ("Graduate Quantitative Researcher (2027 Start)", "If you interviewed for a quantitative graduate or internship role in the past eight months, you are not eligible to reapply.", "uncertain"),
    ("Quantitative Researcher", "Previous internship experience. Our internship program is available separately.", "uncertain"),
    ("2027 Internship or Graduate, FPGA Engineering", "As an intern or graduate, join our team.", "uncertain"),
    ("Quantitative Researcher", "As an intern or graduate, join our team.", "uncertain"),
    ("Quantitative Research Intern", "Our graduate program is also available.", "confirmed"),
    ("Finance Analyst", "As an intern, you will perform valuation.", "confirmed"),
])
def test_live_false_positive_examples_do_not_become_confirmed_stages(title, description, expected):
    assert classify_internship({"title": title, "description_original": description})["status"] == expected


@pytest.mark.parametrize("metadata,retained", [
    ([{"name": "Employment Type", "value": "Permanent"}], True),
    ([{"name": "Requisition Type", "value": "CDI"}], True),
    ([{"name": "Employment Type", "value": ["Internship", "Graduate"]}], True),
    ([{"name": "Employment Type", "value": "Graduate"}], True),
    ([{"name": "Time Type", "value": "Full Time"}], True),
    ([{"name": "Employment Type", "value": "Intern"}], True),
    ([{"name": "Unrelated", "value": "Permanent"}], True),
])
def test_contract_metadata_not_working_hours_decides_admission(metadata, retained):
    feed = [posting(1, metadata=metadata)]
    payload = GreenhouseJobBoardConnector._normalise(GreenhouseBoard("fiction", "Finance", "fiction"),
                                                    {"jobs": feed}, internships_only=True)
    assert bool(payload.jobs) is retained
    if payload.jobs:
        assert payload.jobs[0]["qualification"]["target_status"] == "to_verify"


@pytest.mark.parametrize("title,retained", [
    ("Hardware Engineering Intern", False), ("Security Engineer Intern", False),
    ("FPGA Engineering Intern", False), ("Quantitative Research Intern", True),
    ("Financial Engineering Intern", True), ("IT Operations - Workplace (Internship)", False),
    ("Investment Operations Intern", True),
])
def test_investment_firm_boilerplate_does_not_make_an_engineering_role_financial(title, retained):
    payload = GreenhouseJobBoardConnector._normalise(
        GreenhouseBoard("fiction", "Finance", "fiction"),
        {"jobs": [posting(1, title, content="This internship covers quantitative research and trading. Financial analysis.")]},
        internships_only=True, selection_brief=validate_brief({"domains": ["Autres métiers financiers"],
                                                              "other_domains": ["quantitative research", "trading"]}))
    assert bool(payload.jobs) is retained


def test_explorer_refresh_preserves_known_dates_requirements_and_followup(tmp_path):
    service, _ = service_with(tmp_path, {"fiction": [posting(1)]})
    existing = service.import_job({"company": "Finance fiction", "title": "Corporate Finance Intern",
        "official_url": "https://careers.example.test/jobs/1", "start_date": "2027-01-04",
        "end_date": "2027-06-30", "deadline_date": "2026-12-01", "duration_months": 6,
        "requirements": "Conditions synthétiques", "languages_required": "French", "country": "France"})
    application = service.create_application(existing["id"])
    before = service.get_job(existing["id"])
    with service._connection() as connection:
        application_before = dict(connection.execute("SELECT * FROM applications WHERE id = ?", (application["id"],)).fetchone())
    service.explore_internships()
    after = service.get_job(existing["id"])
    for field in ("start_date", "end_date", "deadline_date", "duration_months", "requirements", "languages_required"):
        assert after[field] == before[field]
    assert after["application"]["id"] == application["id"]
    with service._connection() as connection:
        application_after = dict(connection.execute("SELECT * FROM applications WHERE id = ?", (application["id"],)).fetchone())
    assert application_after == application_before


@pytest.mark.parametrize("location", ["London, England, United Kingdom", "Amsterdam, North Holland, Netherlands"])
def test_explicit_country_in_three_part_location_is_not_replaced_with_unknown(location):
    payload = GreenhouseJobBoardConnector._normalise(
        GreenhouseBoard("fiction", "Finance", "fiction"), {"jobs": [posting(1, location={"name": location})]},
        internships_only=True, selection_brief=validate_brief({"countries": ["France"]}))
    assert not payload.jobs and payload.filtered_criteria_count == 1
