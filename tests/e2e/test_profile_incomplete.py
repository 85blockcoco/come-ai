import json
from pathlib import Path

from tests.e2e.utils import import_job, update_profile


def test_profile_incomplete(page, app):
    # Incomplete profile: no modeling evidence.
    update_profile(
        page,
        app,
        {
            "display_name": "Junior Candidate",
            "education": "BSc Finance",
            "experience": "Intern at Bank A.",
            "skills": "Excel",
            "languages": "French native",
        },
    )
    payload = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "offers" / "goldman_mna.json").read_text(
            encoding="utf-8"
        )
    )
    job_id = import_job(page, app, payload)

    before_response = page.request.get(app + f"/api/career/jobs/{job_id}/prep")
    assert before_response.ok
    before = before_response.json()
    before_pct = before["coverage"]["mandatory_pct"]
    assert before["gaps"]

    # Add proof (M&A experience) and re-analyze.
    update_profile(
        page,
        app,
        {
            "display_name": "Junior Candidate",
            "education": "BSc Finance",
            "experience": "Intern at Bank A. Valued two companies using DCF; financial modeling.",
            "skills": "Excel, financial modeling",
            "languages": "French native",
        },
    )

    after_response = page.request.get(app + f"/api/career/jobs/{job_id}/prep")
    assert after_response.ok
    after = after_response.json()
    assert after["coverage"]["mandatory_pct"] >= before_pct
    assert any(item.get("provenance") for item in after.get("gaps", [])) or after["coverage"]["mandatory_pct"] > before_pct