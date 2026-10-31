"""Shared helpers for the Career browser E2E suite."""

from __future__ import annotations

from typing import Any


SYNTHETIC_PROFILE = {
    "display_name": "Candidate Test",
    "contact_email": "candidate@example.test",
    "education": "MSc Finance — graduation December 2026",
    "experience": (
        "2023 | Analyst | SMBC — Automated 500+ files, reducing time by 80%.\n"
        "2022 | Intern | Bank A — Reviewed 120 reports, improving quality by 30%.\n"
    ),
    "skills": "Excel, Python, financial modeling, valuation",
    "languages": "French native; English C1",
    "eligibility": "compatible",
}

INCOMPLETE_PROFILE = {
    "display_name": "Candidate Test",
    "education": "MSc Finance — graduation December 2026",
    "experience": "",
    "skills": "",
    "languages": "French native; English C1",
    "eligibility": "compatible",
}

NO_MODELING_PROFILE = {
    "display_name": "Candidate Test",
    "education": "MSc Finance — graduation December 2026",
    "experience": "2023 | Analyst | SMBC — Reviewed 120 reports.",
    "skills": "Excel, valuation",
    "languages": "French native; English C1",
    "eligibility": "compatible",
}

SYNTHETIC_JOB = {
    "company": "Synthetic Bank",
    "title": "M&A Internship",
    "official_url": "https://careers.example.test/targeted-kit",
    "job_family": "M&A / Investment Banking",
    "requirements": "Financial modeling, valuation and deal rationale required.",
    "source_status": "open",
}

MODELING_JOB = {
    "company": "Synthetic Bank",
    "title": "M&A Internship",
    "official_url": "https://careers.example.test/modeling",
    "job_family": "M&A / Investment Banking",
    "requirements": "Financial modeling required.",
    "source_status": "open",
}


async def setup_profile(page, app: str, profile: dict[str, Any]) -> None:
    response = await page.request.put(f"{app}/api/career/profile", data=profile)
    assert response.ok, await response.text()


async def import_job(page, app: str, job: dict[str, Any]) -> str:
    response = await page.request.post(f"{app}/api/career/jobs/import", data=job)
    assert response.ok, await response.text()
    payload = await response.json()
    job_id = payload.get("id")
    if job_id is None and isinstance(payload.get("job"), dict):
        job_id = payload["job"].get("id")
    assert job_id, payload
    return str(job_id)


async def create_application(page, app: str, job_id: str) -> str:
    response = await page.request.post(
        f"{app}/api/career/applications", data={"job_id": job_id}
    )
    assert response.ok, await response.text()
    payload = await response.json()
    application_id = payload.get("id")
    if application_id is None and isinstance(payload.get("application"), dict):
        application_id = payload["application"].get("id")
    assert application_id, payload
    return str(application_id)
"""