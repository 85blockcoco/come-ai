"""Application Sprint: deterministic prioritisation, never automatic submission."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from career.application_sprint import build_application_sprint
from career.service import CareerService
from come_ai_web import create_app


def _match(identifier: str, status: str, score: int, company: str = "Banque Démo") -> dict:
    return {
        "job": {
            "id": identifier,
            "company": company,
            "title": "Finance Internship",
            "city": "London",
            "country": "United Kingdom",
            "official_url": f"https://careers.example.test/{identifier}",
            "language": "en",
            "source_status": "open",
        },
        "stage_match": {"score": score, "qualification_status": status},
        "qualification": {"target_status": status, "missing_fields": []},
    }


def _prep(identifier: str, *, supported: int = 2, missing: tuple[str, ...] = ()) -> dict:
    total = supported + len(missing)
    return {
        "job": {"id": identifier},
        "cv_coverage": {
            "requirements_total": total,
            "supported": supported,
            "to_verify": len(missing),
            "coverage_percent": round(supported / total * 100) if total else 0,
            "target_language": "en",
        },
        "cv_action_plan": [
            {
                "status": "needs_evidence",
                "requirement": requirement,
                "missing_keywords": [requirement.casefold()],
                "suggested_change": "Ne pas ajouter sans preuve.",
            }
            for requirement in missing
        ],
        "matched_elements": [
            {"matched_on": ["excel"], "evidence": "Advanced Excel"}
            for _ in range(supported)
        ],
        "unverified_elements": [
            {"requirement": requirement, "note": "Non trouvé dans ton profil."}
            for requirement in missing
        ],
        "uncertainty": [],
    }


def test_sprint_orders_conforming_before_to_verify_and_excludes_non_conforming() -> None:
    matches = [
        _match("verify", "to_verify", 99),
        _match("good", "conforming", 80),
        _match("bad", "non_conforming", 100),
    ]
    payload = build_application_sprint(
        matches,
        {item["job"]["id"]: _prep(item["job"]["id"]) for item in matches},
        [],
    )
    assert [item["job_id"] for item in payload["queue"]] == ["good", "verify"]
    assert payload["queue"][0]["readiness"] == "prepare_now"
    assert payload["queue"][1]["readiness"] == "offer_to_verify"
    assert payload["stats"]["excluded_non_conforming"] == 1


def test_sprint_aggregates_recurring_cv_gaps_without_turning_them_into_skills() -> None:
    matches = [_match("one", "conforming", 90), _match("two", "conforming", 80)]
    payload = build_application_sprint(
        matches,
        {"one": _prep("one", missing=("Bloomberg",)), "two": _prep("two", missing=("Bloomberg",))},
        [],
    )
    priority = payload["cv_advice"]["priorities"][0]
    assert priority["keyword"] == "bloomberg"
    assert priority["offer_count"] == 2
    assert priority["status"] == "needs_evidence"
    assert "preuve" in priority["advice"].casefold()
    assert payload["queue"][0]["readiness"] == "profile_to_complete"


def test_sprint_ignores_employer_and_heading_boilerplate_in_global_cv_advice() -> None:
    match = _match("one", "conforming", 90)
    prep = _prep("one", supported=0, missing=("Who We Are", "Optiver is a leading trading firm"))
    payload = build_application_sprint([match], {"one": prep}, [])
    assert payload["cv_advice"]["priorities"] == []


def test_sprint_does_not_confuse_excellent_with_excel() -> None:
    match = _match("one", "conforming", 90)
    prep = _prep("one", supported=0, missing=("Excellent analytical skills",))
    payload = build_application_sprint([match], {"one": prep}, [])
    assert not any(item["keyword"] == "Excel" for item in payload["cv_advice"]["priorities"])


def test_sprint_uses_existing_job_score_when_brief_match_is_not_available() -> None:
    match = _match("one", "to_verify", 0)
    match["stage_match"] = None
    match["job"]["scoring"] = {"score": 73}
    payload = build_application_sprint([match], {"one": _prep("one")}, [])
    assert payload["queue"][0]["match_score"] == 73


def test_sprint_preserves_tracking_and_never_claims_submission() -> None:
    payload = build_application_sprint(
        [_match("tracked", "conforming", 88)],
        {"tracked": _prep("tracked")},
        [{"id": "app-1", "job_id": "tracked", "stage": "to_prepare"}],
    )
    item = payload["queue"][0]
    assert item["tracking"] == {"application_id": "app-1", "stage": "to_prepare"}
    assert item["submission_status"] == "manual_only_not_submitted"
    assert payload["automatic_submission"] is False


def test_application_sprint_http_uses_real_local_service_path(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    app = create_app(base_dir=tmp_path, career_override=service)
    with TestClient(app) as client:
        client.put(
            "/api/career/stage-search",
            json={
                "domains": ["M&A"],
                "cities": ["London"],
                "excluded_countries": ["France"],
                "excluded_cities": ["Paris"],
                "contract_types": ["stage"],
                "start_months": [1, 2, 3],
            },
        )
        imported = client.post(
            "/api/career/jobs/import",
            json={
                "company": "Banque Synthétique",
                "title": "M&A Internship",
                "official_url": "https://careers.example.test/mna-2027",
                "job_family": "M&A / Investment Banking",
                "city": "London",
                "country": "United Kingdom",
                "start_date": "2027-02-01",
                "end_date": "2027-08-01",
                "duration_months": 6,
                "employment_type": "Internship",
                "source_status": "open",
                "requirements": "Advanced Excel required. Bloomberg required.",
                "language": "en",
            },
        )
        assert imported.status_code == 201
        client.put("/api/career/profile", json={"skills": "Advanced Excel", "languages": "English C1"})
        response = client.get("/api/career/application-sprint?limit=10")
        assert response.status_code == 200
        payload = response.json()
        assert payload["queue"]
        assert payload["queue"][0]["company"] == "Banque Synthétique"
        assert payload["automatic_submission"] is False
        assert "probabilité" in payload["disclaimer"]


def test_application_sprint_ui_contract_is_present() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "career_static/index.html").read_text(encoding="utf-8")
    js = (root / "career_static/career.js").read_text(encoding="utf-8")
    assert 'id="stagehunter-sprint-build"' in html
    assert 'id="stagehunter-sprint"' in html
    assert "/api/career/application-sprint" in js
    assert "Créer le kit local" in js
    assert "startApplicationKitFlow(item.job_id" in js
    assert "Aucun envoi automatique" in html
