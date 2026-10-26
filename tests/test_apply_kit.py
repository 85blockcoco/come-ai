"""Tests for SPEC-044 one-click application kit."""

from __future__ import annotations

import tempfile
from pathlib import Path

from career.apply_kit import ApplyKit, build_apply_kit
from career.service import CareerService


def _profile(complete: bool = False) -> dict[str, str]:
    base = {
        "display_name": "Personne Démo",
        "education": "Master Finance (démo)",
        "experience": "Projet étudiant (démo)",
        "skills": "Excel, analyse financière",
        "languages": "Français, anglais C1",
        "eligibility": "compatible" if complete else "unknown",
    }
    if complete:
        base["contact_email"] = "demo@example.test"
    return base


def _job(service: CareerService) -> dict:
    return service.import_job(
        {
            "company": "Banque de Démo",
            "title": "Stagiaire M&A",
            "source_name": "manual",
            "job_family": "M&A / Investment Banking",
            "requirements": "Modélisation LBO avancée.",
            "official_url": "https://careers.example.test/jobs/demo-42",
            "deadline_date": "2027-02-01",
            "source_status": "open",
        }
    )


def test_apply_kit_complete() -> None:
    with tempfile.TemporaryDirectory() as td:
        service = CareerService(Path(td))
        service.update_profile(_profile(complete=True))
        job = _job(service)
        kit = build_apply_kit(job, service.get_profile())
        assert isinstance(kit, ApplyKit)
        assert kit.readiness == 100
        assert kit.block_reasons == []
        assert kit.variant is not None and kit.variant["id"]
        assert kit.letter is not None
        assert isinstance(kit.answers, dict)
        assert isinstance(kit.checklist, list) and kit.checklist
        assert isinstance(kit.export_urls, dict) and kit.export_urls
        assert kit.deep_link is None


def test_apply_kit_incomplete() -> None:
    with tempfile.TemporaryDirectory() as td:
        service = CareerService(Path(td))
        service.update_profile(_profile(complete=False))
        job = _job(service)
        kit = service.build_apply_kit(job["id"])
        assert kit["readiness"] < 100
        assert kit["block_reasons"]
        assert "Autorisation de travail non vérifiée" in kit["block_reasons"]


def test_apply_kit_unknown_job() -> None:
    with tempfile.TemporaryDirectory() as td:
        service = CareerService(Path(td))
        service.update_profile(_profile(complete=True))
        try:
            service.build_apply_kit("no-such-job")
        except Exception as exc:
            assert "n’existe pas" in str(exc) or "n'existe pas" in str(exc)
        else:
            raise AssertionError("expected error for unknown job")
