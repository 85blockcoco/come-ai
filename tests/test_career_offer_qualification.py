"""Synthetic qualification contracts; no real offers or network access."""

from __future__ import annotations

import json
import socket
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
def test_synthetic_adversarial_offer_never_overstates_january_six_month_fit(offer):
    expected = offer["expected"]
    result = qualify_offer({key: value for key, value in offer.items() if key != "expected"})
    assert result.target_status == expected
    assert result.contract_type in {"internship", "apprenticeship", "permanent", "fixed_term", "VIE", "graduate", "unknown"}
    assert isinstance(result.missing_fields, tuple)
    if expected == "conforming":
        assert result.contract_type == "internship"
        assert result.duration_min_months is not None and result.duration_min_months >= 6
        assert result.start_date and result.start_date[5:7] == "01"
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
