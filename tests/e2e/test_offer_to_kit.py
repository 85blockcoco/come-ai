import json
from pathlib import Path

from tests.e2e.utils import import_job, update_profile


def test_offer_to_kit(page, app):
    update_profile(
        page,
        app,
        {
            "display_name": "Candidate Test",
            "education": "MSc Finance",
            "experience": "2023 | Analyst | SMBC — Valued two companies using DCF.",
            "skills": "Excel, financial modeling, valuation",
            "languages": "French native; English C1",
        },
    )
    payload = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "offers" / "goldman_mna.json").read_text(
            encoding="utf-8"
        )
    )
    job_id = import_job(page, app, payload)

    page.goto(app + "/career")
    page.wait_for_load_state("networkidle")
    assert "Career" in page.title()

    prep_response = page.request.get(app + f"/api/career/jobs/{job_id}/prep")
    assert prep_response.ok
    prep = prep_response.json()
    assert prep["recommended_variant"]
    assert "variant_coverage" in prep

    kit_response = page.request.post(
        app + "/api/career/application-kits",
        data={"job_id": job_id, "language": "en", "variant": "markets"},
    )
    assert kit_response.ok
    kit = kit_response.json()
    assert kit["variant"] == "markets"
    assert kit.get("automatic_submission") is False
    for artifact_path in kit["artifacts"].values():
        assert Path(artifact_path).exists()

    applications_response = page.request.get(app + "/api/career/applications")
    assert applications_response.ok
    applications = applications_response.json().get("applications", [])
    assert any(str(item.get("job_id")) == str(job_id) for item in applications)