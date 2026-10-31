import json
from pathlib import Path

from tests.e2e.utils import import_job, update_profile


def test_no_auto_apply(page, app):
    external_requests = []

    def handler(route, request):
        url = request.url
        if not (url.startswith("http://127.0.0.1") or url.startswith("http://localhost")):
            external_requests.append(url)
        route.continue_()

    page.route("**/*", handler)

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

    kit_response = page.request.post(
        app + "/api/career/application-kits",
        data={"job_id": job_id, "language": "en", "variant": "m_a"},
    )
    assert kit_response.ok
    kit = kit_response.json()
    assert kit.get("automatic_submission") is False

    applications_response = page.request.get(app + "/api/career/applications")
    assert applications_response.ok
    applications = applications_response.json().get("applications", [])
    matching = [item for item in applications if str(item.get("job_id")) == str(job_id)]
    assert matching
    assert all(item.get("stage") != "submitted" for item in matching)

    # No external (non-consented) network calls should have been made.
    assert external_requests == [], external_requests