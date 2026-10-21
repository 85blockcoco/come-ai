from pathlib import Path

from career.cv_quality import analyze_cv
from career.cv_quality.parser import extract_text_from_file
from career.service import CareerService


def _setup(service: CareerService) -> dict:
    service.update_profile(
        {
            "display_name": "Candidate Test",
            "education": "MSc Finance — graduation December 2026",
            "experience": (
                "2023 | Analyst | SMBC — Automated 500+ files, reducing time by 80%.\n"
                "2022 | Intern | Bank A — Reviewed 120 reports, improving quality by 30%.\n"
                "2021 | Assistant | Bank B — Processed 90 cases in 6 months.\n"
                "2020 | Treasurer | Society — Managed EUR 20k budget for 12 months."
            ),
            "skills": "Excel, Python, financial modeling, valuation",
            "languages": "French native; English C1",
            "eligibility": "compatible",
        }
    )
    return service.import_job(
        {
            "company": "Synthetic Bank",
            "title": "M&A Internship",
            "official_url": "https://careers.example.test/targeted-kit",
            "job_family": "M&A / Investment Banking",
            "requirements": "Financial modeling, valuation and deal rationale required.",
            "source_status": "open",
        }
    )


def test_targeted_kit_is_persisted_per_variant_and_idempotent(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    job = _setup(service)

    first = service.create_application_kit(job["id"], "en", "m_a")
    first_bytes = {name: Path(path).read_bytes() for name, path in first["artifacts"].items()}
    second = service.create_application_kit(job["id"], "en", "m_a")
    markets = service.create_application_kit(job["id"], "en", "markets")

    assert second["created_draft"] is False
    assert second["draft"]["id"] == first["draft"]["id"]
    assert {name: Path(path).read_bytes() for name, path in second["artifacts"].items()} == first_bytes
    assert markets["draft"]["variant"] == "markets"
    assert markets["draft"]["id"] != first["draft"]["id"]
    assert len(service.list_application_drafts()) == 2
    assert first["automatic_submission"] is False
    assert first["provenance_map"]


def test_generated_cv_round_trips_through_local_ats_parser(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    job = _setup(service)
    kit = service.create_application_kit(job["id"], "en", "m_a")

    analysis = analyze_cv(extract_text_from_file(Path(kit["artifacts"]["cv"])))
    codes = {finding.code for finding in analysis.findings}
    assert "TABLE_DETECTED" not in codes
    assert "MISSING_SECTION" not in codes
    assert len(analysis.experiences) >= 4
    assert sum(item.has_quantified_result for item in analysis.experiences) / len(
        analysis.experiences
    ) >= 0.8


def test_generated_markets_cv_keeps_quant_sections_and_ats_safety(
    tmp_path: Path,
) -> None:
    service = CareerService(tmp_path, curated_sources=())
    job = _setup(service)
    kit = service.create_application_kit(job["id"], "en", "markets")
    document = extract_text_from_file(Path(kit["artifacts"]["cv"]))
    analysis = analyze_cv(document)
    codes = {finding.code for finding in analysis.findings}
    assert "Technical Skills" in document.text
    assert "Quantitative Projects" in document.text
    assert "TABLE_DETECTED" not in codes
    assert "MISSING_SECTION" not in codes


def test_application_kit_http_accepts_variant(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from come_ai_web import create_app

    service = CareerService(tmp_path, curated_sources=())
    job = _setup(service)
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.post(
            "/api/career/application-kits",
            json={"job_id": job["id"], "language": "en", "variant": "markets"},
        )

    assert response.status_code == 200
    assert response.json()["variant"] == "markets"
    assert response.json()["draft"]["variant"] == "markets"
