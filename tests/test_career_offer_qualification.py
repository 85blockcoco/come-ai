"""Synthetic qualification contracts; no real offers or network access."""

from __future__ import annotations

import json
import socket
from datetime import date
from pathlib import Path

import pytest

import career.offer_qualification as offer_qualification
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


def test_geo_criteria_cache_is_reused_only_inside_scoped_operation(monkeypatch):
    calls = 0
    original = offer_qualification._country_codes

    def count_country_codes(values):
        nonlocal calls
        calls += 1
        return original(values)

    monkeypatch.setattr(offer_qualification, "_country_codes", count_country_codes)
    criteria = {"preferred_countries": ["United Kingdom"], "excluded_countries": ["France"]}

    with offer_qualification.scoped_geo_criteria_cache():
        first = offer_qualification.geo_score_for("France", **criteria)
        second = offer_qualification.geo_score_for("France", **criteria)
        assert first == second
        assert calls == 2

    offer_qualification.geo_score_for("France", **criteria)
    assert calls == 4


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


def test_explicit_month_and_year_in_title_are_start_evidence() -> None:
    result = qualify_offer({
        "title": "Debt Advisory Internship (March 2027)",
        "description_original": "This internship lasts six months.",
        "employment_type": "Internship",
        "official_url": "https://careers.example.test/debt-advisory",
        "source_name": "greenhouse",
        "source_id": "debt-advisory-2027",
        "source_verified": True,
    }, as_of=date(2026, 10, 18))
    assert result.start_month == 3
    assert result.target_status == "conforming"
    assert result.provenance["start_month"].source == "title_passage"
    assert result.provenance["start_month"].quote == "March 2027"


def test_internship_language_and_end_period_are_derived_from_explicit_offer_facts() -> None:
    result = qualify_offer({
        "title": "Corporate Finance Internship",
        "description_original": (
            "This internship starts in May 2027 and lasts four months.\n"
            "Requirements:\nFluent English is required.\nFrench would be a plus."
        ),
        "official_url": "https://careers.example.test/corporate-finance-internship",
        "source_name": "greenhouse",
        "source_id": "finance-internship-may-2027",
        "source_verified": True,
    }, as_of=date(2026, 10, 18))

    assert result.contract_type == "internship"
    assert result.duration_min_months == result.duration_max_months == 4
    assert result.start_month == 5
    assert result.end_date is None  # month-only source: never invent a day
    assert (result.end_month, result.end_year) == (8, 2027)
    assert result.end_date_estimated is True
    assert result.language_requirements == "Anglais requis · Français souhaité"
    assert result.provenance["end_month"].source == "calculated_from_start_and_duration"
    assert result.provenance["language_requirements"].quote == (
        "Fluent English is required. | French would be a plus."
    )


def test_exact_start_and_duration_calculate_an_explicitly_labelled_end_date() -> None:
    result = qualify_offer({
        "title": "Finance Internship",
        "employment_type": "Internship",
        "start_date": "2027-05-01",
        "duration_months": 4,
    }, as_of=date(2026, 10, 18))

    assert result.end_date == "2027-08-31"
    assert (result.end_month, result.end_year) == (8, 2027)
    assert result.end_date_estimated is True
    assert result.provenance["end_date"].source == "calculated_from_start_and_duration"


def test_month_range_in_title_uses_first_month_but_does_not_invent_duration() -> None:
    result = qualify_offer({
        "title": "Stockholm - M&A Internship Jan-June 2027",
        "description_original": "Investment banking internship.",
        "employment_type": "Internship",
        "official_url": "https://careers.example.test/stockholm",
        "source_name": "greenhouse",
        "source_id": "stockholm-2027",
        "source_verified": True,
    }, as_of=date(2026, 10, 18))
    assert result.start_month == 1
    assert result.duration_min_months is None
    assert result.target_status == "to_verify"


@pytest.mark.parametrize("title", [
    "Quantitative Trading Internship Summer 2027",
    "Apply by March 2027 - Finance Internship",
    "Finance Internship Q3 2027",
])
def test_title_seasons_deadlines_and_quarters_do_not_invent_start_month(title: str) -> None:
    result = qualify_offer({
        "title": title,
        "description_original": "Six month internship; start date to be confirmed.",
        "employment_type": "Internship",
        "official_url": "https://careers.example.test/unknown-start",
        "source_name": "greenhouse",
        "source_id": title,
        "source_verified": True,
    }, as_of=date(2026, 10, 18))
    assert result.start_month is None
    assert result.target_status == "to_verify"


def test_education_requirement_is_exposed_with_exact_quote() -> None:
    """SK-19 : le niveau d'études requis apparaît dans la provenance, cité verbatim."""
    description = "Nous recherchons un stagiaire. Bac+5 minimum (Finance) requis pour ce poste."
    result = qualify_offer({
        "title": "Finance Intern",
        "description_original": description,
        "employment_type": "Internship",
        "official_url": "https://careers.example.test/education",
        "source_name": "greenhouse",
        "source_id": "education-1",
        "source_verified": True,
    }, as_of=date(2026, 10, 18))
    fact = result.provenance["education_required"]
    assert fact.value == 5
    assert fact.source == "description_passage"
    assert fact.quote == "Bac+5"
    assert description[description.index(fact.quote):description.index(fact.quote) + len(fact.quote)] == fact.quote


def test_offer_without_education_requirement_has_no_education_evidence() -> None:
    result = qualify_offer({
        "title": "Finance Intern",
        "description_original": "Six month internship in a friendly team; start date to be confirmed.",
        "employment_type": "Internship",
        "official_url": "https://careers.example.test/no-education",
        "source_name": "greenhouse",
        "source_id": "education-2",
        "source_verified": True,
    }, as_of=date(2026, 10, 18))
    assert "education_required" not in result.provenance


def test_negated_education_mention_never_becomes_evidence() -> None:
    result = qualify_offer({
        "title": "Finance Intern",
        "description_original": "Poste ouvert sans diplôme d'ingénieur requis.",
        "employment_type": "Internship",
        "official_url": "https://careers.example.test/negated-education",
        "source_name": "greenhouse",
        "source_id": "education-3",
        "source_verified": True,
    }, as_of=date(2026, 10, 18))
    assert "education_required" not in result.provenance
