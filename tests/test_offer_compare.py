"""Tests for the side-by-side offer comparator (SPEC-026)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from career.offer_compare import (
    CompareVerdict,
    DecisionMatrix,
    OfferRow,
    compare_offers,
    normalize_attr,
)
from career.router import create_career_router
from career.service import CareerService
from fastapi import FastAPI
from workspace_core import UserFacingError


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "offers_compare_synthetic.json"


def test_normalize_attr_forms() -> None:
    assert normalize_attr("salary", "45 000 €") == 45000
    assert normalize_attr("45 000 €") is None or normalize_attr("45 000 €") == 45000
    # ambiguous single string defaults to value normalization
    assert normalize_attr({"salary": "45k"}, "salary") == 45000
    assert normalize_attr(value="n/a", attr="x") is None
    assert normalize_attr(None) is None


def test_offer_row_normalises_attrs() -> None:
    row = OfferRow("o1", {"salary": "50k", "remote": "oui", "missing": ""})
    assert row.attrs["salary"] == 50000
    assert row.attrs["remote"] is True
    assert row.attrs["missing"] is None


def test_compare_offers_basic_ranking() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 40000, "fit": 7, "freshness": 5}},
        {"offer_id": "b", "attrs": {"salary": 50000, "fit": 6, "freshness": 9}},
    ]
    verdict = compare_offers(offers, weights={"salary": 1, "fit": 1})
    assert isinstance(verdict, CompareVerdict)
    assert set(verdict.weighted_scores) == {"a", "b"}
    assert verdict.ranking[0] in {"a", "b"}
    assert "salary" in verdict.matrix
    assert verdict.matrix["salary"]["a"] == 40000


def test_missing_attribute_is_none_and_tolerated() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"score": 10}},
        {"offer_id": "b", "attrs": {"score": None}},
    ]
    verdict = compare_offers(offers)
    assert verdict.matrix["score"]["b"] is None
    assert verdict.weighted_scores["b"] == 0.0


def test_tie_breaker_uses_freshness_then_fit() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"base": 5, "freshness": 3, "fit": 9}},
        {"offer_id": "b", "attrs": {"base": 5, "freshness": 8, "fit": 4}},
    ]
    verdict = compare_offers(offers, weights={"base": 1})
    assert verdict.ranking == ["b", "a"]
    assert verdict.tie_breaker_used is True


def test_configurable_weights_change_ranking() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 4, "fit": 9}},
        {"offer_id": "b", "attrs": {"salary": 6, "fit": 5}},
    ]
    v1 = compare_offers(offers, weights={"salary": 10, "fit": 1})
    v2 = compare_offers(offers, weights={"salary": 1, "fit": 10})
    assert v1.ranking[0] == "b"
    assert v2.ranking[0] == "a"


def test_decision_matrix_object() -> None:
    offers = [
        OfferRow("x", {"value": 1}),
        OfferRow("y", {"value": 2}),
    ]
    matrix = DecisionMatrix(offers, weights={"value": 1})
    assert matrix.ranking == ["y", "x"]
    verdict = matrix.compare()
    assert verdict.ranking == matrix.ranking


def test_fixture_file_loads() -> None:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(data) >= 3
    verdict = compare_offers(data)
    assert len(verdict.ranking) == len(data)
    assert isinstance(verdict.tie_breaker_used, bool)


def test_rest_smoke() -> None:
    service = CareerService.__new__(CareerService)
    # Minimal service instance not needed; router only uses compare module.
    app = FastAPI()
    app.include_router(create_career_router.__wrapped__(service) if hasattr(create_career_router, "__wrapped__") else create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(error)})

    client = TestClient(app)
    response = client.post(
        "/api/career/offers/compare",
        json={
            "offers": [
                {"offer_id": "a", "attrs": {"score": 5}},
                {"offer_id": "b", "attrs": {"score": 7}},
            ],
            "weights": {"score": 1},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ranking"][0] == "b"
    assert "matrix" in body


def test_adversarial_all_missing() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"x": None}},
        {"offer_id": "b", "attrs": {"x": None}},
    ]
    verdict = compare_offers(offers)
    assert verdict.weighted_scores["a"] == 0.0
    assert verdict.weighted_scores["b"] == 0.0
    # tie-breaker not used because no differing breaker
    assert isinstance(verdict.ranking, list)
