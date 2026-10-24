"""Tests for the deterministic administrative-document checklist (SPEC-028)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.stage_admin_docs import (
    AdminChecklist,
    AdminItem,
    REQUIREMENTS_BY_COUNTRY,
    build_checklist,
    completeness,
    get_requirements,
    update_item,
)
from fastapi.testclient import TestClient

from come_ai_web import create_app


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "admin_docs_synthetic.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_admin_item_defaults_and_to_dict():
    item = AdminItem(key="convention", label_fr="Convention", required=True)
    assert item.status == "missing"
    assert item.proof_refs == []
    assert item.to_dict()["key"] == "convention"


def test_admin_item_rejects_invalid_status():
    with pytest.raises(ValueError):
        AdminItem(key="x", label_fr="X", required=True, status="done")


def test_admin_checklist_recomputes_blocking_missing():
    items = [
        AdminItem(key="convention", label_fr="Convention", required=True, status="missing"),
        AdminItem(key="insurance", label_fr="Assurance", required=True, status="ok"),
        AdminItem(key="photo", label_fr="Photo", required=False, status="missing"),
    ]
    checklist = AdminChecklist(country="FR", items=items, blocking_missing=["stale"])
    assert checklist.blocking_missing == ["convention"]
    assert checklist.country == "FR"


def test_admin_checklist_completeness_empty_is_one():
    checklist = AdminChecklist(country="FR", items=[])
    assert checklist.completeness() == 1.0
    assert checklist.completeness_percent() == 100


def test_admin_checklist_completeness_mixed():
    items = [
        AdminItem(key="a", label_fr="A", required=True, status="ok"),
        AdminItem(key="b", label_fr="B", required=True, status="missing"),
        AdminItem(key="c", label_fr="C", required=False, status="not_applicable"),
    ]
    checklist = AdminChecklist(country="FR", items=items)
    assert checklist.completeness() == pytest.approx(2 / 3)


def test_requirements_include_fr_and_international_countries():
    assert "FR" in REQUIREMENTS_BY_COUNTRY
    assert len(REQUIREMENTS_BY_COUNTRY) >= 5
    for code in ("GB", "DE", "NL", "ES"):
        assert code in REQUIREMENTS_BY_COUNTRY


def test_fr_does_not_require_visa_or_work_permit():
    keys = {item["key"] for item in REQUIREMENTS_BY_COUNTRY["FR"]}
    assert "visa" not in keys
    assert "work_permit" not in keys
    assert "convention" in keys


def test_international_requires_visa_or_work_permit():
    items = REQUIREMENTS_BY_COUNTRY.get("GB", [])
    keys = {item["key"] for item in items}
    assert "visa" in keys or "work_permit" in keys


def test_get_requirements_unknown_falls_back_to_intl():
    items = get_requirements("ZZ")
    assert isinstance(items, list)
    assert len(items) > 0
    keys = {item["key"] for item in items}
    assert "visa" in keys


def test_build_checklist_applies_statuses():
    fx = load_fixture()
    checklist = build_checklist(fx["country"], statuses=fx["statuses"], proof_refs=fx["proof_refs"])
    by_key = {item.key: item for item in checklist.items}
    assert by_key["convention"].status == "ok"
    assert by_key["convention"].proof_refs == ["convention_signed.pdf"]
    assert by_key["insurance"].status == "missing"
    assert "insurance" in checklist.blocking_missing
    assert checklist.completeness() < 1.0


def test_build_checklist_country_alias():
    checklist = build_checklist("france")
    assert checklist.country == "FR"


def test_completeness_function_variants():
    items = [
        AdminItem(key="a", label_fr="A", required=True, status="ok"),
        AdminItem(key="b", label_fr="B", required=True, status="missing"),
    ]
    checklist = AdminChecklist(country="FR", items=items)
    assert completeness(checklist) == pytest.approx(0.5)
    assert completeness(items) == pytest.approx(0.5)
    assert completeness([{"status": "ok"}, {"status": "missing"}]) == pytest.approx(0.5)
    assert completeness({}) == 1.0
    assert completeness([]) == 1.0


def test_completeness_rejects_bad_status_via_build():
    fx = load_fixture()
    with pytest.raises(ValueError):
        build_checklist(fx["country"], statuses={"convention": fx["adversarial_bad_status"]})


def test_update_item_mutates_and_refreshes():
    checklist = build_checklist("FR")
    update_item(checklist, "insurance", status="ok", proof_refs=["attestation.pdf"])
    by_key = {item.key: item for item in checklist.items}
    assert by_key["insurance"].status == "ok"
    assert by_key["insurance"].proof_refs == ["attestation.pdf"]
    assert "insurance" not in checklist.blocking_missing


def test_update_item_invalid_status_raises():
    checklist = build_checklist("FR")
    with pytest.raises(ValueError):
        update_item(checklist, "insurance", status="done")


def test_unique_keys_per_country():
    for code, items in REQUIREMENTS_BY_COUNTRY.items():
        keys = [item["key"] for item in items]
        assert len(keys) == len(set(keys)), f"duplicate keys in {code}"


def test_admin_checklist_to_dict_shape():
    checklist = build_checklist("DE")
    data = checklist.to_dict()
    assert set(data.keys()) >= {"country", "items", "blocking_missing", "completeness", "completeness_percent"}
    assert isinstance(data["items"], list)
    assert all("key" in item for item in data["items"])


def test_smoke_http_endpoint(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.get("/api/career/stage-admin-docs/FR")
    assert response.status_code == 200
    body = response.json()
    assert body["country"] == "FR"
    assert isinstance(body["items"], list)
    assert len(body["items"]) > 0


def test_smoke_http_endpoint_post(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/career/stage-admin-docs",
        json={"country": "FR", "statuses": {"convention": "ok"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert any(item["key"] == "convention" and item["status"] == "ok" for item in body["items"])


def test_adversarial_unknown_country_http(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.get("/api/career/stage-admin-docs/ZZ")
    assert response.status_code == 200
    body = response.json()
    # Falls back to international requirements (visa present).
    keys = {item["key"] for item in body["items"]}
    assert "visa" in keys
