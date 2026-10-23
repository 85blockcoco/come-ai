"""SPEC-028 — administrative documents checklist for internships abroad."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from career.stage_admin_docs import (
    AdminChecklist,
    AdminItem,
    REQUIREMENTS_BY_COUNTRY,
    build_admin_checklist,
    completeness,
    normalize_country,
    render_recap,
    requirements_for_country,
)
from career.service import CareerService
from come_ai_web import create_app


def test_requirements_cover_france_plus_four_countries() -> None:
    assert list(REQUIREMENTS_BY_COUNTRY.keys()) == [
        "France",
        "United Kingdom",
        "Germany",
        "Netherlands",
        "Belgium",
    ]
    for country in ("France", "United Kingdom", "Germany", "Netherlands", "Belgium"):
        items = requirements_for_country(country)
        assert items
        assert all(isinstance(item, AdminItem) for item in items)
        assert any(item.required for item in items)


def test_alias_normalization() -> None:
    assert normalize_country("FR") == "France"
    assert normalize_country("uk") == "United Kingdom"
    assert normalize_country("DE") == "Germany"
    assert normalize_country("nl") == "Netherlands"
    assert normalize_country("BE") == "Belgium"
    assert requirements_for_country("fr") == requirements_for_country("France")


def test_build_checklist_defaults_to_missing() -> None:
    checklist = build_admin_checklist("France")
    assert isinstance(checklist, AdminChecklist)
    assert checklist.country == "France"
    assert checklist.items
    assert all(item.status == "missing" for item in checklist.items)
    assert checklist.blocking_missing


def test_status_updates_and_blocking() -> None:
    checklist = build_admin_checklist("France", statuses={"convention": "ok", "insurance": "in_progress"})
    item = checklist.get("convention")
    assert item is not None
    assert item.status == "ok"
    insurance = checklist.get("insurance")
    assert insurance is not None
    assert insurance.status == "in_progress"
    assert "insurance" in checklist.blocking_missing
    assert "convention" not in checklist.blocking_missing


def test_proof_refs() -> None:
    checklist = build_admin_checklist(
        "France",
        statuses={"convention": "ok"},
        proof_refs={"convention": ["file-123"]},
    )
    item = checklist.get("convention")
    assert item is not None
    assert item.proof_refs == ["file-123"]


def test_set_status_method() -> None:
    checklist = build_admin_checklist("France")
    updated = checklist.set_status("convention", "ok", proof_refs=["ev-1"])
    assert updated.status == "ok"
    assert updated.proof_refs == ["ev-1"]
    assert "convention" not in checklist.blocking_missing


def test_invalid_status_raises() -> None:
    try:
        AdminItem(key="x", label_fr="x", required=True, status="nope")  # type: ignore[arg-type]
    except ValueError:
        return
    raise AssertionError("invalid status should raise")


def test_completeness_empty() -> None:
    empty = AdminChecklist(country="France", items=[], blocking_missing=[])
    result = completeness(empty)
    assert result["total"] == 0
    assert result["percent"] == 100.0
    assert result["blocking_count"] == 0


def test_completeness_all_ok() -> None:
    checklist = build_admin_checklist("France", statuses={item.key: "ok" for item in requirements_for_country("France")})
    result = completeness(checklist)
    assert result["done"] == result["total"]
    assert result["percent"] == 100.0
    assert result["blocking_count"] == 0
    assert result == 100


def test_not_applicable_counts_as_done() -> None:
    checklist = build_admin_checklist("France")
    checklist.set_status("photo", "not_applicable")
    result = completeness(checklist)
    photo = next(item for item in result["status_counts"].items() if item[0] == "not_applicable")
    assert photo[1] == 1


def test_completeness_method_and_property() -> None:
    checklist = build_admin_checklist("France")
    assert checklist.completeness()["total"] == len(checklist.items)
    assert isinstance(checklist.completeness_percent, (int, float))


def test_render_recap_contains_country() -> None:
    checklist = build_admin_checklist("United Kingdom")
    markdown = render_recap(checklist)
    assert "United Kingdom" in markdown
    assert "Complétion" in markdown
    text = render_recap(checklist, format="text")
    assert "United Kingdom" in text


def test_to_dict_roundtrip() -> None:
    checklist = build_admin_checklist("Germany")
    data = checklist.to_dict()
    assert data["country"] == "Germany"
    assert isinstance(data["items"], list)
    assert "blocking_missing" in data


def test_http_smoke(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    app = create_app(base_dir=tmp_path, career_override=service)
    with TestClient(app) as client:
        response = client.get("/api/career/admin-docs/checklist", params={"country": "FR"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["country"] == "France"
        assert payload["checklist"]["items"]
        assert "completeness" in payload

        post = client.post(
            "/api/career/stage-admin-docs/checklist",
            json={"country": "UK", "statuses": {"passport": "ok"}, "proof_refs": {"passport": ["p-1"]}},
        )
        assert post.status_code == 200
        post_payload = post.json()
        assert post_payload["country"] == "United Kingdom"
        passport = next(item for item in post_payload["checklist"]["items"] if item["key"] == "passport")
        assert passport["status"] == "ok"
        assert passport["proof_refs"] == ["p-1"]

        req = client.get("/api/career/stage-admin-docs/requirements", params={"country": "BE"})
        assert req.status_code == 200
        assert req.json()["country"] == "Belgium"

        root = client.get("/api/career/stage-admin-docs", params={"country": "Netherlands"})
        assert root.status_code == 200
        assert root.json()["country"] == "Netherlands"


def test_adversarial_unknown_country_fallback() -> None:
    checklist = build_admin_checklist("Atlantis")
    assert checklist.country == "Atlantis"
    # Fallback to France requirements for unknown countries.
    assert len(checklist.items) == len(requirements_for_country("France"))


def test_adversarial_status_method_unknown_key() -> None:
    checklist = build_admin_checklist("France")
    try:
        checklist.set_status("does-not-exist", "ok")
    except KeyError:
        return
    raise AssertionError("unknown key should raise KeyError")


def test_create_app_still_works() -> None:
    # Ensure schema_version / app construction is not broken.
    import come_ai_web

    assert hasattr(come_ai_web, "create_app")


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "admin_docs_synthetic.json"


def test_synthetic_fixture_scenarios() -> None:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert "synthetic" in data["label"].lower()
    countries = data["countries"]
    # FR + the 4 countries already covered by the international connectors.
    assert set(countries) >= {"France", "United Kingdom", "Germany", "Netherlands", "Belgium"}
    for country, scenario in countries.items():
        checklist = build_admin_checklist(
            country,
            statuses=scenario["statuses"],
            proof_refs=scenario["proof_refs"],
        )
        result = completeness(checklist)
        assert result["percent"] == scenario["expected_percent"], country
        assert result["required_percent"] == scenario["expected_required_percent"], country
        assert result["blocking_missing"] == scenario["expected_blocking"], country
        for item in checklist.items:
            if item.key in scenario["proof_refs"]:
                refs = scenario["proof_refs"][item.key]
                assert item.proof_refs == refs, (country, item.key)
                # Synthetic-only: every proof reference is tagged as synthetic.
                assert all(ref.startswith("syn-") for ref in refs), (country, item.key)
