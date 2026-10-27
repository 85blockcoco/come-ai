"""The human review opens a verified site; it never submits to that site."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.offer_qualification import qualify_offer
from career.service import CareerService
from come_ai_web import create_app


class FakeAgent:
    def provider_status(self):
        return {"provider": "synthetic", "available": False}


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COME_AI_MEMORY_DIR", str(tmp_path / "memory_data"))
    service = CareerService(tmp_path, curated_sources=())
    service.update_profile({
        "display_name": "Demo Synthetic", "contact_email": "demo@example.test",
        "education": "MSc Finance (synthetic)", "experience": "Synthetic finance project",
        "skills": "Excel", "languages": "English (synthetic)", "eligibility": "compatible",
    })
    for answer in ("Finance internship", "United Kingdom", "Synthetic finance team", "Financial analysis", "Excel", "Six months in 2027"):
        service.answer_intake(answer)
    job = {
        "company": "Lincoln International", "title": "SYNTHETIC ONLY — Finance Internship",
        "source_name": "greenhouse", "source_id": "synthetic-manual-destination",
        "official_url": "https://job-boards.greenhouse.io/lincolninternational/jobs/000000",
        "job_family": "Corporate Finance", "city": "London", "country": "United Kingdom",
        "posted_date": date.today().isoformat(), "deadline_date": (date.today() + timedelta(days=14)).isoformat(),
        "start_date": "2027-01-04", "end_date": "2027-07-04", "duration_months": 6,
        "employment_type": "Internship", "source_status": "open", "requirements": "Excel",
        "description_original": "Synthetic test only. Excel internship.", "source_verified": True,
    }
    job["qualification"] = qualify_offer(job).to_dict()
    imported = service.import_job(job)
    with TestClient(create_app(tmp_path, agent_override=FakeAgent(), career_override=service)) as client:
        kit = client.post(f"/api/career/apply-kit/{imported['id']}", json={"language": "en"}).json()
        assert kit["readiness"] == 100, kit["block_reasons"]
        yield client, service, imported, kit


def form_fields(kit):
    return {"approved": "true", "draft_id": kit["draft_id"], "review_token": kit["review_token"]}


def destination_url(kit):
    return f"/api/career/applications/{kit['application']['id']}/manual-destination"


def test_review_opens_only_verified_destination_without_submitting(prepared):
    client, service, job, kit = prepared
    response = client.post(destination_url(kit), data=form_fields(kit), follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == job["official_url"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert service.get_application(kit["application"]["id"])["stage"] == "approved_for_manual_submission"
    assert service.apply_tracker()["items"] == []


def test_review_cannot_override_the_destination(prepared):
    client, service, job, kit = prepared
    response = client.post(destination_url(kit), data={**form_fields(kit), "url": "https://attacker.example.test"}, follow_redirects=False)
    assert response.status_code == 422
    assert "location" not in response.headers
    assert service.get_application(kit["application"]["id"])["approval_granted"] is False


def test_review_refuses_a_changed_document(prepared):
    client, service, job, kit = prepared
    service.update_application_draft(kit["draft_id"], "Changed synthetic CV", "Changed synthetic letter")
    response = client.post(destination_url(kit), data=form_fields(kit), follow_redirects=False)
    assert response.status_code == 400
    assert "dossier" in response.text
    assert "location" not in response.headers
    assert service.get_application(kit["application"]["id"])["approval_granted"] is False


def test_unverified_offer_cannot_open_a_manual_destination(prepared):
    client, service, job, kit = prepared
    unverified = service.import_job({"company": "Synthetic Unknown", "title": "Synthetic Internship", "official_url": "https://careers.example.test/unknown"})
    blocked = client.post(f"/api/career/apply-kit/{unverified['id']}", json={"language": "en"}).json()
    response = client.post(destination_url(blocked), data=form_fields(blocked), follow_redirects=False)
    assert response.status_code == 400
    assert "location" not in response.headers
    assert service.get_application(blocked["application"]["id"])["approval_granted"] is False


def test_manual_destination_rejects_cross_origin_and_missing_approval(prepared):
    client, service, job, kit = prepared
    assert client.post(destination_url(kit), data=form_fields(kit), headers={"Origin": "https://attacker.example.test"}, follow_redirects=False).status_code == 403
    assert client.post(destination_url(kit), data={**form_fields(kit), "approved": "false"}, follow_redirects=False).status_code == 422
    assert service.get_application(kit["application"]["id"])["approval_granted"] is False


def test_fetch_review_returns_destination_without_cross_origin_redirect(prepared):
    client, service, job, kit = prepared
    response = client.post(destination_url(kit), data=form_fields(kit), headers={"Accept": "application/json", "Origin": "http://testserver"}, follow_redirects=False)
    assert response.status_code == 200
    assert response.json() == {"destination": job["official_url"]}
    assert "location" not in response.headers
    assert response.headers["referrer-policy"] == "no-referrer"
    assert service.get_application(kit["application"]["id"])["approval_granted"] is True
    assert service.apply_tracker()["items"] == []
