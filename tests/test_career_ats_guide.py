"""SPEC-046 — guide humain d'application et reconnaissance de plateforme ATS.

Toutes les offres sont synthétiques (``tests/fixtures/ats_guide_jobs_synthetic.json``).
Aucune requête réseau, aucune candidature envoyée, aucune donnée réelle.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from career.ats_guide import (
    FIELD_LABELS,
    PLATFORM_DOMAINS,
    ApplyGuide,
    GuideStep,
    detect_platform,
    human_apply_guide,
)
from career.service import CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError

FIXTURES = Path(__file__).parent / "fixtures" / "ats_guide_jobs_synthetic.json"
JOBS: dict[str, dict[str, Any]] = json.loads(FIXTURES.read_text(encoding="utf-8"))

OFFICIAL_URL_PLATFORMS = (
    "greenhouse",
    "lever",
    "workday",
    "smartrecruiters",
    "recruitcrm",
    "breezy",
    "jobvite",
    "ashby",
    "ripplematch",
)


class FakeAgent:
    def chat(self, message: str, **kwargs: Any) -> dict[str, Any]:  # pragma: no cover - unused here
        return {
            "answer": "",
            "provider": "offline",
            "model": "fake",
            "route_reason": "test",
            "tool_events": [],
            "citations": [],
            "usage": {},
            "latency_seconds": 0.0,
            "remote_model_used": False,
        }


def _client(tmp_path: Path) -> TestClient:
    career = CareerService(tmp_path)
    return TestClient(create_app(tmp_path, agent_override=FakeAgent(), career_override=career))


# ---------------------------------------------------------------------------
# Reconnaissance de plateforme
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("platform", OFFICIAL_URL_PLATFORMS)
def test_detects_platform_from_official_domain(platform: str) -> None:
    job = JOBS[platform]
    assert detect_platform(job["official_url"], job["source_name"]) == platform


def test_source_name_never_proves_an_unknown_platform() -> None:
    job = JOBS["source_only_greenhouse"]
    guide = human_apply_guide(job)
    assert guide.platform is None
    assert guide.apply_url == ""


def test_custom_source_returns_custom_platform() -> None:
    guide = human_apply_guide(JOBS["custom"])
    assert guide.platform == "custom"
    assert guide.needs_account is False
    assert guide.estimated_minutes == 15


def test_unknown_platform_is_honest_and_generic() -> None:
    guide = human_apply_guide(JOBS["unknown"])
    assert guide.platform is None
    assert guide.apply_url == ""
    assert guide.source_verified is False
    assert len(guide.steps) >= 4
    assert "générique" in guide.steps[0].tips.lower()
    assert "compte peut être nécessaire" in guide.steps[0].tips.lower()


def test_detection_is_deterministic_and_has_no_side_effect() -> None:
    job = JOBS["greenhouse"]
    first = human_apply_guide(job)
    second = human_apply_guide(dict(job))
    assert first == second


# ---------------------------------------------------------------------------
# URL directe du formulaire
# ---------------------------------------------------------------------------

def test_greenhouse_preserves_the_published_url_without_inventing_an_anchor() -> None:
    guide = human_apply_guide(JOBS["greenhouse"])
    assert guide.apply_url == JOBS["greenhouse"]["official_url"]


def test_lever_points_at_the_apply_path() -> None:
    guide = human_apply_guide(JOBS["lever"])
    assert guide.apply_url.endswith("/apply")
    assert guide.apply_url.startswith(JOBS["lever"]["official_url"].rstrip("/"))


def test_direct_links_are_published_instead_of_guessed() -> None:
    jobvite = human_apply_guide(JOBS["jobvite"])
    ashby = human_apply_guide(JOBS["ashby"])
    assert jobvite.apply_url == JOBS["jobvite"]["official_url"]
    assert ashby.apply_url.endswith("/application")


@pytest.mark.parametrize(
    "platform",
    ("workday", "smartrecruiters", "recruitcrm", "breezy", "ripplematch"),
)
def test_variable_tenants_keep_the_official_url(platform: str) -> None:
    job = JOBS[platform]
    assert human_apply_guide(job).apply_url == job["official_url"]


def test_workday_requires_an_account_and_more_time() -> None:
    guide = human_apply_guide(JOBS["workday"])
    assert guide.needs_account is True
    assert guide.estimated_minutes >= 20


# ---------------------------------------------------------------------------
# Contenu du guide
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("platform", (*OFFICIAL_URL_PLATFORMS, "custom"))
def test_every_platform_has_steps_estimates_and_mapped_fields(platform: str) -> None:
    guide = human_apply_guide(JOBS[platform])
    assert isinstance(guide, ApplyGuide)
    assert len(guide.steps) >= 4
    assert guide.estimated_minutes > 0
    assert all(isinstance(step, GuideStep) for step in guide.steps)
    for step in guide.steps:
        assert step.title.strip()
        assert step.fields
        assert step.tips.strip()
        for field in step.fields:
            assert field.startswith(("profile:", "document:", "quick_answer:", "question:", "review:"))
            if field.startswith("quick_answer:"):
                assert field in FIELD_LABELS
                # Clé stable SPEC-045, jamais un libellé traduit.
                assert field.split(":", 1)[1].islower()


def test_greenhouse_guide_covers_upload_screening_and_review() -> None:
    guide = human_apply_guide(JOBS["greenhouse"])
    steps = " ".join(step.title.lower() for step in guide.steps)
    fields = {field for step in guide.steps for field in step.fields}
    assert "cv" in steps and "envoyer" in steps
    assert "document:cv" in fields
    assert "quick_answer:work_authorization" in fields
    assert "question:screening" in fields
    assert "review:all" in fields


def test_platform_domains_are_non_overlapping_and_declared() -> None:
    assert set(PLATFORM_DOMAINS) == set(OFFICIAL_URL_PLATFORMS)
    for platform, domains in PLATFORM_DOMAINS.items():
        assert domains, platform
        for domain in domains:
            assert domain == domain.lower()
            assert "." in domain


# ---------------------------------------------------------------------------
# Refus propres
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "malicious",
    (
        "javascript:alert(document.cookie)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://greenhouse.io/jobs/1",
    ),
)
def test_rejects_non_http_schemes(malicious: str) -> None:
    with pytest.raises(UserFacingError, match="http"):
        detect_platform(malicious, "greenhouse")


def test_rejects_control_characters_and_newlines() -> None:
    for value in (
        "https://greenhouse.io/jobs/1\nHost: evil.test",
        "https://greenhouse.io/jobs/1\r\nX-Injected: 1",
        "https://greenhouse.io/jobs/1\x00",
        "https://greenhouse.io/jobs/1 with space",
    ):
        with pytest.raises(UserFacingError):
            detect_platform(value)


def test_rejects_credential_bearing_url() -> None:
    with pytest.raises(UserFacingError, match="mot de passe"):
        detect_platform("https://candidate:secret@greenhouse.io/jobs/1")


@pytest.mark.parametrize(
    "lookalike",
    (
        "https://greenhouse.io.evil-synthetic.test/jobs/1",
        "https://greenhouse-synthetic.example/jobs/1",
        "https://my-lever.example/jobs/1",
        "https://jobs.ashbyhq.example/jobs/1",
    ),
)
def test_rejects_platform_lookalike_domains(lookalike: str) -> None:
    with pytest.raises(UserFacingError, match="imite"):
        detect_platform(lookalike)


@pytest.mark.parametrize(
    "unsafe",
    (
        "https://127.0.0.1/jobs/1",
        "https://localhost/jobs/1",
        "https://greenhouse.io:8443/jobs/1",
        "https://greenhouse.io/jobs/1\\@evil.test",
    ),
)
def test_rejects_non_public_or_non_standard_hosts(unsafe: str) -> None:
    with pytest.raises(UserFacingError):
        detect_platform(unsafe)


def test_rejects_source_platform_mismatch() -> None:
    with pytest.raises(UserFacingError, match="ne correspond pas"):
        detect_platform(JOBS["lever"]["official_url"], "greenhouse")


def test_rejects_missing_url() -> None:
    with pytest.raises(UserFacingError, match="Aucun lien"):
        human_apply_guide({"source_name": "manual", "official_url": ""})


def test_guide_never_opens_a_network_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("aucune connexion réseau ne doit être tentée")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    for platform in (*OFFICIAL_URL_PLATFORMS, "custom", "unknown"):
        guide = human_apply_guide(JOBS[platform])
        assert guide.apply_url.startswith("https://") if platform != "unknown" else guide.apply_url == ""


def test_unverified_source_never_enables_a_destination() -> None:
    job = {**JOBS["lever"], "source_verified": False}
    guide = human_apply_guide(job)
    assert guide.platform == "lever"
    assert guide.apply_url == ""
    assert guide.source_verified is False
    assert guide.warnings


@pytest.mark.parametrize("url", [
    "http://jobs.lever.co/synthetic/offer",
    "https://jobs.lever.co/synthetic/offer\n",
    "https://jobs.lever.co/synthetic/offer%0a",
    "https://jobs.lever.co/synthetic/offer%250d",
    "https://careers.example.local/job",
    "https://jobs.lever.co/synthetic/offer?redirect=https://attacker.example.test",
])
def test_rejects_insecure_local_encoded_or_redirecting_links(url: str) -> None:
    with pytest.raises(UserFacingError):
        detect_platform(url)


@pytest.mark.parametrize("url", [
    "https://attacker.example.test/collect",
    "https://jobs.lever.co/another-employer/another-offer/apply",
])
def test_publisher_apply_link_cannot_switch_host_or_offer(url: str) -> None:
    job = {**JOBS["lever"], "source_material": {"material": {"source_fields": {"lever": {"applyUrl": url}}}}}
    assert human_apply_guide(job).apply_url == job["official_url"]


# ---------------------------------------------------------------------------
# Endpoint REST
# ---------------------------------------------------------------------------

def test_endpoint_returns_a_local_guide_and_never_submits(tmp_path: Path) -> None:
    client = _client(tmp_path)
    imported = client.post(
        "/api/career/jobs/import",
        json={
            "company": "Banque Synthétique",
            "title": "Stagiaire M&A",
            "source_name": "greenhouse",
            "source_id": "synthetic-2001",
            "official_url": "https://job-boards.greenhouse.io/banque-synthetique/jobs/4002001",
            "description_original": "Offre synthétique pour test local.",
        },
    )
    assert imported.status_code == 201, imported.text
    job = imported.json()

    response = client.get(f"/api/career/ats-guide/{job['id']}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["platform"] == "greenhouse"
    assert payload["apply_url"] == ""
    assert payload["source_verified"] is False
    assert payload["needs_account"] is False
    assert payload["estimated_minutes"] == 12
    assert len(payload["steps"]) >= 4
    assert payload["automated_submission"] is False
    assert payload["job_id"] == job["id"]


def test_endpoint_unknown_job_is_a_clean_user_error(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/career/ats-guide/job-does-not-exist")
    assert response.status_code == 400
    assert "n’existe pas" in response.json()["detail"]


def test_health_declares_the_local_ats_guide(tmp_path: Path) -> None:
    client = _client(tmp_path)
    health = client.get("/api/career/health")
    assert health.status_code == 200
    capability = health.json()["ats_guide"]
    assert capability["local_only"] is True
    assert capability["network_requests"] is False
    assert capability["automated_submission"] is False
    assert "greenhouse" in capability["platforms"]
