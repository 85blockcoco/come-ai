"""Tests for the static ATS platform detection and human guide (SPEC-046).

All offers are synthetic, no network call is made, and no application is
submitted.  The suite covers every recognised platform, the honest generic
fallback, and the refusal of links that must never be rendered.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.ats_guide import (
    QUICK_ANSWER_FIELDS,
    ApplyGuide,
    UnsafeApplyURLError,
    detect_platform,
    human_apply_guide,
)
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


PLATFORM_URLS = {
    "greenhouse": "https://boards.greenhouse.io/synthetic/jobs/12345",
    "lever": "https://jobs.lever.co/synthetic/7f3c2a1e",
    "workday": "https://synthetic.wd1.myworkdayjobs.com/en-US/careers/job/Paris/Analyst_R-1",
    "smartrecruiters": "https://jobs.smartrecruiters.com/Synthetic/123-analyst",
    "recruitcrm": "https://synthetic.recruitcrm.io/jobs/12345",
    "breezy": "https://synthetic.breezy.hr/p/7f3c2a1e",
    "jobvite": "https://jobs.jobvite.com/synthetic/job/abc123",
    "ashby": "https://jobs.ashbyhq.com/synthetic/7f3c2a1e",
    "ripplematch": "https://ripplematch.com/jobs/7f3c2a1e",
}


def synthetic_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Banque de Démo",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "REF-DEMO-2027-014",
        "official_url": "https://careers.example.test/jobs/demo-42",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "source_status": "open",
        "requirements": "Modélisation financière.",
        "description_original": "Stage de démonstration, données synthétiques.",
    }
    payload.update(changes)
    return payload


def guide_client(service: CareerService) -> TestClient:
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


# --- Detection -------------------------------------------------------------


@pytest.mark.parametrize("platform,url", sorted(PLATFORM_URLS.items()))
def test_detects_platform_from_url(platform: str, url: str) -> None:
    assert detect_platform(url) == platform


def test_detects_platform_from_source_label_when_url_is_unknown_or_empty() -> None:
    assert detect_platform("https://careers.example.test/jobs/42", "Greenhouse") == "greenhouse"
    assert detect_platform("", "Workday / MyWorkdayJobs") == "workday"
    assert detect_platform("https://careers.example.test/jobs/42", "Recruit CRM") == "recruitcrm"


def test_unknown_and_custom_labels_stay_distinct() -> None:
    assert detect_platform("https://careers.example.test/jobs/42", "manual") is None
    assert detect_platform("https://careers.example.test/jobs/42") is None
    assert detect_platform("", "custom") == "custom"
    assert detect_platform("", "company site") == "custom"
    assert detect_platform("", "totally-unknown-board") is None


def test_a_lookalike_domain_is_not_recognised_as_greenhouse() -> None:
    assert detect_platform("https://boards.greenhouse.io.evil.test/jobs/1") is None
    assert detect_platform("https://evil-greenhouse.io/jobs/1") is None


# --- Guides ----------------------------------------------------------------


@pytest.mark.parametrize("platform,url", sorted(PLATFORM_URLS.items()))
def test_every_platform_gets_numbered_steps_and_quick_answer_fields(
    platform: str, url: str
) -> None:
    guide = human_apply_guide(synthetic_job(official_url=url))

    assert isinstance(guide, ApplyGuide)
    assert guide.platform == platform
    assert len(guide.steps) >= 3
    assert [step.title for step in guide.steps]
    assert guide.needs_account is (platform in {"workday", "jobvite", "ripplematch"})
    assert 5 <= guide.estimated_minutes <= 30
    assert all(set(step.fields) <= QUICK_ANSWER_FIELDS for step in guide.steps)
    assert any("cv_file" in step.fields for step in guide.steps)


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("greenhouse", "https://boards.greenhouse.io/synthetic/jobs/12345#app"),
        ("lever", "https://jobs.lever.co/synthetic/7f3c2a1e/apply"),
        (
            "workday",
            "https://synthetic.wd1.myworkdayjobs.com/en-US/careers/job/Paris/Analyst_R-1/apply",
        ),
        (
            "smartrecruiters",
            "https://jobs.smartrecruiters.com/Synthetic/123-analyst?oga=true",
        ),
        ("recruitcrm", "https://synthetic.recruitcrm.io/jobs/12345/apply"),
        ("breezy", "https://synthetic.breezy.hr/p/7f3c2a1e/apply"),
        ("jobvite", "https://jobs.jobvite.com/synthetic/job/abc123/apply"),
        ("ashby", "https://jobs.ashbyhq.com/synthetic/7f3c2a1e/application"),
        ("ripplematch", "https://ripplematch.com/jobs/7f3c2a1e"),
    ],
)
def test_direct_apply_url_uses_the_platform_pattern(platform: str, expected: str) -> None:
    guide = human_apply_guide(synthetic_job(official_url=PLATFORM_URLS[platform]))

    assert guide.apply_url == expected


def test_unknown_public_url_gets_an_honest_generic_guide() -> None:
    url = "https://careers.example.test/jobs/demo-42"
    guide = human_apply_guide(synthetic_job(official_url=url))

    assert guide.platform is None
    assert guide.apply_url == url
    assert guide.needs_account is True
    assert len(guide.steps) >= 4
    assert any("non reconnue" in step.tips for step in guide.steps)
    assert any("Aucune candidature n’est soumise" in step.tips for step in guide.steps)


def test_known_source_without_url_still_explains_what_is_missing() -> None:
    guide = human_apply_guide(synthetic_job(official_url="", source_name="greenhouse"))

    assert guide.platform == "greenhouse"
    assert guide.apply_url == ""
    assert guide.steps[0].title == "Retrouver le lien officiel"


# --- Adversarial URL refusal ----------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "https://user:pass@boards.greenhouse.io/synthetic/jobs/1",
        "http://127.0.0.1/jobs/1",
        "http://localhost/jobs/1",
        "http://169.254.169.254/latest/meta-data",
        "http://intranet/jobs/1",
        "https://boards.greenhouse.io@evil.test/jobs/1",
        "https://boards.greenhouse.io:8080/synthetic/jobs/1",
        "https://boards.greenhouse.io/synthetic/jobs/1\r\nX-Injected: yes",
        "https://boards.greenhouse.io/synthetic/jobs/%0d%0aX-Injected",
        "https://boards.greenhouse.io/<script>/jobs/1",
        "https://boards.greenhouse.io/synthetic/jobs/1|calc",
    ],
)
def test_suspicious_or_internal_urls_are_refused(url: str) -> None:
    with pytest.raises(UnsafeApplyURLError):
        human_apply_guide(synthetic_job(official_url=url))


# --- HTTP endpoint ---------------------------------------------------------


def test_ats_guide_endpoint_returns_the_platform_guide(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(
        synthetic_job(official_url=PLATFORM_URLS["greenhouse"], source_name="manual")
    )
    client = guide_client(service)

    response = client.get(f"/api/career/ats-guide/{job['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["platform"] == "greenhouse"
    assert payload["apply_url"].endswith("#app")
    assert payload["needs_account"] is False
    assert payload["estimated_minutes"] == 12
    assert payload["steps"][0]["title"] == "Importer le CV"
    assert "cv_file" in payload["steps"][0]["fields"]


def test_ats_guide_endpoint_refuses_an_internal_link_cleanly(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(
        synthetic_job(official_url="http://127.0.0.1/jobs/1", source_name="manual")
    )
    client = guide_client(service)

    response = client.get(f"/api/career/ats-guide/{job['id']}")

    assert response.status_code == 400
    assert "adresse IP" in response.json()["detail"]


def test_ats_guide_endpoint_returns_400_for_an_unknown_job(tmp_path: Path) -> None:
    client = guide_client(CareerService(tmp_path))

    response = client.get("/api/career/ats-guide/does-not-exist")

    assert response.status_code == 400


def test_module_contains_no_network_or_submission_code() -> None:
    source = Path("career/ats_guide.py").read_text(encoding="utf-8")

    for forbidden in ("requests.", "httpx.", "urllib.request", "urlopen", "socket.", "webbrowser."):
        assert forbidden not in source
    assert "submit_application" not in source
