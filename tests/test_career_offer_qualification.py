"""Synthetic qualification contracts; no real offers or network access."""

from __future__ import annotations

import json
import socket
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from career.offer_qualification import qualify_offer


FIXTURES = Path(__file__).parent / "fixtures" / "career_offer_qualification_synthetic.json"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network is forbidden in synthetic qualification tests")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, blocked)


@pytest.mark.parametrize("offer", json.loads(FIXTURES.read_text(encoding="utf-8")), ids=lambda item: item["id"])
def test_synthetic_adversarial_offer_never_overstates_configured_search_fit(offer):
    expected = offer["expected"]
    result = qualify_offer({key: value for key, value in offer.items() if key != "expected"})
    assert result.target_status == expected
    assert result.contract_type in {"internship", "apprenticeship", "permanent", "fixed_term", "VIE", "graduate", "unknown", "ambiguous"}
    assert isinstance(result.missing_fields, tuple)
    if expected == "conforming":
        assert result.contract_type in {"internship", "fixed_term", "permanent", "VIE"}
        if result.contract_type == "internship":
            assert result.duration_min_months is not None and result.duration_min_months >= 6
        assert result.start_date and int(result.start_date[5:7]) in {1, 2, 3}
        assert result.verification_status == "verified"


def test_each_known_fact_has_source_provenance_and_unknowns_remain_unknown():
    result = qualify_offer({"title": "Finance Intern", "official_url": "https://careers.example.test/job",
                            "source_name": "greenhouse", "source_id": "synthetic-1", "source_verified": True,
                            "start_date": "2027-01-01", "duration_months": 6,
                            "country": "France", "city": "Paris", "language": "French"})
    assert result.provenance["start_date"].source == "source_field:start_date"
    assert result.provenance["duration_min_months"].source == "source_field:duration_months"
    assert result.provenance["city"].value == "Paris"
    assert result.missing_fields


def test_missing_official_link_never_yields_verified_qualification():
    result = qualify_offer({"title": "Finance Intern", "start_date": "2027-01-01", "duration_months": 6,
                            "source_name": "greenhouse", "source_id": "synthetic-2", "source_verified": True})
    assert result.verification_status == "unverified"
    assert result.target_status == "to_verify"


def test_valid_six_month_date_range_can_prove_duration():
    result = qualify_offer({"title": "Finance Intern", "official_url": "https://careers.example.test/range",
                            "source_name": "greenhouse", "source_id": "synthetic-range", "source_verified": True,
                            "start_date": "2027-01-01", "end_date": "2027-07-01",
                            "language": "English", "country": "France", "city": "Paris"},
                           as_of=date(2026, 10, 18))
    assert result.duration_min_months == result.duration_max_months == 6
    assert result.target_status == "conforming"
    assert result.provenance["duration_min_months"].source == "source_date_range"


def test_ambiguous_date_range_does_not_round_up_to_six_months():
    result = qualify_offer({"title": "Finance Intern", "official_url": "https://careers.example.test/ambiguous-range",
                            "source_name": "greenhouse", "source_id": "synthetic-range-2", "source_verified": True,
                            "start_date": "2027-01-15", "end_date": "2027-07-14",
                            "language": "English", "country": "France", "city": "Paris"},
                           as_of=date(2026, 10, 18))
    assert result.duration_min_months == 5
    assert result.duration_max_months == 6
    assert result.target_status == "to_verify"


def test_invalid_iso_date_is_reported_as_missing_not_as_a_month():
    result = qualify_offer({"title": "Finance Intern", "start_date": "2027-13-01", "duration_months": 6,
                            "official_url": "https://careers.example.test/invalid-date",
                            "source_name": "greenhouse", "source_id": "synthetic-invalid-date", "source_verified": True})
    assert result.start_date is None
    assert result.start_month is None
    assert "début" in result.missing_fields
    assert result.target_status == "to_verify"
