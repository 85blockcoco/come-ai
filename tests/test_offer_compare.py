"""Tests for the side-by-side offer comparator (SPEC-026)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.offer_compare import (
    CompareVerdict,
    DecisionMatrix,
    OfferRow,
    compare_offers,
    normalize_attr,
    verdict_to_dict,
)
from come_ai_web import create_app


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "offers_compare_synthetic.json"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def test_normalize_attr_forms() -> None:
    assert normalize_attr("salary", "45 000 €") == 45000
    assert normalize_attr("45 000 €") == 45000
    # ambiguous single string defaults to value normalization
    assert normalize_attr({"salary": "45k"}, "salary") == 45000
    assert normalize_attr(value="n/a", attr="x") is None
    assert normalize_attr(None) is None


def test_normalize_attr_numbers() -> None:
    assert normalize_attr("salary", "1 234,50 €") == 1234.5
    assert normalize_attr("salary", "1,234.50") == 1234.5
    assert normalize_attr("salary", "45k") == 45000
    assert normalize_attr("salary", "1,5M") == 1_500_000.0
    assert normalize_attr("bonus", "12%") == 12
    assert normalize_attr("delta", "-7") == -7
    assert normalize_attr("delta", 0) == 0
    assert isinstance(normalize_attr("delta", 3.5), float)


def test_normalize_attr_missing_tokens_become_none() -> None:
    for token in ("", "   ", "n/a", "N.A.", "nc", "none", "null", "inconnu", "—", "-"):
        assert normalize_attr("x", token) is None, token


def test_normalize_attr_bool_date_and_containers() -> None:
    assert normalize_attr("remote", "oui") is True
    assert normalize_attr("remote", "non") is False
    assert normalize_attr("start", "2026-10-01") == "2026-10-01"
    assert normalize_attr("start", "01/10/2026") == "2026-10-01"
    assert normalize_attr("tags", ["Excel", " Python "]) == "Excel, Python"
    assert normalize_attr("tags", []) is None
    assert normalize_attr("scores", [1, 2]) == [1, 2]


def test_normalize_attr_rejects_too_many_positional_arguments() -> None:
    with pytest.raises(TypeError):
        normalize_attr("a", "b", "c")


def test_offer_row_normalises_attrs() -> None:
    row = OfferRow("o1", {"salary": "50k", "remote": "oui", "missing": ""})
    assert row.attrs["salary"] == 50000
    assert row.attrs["remote"] is True
    assert row.attrs["missing"] is None


# ---------------------------------------------------------------------------
# Matrice, score et classement
# ---------------------------------------------------------------------------
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


def test_missing_attribute_never_defaults_to_zero_in_the_score() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 100, "fit": 10}},
        {"offer_id": "b", "attrs": {"salary": None, "fit": 6}},
    ]
    verdict = compare_offers(offers, weights={"salary": 1, "fit": 1})
    assert verdict.matrix["salary"]["b"] is None
    # b is scored on its available evidence (fit only), not penalised as salary=0.
    assert verdict.weighted_scores["a"] == 55.0
    assert verdict.weighted_scores["b"] == 6.0


def test_missing_attributes_are_aligned_explicitly_in_matrix() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 10, "fit": 1}},
        {"offer_id": "b", "attrs": {"salary": 20}},
    ]
    verdict = compare_offers(offers, weights={"salary": 1, "fit": 1})
    assert verdict.matrix["fit"] == {"a": 1, "b": None}
    assert verdict.matrix["salary"] == {"a": 10, "b": 20}


def test_configurable_weights_change_ranking() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 4, "fit": 9}},
        {"offer_id": "b", "attrs": {"salary": 6, "fit": 5}},
    ]
    v1 = compare_offers(offers, weights={"salary": 10, "fit": 1})
    v2 = compare_offers(offers, weights={"salary": 1, "fit": 10})
    assert v1.ranking[0] == "b"
    assert v2.ranking[0] == "a"


def test_weight_names_are_case_and_separator_insensitive() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 4, "fit": 9}},
        {"offer_id": "b", "attrs": {"salary": 6, "fit": 5}},
    ]
    verdict = compare_offers(offers, weights={"Salary": 10, "FIT": 1})
    assert verdict.ranking[0] == "b"


def test_scaling_all_weights_does_not_change_the_ranking() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 4, "fit": 9}},
        {"offer_id": "b", "attrs": {"salary": 6, "fit": 5}},
    ]
    base = compare_offers(offers, weights={"salary": 2, "fit": 1})
    scaled = compare_offers(offers, weights={"salary": 200, "fit": 100})
    assert base.ranking == scaled.ranking


def test_zero_weight_ignores_attribute() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 100, "fit": 1}},
        {"offer_id": "b", "attrs": {"salary": 1, "fit": 2}},
    ]
    verdict = compare_offers(offers, weights={"salary": 0, "fit": 1})
    assert verdict.ranking == ["b", "a"]


def test_higher_is_better_override() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"risk": 1}},
        {"offer_id": "b", "attrs": {"risk": 5}},
    ]
    default = compare_offers(offers, weights={"risk": 1})
    overridden = compare_offers(offers, weights={"risk": 1}, higher_is_better={"risk": True})
    assert default.ranking == ["a", "b"]
    assert overridden.ranking == ["b", "a"]


def test_decision_matrix_object() -> None:
    offers = [
        OfferRow("x", {"value": 1}),
        OfferRow("y", {"value": 2}),
    ]
    matrix = DecisionMatrix(offers, weights={"value": 1})
    assert matrix.ranking == ["y", "x"]
    verdict = matrix.compare()
    assert verdict.ranking == matrix.ranking
    assert matrix.as_dict() == verdict_to_dict(verdict)


# ---------------------------------------------------------------------------
# Tie breakers
# ---------------------------------------------------------------------------
def test_tie_breaker_uses_freshness_then_fit() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"base": 5, "freshness": 3, "fit": 9}},
        {"offer_id": "b", "attrs": {"base": 5, "freshness": 8, "fit": 4}},
    ]
    verdict = compare_offers(offers, weights={"base": 1})
    assert verdict.ranking == ["b", "a"]
    assert verdict.tie_breaker_used is True


def test_tie_breaker_falls_back_to_fit_when_freshness_is_equal() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"base": 5, "freshness": 5, "fit": 4}},
        {"offer_id": "b", "attrs": {"base": 5, "freshness": 5, "fit": 9}},
    ]
    verdict = compare_offers(offers, weights={"base": 1})
    assert verdict.ranking == ["b", "a"]
    assert verdict.tie_breaker_used is True


def test_tie_breaker_handles_iso_dates() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"base": 5, "freshness": "2026-10-20"}},
        {"offer_id": "b", "attrs": {"base": 5, "freshness": "2026-10-24"}},
    ]
    verdict = compare_offers(offers, weights={"base": 1})
    assert verdict.ranking == ["b", "a"]
    assert verdict.tie_breaker_used is True


def test_tie_breaker_is_not_reported_without_equal_scores() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"base": 4, "freshness": 3}},
        {"offer_id": "b", "attrs": {"base": 5, "freshness": 9}},
    ]
    verdict = compare_offers(offers, weights={"base": 1})
    assert verdict.ranking == ["b", "a"]
    assert verdict.tie_breaker_used is False


def test_full_tie_keeps_input_order() -> None:
    offers = [
        {"offer_id": "first", "attrs": {"base": 5}},
        {"offer_id": "second", "attrs": {"base": 5}},
    ]
    verdict = compare_offers(offers, weights={"base": 1})
    assert verdict.ranking == ["first", "second"]
    assert verdict.tie_breaker_used is False


# ---------------------------------------------------------------------------
# Fixture synthétique
# ---------------------------------------------------------------------------
def test_fixture_is_synthetic_and_loads() -> None:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(data) >= 3
    offer_ids = [row["offer_id"] for row in data]
    assert len(set(offer_ids)) == len(offer_ids)
    verdict = compare_offers(data)
    assert sorted(verdict.ranking) == sorted(offer_ids)
    assert isinstance(verdict.tie_breaker_used, bool)
    # Les valeurs textuelles sont normalisées de façon déterministe.
    assert verdict.matrix["salary"]["offre_alpha"] == 42000
    assert verdict.matrix["salary"]["offre_beta"] == 48000
    assert verdict.matrix["salary"]["offre_delta"] is None
    assert verdict.matrix["freshness"]["offre_beta"] == "2026-10-24"


# ---------------------------------------------------------------------------
# REST (create_app)
# ---------------------------------------------------------------------------
def test_rest_smoke_uses_create_app(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
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
    assert body["matrix"]["score"] == {"a": 5, "b": 7}

    alias = client.post(
        "/api/career/offer-compare",
        json={"offers": [{"offer_id": "a", "attrs": {"x": 1}}], "weights": {"x": 1}},
    )
    assert alias.status_code == 200
    assert alias.json()["ranking"] == ["a"]


def test_rest_returns_json_safe_missing_values(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/career/offers/compare",
        json={
            "offers": [
                {"offer_id": "a", "attrs": {"salary": "42 000 €", "fit": 8}},
                {"offer_id": "b", "attrs": {"fit": 6}},
            ],
            "weights": {"salary": 1, "fit": 1},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matrix"]["salary"] == {"a": 42000, "b": None}
    assert body["weighted_scores"]["b"] == 6.0


def test_rest_empty_offers_are_supported(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/career/offers/compare", json={"offers": []})
    assert response.status_code == 200
    assert response.json() == {
        "matrix": {},
        "weighted_scores": {},
        "ranking": [],
        "tie_breaker_used": False,
    }


def test_rest_duplicate_offer_ids_are_rejected(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/career/offers/compare",
        json={
            "offers": [
                {"offer_id": "same", "attrs": {"x": 1}},
                {"offer_id": "same", "attrs": {"x": 2}},
            ]
        },
    )
    assert response.status_code == 400
    assert "dupliqué" in response.json()["detail"].casefold()


# ---------------------------------------------------------------------------
# Cas limites / adversarial
# ---------------------------------------------------------------------------
def test_empty_offers_are_supported() -> None:
    verdict = compare_offers([])
    assert verdict.matrix == {}
    assert verdict.weighted_scores == {}
    assert verdict.ranking == []
    assert verdict.tie_breaker_used is False


def test_adversarial_all_missing() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"x": None}},
        {"offer_id": "b", "attrs": {"x": None}},
    ]
    verdict = compare_offers(offers)
    assert verdict.weighted_scores["a"] == 0.0
    assert verdict.weighted_scores["b"] == 0.0
    assert verdict.tie_breaker_used is False
    assert verdict.ranking == ["a", "b"]


def test_adversarial_non_finite_and_blank_values_become_none() -> None:
    offers = [
        {
            "offer_id": "a",
            "attrs": {"score": float("nan"), "salary": float("inf"), "fit": "n/a", "misc": ""},
        },
        {"offer_id": "b", "attrs": {"score": 3, "salary": 100, "fit": 0}},
    ]
    verdict = compare_offers(offers)
    for attr in ("score", "salary", "fit", "misc"):
        assert verdict.matrix[attr]["a"] is None
    assert verdict.weighted_scores["a"] == 0.0
    assert verdict.ranking == ["b", "a"]


def test_adversarial_unknown_weight_names_produce_zero_scores() -> None:
    offers = [
        {"offer_id": "a", "attrs": {"salary": 10, "freshness": 1}},
        {"offer_id": "b", "attrs": {"salary": 20, "freshness": 9}},
    ]
    verdict = compare_offers(offers, weights={"does_not_exist": 1})
    assert verdict.weighted_scores == {"a": 0.0, "b": 0.0}
    assert verdict.ranking == ["b", "a"]
    assert verdict.tie_breaker_used is True


def test_adversarial_duplicate_offer_ids_are_rejected() -> None:
    with pytest.raises(ValueError):
        compare_offers([{"offer_id": "same", "attrs": {"x": 1}}, {"offer_id": "same", "attrs": {"x": 2}}])


def test_adversarial_non_mapping_offer_is_rejected() -> None:
    with pytest.raises(TypeError):
        compare_offers(["not-an-offer"])


def test_adversarial_string_is_not_a_sequence_of_offers() -> None:
    with pytest.raises(TypeError):
        compare_offers("offer")
