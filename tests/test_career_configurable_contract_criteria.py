"""Synthetic regression tests for user-configurable contract/month criteria."""

from __future__ import annotations

import socket
from datetime import date

import pytest

from career.offer_qualification import qualify_offer
from career.service import CareerService
from career.stage_search import default_brief, validate_brief


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
    assert defaults["contract_types"] == ["stage", "cdd", "cdi", "vie"]
    assert defaults["start_months"] == [1, 2, 3]
    assert defaults["minimum_stage_duration_months"] == 6
    chosen = validate_brief({"contract_types": ["cdd", "vie"], "start_months": [2, 12],
                             "minimum_stage_duration_months": 8})
    assert chosen["contract_types"] == ["cdd", "vie"]
    assert chosen["start_months"] == [2, 12]
    assert chosen["minimum_stage_duration_months"] == 8
    service = CareerService(tmp_path)
    saved = service.update_stage_search(chosen)
    restarted = CareerService(tmp_path).get_stage_search()["brief"]
    assert saved["brief"] == chosen == restarted
