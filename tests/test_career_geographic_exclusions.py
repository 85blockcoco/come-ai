"""International-search regressions: France/Paris excluded by explicit saved criteria."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from career.offer_qualification import qualify_offer
from career.service import CareerService
from come_ai_web import create_app


def _offer(**updates):
    value = {
        "company": "Synthetic Finance",
        "title": "Corporate Finance Intern",
        "employment_type": "Internship",
        "official_url": "https://example.test/jobs/international-role",
        "source_name": "greenhouse",
        "source_id": "international-role",
        "source_verified": True,
        "source_status": "open",
        "start_date": "2027-01-15",
        "duration_months": 6,
        "country": "United Kingdom",
        "city": "London",
        "description_original": "Corporate Finance internship for six months.",
    }
    value.update(updates)
    return value


def _qualify(offer):
    return qualify_offer(
        offer,
        excluded_countries=["France"],
        excluded_cities=["Paris"],
        require_known_location=True,
        as_of=date(2026, 10, 21),
    )


def test_france_and_paris_are_non_conforming_but_foreign_offer_can_conform() -> None:
    france = _qualify(_offer(country="France", city="Lyon"))
    paris = _qualify(_offer(country="", city="Paris"))
    london = _qualify(_offer())
    assert france.target_status == "non_conforming"
    assert france.geography_status == "excluded"
    assert paris.target_status == "non_conforming"
    assert london.target_status == "conforming"
    assert london.geography_status == "allowed"


def test_unknown_or_mixed_location_is_never_automatically_conforming() -> None:
    unknown = _qualify(_offer(country="", city=""))
    mixed = _qualify(_offer(country="", city="Paris, London"))
    assert unknown.target_status == "to_verify"
    assert unknown.geography_status == "unknown"
    assert mixed.target_status == "to_verify"
    assert mixed.geography_status == "mixed"


def test_exclusions_are_editable_and_not_a_hidden_global_rule() -> None:
    allowed = qualify_offer(
        _offer(country="France", city="Paris"),
        excluded_countries=[],
        excluded_cities=[],
        require_known_location=False,
        as_of=date(2026, 10, 21),
    )
    assert allowed.geography_status == "allowed"
    assert allowed.target_status == "conforming"


def test_first_run_and_http_save_preserve_international_defaults(tmp_path) -> None:
    service = CareerService(tmp_path)
    initial = service.get_stage_search()["brief"]
    assert initial["excluded_countries"] == ["France"]
    assert initial["excluded_cities"] == ["Paris"]
    assert initial["require_known_location"] is True

    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.put("/api/career/stage-search", json={"domains": ["Corporate Finance"]})
        assert response.status_code == 200
        saved = response.json()["brief"]
    assert saved["excluded_countries"] == ["France"]
    assert saved["excluded_cities"] == ["Paris"]
    assert saved["require_known_location"] is True


def test_saved_empty_exclusions_remain_empty(tmp_path) -> None:
    service = CareerService(tmp_path)
    saved = service.update_stage_search(
        {
            "domains": ["Corporate Finance"],
            "excluded_countries": [],
            "excluded_cities": [],
            "require_known_location": False,
        }
    )["brief"]
    assert saved["excluded_countries"] == []
    assert saved["excluded_cities"] == []
    assert saved["require_known_location"] is False
